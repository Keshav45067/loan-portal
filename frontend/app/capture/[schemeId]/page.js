'use client';

import { useState, useRef, useEffect, useCallback, use } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import styles from '../capture.module.css';
import interviewStyles from '../../interview/interview.module.css';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080';
const WS_BASE_URL = process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8080';

// Minimal AudioVisualizer for Voice Agent Feedback
class AudioVisualizer {
  constructor(canvas) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.animationId = null;
    this.isActive = false;
    this.mode = 'idle'; 
    this.volumeLevel = 0;
    this.time = 0;
    this.bars = Array(40).fill(0).map(() => ({ height: 0, targetHeight: 0, velocity: 0 }));
    this._setupCanvas();
    this._animate();
  }
  _setupCanvas() {
    if (!this.canvas) return;
    const dpr = typeof window !== 'undefined' ? window.devicePixelRatio || 1 : 1;
    const rect = this.canvas.getBoundingClientRect();
    this.canvas.width = rect.width * dpr;
    this.canvas.height = rect.height * dpr;
    this.ctx.scale(dpr, dpr);
    this.width = rect.width;
    this.height = rect.height;
  }
  updateAudioData(volumeLevel) {
    this.volumeLevel = volumeLevel;
  }
  setMode(mode) {
    this.mode = mode;
  }
  _animate() {
    this.time += 0.016; 
    if (this.ctx && this.width && this.height) {
      this.ctx.clearRect(0, 0, this.width, this.height);
      const centerY = this.height / 2;
      const barCount = this.bars.length;
      const barWidth = 3;
      const gap = (this.width - barCount * barWidth) / (barCount + 1);

      for (let i = 0; i < barCount; i++) {
        const x = gap + i * (barWidth + gap);
        let h = 4;
        
        if (this.mode === 'recording') {
            const wave = Math.sin(this.time * 4 + i * 0.4);
            const targetHeight = 4 + this.volumeLevel * (this.height * 0.8) * 0.5 * (0.5 + wave * 0.5);
            this.bars[i].velocity = (this.bars[i].velocity + (targetHeight - this.bars[i].height) * 0.15) * 0.8;
            this.bars[i].height += this.bars[i].velocity;
            h = Math.max(2, this.bars[i].height);
            this.ctx.fillStyle = `rgba(74, 120, 255, 0.8)`;
        } else if (this.mode === 'processing') {
            const wave = Math.sin(this.time * 3 + i * 0.25) * 8 + 10;
            this.bars[i].height += (wave - this.bars[i].height) * 0.08;
            h = this.bars[i].height;
            this.ctx.fillStyle = `rgba(167, 139, 250, 0.8)`;
        } else if (this.mode === 'speaking') {
            const wave1 = Math.sin(this.time * 3 + i * 0.25) * 12;
            const targetH = Math.abs(wave1) + 4;
            this.bars[i].height += (targetH - this.bars[i].height) * 0.12;
            h = this.bars[i].height;
            this.ctx.fillStyle = `rgba(34, 201, 104, 0.8)`;
        } else {
            const wave = Math.sin(this.time * 2 + i * 0.3) * 3 + 4;
            this.bars[i].targetHeight = wave;
            this.bars[i].height += (this.bars[i].targetHeight - this.bars[i].height) * 0.1;
            h = this.bars[i].height;
            this.ctx.fillStyle = `rgba(74, 120, 255, 0.3)`;
        }
        
        this.ctx.beginPath();
        if (this.ctx.roundRect) {
          this.ctx.roundRect(x, centerY - h / 2, barWidth, h, 1.5);
        } else {
          this.ctx.rect(x, centerY - h / 2, barWidth, h);
        }
        this.ctx.fill();
      }
    }
    this.animationId = requestAnimationFrame(() => this._animate());
  }
  destroy() {
    if (this.animationId) cancelAnimationFrame(this.animationId);
  }
}

