'use client';

// Wrap console logs with precise milliseconds timestamp [HH:MM:SS.mmm]
if (typeof window !== 'undefined' && !window._consoleWrapped) {
  window._consoleWrapped = true;
  const originalLog = console.log;
  const originalWarn = console.warn;
  const originalError = console.error;
  const originalInfo = console.info;

  const getTimestamp = () => `[${new Date().toLocaleTimeString('en-US', { hour12: false })}.${String(new Date().getMilliseconds()).padStart(3, '0')}]`;

  console.log = function (...args) {
    originalLog.apply(console, [getTimestamp(), ...args]);
  };
  console.warn = function (...args) {
    originalWarn.apply(console, [getTimestamp(), ...args]);
  };
  console.error = function (...args) {
    originalError.apply(console, [getTimestamp(), ...args]);
  };
  console.info = function (...args) {
    originalInfo.apply(console, [getTimestamp(), ...args]);
  };
}

import { useState, useRef, useEffect, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import AuthGuard from '../components/AuthGuard';
import styles from './interview.module.css';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080';
const WS_BASE_URL = process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8080';

class AudioVisualizer {
  constructor(canvas) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.animationId = null;
    this.isActive = false;
    this.mode = 'idle'; // 'idle', 'recording', 'processing', 'speaking'

    // Audio data
    this.frequencyData = null;
    this.volumeLevel = 0;

    // Animation state
    this.time = 0;
    this.bars = [];
    this.initBars();
  }

  initBars() {
    const barCount = 40;
    this.bars = [];
    for (let i = 0; i < barCount; i++) {
      this.bars.push({
        height: 0,
        targetHeight: 0,
        velocity: 0,
      });
    }
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

  updateAudioData(frequencyData, volumeLevel) {
    this.frequencyData = frequencyData;
    this.volumeLevel = volumeLevel;
  }

  setMode(mode) {
    this.mode = mode;
  }

  _animate() {
    this.time += 0.016; // ~60fps
    if (this.ctx && this.width && this.height) {
      this.ctx.clearRect(0, 0, this.width, this.height);

      switch (this.mode) {
        case 'recording':
          this._drawRecording();
          break;
        case 'processing':
          this._drawProcessing();
          break;
        case 'speaking':
          this._drawSpeaking();
          break;
        default:
          this._drawIdle();
      }
    }

    this.animationId = requestAnimationFrame(() => this._animate());
  }

  _drawIdle() {
    const centerY = this.height / 2;
    const barCount = this.bars.length;
    const barWidth = 3;
    const gap = (this.width - barCount * barWidth) / (barCount + 1);

    for (let i = 0; i < barCount; i++) {
      const x = gap + i * (barWidth + gap);
      const wave = Math.sin(this.time * 2 + i * 0.3) * 3 + 4;

      this.bars[i].targetHeight = wave;
      this.bars[i].height += (this.bars[i].targetHeight - this.bars[i].height) * 0.1;

      const h = this.bars[i].height;
      const alpha = 0.15 + Math.sin(this.time * 1.5 + i * 0.2) * 0.05;

      this.ctx.fillStyle = `rgba(74, 120, 255, ${alpha})`;
      this.ctx.beginPath();
      if (this.ctx.roundRect) {
        this.ctx.roundRect(x, centerY - h / 2, barWidth, h, 1.5);
      } else {
        this.ctx.rect(x, centerY - h / 2, barWidth, h);
      }
      this.ctx.fill();
    }
  }

  _drawRecording() {
    const centerY = this.height / 2;
    const barCount = this.bars.length;
    const barWidth = 4;
    const gap = (this.width - barCount * barWidth) / (barCount + 1);
    const maxHeight = this.height * 0.8;

    for (let i = 0; i < barCount; i++) {
      let targetHeight;

      if (this.frequencyData && this.frequencyData.length > 0) {
        const freqIndex = Math.floor((i / barCount) * this.frequencyData.length);
        const freqValue = this.frequencyData[freqIndex] / 255;
        targetHeight = Math.max(4, freqValue * maxHeight);
      } else {
        const wave = Math.sin(this.time * 4 + i * 0.4);
        targetHeight = 4 + this.volumeLevel * maxHeight * 0.5 * (0.5 + wave * 0.5);
      }

      const spring = 0.15;
      const damping = 0.8;
      this.bars[i].velocity = (this.bars[i].velocity + (targetHeight - this.bars[i].height) * spring) * damping;
      this.bars[i].height += this.bars[i].velocity;

      const x = gap + i * (barWidth + gap);
      const h = Math.max(2, this.bars[i].height);

      const intensity = h / maxHeight;
      const r = Math.floor(74 + intensity * 181);
      const g = Math.floor(120 + intensity * 135);
      const b = Math.floor(255 - intensity * 0);

      this.ctx.fillStyle = `rgba(${r}, ${g}, ${b}, 0.8)`;
      this.ctx.beginPath();
      if (this.ctx.roundRect) {
        this.ctx.roundRect(x, centerY - h / 2, barWidth, h, 2);
      } else {
        this.ctx.rect(x, centerY - h / 2, barWidth, h);
      }
      this.ctx.fill();
    }
  }

  _drawProcessing() {
    const centerY = this.height / 2;
    const barCount = this.bars.length;
    const barWidth = 3;
    const gap = (this.width - barCount * barWidth) / (barCount + 1);

    for (let i = 0; i < barCount; i++) {
      const x = gap + i * (barWidth + gap);
      const wave = Math.sin(this.time * 3 + i * 0.25) * 8 + 10;
      const alpha = 0.3 + Math.sin(this.time * 2 + i * 0.15) * 0.2;

      this.bars[i].height += (wave - this.bars[i].height) * 0.08;
      const h = this.bars[i].height;

      const t = (Math.sin(this.time * 2 + i * 0.1) + 1) / 2;
      const r = Math.floor(167 * (1 - t) + 244 * t);
      const g = Math.floor(139 * (1 - t) + 114 * t);
      const b = Math.floor(250 * (1 - t) + 182 * t);

      this.ctx.fillStyle = `rgba(${r}, ${g}, ${b}, ${alpha})`;
      this.ctx.beginPath();
      if (this.ctx.roundRect) {
        this.ctx.roundRect(x, centerY - h / 2, barWidth, h, 1.5);
      } else {
        this.ctx.rect(x, centerY - h / 2, barWidth, h);
      }
      this.ctx.fill();
    }
  }

  _drawSpeaking() {
    const centerY = this.height / 2;
    const barCount = this.bars.length;
    const barWidth = 4;
    const gap = (this.width - barCount * barWidth) / (barCount + 1);

    for (let i = 0; i < barCount; i++) {
      const x = gap + i * (barWidth + gap);
      const wave1 = Math.sin(this.time * 3 + i * 0.25) * 12;
      const wave2 = Math.sin(this.time * 5 + i * 0.4) * 6;
      const targetH = Math.abs(wave1 + wave2) + 4;

      this.bars[i].height += (targetH - this.bars[i].height) * 0.12;
      const h = this.bars[i].height;

      const alpha = 0.4 + Math.sin(this.time * 2.5 + i * 0.2) * 0.2;
      this.ctx.fillStyle = `rgba(34, 201, 104, ${alpha})`;
      this.ctx.beginPath();
      if (this.ctx.roundRect) {
        this.ctx.roundRect(x, centerY - h / 2, barWidth, h, 2);
      } else {
        this.ctx.rect(x, centerY - h / 2, barWidth, h);
      }
      this.ctx.fill();
    }
  }

  destroy() {
    if (this.animationId) {
      cancelAnimationFrame(this.animationId);
    }
  }
}

const DOCUMENT_METADATA = {
  'selfie': { label: 'Selfie', icon: '🤳', facingMode: 'user', tips: ['Face should be clearly visible', 'Good lighting is required'] },
  'aadhaar_front': { label: 'Aadhaar (Front)', icon: '🪪', facingMode: 'environment', tips: ['Full card should be visible', 'Number must be clear'] },
  'aadhaar_back': { label: 'Aadhaar (Back)', icon: '🪪', facingMode: 'environment', tips: ['QR code should be clear'] },
  'pan': { label: 'PAN Card', icon: '💳', facingMode: 'environment', tips: ['Full PAN card should be in frame'] },
  'spouse_pan': { label: 'Spouse PAN', icon: '💳', facingMode: 'environment', tips: ['Keep spouse\'s PAN card ready'] },
  'voter_front': { label: 'Voter ID (Front)', icon: '🪪', facingMode: 'environment', tips: ['Card must be clear and fully visible'] },
  'voter_back': { label: 'Voter ID (Back)', icon: '🪪', facingMode: 'environment', tips: ['Back address details must be readable'] },
  'udyam': { label: 'Udyam Certificate', icon: '📜', facingMode: 'environment', tips: ['Keep full Udyam document ready'] },
  'bank_statement': { label: 'Bank Statement', icon: '🏦', facingMode: 'environment', tips: ['All pages must be included'] },
  'company_id': { label: 'Company ID', icon: '🏢', facingMode: 'environment', tips: ['ID should be clear'] },
  'office_id': { label: 'Office ID', icon: '🪪', facingMode: 'environment', tips: ['Office ID should be clear'] },
  'address_proof': { label: 'Address Proof', icon: '📄', facingMode: 'environment', tips: ['Address must be clearly visible'] },
  'correspondence_proof': { label: 'Correspondence Proof', icon: '📄', facingMode: 'environment', tips: ['Address must be clearly visible'] },
  'workplace_video': { 
    label: 'Workplace Video', 
    icon: '📹', 
    facingMode: 'environment', 
    tips: [
      'Show your business board, stock, and workspace', 
      'Hold the camera steady', 
      'Follow the spoken instructions'
    ] 
  }
};

function InterviewContent() {
  const router = useRouter();

  // Basic Session Info
  const [token, setToken] = useState('');
  const [sessionId, setSessionId] = useState('');
  const [applicationId, setApplicationId] = useState('');
  const [schemeId, setSchemeId] = useState('mudra-grocery');

  // Flow State (Driven by backend)
  const [isStarted, setIsStarted] = useState(false);
  const [nodeType, setNodeType] = useState('voice-qa'); // 'voice-qa' or 'capture' or 'video_capture'
  const [documentId, setDocumentId] = useState('selfie');
  const [manifestId, setManifestId] = useState('');
  const [pageId, setPageId] = useState('');
  const [currentStep, setCurrentStep] = useState(0);
  const [totalSteps, setTotalSteps] = useState(0);

  // Voice Assistant State
  const [qaState, setQaState] = useState('idle');
  const [transcript, setTranscript] = useState('');
  const [textInputValue, setTextInputValue] = useState('');
  const voiceSessionRef = useRef(null);
  const prevQaStateRef = useRef('');

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

  // Live Video Recording State & Refs
  const [isRecordingVideo, setIsRecordingVideo] = useState(false);
  const [recordingTimeRemaining, setRecordingTimeRemaining] = useState(30);
  const [currentInstructionText, setCurrentInstructionText] = useState('');
  const mediaRecorderRef = useRef(null);
  const videoChunksRef = useRef([]);
  const recordingIntervalRef = useRef(null);
  const capturedLatitudeRef = useRef(null);
  const capturedLongitudeRef = useRef(null);
  const [locationPermissionState, setLocationPermissionState] = useState('prompt'); // 'prompt', 'checking', 'granted', 'denied'
  const canvasDrawLoopActiveRef = useRef(false);

  // Canvas visualizer refs
  const visualizerCanvasRef = useRef(null);
  const visualizerInstanceRef = useRef(null);

  // Post-Interview Review Modal State
  const [showReviewModal, setShowReviewModal] = useState(false);
  const [reviewFields, setReviewFields] = useState({});
  const [isSavingReview, setIsSavingReview] = useState(false);

  const REVIEW_SECTIONS = [
    {
      id: 'personal',
      title: 'Personal & Identity Information',
      icon: '👤',
      keys: ['applicant_name', 'date_of_birth', 'gender', 'phone', 'father_name', 'marital_status', 'education_level', 'number_of_family_members', 'number_of_kids', 'address']
    },
    {
      id: 'documents',
      title: 'Verified Government ID Details',
      icon: '📄',
      keys: ['aadhaar_number', 'pan_number', 'udyam_number', 'epic_number']
    },
    {
      id: 'enterprise',
      title: 'Enterprise & Business Details',
      icon: '🏢',
      keys: ['enterprise_name', 'business_type', 'type_of_enterprise', 'major_activity', 'social_category', 'business_purpose', 'udyam_email', 'udyam_mobile', 'business_address']
    },
    {
      id: 'financials',
      title: 'Financial & Operations Data',
      icon: '💰',
      keys: ['monthly_revenue', 'monthly_profit', 'last_year_monthly_revenue', 'persons_involved', 'number_of_paid_employees', 'current_wages', 'inventory_amount', 'debtors_amount', 'creditors_amount']
    },
    {
      id: 'loan',
      title: 'Loan & Equipment Requirements',
      icon: '⚙️',
      keys: ['needs_machine', 'machine_name', 'machine_purpose', 'machine_supplier', 'machine_cost', 'co_borrower', 'previous_loan_detail', 'previous_loan_default_flag', 'default_reason', 'current_emi_value']
    }
  ];

  const FRIENDLY_FIELD_LABELS = {
    applicant_name: 'Full Name',
    date_of_birth: 'Date of Birth',
    gender: 'Gender',
    phone: 'Mobile Number',
    father_name: "Father / Husband Name",
    email: 'Email Address',
    marital_status: 'Marital Status',
    education_level: 'Qualification',
    number_of_family_members: 'Family Members Count',
    number_of_kids: 'Children Count',
    address: 'Residential Address',
    aadhaar_number: 'Aadhaar Card Number',
    pan_number: 'PAN Card Number',
    udyam_number: 'Udyam Registration Number',
    epic_number: 'Voter ID EPIC Number',
    enterprise_name: 'Enterprise Name',
    business_type: 'Business Type',
    type_of_enterprise: 'Enterprise Category (Micro/Small)',
    major_activity: 'Major Activity (Trading/Mfg/Service)',
    social_category: 'Social Category',
    business_purpose: 'Business Line / Purpose',
    udyam_email: 'Business Email',
    udyam_mobile: 'Business Registered Phone',
    business_address: 'Business Workplace Address',
    monthly_revenue: 'Monthly Sales / Revenue (₹)',
    monthly_profit: 'Monthly Profit (₹)',
    last_year_monthly_revenue: 'Past Year Monthly Sales (₹)',
    persons_involved: 'Persons Involved Currently',
    number_of_paid_employees: 'Paid Employees Count',
    current_wages: 'Annual Wages Paid (₹)',
    inventory_amount: 'Inventory Value (₹)',
    debtors_amount: 'Receivables / Debtors (₹)',
    creditors_amount: 'Payables / Creditors (₹)',
    needs_machine: 'Machine Purchase Needed?',
    machine_name: 'Machine / Equipment Description',
    machine_purpose: 'Purpose of Machine',
    machine_supplier: 'Equipment Supplier Name',
    machine_cost: 'Machine / Equipment Cost (₹)',
    co_borrower: 'Co-Borrower Present?',
    previous_loan_detail: 'Previous Loan Details',
    previous_loan_default_flag: 'Prior Default Record?',
    default_reason: 'Default Reason (if any)',
    current_emi_value: 'Current Monthly EMI (₹)'
  };

  const buildComprehensiveFieldsMap = (data, phoneArg = '', applicantNameArg = '') => {
    const extracted = data.extracted_data || data || {};
    const extractions = extracted.extractions || {};

    const getNested = (obj, pathArray) => {
      let curr = obj;
      for (const p of pathArray) {
        if (curr && typeof curr === 'object') {
          curr = curr[p];
        } else {
          return undefined;
        }
      }
      return curr;
    };

    const getVal = (paths) => {
      for (const p of paths) {
        const parts = p.split('.');
        let val = getNested(extracted, parts);
        if (val === undefined || val === null || val === '') {
          val = getNested(extractions, parts);
        }
        if (val !== undefined && val !== null && val !== '') {
          if (typeof val === 'object') return JSON.stringify(val);
          return String(val);
        }
      }
      return '';
    };

    const formatAddress = (addrObj) => {
      if (!addrObj) return '';
      if (typeof addrObj === 'string') return addrObj;
      if (typeof addrObj === 'object') {
        const parts = [
          addrObj.house_number || addrObj.house || addrObj.flat_door_block,
          addrObj.street || addrObj.road_street_lane || addrObj.building_name,
          addrObj.locality || addrObj.village_town || addrObj.village_town_city,
          addrObj.subdistrict || addrObj.tehsil || addrObj.vtc,
          addrObj.district || addrObj.city,
          addrObj.state,
          addrObj.pincode
        ].filter(Boolean);
        return parts.join(', ');
      }
      return '';
    };

    return {
      applicant_name: getVal(['applicant_name', 'doc_aadhaar_name', 'doc_pan_name', 'doc_voter_name', 'holder.full_name', 'extractions.doc_aadhaar_002.doc_aadhaar_name', 'extractions.doc_pan_001.doc_pan_name', 'extractions.voter_front.doc_voter_name']) || applicantNameArg,
      date_of_birth: getVal(['date_of_birth', 'doc_aadhaar_dob', 'doc_pan_dob', 'doc_voter_dob', 'holder.date_of_birth', 'extractions.doc_aadhaar_002.doc_aadhaar_dob', 'extractions.doc_pan_001.doc_pan_dob', 'extractions.voter_front.doc_voter_dob']),
      gender: getVal(['gender', 'doc_aadhaar_gender', 'doc_voter_gender', 'holder.gender', 'extractions.doc_aadhaar_002.doc_aadhaar_gender', 'extractions.voter_front.doc_voter_gender']),
      phone: getVal(['phone', 'mobile_number']) || phoneArg,
      father_name: getVal(['father_name', 'doc_pan_father_name', 'doc_voter_father_name', 'extractions.doc_pan_001.doc_pan_father_name', 'extractions.voter_front.doc_voter_father_name']),
      marital_status: getVal(['marital_status', 'is_married']),
      education_level: getVal(['education_level']),
      number_of_family_members: getVal(['number_of_family_members']),
      number_of_kids: getVal(['number_of_kids']),
      address: formatAddress(extracted.address) || formatAddress(extracted.doc_aadhaar_address) || formatAddress(extracted.doc_voter_address) || formatAddress(getNested(extractions, ['doc_aadhaar_002', 'doc_aadhaar_address'])) || formatAddress(getNested(extractions, ['doc_voter_001', 'doc_voter_address'])),

      aadhaar_number: getVal(['aadhaar_number', 'doc_aadhaar_last4', 'extractions.doc_aadhaar_002.doc_aadhaar_last4']),
      pan_number: getVal(['pan_number', 'doc_pan_number', 'extractions.doc_pan_001.doc_pan_number']),
      udyam_number: getVal(['udyam_number', 'doc_udyam_registration_number', 'extractions.doc_udyam_001.doc_udyam_registration_number']),
      epic_number: getVal(['epic_number', 'doc_voter_number', 'extractions.voter_front.doc_voter_number']),

      enterprise_name: getVal(['enterprise.enterprise_name', 'enterprise_name', 'doc_udyam_enterprise_name', 'extractions.doc_udyam_001.doc_udyam_enterprise_name']),
      business_type: getVal(['business_type', 'type_of_business', 'doc_udyam_enterprise_type', 'extractions.doc_udyam_001.doc_udyam_enterprise_type']),
      type_of_enterprise: getVal(['enterprise.type_of_enterprise', 'type_of_enterprise', 'doc_udyam_enterprise_type', 'extractions.doc_udyam_001.doc_udyam_enterprise_type']),
      major_activity: getVal(['enterprise.major_activity', 'major_activity', 'doc_udyam_major_activity', 'extractions.doc_udyam_001.doc_udyam_major_activity']),
      social_category: getVal(['enterprise.social_category', 'social_category', 'doc_udyam_social_category', 'extractions.doc_udyam_001.doc_udyam_social_category']),
      business_purpose: getVal(['business_purpose', 'existing_business_activity']),
      udyam_email: getVal(['contact_details.email', 'extractions.doc_udyam_001.contact_details.email']),
      udyam_mobile: getVal(['contact_details.mobile', 'extractions.doc_udyam_001.contact_details.mobile']),
      business_address: formatAddress(extracted.business_address) || formatAddress(extracted.doc_udyam_enterprise_address) || formatAddress(getNested(extractions, ['doc_udyam_001', 'doc_udyam_enterprise_address'])),

      monthly_revenue: getVal(['monthly_revenue', 'business_revenue', 'net_sales_present_year']),
      monthly_profit: getVal(['monthly_profit', 'net_profit_present_year']),
      last_year_monthly_revenue: getVal(['last_year_monthly_revenue', 'net_sales_past_year_1']),
      persons_involved: getVal(['persons_involved', 'number_of_persons_involved_currently']),
      number_of_paid_employees: getVal(['number_of_paid_employees']),
      current_wages: getVal(['current_wages', 'current_total_wages']),
      inventory_amount: getVal(['inventory_amount', 'inventory']),
      debtors_amount: getVal(['debtors_amount', 'debtors']),
      creditors_amount: getVal(['creditors_amount', 'creditors']),

      needs_machine: getVal(['needs_machine']),
      machine_name: getVal(['machine_name', 'type_of_machine_equipment']),
      machine_purpose: getVal(['machine_purpose', 'purpose']),
      machine_supplier: getVal(['machine_supplier', 'name_of_supplier']),
      machine_cost: getVal(['machine_cost', 'approximate_cost']),
      co_borrower: getVal(['co_borrower']),
      previous_loan_detail: getVal(['previous_loan_detail']),
      previous_loan_default_flag: getVal(['previous_loan_default_flag']),
      default_reason: getVal(['default_reason']),
      current_emi_value: getVal(['current_emi_value'])
    };
  };

  const playReviewVoiceAnnouncement = (lang) => {
    if (voiceSessionRef.current) {
      const msg = lang === 'hi' 
        ? "यह आपकी दर्ज की गई जानकारी है। कृपया जांच लें और पुष्टि करें।"
        : "Here are your extracted details. Please review and confirm.";
      voiceSessionRef.current.sendControlSignal(`capture_speak:${msg}`);
    }
  };

  const handleFieldChange = (key, value) => {
    setReviewFields(prev => ({ ...prev, [key]: value }));
  };

  const handleSaveAndConfirmReview = async () => {
    setIsSavingReview(true);
    if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
      window.speechSynthesis.cancel();
    }
    try {
      const savedToken = localStorage.getItem('token') || token;
      const savedSessionId = localStorage.getItem('session_id') || sessionId;

      if (savedToken && savedSessionId) {
        // 1. Save metadata & onboarding status to DB
        await fetch(`${API_BASE_URL}/api/applications/save-metadata`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${savedToken}`
          },
          body: JSON.stringify({
            session_id: savedSessionId,
            fields: {
              ...reviewFields,
              onboarding_finished: true,
              completion_status: 'COMPLETED'
            }
          })
        });

        // 2. Trigger background post-processing calculations
        await fetch(`${API_BASE_URL}/api/applications/trigger-evaluations`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${savedToken}`
          },
          body: JSON.stringify({ session_id: savedSessionId })
        });
      }
    } catch (err) {
      console.error('Error saving confirmed review details:', err);
    } finally {
      setIsSavingReview(false);
      setShowReviewModal(false);
      router.push('/dashboard/details');
    }
  };

  const handleOpenManualFillingModal = async () => {
    try {
      const savedToken = localStorage.getItem('token') || token;
      const savedSessionId = localStorage.getItem('session_id') || sessionId;
      if (savedToken && savedSessionId) {
        const res = await fetch(`${API_BASE_URL}/api/applications/${savedSessionId}`, {
          headers: { 'Authorization': `Bearer ${savedToken}` }
        });
        const data = await res.json();
        const fieldsMap = buildComprehensiveFieldsMap(data, data.phone || '', data.applicant_name || data.doc_aadhaar_name || '');

        setReviewFields(fieldsMap);
        setShowReviewModal(true);
        playReviewVoiceAnnouncement(selectedLanguage);
      }
    } catch (e) {
      console.error('Failed to open manual filling table:', e);
    }
  };

  const handleContinueWithVoiceAssistant = () => {
    if (voiceSessionRef.current) {
      voiceSessionRef.current.sendTextInput("जारी रखें");
    }
  };

  useEffect(() => {
    const savedToken = localStorage.getItem('token');
    const savedSessionId = localStorage.getItem('session_id');

    if (!savedToken || !savedSessionId) {
      router.push('/');
    } else {
      setToken(savedToken);
      setSessionId(savedSessionId);
      setApplicationId(savedSessionId);
      setSchemeId('mudra-grocery');
    }

    import('../utils/voiceHelper').then(({ loadVADScripts }) => {
      loadVADScripts().catch(console.error);
    });
    
    return () => {
      if (voiceSessionRef.current) {
        voiceSessionRef.current.disconnect();
      }
      if (visualizerInstanceRef.current) {
        visualizerInstanceRef.current.destroy();
        visualizerInstanceRef.current = null;
      }
    };
  }, [router]);

  // Handle visualizer lifecycle
  useEffect(() => {
    if (isStarted && nodeType === 'voice-qa' && visualizerCanvasRef.current) {
      if (!visualizerInstanceRef.current) {
        visualizerInstanceRef.current = new AudioVisualizer(visualizerCanvasRef.current);
      }
      let mode = 'idle';
      if (qaState === 'listening') mode = 'recording';
      else if (qaState === 'processing') mode = 'processing';
      else if (qaState === 'speaking') mode = 'speaking';
      visualizerInstanceRef.current.setMode(mode);
    }
    return () => {
      if (!isStarted || nodeType !== 'voice-qa') {
        if (visualizerInstanceRef.current) {
          visualizerInstanceRef.current.destroy();
          visualizerInstanceRef.current = null;
        }
      }
    };
  }, [isStarted, nodeType, qaState]);

  const startSession = async () => {
    setErrors(prev => ({ ...prev, global: null, warning: null }));

    // Check location permission if this is a Mudra scheme
    const isMudra = schemeId.includes('mudra') || schemeId === 'a74b1b43-7cc6-4385-8a8c-12af64cddb2b';
    if (isMudra) {
      const locationGranted = await checkLocationPermission();
      if (!locationGranted) {
        // Stop execution, show the location permission warning/retry panel in renderVideoUI
        setLocationPermissionState('denied');
        setNodeType('video_capture');
        setIsStarted(true);
        return;
      }
    }

    setIsStarted(true);
    setQaState('connecting');

    // Initialize and resume AudioContext synchronously in click handler
    window.globalAudioContext = window.globalAudioContext || new (window.AudioContext || window.webkitAudioContext)();
    if (window.globalAudioContext.state === 'suspended') {
      try { window.globalAudioContext.resume(); } catch (e) { console.error('Failed to resume AudioContext:', e); }
    }

    try {
      const { VoiceSessionManager, loadVADScripts } = await import('../utils/voiceHelper');

      const isLoaded = await loadVADScripts();
      if (!isLoaded) {
        throw new Error('VAD scripts could not be loaded. Please check your connection and try again.');
      }

      const manager = new VoiceSessionManager({
        token,
        sessionId,
        applicationId,
        applicantName: '',
        schemeId: schemeId,
        language: selectedLanguage,
        wsUrl: `${WS_BASE_URL.replace('http', 'ws')}/ws/voice`,
        onStateChange: (state) => {
          console.log('[DEBUG Frontend] onStateChange:', state);
          setQaState(state);

          const prev = prevQaStateRef.current;
          prevQaStateRef.current = state;

          if (state !== 'speaking' || prev !== 'speaking') {
            setTranscript('');
          }

          if (visualizerInstanceRef.current) {
            let mode = 'idle';
            if (state === 'listening') mode = 'recording';
            else if (state === 'processing') mode = 'processing';
            else if (state === 'speaking') mode = 'speaking';
            visualizerInstanceRef.current.setMode(mode);
          }
        },
        onTranscript: (text, isFinal) => {
          console.log('[DEBUG Frontend] onTranscript:', text, 'isFinal:', isFinal);
          setTranscript(text);
        },
        onProgress: (step, total, nodeId) => {
          console.log('[DEBUG Frontend] onProgress: step =', step, 'total =', total, 'nodeId =', nodeId);
          setCurrentStep(step);
          setTotalSteps(total);
        },
        onNodeChange: (type, docId, manifest_id, page_id) => {
          console.log('[DEBUG Frontend] onNodeChange: type =', type, 'docId =', docId, 'manifest_id =', manifest_id, 'page_id =', page_id);
          setNodeType(type);
          if (docId) setDocumentId(docId);
          setManifestId(manifest_id || '');
          setPageId(page_id || '');
        },
        onComplete: async () => {
          console.log('[DEBUG Frontend] onComplete triggered, opening extracted details review modal...');
          try {
            const savedToken = localStorage.getItem('token') || token;
            const savedSessionId = localStorage.getItem('session_id') || sessionId;
            if (savedToken && savedSessionId) {
              const res = await fetch(`${API_BASE_URL}/api/applications/${savedSessionId}`, {
                headers: { 'Authorization': `Bearer ${savedToken}` }
              });
              const data = await res.json();
              const fieldsMap = buildComprehensiveFieldsMap(data, data.phone || '', data.applicant_name || data.doc_aadhaar_name || '');

              setReviewFields(fieldsMap);
              setShowReviewModal(true);

              // Play vocal announcement via backend TTS
              playReviewVoiceAnnouncement(selectedLanguage);
            } else {
              router.push('/dashboard/details');
            }
          } catch (e) {
            console.error('Failed to fetch extracted details for review modal:', e);
            router.push('/dashboard/details');
          }
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

      // Hook visualizer to AudioProcessor volume level callback
      if (manager.audioProcessor) {
        manager.audioProcessor.onVolumeLevel = (level) => {
          if (visualizerInstanceRef.current) {
            visualizerInstanceRef.current.updateAudioData(null, level);
          }
        };
      }


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

  const uploadFileDirectly = async (file, lat = null, lon = null) => {
    if (!file) return;
    const previewUrl = URL.createObjectURL(file);
    setDocs(prev => ({ ...prev, [documentId]: { file, url: previewUrl, name: file.name } }));
    setVerifying(true);
    setErrors(prev => ({ ...prev, [documentId]: null }));

    // Stop any in-flight audio prompt and send processing feedback to the voice assistant
    if (voiceSessionRef.current) {
      voiceSessionRef.current.stopAudioPlayback();
      voiceSessionRef.current.sendControlSignal('capture_processing');
    }

    try {
      const formData = new FormData();
      formData.append('file', file);
      formData.append('document_type', documentId);
      formData.append('scheme_id', schemeId);
      formData.append('session_id', sessionId);
      if (manifestId) formData.append('manifest_id', manifestId);
      if (pageId) formData.append('page_id', pageId);
      if (lat !== null && lat !== undefined) formData.append('latitude', String(lat));
      if (lon !== null && lon !== undefined) formData.append('longitude', String(lon));

      const res = await fetch(`${API_BASE_URL}/api/documents/extract`, {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${token}` },
        body: formData
      });

      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || data.error || 'Failed to upload');
      if (data.success === false) {
        throw new Error(data.error || 'Document verification failed. Please upload a valid document.');
      }

      setVerified(prev => ({ ...prev, [documentId]: true }));
      
      // Notify voice session of success (includes documentId to personalize message)
      if (voiceSessionRef.current) {
        voiceSessionRef.current._waitingForCaptureTransition = true;
        voiceSessionRef.current.sendControlSignal(`capture_success:${documentId}`);
      }
    } catch (err) {
      setErrors(prev => ({ ...prev, [documentId]: err.message }));
      setDocs(prev => {
        const copy = { ...prev };
        delete copy[documentId];
        return copy;
      });
      // Notify voice session of error to play vocal feedback
      if (voiceSessionRef.current) {
        voiceSessionRef.current.sendControlSignal(`capture_error:${err.message}`);
      }
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

  // Geolocation check and request permission helper
  const checkLocationPermission = useCallback(async () => {
    if (!navigator.geolocation) {
      setLocationPermissionState('denied');
      return false;
    }
    setLocationPermissionState('checking');
    return new Promise((resolve) => {
      navigator.geolocation.getCurrentPosition(
        (pos) => {
          capturedLatitudeRef.current = pos.coords.latitude;
          capturedLongitudeRef.current = pos.coords.longitude;
          setLocationPermissionState('granted');
          resolve(true);
        },
        (err) => {
          console.warn('[geolocation] check failed:', err.message);
          setLocationPermissionState('denied');
          resolve(false);
        },
        { enableHighAccuracy: true, timeout: 5000 }
      );
    });
  }, []);

  // Video Recording Logic with Canvas overlay & Web Audio merger
  const startVideoRecording = async () => {
    try {
      videoChunksRef.current = [];
      setRecordingTimeRemaining(30);

      // Verify permission/location is ready
      if (locationPermissionState !== 'granted') {
        const granted = await checkLocationPermission();
        if (!granted) {
          throw new Error('Location permission denied or not available');
        }
      }

      // Check if current stream already has audio. If not, request camera with audio.
      let stream = streamRef.current;
      const hasAudio = stream && stream.getAudioTracks().length > 0;
      if (!hasAudio) {
        stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: activeFacingMode, width: { ideal: 1280 }, height: { ideal: 720 } },
          audio: true
        });
        streamRef.current = stream;
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
          videoRef.current.play().catch(e => console.error(e));
        }
      }

      // Create a 640x480 canvas for burning location and time overlays
      const canvas = document.createElement('canvas');
      canvas.width = 640;
      canvas.height = 480;
      const ctx = canvas.getContext('2d');

      // Frame rendering loop
      canvasDrawLoopActiveRef.current = true;
      const drawFrame = () => {
        if (!canvasDrawLoopActiveRef.current) return;
        if (videoRef.current && !videoRef.current.paused && !videoRef.current.ended) {
          ctx.drawImage(videoRef.current, 0, 0, canvas.width, canvas.height);
          
          // Transparent bottom banner background
          ctx.fillStyle = 'rgba(2, 3, 7, 0.65)';
          ctx.fillRect(0, canvas.height - 70, canvas.width, 70);
          
          // Red recording indicator dot
          ctx.fillStyle = '#ef4444';
          ctx.beginPath();
          ctx.arc(30, canvas.height - 35, 6, 0, 2 * Math.PI);
          ctx.fill();

          // Geotag details text
          ctx.font = 'bold 13px Inter, monospace';
          ctx.fillStyle = '#ffffff';
          const timeStr = new Date().toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' });
          const latVal = capturedLatitudeRef.current ? capturedLatitudeRef.current.toFixed(6) : 'Fetching...';
          const lngVal = capturedLongitudeRef.current ? capturedLongitudeRef.current.toFixed(6) : 'Fetching...';
          
          ctx.fillText(`REC: ${timeStr}`, 48, canvas.height - 45);
          ctx.fillText(`GPS: Lat ${latVal}, Lng ${lngVal}`, 48, canvas.height - 25);
        }
        requestAnimationFrame(drawFrame);
      };
      drawFrame();

      // Grab canvas stream at 25 frames per second
      const canvasStream = canvas.captureStream(25);
      const audioTrack = stream.getAudioTracks()[0];
      if (audioTrack) {
        canvasStream.addTrack(audioTrack);
      }

      // Setup media recorder on composite canvasStream
      const options = { mimeType: 'video/webm;codecs=vp8,opus' };
      let recorder;
      try {
        recorder = new MediaRecorder(canvasStream, options);
      } catch (e) {
        console.warn('VP8/Opus not supported, trying default browser settings');
        recorder = new MediaRecorder(canvasStream);
      }

      recorder.ondataavailable = (event) => {
        if (event.data && event.data.size > 0) {
          videoChunksRef.current.push(event.data);
        }
      };

      recorder.onstop = async () => {
        const videoBlob = new Blob(videoChunksRef.current, { type: 'video/webm' });
        const file = new File([videoBlob], `workplace_video_${Date.now()}.webm`, { type: 'video/webm' });
        await uploadFileDirectly(file, capturedLatitudeRef.current, capturedLongitudeRef.current);
      };

      mediaRecorderRef.current = recorder;
      recorder.start(1000); // chunk data every 1s
      setIsRecordingVideo(true);

      // Timed Vocal Instructions via Central WebSocket TTS Service
      const videoInstructions = [
        { offset: 0, text: "कृपया कैमरे को चालू करें और अपनी दुकान के चारों ओर घुमाकर अपना वर्कप्लेस दिखाएं।" },
        { offset: 10, text: "अब दुकान के मुख्य माल या इन्वेंटरी वाले हिस्से को करीब से दिखाएं।" },
        { offset: 20, text: "धन्यवाद। अब वीडियो रिकॉर्डिंग समाप्त कर सकते हैं।" }
      ];

      let secondsElapsed = 0;
      const speakInstruction = (text) => {
        setCurrentInstructionText(text);
        if (voiceSessionRef.current) {
          voiceSessionRef.current.sendControlSignal(`capture_speak:${text}`);
        }
      };

      speakInstruction(videoInstructions[0].text);

      recordingIntervalRef.current = setInterval(() => {
        secondsElapsed += 1;
        const remaining = 30 - secondsElapsed;
        setRecordingTimeRemaining(remaining);

        const inst = videoInstructions.find(item => item.offset === secondsElapsed);
        if (inst) {
          speakInstruction(inst.text);
        }

        if (remaining <= 0) {
          stopVideoRecording();
        }
      }, 1000);

    } catch (err) {
      console.error('Failed to start video recording:', err);
      setErrors(prev => ({ ...prev, [documentId]: `Failed to access camera/audio or geolocation: ${err.message}` }));
    }
  };

  const stopVideoRecording = () => {
    canvasDrawLoopActiveRef.current = false;
    if (recordingIntervalRef.current) {
      clearInterval(recordingIntervalRef.current);
      recordingIntervalRef.current = null;
    }
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
      mediaRecorderRef.current.stop();
    }
    setIsRecordingVideo(false);
    if (voiceSessionRef.current) {
      voiceSessionRef.current.stopAudioPlayback();
    }
  };

  const stopVideoRecordingManual = () => {
    stopVideoRecording();
  };

  useEffect(() => {
    if (isStarted && (nodeType === 'capture' || nodeType === 'video_capture') && !docs[documentId]) {
      if (nodeType === 'video_capture') {
        checkLocationPermission().then((granted) => {
          if (granted) {
            const meta = DOCUMENT_METADATA[documentId] || {};
            const facing = meta.facingMode || activeFacingMode;
            startCamera(facing);
          } else {
            stopCamera();
          }
        });
      } else {
        const meta = DOCUMENT_METADATA[documentId] || {};
        const facing = meta.facingMode || activeFacingMode;
        startCamera(facing);
      }
    } else {
      stopCamera();
    }
    return () => stopCamera();
  }, [isStarted, nodeType, documentId, activeFacingMode, docs[documentId], startCamera, stopCamera, checkLocationPermission]);

  // Render Neural Voice Core (Fully aligned with visualizer canvas)
  const renderVoiceUI = () => {
    let sphereClass = styles.coreSphere;
    let ringClass = '';
    let isCallActive = false;

    if (qaState === 'listening') {
      sphereClass = `${styles.coreSphere} ${styles.sphereListening}`;
      ringClass = styles.ringActive;
      isCallActive = true;
    } else if (qaState === 'processing') {
      sphereClass = `${styles.coreSphere} ${styles.sphereProcessing}`;
      ringClass = styles.ringActive;
      isCallActive = true;
    } else if (qaState === 'speaking') {
      sphereClass = `${styles.coreSphere} ${styles.sphereSpeaking}`;
      ringClass = styles.ringActive;
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

        <div className={styles.neuralCoreWrapper}>
          <div className={`${styles.coreRing} ${styles.ring1} ${ringClass}`}></div>
          <div className={`${styles.coreRing} ${styles.ring2} ${ringClass}`}></div>
          <div className={`${styles.coreRing} ${styles.ring3} ${ringClass}`}></div>

          <div className={`${sphereClass} ${isCallActive ? styles.sphereActive : ''}`}>
            <div className={styles.coreGlowInner}></div>
          </div>

          {/* Canvas Waveforms Visualizer (from visualizer.js) */}
          <div className={`${styles.visualizerWrapper} ${isCallActive ? styles.visualizerActive : ''}`}>
            <canvas ref={visualizerCanvasRef} style={{ width: '300px', height: '300px' }}></canvas>
          </div>
        </div>

        {/* Transcription and Status Display */}
        <div style={{
          marginTop: '24px',
          marginBottom: '16px',
          minHeight: '48px',
          maxWidth: '480px',
          textAlign: 'center',
          zIndex: 10,
          padding: '0 20px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center'
        }}>
          <p style={{
            fontSize: '1rem',
            color: '#a0aec0',
            fontWeight: 500,
            lineHeight: '1.6',
            margin: 0
          }}>
            {transcript || (qaState === 'listening' ? 'Listening...' : qaState === 'processing' ? 'Processing...' : qaState === 'connecting' ? 'Connecting...' : '')}
          </p>
        </div>

        {/* Text Input Row */}
        {isStarted && (
          <div className={styles.textInputContainer}>
            <input
              type="text"
              className={styles.textInput}
              placeholder="Type here..."
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

        <div style={{ display: 'flex', gap: '16px', marginTop: '24px', justifyContent: 'center' }}>
          <button
            className="btn btn-secondary"
            style={{
              borderRadius: '99px',
              padding: '10px 24px',
              color: '#ef4444',
              borderColor: 'rgba(239, 68, 68, 0.2)',
              background: 'rgba(239, 68, 68, 0.05)',
              fontSize: '0.875rem',
              fontWeight: 600,
              cursor: 'pointer',
              transition: 'all 0.2s'
            }}
            onClick={() => {
              if (voiceSessionRef.current) {
                voiceSessionRef.current.disconnect();
              }
              setIsStarted(false);
              setQaState('idle');
              router.push('/dashboard');
            }}
          >
            ⏹️ Cancel Onboarding
          </button>
        </div>
      </div>
    );
  };

  // Render Video Capture UI
  const renderVideoUI = () => {
    const meta = DOCUMENT_METADATA[documentId] || { label: 'Workplace Video', icon: '📹' };
    const docData = docs[documentId];

    return (
      <div className={styles.detailCard}>
        <div className={styles.cardHeader}>
          <div className={styles.cardIconLarge}>📹</div>
          <div style={{ flex: 1 }}>
            <h3 className={styles.cardTitle}>Record {meta.label}</h3>
            <p className={styles.cardDesc}>Show your workplace for verification</p>
          </div>
        </div>

        <div className={styles.videoContainer}>
          {/* 1. Live Video Stream / Geolocation Warning */}
          {!docData && (
            locationPermissionState === 'denied' ? (
              <div style={{
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                height: '100%',
                width: '100%',
                padding: '24px',
                textAlign: 'center',
                backgroundColor: 'rgba(239, 68, 68, 0.05)',
                color: '#fca5a5'
              }}>
                <span style={{ fontSize: '3rem', marginBottom: '16px' }}>📍</span>
                <h3 style={{ fontSize: '1.25rem', fontWeight: 700, marginBottom: '8px', color: '#fff' }}>Location Permission Required</h3>
                <p style={{ fontSize: '0.875rem', color: '#cbd5e1', marginBottom: '24px', maxWidth: '380px', lineHeight: '1.5' }}>
                  This micro-loan application requires a geotagged video of your workplace. Please enable location permissions for this website in your browser settings and try again.
                </p>
                <button 
                  onClick={async () => {
                    const granted = await checkLocationPermission();
                    if (granted) {
                      if (!voiceSessionRef.current) {
                        setNodeType('voice-qa');
                        startSession();
                      } else {
                        const meta = DOCUMENT_METADATA[documentId] || {};
                        const facing = meta.facingMode || activeFacingMode;
                        startCamera(facing);
                      }
                    }
                  }}
                  style={{
                    backgroundColor: '#10b981',
                    color: 'white',
                    border: 'none',
                    borderRadius: '99px',
                    padding: '12px 28px',
                    fontWeight: 700,
                    cursor: 'pointer',
                    boxShadow: '0 4px 12px rgba(16, 185, 129, 0.3)',
                    transition: 'transform 0.2s'
                  }}
                >
                  🔄 Retry Location Access
                </button>
              </div>
            ) : (
              <div style={{ position: 'relative', width: '100%', height: '100%', display: 'flex', flexDirection: 'column' }}>
                <video
                  ref={videoRef}
                  autoPlay
                  playsInline
                  muted
                  className={styles.videoElement}
                />
                
                {/* Dynamic Instructions Overlay during recording */}
                {isRecordingVideo && (
                  <div style={{
                    position: 'absolute',
                    top: '16px',
                    left: '16px',
                    right: '16px',
                    backgroundColor: 'rgba(15, 23, 42, 0.85)',
                    color: '#38bdf8',
                    padding: '12px 16px',
                    borderRadius: '12px',
                    fontSize: '0.95rem',
                    fontWeight: 600,
                    textAlign: 'center',
                    backdropFilter: 'blur(8px)',
                    border: '1px solid rgba(56, 189, 248, 0.2)',
                    zIndex: 30
                  }}>
                    📢 {currentInstructionText}
                  </div>
                )}

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
                    disabled={isRecordingVideo}
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
                      cursor: isRecordingVideo ? 'not-allowed' : 'pointer',
                      opacity: isRecordingVideo ? 0.5 : 1,
                      fontSize: '1.25rem',
                      backdropFilter: 'blur(8px)'
                    }}
                    title="Flip Camera"
                  >
                    🔄
                  </button>
                  
                  {!isRecordingVideo ? (
                    <button 
                      onClick={startVideoRecording}
                      style={{
                        backgroundColor: '#10b981',
                        color: 'white',
                        border: 'none',
                        borderRadius: '99px',
                        padding: '0 24px',
                        height: '48px',
                        fontWeight: 700,
                        cursor: 'pointer',
                        boxShadow: '0 4px 12px rgba(16, 185, 129, 0.3)',
                      }}
                    >
                      🔴 Start Recording
                    </button>
                  ) : (
                    <button 
                      onClick={stopVideoRecordingManual}
                      style={{
                        backgroundColor: '#ef4444',
                        color: 'white',
                        border: 'none',
                        borderRadius: '99px',
                        padding: '0 24px',
                        height: '48px',
                        fontWeight: 700,
                        cursor: 'pointer',
                        boxShadow: '0 4px 12px rgba(239, 68, 68, 0.3)',
                      }}
                    >
                      ⏹ Stop ({recordingTimeRemaining}s)
                    </button>
                  )}
                </div>
              </div>
            )
          )}

          {/* 2. Captured Preview Video */}
          {docData && (
            <div style={{ position: 'relative', width: '100%', height: '100%' }}>
              <video 
                src={docData.url} 
                controls
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
                  Retake
                </button>
              </div>
            </div>
          )}

          {/* 3. Uploading Animation Overlay */}
          {verifying && (
            <div className={styles.scanningOverlay}>
              <div className={styles.miniSpinner} />
              <p style={{ marginTop: '12px', fontWeight: 600, color: '#fff' }}>
                Uploading workplace video & geo-tagging details...
              </p>
            </div>
          )}
        </div>

        {errors[documentId] && (
          <div style={{ 
            color: '#ef4444', 
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
      </div>
    );
  };

  // Render Camera UI
  const renderCameraUI = () => {
    const meta = DOCUMENT_METADATA[documentId] || DOCUMENT_METADATA['selfie'];
    const docData = docs[documentId];

    return (
      <div className={styles.detailCard}>
        <div className={styles.cardHeader}>
          <div className={styles.cardIconLarge}>{meta.icon}</div>
          <div style={{ flex: 1 }}>
            <h3 className={styles.cardTitle}>Upload {meta.label}</h3>
            <p className={styles.cardDesc}>Scan with camera or upload a file</p>
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
                  title="Flip Camera"
                >
                  🔄
                </button>
                <button 
                  onClick={handleCapture}
                  style={{
                    backgroundColor: '#4a78ff',
                    color: 'white',
                    border: 'none',
                    borderRadius: '99px',
                    padding: '0 24px',
                    height: '48px',
                    fontWeight: 700,
                    cursor: 'pointer',
                    boxShadow: '0 4px 12px rgba(74, 120, 255, 0.3)',
                    transition: 'transform 0.2s'
                  }}
                >
                  📸 Capture
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
                  Retake
                </button>
              </div>
            </div>
          )}

          {/* 3. Scanning Animation Overlay */}
          {verifying && (
            <div className={styles.scanningOverlay}>
              <div className={styles.scanLine} />
              <div className={styles.miniSpinner} />
              <p style={{ marginTop: '12px', fontWeight: 600, color: '#fff' }}>
                AI is verifying the document...
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
              📁 Choose File
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
            color: '#ef4444', 
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
            <strong>Tips:</strong>
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

  const renderManualFillingPromptUI = () => {
    return (
      <div className={styles.promptCardContainer}>
        <div className={styles.promptHeader}>
          <div className={styles.promptIconLarge}>📝</div>
          <h2 className={styles.promptTitle}>Choose How to Complete Your Application</h2>
          <p className={styles.promptDesc}>
            Voter ID documents verified successfully! You can either fill out the remaining details manually in a simple table, or continue speaking with our AI Voice Assistant.
          </p>
        </div>

        <div className={styles.promptChoicesGrid}>
          {/* Choice 1: Manual Filling */}
          <div 
            className={`${styles.choiceCard} ${styles.choiceCardManual}`}
            onClick={handleOpenManualFillingModal}
          >
            <div className={styles.choiceIcon} style={{ color: '#22c968' }}>✍️</div>
            <div className={styles.choiceTitle}>Fill Form Manually</div>
            <div className={styles.choiceDesc}>
              Open auto-filled form table with extracted details and complete remaining fields yourself.
            </div>
          </div>

          {/* Choice 2: Continue Voice */}
          <div 
            className={styles.choiceCard}
            onClick={handleContinueWithVoiceAssistant}
          >
            <div className={styles.choiceIcon} style={{ color: '#818cf8' }}>🎙️</div>
            <div className={styles.choiceTitle}>Continue with AI Voice Assistant</div>
            <div className={styles.choiceDesc}>
              Keep speaking naturally with our AI assistant to complete questions step-by-step.
            </div>
          </div>
        </div>
      </div>
    );
  };

  return (
    <div className={styles.container}>
      {/* ─── Header ─── */}
      <header className={styles.header} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '16px 24px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', fontWeight: 700, fontSize: '1.25rem' }}>
          <svg width="28" height="32" viewBox="0 0 36 40" fill="none">
            <path d="M18 0L36 34H27L18 16L9 34H0L18 0Z" fill="url(#hdr-lg)"/>
            <path d="M18 10L25 25H11L18 10Z" fill="#0f172a" stroke="#4a78ff" strokeWidth="0.8"/>
            <circle cx="18" cy="18" r="2" fill="#4a78ff"/>
            <defs>
              <linearGradient id="hdr-lg" x1="0" y1="0" x2="36" y2="40">
                <stop stopColor="#4a78ff"/>
                <stop offset="1" stopColor="#22c968"/>
              </linearGradient>
            </defs>
          </svg>
          <span>Augmen.io — Mudra Micro-Loan Portal</span>
        </div>

        {/* Multi-Language Selector Parameter (Hindi / English / French) — Collapses into locked badge after start */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span style={{ fontSize: '0.8125rem', color: '#94a3b8', fontWeight: 600, transition: 'all 0.3s ease' }}>
            {isStarted ? 'Session Language:' : 'Voice Language:'}
          </span>
          <div style={{
            display: 'flex',
            alignItems: 'center',
            gap: isStarted ? '0px' : '4px',
            backgroundColor: 'rgba(30, 41, 59, 0.6)',
            padding: '4px',
            borderRadius: '10px',
            border: isStarted ? '1px solid rgba(74, 120, 255, 0.3)' : '1px solid rgba(255,255,255,0.1)',
            transition: 'all 0.5s cubic-bezier(0.16, 1, 0.3, 1)',
            boxShadow: isStarted ? '0 0 12px rgba(74, 120, 255, 0.15)' : 'none',
          }}>
            {[
              { code: 'hi', label: 'Hindi', flag: '🇮🇳' },
              { code: 'en', label: 'English', flag: '🇬🇧' },
              { code: 'fr', label: 'French', flag: '🇫🇷' },
              { code: 'ar', label: 'Arabic', flag: '🇸🇦' },
            ].map((lang) => {
              const isSelected = selectedLanguage === lang.code;
              const isHidden = isStarted && !isSelected;

              return (
                <button
                  key={lang.code}
                  type="button"
                  disabled={isStarted}
                  onClick={() => {
                    if (!isStarted) {
                      setSelectedLanguage(lang.code);
                    }
                  }}
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: '6px',
                    padding: isHidden ? '0px' : '4px 12px',
                    maxWidth: isHidden ? '0px' : '120px',
                    opacity: isHidden ? 0 : 1,
                    transform: isHidden ? 'scale(0.8)' : 'scale(1)',
                    overflow: 'hidden',
                    borderRadius: '6px',
                    border: 'none',
                    fontSize: '0.8125rem',
                    fontWeight: isSelected ? 700 : 500,
                    backgroundColor: isSelected ? '#4a78ff' : 'transparent',
                    color: isSelected ? '#ffffff' : '#94a3b8',
                    cursor: isStarted ? 'default' : 'pointer',
                    transition: 'all 0.5s cubic-bezier(0.16, 1, 0.3, 1)',
                    whiteSpace: 'nowrap',
                    pointerEvents: isStarted ? 'none' : 'auto',
                  }}
                >
                  {isStarted && isSelected && (
                    <span style={{ fontSize: '0.75rem', opacity: 0.9 }}>🔒</span>
                  )}
                  <span>{lang.label}</span>
                  {isStarted && isSelected && (
                    <span style={{
                      width: '6px',
                      height: '6px',
                      borderRadius: '50%',
                      backgroundColor: '#22c968',
                      boxShadow: '0 0 6px #22c968',
                      display: 'inline-block',
                      marginLeft: '2px',
                    }} />
                  )}
                </button>
              );
            })}
          </div>
        </div>
      </header>

      {/* ─── Global Error and Warning Banners ─── */}
      {errors.global && (
        <div style={{
          backgroundColor: 'rgba(239, 68, 68, 0.1)',
          color: '#f87171',
          padding: '16px',
          margin: '16px',
          borderRadius: '12px',
          display: 'flex',
          alignItems: 'center',
          gap: '12px',
          border: '1px solid rgba(239, 68, 68, 0.2)'
        }}>
          <span style={{ fontSize: '24px' }}>⚠️</span>
          <div>
            <h3 style={{ margin: '0 0 4px 0', fontSize: '16px', fontWeight: 600 }}>System Error</h3>
            <p style={{ margin: 0, fontSize: '14px' }}>{errors.global}</p>
          </div>
        </div>
      )}

      {errors.warning && (
        <div style={{
          backgroundColor: 'rgba(245, 158, 11, 0.1)',
          color: '#fbbf24',
          padding: '16px',
          margin: '16px 16px 0 16px',
          borderRadius: '12px',
          display: 'flex',
          alignItems: 'center',
          gap: '12px',
          border: '1px solid rgba(245, 158, 11, 0.2)'
        }}>
          <span style={{ fontSize: '24px' }}>⚠️</span>
          <div style={{ flex: 1 }}>
            <h3 style={{ margin: '0 0 4px 0', fontSize: '16px', fontWeight: 600 }}>Warning</h3>
            <p style={{ margin: 0, fontSize: '14px' }}>{errors.warning}</p>
          </div>
          <button 
            onClick={() => setErrors(prev => ({ ...prev, warning: null }))}
            style={{
              background: 'none',
              border: 'none',
              color: '#fbbf24',
              fontSize: '18px',
              cursor: 'pointer',
              padding: '4px'
            }}
          >
            ✕
          </button>
        </div>
      )}

      {/* ─── Main Content ─── */}
      <main className={styles.mainGrid}>
        {!isStarted ? (
          /* Pre-connect screen */
          <div style={{
            gridColumn: 'span 2',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            minHeight: '65vh',
            gap: '24px',
            textAlign: 'center',
            maxWidth: '600px',
            margin: '0 auto',
            padding: '20px'
          }}>
            <div style={{
              width: '72px',
              height: '72px',
              borderRadius: '50%',
              background: 'rgba(74, 120, 255, 0.1)',
              border: '1px solid rgba(74, 120, 255, 0.2)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              boxShadow: '0 0 30px rgba(74, 120, 255, 0.15)',
              marginBottom: '8px'
            }}>
              <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#4a78ff" strokeWidth="2" strokeLinecap="round">
                <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
                <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
                <line x1="12" y1="19" x2="12" y2="23" />
                <line x1="8" y1="23" x2="16" y2="23" />
              </svg>
            </div>

            <h2 style={{ fontSize: '2rem', fontWeight: 800, background: 'linear-gradient(135deg, #fff 0%, #a5b4fc 100%)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }}>
              {schemeId.includes('mudra') || schemeId === 'a74b1b43-7cc6-4385-8a8c-12af64cddb2b' 
                ? "Micro-Loan Onboarding & Underwriting" 
                : "Digital Bank Account Onboarding"
              }
            </h2>
            <p style={{ color: '#94a3b8', fontSize: '1rem', lineHeight: '1.6', maxWidth: '480px' }}>
              {schemeId.includes('mudra') || schemeId === 'a74b1b43-7cc6-4385-8a8c-12af64cddb2b'
                ? "Our AI Underwriter will guide you through the Micro-Loan application process. You will be asked to verify documents, answer a few questions, and record a geotagged video of your workplace."
                : "Our AI Assistant will guide you through the savings account opening process. You will be asked to upload documents and answer a few questions. Speak naturally to complete the form."
              }
            </p>



            <button 
              onClick={startSession}
              className={styles.btnNeural}
              data-state="start"
              style={{ marginTop: '16px', minWidth: '220px' }}
            >
              <span>Start Onboarding</span>
              <div className={styles.btnGlow}></div>
            </button>
          </div>
        ) : (
          <div style={{ gridColumn: 'span 2', maxWidth: '800px', margin: '0 auto', width: '100%' }}>
            {nodeType === 'manual_filling_prompt' 
              ? renderManualFillingPromptUI() 
              : (nodeType === 'voice-qa' ? renderVoiceUI() : (nodeType === 'video_capture' ? renderVideoUI() : renderCameraUI()))
            }
          </div>
        )}
      </main>

      {/* Extracted Details Review Pop-up Modal */}
      {showReviewModal && (
        <div className={styles.modalOverlay}>
          <div className={styles.modalContent}>
            
            {/* Modal Header */}
            <div className={styles.modalHeader}>
              <div className={styles.modalTitleWrapper}>
                <h2 className={styles.modalTitle}>
                  <span>📋</span>
                  <span>Review Extracted Application Details</span>
                </h2>
                <p className={styles.modalSubtitle}>
                  Please review your information below. You can edit any field before confirming.
                </p>
              </div>

              {/* Voice Announcement Indicator Chip */}
              <div className={styles.voiceAnnouncementChip}>
                <span style={{ fontSize: '1rem' }}>🔊</span>
                <span>{selectedLanguage === 'hi' ? 'पुष्टि संदेश चल रहा है...' : 'Voice Announcement'}</span>
              </div>
            </div>

            {/* Categorized Editable Sections */}
            <div className={styles.tableContainer}>
              {REVIEW_SECTIONS.map((section) => {
                const sectionKeys = section.keys;
                return (
                  <div key={section.id} className={styles.reviewSectionBlock}>
                    <h3 className={styles.sectionHeaderTitle}>
                      <span>{section.icon}</span>
                      <span>{section.title}</span>
                    </h3>
                    <div className={styles.reviewGrid}>
                      {sectionKeys.map((key) => {
                        const val = reviewFields[key];
                        const label = FRIENDLY_FIELD_LABELS[key] || key.replace(/_/g, ' ').toUpperCase();
                        return (
                          <div key={key} className={styles.reviewRow}>
                            <label className={styles.reviewLabel}>
                              <span>✏️</span>
                              <span>{label}</span>
                            </label>
                            <input
                              type="text"
                              className={styles.reviewInput}
                              value={val || ''}
                              onChange={(e) => handleFieldChange(key, e.target.value)}
                              placeholder={`Enter ${label}...`}
                            />
                          </div>
                        );
                      })}
                    </div>
                  </div>
                );
              })}
            </div>

            {/* Modal Footer Controls */}
            <div className={styles.modalFooter}>
              <button
                onClick={handleSaveAndConfirmReview}
                disabled={isSavingReview}
                className={styles.saveButton}
              >
                <span>{isSavingReview ? '💾 Saving & Calculating...' : '✅ Save & Confirm Details'}</span>
              </button>
            </div>

          </div>
        </div>
      )}
    </div>
  );
}

export default function InterviewPage() {
  return (
    <AuthGuard>
      <InterviewContent />
    </AuthGuard>
  );
}
