'use client';

import React, { useState, useEffect, useRef, useCallback } from 'react';
import { loadVADScripts, VoiceSessionManager, unlockAudioContext } from '../utils/voiceHelper';
import { toast } from 'sonner';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080';
const WS_BASE_URL = process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8080';

// Convert Float32Array PCM samples at sampleRate to a playable WAV Blob
function float32ToWavBlob(samples, sampleRate = 16000) {
  if (!samples || samples.length === 0) return null;
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);

  const writeString = (offset, string) => {
    for (let i = 0; i < string.length; i++) {
      view.setUint8(offset + i, string.charCodeAt(i));
    }
  };

  writeString(0, 'RIFF');
  view.setUint32(4, 36 + samples.length * 2, true);
  writeString(8, 'WAVE');
  writeString(12, 'fmt ');
  view.setUint32(16, 16, true); // Subchunk1Size (16 for PCM)
  view.setUint16(20, 1, true);  // AudioFormat (1 for PCM)
  view.setUint16(22, 1, true);  // NumChannels (1 for mono)
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true); // ByteRate
  view.setUint16(32, 2, true);  // BlockAlign
  view.setUint16(34, 16, true); // BitsPerSample
  writeString(36, 'data');
  view.setUint32(40, samples.length * 2, true);

  let offset = 44;
  for (let i = 0; i < samples.length; i++, offset += 2) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7FFF, true);
  }

  return new Blob([view], { type: 'audio/wav' });
}

