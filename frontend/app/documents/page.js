'use client';

import { useState, useRef, useEffect, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import styles from './documents.module.css';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080';
const WS_BASE_URL = process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8080';

const DOCUMENT_METADATA_LOCALIZED = {
  hi: {
    'selfie': { label: 'सेल्फी', icon: '🤳', facingMode: 'user', tips: ['चेहरा साफ दिखे', 'अच्छी रोशनी हो'] },
    'aadhaar_front': { label: 'आधार (आगे)', icon: '🪪', facingMode: 'environment', tips: ['पूरा कार्ड दिखे', 'नंबर साफ हो'] },
    'aadhaar_back': { label: 'आधार (पीछे)', icon: '🪪', facingMode: 'environment', tips: ['QR कोड साफ हो'] },
    'pan': { label: 'पैन कार्ड', icon: '💳', facingMode: 'environment', tips: ['पूरा पैन कार्ड फ्रेम में हो'] },
    'spouse_pan': { label: 'पति/पत्नी पैन', icon: '💳', facingMode: 'environment', tips: ['पति या पत्नी का पैन कार्ड रखें'] },
    'udyam': { label: 'उद्यम प्रमाणपत्र', icon: '📜', facingMode: 'environment', tips: ['पूरा उद्यम पत्र रखें'] },
    'bank_statement': { label: 'बैंक स्टेटमेंट', icon: '🏦', facingMode: 'environment', tips: ['सभी पेज शामिल हों'] },
    'company_id': { label: 'कंपनी आईडी', icon: '🏢', facingMode: 'environment', tips: ['आईडी साफ हो'] },
    'office_id': { label: 'ऑफिस आईडी', icon: '🪪', facingMode: 'environment', tips: ['ऑफिस आईडी साफ हो'] },
    'address_proof': { label: 'पता का प्रमाण', icon: '📄', facingMode: 'environment', tips: ['पता साफ दिखना चाहिए'] }
  },
  en: {
    'selfie': { label: 'Selfie', icon: '🤳', facingMode: 'user', tips: ['Face should be clearly visible', 'Good lighting is required'] },
    'aadhaar_front': { label: 'Aadhaar (Front)', icon: '🪪', facingMode: 'environment', tips: ['Full card should be visible', 'Number must be clear'] },
    'aadhaar_back': { label: 'Aadhaar (Back)', icon: '🪪', facingMode: 'environment', tips: ['QR code should be clear'] },
    'pan': { label: 'PAN Card', icon: '💳', facingMode: 'environment', tips: ['Full PAN card should be in frame'] },
    'spouse_pan': { label: 'Spouse PAN', icon: '💳', facingMode: 'environment', tips: ['Keep spouse\'s PAN card ready'] },
    'udyam': { label: 'Udyam Certificate', icon: '📜', facingMode: 'environment', tips: ['Keep full Udyam document ready'] },
    'bank_statement': { label: 'Bank Statement', icon: '🏦', facingMode: 'environment', tips: ['All pages must be included'] },
    'company_id': { label: 'Company ID', icon: '🏢', facingMode: 'environment', tips: ['ID should be clear'] },
    'office_id': { label: 'Office ID', icon: '🪪', facingMode: 'environment', tips: ['Office ID should be clear'] },
    'address_proof': { label: 'Address Proof', icon: '📄', facingMode: 'environment', tips: ['Address must be clearly visible'] }
  },
  te: {
    'selfie': { label: 'సెల్ఫీ', icon: '🤳', facingMode: 'user', tips: ['ముఖం స్పష్టంగా కనిపించాలి', 'మంచి వెలుతురు ఉండాలి'] },
    'aadhaar_front': { label: 'ఆధార్ (ముందు)', icon: '🪪', facingMode: 'environment', tips: ['కార్డు మొత్తం కనిపించాలి', 'నంబర్ స్పష్టంగా ఉండాలి'] },
    'aadhaar_back': { label: 'ఆధార్ (వెనుక)', icon: '🪪', facingMode: 'environment', tips: ['QR కోడ్ స్పష్టంగా ఉండాలి'] },
    'pan': { label: 'పాన్ కార్డ్', icon: '💳', facingMode: 'environment', tips: ['పాన్ కార్డ్ మొత్తం ఫ్రేమ్‌లో ఉండాలి'] },
    'spouse_pan': { label: 'భర్త/భార్య పాన్', icon: '💳', facingMode: 'environment', tips: ['భర్త లేదా భార్య పాన్ కార్డ్ ఉంచండి'] },
    'udyam': { label: 'ఉద్యమ ధృవీకరణ పత్రం', icon: '📜', facingMode: 'environment', tips: ['ఉద్యమ పత్రం మొత్తం ఉంచండి'] },
    'bank_statement': { label: 'బ్యాంక్ స్టేట్‌మెంట్', icon: '🏦', facingMode: 'environment', tips: ['అన్ని పేజీలు ఉండాలి'] },
    'company_id': { label: 'కంపెనీ ఐడి', icon: '🏢', facingMode: 'environment', tips: ['ఐడి స్పష్టంగా ఉండాలి'] },
    'office_id': { label: 'ఆఫీస్ ఐడి', icon: '🪪', facingMode: 'environment', tips: ['ఆఫీస్ ఐడి స్పష్టంగా ఉండాలి'] },
    'address_proof': { label: 'చిరునామా రుజువు', icon: '📄', facingMode: 'environment', tips: ['చిరునామా స్పష్టంగా కనిపించాలి'] }
  }
};

export default function DocumentsPage() {
  const router = useRouter();

  // Basic Session Info
  const [token, setToken] = useState('');
  const [sessionId, setSessionId] = useState('');
  const [applicationId, setApplicationId] = useState('');
  const [schemeId, setSchemeId] = useState('sbi-account-opening'); // Or dynamically fetched

  // Flow State (Driven by backend)
  const [isStarted, setIsStarted] = useState(false);
  const [nodeType, setNodeType] = useState('voice-qa'); // 'voice-qa' or 'capture'
  const [documentId, setDocumentId] = useState('selfie');
  const [currentStep, setCurrentStep] = useState(0);
  const [totalSteps, setTotalSteps] = useState(0);

  // Voice Assistant State
  const [qaState, setQaState] = useState('idle');
  const [transcript, setTranscript] = useState('');
  const [textInputValue, setTextInputValue] = useState('');
  const voiceSessionRef = useRef(null);

  // Document Uploads State
  const [docs, setDocs] = useState({});
  const [verified, setVerified] = useState({});
  const [verifying, setVerifying] = useState(false);
  const [errors, setErrors] = useState({});
  const [selectedLanguage, setSelectedLanguage] = useState('hi');

  // Live Camera Refs & State
  const fileInputRef = useRef(null);
  const videoRef = useRef(null);
  const canvasRef = useRef(null);
  const streamRef = useRef(null);
  const [activeFacingMode, setActiveFacingMode] = useState('environment');

  console.log('[DEBUG Frontend] RENDER: isStarted =', isStarted, 'nodeType =', nodeType, 'documentId =', documentId, 'qaState =', qaState);

  useEffect(() => {
    const savedToken = localStorage.getItem('token');
    const savedSessionId = localStorage.getItem('session_id');
    const savedApplicationId = localStorage.getItem('application_id');
    const savedSchemeId = localStorage.getItem('scheme_id') || 'sbi-account-opening';
    if (!savedToken || !savedSessionId) {
      router.push('/');
    } else {
      setToken(savedToken);
      setSessionId(savedSessionId);
      setApplicationId(savedApplicationId || '');
      setSchemeId(savedSchemeId);
    }

    import('../utils/voiceHelper').then(({ loadVADScripts }) => {
      loadVADScripts().catch(console.error);
    });
    
    return () => {
        if (voiceSessionRef.current) {
            voiceSessionRef.current.disconnect();
        }
    }
  }, [router]);

  const startSession = async () => {
    setErrors(prev => ({ ...prev, global: null, warning: null }));
    setIsStarted(true);
    setQaState('connecting');

    // VERY IMPORTANT: Initialize and resume AudioContext SYNCHRONOUSLY in the click handler
    window.globalAudioContext = window.globalAudioContext || new (window.AudioContext || window.webkitAudioContext)();
    if (window.globalAudioContext.state === 'suspended') {
        try { window.globalAudioContext.resume(); } catch (e) { console.error('Failed to resume AudioContext:', e); }
    }

    try {
      const { VoiceSessionManager, loadVADScripts } = await import('../utils/voiceHelper');

      const isLoaded = await loadVADScripts();
      if (!isLoaded) {
        throw new Error('VAD scripts could not be loaded. Please check your internet connection and reload the page.');
      }

      const manager = new VoiceSessionManager({
        token,
        sessionId,
        applicationId,
        applicantName: localStorage.getItem('applicant_name') || 'आवेदक',
        schemeId: schemeId,
        language: selectedLanguage,
        wsUrl: `${WS_BASE_URL.replace('http', 'ws')}/ws/voice`,
        onStateChange: (state) => {
          console.log('[DEBUG Frontend] onStateChange:', state);
          setQaState(state);
        },
        onTranscript: (text, isFinal) => {
          console.log('[DEBUG Frontend] onTranscript:', text, 'isFinal:', isFinal);
          if (!isFinal) setTranscript(text);
        },
        onProgress: (step, total, nodeId) => {
          console.log('[DEBUG Frontend] onProgress: step =', step, 'total =', total, 'nodeId =', nodeId);
          setCurrentStep(step);
          setTotalSteps(total);
        },
        onNodeChange: (type, docId) => {
          console.log('[DEBUG Frontend] onNodeChange: type =', type, 'docId =', docId);
          setNodeType(type);
          if (docId) setDocumentId(docId);
        },
        onComplete: async () => {
          console.log('[DEBUG Frontend] onComplete triggered, saving state and redirecting...');
          try {
            const savedToken = localStorage.getItem('token') || token;
            const savedSessionId = localStorage.getItem('session_id') || sessionId;
            if (savedToken && savedSessionId) {
              await fetch(`${API_BASE_URL}/api/applications/save-metadata`, {
                method: 'POST',
                headers: {
                  'Content-Type': 'application/json',
                  'Authorization': `Bearer ${savedToken}`
                },
                body: JSON.stringify({
                  session_id: savedSessionId,
                  fields: {
                    onboarding_finished: true,
                    completion_status: 'COMPLETED'
                  }
                })
              });
            }
          } catch (e) {
            console.error('Failed to update onboarding_finished status:', e);
          }
          router.push('/dashboard/details');
        },
        onSystemMessage: (type, msg) => {
           if (type === 'error' || type === 'system_error') {
               setErrors(prev => ({ ...prev, global: msg }));
               setQaState('error');
               setIsStarted(false);
           } else if (type === 'warning') {
               setErrors(prev => ({ ...prev, warning: msg }));
           }
        },
        onError: (err) => {
          setErrors({ global: err });
          setQaState('error');
          setIsStarted(false);
        }
      });

      voiceSessionRef.current = manager;
      await manager.connect();
    } catch (err) {
      setErrors({ global: err.message });
      setQaState('error');
      setIsStarted(false);
    }
  };

  const handleSendText = () => {
    if (!textInputValue.trim()) return;
    if (voiceSessionRef.current) {
      voiceSessionRef.current.sendTextInput(textInputValue.trim());
      setTextInputValue('');
    }
  };

  const stopCamera = useCallback(() => {
    if (streamRef.current) {
      streamRef.current.getTracks().forEach(t => t.stop());
      streamRef.current = null;
    }
  }, []);

  const startCamera = useCallback(async (facingMode) => {
    stopCamera();
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
  }, [stopCamera]);

  const handleFlipCamera = () => {
    const newMode = activeFacingMode === 'user' ? 'environment' : 'user';
    setActiveFacingMode(newMode);
    startCamera(newMode);
  };

  const uploadFileDirectly = async (file) => {
    if (!file) return;
    const previewUrl = URL.createObjectURL(file);
    setDocs(prev => ({ ...prev, [documentId]: { file, url: previewUrl, name: file.name } }));
    setVerifying(true);
    setErrors(prev => ({ ...prev, [documentId]: null }));

    try {
      const formData = new FormData();
      formData.append('file', file);
      formData.append('document_type', documentId);
      formData.append('scheme_id', schemeId);
      formData.append('session_id', sessionId);

      const res = await fetch(`${API_BASE_URL}/api/documents/extract`, {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${token}` },
        body: formData
      });

      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || data.error || 'Failed to upload');
      if (data.success === false) {
        throw new Error(data.error || 'दस्तावेज़ सत्यापन विफल रहा। कृपया सही दस्तावेज़ अपलोड करें।');
      }

      setVerified(prev => ({ ...prev, [documentId]: true }));
      
      // Document captured successfully! Advance the graph.
      if (voiceSessionRef.current) {
          voiceSessionRef.current.sendControlSignal('capture_complete');
      }

    } catch (err) {
      setErrors(prev => ({ ...prev, [documentId]: err.message }));
      setDocs(prev => {
        const copy = { ...prev };
        delete copy[documentId];
        return copy;
      });
    } finally {
      setVerifying(false);
    }
  };

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
          const file = new File([blob], `${documentId}.jpg`, { type: 'image/jpeg' });
          await uploadFileDirectly(file);
        }
      }, 'image/jpeg', 0.85);
    }
  };

  useEffect(() => {
    if (isStarted && nodeType === 'capture' && !docs[documentId]) {
      const meta = (DOCUMENT_METADATA_LOCALIZED[selectedLanguage] || DOCUMENT_METADATA_LOCALIZED['hi'])[documentId] || {};
      const facing = meta.facingMode || activeFacingMode;
      startCamera(facing);
    } else {
      stopCamera();
    }
    return () => stopCamera();
  }, [isStarted, nodeType, documentId, activeFacingMode, docs[documentId], selectedLanguage, startCamera, stopCamera]);


  // Render Neural Voice Core
  const renderVoiceUI = () => {
    let sphereClass = styles.coreSphere;
    let ringClass = '';
    const isEn = selectedLanguage === 'en';
    const isTe = selectedLanguage === 'te';
    let statusText = isEn ? 'Connecting...' : isTe ? 'కనెక్ట్ అవుతోంది...' : 'कनेक्ट कर रहे हैं...';
    let isCallActive = false;

    if (qaState === 'listening') {
      sphereClass = `${styles.coreSphere} ${styles.sphereListening}`;
      ringClass = styles.ringActive;
      statusText = transcript || (isEn ? 'Listening...' : isTe ? 'వింటున్నారు...' : 'सुन रही हूँ...');
      isCallActive = true;
    } else if (qaState === 'processing') {
      sphereClass = `${styles.coreSphere} ${styles.sphereProcessing}`;
      ringClass = styles.ringActive;
      statusText = isEn ? 'Processing...' : isTe ? 'ప్రాసెస్ అవుతోంది...' : 'प्रोसेसिंग...';
      isCallActive = true;
    } else if (qaState === 'speaking') {
      sphereClass = `${styles.coreSphere} ${styles.sphereSpeaking}`;
      ringClass = styles.ringActive;
      statusText = transcript || (isEn ? 'Speaking...' : isTe ? 'మాట్లాడుతున్నారు...' : 'बोल रही हूँ...');
      isCallActive = true;
    }

    return (
      <div className={styles.neuralCoreContainer}>
        <div className={styles.connectionBar}>
          <div className={`${styles.connectionDot} ${isCallActive ? styles.connected : ''}`}></div>
          <span className={styles.connectionText}>
            {isCallActive ? 'Live Audio Link' : 'Standby'}
          </span>
        </div>

        <div className={styles.neuralTitle}>
          <h2 className={styles.neuralH2}>
            Chayan <span className={styles.neuralAccent}>AI</span>
          </h2>
          <div className={`${styles.callStatusText} ${isCallActive ? styles.callActive : ''}`}>
            {statusText}
          </div>
        </div>

        <div className={styles.neuralCoreWrapper}>
          <div className={`${styles.coreRing} ${styles.ring1} ${ringClass}`}></div>
          <div className={`${styles.coreRing} ${styles.ring2} ${ringClass}`}></div>
          <div className={`${styles.coreRing} ${styles.ring3} ${ringClass}`}></div>

          <div className={`${sphereClass} ${isCallActive ? styles.sphereActive : ''}`}>
            <div className={styles.coreGlowInner}></div>
            <img src="/logo.png" alt="AI Core" className={styles.aiLogo} />
          </div>
        </div>

        {/* Text Input Row */}
        {isStarted && (
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
              disabled={qaState === 'connecting'}
            />
            <button 
              className={styles.sendButton} 
              onClick={handleSendText} 
              aria-label="Send text"
              disabled={qaState === 'connecting' || !textInputValue.trim()}
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <line x1="22" y1="2" x2="11" y2="13"></line>
                <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
              </svg>
            </button>
          </div>
        )}
      </div>
    );
  };

  // Render Camera UI
  const renderCameraUI = () => {
    const meta = (DOCUMENT_METADATA_LOCALIZED[selectedLanguage] || DOCUMENT_METADATA_LOCALIZED['hi'])[documentId] || (DOCUMENT_METADATA_LOCALIZED[selectedLanguage] || DOCUMENT_METADATA_LOCALIZED['hi'])['selfie'];
    const docData = docs[documentId];

    return (
      <div className={styles.detailCard}>
        <div className={styles.cardHeader}>
          <div className={styles.cardIconLarge}>{meta.icon}</div>
          <div style={{ flex: 1 }}>
            <h3 className={styles.cardTitle}>{meta.label} अपलोड करें</h3>
            <p className={styles.cardDesc}>कैमरा से स्कैन करें या गैलरी से चुनें</p>
          </div>
        </div>

        <div className={styles.videoContainer}>
          {/* 1. Live Video Stream */}
          {!docData && (
            <div style={{ position: 'relative', width: '100%', height: '100%', display: 'flex', flexDirection: 'column' }}>
              <video
                ref={videoRef}
                autoPlay
                playsInline
                muted
                className={styles.videoElement}
              />
              <div style={{
                position: 'absolute',
                bottom: '16px',
                left: 0,
                right: 0,
                display: 'flex',
                justifyContent: 'center',
                gap: '16px',
                zIndex: 20
              }}>
                <button 
                  onClick={handleFlipCamera}
                  style={{
                    backgroundColor: 'rgba(15, 23, 42, 0.65)',
                    color: 'white',
                    border: '1px solid rgba(255,255,255,0.2)',
                    borderRadius: '50%',
                    width: '48px',
                    height: '48px',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    cursor: 'pointer',
                    fontSize: '1.25rem',
                    backdropFilter: 'blur(8px)',
                    transition: 'transform 0.2s'
                  }}
                  title="कैमरा बदलें / Flip Camera"
                >
                  🔄
                </button>
                <button 
                  onClick={handleCapture}
                  style={{
                    backgroundColor: 'var(--accent-primary)',
                    color: 'white',
                    border: 'none',
                    borderRadius: '99px',
                    padding: '0 24px',
                    height: '48px',
                    fontWeight: 700,
                    cursor: 'pointer',
                    boxShadow: '0 4px 12px rgba(124, 58, 237, 0.3)',
                    transition: 'transform 0.2s'
                  }}
                >
                  📸 फोटो लें / Capture
                </button>
              </div>
            </div>
          )}

          {/* 2. Captured Preview Image */}
          {docData && (
            <div style={{ position: 'relative', width: '100%', height: '100%' }}>
              <img 
                src={docData.url || (docData instanceof File ? URL.createObjectURL(docData) : '')} 
                alt="Preview" 
                style={{ width: '100%', height: '100%', objectFit: 'contain' }} 
              />
              <div style={{
                position: 'absolute',
                bottom: '16px',
                left: 0,
                right: 0,
                display: 'flex',
                justifyContent: 'center',
                zIndex: 20
              }}>
                <button 
                  onClick={() => {
                    setDocs(prev => {
                      const copy = { ...prev };
                      delete copy[documentId];
                      return copy;
                    });
                  }}
                  style={{
                    backgroundColor: 'rgba(239, 68, 68, 0.85)',
                    color: 'white',
                    border: 'none',
                    borderRadius: '99px',
                    padding: '8px 20px',
                    fontWeight: 700,
                    cursor: 'pointer',
                    boxShadow: '0 4px 12px rgba(239, 68, 68, 0.3)'
                  }}
                >
                  फिर से लें / Retake
                </button>
              </div>
            </div>
          )}

          {/* 3. Scanning Animation Overlay */}
          {verifying && (
            <div className={styles.scanningOverlay}>
              <div className={styles.scanLine} />
              <div className={styles.miniSpinner} />
              <p style={{ marginTop: '12px', fontWeight: 600, color: 'var(--text-primary)' }}>
                AI दस्तावेज़ की जाँच कर रहा है...
              </p>
            </div>
          )}
        </div>

        {/* 4. Desktop/Fallback Uploader Button */}
        {!docData && !verifying && (
          <div style={{ display: 'flex', justifyContent: 'center', marginTop: '8px' }}>
            <button 
              onClick={() => fileInputRef.current?.click()}
              style={{
                backgroundColor: 'transparent',
                color: 'var(--text-secondary)',
                border: '1px solid var(--border-default)',
                borderRadius: '8px',
                padding: '8px 16px',
                fontSize: '0.875rem',
                fontWeight: 600,
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: '8px'
              }}
            >
              📁 फ़ाइल अपलोड करें / Choose File
            </button>
            <input 
              type="file"
              ref={fileInputRef}
              style={{ display: 'none' }}
              accept="image/*"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) uploadFileDirectly(file);
              }}
            />
          </div>
        )}

        {/* 5. Hidden canvas for capturing */}
        <canvas ref={canvasRef} style={{ display: 'none' }} />

        {errors[documentId] && (
          <div style={{ 
            color: 'var(--accent-error)', 
            fontSize: '0.9rem', 
            marginTop: '8px',
            backgroundColor: 'rgba(239, 68, 68, 0.05)',
            padding: '12px',
            borderRadius: '6px',
            border: '1px solid rgba(239, 68, 68, 0.15)'
          }}>
            ❌ {errors[documentId]}
          </div>
        )}

        {meta.tips && meta.tips.length > 0 && (
          <div style={{ marginTop: '1rem', borderTop: '1px solid var(--border-default)', paddingTop: '1rem' }}>
            <strong>सुझाव / Tips:</strong>
            <ul className={styles.tipsList}>
              {meta.tips.map((tip, i) => (
                <li key={i} className={styles.tipItem}>
                  <span className={styles.checkMarker}>✓</span> {tip}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    );
  };

  return (
    <div className={styles.container}>
      <header className={styles.header}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', fontWeight: 700, fontSize: '1.25rem' }}>
          <svg width="28" height="28" viewBox="0 0 48 48" fill="none">
            <circle cx="24" cy="24" r="24" fill="url(#lg)" />
            <path d="M16 24C16 19.58 19.58 16 24 16V32C19.58 32 16 28.42 16 24Z" fill="white" opacity="0.9"/>
            <defs><linearGradient id="lg" x1="0" y1="0" x2="48" y2="48"><stop stopColor="#7c3aed"/><stop offset="1" stopColor="#a855f7"/></linearGradient></defs>
          </svg>
          <span>Chayan AI - Unified Application</span>
        </div>
      </header>
      {errors.global && (
        <div style={{
          backgroundColor: '#ffebee',
          color: '#c62828',
          padding: '16px',
          margin: '16px',
          borderRadius: '8px',
          display: 'flex',
          alignItems: 'center',
          gap: '12px',
          boxShadow: '0 2px 4px rgba(0,0,0,0.1)',
          borderLeft: '4px solid #c62828'
        }}>
          <span style={{ fontSize: '24px' }}>⚠️</span>
          <div>
            <h3 style={{ margin: '0 0 4px 0', fontSize: '16px' }}>System Error</h3>
            <p style={{ margin: 0, fontSize: '14px' }}>{errors.global}</p>
          </div>
        </div>
      )}

      {errors.warning && (
        <div style={{
          backgroundColor: '#fff9c4',
          color: '#f57f17',
          padding: '16px',
          margin: '16px 16px 0 16px',
          borderRadius: '8px',
          display: 'flex',
          alignItems: 'center',
          gap: '12px',
          boxShadow: '0 2px 4px rgba(0,0,0,0.1)',
          borderLeft: '4px solid #f57f17'
        }}>
          <span style={{ fontSize: '24px' }}>⚠️</span>
          <div style={{ flex: 1 }}>
            <h3 style={{ margin: '0 0 4px 0', fontSize: '16px', color: '#f57f17' }}>चेतावनी / Warning</h3>
            <p style={{ margin: 0, fontSize: '14px', color: '#5d4037' }}>{errors.warning}</p>
          </div>
          <button 
            onClick={() => setErrors(prev => ({ ...prev, warning: null }))}
            style={{
              background: 'none',
              border: 'none',
              color: '#f57f17',
              fontSize: '18px',
              cursor: 'pointer',
              padding: '4px'
            }}
          >
            ✕
          </button>
        </div>
      )}

      {isStarted && totalSteps > 0 && (
        <div className={styles.progressSection}>
          <div className={styles.progressSteps}>
              <div className={styles.stepChipActive} style={{ padding: '8px 16px', borderRadius: '20px', background: 'var(--accent-primary-soft)', border: '1px solid var(--accent-primary)', color: 'var(--text-accent)' }}>
                चरण {currentStep} / {totalSteps}
              </div>
          </div>
        </div>
      )}

      <main className={styles.mainGrid}>
        {!isStarted ? (
            <div style={{ gridColumn: 'span 2', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '65vh', gap: '20px' }}>
               <h2>आपकी आवेदन प्रक्रिया में आपका स्वागत है।</h2>
               <p>यह प्रक्रिया स्वचालित है। आपसे कुछ दस्तावेज़ मांगे जाएंगे और कुछ प्रश्न पूछे जाएंगे।</p>

               {/* Premium Language Selection Card */}
               <div style={{
                 background: 'rgba(255, 255, 255, 0.03)',
                 border: '1px solid rgba(255, 255, 255, 0.08)',
                 borderRadius: '16px',
                 padding: '24px',
                 width: '100%',
                 maxWidth: '480px',
                 textAlign: 'center',
                 boxShadow: '0 8px 32px 0 rgba(0, 0, 0, 0.37)',
                 backdropFilter: 'blur(12px)',
                 display: 'flex',
                 flexDirection: 'column',
                 gap: '16px',
                 marginTop: '10px',
                 marginBottom: '10px'
               }}>
                 <span style={{ fontSize: '0.95rem', fontWeight: 600, color: '#a0aec0' }}>
                   अपनी पसंदीदा भाषा चुनें / Choose your preferred language
                 </span>
                 <div style={{ display: 'flex', gap: '12px', justifyContent: 'center' }}>
                   {[
                     { code: 'hi', label: 'हिंदी (Hindi)' },
                     { code: 'en', label: 'English' },
                     { code: 'te', label: 'తెలుగు (Telugu)' }
                   ].map(lang => (
                     <button
                       key={lang.code}
                       onClick={() => setSelectedLanguage(lang.code)}
                       style={{
                         padding: '12px 20px',
                         borderRadius: '10px',
                         border: selectedLanguage === lang.code ? '2px solid #7c3aed' : '1px solid rgba(255, 255, 255, 0.1)',
                         background: selectedLanguage === lang.code ? 'rgba(124, 58, 237, 0.15)' : 'rgba(255, 255, 255, 0.02)',
                         color: selectedLanguage === lang.code ? '#fff' : '#a0aec0',
                         fontWeight: 600,
                         cursor: 'pointer',
                         transition: 'all 0.2s ease',
                         outline: 'none',
                         boxShadow: selectedLanguage === lang.code ? '0 0 15px rgba(124, 58, 237, 0.3)' : 'none'
                       }}
                     >
                       {lang.label}
                     </button>
                   ))}
                 </div>
               </div>

               <button 
                  onClick={startSession}
                  className={styles.btnNeural}
                  data-state="start"
                  style={{ marginTop: '10px' }}
                >
                  <span>प्रक्रिया शुरू करें / Start Process</span>
                  <div className={styles.btnGlow}></div>
                </button>
            </div>
        ) : (
            <div style={{ gridColumn: 'span 2', maxWidth: '800px', margin: '0 auto', width: '100%' }}>
              {nodeType === 'voice-qa' ? renderVoiceUI() : renderCameraUI()}
            </div>
        )}
      </main>
    </div>
  );
}