export default function CaptureFlowPage({ params }) {
  const unwrappedParams = use(params);
  const schemeId = unwrappedParams.schemeId;
  const searchParams = useSearchParams();
  const language = searchParams.get('lang') || 'en';
  const router = useRouter();

  const [token, setToken] = useState('');
  const [sessionId, setSessionId] = useState('');

  // Flow State
  const [state, setState] = useState({
    docId: '',
    pageId: '',
    docIndex: 0,
    totalDocs: 0,
    pageIndex: 0,
    totalPages: 0,
    pageInfo: null,
    allComplete: false
  });

  const [isStarted, setIsStarted] = useState(false);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  
  // File / Camera State
  const videoRef = useRef(null);
  const canvasRef = useRef(null);
  const streamRef = useRef(null);
  const [activeFacingMode, setActiveFacingMode] = useState('environment');
  const [previewUrl, setPreviewUrl] = useState(null);
  const [processingDoc, setProcessingDoc] = useState(false);

  // Voice Agent State
  const [qaState, setQaState] = useState('idle');
  const [transcript, setTranscript] = useState('');
  const [textInputValue, setTextInputValue] = useState('');
  const voiceSessionRef = useRef(null);
  
  const visualizerCanvasRef = useRef(null);
  const visualizerInstanceRef = useRef(null);

  useEffect(() => {
    const init = async () => {
      const savedToken = localStorage.getItem('token');
      const savedSessionId = localStorage.getItem('session_id');
      if (!savedToken || !savedSessionId) {
        router.push('/');
        return;
      }
      setToken(savedToken);
      setSessionId(savedSessionId);
      
      // Fetch initial state
      try {
        const res = await fetch(`${API_BASE_URL}/api/capture/start`, {
            method: 'POST',
            headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${savedToken}`
            },
            body: JSON.stringify({ scheme_id: schemeId, language: language })
        });
        const data = await res.json();
        if (!data.success) throw new Error(data.error);
        
        setState({
            docId: data.current_document_id,
            pageId: data.current_page_id,
            docIndex: data.current_document_index,
            totalDocs: data.total_documents,
            pageIndex: data.current_page_index,
            totalPages: data.total_pages,
            pageInfo: data.current_page_info,
            allComplete: data.all_complete
        });

        if (data.all_complete) {
            router.push('/dashboard/details');
        }
      } catch (err) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    };
    init();

    return () => {
      stopCamera();
      if (voiceSessionRef.current) voiceSessionRef.current.disconnect();
      if (visualizerInstanceRef.current) visualizerInstanceRef.current.destroy();
    };
  }, [schemeId, language, router]);

  useEffect(() => {
    // Preload large WASM/ONNX VAD scripts early
    import('../../utils/voiceHelper').then(({ loadVADScripts }) => {
      loadVADScripts().catch(console.error);
    });
  }, []);

  useEffect(() => {
    if (visualizerCanvasRef.current && !visualizerInstanceRef.current) {
        visualizerInstanceRef.current = new AudioVisualizer(visualizerCanvasRef.current);
    }
    if (visualizerInstanceRef.current) {
        let mode = 'idle';
        if (qaState === 'listening') mode = 'recording';
        else if (qaState === 'processing') mode = 'processing';
        else if (qaState === 'speaking') mode = 'speaking';
        visualizerInstanceRef.current.setMode(mode);
    }
  }, [qaState]);

  const startSession = () => {
    // Initialize and resume AudioContext synchronously in click handler
    window.globalAudioContext = window.globalAudioContext || new (window.AudioContext || window.webkitAudioContext)();
    if (window.globalAudioContext.state === 'suspended') {
      try { window.globalAudioContext.resume(); } catch (e) { console.error('Failed to resume AudioContext:', e); }
    }
    setIsStarted(true);
  };

  // Start Voice Session
  useEffect(() => {
    if (!loading && !state.allComplete && token && sessionId && isStarted) {
        const startVoice = async () => {
            if (voiceSessionRef.current) return;
            const { VoiceSessionManager, loadVADScripts } = await import('../../utils/voiceHelper');
            
            // Ensure VAD is loaded (will return true instantly if already preloaded)
            const isLoaded = await loadVADScripts();
            if (!isLoaded) {
                setError('Failed to load voice components. Please check your connection and reload.');
                return;
            }

            const manager = new VoiceSessionManager({
                token,
                sessionId,
                language,
                wsUrl: `${WS_BASE_URL.replace('http', 'ws')}/ws/capture-voice`,
                onStateChange: (s) => setQaState(s),
                onTranscript: (t, isFinal) => { if (!isFinal) setTranscript(t); },
                onError: (err) => setError(err.message || err),
                onConnected: () => {
                    const text = state.pageInfo?.intro_prompt?.[language] || "Please capture your document.";
                    manager.sendControlSignal(`capture_speak:${text}`);
                    manager.sendControlSignal('update_page_context');
                }
            });
            voiceSessionRef.current = manager;
            
            await manager.connect();

            // Hook visualizer after connect so audioProcessor is initialized
            if (manager.audioProcessor) {
                manager.audioProcessor.onVolumeLevel = (l) => {
                    if (visualizerInstanceRef.current) visualizerInstanceRef.current.updateAudioData(l);
                };
            }
        };
        startVoice();
    }
  }, [loading, state.allComplete, token, sessionId, language, isStarted]);

  // Camera Management
  const stopCamera = useCallback(() => {
    if (streamRef.current) {
      streamRef.current.getTracks().forEach(t => t.stop());
      streamRef.current = null;
    }
  }, []);

  const startCamera = useCallback(async (facingMode) => {
    stopCamera();
    if (previewUrl) return; // Don't start if previewing
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode, width: { ideal: 1280 }, height: { ideal: 720 } }
      });
      streamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        videoRef.current.play().catch(e => console.error(e));
      }
    } catch (err) {
      console.error('Camera access error:', err);
    }
  }, [stopCamera, previewUrl]);

  useEffect(() => {
    if (!loading && !state.allComplete) {
        const facing = state.pageInfo?.ui_camera_overlay === 'selfie' ? 'user' : 'environment';
        startCamera(facing);
    }
    return stopCamera;
  }, [loading, state.allComplete, state.pageInfo, startCamera, stopCamera]);

  const handleCapture = () => {
    if (videoRef.current && canvasRef.current) {
      const video = videoRef.current;
      const canvas = canvasRef.current;
      canvas.width = video.videoWidth || 640;
      canvas.height = video.videoHeight || 480;
      const ctx = canvas.getContext('2d');
      ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
      
      canvas.toBlob(async (blob) => {
        if (blob) {
          const file = new File([blob], `${state.pageId}.jpg`, { type: 'image/jpeg' });
          setPreviewUrl(URL.createObjectURL(file));
          await uploadDocument(file);
        }
      }, 'image/jpeg', 0.85);
    }
  };

  const handleFileUpload = async (e) => {
    const file = e.target.files[0];
    if (!file) return;

    // Validate size
    const max_size_mb = state.pageInfo?.max_file_size_mb || 5;
    if (file.size > max_size_mb * 1024 * 1024) {
        setError(`File exceeds maximum allowed size of ${max_size_mb}MB.`);
        e.target.value = ''; // Reset
        return;
    }

    // Validate format
    const formats = state.pageInfo?.acceptable_formats || [];
    if (formats.length > 0) {
        if (!formats.includes(file.type)) {
            setError(`Invalid file format. Allowed formats: ${formats.join(', ')}`);
            e.target.value = ''; // Reset
            return;
        }
    }

    setPreviewUrl(URL.createObjectURL(file));
    await uploadDocument(file);
    e.target.value = ''; // Reset
  };

  const uploadDocument = async (file) => {
    if (!file) return;
    setProcessingDoc(true);
    setError(null);

    if (voiceSessionRef.current) {
      voiceSessionRef.current.stopAudioPlayback();
      voiceSessionRef.current.sendControlSignal('capture_processing');
    }

    try {
      const formData = new FormData();
      formData.append('file', file);
      formData.append('document_id', state.docId);
      formData.append('page_id', state.pageId);

      const res = await fetch(`${API_BASE_URL}/api/capture/process`, {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${token}` },
        body: formData
      });

      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Failed to process document');
      
      if (!data.success) {
          // Validation failed
          if (voiceSessionRef.current) {
              voiceSessionRef.current.stopAudioPlayback();
              const errKey = data.validation_error_key || data.error || 'unknown_error';
              voiceSessionRef.current.sendControlSignal(`capture_error:${errKey}`);
          }
          throw new Error(data.validation_error_text || data.error || 'Validation failed. Please try again.');
      }

      if (voiceSessionRef.current) {
        voiceSessionRef.current.sendControlSignal('capture_success');
      }
      
      if (data.all_complete) {
          router.push('/dashboard/details');
          return;
      }

      // Update state for next step
      setState(prev => ({
          ...prev,
          docId: data.next_document_id,
          pageId: data.next_page_id,
      }));
      setPreviewUrl(null);
      
      // Need to re-fetch page info to update prompts and overlay
      const infoRes = await fetch(`${API_BASE_URL}/api/capture/page-info?session_id=${sessionId}`, {
          headers: { 'Authorization': `Bearer ${token}` }
      });
      const infoData = await infoRes.json();
      if (infoData.success) {
          setState(prev => ({
              ...prev,
              pageInfo: infoData.page_info,
              docIndex: infoData.document_index,
              totalDocs: infoData.total_documents
          }));
          
          if (voiceSessionRef.current) {
              voiceSessionRef.current.sendControlSignal('update_page_context');
              const text = infoData.page_info?.intro_prompt?.[language] || "Please capture the next document.";
              // Delay slightly so the success message has time to queue first
              setTimeout(() => {
                  if (voiceSessionRef.current) {
                      voiceSessionRef.current.sendControlSignal(`capture_speak:${text}`);
                  }
              }, 500);
          }
      }

    } catch (err) {
      setError(err.message);
      setPreviewUrl(null); // Reset on error
    } finally {
      setProcessingDoc(false);
    }
  };

  const handleAdvance = async () => {
    setProcessingDoc(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE_URL}/api/capture/advance`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        }
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Failed to advance page');
      if (!data.success) throw new Error(data.error || 'Failed to advance page');

      if (data.all_complete) {
          router.push('/dashboard/details');
          return;
      }

      // Update state for next step
      setState(prev => ({
          ...prev,
          docId: data.current_document_id,
          pageId: data.current_page_id,
      }));
      setPreviewUrl(null);
      
      // Need to re-fetch page info to update prompts and overlay
      const infoRes = await fetch(`${API_BASE_URL}/api/capture/page-info?session_id=${sessionId}`, {
          headers: { 'Authorization': `Bearer ${token}` }
      });
      const infoData = await infoRes.json();
      if (infoData.success) {
          setState(prev => ({
              ...prev,
              pageInfo: infoData.page_info,
              docIndex: infoData.document_index,
              totalDocs: infoData.total_documents
          }));
          
          if (voiceSessionRef.current) {
              voiceSessionRef.current.sendControlSignal('update_page_context');
              const text = infoData.page_info?.intro_prompt?.[language] || "Please capture the next document.";
              setTimeout(() => {
                  if (voiceSessionRef.current) {
                      voiceSessionRef.current.sendControlSignal(`capture_speak:${text}`);
                  }
              }, 500);
          }
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setProcessingDoc(false);
    }
  };
  
  const handleSendText = () => {
    if (!textInputValue.trim()) return;
    if (voiceSessionRef.current) {
      voiceSessionRef.current.sendTextInput(textInputValue.trim());
      setTextInputValue('');
    }
  };

  if (loading) return <div className={styles.container}>Loading capture engine...</div>;
  if (state.allComplete) return <div className={styles.container}>All documents captured! Redirecting...</div>;

  return (
    <div className={styles.container} style={{ background: 'radial-gradient(circle at 10% 20%, #16192b 0%, #090a0f 90%)', color: '#fff', minHeight: '100vh', display: 'flex', flexDirection: 'column', padding: 0 }}>
      {/* ─── Top Nav ─── */}
      <nav style={{ padding: '20px 40px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid rgba(255, 255, 255, 0.08)', background: 'rgba(9, 10, 15, 0.7)', backdropFilter: 'blur(20px)', width: '100%' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', fontSize: '1.25rem', fontWeight: 700, color: '#fff' }}>
            <svg width="32" height="32" viewBox="0 0 48 48" fill="none">
              <circle cx="24" cy="24" r="24" fill="url(#logo-grad)" />
              <path d="M16 24C16 19.58 19.58 16 24 16V32C19.58 32 16 28.42 16 24Z" fill="white" opacity="0.9" />
              <defs>
                <linearGradient id="logo-grad" x1="0" y1="0" x2="48" y2="48">
                  <stop stopColor="#4a78ff" /><stop offset="1" stopColor="#06b6d4" />
                </linearGradient>
              </defs>
            </svg>
            <span>Augmen.io</span>
          </div>
        </div>
        <div>
          <button
            onClick={() => {
              stopCamera();
              router.push('/dashboard');
            }}
            className="btn btn-secondary"
            style={{ fontSize: '0.875rem', fontWeight: 500, padding: '8px 16px', borderRadius: '8px', cursor: 'pointer', background: 'rgba(255,255,255,0.05)', color: '#fff', border: '1px solid rgba(255,255,255,0.1)' }}
          >
            Dashboard
          </button>
        </div>
      </nav>

      {/* Main Flow Content Container */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '40px 40px 60px', width: '100%' }}>
        {/* Progress Header */}
        <div style={{ width: '100%', maxWidth: '1200px', marginBottom: '24px' }}>
            <div className={styles.headerRow}>
                <h2 style={{ fontSize: '1.25rem', fontWeight: 600, color: '#94a3b8', margin: 0 }}>Document {state.docIndex + 1} of {state.totalDocs}</h2>
            </div>
            <div className={styles.progressBar} style={{ height: '8px', background: 'rgba(255, 255, 255, 0.05)', borderRadius: '99px', marginTop: '12px', overflow: 'hidden' }}>
                <div className={styles.progressFill} style={{ width: `${(state.docIndex / state.totalDocs) * 100}%`, background: 'linear-gradient(90deg, #4a78ff, #7c3aed)' }}></div>
            </div>
        </div>

        <div className={styles.mainLayout}>
          {/* Left: Camera / File Area */}
          <div className="glass-card" style={{ maxWidth: '100%', display: 'flex', flexDirection: 'column', position: 'relative', background: 'rgba(13, 17, 30, 0.45)', border: '1px solid rgba(255, 255, 255, 0.07)', backdropFilter: 'blur(20px)', borderRadius: '24px', padding: '32px' }}>
              {!isStarted ? (
                  <div style={{ position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, zIndex: 50, background: 'rgba(5, 7, 15, 0.9)', backdropFilter: 'blur(10px)', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', borderRadius: '24px' }}>
                      <h2 style={{ color: '#fff', marginBottom: '1.5rem', fontSize: '1.8rem', fontWeight: 700 }}>Ready to capture your documents?</h2>
                      <button 
                          onClick={startSession} 
                          className="btn btn-primary btn-lg"
                          style={{ background: 'linear-gradient(135deg, #4a78ff, #7c3aed)', boxShadow: '0 4px 20px rgba(74, 120, 255, 0.3)', border: 'none' }}
                      >
                          Start Session
                      </button>
                  </div>
              ) : null}

              <h3 style={{ marginBottom: '1.5rem', fontSize: '1.5rem', fontWeight: 700, color: '#60a5fa' }}>
                  {state.pageInfo?.page_name || 'Document'}
              </h3>
              
              {error && (
                <div style={{ color: '#ef4444', marginBottom: '1rem', padding: '0.75rem', background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.15)', borderRadius: '12px' }}>
                  {error}
                </div>
              )}

              <div className={styles.videoContainer} style={{ borderRadius: '16px', overflow: 'hidden', border: '1px solid rgba(255,255,255,0.05)' }}>
                  {!previewUrl ? (
                      <>
                          <video ref={videoRef} autoPlay playsInline muted className={styles.videoElement} />
                          {state.pageInfo?.ui_camera_overlay && (
                              <div className={styles.overlay} />
                          )}
                          <div className={styles.cameraControls} style={{ display: 'flex', gap: '10px', justifyContent: 'center', bottom: '20px' }}>
                              <button className={styles.iconButton} onClick={() => startCamera(activeFacingMode === 'user' ? 'environment' : 'user')} title="Flip Camera" style={{ background: 'rgba(15, 23, 42, 0.8)', border: '1px solid rgba(255, 255, 255, 0.15)', color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>🔄</button>
                              <button className="btn btn-primary" onClick={handleCapture} disabled={processingDoc} style={{ height: '3rem', padding: '0 24px', borderRadius: '999px', background: 'linear-gradient(135deg, #4a78ff, #7c3aed)', border: 'none', fontWeight: 600 }}>
                                  {processingDoc ? 'Processing...' : '📸 Capture'}
                              </button>
                              <label className="btn btn-secondary" style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', cursor: processingDoc ? 'not-allowed' : 'pointer', height: '3rem', padding: '0 24px', borderRadius: '999px', background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.1)', color: '#fff', fontWeight: 600 }}>
                                  📁 Upload
                                  <input 
                                      type="file" 
                                      style={{ display: 'none' }}
                                      accept={state.pageInfo?.acceptable_formats?.map(f => `.${f.replace('.','')}`).join(',')}
                                      disabled={processingDoc}
                                      onChange={handleFileUpload}
                                  />
                              </label>
                              {state.pageInfo?.allow_multiple && (
                                  <button 
                                      className="btn" 
                                      onClick={handleAdvance} 
                                      disabled={processingDoc || (state.pageInfo?.uploads_count || 0) === 0} 
                                      style={{ height: '3rem', padding: '0 24px', borderRadius: '999px', background: 'rgba(16, 185, 129, 0.15)', border: '1px solid rgba(16, 185, 129, 0.3)', color: '#34d399', fontWeight: 600, cursor: 'pointer', display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}
                                  >
                                      Done / Next Part ➔
                                  </button>
                              )}
                          </div>
                      </>
                  ) : (
                      <>
                          <img src={previewUrl} alt="Preview" className={styles.videoElement} />
                          {processingDoc && (
                              <div style={{ position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, background: 'rgba(0,0,0,0.5)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 20 }}>
                                  <div className={styles.sphereProcessing} style={{ width: '50px', height: '50px', borderRadius: '50%' }}></div>
                              </div>
                          )}
                      </>
                  )}
              </div>
              
              {/* Hidden canvas for image capture */}
              <canvas ref={canvasRef} style={{ display: 'none' }} />
          </div>

          {/* Right: Voice Agent Sidebar (Unified with Interview UI) */}
          <div className={interviewStyles.neuralCoreContainer} style={{ height: '100%', padding: '2rem 1.5rem', background: 'rgba(10, 14, 25, 0.45)', border: '1px solid rgba(255, 255, 255, 0.07)', borderRadius: '24px', backdropFilter: 'blur(20px)' }}>
            <div className={interviewStyles.connectionBar} style={{ marginBottom: '1.5rem' }}>
              <div className={`${interviewStyles.connectionDot} ${['listening', 'processing', 'speaking'].includes(qaState) ? interviewStyles.connected : ''}`}></div>
              <span className={interviewStyles.connectionText}>
                {['listening', 'processing', 'speaking'].includes(qaState) ? 'Live Audio Link' : 'Standby'}
              </span>
            </div>

            <div className={interviewStyles.neuralCoreWrapper} style={{ transform: 'scale(0.8)', marginBottom: '1rem' }}>
              <div className={`${interviewStyles.coreRing} ${interviewStyles.ring1} ${['listening', 'processing', 'speaking'].includes(qaState) ? interviewStyles.ringActive : ''}`}></div>
              <div className={`${interviewStyles.coreRing} ${interviewStyles.ring2} ${['listening', 'processing', 'speaking'].includes(qaState) ? interviewStyles.ringActive : ''}`}></div>
              <div className={`${interviewStyles.coreRing} ${interviewStyles.ring3} ${['listening', 'processing', 'speaking'].includes(qaState) ? interviewStyles.ringActive : ''}`}></div>

              <div className={`${interviewStyles.coreSphere} ${qaState === 'listening' ? interviewStyles.sphereListening : qaState === 'processing' ? interviewStyles.sphereProcessing : qaState === 'speaking' ? interviewStyles.sphereSpeaking : ''} ${['listening', 'processing', 'speaking'].includes(qaState) ? interviewStyles.sphereActive : ''}`}>
                <div className={interviewStyles.coreGlowInner}></div>
              </div>

              <div className={`${interviewStyles.visualizerWrapper} ${['listening', 'processing', 'speaking'].includes(qaState) ? interviewStyles.visualizerActive : ''}`}>
                <canvas ref={visualizerCanvasRef} style={{ width: '300px', height: '300px' }}></canvas>
              </div>
            </div>

            <div style={{ textAlign: 'center', marginBottom: 'auto', minHeight: '60px', color: '#e2e8f0', fontSize: '0.95rem', width: '100%' }}>
              {transcript || (qaState === 'listening' ? 'Listening...' : qaState === 'processing' ? 'Processing...' : qaState === 'connecting' ? 'Connecting...' : '')}
            </div>

            <div className={interviewStyles.textInputContainer} style={{ marginTop: '0', width: '100%', maxWidth: '100%' }}>
              <input 
                type="text" 
                className={interviewStyles.textInput} 
                placeholder="Type here..." 
                value={textInputValue}
                onChange={(e) => setTextInputValue(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleSendText()}
                disabled={qaState === 'connecting'}
              />
              <button className={interviewStyles.sendButton} onClick={handleSendText} disabled={!textInputValue.trim() || qaState === 'connecting'}>
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ width: '16px', height: '16px' }}>
                  <line x1="22" y1="2" x2="11" y2="13"></line>
                  <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
                </svg>
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
