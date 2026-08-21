'use client';

import React, { useState, useEffect, useRef, useCallback } from 'react';
import { PipelineAudioEngine } from '../utils/pipelineAudioEngine';
import { loadVADScripts, unlockAudioContext } from '../utils/voiceHelper';
import { toast } from 'sonner';

// Supported STT Languages
const SUPPORTED_LANGUAGES = [
  { code: 'hi', label: 'Hindi (हिन्दी)', flag: '🇮🇳' },
  { code: 'en', label: 'English', flag: '🌐' },
  { code: 'mr', label: 'Marathi (मराठी)', flag: '🇮🇳' },
  { code: 'ta', label: 'Tamil (தமிழ்)', flag: '🇮🇳' },
  { code: 'te', label: 'Telugu (తెలుగు)', flag: '🇮🇳' },
  { code: 'kn', label: 'Kannada (ಕನ್ನಡ)', flag: '🇮🇳' },
  { code: 'ar', label: 'Arabic (العربية)', flag: '🇸🇦' },
  { code: 'fr', label: 'French (Français)', flag: '🇫🇷' },
];

export default function TestVoicePipelineDashboard() {
  // === Pipeline & Session State ===
  const [isRunning, setIsRunning] = useState(false);
  const [sessionState, setSessionState] = useState('idle'); // idle, connecting, running, stopped, error
  const [vadLoaded, setVadLoaded] = useState(false);
  const [selectedLanguage, setSelectedLanguage] = useState('hi');

  // === Live Flags ===
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [isHighBgNoise, setIsHighBgNoise] = useState(false);
  const [ambientRmsVal, setAmbientRmsVal] = useState(0);
  const [vadProb, setVadProb] = useState(0);
  const [isLimiting, setIsLimiting] = useState(false);

  // === Live 4-Stage Real-Time Telemetry ===
  const [stageMetrics, setStageMetrics] = useState({
    raw: { rms: 0, db: -60, peak: 0 },
    hpf: { rms: 0, db: -60, peak: 0, subBassCutDb: 0 },
    rnnoise: { rms: 0, db: -60, peak: 0, noiseReductionDb: 0 },
    agc: { rms: 0, db: -60, peak: 0, gainApplied: 1.0, gainDb: 0, isLimiting: false },
  });

  // === Live STT Streaming Transcription ===
  const [liveTranscription, setLiveTranscription] = useState('');
  const [isFinalTranscript, setIsFinalTranscript] = useState(false);
  const [transcriptLatency, setTranscriptLatency] = useState(null);
  const [transcriptHistory, setTranscriptHistory] = useState([]);

  // === 4-Stage Utterance Auditioning History ===
  const [utterances, setUtterances] = useState([]);

  // === Master A/B/C/D Player State ===
  const [activeUtteranceId, setActiveUtteranceId] = useState(null);
  const [activeStageMode, setActiveStageMode] = useState('agc'); // 'raw', 'hpf', 'rnnoise', 'agc'
  const [isPlayingMaster, setIsPlayingMaster] = useState(false);
  const masterAudioRef = useRef(null);

  // === Dynamic DSP & VAD Tuning Configuration ===
  const [tuningParams, setTuningParams] = useState({
    hpfCutoff: 85,
    rnnoiseEnabled: true,
    rnnoiseStrength: 1.0,
    positiveSpeechThreshold: 0.65,
    negativeSpeechThreshold: 0.25,
    agcTargetRms: 0.125, // ≈ -18 dBFS
    agcMaxGain: 6.0,
    ambientNoiseThreshold: 0.0080,
    ambientRecoveryThreshold: 0.0060,
  });

  const [showTuningDrawer, setShowTuningDrawer] = useState(false);

  // === Engine & Canvas Refs ===
  const audioEngineRef = useRef(null);
  const timelineCanvasRef = useRef(null);
  const timeSeriesRef = useRef([]); // History for oscilloscope: { t, rawRms, rnnoiseRms, vadProb, ambientRms, isSpeaking }
  const animFrameIdRef = useRef(null);

  // Initialize VAD scripts on mount
  useEffect(() => {
    loadVADScripts().then((loaded) => {
      setVadLoaded(loaded);
      if (loaded) {
        toast.success('Silero VAD WebAssembly Engine Ready');
      } else {
        toast.error('Failed to load Silero VAD library from CDN');
      }
    });

    return () => {
      if (audioEngineRef.current) audioEngineRef.current.stop();
      if (animFrameIdRef.current) cancelAnimationFrame(animFrameIdRef.current);
    };
  }, []);

  // Update dynamic config on tuning change
  useEffect(() => {
    if (audioEngineRef.current) {
      audioEngineRef.current.updateConfig({
        ...tuningParams,
        language: selectedLanguage,
      });
    }
  }, [tuningParams, selectedLanguage]);

  // ==========================================
  // Master A/B/C/D Seamless Audio Switcher
  // ==========================================
  const handlePlayMaster = (uttId, stageKey = activeStageMode) => {
    const utt = utterances.find((u) => u.id === uttId);
    if (!utt) return;

    const audioUrl = utt.urls[stageKey];
    if (!audioUrl) {
      toast.error(`Audio not available for stage ${stageKey}`);
      return;
    }

    if (!masterAudioRef.current) {
      masterAudioRef.current = new Audio();
    }

    const audio = masterAudioRef.current;

    if (activeUtteranceId === uttId && isPlayingMaster && activeStageMode === stageKey) {
      // Pause
      audio.pause();
      setIsPlayingMaster(false);
      return;
    }

    // Preserve playback position when switching stages!
    let resumeTime = 0;
    if (activeUtteranceId === uttId && !audio.paused) {
      resumeTime = audio.currentTime;
    }

    audio.src = audioUrl;
    audio.currentTime = resumeTime;
    audio.play().then(() => {
      setActiveUtteranceId(uttId);
      setActiveStageMode(stageKey);
      setIsPlayingMaster(true);
    }).catch(console.error);

    audio.onended = () => {
      setIsPlayingMaster(false);
    };
  };

  // Switch stage on the fly during active playback
  const handleSwitchStage = (stageKey) => {
    setActiveStageMode(stageKey);
    if (activeUtteranceId && isPlayingMaster) {
      handlePlayMaster(activeUtteranceId, stageKey);
    }
  };

  // ==========================================
  // Start / Stop Pipeline Handler
  // ==========================================
  const togglePipeline = async () => {
    unlockAudioContext();

    if (isRunning) {
      if (audioEngineRef.current) {
        audioEngineRef.current.stop();
        audioEngineRef.current = null;
      }
      setIsRunning(false);
      setIsSpeaking(false);
      setSessionState('stopped');
      toast.info('Voice Pipeline Stopped');
      return;
    }

    try {
      setSessionState('connecting');
      toast.info('Starting 5-Stage Voice Pipeline...');

      const defaultHost = typeof window !== 'undefined' ? window.location.hostname : 'localhost';
      const wsUrl = `ws://${defaultHost}:8080/ws/voice`;

      const engine = new PipelineAudioEngine({
        sampleRate: 16000,
        language: selectedLanguage,
        wsUrl,
        ...tuningParams,

        onStateChange: (state) => {
          setSessionState(state);
          if (state === 'running') setIsRunning(true);
        },

        onTelemetry: (t) => {
          setVadProb(t.vadProbability);
          setIsSpeaking(t.isSpeaking);
          setIsHighBgNoise(t.isHighBackgroundNoise);
          setAmbientRmsVal(t.ambientRms);
          setIsLimiting(t.agc.isLimiting);

          setStageMetrics({
            raw: t.raw,
            hpf: t.hpf,
            rnnoise: t.rnnoise,
            agc: t.agc,
          });

          // Append to oscilloscope time series
          timeSeriesRef.current.push({
            t: t.timestamp,
            rawRms: t.raw.rms,
            rnnoiseRms: t.rnnoise.rms,
            agcRms: t.agc.rms,
            vadProb: t.vadProbability,
            ambientRms: t.ambientRms,
            isSpeaking: t.isSpeaking,
            isLimiting: t.agc.isLimiting,
          });

          // Keep max 320 points (~10 seconds)
          if (timeSeriesRef.current.length > 320) {
            timeSeriesRef.current.shift();
          }
        },

        onSpeechStart: () => {
          setIsSpeaking(true);
          setLiveTranscription('Listening... 🎙️');
          setIsFinalTranscript(false);
        },

        onSpeechEnd: (utteranceData) => {
          setIsSpeaking(false);
          // Prepend new utterance to auditioning list
          setUtterances((prev) => [
            {
              ...utteranceData,
              transcription: liveTranscription || '(Awaiting transcription...)',
            },
            ...prev,
          ]);
        },

        onTranscript: (tData) => {
          setLiveTranscription(tData.text);
          setIsFinalTranscript(tData.isFinal);
          if (tData.latencyMs) setTranscriptLatency(tData.latencyMs);

          if (tData.isFinal && tData.text) {
            setTranscriptHistory((prev) => [
              {
                id: Date.now(),
                time: new Date().toLocaleTimeString(),
                text: tData.text,
                language: selectedLanguage,
                latencyMs: tData.latencyMs,
              },
              ...prev,
            ]);

            // Update latest utterance card with final transcription
            setUtterances((prev) => {
              if (prev.length === 0) return prev;
              const copy = [...prev];
              copy[0] = { ...copy[0], transcription: tData.text };
              return copy;
            });
          }
        },

        onBackgroundNoiseChange: (isHigh, rms) => {
          setIsHighBgNoise(isHigh);
          setAmbientRmsVal(rms);
          if (isHigh) {
            toast.warning(`High Background Noise Alert! (RMS: ${rms.toFixed(4)})`);
          } else {
            toast.success(`Ambient Noise Recovered (RMS: ${rms.toFixed(4)})`);
          }
        },

        onError: (err) => {
          toast.error(`Pipeline Error: ${err.message || err}`);
          setIsRunning(false);
          setSessionState('error');
        },
      });

      audioEngineRef.current = engine;
      await engine.start();
    } catch (err) {
      toast.error(`Failed to start: ${err.message}`);
      setIsRunning(false);
      setSessionState('error');
    }
  };

  // ==========================================
  // Multi-Track Synchronized Oscilloscope Canvas
  // ==========================================
  useEffect(() => {
    const canvas = timelineCanvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const render = () => {
      const w = canvas.width;
      const h = canvas.height;
      const history = timeSeriesRef.current;

      // Dark futuristic background
      ctx.fillStyle = '#060a12';
      ctx.fillRect(0, 0, w, h);

      // Grid Lines
      ctx.strokeStyle = 'rgba(255, 255, 255, 0.05)';
      ctx.lineWidth = 1;
      for (let y = 30; y < h; y += 45) {
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(w, y);
        ctx.stroke();
      }

      // Track Heights:
      // Track 1: Dual Waveform RMS (Raw vs RNNoise) [top 0 to 90px]
      // Track 2: VAD Probability Waveform [95 to 165px]
      // Track 3: Ambient Noise vs Hysteresis [170 to 230px]
      // Track 4: Audio Gate & Speech Ribbon [235 to 255px]

      const t1Top = 15;
      const t1H = 75;
      const t2Top = 100;
      const t2H = 65;
      const t3Top = 175;
      const t3H = 55;
      const t4Top = 238;
      const t4H = 15;

      // Labels
      ctx.font = '10px "Inter", sans-serif';
      ctx.fillStyle = '#38bdf8';
      ctx.fillText('STAGE 1 & 3: RAW (CYAN) vs RNNOISE (GREEN) ENERGY', 12, t1Top + 12);

      ctx.fillStyle = '#a855f7';
      ctx.fillText('STAGE 4: SILERO VAD PROBABILITY', 12, t2Top + 12);

      ctx.fillStyle = '#f59e0b';
      ctx.fillText('AMBIENT NOISE HYSTERESIS CORRIDOR', 12, t3Top + 12);

      ctx.fillStyle = '#94a3b8';
      ctx.fillText('SPEECH STATE', 12, t4Top + 11);

      if (history.length < 2) {
        ctx.fillStyle = '#64748b';
        ctx.font = '12px "Inter", sans-serif';
        ctx.fillText('Awaiting microphone stream data...', w / 2 - 100, h / 2);
        animFrameIdRef.current = requestAnimationFrame(render);
        return;
      }

      const step = w / Math.max(1, history.length - 1);

      // Track 1: Stage 1 Raw RMS (Cyan)
      ctx.strokeStyle = '#06b6d4';
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      for (let i = 0; i < history.length; i++) {
        const x = i * step;
        const norm = Math.min(1.0, history[i].rawRms / 0.15);
        const y = t1Top + t1H - norm * t1H;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.stroke();

      // Track 1: Stage 3 RNNoise RMS (Emerald Green)
      ctx.strokeStyle = '#10b981';
      ctx.lineWidth = 2.0;
      ctx.beginPath();
      for (let i = 0; i < history.length; i++) {
        const x = i * step;
        const norm = Math.min(1.0, history[i].rnnoiseRms / 0.15);
        const y = t1Top + t1H - norm * t1H;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.stroke();

      // Track 2: VAD Probability (Purple)
      ctx.strokeStyle = '#a855f7';
      ctx.lineWidth = 2.0;
      ctx.beginPath();
      for (let i = 0; i < history.length; i++) {
        const x = i * step;
        const norm = history[i].vadProb;
        const y = t2Top + t2H - norm * t2H;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.stroke();

      // VAD Positive Threshold Guide
      const posVadY = t2Top + t2H - tuningParams.positiveSpeechThreshold * t2H;
      ctx.strokeStyle = 'rgba(236, 72, 153, 0.6)';
      ctx.setLineDash([4, 4]);
      ctx.beginPath();
      ctx.moveTo(0, posVadY);
      ctx.lineTo(w, posVadY);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = '#ec4899';
      ctx.fillText(`Pos Thresh (${(tuningParams.positiveSpeechThreshold * 100).toFixed(0)}%)`, w - 100, posVadY - 3);

      // Track 3: Ambient RMS (Amber)
      ctx.strokeStyle = '#f59e0b';
      ctx.lineWidth = 1.8;
      ctx.beginPath();
      for (let i = 0; i < history.length; i++) {
        const x = i * step;
        const norm = Math.min(1.0, history[i].ambientRms / 0.02);
        const y = t3Top + t3H - norm * t3H;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.stroke();

      // Hysteresis Alarm Threshold Line
      const alarmY = t3Top + t3H - Math.min(1.0, tuningParams.ambientNoiseThreshold / 0.02) * t3H;
      ctx.strokeStyle = 'rgba(239, 68, 68, 0.7)';
      ctx.setLineDash([3, 3]);
      ctx.beginPath();
      ctx.moveTo(0, alarmY);
      ctx.lineTo(w, alarmY);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = '#ef4444';
      ctx.fillText(`Alarm (${tuningParams.ambientNoiseThreshold})`, w - 85, alarmY - 3);

      // Track 4: Speech State Ribbon
      for (let i = 0; i < history.length; i++) {
        const x = i * step;
        const isSpk = history[i].isSpeaking;
        ctx.fillStyle = isSpk ? '#10b981' : '#1e293b';
        ctx.fillRect(x, t4Top, step + 1, t4H);
      }

      animFrameIdRef.current = requestAnimationFrame(render);
    };

    render();

    return () => {
      if (animFrameIdRef.current) cancelAnimationFrame(animFrameIdRef.current);
    };
  }, [tuningParams]);

  return (
    <div style={{ minHeight: '100vh', background: '#030712', color: '#f8fafc', fontFamily: 'Inter, system-ui, sans-serif', padding: '24px' }}>
      <div style={{ maxWidth: '1440px', margin: '0 auto' }}>

        {/* ─── Top Header & Architecture Breadcrumb ─── */}
        <div style={{ background: 'rgba(15, 23, 42, 0.75)', backdropFilter: 'blur(16px)', border: '1px solid rgba(255, 255, 255, 0.1)', borderRadius: '16px', padding: '20px 28px', marginBottom: '24px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '16px' }}>
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                <span style={{ fontSize: '24px' }}>⚡</span>
                <h1 style={{ margin: 0, fontSize: '22px', fontWeight: '700', letterSpacing: '-0.5px', background: 'linear-gradient(135deg, #38bdf8, #818cf8, #c084fc)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }}>
                  5-Stage Voice Pipeline Lab & Diagnostics
                </h1>
                <span style={{ background: 'rgba(56, 189, 248, 0.15)', color: '#38bdf8', border: '1px solid rgba(56, 189, 248, 0.3)', padding: '3px 10px', borderRadius: '12px', fontSize: '11px', fontWeight: '600' }}>
                  NEW ARCHITECTURE
                </span>
              </div>
              <p style={{ margin: '6px 0 0', color: '#94a3b8', fontSize: '13px' }}>
                Audio from mic ➔ HPF (85Hz) ➔ RNNoise Suppression ➔ Silero VAD ➔ Digital AGC ➔ Backend STT ➔ Live Transcription
              </p>
            </div>

            {/* Controls */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '14px', flexWrap: 'wrap' }}>
              {/* Language Selector */}
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', background: 'rgba(30, 41, 59, 0.8)', padding: '6px 12px', borderRadius: '10px', border: '1px solid rgba(255, 255, 255, 0.1)' }}>
                <span style={{ fontSize: '12px', color: '#94a3b8' }}>Language:</span>
                <select
                  value={selectedLanguage}
                  onChange={(e) => setSelectedLanguage(e.target.value)}
                  style={{ background: 'transparent', border: 'none', color: '#f8fafc', fontSize: '13px', fontWeight: '600', outline: 'none', cursor: 'pointer' }}
                >
                  {SUPPORTED_LANGUAGES.map((lang) => (
                    <option key={lang.code} value={lang.code} style={{ background: '#0f172a', color: '#f8fafc' }}>
                      {lang.flag} {lang.label}
                    </option>
                  ))}
                </select>
              </div>

              {/* Tuning Drawer Button */}
              <button
                onClick={() => setShowTuningDrawer(!showTuningDrawer)}
                style={{ background: showTuningDrawer ? 'rgba(168, 85, 247, 0.2)' : 'rgba(30, 41, 59, 0.8)', border: '1px solid rgba(168, 85, 247, 0.4)', color: '#c084fc', padding: '8px 14px', borderRadius: '10px', fontSize: '13px', fontWeight: '600', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '6px' }}
              >
                ⚙️ DSP Tuning
              </button>

              {/* Master Start / Stop Button */}
              <button
                onClick={togglePipeline}
                style={{
                  background: isRunning ? 'linear-gradient(135deg, #ef4444, #dc2626)' : 'linear-gradient(135deg, #0284c7, #2563eb)',
                  color: '#ffffff',
                  border: 'none',
                  padding: '10px 22px',
                  borderRadius: '12px',
                  fontSize: '14px',
                  fontWeight: '700',
                  cursor: 'pointer',
                  boxShadow: isRunning ? '0 0 20px rgba(239, 68, 68, 0.5)' : '0 0 20px rgba(37, 99, 235, 0.4)',
                  transition: 'all 0.2s ease',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '8px',
                }}
              >
                <span>{isRunning ? '⏹️' : '🎙️'}</span>
                {isRunning ? 'Stop Pipeline' : 'Start Voice Pipeline'}
              </button>
            </div>
          </div>

          {/* ─── Real-Time Live Flags Banner ─── */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '12px', marginTop: '18px', paddingTop: '16px', borderTop: '1px solid rgba(255, 255, 255, 0.08)' }}>
            {/* Flag 1: Background Noise */}
            <div style={{ background: isHighBgNoise ? 'rgba(239, 68, 68, 0.15)' : 'rgba(16, 185, 129, 0.1)', border: `1px solid ${isHighBgNoise ? '#ef4444' : '#10b981'}`, borderRadius: '10px', padding: '10px 14px', display: 'flex', alignItems: 'center', gap: '10px' }}>
              <span style={{ fontSize: '18px' }}>{isHighBgNoise ? '⚠️' : '🛡️'}</span>
              <div>
                <div style={{ fontSize: '10px', textTransform: 'uppercase', letterSpacing: '0.5px', color: isHighBgNoise ? '#fca5a5' : '#6ee7b7' }}>
                  {isHighBgNoise ? 'High Noise Alert' : 'Ambient Noise OK'}
                </div>
                <div style={{ fontSize: '13px', fontWeight: '700', color: isHighBgNoise ? '#ef4444' : '#10b981' }}>
                  RMS: {ambientRmsVal.toFixed(4)} {isHighBgNoise ? '> 0.0080' : '≤ 0.0060'}
                </div>
              </div>
            </div>

            {/* Flag 2: VAD Speech Detection */}
            <div style={{ background: isSpeaking ? 'rgba(16, 185, 129, 0.15)' : 'rgba(51, 65, 85, 0.3)', border: `1px solid ${isSpeaking ? '#10b981' : 'rgba(255, 255, 255, 0.1)'}`, borderRadius: '10px', padding: '10px 14px', display: 'flex', alignItems: 'center', gap: '10px' }}>
              <span style={{ fontSize: '18px', animation: isSpeaking ? 'pulse 1s infinite' : 'none' }}>{isSpeaking ? '🗣️' : '👂'}</span>
              <div>
                <div style={{ fontSize: '10px', textTransform: 'uppercase', letterSpacing: '0.5px', color: isSpeaking ? '#6ee7b7' : '#94a3b8' }}>
                  {isSpeaking ? 'Speech Active' : 'Listening / Silence'}
                </div>
                <div style={{ fontSize: '13px', fontWeight: '700', color: isSpeaking ? '#10b981' : '#f8fafc' }}>
                  VAD Prob: {(vadProb * 100).toFixed(0)}%
                </div>
              </div>
            </div>

            {/* Flag 3: Digital AGC & Limiter */}
            <div style={{ background: isLimiting ? 'rgba(245, 158, 11, 0.15)' : 'rgba(56, 189, 248, 0.1)', border: `1px solid ${isLimiting ? '#f59e0b' : '#38bdf8'}`, borderRadius: '10px', padding: '10px 14px', display: 'flex', alignItems: 'center', gap: '10px' }}>
              <span style={{ fontSize: '18px' }}>{isLimiting ? '⚡' : '🎚️'}</span>
              <div>
                <div style={{ fontSize: '10px', textTransform: 'uppercase', letterSpacing: '0.5px', color: isLimiting ? '#fde68a' : '#7dd3fc' }}>
                  {isLimiting ? 'Soft Limiter Active' : 'AGC Leveler'}
                </div>
                <div style={{ fontSize: '13px', fontWeight: '700', color: isLimiting ? '#f59e0b' : '#38bdf8' }}>
                  Gain: {stageMetrics.agc.gainDb >= 0 ? `+${stageMetrics.agc.gainDb.toFixed(1)}` : stageMetrics.agc.gainDb.toFixed(1)} dB
                </div>
              </div>
            </div>

            {/* Flag 4: STT WebSocket Status */}
            <div style={{ background: sessionState === 'running' ? 'rgba(129, 140, 248, 0.15)' : 'rgba(51, 65, 85, 0.3)', border: `1px solid ${sessionState === 'running' ? '#818cf8' : 'rgba(255, 255, 255, 0.1)'}`, borderRadius: '10px', padding: '10px 14px', display: 'flex', alignItems: 'center', gap: '10px' }}>
              <span style={{ fontSize: '18px' }}>🌐</span>
              <div>
                <div style={{ fontSize: '10px', textTransform: 'uppercase', letterSpacing: '0.5px', color: '#a5b4fc' }}>
                  STT Service ({selectedLanguage.toUpperCase()})
                </div>
                <div style={{ fontSize: '13px', fontWeight: '700', color: sessionState === 'running' ? '#818cf8' : '#94a3b8' }}>
                  {sessionState === 'running' ? 'Streaming Active' : sessionState.toUpperCase()}
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* ─── Optional Tuning Parameters Drawer ─── */}
        {showTuningDrawer && (
          <div style={{ background: 'rgba(15, 23, 42, 0.85)', backdropFilter: 'blur(16px)', border: '1px solid rgba(168, 85, 247, 0.3)', borderRadius: '16px', padding: '20px 28px', marginBottom: '24px' }}>
            <h3 style={{ margin: '0 0 16px', fontSize: '16px', color: '#c084fc', display: 'flex', alignItems: 'center', gap: '8px' }}>
              ⚙️ Dynamic DSP & VAD Tuning Controls
            </h3>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: '18px' }}>
              {/* HPF Cutoff */}
              <div>
                <label style={{ fontSize: '12px', color: '#94a3b8', display: 'block', marginBottom: '4px' }}>
                  HPF Cutoff Frequency: <strong style={{ color: '#38bdf8' }}>{tuningParams.hpfCutoff} Hz</strong>
                </label>
                <input
                  type="range"
                  min="40"
                  max="200"
                  step="5"
                  value={tuningParams.hpfCutoff}
                  onChange={(e) => setTuningParams({ ...tuningParams, hpfCutoff: Number(e.target.value) })}
                  style={{ width: '100%', accentColor: '#38bdf8' }}
                />
              </div>

              {/* RNNoise Strength */}
              <div>
                <label style={{ fontSize: '12px', color: '#94a3b8', display: 'block', marginBottom: '4px' }}>
                  RNNoise Suppression Strength: <strong style={{ color: '#10b981' }}>{(tuningParams.rnnoiseStrength * 100).toFixed(0)}%</strong>
                </label>
                <input
                  type="range"
                  min="0.0"
                  max="1.0"
                  step="0.05"
                  value={tuningParams.rnnoiseStrength}
                  onChange={(e) => setTuningParams({ ...tuningParams, rnnoiseStrength: Number(e.target.value) })}
                  style={{ width: '100%', accentColor: '#10b981' }}
                />
              </div>

              {/* VAD Positive Threshold */}
              <div>
                <label style={{ fontSize: '12px', color: '#94a3b8', display: 'block', marginBottom: '4px' }}>
                  VAD Speech Start Threshold: <strong style={{ color: '#a855f7' }}>{(tuningParams.positiveSpeechThreshold * 100).toFixed(0)}%</strong>
                </label>
                <input
                  type="range"
                  min="0.30"
                  max="0.95"
                  step="0.05"
                  value={tuningParams.positiveSpeechThreshold}
                  onChange={(e) => setTuningParams({ ...tuningParams, positiveSpeechThreshold: Number(e.target.value) })}
                  style={{ width: '100%', accentColor: '#a855f7' }}
                />
              </div>

              {/* AGC Target RMS */}
              <div>
                <label style={{ fontSize: '12px', color: '#94a3b8', display: 'block', marginBottom: '4px' }}>
                  AGC Target Level: <strong style={{ color: '#f59e0b' }}>{(20 * Math.log10(tuningParams.agcTargetRms)).toFixed(1)} dBFS</strong>
                </label>
                <input
                  type="range"
                  min="0.05"
                  max="0.30"
                  step="0.01"
                  value={tuningParams.agcTargetRms}
                  onChange={(e) => setTuningParams({ ...tuningParams, agcTargetRms: Number(e.target.value) })}
                  style={{ width: '100%', accentColor: '#f59e0b' }}
                />
              </div>
            </div>
          </div>
        )}

        {/* ─── 4-Stage Live VU & Metrics Matrix ─── */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: '16px', marginBottom: '24px' }}>
          {/* Stage 1: Raw Mic */}
          <div style={{ background: 'rgba(15, 23, 42, 0.7)', border: '1px solid rgba(56, 189, 248, 0.25)', borderRadius: '14px', padding: '18px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
              <span style={{ fontSize: '12px', fontWeight: '700', color: '#38bdf8' }}>STAGE 1: RAW MIC</span>
              <span style={{ fontSize: '11px', color: '#94a3b8' }}>16kHz PCM</span>
            </div>
            <div style={{ fontSize: '20px', fontWeight: '800', color: '#f8fafc', marginBottom: '4px' }}>
              {stageMetrics.raw.db.toFixed(1)} <span style={{ fontSize: '12px', color: '#94a3b8' }}>dBFS</span>
            </div>
            {/* Level Bar */}
            <div style={{ background: '#1e293b', height: '8px', borderRadius: '4px', overflow: 'hidden', margin: '8px 0' }}>
              <div style={{ width: `${Math.min(100, Math.max(0, (stageMetrics.raw.db + 60) * 1.66))}%`, height: '100%', background: 'linear-gradient(90deg, #0284c7, #38bdf8)', transition: 'width 0.05s linear' }} />
            </div>
            <div style={{ fontSize: '11px', color: '#94a3b8', display: 'flex', justifyContent: 'space-between' }}>
              <span>Peak: {stageMetrics.raw.peak.toFixed(3)}</span>
              <span>RMS: {stageMetrics.raw.rms.toFixed(4)}</span>
            </div>
          </div>

          {/* Stage 2: HPF Filter */}
          <div style={{ background: 'rgba(15, 23, 42, 0.7)', border: '1px solid rgba(168, 85, 247, 0.25)', borderRadius: '14px', padding: '18px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
              <span style={{ fontSize: '12px', fontWeight: '700', color: '#c084fc' }}>STAGE 2: HPF ({tuningParams.hpfCutoff}Hz)</span>
              <span style={{ fontSize: '11px', color: '#94a3b8' }}>IIR Filter</span>
            </div>
            <div style={{ fontSize: '20px', fontWeight: '800', color: '#f8fafc', marginBottom: '4px' }}>
              {stageMetrics.hpf.db.toFixed(1)} <span style={{ fontSize: '12px', color: '#94a3b8' }}>dBFS</span>
            </div>
            {/* Level Bar */}
            <div style={{ background: '#1e293b', height: '8px', borderRadius: '4px', overflow: 'hidden', margin: '8px 0' }}>
              <div style={{ width: `${Math.min(100, Math.max(0, (stageMetrics.hpf.db + 60) * 1.66))}%`, height: '100%', background: 'linear-gradient(90deg, #7c3aed, #c084fc)', transition: 'width 0.05s linear' }} />
            </div>
            <div style={{ fontSize: '11px', color: '#94a3b8', display: 'flex', justifyContent: 'space-between' }}>
              <span>Sub-Bass Cut: -{stageMetrics.hpf.subBassCutDb.toFixed(1)} dB</span>
              <span>RMS: {stageMetrics.hpf.rms.toFixed(4)}</span>
            </div>
          </div>

          {/* Stage 3: RNNoise */}
          <div style={{ background: 'rgba(15, 23, 42, 0.7)', border: '1px solid rgba(16, 185, 129, 0.25)', borderRadius: '14px', padding: '18px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
              <span style={{ fontSize: '12px', fontWeight: '700', color: '#34d399' }}>STAGE 3: RNNOISE AI</span>
              <span style={{ fontSize: '11px', color: '#94a3b8' }}>Neural Denoiser</span>
            </div>
            <div style={{ fontSize: '20px', fontWeight: '800', color: '#f8fafc', marginBottom: '4px' }}>
              {stageMetrics.rnnoise.db.toFixed(1)} <span style={{ fontSize: '12px', color: '#94a3b8' }}>dBFS</span>
            </div>
            {/* Level Bar */}
            <div style={{ background: '#1e293b', height: '8px', borderRadius: '4px', overflow: 'hidden', margin: '8px 0' }}>
              <div style={{ width: `${Math.min(100, Math.max(0, (stageMetrics.rnnoise.db + 60) * 1.66))}%`, height: '100%', background: 'linear-gradient(90deg, #059669, #34d399)', transition: 'width 0.05s linear' }} />
            </div>
            <div style={{ fontSize: '11px', color: '#94a3b8', display: 'flex', justifyContent: 'space-between' }}>
              <span>Noise Reduced: -{stageMetrics.rnnoise.noiseReductionDb.toFixed(1)} dB</span>
              <span>RMS: {stageMetrics.rnnoise.rms.toFixed(4)}</span>
            </div>
          </div>

          {/* Stage 4: AGC & Limiter */}
          <div style={{ background: 'rgba(15, 23, 42, 0.7)', border: '1px solid rgba(245, 158, 11, 0.25)', borderRadius: '14px', padding: '18px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
              <span style={{ fontSize: '12px', fontWeight: '700', color: '#fbbf24' }}>STAGE 4: AGC & LIMITER</span>
              <span style={{ fontSize: '11px', color: '#94a3b8' }}>Final to STT</span>
            </div>
            <div style={{ fontSize: '20px', fontWeight: '800', color: '#f8fafc', marginBottom: '4px' }}>
              {stageMetrics.agc.db.toFixed(1)} <span style={{ fontSize: '12px', color: '#94a3b8' }}>dBFS</span>
            </div>
            {/* Level Bar */}
            <div style={{ background: '#1e293b', height: '8px', borderRadius: '4px', overflow: 'hidden', margin: '8px 0' }}>
              <div style={{ width: `${Math.min(100, Math.max(0, (stageMetrics.agc.db + 60) * 1.66))}%`, height: '100%', background: 'linear-gradient(90deg, #d97706, #fbbf24)', transition: 'width 0.05s linear' }} />
            </div>
            <div style={{ fontSize: '11px', color: '#94a3b8', display: 'flex', justifyContent: 'space-between' }}>
              <span>Boost: +{stageMetrics.agc.gainDb.toFixed(1)} dB</span>
              <span>{stageMetrics.agc.isLimiting ? '⚡ Limiting' : '✅ Normalized'}</span>
            </div>
          </div>
        </div>

        {/* ─── Multi-Track Oscilloscope Canvas ─── */}
        <div style={{ background: 'rgba(15, 23, 42, 0.75)', backdropFilter: 'blur(16px)', border: '1px solid rgba(255, 255, 255, 0.1)', borderRadius: '16px', padding: '20px', marginBottom: '24px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
            <h3 style={{ margin: 0, fontSize: '15px', fontWeight: '700', color: '#f8fafc', display: 'flex', alignItems: 'center', gap: '8px' }}>
              📊 Multi-Track Telemetry & Hysteresis Oscilloscope
            </h3>
            <span style={{ fontSize: '11px', color: '#94a3b8' }}>Real-Time 16kHz Time-Series (10s window)</span>
          </div>
          <canvas
            ref={timelineCanvasRef}
            width={1380}
            height={260}
            style={{ width: '100%', height: '260px', borderRadius: '10px', display: 'block' }}
          />
        </div>

        {/* ─── Live Streaming STT Terminal ─── */}
        <div style={{ background: 'rgba(15, 23, 42, 0.85)', backdropFilter: 'blur(16px)', border: '1px solid rgba(129, 140, 248, 0.3)', borderRadius: '16px', padding: '20px 24px', marginBottom: '24px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span style={{ fontSize: '16px' }}>💬</span>
              <span style={{ fontSize: '14px', fontWeight: '700', color: '#a5b4fc' }}>
                Live STT Transcription Stream ({selectedLanguage.toUpperCase()})
              </span>
            </div>
            {transcriptLatency && (
              <span style={{ background: 'rgba(129, 140, 248, 0.15)', color: '#818cf8', padding: '2px 8px', borderRadius: '8px', fontSize: '11px', fontWeight: '600' }}>
                ⚡ Latency: {transcriptLatency} ms
              </span>
            )}
          </div>
          <div style={{ minHeight: '60px', padding: '14px 18px', background: '#090d16', borderRadius: '10px', border: '1px solid rgba(255, 255, 255, 0.05)', fontSize: '16px', color: isFinalTranscript ? '#f8fafc' : '#93c5fd', lineHeight: '1.5' }}>
            {liveTranscription ? (
              <span>
                {liveTranscription}
                {!isFinalTranscript && <span style={{ animation: 'blink 1s infinite', color: '#38bdf8' }}> ▍</span>}
              </span>
            ) : (
              <span style={{ color: '#475569', fontStyle: 'italic' }}>
                Speak into your microphone to view live streaming transcriptions here...
              </span>
            )}
          </div>
        </div>

        {/* ─── 4-Stage Utterance Auditioning & Comparison Deck ─── */}
        <div>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
            <h2 style={{ margin: 0, fontSize: '18px', fontWeight: '700', color: '#f8fafc', display: 'flex', alignItems: 'center', gap: '8px' }}>
              🎧 4-Stage Audio Auditioning Deck ({utterances.length} Captures)
            </h2>
            <div style={{ fontSize: '12px', color: '#94a3b8' }}>
              Compare audio before & after HPF, RNNoise, and AGC
            </div>
          </div>

          {utterances.length === 0 ? (
            <div style={{ textAlign: 'center', padding: '48px 20px', background: 'rgba(15, 23, 42, 0.4)', borderRadius: '16px', border: '1px dashed rgba(255, 255, 255, 0.1)', color: '#64748b' }}>
              <div style={{ fontSize: '32px', marginBottom: '8px' }}>🎙️</div>
              <div style={{ fontSize: '15px', fontWeight: '600', color: '#94a3b8' }}>No speech utterances recorded yet</div>
              <div style={{ fontSize: '13px', marginTop: '4px' }}>Click &quot;Start Voice Pipeline&quot; and speak a sentence to capture synchronized 4-stage clips.</div>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
              {utterances.map((utt) => {
                const isActive = activeUtteranceId === utt.id && isPlayingMaster;

                return (
                  <div
                    key={utt.id}
                    style={{
                      background: 'rgba(15, 23, 42, 0.75)',
                      backdropFilter: 'blur(16px)',
                      border: activeUtteranceId === utt.id ? '1px solid #38bdf8' : '1px solid rgba(255, 255, 255, 0.1)',
                      borderRadius: '16px',
                      padding: '20px 24px',
                      transition: 'all 0.2s ease',
                    }}
                  >
                    {/* Utterance Card Header */}
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '12px', marginBottom: '14px' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                        <span style={{ background: '#1e293b', color: '#cbd5e1', padding: '3px 10px', borderRadius: '8px', fontSize: '11px', fontWeight: '600' }}>
                          ⏱️ {utt.timestamp}
                        </span>
                        <span style={{ background: 'rgba(56, 189, 248, 0.15)', color: '#38bdf8', padding: '3px 10px', borderRadius: '8px', fontSize: '11px', fontWeight: '600' }}>
                          {(utt.durationMs / 1000).toFixed(2)}s Duration
                        </span>
                        <span style={{ background: 'rgba(168, 85, 247, 0.15)', color: '#c084fc', padding: '3px 10px', borderRadius: '8px', fontSize: '11px', fontWeight: '600' }}>
                          {utt.language.toUpperCase()}
                        </span>
                      </div>

                      {/* Master A/B/C/D Instant Stage Switcher */}
                      <div style={{ display: 'flex', alignItems: 'center', gap: '6px', background: '#090d16', padding: '4px 6px', borderRadius: '10px', border: '1px solid rgba(255, 255, 255, 0.1)' }}>
                        <span style={{ fontSize: '11px', color: '#94a3b8', marginRight: '4px' }}>A/B/C/D Switch:</span>
                        {[
                          { key: 'raw', label: '1. Raw', color: '#06b6d4' },
                          { key: 'hpf', label: '2. HPF', color: '#a855f7' },
                          { key: 'rnnoise', label: '3. RNNoise', color: '#10b981' },
                          { key: 'agc', label: '4. AGC (STT)', color: '#f59e0b' },
                        ].map((st) => (
                          <button
                            key={st.key}
                            onClick={() => {
                              if (activeUtteranceId === utt.id && isPlayingMaster) {
                                handleSwitchStage(st.key);
                              } else {
                                handlePlayMaster(utt.id, st.key);
                              }
                            }}
                            style={{
                              background: activeUtteranceId === utt.id && activeStageMode === st.key ? st.color : 'transparent',
                              color: activeUtteranceId === utt.id && activeStageMode === st.key ? '#000000' : st.color,
                              border: 'none',
                              padding: '4px 10px',
                              borderRadius: '6px',
                              fontSize: '11px',
                              fontWeight: '700',
                              cursor: 'pointer',
                              transition: 'all 0.15s ease',
                            }}
                          >
                            {st.label}
                          </button>
                        ))}
                      </div>
                    </div>

                    {/* Transcribed Text */}
                    <div style={{ background: '#090d16', padding: '12px 16px', borderRadius: '10px', border: '1px solid rgba(255, 255, 255, 0.05)', marginBottom: '16px', fontSize: '15px', color: '#f8fafc' }}>
                      <strong style={{ color: '#818cf8', marginRight: '6px' }}>Transcript:</strong>
                      {utt.transcription || '(Speech captured)'}
                    </div>

                    {/* 4 Individual Playable Audio Strips */}
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: '12px' }}>
                      {/* Stage 1 Audio: Raw */}
                      <div style={{ background: '#0f172a', border: '1px solid rgba(6, 182, 212, 0.3)', borderRadius: '10px', padding: '10px 14px' }}>
                        <div style={{ fontSize: '11px', fontWeight: '700', color: '#06b6d4', marginBottom: '6px' }}>
                          🔵 Stage 1: Raw Mic
                        </div>
                        {utt.urls.raw && (
                          <audio controls src={utt.urls.raw} style={{ width: '100%', height: '32px' }} />
                        )}
                      </div>

                      {/* Stage 2 Audio: HPF */}
                      <div style={{ background: '#0f172a', border: '1px solid rgba(168, 85, 247, 0.3)', borderRadius: '10px', padding: '10px 14px' }}>
                        <div style={{ fontSize: '11px', fontWeight: '700', color: '#a855f7', marginBottom: '6px' }}>
                          🟣 Stage 2: After HPF (85Hz)
                        </div>
                        {utt.urls.hpf && (
                          <audio controls src={utt.urls.hpf} style={{ width: '100%', height: '32px' }} />
                        )}
                      </div>

                      {/* Stage 3 Audio: RNNoise */}
                      <div style={{ background: '#0f172a', border: '1px solid rgba(16, 185, 129, 0.3)', borderRadius: '10px', padding: '10px 14px' }}>
                        <div style={{ fontSize: '11px', fontWeight: '700', color: '#10b981', marginBottom: '6px' }}>
                          🟢 Stage 3: After RNNoise
                        </div>
                        {utt.urls.rnnoise && (
                          <audio controls src={utt.urls.rnnoise} style={{ width: '100%', height: '32px' }} />
                        )}
                      </div>

                      {/* Stage 4 Audio: AGC */}
                      <div style={{ background: '#0f172a', border: '1px solid rgba(245, 158, 11, 0.3)', borderRadius: '10px', padding: '10px 14px' }}>
                        <div style={{ fontSize: '11px', fontWeight: '700', color: '#f59e0b', marginBottom: '6px' }}>
                          🟡 Stage 4: After AGC (Sent to STT)
                        </div>
                        {utt.urls.agc && (
                          <audio controls src={utt.urls.agc} style={{ width: '100%', height: '32px' }} />
                        )}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

      </div>
    </div>
  );
}
