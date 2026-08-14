'use client';

import React, { useState, useEffect, useRef, useCallback } from 'react';
import { loadVADScripts, unlockAudioContext } from '../utils/voiceHelper';
import { AudioProcessor } from '../utils/audioProcessor';
import { AudioProcessorRobust } from '../utils/audioProcessorRobust';
import { toast } from 'sonner';

/**
 * Convert an array of PCM byte chunks (Uint8Array or ArrayBuffer containing 16-bit PCM @ 16kHz)
 * into a playable WAV Blob.
 */
function pcmChunksToWavBlob(chunks, sampleRate = 16000) {
  let totalBytes = 0;
  for (const c of chunks) {
    totalBytes += c.byteLength || c.length;
  }
  if (totalBytes === 0) return null;

  const merged = new Uint8Array(totalBytes);
  let offset = 0;
  for (const c of chunks) {
    const arr = c instanceof Uint8Array ? c : new Uint8Array(c);
    merged.set(arr, offset);
    offset += arr.byteLength;
  }

  const numSamples = Math.floor(totalBytes / 2);
  const buffer = new ArrayBuffer(44 + numSamples * 2);
  const view = new DataView(buffer);

  const writeString = (off, str) => {
    for (let i = 0; i < str.length; i++) {
      view.setUint8(off + i, str.charCodeAt(i));
    }
  };

  // RIFF Header
  writeString(0, 'RIFF');
  view.setUint32(4, 36 + numSamples * 2, true);
  writeString(8, 'WAVE');
  writeString(12, 'fmt ');
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true); // PCM format
  view.setUint16(22, 1, true); // Mono
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeString(36, 'data');
  view.setUint32(40, numSamples * 2, true);

  const pcmDest = new Uint8Array(buffer, 44);
  pcmDest.set(merged.subarray(0, numSamples * 2));

  return new Blob([view], { type: 'audio/wav' });
}

