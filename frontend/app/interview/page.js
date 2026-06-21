'use client';

import { useState, useEffect, useRef, useCallback, Suspense } from 'react';
import { useSearchParams, useRouter } from 'next/navigation';
import styles from './interview.module.css';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080';
const WS_BASE_URL = process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8080';

const STEPS = [
  { id: 'START', label: 'स्वागत', short: 'Welcome' },
  { id: 'Q_STATUS', label: 'स्थिति', short: 'Status' },
  { id: 'Q_MONTHLY_REV', label: 'मासिक बिक्री', short: 'Revenue' },
  { id: 'Q_MONTHLY_PROFIT', label: 'मासिक लाभ', short: 'Profit' },
  { id: 'Q_LAST_YEAR_REV', label: 'पिछले साल', short: 'Last Year' },
  { id: 'Q_PERSONS', label: 'कर्मचारी', short: 'Staff' },
  { id: 'Q_INVENTORY', label: 'माल/स्टॉक', short: 'Inventory' },
  { id: 'Q_DEBTORS', label: 'उधारी', short: 'Debtors' },
  { id: 'Q_CREDITORS', label: 'लेनदार', short: 'Creditors' },
  { id: 'Q_PROPOSED', label: 'प्रस्तावित', short: 'Proposed' },
  { id: 'Q_MACHINES', label: 'मशीन', short: 'Machines' },
  { id: 'Q_PRIOR_LOAN', label: 'पूर्व कर्ज', short: 'Loan History' },
  { id: 'Q_FAMILY', label: 'परिवार', short: 'Family' },
  { id: 'Q_EDUCATION', label: 'शिक्षा', short: 'Education' },
  { id: 'Q_COBORROWER', label: 'सह-कर्जदार', short: 'Co-borrower' },
];

// Resample float32 buffer to 16000Hz
function resample(buffer, sourceRate, targetRate) {
  const ratio = sourceRate / targetRate;
  const newLength = Math.round(buffer.length / ratio);
  const result = new Float32Array(newLength);
  let offsetResult = 0;
  let offsetBuffer = 0;
  while (offsetResult < result.length) {
    const nextOffsetBuffer = Math.round((offsetResult + 1) * ratio);
    let accum = 0, count = 0;
    for (let i = offsetBuffer; i < nextOffsetBuffer && i < buffer.length; i++) {
      accum += buffer[i];
      count++;
    }
    result[offsetResult] = count > 0 ? accum / count : 0;
    offsetResult++;
    offsetBuffer = nextOffsetBuffer;
  }
  return result;
}

// Convert Float32 array to 16-bit PCM ArrayBuffer
function floatTo16BitPCM(float32Array) {
  const buffer = new ArrayBuffer(float32Array.length * 2);
  const view = new DataView(buffer);
  for (let i = 0; i < float32Array.length; i++) {
    const s = Math.max(-1, Math.min(1, float32Array[i]));
    view.setInt16(i * 2, s < 0 ? s * 0x8000 : s * 0x7FFF, true);
  }
  return buffer;
}

