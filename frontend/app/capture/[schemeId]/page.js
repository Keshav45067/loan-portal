'use client';

import { useState, useRef, useEffect, useCallback, use } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import styles from '../capture.module.css';
import interviewStyles from '../../interview/interview.module.css';
import useCaptureGuard from '../useCaptureGuard';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080';
const WS_BASE_URL = process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8080';

const LABEL_MAP = {
  name: "Full Name",
  applicant_name: "Applicant Name",
  full_name: "Full Name",
  dob: "Date of Birth",
  date_of_birth: "Date of Birth",
  year_of_birth: "Year of Birth",
  gender: "Gender",
  father_name: "Father's Name",
  mother_name: "Mother's Name",
  spouse_name: "Spouse's Name",
  phone: "Phone Number",
  mobile_number: "Mobile Number",
  email: "Email Address",
  email_id: "Email Address",
  aadhaar_number: "Aadhaar Number",
  pan_number: "PAN Number",
  pan_confirmed: "PAN Verification Status",
  marital_status: "Marital Status",
  religion: "Religion",
  caste_category: "Caste Category",
  social_category: "Social Category",
  educational_qualification: "Education",
  education: "Education",
  net_worth: "Net Worth",
  occupation: "Occupation Type",
  occupation_type: "Occupation Type",
  business_type: "Business Type",
  nature_of_business: "Nature of Business",
  monthly_revenue: "Monthly Revenue",
  business_revenue: "Monthly Revenue",
  annual_income: "Annual Income",
  udyam_number: "Udyam Number",
  enterprise_name: "Enterprise Name",
  date_of_registration: "Registration Date",
  date_of_commencement: "Commencement Date",
  account_number: "Account Number",
  bank_name: "Bank Name",
  ifsc_code: "IFSC Code",
  pincode: "Pincode",
  pin_code: "Pincode",
  full_address: "Full Address",
  address_line: "Address Line",
  care_of: "Care Of"
};

const formatKey = (key) => {
  if (LABEL_MAP[key]) return LABEL_MAP[key];
  const parts = key.split('.');
  const lastPart = parts[parts.length - 1];
  if (LABEL_MAP[lastPart]) return LABEL_MAP[lastPart];
  
  return key
    .replace(/^doc_/, '')
    .replace(/^aadhaar_/, '')
    .replace(/^pan_/, '')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, c => c.toUpperCase());
};

