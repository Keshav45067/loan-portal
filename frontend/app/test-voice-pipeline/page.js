'use client';

import React, { useState, useEffect, useRef, useCallback } from 'react';
import { loadVADScripts, VoiceSessionManager, unlockAudioContext } from '../utils/voiceHelper';
import { VoiceSessionManagerRobust } from '../utils/voiceHelperRobust';
import { toast } from 'sonner';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080';
const WS_BASE_URL = process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8080';

export default function VoicePipelineComparisonDashboard() {
  // === Shared Session Config ===
  const [token, setToken] = useState('sandbox_test_token');
  const [sessionIdClassic, setSessionIdClassic] = useState('');
  const [sessionIdRobust, setSessionIdRobust] = useState('');
  const [schemeId, setSchemeId] = useState('mudra-grocery');
  const [language, setLanguage] = useState('hi');
  const [vadLibrariesLoaded, setVadLibrariesLoaded] = useState(false);

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

  // === Classic Pipeline State ===
  const [classicState, setClassicState] = useState('idle'); // idle, connecting, listening, processing, speaking
  const [classicVolume, setClassicVolume] = useState(0);
  const [classicTranscripts, setClassicTranscripts] = useState([]);
  const [classicExtractions, setClassicExtractions] = useState({});
  const classicManagerRef = useRef(null);

  // === Robust Pipeline State ===
  const [robustState, setRobustState] = useState('idle');
  const [robustVolume, setRobustVolume] = useState(0);
  const [robustTranscripts, setRobustTranscripts] = useState([]);
  const [robustExtractions, setRobustExtractions] = useState({});
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
  const robustManagerRef = useRef(null);

  // === Real-time Frame Log & Stats ===
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

  // === UX Alerts State ===
  const [ambientAlert, setAmbientAlert] = useState(null);
  const [speakCloserAlert, setSpeakCloserAlert] = useState(null);

  // Initialize Session IDs & VAD on mount
  useEffect(() => {
    const s1 = `classic_${Date.now().toString().slice(-6)}`;
    const s2 = `robust_${Date.now().toString().slice(-6)}`;
    setSessionIdClassic(s1);
    setSessionIdRobust(s2);

    loadVADScripts().then((loaded) => {
      setVadLibrariesLoaded(loaded);
      if (loaded) {
        toast.success('VAD ONNX libraries loaded successfully');
      } else {
        toast.error('Failed to load VAD libraries');
      }
    });

    return () => {
      stopClassic();
      stopRobust();
    };
  }, []);

  // Update Robust Config on Tuning Change
  useEffect(() => {
    if (robustManagerRef.current) {
      robustManagerRef.current.updateProcessorConfig(tuningParams);
    }
  }, [tuningParams]);

  // Auto-scroll logs container
  useEffect(() => {
    if (autoScrollLogs && logsContainerRef.current) {
      logsContainerRef.current.scrollTop = logsContainerRef.current.scrollHeight;
    }
  }, [frameLogs, autoScrollLogs]);

  // === Classic Pipeline Handlers ===
  const startClassic = () => {
    unlockAudioContext();
    stopClassic();

    const manager = new VoiceSessionManager({
      token,
      sessionId: sessionIdClassic,
      schemeId,
      language,
      wsUrl: `${WS_BASE_URL}/ws/voice`,
      applicantName: 'Applicant',
      vadOptions: {
        positiveSpeechThreshold: tuningParams.positiveSpeechThreshold,
        negativeSpeechThreshold: tuningParams.negativeSpeechThreshold,
      },
      onStateChange: (state) => setClassicState(state),
      onVolumeLevel: (vol) => setClassicVolume(vol),
      onTranscript: (text, isFinal) => {
        setClassicTranscripts((prev) => [
          ...prev.slice(-15),
          { text, isFinal, time: new Date().toLocaleTimeString(), sender: 'system' }
        ]);
      },
      onExtraction: (fields) => {
        setClassicExtractions((prev) => ({ ...prev, ...fields }));
      },
      onSystemMessage: (type, msg) => {
        if (type === 'error') toast.error(`[Classic] ${msg}`);
      },
    });

    classicManagerRef.current = manager;
    manager.connect();
  };

  const stopClassic = () => {
    if (classicManagerRef.current) {
      classicManagerRef.current.disconnect();
      classicManagerRef.current = null;
    }
    setClassicState('idle');
    setClassicVolume(0);
  };

  // === Robust Pipeline Handlers ===
  const startRobust = () => {
    unlockAudioContext();
    stopRobust();

    const manager = new VoiceSessionManagerRobust({
      token,
      sessionId: sessionIdRobust,
      schemeId,
      language,
      wsUrl: `${WS_BASE_URL}/ws/voice`,
      applicantName: 'Applicant',
      vadOptions: {
        ...tuningParams,
      },
      onStateChange: (state) => setRobustState(state),
      onVolumeLevel: (vol) => setRobustVolume(vol),
      onTranscript: (text, isFinal) => {
        setRobustTranscripts((prev) => [
          ...prev.slice(-15),
          { text, isFinal, time: new Date().toLocaleTimeString(), sender: 'system' }
        ]);
      },
      onExtraction: (fields) => {
        setRobustExtractions((prev) => ({ ...prev, ...fields }));
      },
      onDiagnostics: (diag) => {
        setCurrentDiag(diag);

        // Update real-time frame logs
        setFrameLogs((prev) => {
          const newEntry = {
            id: Date.now() + Math.random(),
            time: new Date().toLocaleTimeString() + `.${(Date.now() % 1000).toString().padStart(3, '0')}`,
            ...diag,
          };
          return [...prev.slice(-99), newEntry];
        });

        // Update Aggregate Stats
        if (robustManagerRef.current) {
          const st = robustManagerRef.current.getStats();
          if (st) setStats({ ...st });
        }
      },
      onSpeechTooQuiet: (data) => {
        setSpeakCloserAlert({
          message: 'कृपया माइक के थोड़ा पास आकर बोलें (Speak Closer)',
          timestamp: Date.now(),
        });
        toast.warning('⚠️ Speech too quiet / far away — please speak closer');
        setTimeout(() => setSpeakCloserAlert(null), 4000);
      },
      onHighBackgroundNoise: (data) => {
        if (data.active) {
          setAmbientAlert({
            message: `उच्च पृष्ठभूमि शोर (High Background Noise: RMS ${(data.ambientRms * 100).toFixed(2)}%)`,
          });
        } else {
          setAmbientAlert(null);
        }
      },
      onSystemMessage: (type, msg) => {
        if (type === 'error') toast.error(`[Robust] ${msg}`);
      },
    });

    robustManagerRef.current = manager;
    manager.connect();
  };

  const stopRobust = () => {
    if (robustManagerRef.current) {
      robustManagerRef.current.disconnect();
      robustManagerRef.current = null;
    }
    setRobustState('idle');
    setRobustVolume(0);
    setCurrentDiag((prev) => ({ ...prev, classification: 'SILENT', isStreaming: false }));
  };

  const startBoth = () => {
    startClassic();
    startRobust();
  };

  const stopBoth = () => {
    stopClassic();
    stopRobust();
  };

  const clearAllData = () => {
    setClassicTranscripts([]);
    setRobustTranscripts([]);
    setClassicExtractions({});
    setRobustExtractions({});
    setFrameLogs([]);
    if (robustManagerRef.current) {
      robustManagerRef.current.resetStats();
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

  // Helper formatting for classification badge
  const getClassificationBadge = (cls) => {
    switch (cls) {
      case 'SPEECH_NEAR':
        return <span style={{ backgroundColor: '#059669', color: '#fff', padding: '3px 8px', borderRadius: 4, fontWeight: 700, fontSize: '0.78rem' }}>🟢 SPEECH_NEAR (Near-field)</span>;
      case 'SPEECH_FAR':
        return <span style={{ backgroundColor: '#d97706', color: '#fff', padding: '3px 8px', borderRadius: 4, fontWeight: 700, fontSize: '0.78rem' }}>🟡 SPEECH_FAR (Too Quiet/Far)</span>;
      case 'NOISE_ONLY':
        return <span style={{ backgroundColor: '#dc2626', color: '#fff', padding: '3px 8px', borderRadius: 4, fontWeight: 700, fontSize: '0.78rem' }}>🔴 NOISE_ONLY (Ambient Noise)</span>;
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

  return (
    <div style={{ minHeight: '100vh', backgroundColor: '#0f172a', color: '#f8fafc', fontFamily: 'Inter, system-ui, sans-serif', padding: '24px' }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid #334155', paddingBottom: '16px', marginBottom: '20px' }}>
        <div>
          <h1 style={{ fontSize: '1.6rem', fontWeight: 800, margin: 0, background: 'linear-gradient(90deg, #38bdf8, #818cf8)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }}>
            ⚡ Voice Pipeline Hardening & A/B Comparison Dashboard
          </h1>
          <p style={{ margin: '4px 0 0', fontSize: '0.85rem', color: '#94a3b8' }}>
            Side-by-Side Real-Time Benchmark: Classic VAD vs. Robust RMS Energy-Gated Triage Pipeline
          </p>
        </div>
        <div style={{ display: 'flex', gap: '10px' }}>
          <button
            onClick={startBoth}
            style={{ backgroundColor: '#2563eb', color: '#fff', border: 'none', padding: '10px 18px', borderRadius: '6px', fontWeight: 600, cursor: 'pointer', boxShadow: '0 4px 12px rgba(37,99,235,0.3)' }}
          >
            ▶️ Start Both Pipelines
          </button>
          <button
            onClick={stopBoth}
            style={{ backgroundColor: '#475569', color: '#fff', border: 'none', padding: '10px 18px', borderRadius: '6px', fontWeight: 600, cursor: 'pointer' }}
          >
            ⏹️ Stop Both
          </button>
          <button
            onClick={clearAllData}
            style={{ backgroundColor: '#1e293b', color: '#cbd5e1', border: '1px solid #475569', padding: '10px 14px', borderRadius: '6px', cursor: 'pointer' }}
          >
            🧹 Clear Logs
          </button>
        </div>
      </div>

      {/* Global Alerts Banner */}
      {ambientAlert && (
        <div style={{ backgroundColor: 'rgba(220, 38, 38, 0.2)', border: '1px solid #dc2626', color: '#fca5a5', padding: '10px 16px', borderRadius: '6px', marginBottom: '16px', display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span>⚠️</span>
          <strong>{ambientAlert.message}</strong> — Consider moving to a quieter area or lowering mic boost.
        </div>
      )}
      {speakCloserAlert && (
        <div style={{ backgroundColor: 'rgba(217, 119, 6, 0.2)', border: '1px solid #d97706', color: '#fcd34d', padding: '10px 16px', borderRadius: '6px', marginBottom: '16px', display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span>🎙️</span>
          <strong>{speakCloserAlert.message}</strong>
        </div>
      )}

      {/* Shared Config Bar */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '12px', backgroundColor: '#1e293b', padding: '12px 16px', borderRadius: '8px', marginBottom: '20px', border: '1px solid #334155' }}>
        <div>
          <label style={{ fontSize: '0.75rem', color: '#94a3b8', display: 'block', marginBottom: '4px' }}>Scheme ID</label>
          <input
            type="text"
            value={schemeId}
            onChange={(e) => setSchemeId(e.target.value)}
            style={{ width: '100%', backgroundColor: '#0f172a', border: '1px solid #475569', color: '#fff', padding: '6px 8px', borderRadius: '4px', fontSize: '0.85rem' }}
          />
        </div>
        <div>
          <label style={{ fontSize: '0.75rem', color: '#94a3b8', display: 'block', marginBottom: '4px' }}>Language</label>
          <select
            value={language}
            onChange={(e) => setLanguage(e.target.value)}
            style={{ width: '100%', backgroundColor: '#0f172a', border: '1px solid #475569', color: '#fff', padding: '6px 8px', borderRadius: '4px', fontSize: '0.85rem' }}
          >
            <option value="hi">Hindi (hi)</option>
            <option value="mr">Marathi (mr)</option>
            <option value="en">English (en)</option>
            <option value="fr">French (fr)</option>
            <option value="ar">Arabic (ar)</option>
          </select>
        </div>
        <div>
          <label style={{ fontSize: '0.75rem', color: '#94a3b8', display: 'block', marginBottom: '4px' }}>Classic Session ID</label>
          <input
            type="text"
            value={sessionIdClassic}
            onChange={(e) => setSessionIdClassic(e.target.value)}
            style={{ width: '100%', backgroundColor: '#0f172a', border: '1px solid #475569', color: '#fff', padding: '6px 8px', borderRadius: '4px', fontSize: '0.85rem' }}
          />
        </div>
        <div>
          <label style={{ fontSize: '0.75rem', color: '#94a3b8', display: 'block', marginBottom: '4px' }}>Robust Session ID</label>
          <input
            type="text"
            value={sessionIdRobust}
            onChange={(e) => setSessionIdRobust(e.target.value)}
            style={{ width: '100%', backgroundColor: '#0f172a', border: '1px solid #475569', color: '#fff', padding: '6px 8px', borderRadius: '4px', fontSize: '0.85rem' }}
          />
        </div>
      </div>

      {/* Main Side-by-Side Comparison Grid */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px', marginBottom: '24px' }}>
        
        {/* === LEFT: Classic Pipeline Card === */}
        <div style={{ backgroundColor: '#1e293b', borderRadius: '8px', border: '1px solid #334155', padding: '16px', display: 'flex', flexDirection: 'column' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid #334155', paddingBottom: '10px', marginBottom: '14px' }}>
            <div>
              <h2 style={{ fontSize: '1.1rem', margin: 0, fontWeight: 700, color: '#94a3b8' }}>🏛️ Classic Pipeline (Basic VAD)</h2>
              <span style={{ fontSize: '0.75rem', color: '#64748b' }}>Standard @ricky0123/vad-web without energy gating</span>
            </div>
            <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
              <span style={{ fontSize: '0.8rem', padding: '3px 8px', borderRadius: '4px', backgroundColor: classicState === 'listening' ? '#059669' : classicState === 'speaking' ? '#2563eb' : '#475569' }}>
                {classicState.toUpperCase()}
              </span>
              {classicState === 'idle' ? (
                <button onClick={startClassic} style={{ backgroundColor: '#059669', color: '#fff', border: 'none', padding: '4px 10px', borderRadius: '4px', cursor: 'pointer', fontSize: '0.8rem' }}>Start</button>
              ) : (
                <button onClick={stopClassic} style={{ backgroundColor: '#dc2626', color: '#fff', border: 'none', padding: '4px 10px', borderRadius: '4px', cursor: 'pointer', fontSize: '0.8rem' }}>Stop</button>
              )}
            </div>
          </div>

          {/* Meters */}
          <div style={{ marginBottom: '14px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', color: '#94a3b8', marginBottom: '4px' }}>
              <span>Volume Level</span>
              <span>{(classicVolume * 100).toFixed(0)}%</span>
            </div>
            <div style={{ height: '8px', backgroundColor: '#0f172a', borderRadius: '4px', overflow: 'hidden' }}>
              <div style={{ width: `${Math.min(100, classicVolume * 100)}%`, height: '100%', backgroundColor: '#38bdf8', transition: 'width 0.05s linear' }} />
            </div>
          </div>

          {/* Transcripts Box */}
          <div style={{ flex: 1, backgroundColor: '#0f172a', borderRadius: '6px', padding: '10px', border: '1px solid #334155', minHeight: '180px', maxHeight: '220px', overflowY: 'auto', marginBottom: '12px' }}>
            <div style={{ fontSize: '0.75rem', fontWeight: 600, color: '#64748b', marginBottom: '6px' }}>TRANSCRIPTION STREAM</div>
            {classicTranscripts.length === 0 ? (
              <div style={{ color: '#475569', fontSize: '0.8rem', fontStyle: 'italic' }}>No transcripts yet...</div>
            ) : (
              classicTranscripts.map((t, idx) => (
                <div key={idx} style={{ fontSize: '0.82rem', marginBottom: '4px', color: t.isFinal ? '#38bdf8' : '#94a3b8' }}>
                  <span style={{ color: '#64748b', fontSize: '0.7rem', marginRight: '6px' }}>[{t.time}]</span>
                  {t.text}
                </div>
              ))
            )}
          </div>

          {/* Extractions Box */}
          <div style={{ backgroundColor: '#0f172a', borderRadius: '6px', padding: '10px', border: '1px solid #334155', minHeight: '100px', maxHeight: '120px', overflowY: 'auto' }}>
            <div style={{ fontSize: '0.75rem', fontWeight: 600, color: '#64748b', marginBottom: '6px' }}>EXTRACTED FIELDS</div>
            <pre style={{ margin: 0, fontSize: '0.75rem', color: '#a7f3d0' }}>
              {JSON.stringify(classicExtractions, null, 2)}
            </pre>
          </div>
        </div>

        {/* === RIGHT: Robust Pipeline Card === */}
        <div style={{ backgroundColor: '#1e293b', borderRadius: '8px', border: '1px solid #38bdf8', padding: '16px', display: 'flex', flexDirection: 'column', boxShadow: '0 0 15px rgba(56, 189, 248, 0.15)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid #334155', paddingBottom: '10px', marginBottom: '14px' }}>
            <div>
              <h2 style={{ fontSize: '1.1rem', margin: 0, fontWeight: 800, color: '#38bdf8' }}>🚀 Robust Pipeline (Energy-Gated Triage)</h2>
              <span style={{ fontSize: '0.75rem', color: '#94a3b8' }}>Two-Layer VAD + RMS Near-Field Proximity Gate</span>
            </div>
            <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
              <span style={{ fontSize: '0.8rem', padding: '3px 8px', borderRadius: '4px', backgroundColor: robustState === 'listening' ? '#059669' : robustState === 'speaking' ? '#2563eb' : '#475569' }}>
                {robustState.toUpperCase()}
              </span>
              {robustState === 'idle' ? (
                <button onClick={startRobust} style={{ backgroundColor: '#38bdf8', color: '#0f172a', fontWeight: 700, border: 'none', padding: '4px 10px', borderRadius: '4px', cursor: 'pointer', fontSize: '0.8rem' }}>Start</button>
              ) : (
                <button onClick={stopRobust} style={{ backgroundColor: '#dc2626', color: '#fff', border: 'none', padding: '4px 10px', borderRadius: '4px', cursor: 'pointer', fontSize: '0.8rem' }}>Stop</button>
              )}
            </div>
          </div>

          {/* Diagnostic Metrics Matrix */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '8px', backgroundColor: '#0f172a', padding: '10px', borderRadius: '6px', marginBottom: '12px', border: '1px solid #334155' }}>
            <div>
              <div style={{ fontSize: '0.7rem', color: '#94a3b8' }}>CLASSIFICATION</div>
              <div style={{ marginTop: '3px' }}>{getClassificationBadge(currentDiag.classification)}</div>
            </div>
            <div>
              <div style={{ fontSize: '0.7rem', color: '#94a3b8' }}>ENERGY STATE</div>
              <div style={{ fontSize: '0.82rem', fontWeight: 700, color: currentDiag.energyState.includes('CONFIRMED') ? '#34d399' : currentDiag.energyState.includes('PAUSE') ? '#fbbf24' : '#94a3b8' }}>
                {currentDiag.energyState}
              </div>
            </div>
            <div>
              <div style={{ fontSize: '0.7rem', color: '#94a3b8' }}>STREAMING TO BACKEND</div>
              <div style={{ fontSize: '0.82rem', fontWeight: 800, color: currentDiag.isStreaming ? '#34d399' : '#f87171' }}>
                {currentDiag.isStreaming ? '🟢 ACTIVE (PCM Sent)' : '🔴 DROPPED (Gated)'}
              </div>
            </div>
          </div>

          {/* Live Meter Bars */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px', marginBottom: '12px' }}>
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', color: '#94a3b8', marginBottom: '3px' }}>
                <span>VAD Probability</span>
                <span style={{ fontWeight: 600, color: currentDiag.vadProbability >= tuningParams.positiveSpeechThreshold ? '#34d399' : '#94a3b8' }}>
                  {(currentDiag.vadProbability * 100).toFixed(0)}%
                </span>
              </div>
              <div style={{ height: '7px', backgroundColor: '#0f172a', borderRadius: '4px', overflow: 'hidden' }}>
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
              <div style={{ height: '7px', backgroundColor: '#0f172a', borderRadius: '4px', overflow: 'hidden' }}>
                <div style={{ width: `${Math.min(100, (currentDiag.rollingRms / 0.05) * 100)}%`, height: '100%', backgroundColor: currentDiag.rollingRms >= tuningParams.rmsHighThreshold ? '#38bdf8' : '#f59e0b', transition: 'width 0.05s' }} />
              </div>
            </div>
          </div>

          {/* Transcripts Box */}
          <div style={{ flex: 1, backgroundColor: '#0f172a', borderRadius: '6px', padding: '10px', border: '1px solid #334155', minHeight: '180px', maxHeight: '220px', overflowY: 'auto', marginBottom: '12px' }}>
            <div style={{ fontSize: '0.75rem', fontWeight: 600, color: '#38bdf8', marginBottom: '6px' }}>ROBUST TRANSCRIPTION STREAM</div>
            {robustTranscripts.length === 0 ? (
              <div style={{ color: '#475569', fontSize: '0.8rem', fontStyle: 'italic' }}>No transcripts yet...</div>
            ) : (
              robustTranscripts.map((t, idx) => (
                <div key={idx} style={{ fontSize: '0.82rem', marginBottom: '4px', color: t.isFinal ? '#38bdf8' : '#94a3b8' }}>
                  <span style={{ color: '#64748b', fontSize: '0.7rem', marginRight: '6px' }}>[{t.time}]</span>
                  {t.text}
                </div>
              ))
            )}
          </div>

          {/* Extractions Box */}
          <div style={{ backgroundColor: '#0f172a', borderRadius: '6px', padding: '10px', border: '1px solid #334155', minHeight: '100px', maxHeight: '120px', overflowY: 'auto' }}>
            <div style={{ fontSize: '0.75rem', fontWeight: 600, color: '#38bdf8', marginBottom: '6px' }}>EXTRACTED FIELDS</div>
            <pre style={{ margin: 0, fontSize: '0.75rem', color: '#a7f3d0' }}>
              {JSON.stringify(robustExtractions, null, 2)}
            </pre>
          </div>
        </div>
      </div>

      {/* Aggregate Statistics & Efficiency Summary */}
      <div style={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: '8px', padding: '16px', marginBottom: '20px' }}>
        <h3 style={{ margin: '0 0 12px 0', fontSize: '1rem', fontWeight: 700, color: '#f1f5f9' }}>
          📊 Real-Time Efficiency & Triage Statistics
        </h3>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6, 1fr)', gap: '12px' }}>
          <div style={{ backgroundColor: '#0f172a', padding: '10px', borderRadius: '6px', border: '1px solid #334155' }}>
            <div style={{ fontSize: '0.75rem', color: '#94a3b8' }}>Total Frames</div>
            <div style={{ fontSize: '1.2rem', fontWeight: 800, color: '#f8fafc' }}>{stats.totalFrames}</div>
          </div>
          <div style={{ backgroundColor: '#0f172a', padding: '10px', borderRadius: '6px', border: '1px solid #334155' }}>
            <div style={{ fontSize: '0.75rem', color: '#94a3b8' }}>Speech Near (Streamed)</div>
            <div style={{ fontSize: '1.2rem', fontWeight: 800, color: '#10b981' }}>{stats.speechNearFrames}</div>
          </div>
          <div style={{ backgroundColor: '#0f172a', padding: '10px', borderRadius: '6px', border: '1px solid #334155' }}>
            <div style={{ fontSize: '0.75rem', color: '#94a3b8' }}>Speech Far (Blocked)</div>
            <div style={{ fontSize: '1.2rem', fontWeight: 800, color: '#f59e0b' }}>{stats.speechFarFrames}</div>
          </div>
          <div style={{ backgroundColor: '#0f172a', padding: '10px', borderRadius: '6px', border: '1px solid #334155' }}>
            <div style={{ fontSize: '0.75rem', color: '#94a3b8' }}>Noise Frames (Dropped)</div>
            <div style={{ fontSize: '1.2rem', fontWeight: 800, color: '#ef4444' }}>{stats.noiseFrames}</div>
          </div>
          <div style={{ backgroundColor: '#0f172a', padding: '10px', borderRadius: '6px', border: '1px solid #334155' }}>
            <div style={{ fontSize: '0.75rem', color: '#94a3b8' }}>Streamed Chunks</div>
            <div style={{ fontSize: '1.2rem', fontWeight: 800, color: '#38bdf8' }}>{stats.streamedChunks}</div>
          </div>
          <div style={{ backgroundColor: '#0f172a', padding: '10px', borderRadius: '6px', border: '1px solid #334155' }}>
            <div style={{ fontSize: '0.75rem', color: '#94a3b8' }}>Estimated Bandwidth Saved</div>
            <div style={{ fontSize: '1.2rem', fontWeight: 800, color: '#a855f7' }}>{bandwidthSavedPct}%</div>
          </div>
        </div>
      </div>

      {/* Interactive Parameter Tuning Sliders Panel */}
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
              <span>RMS High Threshold (Near-field)</span>
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
              🔬 Real-Time Frame-by-Frame Diagnostic Stream (Last 100)
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
            height: '240px',
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
                <span>{log.isStreaming ? '🟢 STREAMING' : '🔴 GATED'}</span>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
