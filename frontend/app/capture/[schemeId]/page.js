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

const SUB_FIELD_LABELS = {
  care_of: "C/O",
  street: "Street",
  city_village: "City/Village",
  district: "District",
  state: "State",
  pincode: "Pincode",
  visa_country: "Country",
  visa_type: "Type",
  visa_issue_date: "Issue Date"
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

  const [torchOn, setTorchOn] = useState(false);
  const [torchSupported, setTorchSupported] = useState(false);

  const [demoCheckboxes, setDemoCheckboxes] = useState({
    needRegistration: false,
    existingSupplier: false,
    registeredIndia: false,
    gstRegistered: false,
  });
  const [demoTextInputs, setDemoTextInputs] = useState({
    businessJustification: '',
    tplEmail: '',
    contactEmail: '',
    mobilePhone: '',
    contactPhone: '',
    categories: '',
    locations: '',
    vendorType: '',
    eligibleCE: ''
  });

  const toggleTorch = useCallback(async () => {
    if (!streamRef.current || !torchSupported) return;
    try {
      const track = streamRef.current.getVideoTracks()[0];
      if (track) {
        const nextState = !torchOn;
        await track.applyConstraints({
          advanced: [{ torch: nextState }]
        });
        setTorchOn(nextState);
      }
    } catch (e) {
      console.error("Error toggling torch:", e);
    }
  }, [torchOn, torchSupported]);

  // Voice Agent State
  const [qaState, setQaState] = useState('idle');
  const [transcript, setTranscript] = useState('');
  const [textInputValue, setTextInputValue] = useState('');
  const voiceSessionRef = useRef(null);
  
  // Final Extraction Results State
  const [extractedData, setExtractedData] = useState(null);
  const [fetchingData, setFetchingData] = useState(false);
  const [fieldsRegistry, setFieldsRegistry] = useState(null);
  const [manifests, setManifests] = useState({});

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
    false, // OpenCV live analysis disabled/bypassed
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

  const getCleanDocTitle = (docId, manifestsDict) => {
    if (manifestsDict && manifestsDict[docId]?.title?.English) {
      return manifestsDict[docId].title.English;
    }
    if (!docId) return "Document";
    const lower = docId.toLowerCase();
    if (lower.includes("aadhaar")) return "Aadhaar Card";
    if (lower.includes("pan")) return "PAN Card";
    if (lower.includes("gst")) return "GST Registration Certificate";
    if (lower.includes("udyam")) return "Udyam Registration Certificate";
    if (lower.includes("bank")) return "Bank Statement";
    return docId.replace(/^doc_/, '').replace(/_\d+$/, '').replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
  };

  const fetchCaptureState = useCallback(async () => {
    const savedToken = localStorage.getItem('token') || token;
    if (!savedToken) return;
    try {
      // 1. Fetch current capture session state
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

      setState(prev => {
        if (prev.allComplete) return prev;
        return {
          docId: data.current_document_id,
          pageId: data.current_page_id,
          docIndex: data.current_document_index,
          totalDocs: data.total_documents,
          pageIndex: data.current_page_index,
          totalPages: data.total_pages,
          pageInfo: data.current_page_info,
          allComplete: data.all_complete
        };
      });
      setLocalUploadsCount(data.current_page_info?.uploads_count || 0);

      // 2. Load scheme manifests if not loaded yet
      const schemeRes = await fetch(`${API_BASE_URL}/api/capture/scheme-docs/${schemeId}`, {
        headers: { 'Authorization': `Bearer ${savedToken}` }
      });
      const schemeData = await schemeRes.json();
      if (schemeData.manifests) {
        setManifests(schemeData.manifests);
      }
      if (schemeData.fields_registry) {
        setFieldsRegistry(schemeData.fields_registry);
      }

      // 3. Load application extracted data if session_id is available
      const savedSessionId = localStorage.getItem('session_id') || sessionId;
      if (savedSessionId) {
        const appRes = await fetch(`${API_BASE_URL}/api/applications/${savedSessionId}`, {
          headers: { 'Authorization': `Bearer ${savedToken}` }
        });
        const appDataJson = await appRes.json();
        if (appDataJson && appDataJson.extracted_data) {
          setExtractedData(appDataJson.extracted_data);
        }
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [schemeId, language, token, sessionId]);

  useEffect(() => {
    const savedToken = localStorage.getItem('token');
    const savedSessionId = localStorage.getItem('session_id');
    if (!savedToken || !savedSessionId) {
      router.push('/');
      return;
    }
    setToken(savedToken);
    setSessionId(savedSessionId);

    fetchCaptureState();

    return () => {
      stopCamera();
      if (voiceSessionRef.current) voiceSessionRef.current.disconnect();
    };
  }, [schemeId, language, router, fetchCaptureState]);

  useEffect(() => {
    // Preload large WASM/ONNX VAD scripts early
    import('../../utils/voiceHelper').then(({ loadVADScripts }) => {
      loadVADScripts().catch(console.error);
    });
  }, []);

  useEffect(() => {
    if (state.allComplete && sessionId && token) {
      setFetchingData(true);
      
      const loadAllData = async () => {
        try {
          // 1. Fetch extracted data from application
          const appRes = await fetch(`${API_BASE_URL}/api/applications/${sessionId}`, {
            headers: { 'Authorization': `Bearer ${token}` }
          });
          const appDataJson = await appRes.json();
          if (appDataJson && appDataJson.extracted_data) {
            setExtractedData(appDataJson.extracted_data);
          }
          
          // 2. Fetch scheme config (manifests + fields registry) using schemeId from URL
          const schemeRes = await fetch(`${API_BASE_URL}/api/capture/scheme-docs/${schemeId}`, {
            headers: { 'Authorization': `Bearer ${token}` }
          });
          const schemeData = await schemeRes.json();
          if (schemeData.manifests) {
            setManifests(schemeData.manifests);
          }
          if (schemeData.fields_registry) {
            setFieldsRegistry(schemeData.fields_registry);
          }
        } catch (err) {
          console.error("Error loading final verification data:", err);
        } finally {
          setFetchingData(false);
        }
      };
      
      loadAllData();
    }
  }, [state.allComplete, sessionId, token, schemeId]);

  const startSession = () => {
    // Initialize and resume AudioContext synchronously in click handler
    window.globalAudioContext = window.globalAudioContext || new (window.AudioContext || window.webkitAudioContext)();
    if (window.globalAudioContext.state === 'suspended') {
      try { window.globalAudioContext.resume(); } catch (e) { console.error('Failed to resume AudioContext:', e); }
    }
    setIsStarted(true);
  };

  const onControlSignalRef = useRef(null);

  onControlSignalRef.current = async (sigType, payload) => {
    console.log('[capture page] Received control_signal:', sigType, payload);
    if (sigType === 'UPDATE_FIELD' && payload?.field_key) {
      setExtractedData(prev => ({
        ...(prev || {}),
        [payload.field_key]: {
          value: parseObjIfNeeded(payload.new_value),
          manually_overridden: true,
          override_reason: payload.override_reason || 'Agent override'
        }
      }));
    } else if (sigType === 'SWITCH_PAGE' || sigType === 'RESET_PAGE') {
      setPreviewUrl(null);
      setProcessingDoc(false);
      setError(null);

      // 1. If payload contains enriched page_info directly, update state instantly without HTTP fetch
      if (payload?.page_info) {
        setState(prev => ({
          ...prev,
          docId: payload.doc_id || prev.docId,
          pageId: payload.part_id || payload.page_info.page_id || prev.pageId,
          docIndex: payload.page_info.document_index ?? prev.docIndex,
          totalDocs: payload.page_info.total_documents ?? prev.totalDocs,
          pageInfo: payload.page_info
        }));
        if (payload.page_info.uploads_count !== undefined) {
          setLocalUploadsCount(payload.page_info.uploads_count);
        }
        return;
      }

      // 2. Fallback: if signal didn't contain page_info, fetch from API
      if (payload?.doc_id) {
        setState(prev => ({
          ...prev,
          docId: payload.doc_id,
          pageId: payload.part_id || prev.pageId,
        }));
      }
      const savedToken = localStorage.getItem('token') || token;
      if (!savedToken) return;

      try {
        const targetDocId = payload?.doc_id || '';
        const targetPartId = payload?.part_id || '';
        const infoRes = await fetch(`${API_BASE_URL}/api/capture/page-info?session_id=${sessionId}&document_id=${targetDocId}&page_id=${targetPartId}`, {
          headers: { 'Authorization': `Bearer ${savedToken}` }
        });
        const infoData = await infoRes.json();
        if (infoData.success) {
          setState(prev => ({
            ...prev,
            docId: payload?.doc_id || infoData.document_id,
            pageId: payload?.part_id || infoData.page_info?.page_id || prev.pageId,
            docIndex: infoData.document_index,
            totalDocs: infoData.total_documents,
            pageInfo: infoData.page_info
          }));
          if (infoData.page_info?.uploads_count !== undefined) {
            setLocalUploadsCount(infoData.page_info.uploads_count);
          }
        }
      } catch (err) {
        console.error('Failed to fetch page-info on control signal:', err);
      }
    } else if (sigType === 'SUBMIT_APPLICATION') {
      stopCamera();
      router.push('/dashboard');
    }
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
                console.error("VAD scripts failed to load!");
                setError("Voice engine audio analyzer failed to load.");
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
                },
                onControlSignal: (sigType, payload) => {
                    if (onControlSignalRef.current) {
                        onControlSignalRef.current(sigType, payload);
                    }
                }
            });
            voiceSessionRef.current = manager;
            
            await manager.connect();


        };
        startVoice();
    }
  }, [loading, state.allComplete, token, sessionId, language, isStarted, fetchCaptureState]);

  // Camera Management
  const stopCamera = useCallback(() => {
    if (streamRef.current) {
      streamRef.current.getTracks().forEach(t => t.stop());
      streamRef.current = null;
    }
    setTorchSupported(false);
    setTorchOn(false);
  }, []);

  const startCamera = useCallback(async (facingMode) => {
    stopCamera();
    if (previewUrl) return; // Don't start if previewing
    
    if (typeof navigator === 'undefined' || !navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      setError('Camera API is not supported in this browser. Please use manual upload.');
      return;
    }

    const detectTorch = (stream) => {
      const track = stream.getVideoTracks()[0];
      if (track) {
        setTimeout(() => {
          try {
            const capabilities = typeof track.getCapabilities === 'function' ? track.getCapabilities() : {};
            if (capabilities.torch) {
              setTorchSupported(true);
              if (torchOn) {
                track.applyConstraints({ advanced: [{ torch: true }] }).catch(console.error);
              }
            } else {
              setTorchSupported(false);
            }
          } catch (e) {
            console.warn("Failed to get camera capabilities:", e);
            setTorchSupported(false);
          }
        }, 500);
      }
    };

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
      detectTorch(stream);
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
        detectTorch(fallbackStream);
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
    if (!videoRef.current || !canvasRef.current) return;

    const video = videoRef.current;
    const canvas = canvasRef.current;
    const vw = video.videoWidth || 640;
    const vh = video.videoHeight || 480;
    const ctx = canvas.getContext('2d');
    const cv = window.cv;
    const MAX_DIM = 2500;

    // ── Case A: OpenCV loaded + document quad detected → perspective warp crop (Disabled, fallback to downscaling only)
    if (false && cv && cv.Mat && documentQuad && documentQuad.length === 4) {
      const matsToDelete = [];
      let warpSuccess = false;

      try {
        // Draw full-res frame to canvas
        canvas.width = vw;
        canvas.height = vh;
        ctx.drawImage(video, 0, 0, vw, vh);
        const imgData = ctx.getImageData(0, 0, vw, vh);

        const src = cv.matFromImageData(imgData);
        matsToDelete.push(src);

        // Convert normalized quad (TL, TR, BR, BL) to pixel coordinates
        const srcPts = documentQuad.map(p => [p.x * vw, p.y * vh]);

        // Compute output dimensions from quad edge lengths
        const widthTop = Math.hypot(srcPts[1][0] - srcPts[0][0], srcPts[1][1] - srcPts[0][1]);
        const widthBot = Math.hypot(srcPts[2][0] - srcPts[3][0], srcPts[2][1] - srcPts[3][1]);
        const heightL  = Math.hypot(srcPts[3][0] - srcPts[0][0], srcPts[3][1] - srcPts[0][1]);
        const heightR  = Math.hypot(srcPts[2][0] - srcPts[1][0], srcPts[2][1] - srcPts[1][1]);

        let dstW = Math.round(Math.max(widthTop, widthBot));
        let dstH = Math.round(Math.max(heightL, heightR));

        // Cap at MAX_DIM on longest edge
        const longest = Math.max(dstW, dstH);
        if (longest > MAX_DIM) {
          const scale = MAX_DIM / longest;
          dstW = Math.round(dstW * scale);
          dstH = Math.round(dstH * scale);
        }

        // Ensure minimum dimensions
        dstW = Math.max(dstW, 100);
        dstH = Math.max(dstH, 100);

        // Build point matrices for getPerspectiveTransform
        const srcMat = cv.matFromArray(4, 1, cv.CV_32FC2, srcPts.flat());
        matsToDelete.push(srcMat);

        const dstMat = cv.matFromArray(4, 1, cv.CV_32FC2, [
          0, 0,       dstW, 0,
          dstW, dstH, 0, dstH
        ]);
        matsToDelete.push(dstMat);

        const M = cv.getPerspectiveTransform(srcMat, dstMat);
        matsToDelete.push(M);

        const warped = new cv.Mat();
        matsToDelete.push(warped);
        cv.warpPerspective(src, warped, M, new cv.Size(dstW, dstH));

        // Copy warped pixels to canvas (must happen before Mat cleanup)
        canvas.width = dstW;
        canvas.height = dstH;
        const outData = new ImageData(new Uint8ClampedArray(warped.data), dstW, dstH);
        ctx.putImageData(outData, 0, 0);

        warpSuccess = true;
        console.log(`[Capture] Perspective warp: ${vw}×${vh} → ${dstW}×${dstH}`);
      } catch (err) {
        console.error('[Capture] Perspective warp failed, falling back to full frame:', err);
      } finally {
        for (const m of matsToDelete) {
          try { m.delete(); } catch (_) {}
        }
      }

      // Fallback: if warp failed, redraw full frame (capped)
      if (!warpSuccess) {
        canvas.width = vw;
        canvas.height = vh;
        ctx.drawImage(video, 0, 0, vw, vh);
        if (Math.max(vw, vh) > MAX_DIM) {
          const scale = MAX_DIM / Math.max(vw, vh);
          const nw = Math.round(vw * scale);
          const nh = Math.round(vh * scale);
          const tmp = document.createElement('canvas');
          tmp.width = vw; tmp.height = vh;
          tmp.getContext('2d').drawImage(video, 0, 0, vw, vh);
          canvas.width = nw; canvas.height = nh;
          ctx.drawImage(tmp, 0, 0, nw, nh);
        }
      }
    } else {
      // ── Case B: No quad or no OpenCV → send full frame, capped at MAX_DIM
      canvas.width = vw;
      canvas.height = vh;
      ctx.drawImage(video, 0, 0, vw, vh);

      if (Math.max(vw, vh) > MAX_DIM) {
        const scale = MAX_DIM / Math.max(vw, vh);
        const nw = Math.round(vw * scale);
        const nh = Math.round(vh * scale);
        const tmp = document.createElement('canvas');
        tmp.width = vw; tmp.height = vh;
        tmp.getContext('2d').drawImage(video, 0, 0, vw, vh);
        canvas.width = nw; canvas.height = nh;
        ctx.drawImage(tmp, 0, 0, nw, nh);
      }
    }

    // Compress to JPEG 85% and upload
    canvas.toBlob(async (blob) => {
      if (blob) {
        const file = new File([blob], `${state.pageId}.jpg`, { type: 'image/jpeg' });
        setPreviewUrl(URL.createObjectURL(file));
        await uploadDocument(file);
      }
    }, 'image/jpeg', 0.85);
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
          if (data.validation_error_key === 'error_low_light' && torchSupported) {
              setTorchOn(true);
          }
          // Validation failed
          if (voiceSessionRef.current) {
              voiceSessionRef.current.stopAudioPlayback();
              const errKey = data.validation_error_key || data.error || 'unknown_error';
              voiceSessionRef.current.sendControlSignal(`capture_error:${errKey}`);
          }
          
          setError(data.validation_error_text || data.error || 'Validation failed. Please try again.');
          setPreviewUrl(null);
          
          if (data.next_page_id) {
              setState(prev => ({
                  ...prev,
                  docId: data.next_document_id || prev.docId,
                  pageId: data.next_page_id,
              }));
              setPreviewUrl(null);
              
              const targetDocId = data.next_document_id || prev.docId;
              const targetPageId = data.next_page_id || prev.pageId;
              // Need to re-fetch page info to update prompts and overlay
              const infoRes = await fetch(`${API_BASE_URL}/api/capture/page-info?session_id=${sessionId}&document_id=${targetDocId}&page_id=${targetPageId}`, {
                  headers: { 'Authorization': `Bearer ${token}` }
              });
              const infoData = await infoRes.json();
              if (infoData.success) {
                  setState(prev => ({
                      ...prev,
                      docId: infoData.document_id || targetDocId,
                      pageId: infoData.page_info?.page_id || targetPageId,
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
          setPreviewUrl(null);
          setProcessingDoc(false);
          setState(prev => ({ ...prev, allComplete: true }));
          return;
      }

      const nextDoc = data.next_document_id || data.processed_document_id;
      const nextPage = data.next_page_id;

       // Update state for next step
      setState(prev => ({
          ...prev,
          docId: nextDoc || prev.docId,
          pageId: nextPage || prev.pageId,
      }));
      setPreviewUrl(null);
      setLocalUploadsCount(prev => prev + 1);
      
      // Need to re-fetch page info to update prompts and overlay
      const infoRes = await fetch(`${API_BASE_URL}/api/capture/page-info?session_id=${sessionId}&document_id=${nextDoc || ''}&page_id=${nextPage || ''}`, {
          headers: { 'Authorization': `Bearer ${token}` }
      });
      const infoData = await infoRes.json();
      if (infoData.success) {
          setState(prev => ({
              ...prev,
              docId: infoData.document_id || nextDoc || prev.docId,
              pageId: infoData.page_info?.page_id || nextPage || prev.pageId,
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
              
              const targetDocId = data.next_document_id || prev.docId;
              const targetPageId = data.next_page_id || prev.pageId;
              // Need to re-fetch page info to update prompts and overlay
              const infoRes = await fetch(`${API_BASE_URL}/api/capture/page-info?session_id=${sessionId}&document_id=${targetDocId}&page_id=${targetPageId}`, {
                  headers: { 'Authorization': `Bearer ${token}` }
              });
              const infoData = await infoRes.json();
              if (infoData.success) {
                  setState(prev => ({
                      ...prev,
                      docId: infoData.document_id || targetDocId,
                      pageId: infoData.page_info?.page_id || targetPageId,
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

      const nextDoc = data.current_document_id || data.next_document_id;
      const nextPage = data.current_page_id || data.next_page_id;

      // Update state for next step
      setState(prev => ({
          ...prev,
          docId: nextDoc || prev.docId,
          pageId: nextPage || prev.pageId,
      }));
      setPreviewUrl(null);
      
      // Need to re-fetch page info to update prompts and overlay
      const infoRes = await fetch(`${API_BASE_URL}/api/capture/page-info?session_id=${sessionId}&document_id=${nextDoc || ''}&page_id=${nextPage || ''}`, {
          headers: { 'Authorization': `Bearer ${token}` }
      });
      const infoData = await infoRes.json();
      if (infoData.success) {
          setState(prev => ({
              ...prev,
              docId: infoData.document_id || nextDoc || prev.docId,
              pageId: infoData.page_info?.page_id || nextPage || prev.pageId,
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

  const parseObjIfNeeded = (val) => {
    if (!val) return val;
    if (typeof val === 'object') return val;
    if (typeof val === 'string') {
      const trimmed = val.trim();
      if (trimmed.startsWith('{')) {
        try {
          return JSON.parse(trimmed);
        } catch (e) {
          try {
            const jsonStr = trimmed
              .replace(/'/g, '"')
              .replace(/None/g, 'null')
              .replace(/True/g, 'true')
              .replace(/False/g, 'false');
            return JSON.parse(jsonStr);
          } catch (err) {}
        }
      }
    }
    return val;
  };

  const getPageNameForSlot = (slotId, manifest) => {
    if (!manifest || !manifest.parts) return "Document Details";
    const part = manifest.parts.find(p => p.provides && p.provides.includes(slotId));
    if (part && part.name && part.name.English) {
      return part.name.English;
    }
    return manifest.title?.English || "Document Details";
  };

  const getValueWithFallback = (slotId, dataObj) => {
    if (!dataObj) return null;
    if (dataObj[slotId] !== undefined) return dataObj[slotId];
    
    const suffix = slotId.replace(/^doc_[a-z0-9]+_/, '');
    if (dataObj[suffix] !== undefined) return dataObj[suffix];

    if (slotId === 'doc_aadhaar_name' && dataObj.applicant_name !== undefined) {
      return dataObj.applicant_name;
    }
    if (slotId === 'doc_aadhaar_name' && dataObj.name !== undefined) {
      return dataObj.name;
    }
    return null;
  };

  const handleFieldUpdate = (slotId, newValue, subKey = null) => {
    setExtractedData(prev => {
      const currentSlotObj = prev?.[slotId];
      const currentValRaw = (currentSlotObj && typeof currentSlotObj === 'object' && currentSlotObj.value !== undefined)
        ? currentSlotObj.value
        : getValueWithFallback(slotId, prev);
      const currentVal = parseObjIfNeeded(currentValRaw);

      let finalVal;
      if (subKey) {
        const baseObj = (typeof currentVal === 'object' && currentVal !== null) ? currentVal : {};
        finalVal = { ...baseObj, [subKey]: newValue };
      } else {
        finalVal = newValue;
      }

      const updatedObj = {
        value: finalVal,
        manually_overridden: true,
        override_reason: 'User manual edit'
      };

      const newExtractedData = {
        ...(prev || {}),
        [slotId]: updatedObj
      };

      const savedToken = localStorage.getItem('token') || token;
      const savedSessionId = localStorage.getItem('session_id') || sessionId;
      if (savedSessionId && savedToken) {
        fetch(`${API_BASE_URL}/api/applications/save-metadata`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${savedToken}`
          },
          body: JSON.stringify({
            session_id: savedSessionId,
            fields: {
              [slotId]: updatedObj
            }
          })
        }).catch(err => console.error("Error saving manual edit:", err));
      }

      return newExtractedData;
    });
  };

  const formatExtractedValue = (rawValue, fieldDef, slotId, isOverridden) => {
    const value = parseObjIfNeeded(rawValue);
    const type = fieldDef?.type || (typeof value === 'object' && value !== null ? 'object' : 'text');

    if (type === 'object' && typeof value === 'object' && value !== null) {
      const fields = fieldDef?.fields || Object.keys(value);
      return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', fontSize: '0.85rem' }}>
          {fields.map((fKey) => {
            const fVal = value[fKey];
            const subLabel = SUB_FIELD_LABELS[fKey] || formatKey(fKey);
            return (
              <div key={fKey} style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                <span style={{ color: '#94a3b8', fontWeight: 500, width: '130px', flexShrink: 0, fontSize: '0.78rem' }}>{subLabel}:</span>
                <input
                  type="text"
                  value={fVal !== null && fVal !== undefined ? String(fVal) : ''}
                  placeholder="Type to edit..."
                  onChange={(e) => handleFieldUpdate(slotId, e.target.value, fKey)}
                  style={{
                    flex: 1,
                    padding: '6px 10px',
                    background: isOverridden ? 'rgba(251, 191, 36, 0.08)' : '#0f172a',
                    border: `1px solid ${isOverridden ? 'rgba(251, 191, 36, 0.4)' : '#334155'}`,
                    borderRadius: '6px',
                    color: isOverridden ? '#fbbf24' : '#fff',
                    fontSize: '0.84rem',
                    outline: 'none'
                  }}
                />
              </div>
            );
          })}
        </div>
      );
    }

    return (
      <input
        type="text"
        value={value !== null && value !== undefined ? String(value) : ''}
        placeholder="Type to edit..."
        onChange={(e) => handleFieldUpdate(slotId, e.target.value)}
        style={{
          width: '100%',
          padding: '8px 12px',
          background: isOverridden ? 'rgba(251, 191, 36, 0.08)' : '#0f172a',
          border: `1px solid ${isOverridden ? 'rgba(251, 191, 36, 0.4)' : '#334155'}`,
          borderRadius: '8px',
          color: isOverridden ? '#fbbf24' : '#fff',
          fontSize: '0.88rem',
          outline: 'none'
        }}
      />
    );
  };



  const renderCompletedTable = () => {
    if (fetchingData) {
      return (
        <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, zIndex: 100, background: 'rgba(3, 4, 8, 0.9)', backdropFilter: 'blur(20px)', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', color: '#fff' }}>
          <div style={{ width: '44px', height: '44px', border: '3px solid rgba(255,255,255,0.1)', borderTopColor: '#3b82f6', borderRadius: '50%', animation: 'spin 1s linear infinite', marginBottom: '20px' }}></div>
          <p style={{ color: '#94a3b8', fontSize: '1rem' }}>Retrieving final extraction results...</p>
        </div>
      );
    }

    const activeDocTypes = Object.keys(manifests);

    return (
      <div style={{
        position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, zIndex: 100,
        background: 'rgba(3, 4, 8, 0.88)', backdropFilter: 'blur(20px)',
        color: '#fff', padding: '30px 20px', display: 'flex', flexDirection: 'column',
        alignItems: 'center', overflowY: 'auto'
      }}>
        <div style={{ width: '100%', maxWidth: '820px', display: 'flex', flexDirection: 'column', gap: '24px' }}>
          {/* Header */}
          <div style={{ textAlign: 'center', marginTop: '10px' }}>
            <div style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: '56px', height: '56px', borderRadius: '50%', background: 'rgba(34, 197, 94, 0.15)', border: '1px solid rgba(34, 197, 94, 0.4)', color: '#4ade80', fontSize: '1.6rem', marginBottom: '14px' }}>✓</div>
            <h1 style={{ fontSize: '1.65rem', fontWeight: 700, letterSpacing: '-0.02em', margin: '0 0 6px' }}>All Documents Captured Successfully</h1>
            <p style={{ color: '#94a3b8', fontSize: '0.92rem', margin: 0 }}>Review or edit extracted details below. The AI voice assistant remains active to answer questions or make updates.</p>
          </div>

          {/* Grouped Document Results */}
          {activeDocTypes.map((docType) => {
            const manifest = manifests[docType];
            if (!manifest) return null;

            const expects = manifest.expects || [];
            const docFields = [];

            expects.forEach((slotId) => {
              const fieldDef = fieldsRegistry ? fieldsRegistry[slotId] : null;
              const label = fieldDef?.label?.English || formatKey(slotId);
              const valObj = extractedData ? extractedData[slotId] : null;
              const rawVal = valObj && typeof valObj === 'object' && valObj.value !== undefined ? valObj.value : getValueWithFallback(slotId, extractedData);
              const isOverridden = valObj?.manually_overridden || false;
              const pageName = getPageNameForSlot(slotId, manifest);

              docFields.push({
                slotId,
                pageName,
                label,
                value: rawVal,
                isOverridden,
                fieldDef
              });
            });

            if (docFields.length === 0) return null;

            return (
              <div key={docType} style={{
                background: 'rgba(30, 41, 59, 0.7)',
                border: '1px solid rgba(255,255,255,0.08)',
                borderRadius: '16px',
                padding: '24px',
                boxShadow: '0 20px 40px rgba(0,0,0,0.4)',
                backdropFilter: 'blur(20px)'
              }}>
                <h3 style={{ fontSize: '1.1rem', fontWeight: 700, color: '#60a5fa', margin: '0 0 16px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <span>📄</span>
                  <span>{manifest.title?.English || formatKey(docType)}</span>
                </h3>
                
                <div style={{ overflowX: 'auto' }}>
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.88rem', textAlign: 'left' }}>
                    <thead>
                      <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.08)' }}>
                        <th style={{ padding: '10px 14px', color: '#94a3b8', fontWeight: 600, fontSize: '0.75rem', textTransform: 'uppercase', width: '35%' }}>Field Name</th>
                        <th style={{ padding: '10px 14px', color: '#94a3b8', fontWeight: 600, fontSize: '0.75rem', textTransform: 'uppercase', width: '65%' }}>Extracted Value</th>
                      </tr>
                    </thead>
                    <tbody>
                      {docFields.map((field, fIdx) => (
                        <tr key={fIdx} style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
                          <td style={{ padding: '12px 14px', color: '#cbd5e1' }}>
                            <div style={{ fontWeight: 600, color: '#fff', display: 'flex', alignItems: 'center', gap: '6px' }}>
                              <span>{field.label}</span>
                              {field.isOverridden && (
                                <span style={{ background: 'rgba(251, 191, 36, 0.18)', color: '#fbbf24', border: '1px solid rgba(251, 191, 36, 0.3)', fontSize: '0.62rem', fontWeight: 700, padding: '2px 6px', borderRadius: '4px', textTransform: 'uppercase' }}>
                                  EDITED
                                </span>
                              )}
                            </div>
                            <div style={{ fontSize: '0.72rem', color: '#64748b', marginTop: '2px' }}>{field.pageName}</div>
                          </td>
                          <td style={{ padding: '12px 14px' }}>
                            {formatExtractedValue(field.value, field.fieldDef, field.slotId, field.isOverridden)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            );
          })}

          {/* Chat with AI Agent Text Box */}
          <div style={{
            display: 'flex',
            alignItems: 'center',
            gap: '10px',
            background: 'rgba(15, 23, 42, 0.85)',
            backdropFilter: 'blur(20px)',
            border: '1px solid rgba(255, 255, 255, 0.12)',
            borderRadius: '16px',
            padding: '12px 16px',
            width: '100%',
            marginTop: '10px'
          }}>
            <input
              type="text"
              placeholder="Chat with AI Agent to make updates (e.g. 'Change my PAN name to Keshav Garg')..."
              value={textInputValue}
              onChange={(e) => setTextInputValue(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') handleSendText();
              }}
              style={{
                flex: 1,
                padding: '12px 16px',
                background: '#1e293b',
                border: '1px solid #334155',
                borderRadius: '10px',
                color: '#fff',
                fontSize: '0.9rem',
                outline: 'none'
              }}
            />
            <button
              onClick={handleSendText}
              disabled={!textInputValue.trim()}
              style={{
                padding: '12px 24px',
                background: textInputValue.trim() ? '#3b82f6' : '#334155',
                color: '#fff',
                border: 'none',
                borderRadius: '10px',
                fontWeight: 600,
                fontSize: '0.9rem',
                cursor: textInputValue.trim() ? 'pointer' : 'not-allowed',
                transition: 'background 0.15s'
              }}
            >
              Send Message
            </button>
          </div>

          {/* Action Buttons */}
          <div style={{ display: 'flex', justifyContent: 'center', gap: '16px', paddingBottom: '30px' }}>
            <button
              onClick={async () => {
                localStorage.removeItem('session_id');
                setState(prev => ({ ...prev, allComplete: false }));
                setExtractedData(null);
                await fetchCaptureState();
              }}
              style={{
                background: 'rgba(239, 68, 68, 0.2)',
                color: '#f87171',
                border: '1px solid rgba(239, 68, 68, 0.4)',
                borderRadius: '10px',
                padding: '14px 24px',
                fontSize: '0.92rem',
                fontWeight: 600,
                cursor: 'pointer',
                transition: 'transform 0.15s'
              }}
              onMouseOver={(e) => e.currentTarget.style.transform = 'scale(1.02)'}
              onMouseOut={(e) => e.currentTarget.style.transform = 'scale(1)'}
            >
              🔄 Re-scan / Start Over
            </button>
            <button
              onClick={() => {
                stopCamera();
                if (voiceSessionRef.current) voiceSessionRef.current.disconnect();
                localStorage.removeItem('session_id');
                router.push('/dashboard');
              }}
              style={{
                background: 'linear-gradient(135deg, #22c55e, #16a34a)',
                color: '#fff',
                border: 'none',
                borderRadius: '10px',
                padding: '14px 40px',
                fontSize: '1rem',
                fontWeight: 700,
                cursor: 'pointer',
                boxShadow: '0 4px 20px rgba(34, 197, 94, 0.3)',
                transition: 'transform 0.15s'
              }}
              onMouseOver={(e) => e.currentTarget.style.transform = 'scale(1.02)'}
              onMouseOut={(e) => e.currentTarget.style.transform = 'scale(1)'}
            >
              ✓ Submit Application
            </button>
          </div>
        </div>
      </div>
    );
  };

  if (loading) return <div className={styles.container} style={{ justifyContent: 'center', height: '100vh' }}>Loading capture engine...</div>;

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
            borderRadius: '20px',
            padding: '10px 18px',
            maxWidth: '90%',
            width: '100%',
            boxShadow: '0 8px 32px rgba(0,0,0,0.25)',
            fontSize: '0.875rem',
            color: '#fff',
            pointerEvents: 'auto',
            flexDirection: 'row',
            justifyContent: 'flex-start'
          }} className={styles.interactive}>
            {/* Connection Dot */}
            <div style={{
              width: '8px',
              height: '8px',
              borderRadius: '50%',
              flexShrink: 0,
              background: qaState === 'listening' ? '#3b82f6' : qaState === 'speaking' ? '#10b981' : qaState === 'processing' ? '#a78bfa' : '#64748b',
              boxShadow: qaState === 'listening' ? '0 0 8px #3b82f6' : qaState === 'speaking' ? '0 0 8px #10b981' : qaState === 'processing' ? '0 0 8px #a78bfa' : 'none'
            }}></div>
            
            {/* Status & Live Transcript */}
            <div style={{ display: 'flex', flexDirection: 'row', flexWrap: 'wrap', gap: '6px', alignItems: 'center' }}>
              <span style={{ fontWeight: 600, color: '#94a3b8', whiteSpace: 'nowrap' }}>
                {qaState === 'listening' ? 'Listening' : qaState === 'processing' ? 'Processing' : qaState === 'speaking' ? 'Speaking' : 'Standby'}:
              </span>
              <span style={{ color: '#fff', fontWeight: 500, wordBreak: 'break-word', whiteSpace: 'normal', textAlign: 'left' }}>
                {transcript || (qaState === 'listening' ? 'Speak now...' : qaState === 'processing' ? 'Thinking...' : 'Voice assistant ready')}
              </span>
            </div>
          </div>

          <div className={styles.leftControls} style={{ width: '100%', maxWidth: '600px' }}>
            {/* Header / Progress over camera */}
            <div style={{ width: '100%', marginBottom: '16px' }}>
                <div className={styles.headerRow}>
                    <h2 style={{ fontSize: '1.15rem', fontWeight: 600, color: '#fff', margin: 0, display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <span>📄</span>
                        <span>{getCleanDocTitle(state.docId, manifests)}</span>
                        <span style={{ fontSize: '0.85rem', color: '#94a3b8', fontWeight: 400 }}>(Doc {state.docIndex + 1} of {state.totalDocs})</span>
                    </h2>
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
                  {torchSupported && (
                    <button 
                      className={styles.iconButton} 
                      onClick={toggleTorch} 
                      title="Toggle Flash"
                      style={{
                        background: torchOn ? 'rgba(234, 179, 8, 0.25)' : 'rgba(0, 0, 0, 0.3)',
                        borderColor: torchOn ? '#eab308' : 'rgba(255, 255, 255, 0.4)',
                        color: torchOn ? '#eab308' : '#fff'
                      }}
                    >
                      ⚡
                    </button>
                  )}
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

          {/* Text Message Input Bar for AI Voice Assistant */}
          <div style={{
            display: 'flex',
            alignItems: 'center',
            gap: '10px',
            background: 'rgba(15, 23, 42, 0.85)',
            backdropFilter: 'blur(20px)',
            border: '1px solid rgba(255, 255, 255, 0.12)',
            borderRadius: '16px',
            padding: '8px 12px',
            maxWidth: '600px',
            width: '100%',
            marginBottom: '10px'
          }} className={styles.interactive}>
            <input
              type="text"
              placeholder="Type a message to AI Assistant..."
              value={textInputValue}
              onChange={(e) => setTextInputValue(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') handleSendText();
              }}
              style={{
                flex: 1,
                padding: '10px 14px',
                background: '#1e293b',
                border: '1px solid #334155',
                borderRadius: '10px',
                color: '#fff',
                fontSize: '0.88rem',
                outline: 'none'
              }}
            />
            <button
              onClick={handleSendText}
              disabled={!textInputValue.trim()}
              style={{
                padding: '10px 20px',
                background: textInputValue.trim() ? '#3b82f6' : '#334155',
                color: '#fff',
                border: 'none',
                borderRadius: '10px',
                fontWeight: 600,
                fontSize: '0.85rem',
                cursor: textInputValue.trim() ? 'pointer' : 'not-allowed',
                transition: 'background 0.15s'
              }}
            >
              Send
            </button>
          </div>

        </div>
      </div>
      
      {/* ─── Completion Pop-Up Modal Overlay (preserves WS voice session) ─── */}
      {state.allComplete && renderCompletedTable()}

      {/* Hidden canvas for image capture */}
      <canvas ref={canvasRef} style={{ display: 'none' }} />
    </div>
  );
}
