'use client';

import { useState, useRef, useEffect, useCallback, use } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import styles from '../capture.module.css';
import interviewStyles from '../../interview/interview.module.css';
import useCaptureGuard from '../useCaptureGuard';

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
  const [localUploadsCount, setLocalUploadsCount] = useState(0);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  
  // File / Camera State
  const videoRef = useRef(null);
  const canvasRef = useRef(null);
  const streamRef = useRef(null);
  const [activeFacingMode, setActiveFacingMode] = useState('environment');
  const [previewUrl, setPreviewUrl] = useState(null);
  const [processingDoc, setProcessingDoc] = useState(false);
  const autoCaptureTriggeredRef = useRef(false);

  // Voice Agent State
  const [qaState, setQaState] = useState('idle');
  const [transcript, setTranscript] = useState('');
  const [textInputValue, setTextInputValue] = useState('');
  const voiceSessionRef = useRef(null);
  
  const visualizerCanvasRef = useRef(null);
  const visualizerInstanceRef = useRef(null);

  // Live guard hook for real time guidance and document edge detection
  const {
    cvLoaded,
    cvLoadingError,
    brightness,
    blur,
    coverage,
    isStable,
    documentQuad,
    overallReady,
    statusText,
    statusColor
  } = useCaptureGuard(
    videoRef,
    isStarted && !previewUrl && !processingDoc && !state.allComplete,
    state.pageInfo?.orientation || 'landscape'
  );

  // Auto-capture when document is stable and all metrics pass
  useEffect(() => {
    if (overallReady && !processingDoc && !previewUrl && isStarted && !autoCaptureTriggeredRef.current) {
      autoCaptureTriggeredRef.current = true;
      console.log('OpenCV.js live guard: conditions satisfied, starting auto-capture!');
      handleCapture();
    }
  }, [overallReady, processingDoc, previewUrl, isStarted]);

  // Reset auto-capture flag on new pages or when clearing preview
  useEffect(() => {
    if (!previewUrl && !processingDoc) {
      autoCaptureTriggeredRef.current = false;
    }
  }, [previewUrl, processingDoc, state.pageId]);

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
        setLocalUploadsCount(data.current_page_info?.uploads_count || 0);

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
    
    if (typeof navigator === 'undefined' || !navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      setError('Camera API is not supported in this browser. Please use manual upload.');
      return;
    }

    const constraints = {
      video: {
        facingMode: { ideal: facingMode },
        width: { ideal: 1280 },
        height: { ideal: 720 }
      }
    };

    try {
      const stream = await navigator.mediaDevices.getUserMedia(constraints);
      streamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        videoRef.current.play().catch(e => console.error("Error playing video stream:", e));
      }
    } catch (err) {
      console.warn("Primary camera constraints failed, attempting fallback:", err);
      try {
        const fallbackStream = await navigator.mediaDevices.getUserMedia({
          video: { width: { ideal: 1280 }, height: { ideal: 720 } }
        });
        streamRef.current = fallbackStream;
        if (videoRef.current) {
          videoRef.current.srcObject = fallbackStream;
          videoRef.current.play().catch(e => console.error("Error playing video stream:", e));
        }
      } catch (fallbackErr) {
        console.error("All camera constraints failed:", fallbackErr);
        
        let friendlyMessage = 'Failed to access camera.';
        if (fallbackErr.name === 'NotAllowedError' || fallbackErr.name === 'PermissionDeniedError') {
          friendlyMessage = 'Camera access denied. Please enable camera permissions in your browser settings and refresh.';
        } else if (fallbackErr.name === 'NotFoundError' || fallbackErr.name === 'DevicesNotFoundError') {
          friendlyMessage = 'No camera found on this device. Please connect a camera or use manual file upload.';
        } else if (fallbackErr.name === 'NotReadableError' || fallbackErr.name === 'TrackStartError') {
          friendlyMessage = 'Camera is currently in use by another application. Please close other camera apps and retry.';
        } else if (fallbackErr.name === 'OverconstrainedError') {
          friendlyMessage = 'Camera constraints could not be satisfied on this device.';
        } else {
          friendlyMessage = `Camera error: ${fallbackErr.message || fallbackErr.name || 'Unknown'}`;
        }
        setError(friendlyMessage);
      }
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
          
          setError(data.validation_error_text || data.error || 'Validation failed. Please try again.');
          
          if (data.next_page_id) {
              setState(prev => ({
                  ...prev,
                  docId: data.next_document_id || prev.docId,
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
                  
                  if (infoData.page_info?.uploads_count !== undefined) {
                      setLocalUploadsCount(infoData.page_info.uploads_count);
                  }
                  
                  if (voiceSessionRef.current) {
                      voiceSessionRef.current.sendControlSignal('update_page_context');
                      const text = infoData.page_info?.intro_prompt?.[language] || "Please capture the document again.";
                      setTimeout(() => {
                          if (voiceSessionRef.current) {
                              voiceSessionRef.current.sendControlSignal(`capture_speak:${text}`);
                          }
                      }, 500);
                  }
              }
          }
          return;
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
      setLocalUploadsCount(prev => prev + 1);
      
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
          
          if (infoData.page_info?.uploads_count !== undefined) {
              setLocalUploadsCount(infoData.page_info.uploads_count);
          }
          
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
      
      if (!data.success) {
          // Extraction validation failed
          if (voiceSessionRef.current) {
              voiceSessionRef.current.stopAudioPlayback();
              const errKey = data.validation_error_key || 'error_low_confidence';
              voiceSessionRef.current.sendControlSignal(`capture_error:${errKey}`);
          }
          
          setError(data.validation_error_text || data.error || 'Validation failed. Please try again.');
          
          if (data.next_page_id) {
              setState(prev => ({
                  ...prev,
                  docId: data.next_document_id || prev.docId,
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
                  
                  if (infoData.page_info?.uploads_count !== undefined) {
                      setLocalUploadsCount(infoData.page_info.uploads_count);
                  }
                  
                  if (voiceSessionRef.current) {
                      voiceSessionRef.current.sendControlSignal('update_page_context');
                      const text = infoData.page_info?.intro_prompt?.[language] || "Please capture the document again.";
                      setTimeout(() => {
                          if (voiceSessionRef.current) {
                              voiceSessionRef.current.sendControlSignal(`capture_speak:${text}`);
                          }
                      }, 500);
                  }
              }
          }
          return;
      }

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
          setLocalUploadsCount(infoData.page_info?.uploads_count || 0);
          
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

  if (loading) return <div className={styles.container} style={{ justifyContent: 'center', height: '100vh' }}>Loading capture engine...</div>;
  if (state.allComplete) return <div className={styles.container} style={{ justifyContent: 'center', height: '100vh' }}>All documents captured! Redirecting...</div>;

  return (
    <div className={styles.container}>
      {/* ─── Background Camera Layer ─── */}
      <div className={styles.fullScreenCamera}>
        {!previewUrl ? (
          <>
            <video ref={videoRef} autoPlay playsInline muted className={styles.videoElement} />
            <div className={`${styles.guideBox} ${state.pageInfo?.orientation === 'portrait' ? styles.guidePortrait : styles.guideLandscape}`} />
            <div className={styles.statusBadge} style={{ color: statusColor !== '#94a3b8' ? statusColor : '#000' }}>
              {statusText}
            </div>
            {cvLoaded && documentQuad && (
              <svg className={styles.overlaySvg} viewBox="0 0 1000 1000" preserveAspectRatio="none">
                <polygon
                  points={documentQuad.map(p => `${Math.round(p.x * 1000)},${Math.round(p.y * 1000)}`).join(' ')}
                  className={`${styles.detectedPoly} ${overallReady ? styles.detectedPolyReady : ''}`}
                />
              </svg>
            )}
          </>
        ) : (
          <>
            <img src={previewUrl} alt="Preview" className={styles.videoElement} />
            {processingDoc && (
              <div style={{ position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, background: 'rgba(0,0,0,0.7)', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', zIndex: 20 }}>
                <div className={styles.sphereProcessing} style={{ width: '56px', height: '56px', marginBottom: '1.25rem' }}></div>
                <span style={{ color: '#fff', fontSize: '1rem', fontWeight: 500 }}>Processing details with AI...</span>
              </div>
            )}
          </>
        )}
      </div>

      {/* ─── Foreground UI Layer ─── */}
      <div className={styles.uiOverlay}>
        {/* Top Nav */}
        <nav className={styles.topNav}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', fontSize: '1.25rem', fontWeight: 700 }} className={styles.topNavText}>
              <svg width="32" height="32" viewBox="0 0 48 48" fill="none">
                <circle cx="24" cy="24" r="24" fill="url(#logo-grad)" />
                <path d="M16 24C16 19.58 19.58 16 24 16V32C19.58 32 16 28.42 16 24Z" fill="white" opacity="1" />
                <defs>
                  <linearGradient id="logo-grad" x1="0" y1="0" x2="48" y2="48">
                    <stop stopColor="#4a78ff" /><stop offset="1" stopColor="#06b6d4" />
                  </linearGradient>
                </defs>
              </svg>
              <span>Augmen.io</span>
            </div>
          </div>
          <button
            onClick={() => {
              stopCamera();
              router.push('/dashboard');
            }}
            className={`${styles.interactive}`}
            style={{ fontSize: '0.875rem', fontWeight: 600, padding: '8px 16px', borderRadius: '8px', cursor: 'pointer', background: 'rgba(255,255,255,0.2)', color: '#fff', border: '1px solid rgba(255,255,255,0.4)', backdropFilter: 'blur(10px)' }}
          >
            Dashboard
          </button>
        </nav>

        {/* Start Overlay */}
        {!isStarted && (
            <div style={{ position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, zIndex: 50, background: 'rgba(0, 0, 0, 0.8)', backdropFilter: 'blur(20px)', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center' }} className={styles.interactive}>
                <h2 style={{ color: '#fff', marginBottom: '1.25rem', fontSize: '2.2rem', fontWeight: 700 }}>Ready to scan?</h2>
                <p style={{ color: '#cbd5e1', marginBottom: '2.5rem', maxWidth: '400px', textAlign: 'center', fontSize: '1.05rem', lineHeight: '1.6' }}>
                    We will guide you to capture your document with optimal brightness, stability, and alignment automatically.
                </p>
                <button 
                    onClick={startSession} 
                    style={{ background: '#fff', color: '#000', border: 'none', borderRadius: '999px', padding: '16px 40px', fontSize: '1.1rem', fontWeight: 700, cursor: 'pointer', boxShadow: '0 8px 32px rgba(255, 255, 255, 0.3)', transition: 'transform 0.2s' }}
                    onMouseOver={(e) => e.currentTarget.style.transform = 'scale(1.05)'}
                    onMouseOut={(e) => e.currentTarget.style.transform = 'scale(1)'}
                >
                    Start Scanning
                </button>
            </div>
        )}

        {/* Loading OpenCV state */}
        {isStarted && !cvLoaded && !cvLoadingError && !previewUrl && (
            <div style={{ position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, zIndex: 40, background: 'rgba(0, 0, 0, 0.6)', backdropFilter: 'blur(10px)', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center' }}>
                <div className={styles.sphereProcessing} style={{ width: '56px', height: '56px', marginBottom: '1.5rem' }}></div>
                <span style={{ color: '#fff', fontSize: '1.1rem', fontWeight: 500 }}>Initializing AI scanner...</span>
            </div>
        )}

        {/* Main Content Layout */}
        <div className={styles.mainLayout}>
          
          <div className={styles.leftControls}>
            {/* Header / Progress over camera */}
            <div style={{ width: '100%', maxWidth: '600px', marginBottom: '24px' }}>
                <div className={styles.headerRow}>
                    <h2 style={{ fontSize: '1.15rem', fontWeight: 600, color: '#fff', margin: 0 }}>Document {state.docIndex + 1} of {state.totalDocs}</h2>
                    <span style={{ fontSize: '0.95rem', color: '#93c5fd', fontWeight: 700 }}>{state.pageInfo?.page_name}</span>
                </div>
                <div className={styles.progressBar}>
                    <div className={styles.progressFill} style={{ width: `${(state.docIndex / state.totalDocs) * 100}%` }}></div>
                </div>
            </div>

            {error && (
              <div className={`${styles.errorCard} ${styles.interactive}`}>
                <div style={{ display: 'flex', gap: '12px', alignItems: 'flex-start' }}>
                  <span style={{ fontSize: '1.5rem' }}>⚠️</span>
                  <div>
                    <h4 style={{ margin: '0 0 4px', fontSize: '1.05rem', fontWeight: 700 }}>Action Required</h4>
                    <p style={{ margin: 0, fontSize: '0.95rem', lineHeight: '1.4' }}>{error}</p>
                  </div>
                </div>
              </div>
            )}

            {!previewUrl && (
              <div className={styles.cameraControls}>
                  <button className={styles.iconButton} onClick={() => startCamera(activeFacingMode === 'user' ? 'environment' : 'user')} title="Flip Camera">🔄</button>
                  <button className={styles.captureButton} onClick={handleCapture} disabled={processingDoc}>
                      {processingDoc ? 'Processing...' : '📸 Capture'}
                  </button>
                  <label className={styles.iconButton} style={{ cursor: processingDoc ? 'not-allowed' : 'pointer' }} title="Upload File">
                      📁
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
                          onClick={handleAdvance} 
                          className={styles.interactive}
                          disabled={processingDoc || ((state.pageInfo?.uploads_count || 0) === 0 && localUploadsCount === 0)} 
                          style={{ height: '3rem', padding: '0 24px', borderRadius: '999px', background: 'rgba(16, 185, 129, 0.25)', border: '1px solid rgba(16, 185, 129, 0.5)', color: '#fff', fontWeight: 700, cursor: 'pointer', display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}
                      >
                          Next ➔
                      </button>
                  )}
              </div>
            )}
          </div>

          {/* Right: Voice Agent Sidebar */}
          <div className={`${styles.voiceAgentSidebar}`}>
            <div className={interviewStyles.connectionBar} style={{ marginBottom: '1.5rem' }}>
              <div className={`${interviewStyles.connectionDot} ${['listening', 'processing', 'speaking'].includes(qaState) ? interviewStyles.connected : ''}`}></div>
              <span className={interviewStyles.connectionText} style={{ color: '#475569', fontWeight: 600 }}>
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

            <div style={{ textAlign: 'center', marginBottom: 'auto', minHeight: '60px', color: '#0f172a', fontSize: '0.95rem', width: '100%', padding: '0 0.5rem', lineHeight: '1.5', fontWeight: 600 }}>
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
      
      {/* Hidden canvas for image capture */}
      <canvas ref={canvasRef} style={{ display: 'none' }} />
    </div>
  );
}