function InterviewContent() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const applicantName = searchParams.get('name') || 'आवेदक';
  const businessType = searchParams.get('type') || 'GROCERY';

  // State
  const [voiceState, setVoiceState] = useState('idle'); // idle, connecting, listening, speaking, processing
  const [currentStep, setCurrentStep] = useState(0);
  const [currentText, setCurrentText] = useState('');
  const [transcript, setTranscript] = useState('');
  const [extractedData, setExtractedData] = useState({});
  const [isConnected, setIsConnected] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [showComplete, setShowComplete] = useState(false);
  const [errorMsg, setErrorMsg] = useState('');
  const [textInputValue, setTextInputValue] = useState('');

  // Audio recording state
  const [isClientSpeaking, setIsClientSpeaking] = useState(false);

  // Audio visualizer bars
  const [bars, setBars] = useState(Array(8).fill(4));

  // Global Audio Unlock on first interaction
  useEffect(() => {
    const unlock = () => {
      if (typeof window !== 'undefined') {
        window.globalAudioContext = window.globalAudioContext || new (window.AudioContext || window.webkitAudioContext)();
        const ctx = window.globalAudioContext;
        if (ctx.state === 'suspended') {
          try { ctx.resume(); } catch (e) {}
        }
        if (!window.audioUnlocked) {
          try {
            const buffer = ctx.createBuffer(1, ctx.sampleRate * 0.1, ctx.sampleRate);
            const source = ctx.createBufferSource();
            source.buffer = buffer;
            source.connect(ctx.destination);
            source.start(0);
            window.audioUnlocked = true;
          } catch(e) {}
        }
      }
      document.removeEventListener('click', unlock);
      document.removeEventListener('touchstart', unlock);
    };
    document.addEventListener('click', unlock);
    document.addEventListener('touchstart', unlock);
    return () => {
      document.removeEventListener('click', unlock);
      document.removeEventListener('touchstart', unlock);
    };
  }, []);

  // Timer
  const animFrameRef = useRef();

  // Shared Voice Session Ref
  const voiceSessionRef = useRef(null);
  const [isUserSpeaking, setIsUserSpeaking] = useState(false);

  // Timer
  useEffect(() => {
    if (!isConnected || showComplete) return;
    const t = setInterval(() => setElapsed(e => e + 1), 1000);
    return () => clearInterval(t);
  }, [isConnected, showComplete]);

  // Voice bar animation
  useEffect(() => {
    if (voiceState === 'speaking' || voiceState === 'listening' || isClientSpeaking) {
      const animate = () => {
        setBars(prev => prev.map(() => {
          const intensity = voiceState === 'speaking' ? 0.7 : 0.3;
          return Math.random() * 28 * intensity + 4;
        }));
        animFrameRef.current = requestAnimationFrame(() => {
          setTimeout(animate, 100);
        });
      };
      animate();
      return () => cancelAnimationFrame(animFrameRef.current);
    } else {
      setBars(Array(12).fill(4));
    }
  }, [voiceState, isClientSpeaking]);

  // Disconnect socket & stop mic
  const cleanup = useCallback(() => {
    if (voiceSessionRef.current) {
      voiceSessionRef.current.disconnect();
      voiceSessionRef.current = null;
    }
    setIsUserSpeaking(false);
    setIsConnected(false);
  }, []);

  useEffect(() => {
    // Load VAD dependencies from CDN
    import('../utils/voiceHelper').then(({ loadVADScripts }) => {
      loadVADScripts().then(success => {
        if (success) console.log('Interview VAD loaded.');
      });
    });
    return () => cleanup();
  }, [cleanup]);

  // Start Voice Session (Connect to WebSocket)
  const startInterview = async () => {
    cleanup();
    setErrorMsg('');
    setVoiceState('connecting');

    const token = localStorage.getItem('token');
    const sessionId = localStorage.getItem('session_id');
    const applicationId = localStorage.getItem('application_id');

    if (!token || !sessionId) {
      setErrorMsg('प्रमाणिकरण विवरण गुम हैं। कृपया पुनः लॉगिन करें।');
      setVoiceState('idle');
      return;
    }

    try {
      const { loadVADScripts, VoiceSessionManager } = await import('../utils/voiceHelper');
      const loaded = await loadVADScripts();
      if (!loaded) {
        throw new Error('VAD scripts could not be loaded.');
      }

      const manager = new VoiceSessionManager({
        token,
        sessionId,
        applicationId,
        applicantName,
        schemeId: `mudra-${businessType.toLowerCase()}`,
        wsUrl: `${WS_BASE_URL.replace('http', 'ws')}/ws/voice`,
        onStateChange: (state) => {
          setVoiceState(state);
        },
        onTranscript: (text, isFinal) => {
          if (isFinal) {
            setTranscript(text);
          } else {
            // Assistant text question
            setCurrentText(text);
            setTranscript('');
          }
        },
        onProgress: (current_step, total_steps, current_node_id) => {
          const nodeIndex = STEPS.findIndex(s => s.id === current_node_id);
          if (nodeIndex !== -1) {
            setCurrentStep(nodeIndex);
          }
        },
        onExtraction: (fields) => {
          setExtractedData(prev => ({ ...prev, ...fields }));
        },
        onComplete: (data) => {
          setVoiceState('idle');
          cleanup();
          router.push('/dashboard/details');
        },
        onSystemMessage: (role, text) => {
          if (role === 'error') {
            setErrorMsg(text);
            setIsConnected(false);
          } else if (role === 'connecting') {
            setIsConnected(false);
          } else {
            setIsConnected(true);
          }
        },
        onError: (err) => {
          setErrorMsg(err);
          setIsConnected(false);
        }
      });

      voiceSessionRef.current = manager;

      await manager.connect();

      // Hook VAD speech triggers to our React state
      const vadInstance = manager.audioProcessor?.vadInstance;
      if (vadInstance) {
        const originalOnSpeechStart = vadInstance.options.onSpeechStart;
        vadInstance.options.onSpeechStart = () => {
          setIsUserSpeaking(true);
          originalOnSpeechStart();
        };

        const originalOnSpeechEnd = vadInstance.options.onSpeechEnd;
        vadInstance.options.onSpeechEnd = () => {
          setIsUserSpeaking(false);
          originalOnSpeechEnd();
        };

        const originalOnFrameProcessed = vadInstance.options.onFrameProcessed;
        vadInstance.options.onFrameProcessed = (probabilities, frame) => {
          originalOnFrameProcessed(probabilities, frame);
          
          // Estimate volume for bar visualizer
          let sum = 0;
          for (let i = 0; i < frame.length; i++) {
            sum += Math.abs(frame[i]);
          }
          const avgVolume = sum / frame.length;
          const vol = Math.min(100, avgVolume * 500);
          setBars(prev => prev.map(() => Math.random() * vol * 0.4 + 4));
        };
      }

    } catch (err) {
      console.error('Failed to initialize microphone / VAD / WS connection:', err);
      setErrorMsg('माइक्रोफोन अनुमति अस्वीकार कर दी गई है या उपलब्ध नहीं है।');
      setVoiceState('idle');
      cleanup();
    }
  };

  const handleSendText = () => {
    if (!textInputValue.trim()) return;
    if (voiceSessionRef.current) {
      voiceSessionRef.current.sendTextInput(textInputValue.trim());
      setTextInputValue('');
    }
  };

  const formatTime = (s) => {
    const m = Math.floor(s / 60);
    return `${m}:${String(s % 60).padStart(2, '0')}`;
  };

  const extractedCount = Object.keys(extractedData).length;

  return (
    <div className={styles.container}>
      {/* ─── Header ─── */}
      <header className={styles.header}>
        <div className={styles.logo}>
          <svg width="24" height="24" viewBox="0 0 48 48" fill="none">
            <circle cx="24" cy="24" r="24" fill="url(#lg)" />
            <path d="M16 24C16 19.58 19.58 16 24 16V32C19.58 32 16 28.42 16 24Z" fill="white" opacity="0.9"/>
            <defs><linearGradient id="lg" x1="0" y1="0" x2="48" y2="48"><stop stopColor="#7c3aed"/><stop offset="1" stopColor="#a855f7"/></linearGradient></defs>
          </svg>
          Chayan AI
        </div>
        <div className={styles.headerInfo}>
          <span className="badge badge-accent">{applicantName} • {businessType}</span>
          <span className={styles.timer}>{formatTime(elapsed)}</span>
        </div>
      </header>

      {/* ─── Main Center Content ─── */}
      <main className={styles.main}>
        {!isConnected && !showComplete ? (
          /* Pre-connect screen */
          <div className={styles.preConnect}>
            <div className={styles.preConnectIcon}>
              <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
                <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
                <line x1="12" y1="19" x2="12" y2="23" />
                <line x1="8" y1="23" x2="16" y2="23" />
              </svg>
            </div>
            <h2>Live Interview</h2>
            <p>
              AI आपसे हिंदी में सवाल पूछेगा। बस सामान्य तरीके से बातचीत करें, <br/>सभी जानकारी अपने आप दर्ज़ हो जाएगी।
            </p>

            {errorMsg && (
              <div className={styles.errorBox}>
                <div className={styles.errorBoxTitle}>⚠️ कनेक्शन त्रुटि / Connection Issue</div>
                <div className={styles.errorBoxMsg}>{errorMsg}</div>
              </div>
            )}

            <button
              className="btn btn-primary btn-lg"
              onClick={startInterview}
              style={{ marginTop: 'var(--space-md)', padding: '16px 40px', fontSize: '1.125rem', borderRadius: 'var(--radius-full)' }}
            >
              {errorMsg ? 'पुनः प्रयास करें / Retry Interview' : 'इंटरव्यू शुरू करें'}
            </button>
          </div>
        ) : showComplete ? (
          /* Complete screen */
          <div className={styles.complete}>
            <div className={styles.completeIcon}>✅</div>
            <h2>इंटरव्यू पूरा हुआ!</h2>
            <p className="text-muted" style={{ maxWidth: 400, textAlign: 'center' }}>
              {applicantName} जी, आपकी सारी जानकारी सफलतापूर्वक दर्ज कर ली गई है।
            </p>
            <div className={styles.completeStats}>
              <div className={styles.completeStat}>
                <span className={styles.completeValue}>{extractedCount}</span>
                <span className="text-muted text-sm">फ़ील्ड</span>
              </div>
              <div className={styles.completeStat}>
                <span className={styles.completeValue}>{formatTime(elapsed)}</span>
                <span className="text-muted text-sm">समय</span>
              </div>
              <div className={styles.completeStat}>
                <span className={styles.completeValue}>{currentStep}</span>
                <span className="text-muted text-sm">सवाल</span>
              </div>
            </div>
            <button className="btn btn-primary btn-lg" onClick={() => router.push('/dashboard/details')} style={{ minWidth: 220, borderRadius: 'var(--radius-full)' }}>
              डैशबोर्ड पर जाएँ →
            </button>
          </div>
        ) : (
          /* Active interview */
          <div className={styles.voiceInterface}>
            <div className={`${styles.statusBadge} ${styles[`status-${voiceState}`]}`}>
              <span className={styles.statusDot} />
              {isUserSpeaking ? 'आप बोल रहे हैं...' :
               voiceState === 'listening' ? 'सुन रहा है (शांत)...' :
               voiceState === 'speaking' ? 'बोल रहा है...' :
               voiceState === 'processing' ? 'समझ रहा है...' :
               'जुड़ रहा है...'}
            </div>

            {/* Voice Orb (Light Theme) */}
            <div className={styles.orbContainer}>
              <div className={`${styles.coreRing} ${styles.ring1}`} />
              <div className={`${styles.coreRing} ${styles.ring2}`} />
              <div className={`${styles.coreRing} ${styles.ring3}`} />
              <div className={`${styles.coreSphere} ${isUserSpeaking ? styles.sphereListening : styles[`sphere${voiceState.charAt(0).toUpperCase() + voiceState.slice(1)}`] || ''}`}>
                <div className={styles.coreGlowInner} />
                <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="var(--accent-primary)" strokeWidth="1.5">
                  <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
                  <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
                </svg>
              </div>
            </div>

            {/* Current Question / Transcript */}
            <div className={styles.textArea}>
              {voiceState === 'speaking' && currentText && (
                <p className={styles.questionText}>
                  {currentText}
                </p>
              )}
              {(voiceState === 'listening' || isClientSpeaking || isUserSpeaking) && (
                <p className={styles.transcriptText}>
                  {transcript || 'आप बोल सकते हैं...'}
                </p>
              )}
            </div>

            {/* Direct Text Input */}
            <div className={styles.textInputContainer}>
              <input
                type="text"
                className={styles.textInput}
                placeholder="यहाँ टाइप करें... / Type here..."
                value={textInputValue}
                onChange={(e) => setTextInputValue(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') handleSendText();
                }}
                disabled={voiceState === 'connecting'}
              />
              <button 
                className={styles.sendButton} 
                onClick={handleSendText} 
                aria-label="Send text"
                disabled={voiceState === 'connecting' || !textInputValue.trim()}
              >
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <line x1="22" y1="2" x2="11" y2="13"></line>
                  <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
                </svg>
              </button>
            </div>

            {/* Action Buttons */}
            <div className={styles.actionRow}>
              <button
                className="btn btn-secondary"
                style={{ borderRadius: 'var(--radius-full)', padding: '12px 32px', color: 'var(--accent-danger)', borderColor: 'var(--border-default)', background: 'var(--bg-glass)' }}
                onClick={() => { setShowComplete(true); setVoiceState('idle'); cleanup(); }}
              >
                ⏹️ इंटरव्यू समाप्त करें
              </button>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}

export default function InterviewPage() {
  return (
    <Suspense fallback={
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh', color: 'var(--text-secondary)' }}>
        Loading...
      </div>
    }>
      <InterviewContent />
    </Suspense>
  );
}