const flattenData = (obj, prefix = '') => {
  let result = {};
  for (const key in obj) {
    if (obj[key] && typeof obj[key] === 'object' && !Array.isArray(obj[key])) {
      const flat = flattenData(obj[key], prefix ? `${prefix}.${key}` : key);
      result = { ...result, ...flat };
    } else {
      result[prefix ? `${prefix}.${key}` : key] = obj[key];
    }
  }
  return result;
};

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
  
  // Final Extraction Results State
  const [extractedData, setExtractedData] = useState(null);
  const [fetchingData, setFetchingData] = useState(false);

  // Live guard hook for real time guidance and document edge detection
  const {
    cvLoaded,
    cvLoadingError,
    brightness,
    blur,
    coverage,
    confidence,
    isStable,
    documentQuad,
    overallReady,
    statusText,
    statusDetail,
    statusColor,
    readinessScore
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
    };
  }, [schemeId, language, router]);

  useEffect(() => {
    // Preload large WASM/ONNX VAD scripts early
    import('../../utils/voiceHelper').then(({ loadVADScripts }) => {
      loadVADScripts().catch(console.error);
    });
  }, []);

  useEffect(() => {
    if (state.allComplete && sessionId && token) {
      setFetchingData(true);
      fetch(`${API_BASE_URL}/api/applications/${sessionId}`, {
        headers: { 'Authorization': `Bearer ${token}` }
      })
        .then(res => res.json())
        .then(data => {
          if (data && data.extracted_data) {
            setExtractedData(data.extracted_data);
          }
        })
        .catch(err => console.error("Error fetching completed application data:", err))
        .finally(() => setFetchingData(false));
    }
  }, [state.allComplete, sessionId, token]);

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
          setState(prev => ({ ...prev, allComplete: true }));
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
          setState(prev => ({ ...prev, allComplete: true }));
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

  const renderCompletedTable = () => {
    if (fetchingData) {
      return (
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100dvh', background: 'radial-gradient(circle at center, #0f111a 0%, #050508 100%)', color: '#fff' }}>
          <div style={{ width: '40px', height: '40px', border: '3px solid rgba(255,255,255,0.1)', borderTopColor: '#4a78ff', borderRadius: '50%', animation: 'spin 1s linear infinite', marginBottom: '20px' }}></div>
          <p style={{ color: '#94a3b8' }}>Retrieving final extraction results...</p>
        </div>
      );
    }

    const flatData = extractedData ? flattenData(extractedData) : {};
    const items = Object.entries(flatData).map(([key, val]) => {
      let docName = "Application Details";
      if (key.includes("aadhaar") || key.includes("address")) docName = "Aadhaar Card";
      else if (key.includes("pan")) docName = "PAN Card";
      else if (key.includes("passport")) docName = "Passport";
      else if (key.includes("bank") || key.includes("account")) docName = "Bank Statement";
      else if (key.includes("udyam") || key.includes("enterprise")) docName = "Udyam Certificate";

      return {
        key,
        docName,
        label: formatKey(key),
        value: typeof val === 'object' ? JSON.stringify(val) : String(val)
      };
    }).filter(item => item.value && item.value !== 'Not Available' && item.value !== '{}');

    return (
      <div style={{
        minHeight: '100vh',
        background: 'radial-gradient(circle at center, #0b0d16 0%, #030408 100%)',
        color: '#fff',
        padding: '40px 20px',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        fontFamily: 'sans-serif'
      }}>
        <div style={{ width: '100%', maxWidth: '800px', display: 'flex', flexDirection: 'column', gap: '30px' }}>
          {/* Header */}
          <div style={{ textAlign: 'center', marginTop: '20px' }}>
            <div style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: '56px', height: '56px', borderRadius: '50%', background: 'rgba(34, 197, 94, 0.1)', border: '1px solid rgba(34, 197, 94, 0.3)', color: '#22c55e', fontSize: '1.5rem', marginBottom: '16px' }}>✓</div>
            <h1 style={{ fontSize: '1.75rem', fontWeight: 700, letterSpacing: '-0.02em', margin: '0 0 8px' }}>Scanning Completed Successfully</h1>
            <p style={{ color: '#94a3b8', fontSize: '0.95rem', margin: 0 }}>All document pages have been captured, analyzed, and verified by our extraction engine.</p>
          </div>

          {/* Table Card */}
          <div style={{
            background: 'rgba(255,255,255,0.02)',
            border: '1px solid rgba(255,255,255,0.06)',
            borderRadius: '16px',
            padding: '24px',
            boxShadow: '0 20px 40px rgba(0,0,0,0.3)',
            backdropFilter: 'blur(20px)'
          }}>
            <h3 style={{ fontSize: '1.1rem', fontWeight: 600, color: '#a7b4fc', margin: '0 0 20px' }}>Extracted Metadata Summary</h3>
            {items.length === 0 ? (
              <p style={{ color: '#64748b', fontSize: '0.9rem', textAlign: 'center', padding: '20px' }}>No metadata extracted from the uploaded files.</p>
            ) : (
              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.9rem', textAlign: 'left' }}>
                  <thead>
                    <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.08)' }}>
                      <th style={{ padding: '12px 16px', color: '#94a3b8', fontWeight: 500, fontSize: '0.75rem', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Document / Page</th>
                      <th style={{ padding: '12px 16px', color: '#94a3b8', fontWeight: 500, fontSize: '0.75rem', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Field Label</th>
                      <th style={{ padding: '12px 16px', color: '#94a3b8', fontWeight: 500, fontSize: '0.75rem', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Extracted Value</th>
                    </tr>
                  </thead>
                  <tbody>
                    {items.map((item, idx) => (
                      <tr key={idx} style={{ borderBottom: '1px solid rgba(255,255,255,0.03)', transition: 'background 0.2s' }}>
                        <td style={{ padding: '14px 16px', color: '#a7b4fc', fontWeight: 600 }}>{item.docName}</td>
                        <td style={{ padding: '14px 16px', color: '#cbd5e1' }}>{item.label}</td>
                        <td style={{ padding: '14px 16px', color: '#fff', fontWeight: 500, fontFamily: 'monospace' }}>{item.value}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* Action Button */}
          <div style={{ display: 'flex', justifyContent: 'center' }}>
            <button
              onClick={() => router.push('/dashboard')}
              style={{
                background: '#fff',
                color: '#000',
                border: 'none',
                borderRadius: '8px',
                padding: '12px 32px',
                fontSize: '0.95rem',
                fontWeight: 600,
                cursor: 'pointer',
                transition: 'transform 0.1s'
              }}
              onMouseOver={(e) => e.currentTarget.style.transform = 'scale(1.02)'}
              onMouseOut={(e) => e.currentTarget.style.transform = 'scale(1)'}
            >
              Go to Dashboard
            </button>
          </div>
        </div>
      </div>
    );
  };

  if (loading) return <div className={styles.container} style={{ justifyContent: 'center', height: '100vh' }}>Loading capture engine...</div>;
  if (state.allComplete) return renderCompletedTable();

  return (
    <div className={styles.container}>
      {/* ─── Background Camera Layer ─── */}
      <div className={styles.fullScreenCamera}>
        {!previewUrl ? (
          <>
            <video ref={videoRef} autoPlay playsInline muted className={styles.videoElement} />
            <div className={`${styles.guideBox} ${state.pageInfo?.orientation === 'portrait' ? styles.guidePortrait : styles.guideLandscape}`} />
            <div className={styles.statusBadge} style={{ color: statusColor !== '#94a3b8' ? statusColor : '#000' }}>
              <span>{statusText}</span>
              {statusDetail && <span className={styles.statusDetail}>{statusDetail}</span>}
            </div>
            <div className={styles.readinessBar}>
              <div className={styles.readinessFill} style={{ width: `${(readinessScore || 0) * 100}%` }} />
            </div>
            {cvLoaded && documentQuad && (
              <svg className={styles.overlaySvg} viewBox="0 0 1000 1000" preserveAspectRatio="none">
                <polygon
                  points={documentQuad.map(p => `${Math.round(p.x * 1000)},${Math.round(p.y * 1000)}`).join(' ')}
                  className={`${styles.detectedPoly} ${overallReady ? styles.detectedPolyReady : ''}`}
                />
                {documentQuad.map((p, i) => (
                  <g key={i}>
                    <circle
                      cx={Math.round(p.x * 1000)}
                      cy={Math.round(p.y * 1000)}
                      r="14"
                      className={overallReady ? styles.cornerDotPulseReady : styles.cornerDotPulse}
                    />
                    <circle
                      cx={Math.round(p.x * 1000)}
                      cy={Math.round(p.y * 1000)}
                      r="8"
                      className={`${styles.cornerDot} ${overallReady ? styles.cornerDotReady : ''}`}
                    />
                  </g>
                ))}
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
        <div className={styles.mainLayout} style={{ flexDirection: 'column', alignItems: 'center', justifyContent: 'flex-end', gap: '20px' }}>
          
          {/* Sleek Minimal One-Line Voice Agent Capsule */}
          <div style={{
            display: 'flex',
            alignItems: 'center',
            gap: '12px',
            background: 'rgba(9, 10, 15, 0.75)',
            backdropFilter: 'blur(20px)',
            border: '1px solid rgba(255, 255, 255, 0.08)',
            borderRadius: '999px',
            padding: '8px 18px',
            maxWidth: '90%',
            width: 'max-content',
            margin: '0 auto',
            boxShadow: '0 8px 32px rgba(0,0,0,0.25)',
            fontSize: '0.875rem',
            color: '#fff',
            pointerEvents: 'auto'
          }} className={styles.interactive}>
            {/* Connection Dot */}
            <div style={{
              width: '8px',
              height: '8px',
              borderRadius: '50%',
              background: qaState === 'listening' ? '#3b82f6' : qaState === 'speaking' ? '#10b981' : qaState === 'processing' ? '#a78bfa' : '#64748b',
              boxShadow: qaState === 'listening' ? '0 0 8px #3b82f6' : qaState === 'speaking' ? '0 0 8px #10b981' : qaState === 'processing' ? '0 0 8px #a78bfa' : 'none'
            }}></div>
            
            {/* Status & Live Transcript */}
            <span style={{ fontWeight: 600, color: '#94a3b8', whiteSpace: 'nowrap' }}>
              {qaState === 'listening' ? 'Listening' : qaState === 'processing' ? 'Processing' : qaState === 'speaking' ? 'Speaking' : 'Standby'}:
            </span>
            <span style={{ color: '#fff', fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '300px' }}>
              {transcript || (qaState === 'listening' ? 'Speak now...' : qaState === 'processing' ? 'Thinking...' : 'Voice assistant ready')}
            </span>
          </div>

          <div className={styles.leftControls} style={{ width: '100%', maxWidth: '600px' }}>
            {/* Header / Progress over camera */}
            <div style={{ width: '100%', marginBottom: '16px' }}>
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

        </div>
      </div>
      
      {/* Hidden canvas for image capture */}
      <canvas ref={canvasRef} style={{ display: 'none' }} />
    </div>
  );
}
