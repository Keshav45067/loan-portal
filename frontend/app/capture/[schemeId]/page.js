'use client';

import { useState, useRef, useEffect, useCallback, use } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import styles from '../capture.module.css';

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

  // Start Voice Session
  useEffect(() => {
    if (!loading && !error && !state.allComplete && token && sessionId) {
        const startVoice = async () => {
            const { CaptureVoiceManager } = await import('../utils/captureVoiceHelper');
            const manager = new CaptureVoiceManager({
                token,
                sessionId,
                language,
                wsUrl: `${WS_BASE_URL.replace('http', 'ws')}/api/capture/ws/capture-voice`,
                onStateChange: (s) => setQaState(s),
                onTranscript: (t, isFinal) => { if (!isFinal) setTranscript(t); },
                onError: (err) => setError(err)
            });
            voiceSessionRef.current = manager;
            
            // Hook visualizer
            manager.onAudioLevel = (l) => {
                if (visualizerInstanceRef.current) visualizerInstanceRef.current.updateAudioData(l);
            };

            await manager.connect();
        };
        startVoice();
    }
  }, [loading, error, state.allComplete, token, sessionId, language]);

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
    if (!loading && !error && !state.allComplete) {
        const facing = state.pageInfo?.ui_camera_overlay === 'selfie' ? 'user' : 'environment';
        startCamera(facing);
    }
    return stopCamera;
  }, [loading, error, state.allComplete, state.pageInfo, startCamera, stopCamera]);

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
        const ext = file.name.split('.').pop().toLowerCase();
        const allowed_exts = formats.map(f => f.toLowerCase().replace('.', ''));
        if (!allowed_exts.includes(ext)) {
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
          if (voiceSessionRef.current && data.validation_error_key) {
              voiceSessionRef.current.sendControlSignal(`capture_error:${data.validation_error_key}:${data.validation_field_id}`);
          }
          throw new Error(data.validation_error_text || 'Validation failed. Please try again.');
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
      }

    } catch (err) {
      setError(err.message);
      setPreviewUrl(null); // Reset on error
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
    <div className={styles.container} style={{ padding: '1rem', maxWidth: '100vw' }}>
      {/* Progress Header */}
      <div style={{ width: '100%', maxWidth: '1200px', marginBottom: '1rem' }}>
          <div className={styles.headerRow}>
              <h2 style={{ fontSize: '1.2rem', margin: 0 }}>Document {state.docIndex + 1} of {state.totalDocs}</h2>
          </div>
          <div className={styles.progressBar}>
              <div className={styles.progressFill} style={{ width: `${(state.docIndex / state.totalDocs) * 100}%` }}></div>
          </div>
      </div>

      <div className={styles.mainLayout}>
        {/* Left: Camera / File Area */}
        <div className={styles.card} style={{ maxWidth: '100%', display: 'flex', flexDirection: 'column' }}>
            <h3 style={{ marginBottom: '0.5rem', fontSize: '1.5rem', color: '#60a5fa' }}>
                {state.pageInfo?.page_name || 'Document'}
            </h3>
            
            {error && (
              <div style={{ color: '#ef4444', marginBottom: '1rem', padding: '0.5rem', background: 'rgba(239,68,68,0.1)', borderRadius: '0.5rem' }}>
                {error}
              </div>
            )}

            <div className={styles.videoContainer}>
                {!previewUrl ? (
                    <>
                        <video ref={videoRef} autoPlay playsInline muted className={styles.videoElement} />
                        {state.pageInfo?.ui_camera_overlay && (
                            <div className={styles.overlay} />
                        )}
                        <div className={styles.cameraControls} style={{ display: 'flex', gap: '0.5rem', justifyContent: 'center' }}>
                            <button className={styles.iconButton} onClick={() => startCamera(activeFacingMode === 'user' ? 'environment' : 'user')} title="Flip Camera">🔄</button>
                            <button className={styles.captureButton} onClick={handleCapture} disabled={processingDoc}>
                                {processingDoc ? 'Processing...' : '📸 Capture'}
                            </button>
                            <label className={styles.captureButton} style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', cursor: processingDoc ? 'not-allowed' : 'pointer', background: '#4b5563' }}>
                                📁 Upload
                                <input 
                                    type="file" 
                                    style={{ display: 'none' }}
                                    accept={state.pageInfo?.acceptable_formats?.map(f => `.${f.replace('.','')}`).join(',')}
                                    disabled={processingDoc}
                                    onChange={handleFileUpload}
                                />
                            </label>
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

        {/* Right: Voice Agent Sidebar */}
        <div className={styles.voiceAgent}>
            <h3 style={{ margin: 0, color: '#a78bfa' }}>Assistant</h3>
            
            <div className={styles.neuralCore}>
                {qaState === 'listening' && <div className={`${styles.coreSphere} ${styles.sphereListening}`} />}
                {qaState === 'processing' && <div className={`${styles.coreSphere} ${styles.sphereProcessing}`} />}
                {qaState === 'speaking' && <div className={`${styles.coreSphere} ${styles.sphereSpeaking}`} />}
                {qaState === 'idle' && <div className={styles.coreSphere} />}
                
                <div style={{ position: 'absolute', top: -50, left: -50 }}>
                    <canvas ref={visualizerCanvasRef} style={{ width: '300px', height: '300px', pointerEvents: 'none' }} />
                </div>
            </div>

            <div className={styles.transcriptBox}>
                {transcript || (qaState === 'listening' ? 'Listening...' : qaState === 'processing' ? 'Processing...' : 'Connecting...')}
            </div>

            <div style={{ width: '100%', marginTop: 'auto', display: 'flex', gap: '0.5rem' }}>
                <input 
                    type="text" 
                    className={styles.input} 
                    placeholder="Type a question..." 
                    value={textInputValue}
                    onChange={(e) => setTextInputValue(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && handleSendText()}
                    disabled={qaState === 'connecting'}
                />
                <button className={styles.iconButton} onClick={handleSendText} disabled={!textInputValue.trim()}>
                    ➤
                </button>
            </div>
        </div>
      </div>
    </div>
  );
}