export default function StandaloneVoicePipelineLab() {
  const [vadLoaded, setVadLoaded] = useState(false);
  const [activePipeline, setActivePipeline] = useState('none'); // 'none', 'classic', 'robust', 'both'

  // === Dynamic Tuning Parameters (Robust Pipeline) ===
  const [tuningParams, setTuningParams] = useState({
    positiveSpeechThreshold: 0.75,
    negativeSpeechThreshold: 0.25,
    rmsHighThreshold: 0.015,
    rmsLowThreshold: 0.004,
    rmsWindowSize: 5,
    minNearFrames: 3,
    maxEvalFrames: 30,
    energyRedemptionFrames: 12,
    ambientNoiseThreshold: 0.008,
    speakCloserCooldownMs: 15000,
  });

  // Time window for graphs (seconds)
  const [timeWindowSec, setTimeWindowSec] = useState(10); // 5, 10, 20

  // === Classic Pipeline State ===
  const [classicIsSpeaking, setClassicIsSpeaking] = useState(false);
  const [classicVolume, setClassicVolume] = useState(0);
  const [classicAudioClips, setClassicAudioClips] = useState([]);
  const classicProcessorRef = useRef(null);
  const classicChunksRef = useRef([]);

  // === Robust Pipeline State ===
  const [robustIsSpeaking, setRobustIsSpeaking] = useState(false);
  const [robustVolume, setRobustVolume] = useState(0);
  const [robustAudioClips, setRobustAudioClips] = useState([]);
  const robustProcessorRef = useRef(null);
  const robustChunksRef = useRef([]);

  // === Real-time Diagnostics Matrix (Robust) ===
  const [currentDiag, setCurrentDiag] = useState({
    vadProbability: 0,
    rmsEnergy: 0,
    rmsDb: -60,
    rollingRms: 0,
    classification: 'SILENT',
    energyState: 'ENERGY_IDLE',
    ambientRms: 0,
    isStreaming: false,
  });

  // === Real-time Event Flags History ===
  const [eventFlags, setEventFlags] = useState([]);

  // === Time-Series Buffer for Graphs ===
  // Stores history: { t, vadProb, rms, rollingRms, ambientRms, classification, energyState, isStreaming, flag }
  const timeSeriesRef = useRef([]);

  // === Diagnostic Logs & Stats ===
  const [frameLogs, setFrameLogs] = useState([]);
  const [logFilter, setLogFilter] = useState('ALL');
  const [autoScrollLogs, setAutoScrollLogs] = useState(true);
  const logsContainerRef = useRef(null);

  const [stats, setStats] = useState({
    totalFrames: 0,
    silentFrames: 0,
    noiseFrames: 0,
    speechFarFrames: 0,
    speechNearFrames: 0,
    streamedChunks: 0,
    droppedChunks: 0,
  });

  // Canvas Refs
  const timelineCanvasRef = useRef(null);
  const animFrameIdRef = useRef(null);

  // === UX Alerts ===
  const [ambientAlert, setAmbientAlert] = useState(null);
  const [speakCloserAlert, setSpeakCloserAlert] = useState(null);

  // Initialize VAD scripts on mount
  useEffect(() => {
    loadVADScripts().then((loaded) => {
      setVadLoaded(loaded);
      if (loaded) {
        toast.success('Silero VAD WebAssembly ready (Client-Side Only)');
      } else {
        toast.error('Failed to load VAD libraries');
      }
    });

    return () => {
      stopAll();
      if (animFrameIdRef.current) cancelAnimationFrame(animFrameIdRef.current);
    };
  }, []);

  // Update Robust Config on Tuning Change
  useEffect(() => {
    if (robustProcessorRef.current) {
      robustProcessorRef.current.updateConfig(tuningParams);
    }
  }, [tuningParams]);

  // Auto-scroll log
  useEffect(() => {
    if (autoScrollLogs && logsContainerRef.current) {
      logsContainerRef.current.scrollTop = logsContainerRef.current.scrollHeight;
    }
  }, [frameLogs, autoScrollLogs]);

  // ==========================================
  // Multi-Track Synchronized Timeline Canvas
  // ==========================================
  useEffect(() => {
    const canvas = timelineCanvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const maxHistoryPoints = timeWindowSec * 32; // ~32 frames per second

    const render = () => {
      const w = canvas.width;
      const h = canvas.height;
      const history = timeSeriesRef.current;

      // Background
      ctx.fillStyle = '#070b14';
      ctx.fillRect(0, 0, w, h);

      // Sub-track layout definitions:
      // Track 1: RMS Energy Curve & Thresholds (top 0 to 110px)
      // Track 2: VAD Probability Curve (115 to 200px)
      // Track 3: Classification Ribbon (205 to 225px)
      // Track 4: Audio Gate & State Machine Ribbon (230 to 250px)

      const t1Top = 15;
      const t1H = 95;
      const t2Top = 125;
      const t2H = 80;
      const t3Top = 220;
      const t3H = 18;
      const t4Top = 246;
      const t4H = 18;

      // Draw Sub-track Backgrounds & Borders
      ctx.fillStyle = '#0d1527';
      ctx.fillRect(50, t1Top, w - 60, t1H);
      ctx.fillRect(50, t2Top, w - 60, t2H);
      ctx.fillRect(50, t3Top, w - 60, t3H);
      ctx.fillRect(50, t4Top, w - 60, t4H);

      ctx.strokeStyle = '#1e293b';
      ctx.lineWidth = 1;
      ctx.strokeRect(50, t1Top, w - 60, t1H);
      ctx.strokeRect(50, t2Top, w - 60, t2H);
      ctx.strokeRect(50, t3Top, w - 60, t3H);
      ctx.strokeRect(50, t4Top, w - 60, t4H);

      // Track Labels
      ctx.font = '10px Inter, monospace';
      ctx.fillStyle = '#38bdf8';
      ctx.fillText('ENERGY (RMS)', 5, t1Top + 20);
      ctx.fillText('& THRESH', 5, t1Top + 34);

      ctx.fillStyle = '#10b981';
      ctx.fillText('VAD PROB', 5, t2Top + 20);
      ctx.fillText('(0 - 100%)', 5, t2Top + 34);

      ctx.fillStyle = '#cbd5e1';
      ctx.fillText('CLASS', 5, t3Top + 13);
      ctx.fillText('GATE', 5, t4Top + 13);

      // ----------------------------------------------------
      // Track 1: RMS & Near-Field Floor
      // ----------------------------------------------------
      // Grid lines
      const maxRmsPlot = 0.040;
      const rmsY = (val) => t1Top + t1H - Math.min(t1H, (val / maxRmsPlot) * t1H);

      // Draw RMS High threshold line
      const highThreshY = rmsY(tuningParams.rmsHighThreshold);
      ctx.strokeStyle = 'rgba(56, 189, 248, 0.7)';
      ctx.setLineDash([4, 4]);
      ctx.beginPath();
      ctx.moveTo(50, highThreshY);
      ctx.lineTo(w - 10, highThreshY);
      ctx.stroke();

      // Draw Ambient Noise threshold line
      const ambientThreshY = rmsY(tuningParams.ambientNoiseThreshold);
      ctx.strokeStyle = 'rgba(239, 68, 68, 0.5)';
      ctx.beginPath();
      ctx.moveTo(50, ambientThreshY);
      ctx.lineTo(w - 10, ambientThreshY);
      ctx.stroke();
      ctx.setLineDash([]);

      ctx.fillStyle = 'rgba(56, 189, 248, 0.9)';
      ctx.fillText(`Floor: ${tuningParams.rmsHighThreshold.toFixed(3)}`, w - 100, highThreshY - 3);

      // ----------------------------------------------------
      // Track 2: VAD Probability Markers
      // ----------------------------------------------------
      const vadY = (val) => t2Top + t2H - Math.min(t2H, val * t2H);
      const posVadY = vadY(tuningParams.positiveSpeechThreshold);
      const negVadY = vadY(tuningParams.negativeSpeechThreshold);

      ctx.strokeStyle = 'rgba(16, 185, 129, 0.6)';
      ctx.setLineDash([3, 3]);
      ctx.beginPath();
      ctx.moveTo(50, posVadY);
      ctx.lineTo(w - 10, posVadY);
      ctx.stroke();

      ctx.strokeStyle = 'rgba(148, 163, 184, 0.4)';
      ctx.beginPath();
      ctx.moveTo(50, negVadY);
      ctx.lineTo(w - 10, negVadY);
      ctx.stroke();
      ctx.setLineDash([]);

      ctx.fillStyle = '#10b981';
      ctx.fillText(`Pos: ${(tuningParams.positiveSpeechThreshold * 100).toFixed(0)}%`, w - 95, posVadY - 3);
      ctx.fillStyle = '#94a3b8';
      ctx.fillText(`Neg: ${(tuningParams.negativeSpeechThreshold * 100).toFixed(0)}%`, w - 95, negVadY + 10);

      // ----------------------------------------------------
      // Draw Curves & Ribbons from History
      // ----------------------------------------------------
      if (history.length > 1) {
        const plotWidth = w - 60;
        const stepX = plotWidth / maxHistoryPoints;
        const startIndex = Math.max(0, history.length - maxHistoryPoints);
        const activeHistory = history.slice(startIndex);

        // 1. Draw Classification Ribbon (Track 3)
        for (let i = 0; i < activeHistory.length; i++) {
          const pt = activeHistory[i];
          const x = 50 + i * stepX;
          const barW = Math.max(1, stepX + 0.5);

          if (pt.classification === 'SPEECH_NEAR') ctx.fillStyle = '#10b981';
          else if (pt.classification === 'SPEECH_FAR') ctx.fillStyle = '#f59e0b';
          else if (pt.classification === 'NOISE_ONLY') ctx.fillStyle = '#ef4444';
          else ctx.fillStyle = '#1e293b';

          ctx.fillRect(x, t3Top, barW, t3H);
        }

        // 2. Draw Audio Gate & State Ribbon (Track 4)
        for (let i = 0; i < activeHistory.length; i++) {
          const pt = activeHistory[i];
          const x = 50 + i * stepX;
          const barW = Math.max(1, stepX + 0.5);

          if (pt.isStreaming) ctx.fillStyle = '#059669'; // Passed
          else if (pt.energyState === 'ENERGY_EVALUATING') ctx.fillStyle = '#6366f1'; // Evaluating
          else if (pt.energyState === 'ENERGY_FLAGGED_QUIET') ctx.fillStyle = '#d97706'; // Blocked Far
          else ctx.fillStyle = '#0f172a';

          ctx.fillRect(x, t4Top, barW, t4H);
        }

        // 3. Draw VAD Curve (Track 2)
        ctx.strokeStyle = '#34d399';
        ctx.lineWidth = 2;
        ctx.beginPath();
        for (let i = 0; i < activeHistory.length; i++) {
          const x = 50 + i * stepX;
          const y = vadY(activeHistory[i].vadProbability);
          if (i === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        }
        ctx.stroke();

        // 4. Draw RMS Energy Curve (Track 1)
        // Area under rolling RMS
        ctx.fillStyle = 'rgba(56, 189, 248, 0.15)';
        ctx.beginPath();
        ctx.moveTo(50, t1Top + t1H);
        for (let i = 0; i < activeHistory.length; i++) {
          const x = 50 + i * stepX;
          const y = rmsY(activeHistory[i].rollingRms);
          ctx.lineTo(x, y);
        }
        ctx.lineTo(50 + (activeHistory.length - 1) * stepX, t1Top + t1H);
        ctx.closePath();
        ctx.fill();

        // Rolling RMS Line
        ctx.strokeStyle = '#38bdf8';
        ctx.lineWidth = 2;
        ctx.beginPath();
        for (let i = 0; i < activeHistory.length; i++) {
          const x = 50 + i * stepX;
          const y = rmsY(activeHistory[i].rollingRms);
          if (i === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        }
        ctx.stroke();

        // Raw RMS instantaneous line (fainter)
        ctx.strokeStyle = 'rgba(129, 140, 248, 0.4)';
        ctx.lineWidth = 1;
        ctx.beginPath();
        for (let i = 0; i < activeHistory.length; i++) {
          const x = 50 + i * stepX;
          const y = rmsY(activeHistory[i].rmsEnergy);
          if (i === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        }
        ctx.stroke();

        // 5. Draw Event Pins / Flag Markers
        for (let i = 0; i < activeHistory.length; i++) {
          const pt = activeHistory[i];
          if (pt.flag) {
            const x = 50 + i * stepX;
            ctx.fillStyle = pt.flag === 'SPEAK_CLOSER' ? '#f59e0b' : '#ef4444';
            ctx.beginPath();
            ctx.arc(x, t1Top + 8, 4, 0, Math.PI * 2);
            ctx.fill();

            ctx.strokeStyle = ctx.fillStyle;
            ctx.lineWidth = 1;
            ctx.beginPath();
            ctx.moveTo(x, t1Top + 12);
            ctx.lineTo(x, t4Top + t4H);
            ctx.stroke();
          }
        }
      }

      animFrameIdRef.current = requestAnimationFrame(render);
    };

    render();

    return () => {
      if (animFrameIdRef.current) cancelAnimationFrame(animFrameIdRef.current);
    };
  }, [tuningParams, timeWindowSec]);

  // === Start Classic Pipeline (No WebSocket) ===
  const startClassic = async () => {
    unlockAudioContext();
    stopClassic();

    classicChunksRef.current = [];

    const processor = new AudioProcessor({
      positiveSpeechThreshold: tuningParams.positiveSpeechThreshold,
      negativeSpeechThreshold: tuningParams.negativeSpeechThreshold,
      onVolumeLevel: (vol) => setClassicVolume(vol),
      onSpeechStart: () => {
        setClassicIsSpeaking(true);
        classicChunksRef.current = [];
      },
      onAudioChunk: (chunk) => {
        classicChunksRef.current.push(chunk);
      },
      onSpeechEnd: () => {
        setClassicIsSpeaking(false);
        const pcmChunks = [...classicChunksRef.current];
        classicChunksRef.current = [];

        const blob = pcmChunksToWavBlob(pcmChunks, 16000);
        if (blob && blob.size > 100) {
          const url = URL.createObjectURL(blob);
          const durationSec = (pcmChunks.reduce((acc, c) => acc + (c.byteLength || c.length), 0) / 32000).toFixed(2);
          const clip = {
            id: Date.now(),
            time: new Date().toLocaleTimeString(),
            durationSec,
            url,
            sizeKb: (blob.size / 1024).toFixed(1),
          };
          setClassicAudioClips((prev) => [clip, ...prev.slice(0, 19)]);
          toast.success(`[Classic] Captured ${durationSec}s audio utterance`);
        }
      },
    });

    const ok = await processor.initialize();
    if (ok) {
      processor.start();
      classicProcessorRef.current = processor;
      setActivePipeline((prev) => (prev === 'robust' ? 'both' : 'classic'));
    } else {
      toast.error('Failed to start Classic AudioProcessor');
    }
  };

  const stopClassic = () => {
    if (classicProcessorRef.current) {
      classicProcessorRef.current.destroy();
      classicProcessorRef.current = null;
    }
    setClassicIsSpeaking(false);
    setClassicVolume(0);
    setActivePipeline((prev) => (prev === 'both' ? 'robust' : 'none'));
  };

  // === Start Robust Pipeline (No WebSocket) ===
  const startRobust = async () => {
    unlockAudioContext();
    stopRobust();

    robustChunksRef.current = [];

    const processor = new AudioProcessorRobust({
      ...tuningParams,
      onVolumeLevel: (vol) => setRobustVolume(vol),
      onSpeechStart: () => {
        setRobustIsSpeaking(true);
        robustChunksRef.current = [];
      },
      onAudioChunk: (chunk) => {
        robustChunksRef.current.push(chunk);
      },
      onSpeechEnd: () => {
        setRobustIsSpeaking(false);
        const pcmChunks = [...robustChunksRef.current];
        robustChunksRef.current = [];

        const blob = pcmChunksToWavBlob(pcmChunks, 16000);
        if (blob && blob.size > 100) {
          const url = URL.createObjectURL(blob);
          const durationSec = (pcmChunks.reduce((acc, c) => acc + (c.byteLength || c.length), 0) / 32000).toFixed(2);
          const clip = {
            id: Date.now(),
            time: new Date().toLocaleTimeString(),
            durationSec,
            url,
            sizeKb: (blob.size / 1024).toFixed(1),
          };
          setRobustAudioClips((prev) => [clip, ...prev.slice(0, 19)]);
          toast.success(`[Robust] Passed ${durationSec}s near-field speech`);
        }
      },
      onFrameClassified: (diag) => {
        setCurrentDiag(diag);

        // Check if there is an active flag
        let currentFlag = null;
        if (diag.energyState === 'ENERGY_FLAGGED_QUIET') currentFlag = 'SPEAK_CLOSER';

        // Add to Time-Series Graph History
        timeSeriesRef.current.push({
          t: Date.now(),
          vadProbability: diag.vadProbability,
          rmsEnergy: diag.rmsEnergy,
          rollingRms: diag.rollingRms,
          ambientRms: diag.ambientRms,
          classification: diag.classification,
          energyState: diag.energyState,
          isStreaming: diag.isStreaming,
          flag: currentFlag,
        });

        // Cap in-memory history to 1000 points (~30 seconds)
        if (timeSeriesRef.current.length > 1000) {
          timeSeriesRef.current.shift();
        }

        // Add to frame logs
        setFrameLogs((prev) => [
          ...prev.slice(-99),
          {
            id: Date.now() + Math.random(),
            time: new Date().toLocaleTimeString() + `.${(Date.now() % 1000).toString().padStart(3, '0')}`,
            ...diag,
          },
        ]);

        if (robustProcessorRef.current) {
          const st = robustProcessorRef.current.stats;
          if (st) setStats({ ...st });
        }
      },
      onSpeechTooQuiet: (data) => {
        setSpeakCloserAlert({
          message: '⚠️ Speech Too Quiet / Far-Field (Gated Out)',
          timestamp: Date.now(),
        });
        setEventFlags((prev) => [
          { id: Date.now(), time: new Date().toLocaleTimeString(), type: 'SPEAK_CLOSER', desc: `RMS ${data.rollingRms.toFixed(4)} < Floor ${data.threshold}` },
          ...prev.slice(0, 9),
        ]);
        toast.warning('⚠️ Speech too quiet / far away — audio gated out to prevent noise errors');
        setTimeout(() => setSpeakCloserAlert(null), 4000);
      },
      onHighBackgroundNoise: (data) => {
        if (data.active) {
          setAmbientAlert({
            message: `⚠️ High Ambient Noise Detected: RMS ${(data.ambientRms * 100).toFixed(2)}%`,
          });
          setEventFlags((prev) => [
            { id: Date.now(), time: new Date().toLocaleTimeString(), type: 'HIGH_AMBIENT_NOISE', desc: `Ambient RMS ${(data.ambientRms * 100).toFixed(2)}%` },
            ...prev.slice(0, 9),
          ]);
        } else {
          setAmbientAlert(null);
        }
      },
    });

    const ok = await processor.initialize();
    if (ok) {
      processor.start();
      robustProcessorRef.current = processor;
      setActivePipeline((prev) => (prev === 'classic' ? 'both' : 'robust'));
    } else {
      toast.error('Failed to start Robust AudioProcessor');
    }
  };

  const stopRobust = () => {
    if (robustProcessorRef.current) {
      robustProcessorRef.current.destroy();
      robustProcessorRef.current = null;
    }
    setRobustIsSpeaking(false);
    setRobustVolume(0);
    setCurrentDiag((prev) => ({ ...prev, classification: 'SILENT', isStreaming: false }));
    setActivePipeline((prev) => (prev === 'both' ? 'classic' : 'none'));
  };

  const startBoth = async () => {
    await startClassic();
    await startRobust();
  };

  const stopAll = () => {
    stopClassic();
    stopRobust();
    setActivePipeline('none');
  };

  const clearAllData = () => {
    setClassicAudioClips([]);
    setRobustAudioClips([]);
    setFrameLogs([]);
    setEventFlags([]);
    timeSeriesRef.current = [];
    if (robustProcessorRef.current) {
      robustProcessorRef.current.resetStats();
    }
    setStats({
      totalFrames: 0,
      silentFrames: 0,
      noiseFrames: 0,
      speechFarFrames: 0,
      speechNearFrames: 0,
      streamedChunks: 0,
      droppedChunks: 0,
    });
  };

  const getClassificationBadge = (cls) => {
    switch (cls) {
      case 'SPEECH_NEAR':
        return <span style={{ backgroundColor: '#059669', color: '#fff', padding: '3px 8px', borderRadius: 4, fontWeight: 700, fontSize: '0.78rem' }}>🟢 SPEECH_NEAR (Passed)</span>;
      case 'SPEECH_FAR':
        return <span style={{ backgroundColor: '#d97706', color: '#fff', padding: '3px 8px', borderRadius: 4, fontWeight: 700, fontSize: '0.78rem' }}>🟡 SPEECH_FAR (Gated)</span>;
      case 'NOISE_ONLY':
        return <span style={{ backgroundColor: '#dc2626', color: '#fff', padding: '3px 8px', borderRadius: 4, fontWeight: 700, fontSize: '0.78rem' }}>🔴 NOISE_ONLY (Dropped)</span>;
      default:
        return <span style={{ backgroundColor: '#475569', color: '#fff', padding: '3px 8px', borderRadius: 4, fontWeight: 700, fontSize: '0.78rem' }}>⚫ SILENT</span>;
    }
  };

  const filteredLogs = frameLogs.filter((log) => {
    if (logFilter === 'ALL') return true;
    return log.classification === logFilter;
  });

  const totalEvaluated = stats.speechNearFrames + stats.speechFarFrames + stats.noiseFrames + stats.silentFrames;
  const bandwidthSavedPct = totalEvaluated > 0 ? (((totalEvaluated - stats.speechNearFrames) / totalEvaluated) * 100).toFixed(1) : '0.0';

  // Compute Signal-to-Noise Ratio (SNR) estimation in dB
  const estimatedSnrDb = currentDiag.ambientRms > 0 && currentDiag.rollingRms > 0
    ? (20 * Math.log10(currentDiag.rollingRms / currentDiag.ambientRms)).toFixed(1)
    : '0.0';

  return (
    <div style={{ minHeight: '100vh', backgroundColor: '#070b14', color: '#f8fafc', fontFamily: 'Inter, system-ui, sans-serif', padding: '24px' }}>
      
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid #1e293b', paddingBottom: '16px', marginBottom: '20px' }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <h1 style={{ fontSize: '1.5rem', fontWeight: 800, margin: 0, background: 'linear-gradient(90deg, #38bdf8, #818cf8)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }}>
              🔬 Audio Processing, VAD & Energy Triage Visualizer
            </h1>
            <span style={{ backgroundColor: '#10b981', color: '#064e3b', fontWeight: 700, fontSize: '0.7rem', padding: '2px 8px', borderRadius: '12px' }}>
              100% CLIENT-SIDE STANDALONE (ZERO BACKEND)
            </span>
          </div>
          <p style={{ margin: '4px 0 0', fontSize: '0.85rem', color: '#94a3b8' }}>
            Inspect multi-track timeline graphs of RMS energy, Silero VAD probability, classifications, gate status, and audio clips.
          </p>
        </div>

        <div style={{ display: 'flex', gap: '10px' }}>
          <button
            onClick={startBoth}
            disabled={!vadLoaded}
            style={{ backgroundColor: activePipeline === 'both' ? '#10b981' : '#2563eb', color: '#fff', border: 'none', padding: '10px 18px', borderRadius: '6px', fontWeight: 600, cursor: 'pointer', boxShadow: '0 4px 12px rgba(37,99,235,0.3)' }}
          >
            {activePipeline === 'both' ? '🟢 Both Running' : '▶️ Test Both Pipelines'}
          </button>
          <button
            onClick={stopAll}
            style={{ backgroundColor: '#334155', color: '#fff', border: 'none', padding: '10px 18px', borderRadius: '6px', fontWeight: 600, cursor: 'pointer' }}
          >
            ⏹️ Stop All
          </button>
          <button
            onClick={clearAllData}
            style={{ backgroundColor: '#1e293b', color: '#cbd5e1', border: '1px solid #334155', padding: '10px 14px', borderRadius: '6px', cursor: 'pointer' }}
          >
            🧹 Clear Data
          </button>
        </div>
      </div>

      {/* Real-time Alerts */}
      {ambientAlert && (
        <div style={{ backgroundColor: 'rgba(220, 38, 38, 0.2)', border: '1px solid #dc2626', color: '#fca5a5', padding: '10px 16px', borderRadius: '6px', marginBottom: '16px', display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span>⚠️</span>
          <strong>{ambientAlert.message}</strong> — High background noise level in environment.
        </div>
      )}
      {speakCloserAlert && (
        <div style={{ backgroundColor: 'rgba(217, 119, 6, 0.2)', border: '1px solid #d97706', color: '#fcd34d', padding: '10px 16px', borderRadius: '6px', marginBottom: '16px', display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span>🎙️</span>
          <strong>{speakCloserAlert.message}</strong>
        </div>
      )}

      {/* ========================================================================= */}
      {/* 📊 MULTI-TRACK REAL-TIME SYNCHRONIZED TIMELINE GRAPH                      */}
      {/* ========================================================================= */}
      <div style={{ backgroundColor: '#0f172a', border: '1px solid #334155', borderRadius: '8px', padding: '16px', marginBottom: '20px', boxShadow: '0 4px 20px rgba(0,0,0,0.3)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <h3 style={{ margin: 0, fontSize: '1rem', fontWeight: 800, color: '#38bdf8' }}>
              📈 Multi-Track Time-Series Oscilloscope (Energy, VAD, Classification & Gate)
            </h3>
            <span style={{ fontSize: '0.75rem', color: '#64748b' }}>60 FPS Real-time Stream</span>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.75rem', color: '#94a3b8' }}>
              <span>Time Window:</span>
              {[5, 10, 20].map((sec) => (
                <button
                  key={sec}
                  onClick={() => setTimeWindowSec(sec)}
                  style={{
                    backgroundColor: timeWindowSec === sec ? '#38bdf8' : '#1e293b',
                    color: timeWindowSec === sec ? '#0f172a' : '#cbd5e1',
                    border: '1px solid #334155',
                    padding: '2px 8px',
                    borderRadius: '4px',
                    cursor: 'pointer',
                    fontWeight: 700,
                    fontSize: '0.75rem'
                  }}
                >
                  {sec}s
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Canvas Strip Chart */}
        <canvas
          ref={timelineCanvasRef}
          width={1120}
          height={275}
          style={{ width: '100%', height: '275px', borderRadius: '6px', backgroundColor: '#070b14' }}
        />

        {/* Legend */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '8px', fontSize: '0.72rem', color: '#94a3b8', borderTop: '1px solid #1e293b', paddingTop: '8px' }}>
          <div style={{ display: 'flex', gap: '16px' }}>
            <span><strong style={{ color: '#38bdf8' }}>— Blue Line:</strong> Rolling RMS Energy</span>
            <span><strong style={{ color: '#34d399' }}>— Green Line:</strong> Silero VAD Probability</span>
            <span><strong style={{ color: 'rgba(56,189,248,0.7)' }}>-- Dashed Line:</strong> Near-Field Floor</span>
            <span><strong style={{ color: '#f59e0b' }}>● Amber Pin:</strong> Speak-Closer Flag</span>
          </div>
          <div style={{ display: 'flex', gap: '12px' }}>
            <span style={{ color: '#10b981' }}>■ SPEECH_NEAR (Passed)</span>
            <span style={{ color: '#f59e0b' }}>■ SPEECH_FAR (Gated)</span>
            <span style={{ color: '#ef4444' }}>■ NOISE_ONLY (Dropped)</span>
            <span style={{ color: '#64748b' }}>■ SILENT</span>
          </div>
        </div>
      </div>

      {/* Real-time Diagnostics Matrix & Gauges */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: '12px', marginBottom: '20px' }}>
        <div style={{ backgroundColor: '#0f172a', border: '1px solid #334155', padding: '12px', borderRadius: '6px' }}>
          <div style={{ fontSize: '0.72rem', color: '#94a3b8', marginBottom: '4px' }}>CURRENT CLASSIFICATION</div>
          {getClassificationBadge(currentDiag.classification)}
        </div>
        <div style={{ backgroundColor: '#0f172a', border: '1px solid #334155', padding: '12px', borderRadius: '6px' }}>
          <div style={{ fontSize: '0.72rem', color: '#94a3b8', marginBottom: '4px' }}>ENERGY STATE MACHINE</div>
          <div style={{ fontSize: '0.9rem', fontWeight: 800, color: currentDiag.energyState.includes('CONFIRMED') ? '#10b981' : currentDiag.energyState.includes('PAUSE') ? '#fbbf24' : '#94a3b8' }}>
            {currentDiag.energyState}
          </div>
        </div>
        <div style={{ backgroundColor: '#0f172a', border: '1px solid #334155', padding: '12px', borderRadius: '6px' }}>
          <div style={{ fontSize: '0.72rem', color: '#94a3b8', marginBottom: '4px' }}>AUDIO GATE STREAMING</div>
          <div style={{ fontSize: '0.9rem', fontWeight: 800, color: currentDiag.isStreaming ? '#10b981' : '#f87171' }}>
            {currentDiag.isStreaming ? '🟢 PASSED (WAV Chunk)' : '🔴 BLOCKED (Gated)'}
          </div>
        </div>
        <div style={{ backgroundColor: '#0f172a', border: '1px solid #334155', padding: '12px', borderRadius: '6px' }}>
          <div style={{ fontSize: '0.72rem', color: '#94a3b8', marginBottom: '4px' }}>ENERGY & DECIBELS</div>
          <div style={{ fontSize: '0.9rem', fontWeight: 800, color: '#38bdf8' }}>
            {currentDiag.rollingRms.toFixed(4)} <span style={{ fontSize: '0.75rem', color: '#94a3b8' }}>({currentDiag.rmsDb.toFixed(1)} dB)</span>
          </div>
        </div>
        <div style={{ backgroundColor: '#0f172a', border: '1px solid #334155', padding: '12px', borderRadius: '6px' }}>
          <div style={{ fontSize: '0.72rem', color: '#94a3b8', marginBottom: '4px' }}>ESTIMATED SNR (dB)</div>
          <div style={{ fontSize: '0.9rem', fontWeight: 800, color: parseFloat(estimatedSnrDb) > 10 ? '#10b981' : '#f59e0b' }}>
            +{estimatedSnrDb} dB SNR
          </div>
        </div>
      </div>

      {/* Side-by-Side Audio Capture Comparison */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px', marginBottom: '24px' }}>
        
        {/* === LEFT: Classic Audio Processor === */}
        <div style={{ backgroundColor: '#1e293b', borderRadius: '8px', border: '1px solid #334155', padding: '16px', display: 'flex', flexDirection: 'column' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid #334155', paddingBottom: '10px', marginBottom: '14px' }}>
            <div>
              <h2 style={{ fontSize: '1.1rem', margin: 0, fontWeight: 700, color: '#94a3b8' }}>🏛️ Classic AudioProcessor Output</h2>
              <span style={{ fontSize: '0.75rem', color: '#64748b' }}>Streams EVERYTHING that triggers Silero VAD (noise, distant voices)</span>
            </div>
            <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
              <span style={{ fontSize: '0.75rem', padding: '3px 8px', borderRadius: '4px', backgroundColor: classicIsSpeaking ? '#10b981' : '#475569', color: '#fff', fontWeight: 700 }}>
                {classicIsSpeaking ? 'VAD SPEECH' : 'IDLE'}
              </span>
              {!classicProcessorRef.current ? (
                <button onClick={startClassic} disabled={!vadLoaded} style={{ backgroundColor: '#059669', color: '#fff', border: 'none', padding: '4px 10px', borderRadius: '4px', cursor: 'pointer', fontSize: '0.8rem' }}>Start</button>
              ) : (
                <button onClick={stopClassic} style={{ backgroundColor: '#dc2626', color: '#fff', border: 'none', padding: '4px 10px', borderRadius: '4px', cursor: 'pointer', fontSize: '0.8rem' }}>Stop</button>
              )}
            </div>
          </div>

          {/* Volume Meter */}
          <div style={{ marginBottom: '14px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', color: '#94a3b8', marginBottom: '4px' }}>
              <span>Microphone Volume Level</span>
              <span>{(classicVolume * 100).toFixed(0)}%</span>
            </div>
            <div style={{ height: '8px', backgroundColor: '#0f172a', borderRadius: '4px', overflow: 'hidden' }}>
              <div style={{ width: `${Math.min(100, classicVolume * 100)}%`, height: '100%', backgroundColor: '#38bdf8', transition: 'width 0.05s linear' }} />
            </div>
          </div>

          {/* Recorded Audio Output List */}
          <div style={{ flex: 1, backgroundColor: '#0f172a', borderRadius: '6px', padding: '12px', border: '1px solid #334155', minHeight: '220px', maxHeight: '280px', overflowY: 'auto' }}>
            <div style={{ fontSize: '0.75rem', fontWeight: 700, color: '#94a3b8', marginBottom: '8px' }}>
              🔊 CAPTURED AUDIO CLIPS ({classicAudioClips.length})
            </div>
            {classicAudioClips.length === 0 ? (
              <div style={{ color: '#475569', fontSize: '0.8rem', fontStyle: 'italic', padding: '10px 0' }}>
                Speak into microphone to capture audio...
              </div>
            ) : (
              classicAudioClips.map((clip) => (
                <div key={clip.id} style={{ backgroundColor: '#1e293b', padding: '8px 10px', borderRadius: '6px', marginBottom: '8px', border: '1px solid #334155' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', color: '#94a3b8', marginBottom: '4px' }}>
                    <span>🕒 {clip.time} ({clip.durationSec}s, {clip.sizeKb} KB)</span>
                    <a href={clip.url} download={`classic_${clip.id}.wav`} style={{ color: '#38bdf8', textDecoration: 'none' }}>⬇️ Download</a>
                  </div>
                  <audio controls src={clip.url} style={{ width: '100%', height: '32px' }} />
                </div>
              ))
            )}
          </div>
        </div>

        {/* === RIGHT: Robust Audio Processor === */}
        <div style={{ backgroundColor: '#1e293b', borderRadius: '8px', border: '1px solid #38bdf8', padding: '16px', display: 'flex', flexDirection: 'column', boxShadow: '0 0 15px rgba(56, 189, 248, 0.15)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid #334155', paddingBottom: '10px', marginBottom: '14px' }}>
            <div>
              <h2 style={{ fontSize: '1.1rem', margin: 0, fontWeight: 800, color: '#38bdf8' }}>🚀 Robust AudioProcessor (Energy Gated)</h2>
              <span style={{ fontSize: '0.75rem', color: '#94a3b8' }}>GATES OUT distant voices, mumbles & noise before audio leaves browser</span>
            </div>
            <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
              <span style={{ fontSize: '0.75rem', padding: '3px 8px', borderRadius: '4px', backgroundColor: robustIsSpeaking ? '#10b981' : '#475569', color: '#fff', fontWeight: 700 }}>
                {robustIsSpeaking ? 'STREAMING NEAR-FIELD' : 'IDLE / GATED'}
              </span>
              {!robustProcessorRef.current ? (
                <button onClick={startRobust} disabled={!vadLoaded} style={{ backgroundColor: '#38bdf8', color: '#0f172a', fontWeight: 700, border: 'none', padding: '4px 10px', borderRadius: '4px', cursor: 'pointer', fontSize: '0.8rem' }}>Start</button>
              ) : (
                <button onClick={stopRobust} style={{ backgroundColor: '#dc2626', color: '#fff', border: 'none', padding: '4px 10px', borderRadius: '4px', cursor: 'pointer', fontSize: '0.8rem' }}>Stop</button>
              )}
            </div>
          </div>

          {/* Meter Bars */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px', marginBottom: '14px' }}>
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', color: '#94a3b8', marginBottom: '3px' }}>
                <span>VAD Probability</span>
                <span style={{ fontWeight: 600, color: currentDiag.vadProbability >= tuningParams.positiveSpeechThreshold ? '#34d399' : '#94a3b8' }}>
                  {(currentDiag.vadProbability * 100).toFixed(0)}%
                </span>
              </div>
              <div style={{ height: '8px', backgroundColor: '#0f172a', borderRadius: '4px', overflow: 'hidden' }}>
                <div style={{ width: `${Math.min(100, currentDiag.vadProbability * 100)}%`, height: '100%', backgroundColor: currentDiag.vadProbability >= tuningParams.positiveSpeechThreshold ? '#10b981' : '#64748b', transition: 'width 0.05s' }} />
              </div>
            </div>

            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', color: '#94a3b8', marginBottom: '3px' }}>
                <span>Rolling RMS Energy</span>
                <span style={{ fontWeight: 600, color: currentDiag.rollingRms >= tuningParams.rmsHighThreshold ? '#34d399' : '#f59e0b' }}>
                  {currentDiag.rollingRms.toFixed(4)} ({currentDiag.rmsDb.toFixed(1)} dB)
                </span>
              </div>
              <div style={{ height: '8px', backgroundColor: '#0f172a', borderRadius: '4px', overflow: 'hidden' }}>
                <div style={{ width: `${Math.min(100, (currentDiag.rollingRms / 0.04) * 100)}%`, height: '100%', backgroundColor: currentDiag.rollingRms >= tuningParams.rmsHighThreshold ? '#38bdf8' : '#f59e0b', transition: 'width 0.05s' }} />
              </div>
            </div>
          </div>

          {/* Processed & Passed Audio Output List */}
          <div style={{ flex: 1, backgroundColor: '#0f172a', borderRadius: '6px', padding: '12px', border: '1px solid #334155', minHeight: '220px', maxHeight: '280px', overflowY: 'auto' }}>
            <div style={{ fontSize: '0.75rem', fontWeight: 700, color: '#38bdf8', marginBottom: '8px' }}>
              🔊 CLEANED & PASSED AUDIO CLIPS ({robustAudioClips.length})
            </div>
            {robustAudioClips.length === 0 ? (
              <div style={{ color: '#475569', fontSize: '0.8rem', fontStyle: 'italic', padding: '10px 0' }}>
                Speak near the mic (10-30cm) to pass the energy gate...
              </div>
            ) : (
              robustAudioClips.map((clip) => (
                <div key={clip.id} style={{ backgroundColor: '#1e293b', padding: '8px 10px', borderRadius: '6px', marginBottom: '8px', border: '1px solid rgba(56, 189, 248, 0.4)' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', color: '#38bdf8', marginBottom: '4px' }}>
                    <span>🕒 {clip.time} ({clip.durationSec}s, {clip.sizeKb} KB)</span>
                    <a href={clip.url} download={`robust_${clip.id}.wav`} style={{ color: '#38bdf8', textDecoration: 'none' }}>⬇️ Download</a>
                  </div>
                  <audio controls src={clip.url} style={{ width: '100%', height: '32px' }} />
                </div>
              ))
            )}
          </div>
        </div>
      </div>

      {/* Aggregate Statistics & Noise Reduction Summary */}
      <div style={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: '8px', padding: '16px', marginBottom: '20px' }}>
        <h3 style={{ margin: '0 0 12px 0', fontSize: '1rem', fontWeight: 700, color: '#f1f5f9' }}>
          📊 Real-Time Efficiency & Noise Reduction Statistics
        </h3>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6, 1fr)', gap: '12px' }}>
          <div style={{ backgroundColor: '#0f172a', padding: '10px', borderRadius: '6px', border: '1px solid #334155' }}>
            <div style={{ fontSize: '0.75rem', color: '#94a3b8' }}>Total Frames</div>
            <div style={{ fontSize: '1.2rem', fontWeight: 800, color: '#f8fafc' }}>{stats.totalFrames}</div>
          </div>
          <div style={{ backgroundColor: '#0f172a', padding: '10px', borderRadius: '6px', border: '1px solid #334155' }}>
            <div style={{ fontSize: '0.75rem', color: '#94a3b8' }}>Speech Near (Passed)</div>
            <div style={{ fontSize: '1.2rem', fontWeight: 800, color: '#10b981' }}>{stats.speechNearFrames}</div>
          </div>
          <div style={{ backgroundColor: '#0f172a', padding: '10px', borderRadius: '6px', border: '1px solid #334155' }}>
            <div style={{ fontSize: '0.75rem', color: '#94a3b8' }}>Speech Far (Gated)</div>
            <div style={{ fontSize: '1.2rem', fontWeight: 800, color: '#f59e0b' }}>{stats.speechFarFrames}</div>
          </div>
          <div style={{ backgroundColor: '#0f172a', padding: '10px', borderRadius: '6px', border: '1px solid #334155' }}>
            <div style={{ fontSize: '0.75rem', color: '#94a3b8' }}>Noise Only (Dropped)</div>
            <div style={{ fontSize: '1.2rem', fontWeight: 800, color: '#ef4444' }}>{stats.noiseFrames}</div>
          </div>
          <div style={{ backgroundColor: '#0f172a', padding: '10px', borderRadius: '6px', border: '1px solid #334155' }}>
            <div style={{ fontSize: '0.75rem', color: '#94a3b8' }}>Streamed Chunks</div>
            <div style={{ fontSize: '1.2rem', fontWeight: 800, color: '#38bdf8' }}>{stats.streamedChunks}</div>
          </div>
          <div style={{ backgroundColor: '#0f172a', padding: '10px', borderRadius: '6px', border: '1px solid #334155' }}>
            <div style={{ fontSize: '0.75rem', color: '#94a3b8' }}>Unwanted Audio Filtered</div>
            <div style={{ fontSize: '1.2rem', fontWeight: 800, color: '#a855f7' }}>{bandwidthSavedPct}%</div>
          </div>
        </div>
      </div>

      {/* Interactive Parameter Tuning Sliders */}
      <div style={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: '8px', padding: '16px', marginBottom: '20px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '14px' }}>
          <h3 style={{ margin: 0, fontSize: '1rem', fontWeight: 700, color: '#f1f5f9' }}>
            🎛️ Live Parameter Tuning & Heuristic Controls
          </h3>
          <button
            onClick={() => setTuningParams({
              positiveSpeechThreshold: 0.75,
              negativeSpeechThreshold: 0.25,
              rmsHighThreshold: 0.015,
              rmsLowThreshold: 0.004,
              rmsWindowSize: 5,
              minNearFrames: 3,
              maxEvalFrames: 30,
              energyRedemptionFrames: 12,
              ambientNoiseThreshold: 0.008,
              speakCloserCooldownMs: 15000,
            })}
            style={{ backgroundColor: '#334155', color: '#cbd5e1', border: 'none', padding: '4px 10px', borderRadius: '4px', fontSize: '0.75rem', cursor: 'pointer' }}
          >
            Reset Defaults
          </button>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '16px' }}>
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.8rem', color: '#94a3b8' }}>
              <span>VAD Positive Threshold</span>
              <strong style={{ color: '#38bdf8' }}>{tuningParams.positiveSpeechThreshold.toFixed(2)}</strong>
            </div>
            <input
              type="range"
              min="0.3"
              max="0.95"
              step="0.05"
              value={tuningParams.positiveSpeechThreshold}
              onChange={(e) => setTuningParams({ ...tuningParams, positiveSpeechThreshold: parseFloat(e.target.value) })}
              style={{ width: '100%', cursor: 'pointer' }}
            />
          </div>

          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.8rem', color: '#94a3b8' }}>
              <span>VAD Negative Threshold</span>
              <strong style={{ color: '#38bdf8' }}>{tuningParams.negativeSpeechThreshold.toFixed(2)}</strong>
            </div>
            <input
              type="range"
              min="0.1"
              max="0.6"
              step="0.05"
              value={tuningParams.negativeSpeechThreshold}
              onChange={(e) => setTuningParams({ ...tuningParams, negativeSpeechThreshold: parseFloat(e.target.value) })}
              style={{ width: '100%', cursor: 'pointer' }}
            />
          </div>

          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.8rem', color: '#94a3b8' }}>
              <span>RMS High Threshold (Near-field floor)</span>
              <strong style={{ color: '#38bdf8' }}>{tuningParams.rmsHighThreshold.toFixed(3)}</strong>
            </div>
            <input
              type="range"
              min="0.005"
              max="0.040"
              step="0.001"
              value={tuningParams.rmsHighThreshold}
              onChange={(e) => setTuningParams({ ...tuningParams, rmsHighThreshold: parseFloat(e.target.value) })}
              style={{ width: '100%', cursor: 'pointer' }}
            />
          </div>

          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.8rem', color: '#94a3b8' }}>
              <span>Min Near Frames to Confirm</span>
              <strong style={{ color: '#38bdf8' }}>{tuningParams.minNearFrames}</strong>
            </div>
            <input
              type="range"
              min="1"
              max="8"
              step="1"
              value={tuningParams.minNearFrames}
              onChange={(e) => setTuningParams({ ...tuningParams, minNearFrames: parseInt(e.target.value) })}
              style={{ width: '100%', cursor: 'pointer' }}
            />
          </div>

          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.8rem', color: '#94a3b8' }}>
              <span>Energy Pause Redemption Frames</span>
              <strong style={{ color: '#38bdf8' }}>{tuningParams.energyRedemptionFrames}</strong>
            </div>
            <input
              type="range"
              min="4"
              max="24"
              step="2"
              value={tuningParams.energyRedemptionFrames}
              onChange={(e) => setTuningParams({ ...tuningParams, energyRedemptionFrames: parseInt(e.target.value) })}
              style={{ width: '100%', cursor: 'pointer' }}
            />
          </div>

          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.8rem', color: '#94a3b8' }}>
              <span>Ambient Noise Threshold</span>
              <strong style={{ color: '#38bdf8' }}>{tuningParams.ambientNoiseThreshold.toFixed(3)}</strong>
            </div>
            <input
              type="range"
              min="0.003"
              max="0.020"
              step="0.001"
              value={tuningParams.ambientNoiseThreshold}
              onChange={(e) => setTuningParams({ ...tuningParams, ambientNoiseThreshold: parseFloat(e.target.value) })}
              style={{ width: '100%', cursor: 'pointer' }}
            />
          </div>
        </div>
      </div>

      {/* Frame-by-Frame Diagnostic Stream Log */}
      <div style={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: '8px', padding: '16px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <h3 style={{ margin: 0, fontSize: '1rem', fontWeight: 700, color: '#f1f5f9' }}>
              🔬 Frame-by-Frame Diagnostic Stream (Last 100)
            </h3>
            <div style={{ display: 'flex', gap: '4px' }}>
              {['ALL', 'SPEECH_NEAR', 'SPEECH_FAR', 'NOISE_ONLY', 'SILENT'].map((filter) => (
                <button
                  key={filter}
                  onClick={() => setLogFilter(filter)}
                  style={{
                    backgroundColor: logFilter === filter ? '#38bdf8' : '#0f172a',
                    color: logFilter === filter ? '#0f172a' : '#94a3b8',
                    border: '1px solid #334155',
                    padding: '3px 8px',
                    borderRadius: '4px',
                    fontSize: '0.72rem',
                    fontWeight: 600,
                    cursor: 'pointer'
                  }}
                >
                  {filter}
                </button>
              ))}
            </div>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <label style={{ fontSize: '0.75rem', color: '#94a3b8', display: 'flex', alignItems: 'center', gap: '4px', cursor: 'pointer' }}>
              <input
                type="checkbox"
                checked={autoScrollLogs}
                onChange={(e) => setAutoScrollLogs(e.target.checked)}
              />
              Auto-Scroll
            </label>
            <button
              onClick={() => setFrameLogs([])}
              style={{ backgroundColor: '#334155', color: '#cbd5e1', border: 'none', padding: '3px 8px', borderRadius: '4px', fontSize: '0.72rem', cursor: 'pointer' }}
            >
              Clear Log
            </button>
          </div>
        </div>

        <div
          ref={logsContainerRef}
          style={{
            backgroundColor: '#0f172a',
            border: '1px solid #334155',
            borderRadius: '6px',
            height: '220px',
            overflowY: 'auto',
            fontFamily: 'monospace',
            fontSize: '0.75rem',
            padding: '8px 12px',
          }}
        >
          {filteredLogs.length === 0 ? (
            <div style={{ color: '#475569', fontStyle: 'italic', padding: '8px' }}>Waiting for audio frames...</div>
          ) : (
            filteredLogs.map((log) => (
              <div
                key={log.id}
                style={{
                  display: 'grid',
                  gridTemplateColumns: '110px 90px 100px 100px 140px 140px 1fr',
                  padding: '3px 0',
                  borderBottom: '1px solid rgba(51,65,85,0.4)',
                  color: log.classification === 'SPEECH_NEAR' ? '#34d399' : log.classification === 'SPEECH_FAR' ? '#f59e0b' : log.classification === 'NOISE_ONLY' ? '#f87171' : '#64748b'
                }}
              >
                <span>[{log.time}]</span>
                <span>VAD: {(log.vadProbability * 100).toFixed(0)}%</span>
                <span>RMS: {log.rmsEnergy.toFixed(4)}</span>
                <span>dB: {log.rmsDb.toFixed(1)}</span>
                <span>RollRMS: {log.rollingRms.toFixed(4)}</span>
                <span>{log.energyState}</span>
                <span>{log.isStreaming ? '🟢 PASSED (WAV)' : '🔴 GATED (DROP)'}</span>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