export default function STTSandboxPage() {
  // Session & Auth state
  const [token, setToken] = useState('');
  const [sessionId, setSessionId] = useState('');
  const [isConnected, setIsConnected] = useState(false);
  const [sessionState, setSessionState] = useState('disconnected'); // disconnected, connecting, ready, listening, processing
  const [sttLanguage, setSttLanguage] = useState('hi');

  // Dynamic VAD Options
  const [positiveSpeechThreshold, setPositiveSpeechThreshold] = useState(0.50);
  const [negativeSpeechThreshold, setNegativeSpeechThreshold] = useState(0.25);
  const [minSpeechFrames, setMinSpeechFrames] = useState(2);
  const [preSpeechPadFrames, setPreSpeechPadFrames] = useState(14);
  const [redemptionFrames, setRedemptionFrames] = useState(8);
  const [noiseSuppression, setNoiseSuppression] = useState(false);
  const [autoGainControl, setAutoGainControl] = useState(true);
  const [echoCancellation, setEchoCancellation] = useState(true);

  // Current Utterance Data & Visualizer State
  const [currentUtterance, setCurrentUtterance] = useState(null);
  const [sttText, setSttText] = useState('');
  const [sttLatency, setSttLatency] = useState(null);
  const [volumeLevel, setVolumeLevel] = useState(0);

  // Benchmark / Test History Log
  const [history, setHistory] = useState([]);

  // Refs
  const sessionManagerRef = useRef(null);
  const canvasRef = useRef(null);
  const audioContextRef = useRef(null);
  const tSpeechEndRef = useRef(null);
  const activeAudioSourceRef = useRef(null);

  // Initialize Auth / Session credentials
  useEffect(() => {
    let t = typeof window !== 'undefined' ? localStorage.getItem('token') : null;
    let s = typeof window !== 'undefined' ? localStorage.getItem('session_id') : null;
    if (!t) {
      t = 'sandbox_test_token';
      if (typeof window !== 'undefined') localStorage.setItem('token', t);
    }
    if (!s) {
      s = `sandbox_${Date.now()}`;
      if (typeof window !== 'undefined') localStorage.setItem('session_id', s);
    }
    setToken(t);
    setSessionId(s);

    // Pre-load VAD scripts
    loadVADScripts().then((loaded) => {
      if (loaded) {
        console.log('[STTSandbox] VAD libraries loaded successfully');
      } else {
        toast.error('Failed to load VAD libraries');
      }
    });
  }, []);

  // Connect or Reconnect Session with current VAD Config
  const handleStartSession = async () => {
    unlockAudioContext();
    if (sessionManagerRef.current) {
      sessionManagerRef.current.disconnect();
      sessionManagerRef.current = null;
    }

    setSessionState('connecting');
    toast.info('Initializing Voice Session with dynamic VAD settings...');

    const manager = new VoiceSessionManager({
      token,
      sessionId,
      applicationId: sessionId,
      schemeId: 'stt-sandbox',
      language: sttLanguage,
      wsUrl: `${WS_BASE_URL.replace('http', 'ws')}/ws/voice?token=${token}&session_id=${sessionId}&scheme_id=stt-sandbox`,

      vadOptions: {
        positiveSpeechThreshold,
        negativeSpeechThreshold,
        minSpeechFrames,
        preSpeechPadFrames,
        redemptionFrames,
        additionalAudioConstraints: {
          noiseSuppression,
          autoGainControl,
          echoCancellation
        }
      },

      onStateChange: (state) => {
        setSessionState(state);
        if (state === 'listening') {
          setSttText('');
          setSttLatency(null);
        }
      },

      onTranscript: (data) => {
        if (data && data.text) {
          const tNow = performance.now();
          setSttText(data.text);
          let latency = null;
          if (tSpeechEndRef.current) {
            latency = Math.round(tNow - tSpeechEndRef.current);
            setSttLatency(latency);
          }

          // Append to history log
          setHistory((prev) => [
            {
              id: Date.now(),
              time: new Date().toLocaleTimeString(),
              text: data.text,
              latency,
              config: {
                posThresh: positiveSpeechThreshold,
                negThresh: negativeSpeechThreshold,
                prePad: preSpeechPadFrames,
                redemption: redemptionFrames,
                lang: sttLanguage
              }
            },
            ...prev
          ]);
        }
      },

      onSystemMessage: (type, text) => {
        console.log(`[STTSandbox] SystemMessage (${type}): ${text}`);
      },

      onError: (err) => {
        console.error('[STTSandbox] Error:', err);
        toast.error(`Session Error: ${err}`);
      }
    });

    // Register custom callbacks for raw VAD audio & volume level
    manager.onSpeechEndCallback = (audioFloat32) => {
      tSpeechEndRef.current = performance.now();
      if (!audioFloat32 || audioFloat32.length === 0) return;

      // Silero VAD frame size: 1 frame = 1536 samples (96ms at 16kHz)
      const sampleRate = 16000;
      const totalSamples = audioFloat32.length;
      const totalMs = Math.round((totalSamples / sampleRate) * 1000);

      // Pre-roll samples & redemption samples calculation
      const preRollSamples = Math.min(preSpeechPadFrames * 1536, totalSamples);
      const redemptionSamples = Math.min(redemptionFrames * 1536, totalSamples - preRollSamples);
      const activeSpeechSamples = Math.max(0, totalSamples - preRollSamples - redemptionSamples);

      const preRollMs = Math.round((preRollSamples / sampleRate) * 1000);
      const activeMs = Math.round((activeSpeechSamples / sampleRate) * 1000);
      const redemptionMs = Math.round((redemptionSamples / sampleRate) * 1000);

      // SliceFloat32 buffers for individual segment playback
      const preRollBuffer = audioFloat32.slice(0, preRollSamples);
      const activeSpeechBuffer = audioFloat32.slice(preRollSamples, preRollSamples + activeSpeechSamples);
      const redemptionBuffer = audioFloat32.slice(preRollSamples + activeSpeechSamples);

      const utteranceData = {
        fullAudio: audioFloat32,
        preRollAudio: preRollBuffer,
        activeSpeechAudio: activeSpeechBuffer,
        redemptionAudio: redemptionBuffer,
        sampleRate,
        totalSamples,
        totalMs,
        preRollMs,
        activeMs,
        redemptionMs,
        preRollSamples,
        activeSpeechSamples,
        redemptionSamples,
        fullBlob: float32ToWavBlob(audioFloat32, sampleRate),
        preRollBlob: float32ToWavBlob(preRollBuffer, sampleRate),
        activeSpeechBlob: float32ToWavBlob(activeSpeechBuffer, sampleRate),
        redemptionBlob: float32ToWavBlob(redemptionBuffer, sampleRate)
      };

      setCurrentUtterance(utteranceData);
    };

    manager.onVolumeLevelCallback = (vol) => {
      setVolumeLevel(vol);
    };

    await manager.connect();
    sessionManagerRef.current = manager;
    manager.startListening();
    setIsConnected(true);
    toast.success('Connected & Listening! Speak into your microphone.');
  };

  const handleStopSession = () => {
    if (sessionManagerRef.current) {
      sessionManagerRef.current.disconnect();
      sessionManagerRef.current = null;
    }
    setIsConnected(false);
    setSessionState('disconnected');
    toast.info('Session stopped.');
  };

  // Audio Playback Helper
  const playAudioBuffer = (float32Array) => {
    if (!float32Array || float32Array.length === 0) {
      toast.warning('No audio samples available for this segment');
      return;
    }

    if (activeAudioSourceRef.current) {
      try { activeAudioSourceRef.current.stop(); } catch (e) {}
    }

    const ctx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
    const buffer = ctx.createBuffer(1, float32Array.length, 16000);
    buffer.getChannelData(0).set(float32Array);

    const source = ctx.createBufferSource();
    source.buffer = buffer;
    source.connect(ctx.destination);
    source.start(0);
    activeAudioSourceRef.current = source;
  };

  // Draw Audio Waveform & Timeline canvas
  const drawWaveformTimeline = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas || !currentUtterance) return;
    const ctx = canvas.getContext('2d');
    const width = canvas.width;
    const height = canvas.height;

    // Clear background
    ctx.fillStyle = '#0a0d14';
    ctx.fillRect(0, 0, width, height);

    const { fullAudio, totalSamples, preRollSamples, redemptionSamples } = currentUtterance;
    if (!fullAudio || totalSamples === 0) return;

    const speechStartFrac = preRollSamples / totalSamples;
    const speechEndFrac = (totalSamples - redemptionSamples) / totalSamples;

    // Render 3 Segment Regions
    // 1. Pre-roll Buffer (Amber)
    ctx.fillStyle = 'rgba(245, 158, 11, 0.18)';
    ctx.fillRect(0, 0, width * speechStartFrac, height);

    // 2. Active Speech Body (Emerald)
    ctx.fillStyle = 'rgba(16, 185, 129, 0.18)';
    ctx.fillRect(width * speechStartFrac, 0, width * (speechEndFrac - speechStartFrac), height);

    // 3. Hangover Redemption (Indigo)
    ctx.fillStyle = 'rgba(99, 102, 241, 0.18)';
    ctx.fillRect(width * speechEndFrac, 0, width * (1 - speechEndFrac), height);

    // Draw Audio Waveform (Centered)
    ctx.beginPath();
    ctx.strokeStyle = '#38bdf8';
    ctx.lineWidth = 1.5;

    const step = Math.max(1, Math.floor(totalSamples / width));
    const centerY = height / 2;

    for (let i = 0; i < width; i++) {
      const sampleIdx = Math.floor(i * step);
      const val = fullAudio[sampleIdx] || 0;
      const y = centerY - val * (height / 2 - 10);
      if (i === 0) ctx.moveTo(i, y);
      else ctx.lineTo(i, y);
    }
    ctx.stroke();

    // Vertical Divider Lines
    // Speech Start Line
    const xStart = width * speechStartFrac;
    ctx.strokeStyle = '#f59e0b';
    ctx.lineWidth = 2;
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    ctx.moveTo(xStart, 0);
    ctx.lineTo(xStart, height);
    ctx.stroke();

    // Speech End Line
    const xEnd = width * speechEndFrac;
    ctx.strokeStyle = '#6366f1';
    ctx.beginPath();
    ctx.moveTo(xEnd, 0);
    ctx.lineTo(xEnd, height);
    ctx.stroke();

    ctx.setLineDash([]); // Reset dash

    // Text Markers & Labels
    ctx.font = '11px sans-serif';
    ctx.fillStyle = '#f59e0b';
    ctx.fillText(`Pre-Roll Guard (${currentUtterance.preRollMs}ms)`, 8, 18);

    ctx.fillStyle = '#10b981';
    ctx.fillText(`Active Speech (${currentUtterance.activeMs}ms)`, xStart + 8, 18);

    ctx.fillStyle = '#818cf8';
    ctx.fillText(`Hangover (${currentUtterance.redemptionMs}ms)`, xEnd + 8, 18);
  }, [currentUtterance]);

  useEffect(() => {
    drawWaveformTimeline();
  }, [drawWaveformTimeline]);

  return (
    <div style={{
      minHeight: '100vh',
      backgroundColor: '#05070c',
      color: '#e2e8f0',
      fontFamily: 'Inter, system-ui, -apple-system, sans-serif',
      padding: '24px'
    }}>
      {/* Top Header */}
      <div style={{
        maxWidth: '1300px',
        margin: '0 auto 24px auto',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        borderBottom: '1px solid rgba(255, 255, 255, 0.08)',
        paddingBottom: '16px'
      }}>
        <div>
          <h1 style={{ fontSize: '24px', fontWeight: '700', margin: 0, color: '#f8fafc' }}>
            🎙️ Speech-to-Text & VAD Tuning Sandbox
          </h1>
          <p style={{ fontSize: '13px', color: '#94a3b8', margin: '4px 0 0 0' }}>
            Inspect VAD pre-roll buffer, speech timestamps, STT accuracy & latency using existing production pipeline
          </p>
        </div>

        {/* Status Badge */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <div style={{
            padding: '6px 14px',
            borderRadius: '20px',
            fontSize: '12px',
            fontWeight: '600',
            backgroundColor: sessionState === 'listening' ? 'rgba(16, 185, 129, 0.15)' :
                             sessionState === 'processing' ? 'rgba(245, 158, 11, 0.15)' : 'rgba(255, 255, 255, 0.05)',
            color: sessionState === 'listening' ? '#34d399' :
                   sessionState === 'processing' ? '#fbbf24' : '#94a3b8',
            border: '1px solid currentColor'
          }}>
            State: {sessionState.toUpperCase()}
          </div>

          {!isConnected ? (
            <button
              onClick={handleStartSession}
              style={{
                backgroundColor: '#2563eb',
                color: '#fff',
                border: 'none',
                padding: '10px 20px',
                borderRadius: '8px',
                fontWeight: '600',
                cursor: 'pointer',
                fontSize: '14px',
                boxShadow: '0 4px 12px rgba(37, 99, 235, 0.3)'
              }}
            >
              Start VAD & Voice Engine
            </button>
          ) : (
            <button
              onClick={handleStopSession}
              style={{
                backgroundColor: '#dc2626',
                color: '#fff',
                border: 'none',
                padding: '10px 20px',
                borderRadius: '8px',
                fontWeight: '600',
                cursor: 'pointer',
                fontSize: '14px'
              }}
            >
              Disconnect
            </button>
          )}
        </div>
      </div>

      {/* Main Grid Layout */}
      <div style={{
        maxWidth: '1300px',
        margin: '0 auto',
        display: 'grid',
        gridTemplateColumns: '360px 1fr',
        gap: '24px'
      }}>
        {/* Left Column: Dynamic VAD Settings */}
        <div style={{
          backgroundColor: '#0f172a',
          borderRadius: '12px',
          padding: '20px',
          border: '1px solid rgba(255, 255, 255, 0.08)'
        }}>
          <h2 style={{ fontSize: '16px', fontWeight: '600', marginBottom: '16px', color: '#38bdf8' }}>
            ⚙️ VAD & Audio Buffer Controls
          </h2>

          {/* Positive Speech Threshold */}
          <div style={{ marginBottom: '18px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '13px', marginBottom: '6px' }}>
              <span>Positive Threshold (Activation):</span>
              <strong style={{ color: '#38bdf8' }}>{positiveSpeechThreshold.toFixed(2)}</strong>
            </div>
            <input
              type="range"
              min="0.10"
              max="0.95"
              step="0.01"
              value={positiveSpeechThreshold}
              onChange={(e) => setPositiveSpeechThreshold(parseFloat(e.target.value))}
              style={{ width: '100%', accentColor: '#38bdf8' }}
            />
            <small style={{ fontSize: '11px', color: '#64748b' }}>Lower = easily triggers on soft speech like "Haa"</small>
          </div>

          {/* Negative Speech Threshold */}
          <div style={{ marginBottom: '18px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '13px', marginBottom: '6px' }}>
              <span>Negative Threshold (Deactivation):</span>
              <strong style={{ color: '#38bdf8' }}>{negativeSpeechThreshold.toFixed(2)}</strong>
            </div>
            <input
              type="range"
              min="0.10"
              max="0.90"
              step="0.01"
              value={negativeSpeechThreshold}
              onChange={(e) => setNegativeSpeechThreshold(parseFloat(e.target.value))}
              style={{ width: '100%', accentColor: '#38bdf8' }}
            />
            <small style={{ fontSize: '11px', color: '#64748b' }}>Lower = holds hangover silence longer before end</small>
          </div>

          {/* Pre-Speech Pad Frames */}
          <div style={{ marginBottom: '18px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '13px', marginBottom: '6px' }}>
              <span>Pre-Roll Guard Buffer:</span>
              <strong style={{ color: '#f59e0b' }}>{preSpeechPadFrames} frames (~{Math.round(preSpeechPadFrames * 96)}ms)</strong>
            </div>
            <input
              type="range"
              min="0"
              max="30"
              step="1"
              value={preSpeechPadFrames}
              onChange={(e) => setPreSpeechPadFrames(parseInt(e.target.value))}
              style={{ width: '100%', accentColor: '#f59e0b' }}
            />
            <small style={{ fontSize: '11px', color: '#64748b' }}>Pre-roll padding buffer to catch initial syllable</small>
          </div>

          {/* Redemption Frames */}
          <div style={{ marginBottom: '18px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '13px', marginBottom: '6px' }}>
              <span>Hangover Silence (Redemption):</span>
              <strong style={{ color: '#818cf8' }}>{redemptionFrames} frames (~{Math.round(redemptionFrames * 96)}ms)</strong>
            </div>
            <input
              type="range"
              min="1"
              max="30"
              step="1"
              value={redemptionFrames}
              onChange={(e) => setRedemptionFrames(parseInt(e.target.value))}
              style={{ width: '100%', accentColor: '#818cf8' }}
            />
            <small style={{ fontSize: '11px', color: '#64748b' }}>Silence duration before triggering speech_end</small>
          </div>

          {/* Min Speech Frames */}
          <div style={{ marginBottom: '18px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '13px', marginBottom: '6px' }}>
              <span>Min Verification Frames:</span>
              <strong style={{ color: '#38bdf8' }}>{minSpeechFrames} frames (~{Math.round(minSpeechFrames * 96)}ms)</strong>
            </div>
            <input
              type="range"
              min="1"
              max="10"
              step="1"
              value={minSpeechFrames}
              onChange={(e) => setMinSpeechFrames(parseInt(e.target.value))}
              style={{ width: '100%', accentColor: '#38bdf8' }}
            />
          </div>

          {/* Language Selection */}
          <div style={{ marginBottom: '18px' }}>
            <label style={{ display: 'block', fontSize: '13px', marginBottom: '6px' }}>STT Language:</label>
            <select
              value={sttLanguage}
              onChange={(e) => setSttLanguage(e.target.value)}
              style={{
                width: '100%',
                padding: '8px 12px',
                borderRadius: '6px',
                backgroundColor: '#1e293b',
                color: '#fff',
                border: '1px solid rgba(255,255,255,0.1)'
              }}
            >
              <option value="hi">Hindi (hi-IN)</option>
              <option value="mr">Marathi (mr-IN)</option>
              <option value="en">English (en-US)</option>
              <option value="fr">French (fr-FR)</option>
              <option value="ar">Arabic (ar-XA)</option>
            </select>
          </div>

          {/* Mic Constraints Toggles */}
          <div style={{ fontSize: '13px', display: 'flex', flexDirection: 'column', gap: '10px', marginTop: '12px' }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer' }}>
              <input
                type="checkbox"
                checked={noiseSuppression}
                onChange={(e) => setNoiseSuppression(e.target.checked)}
              />
              <span>Browser Noise Suppression</span>
            </label>
            <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer' }}>
              <input
                type="checkbox"
                checked={autoGainControl}
                onChange={(e) => setAutoGainControl(e.target.checked)}
              />
              <span>Auto Gain Control (AGC)</span>
            </label>
          </div>

          {/* Apply & Reconnect Button */}
          {isConnected && (
            <button
              onClick={handleStartSession}
              style={{
                marginTop: '20px',
                width: '100%',
                backgroundColor: '#0284c7',
                color: '#fff',
                border: 'none',
                padding: '10px',
                borderRadius: '6px',
                fontWeight: '600',
                cursor: 'pointer'
              }}
            >
              Apply Settings & Reconnect
            </button>
          )}
        </div>

        {/* Right Column: Audio Timeline, Visualizer & Transcription */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
          {/* Live Volume Meter */}
          <div style={{
            backgroundColor: '#0f172a',
            borderRadius: '12px',
            padding: '16px 20px',
            border: '1px solid rgba(255, 255, 255, 0.08)',
            display: 'flex',
            alignItems: 'center',
            gap: '16px'
          }}>
            <span style={{ fontSize: '13px', fontWeight: '600', minWidth: '100px' }}>Mic Level:</span>
            <div style={{
              flex: 1,
              height: '10px',
              backgroundColor: '#1e293b',
              borderRadius: '5px',
              overflow: 'hidden'
            }}>
              <div style={{
                height: '100%',
                width: `${Math.min(100, volumeLevel * 100)}%`,
                backgroundColor: volumeLevel > 0.6 ? '#ef4444' : volumeLevel > 0.2 ? '#10b981' : '#38bdf8',
                transition: 'width 50ms ease-out'
              }} />
            </div>
          </div>

          {/* STT Result Card */}
          <div style={{
            backgroundColor: '#0f172a',
            borderRadius: '12px',
            padding: '20px',
            border: '1px solid rgba(255, 255, 255, 0.08)'
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
              <h2 style={{ fontSize: '16px', fontWeight: '600', margin: 0, color: '#f8fafc' }}>
                🔤 STT Transcription Result
              </h2>
              {sttLatency && (
                <span style={{ fontSize: '12px', fontWeight: '600', color: '#10b981', backgroundColor: 'rgba(16,185,129,0.1)', padding: '4px 10px', borderRadius: '12px' }}>
                  Latency: {sttLatency} ms
                </span>
              )}
            </div>

            <div style={{
              minHeight: '60px',
              backgroundColor: '#05070c',
              borderRadius: '8px',
              padding: '16px',
              fontSize: '18px',
              fontWeight: '500',
              color: sttText ? '#f8fafc' : '#64748b',
              border: '1px solid rgba(255, 255, 255, 0.05)'
            }}>
              {sttText || (sessionState === 'listening' ? 'Speak into microphone...' : sessionState === 'processing' ? 'Processing STT...' : 'Waiting for speech utterance...')}
            </div>
          </div>

          {/* Audio Waveform & Timeline Visualization */}
          {currentUtterance && (
            <div style={{
              backgroundColor: '#0f172a',
              borderRadius: '12px',
              padding: '20px',
              border: '1px solid rgba(255, 255, 255, 0.08)'
            }}>
              <h2 style={{ fontSize: '16px', fontWeight: '600', marginBottom: '14px', color: '#f8fafc' }}>
                📈 Audio Utterance Timeline & Buffer Inspection
              </h2>

              <canvas
                ref={canvasRef}
                width={850}
                height={160}
                style={{
                  width: '100%',
                  height: '160px',
                  borderRadius: '8px',
                  border: '1px solid rgba(255, 255, 255, 0.1)',
                  backgroundColor: '#05070c'
                }}
              />

              {/* Segment Breakdowns & Playback Buttons */}
              <div style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(4, 1fr)',
                gap: '12px',
                marginTop: '16px'
              }}>
                {/* Full Audio */}
                <div style={{ backgroundColor: '#1e293b', padding: '12px', borderRadius: '8px', textAlign: 'center' }}>
                  <div style={{ fontSize: '12px', color: '#94a3b8', marginBottom: '4px' }}>Total Utterance</div>
                  <strong style={{ fontSize: '15px', color: '#f8fafc' }}>{currentUtterance.totalMs} ms</strong>
                  <button
                    onClick={() => playAudioBuffer(currentUtterance.fullAudio)}
                    style={{
                      marginTop: '8px',
                      width: '100%',
                      padding: '6px',
                      backgroundColor: '#3b82f6',
                      color: '#fff',
                      border: 'none',
                      borderRadius: '4px',
                      fontSize: '12px',
                      fontWeight: '600',
                      cursor: 'pointer'
                    }}
                  >
                    ▶ Play Full
                  </button>
                </div>

                {/* Pre-roll Guard Buffer */}
                <div style={{ backgroundColor: '#1e293b', padding: '12px', borderRadius: '8px', textAlign: 'center', borderTop: '3px solid #f59e0b' }}>
                  <div style={{ fontSize: '12px', color: '#f59e0b', marginBottom: '4px' }}>Pre-Roll Buffer</div>
                  <strong style={{ fontSize: '15px', color: '#f8fafc' }}>{currentUtterance.preRollMs} ms</strong>
                  <button
                    onClick={() => playAudioBuffer(currentUtterance.preRollAudio)}
                    style={{
                      marginTop: '8px',
                      width: '100%',
                      padding: '6px',
                      backgroundColor: '#f59e0b',
                      color: '#000',
                      border: 'none',
                      borderRadius: '4px',
                      fontSize: '12px',
                      fontWeight: '600',
                      cursor: 'pointer'
                    }}
                  >
                    ▶ Play Guard
                  </button>
                </div>

                {/* Active Speech Body */}
                <div style={{ backgroundColor: '#1e293b', padding: '12px', borderRadius: '8px', textAlign: 'center', borderTop: '3px solid #10b981' }}>
                  <div style={{ fontSize: '12px', color: '#10b981', marginBottom: '4px' }}>Active Speech</div>
                  <strong style={{ fontSize: '15px', color: '#f8fafc' }}>{currentUtterance.activeMs} ms</strong>
                  <button
                    onClick={() => playAudioBuffer(currentUtterance.activeSpeechAudio)}
                    style={{
                      marginTop: '8px',
                      width: '100%',
                      padding: '6px',
                      backgroundColor: '#10b981',
                      color: '#fff',
                      border: 'none',
                      borderRadius: '4px',
                      fontSize: '12px',
                      fontWeight: '600',
                      cursor: 'pointer'
                    }}
                  >
                    ▶ Play Speech
                  </button>
                </div>

                {/* Hangover Redemption */}
                <div style={{ backgroundColor: '#1e293b', padding: '12px', borderRadius: '8px', textAlign: 'center', borderTop: '3px solid #818cf8' }}>
                  <div style={{ fontSize: '12px', color: '#818cf8', marginBottom: '4px' }}>Hangover Silence</div>
                  <strong style={{ fontSize: '15px', color: '#f8fafc' }}>{currentUtterance.redemptionMs} ms</strong>
                  <button
                    onClick={() => playAudioBuffer(currentUtterance.redemptionAudio)}
                    style={{
                      marginTop: '8px',
                      width: '100%',
                      padding: '6px',
                      backgroundColor: '#6366f1',
                      color: '#fff',
                      border: 'none',
                      borderRadius: '4px',
                      fontSize: '12px',
                      fontWeight: '600',
                      cursor: 'pointer'
                    }}
                  >
                    ▶ Play Hangover
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* Test History Benchmark Log */}
          {history.length > 0 && (
            <div style={{
              backgroundColor: '#0f172a',
              borderRadius: '12px',
              padding: '20px',
              border: '1px solid rgba(255, 255, 255, 0.08)'
            }}>
              <h2 style={{ fontSize: '16px', fontWeight: '600', marginBottom: '14px', color: '#f8fafc' }}>
                📋 Session Benchmark Log
              </h2>

              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '13px', textAlign: 'left' }}>
                  <thead>
                    <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.1)', color: '#94a3b8' }}>
                      <th style={{ padding: '8px' }}>Time</th>
                      <th style={{ padding: '8px' }}>STT Output</th>
                      <th style={{ padding: '8px' }}>Latency</th>
                      <th style={{ padding: '8px' }}>Pos Thresh</th>
                      <th style={{ padding: '8px' }}>Pre-Roll Pad</th>
                      <th style={{ padding: '8px' }}>Redemption</th>
                    </tr>
                  </thead>
                  <tbody>
                    {history.map((item) => (
                      <tr key={item.id} style={{ borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
                        <td style={{ padding: '8px', color: '#64748b' }}>{item.time}</td>
                        <td style={{ padding: '8px', fontWeight: '500', color: '#38bdf8' }}>{item.text}</td>
                        <td style={{ padding: '8px', color: '#10b981' }}>{item.latency ? `${item.latency} ms` : '-'}</td>
                        <td style={{ padding: '8px' }}>{item.config.posThresh}</td>
                        <td style={{ padding: '8px', color: '#f59e0b' }}>{item.config.prePad} fr</td>
                        <td style={{ padding: '8px', color: '#818cf8' }}>{item.config.redemption} fr</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
