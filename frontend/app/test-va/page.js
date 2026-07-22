'use client';

/**
 * Test Voice Assistant Page
 * 
 * EXACT port of the Hindi repo's frontend (app.js + websocket-client.js + 
 * audio-processor.js + visualizer.js) into a single Next.js page component.
 * 
 * The only difference: we connect through the microservice Gateway's WebSocket
 * which requires an auth handshake as the first JSON message, then uses 
 * { signal: "speech_start" / "speech_end" } for control, and streams binary
 * audio chunks directly (not the audio_chunk JSON header approach).
 */

import { useState, useRef, useEffect, useCallback } from 'react';
import styles from './test-va.module.css';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080';
const WS_BASE_URL = process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8080';

// ─── Audio Processing Constants (from Hindi audio-processor.js) ───
const TARGET_SAMPLE_RATE = 16000;
const BUFFER_SIZE = 512;

// ─── CDN Resources (same as Hindi repo) ───
const ORT_CDN = "https://cdn.jsdelivr.net/npm/onnxruntime-web@1.14.0/dist/ort.js";
const VAD_CDN = "https://cdn.jsdelivr.net/npm/@ricky0123/vad-web@0.0.30/dist/bundle.min.js";
const VAD_WORKLET_URL = "https://cdn.jsdelivr.net/npm/@ricky0123/vad-web@0.0.30/dist/vad.worklet.bundle.min.js";
const VAD_MODEL_URL = "https://cdn.jsdelivr.net/npm/@ricky0123/vad-web@0.0.30/dist/silero_vad_v5.onnx";
const ORT_WASM_PATH = "https://cdn.jsdelivr.net/npm/onnxruntime-web@1.14.0/dist/";

// ─── Float32 → Int16 PCM (from Hindi audio-processor.js) ───
function float32ToInt16(float32Array) {
  const bytes = [];
  for (let i = 0; i < float32Array.length; i++) {
    const s = Math.max(-1, Math.min(1, float32Array[i]));
    const val = s < 0 ? s * 0x8000 : s * 0x7FFF;
    const int16 = Math.round(val);
    bytes.push(int16 & 0xFF);
    bytes.push((int16 >> 8) & 0xFF);
  }
  return bytes;
}

// ─── Script Loader ───
function loadScript(src, id) {
  return new Promise((resolve) => {
    if (typeof window === 'undefined') { resolve(); return; }
    if (document.getElementById(id)) { resolve(); return; }
    const script = document.createElement('script');
    script.src = src;
    script.id = id;
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () => resolve();
    document.body.appendChild(script);
  });
}

export default function TestVoiceAssistantPage() {
  // ─── State ───
  const [isRecording, setIsRecording] = useState(false);
  const [isConnected, setIsConnected] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [isUserSpeaking, setIsUserSpeaking] = useState(false);
  const [statusText, setStatusText] = useState('Initialize the Neural Interface');
  const [callActive, setCallActive] = useState(false);
  const [buttonState, setButtonState] = useState('start'); // 'start', 'connecting', 'end'
  const [langDropdownOpen, setLangDropdownOpen] = useState(false);
  const [currentLang, setCurrentLang] = useState('hi');
  const [scriptsLoaded, setScriptsLoaded] = useState(false);
  // Live transcription display
  const [assistantText, setAssistantText] = useState('');
  const [userText, setUserText] = useState('');
  // Orb mode: 'idle' | 'listening' | 'userSpeaking' | 'processing' | 'speaking'
  const [orbMode, setOrbMode] = useState('idle');

  // ─── Refs (mirrors Hindi app.js module-scoped vars) ───
  const wsRef = useRef(null);
  const vadRef = useRef(null);
  const audioContextRef = useRef(null);
  const currentAudioSourceRef = useRef(null);
  const audioQueueRef = useRef([]);
  const isPlayingAudioRef = useRef(false);
  const audioEndReceivedRef = useRef(false);
  const isProcessingRef = useRef(false);
  const isRecordingRef = useRef(false);
  const isUserSpeakingRef = useRef(false);
  const chunkBufferRef = useRef([]);
  const preSpeechBufferRef = useRef([]);
  const canvasRef = useRef(null);
  const visualizerRef = useRef(null);
  const speechEndTimeRef = useRef(null);
  const tokenRef = useRef(null);
  const sessionIdRef = useRef(null);
  const pendingTextRef = useRef('');  // Text received from audio_chunk header, paired with next binary

  // ─── Sync refs with state ───
  useEffect(() => { isRecordingRef.current = isRecording; }, [isRecording]);
  useEffect(() => { isProcessingRef.current = isProcessing; }, [isProcessing]);

  // ─── AudioVisualizer class (from Hindi visualizer.js) ───
  class AudioVisualizer {
    constructor(canvas) {
      this.canvas = canvas;
      this.ctx = canvas.getContext('2d');
      this.animationId = null;
      this.mode = 'idle';
      this.frequencyData = null;
      this.volumeLevel = 0;
      this.time = 0;
      this.bars = [];
      this.initBars();
      this._setupCanvas();
      this._animate();
    }

    initBars() {
      const barCount = 40;
      this.bars = [];
      for (let i = 0; i < barCount; i++) {
        this.bars.push({ height: 0, targetHeight: 0, velocity: 0 });
      }
    }

    _setupCanvas() {
      const dpr = window.devicePixelRatio || 1;
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

    setMode(mode) { this.mode = mode; }

    _animate() {
      this.time += 0.016;
      this.ctx.clearRect(0, 0, this.width, this.height);
      switch (this.mode) {
        case 'recording': this._drawRecording(); break;
        case 'processing': this._drawProcessing(); break;
        case 'speaking': this._drawSpeaking(); break;
        default: this._drawIdle();
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
        this.ctx.roundRect(x, centerY - h / 2, barWidth, h, 1.5);
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
        this.ctx.roundRect(x, centerY - h / 2, barWidth, h, 2);
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
        const wave = Math.sin(this.time * 3 + i * 0.2) * 8 + 10;
        const alpha = 0.3 + Math.sin(this.time * 2 + i * 0.15) * 0.2;
        this.bars[i].height += (wave - this.bars[i].height) * 0.08;
        const h = this.bars[i].height;
        const t = (Math.sin(this.time * 2 + i * 0.1) + 1) / 2;
        const r = Math.floor(167 * (1 - t) + 244 * t);
        const g = Math.floor(139 * (1 - t) + 114 * t);
        const b = Math.floor(250 * (1 - t) + 182 * t);
        this.ctx.fillStyle = `rgba(${r}, ${g}, ${b}, ${alpha})`;
        this.ctx.beginPath();
        this.ctx.roundRect(x, centerY - h / 2, barWidth, h, 1.5);
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
        this.ctx.roundRect(x, centerY - h / 2, barWidth, h, 2);
        this.ctx.fill();
      }
    }

    destroy() {
      if (this.animationId) cancelAnimationFrame(this.animationId);
    }
  }

  // ─── Load CDN Scripts (same as Hindi repo) ───
  useEffect(() => {
    async function loadScripts() {
      await loadScript(ORT_CDN, 'ort-script');
      await loadScript(VAD_CDN, 'vad-script');
      if (window.ort && window.vad) {
        setScriptsLoaded(true);
        console.log('[TestVA] ONNX + VAD scripts loaded.');
      } else {
        console.error('[TestVA] Failed to load VAD/ONNX scripts.');
      }
    }
    loadScripts();
  }, []);

  // ─── Initialize Visualizer ───
  useEffect(() => {
    if (canvasRef.current && !visualizerRef.current) {
      visualizerRef.current = new AudioVisualizer(canvasRef.current);
    }
    return () => {
      if (visualizerRef.current) {
        visualizerRef.current.destroy();
        visualizerRef.current = null;
      }
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // ─── Fetch test token from Gateway ───
  const fetchTestToken = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/api/auth/test-token`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      tokenRef.current = data.token;
      sessionIdRef.current = data.session_id;
      console.log(`[TestVA] Token fetched (session: ${data.session_id.substring(0, 8)}...)`);
      return data;
    } catch (err) {
      console.error('[TestVA] Failed to fetch test token:', err);
      return null;
    }
  }, []);

  // ─── Audio Playback Queue (from Hindi app.js — exact pattern) ───
  const playNextAudioChunk = useCallback(() => {
    if (isPlayingAudioRef.current) return;

    if (audioQueueRef.current.length === 0) {
      if (audioEndReceivedRef.current) {
        finalizeSpeakingTurn();
      }
      return;
    }

    const chunk = audioQueueRef.current.shift();
    isPlayingAudioRef.current = true;
    setIsSpeaking(true);

    // Display the chunk text or fallback (exact Hindi pattern)
    if (chunk.text && chunk.text.trim().length > 0) {
      setAssistantText(chunk.text);
    }

    if (visualizerRef.current) visualizerRef.current.setMode('speaking');

    if (!audioContextRef.current) {
      audioContextRef.current = new (window.AudioContext || window.webkitAudioContext)();
    }
    if (audioContextRef.current.state === 'suspended') {
      audioContextRef.current.resume();
    }

    const bufferCopy = chunk.buffer.slice(0);
    audioContextRef.current.decodeAudioData(
      bufferCopy,
      (decodedData) => {
        const source = audioContextRef.current.createBufferSource();
        source.buffer = decodedData;
        source.connect(audioContextRef.current.destination);
        currentAudioSourceRef.current = source;

        source.onended = () => {
          if (currentAudioSourceRef.current === source) {
            currentAudioSourceRef.current = null;
          }
          isPlayingAudioRef.current = false;
          playNextAudioChunk();
        };
        source.start(0);
      },
      (error) => {
        console.error('[TestVA] Error decoding audio:', error);
        isPlayingAudioRef.current = false;
        playNextAudioChunk();
      }
    );
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // ─── Finalize Speaking Turn (from Hindi app.js) ───
  const finalizeSpeakingTurn = useCallback(() => {
    setIsSpeaking(false);
    isPlayingAudioRef.current = false;
    audioEndReceivedRef.current = false;
    setIsProcessing(false);
    isProcessingRef.current = false;

    if (isRecordingRef.current) {
      if (visualizerRef.current) visualizerRef.current.setMode('recording');
      setStatusText('Listening...');
      setOrbMode('listening');

      // FIX from Hindi app.js: If user started speaking while audio was playing,
      // fire a delayed speech_start
      if (isUserSpeakingRef.current) {
        console.log('[TestVA] User is already speaking! Firing delayed speech_start');
        wsRef.current?.send(JSON.stringify({ signal: 'speech_start' }));
        setOrbMode('userSpeaking');
      }
    } else {
      if (visualizerRef.current) visualizerRef.current.setMode('idle');
      setStatusText('Call Ended');
      setOrbMode('idle');
    }
  }, []);

  // ─── Stop Audio Playback (from Hindi app.js) ───
  const stopAudioPlayback = useCallback(() => {
    if (currentAudioSourceRef.current) {
      try {
        currentAudioSourceRef.current.onended = null;
        currentAudioSourceRef.current.stop();
      } catch (e) {}
      currentAudioSourceRef.current = null;
    }
    audioQueueRef.current = [];
    pendingTextRef.current = '';
    isPlayingAudioRef.current = false;
    audioEndReceivedRef.current = false;
  }, []);

  // ─── WebSocket Message Handler (mirrors Hindi websocket-client.js) ───
  const handleWsMessage = useCallback((event) => {
    if (event.data instanceof ArrayBuffer) {
      // Binary audio chunk — pair with pending text from audio_chunk header
      if (speechEndTimeRef.current) {
        const firstChunkTime = performance.now();
        const diff = firstChunkTime - speechEndTimeRef.current;
        console.log(`[LATENCY] First audio chunk: ${(diff / 1000).toFixed(2)}s`);
        speechEndTimeRef.current = null;
      }

      // Push paired {buffer, text} to queue (exact Hindi pattern)
      audioQueueRef.current.push({
        buffer: event.data,
        text: pendingTextRef.current
      });
      pendingTextRef.current = '';  // Reset after pairing
      playNextAudioChunk();
      return;
    }

    // JSON text message
    try {
      const data = JSON.parse(event.data);

      if (data.error) {
        console.error('[TestVA] Server error:', data.error);
        setStatusText(`Error: ${data.error}`);
        return;
      }

      switch (data.type) {
        case 'status':
          if (data.status === 'connected') {
            setIsConnected(true);
            console.log('[TestVA] Connected to voice engine');
          } else if (data.status === 'listening') {
            if (!isPlayingAudioRef.current) {
              setIsProcessing(false);
              isProcessingRef.current = false;
              setIsSpeaking(false);
              if (isRecordingRef.current) {
                setStatusText('Listening...');
                setOrbMode('listening');
                if (visualizerRef.current) visualizerRef.current.setMode('recording');
              }
            }
          } else if (data.status === 'processing') {
            setIsProcessing(true);
            isProcessingRef.current = true;
            setStatusText('Processing...');
            setOrbMode('processing');
            if (visualizerRef.current) visualizerRef.current.setMode('processing');
          } else if (data.status === 'speaking') {
            setIsSpeaking(true);
            setOrbMode('speaking');
            if (visualizerRef.current) visualizerRef.current.setMode('speaking');
          } else if (data.status === 'stopped') {
            setStatusText('Call Ended');
            setOrbMode('idle');
          }
          break;

        case 'transcription':
          // User's final STT transcription (is_final=true)
          setUserText(data.text);
          console.log(`[TestVA] User said: "${data.text}"`);
          break;

        case 'audio_chunk':
          // JSON header before binary audio (exact Hindi pattern)
          // Store text — will be paired with next binary message
          pendingTextRef.current = data.text || '';
          console.log(`[TestVA] Audio chunk header: "${data.text || ''}"`);
          break;

        case 'audio_end':
          audioEndReceivedRef.current = true;
          if (!isPlayingAudioRef.current && audioQueueRef.current.length === 0) {
            finalizeSpeakingTurn();
          }
          break;

        case 'progress':
          console.log(`[TestVA] Progress: step ${data.current_step}/${data.total_steps} — node: ${data.current_node_id}`);
          break;

        case 'extraction':
          console.log(`[TestVA] Extraction:`, data.json_fields);
          break;

        case 'complete':
          console.log('[TestVA] Interview complete!', data);
          setStatusText('Interview Complete!');
          setOrbMode('idle');
          break;

        case 'error':
          console.error('[TestVA] Error:', data.message);
          setStatusText(`Error: ${data.message}`);
          break;

        default:
          console.warn('[TestVA] Unknown message type:', data.type);
      }
    } catch (err) {
      console.error('[TestVA] Failed to parse message:', err);
    }
  }, [playNextAudioChunk, finalizeSpeakingTurn]);

  // ─── Start Call (mirrors Hindi app.js startCall) ───
  const startCall = useCallback(async () => {
    if (!scriptsLoaded) {
      setStatusText('VAD scripts not loaded yet...');
      return;
    }

    stopAudioPlayback();
    setStatusText('Connecting...');
    setButtonState('connecting');

    // Fetch auth token
    let token = tokenRef.current;
    let sid = sessionIdRef.current;
    if (!token || !sid) {
      const creds = await fetchTestToken();
      if (!creds) {
        setStatusText('Failed to get auth token');
        setButtonState('start');
        return;
      }
      token = creds.token;
      sid = creds.session_id;
    }

    // Initialize VAD (from Hindi audio-processor.js initialize())
    if (!vadRef.current) {
      try {
        if (window.ort && window.ort.env) {
          window.ort.env.wasm.wasmPaths = ORT_WASM_PATH;
        }

        vadRef.current = await window.vad.MicVAD.new({
          workletURL: VAD_WORKLET_URL,
          modelURL: VAD_MODEL_URL,
          model: "v5",
          positiveSpeechThreshold: 0.45,
          negativeSpeechThreshold: 0.35,
          minSpeechFrames: 1,
          preSpeechPadFrames: 20,
          redemptionFrames: 12,
          additionalAudioConstraints: {
            echoCancellation: true,
            noiseSuppression: false,
            autoGainControl: true,
          },

          onSpeechStart: () => {
            console.log('[VAD] Speech started');
            isUserSpeakingRef.current = true;
            setIsUserSpeaking(true);
            setOrbMode('userSpeaking');
            chunkBufferRef.current = [...preSpeechBufferRef.current];
            preSpeechBufferRef.current = [];

            if (isRecordingRef.current && !isPlayingAudioRef.current && !isProcessingRef.current) {
              wsRef.current?.send(JSON.stringify({ signal: 'speech_start' }));
              setStatusText('Listening...');
              setAssistantText('');
              pendingTextRef.current = '';
              if (visualizerRef.current) visualizerRef.current.setMode('recording');
            }
          },

          onSpeechEnd: () => {
            console.log('[VAD] Speech ended');
            isUserSpeakingRef.current = false;
            setIsUserSpeaking(false);

            speechEndTimeRef.current = performance.now();
            console.log(`[LATENCY] User stopped speaking at: ${speechEndTimeRef.current.toFixed(2)}ms`);

            if (isRecordingRef.current && !isPlayingAudioRef.current && !isProcessingRef.current) {
              // Flush remaining chunks
              if (chunkBufferRef.current.length > 0) {
                const chunk = new Uint8Array(chunkBufferRef.current);
                wsRef.current?.send(chunk.buffer);
                chunkBufferRef.current = [];
              }
              wsRef.current?.send(JSON.stringify({ signal: 'speech_end' }));
              setIsProcessing(true);
              isProcessingRef.current = true;
              setStatusText('Processing...');
              setOrbMode('processing');
              if (visualizerRef.current) visualizerRef.current.setMode('processing');
            }
          },

          onFrameProcessed: (probabilities, frame) => {
            if (!isRecordingRef.current) return;

            // Volume level for visualizer
            let sum = 0;
            for (let i = 0; i < frame.length; i++) sum += Math.abs(frame[i]);
            const avgVolume = sum / frame.length;
            if (visualizerRef.current && isRecordingRef.current) {
              visualizerRef.current.updateAudioData(null, Math.min(1, avgVolume * 5));
            }

            // PCM conversion (from Hindi audio-processor.js)
            const pcmData = float32ToInt16(frame);

            if (isUserSpeakingRef.current) {
              chunkBufferRef.current.push(...pcmData);
              while (chunkBufferRef.current.length >= BUFFER_SIZE * 2) {
                const chunk = new Uint8Array(
                  chunkBufferRef.current.splice(0, BUFFER_SIZE * 2)
                );
                if (wsRef.current?.readyState === WebSocket.OPEN &&
                    !isPlayingAudioRef.current && !isProcessingRef.current) {
                  wsRef.current.send(chunk.buffer);
                }
              }
            } else {
              // Pre-speech buffer (from Hindi audio-processor.js)
              preSpeechBufferRef.current.push(...pcmData);
              const maxPreSpeechSamples = frame.length * 40;
              if (preSpeechBufferRef.current.length > maxPreSpeechSamples) {
                preSpeechBufferRef.current.splice(
                  0, preSpeechBufferRef.current.length - maxPreSpeechSamples
                );
              }
            }
          },
        });

        console.log('[TestVA] MicVAD initialized successfully.');
      } catch (err) {
        console.error('[TestVA] VAD init failed:', err);
        setStatusText('Microphone access denied');
        setButtonState('start');
        return;
      }
    }

    // Connect WebSocket (mirrors Hindi websocket-client.js connect())
    const wsUrl = `${WS_BASE_URL.replace('http', 'ws')}/ws/voice`;
    console.log(`[TestVA] Connecting WebSocket: ${wsUrl}`);

    const ws = new WebSocket(wsUrl);
    ws.binaryType = 'arraybuffer';
    wsRef.current = ws;

    ws.onopen = () => {
      console.log('[TestVA] WebSocket connected, sending auth...');
      // First message = auth (microservice protocol)
      ws.send(JSON.stringify({
        token: token,
        scheme_id: 'mudra-clothing',
        session_id: sid,
        language: currentLang,
        applicant_name: 'केशव',
        application_id: ''
      }));
    };

    ws.onmessage = handleWsMessage;

    ws.onerror = (err) => {
      console.error('[TestVA] WebSocket error:', err);
      setStatusText('Connection Error');
    };

    ws.onclose = (event) => {
      console.log(`[TestVA] WebSocket closed: code=${event.code}`);
      setIsConnected(false);
    };

    // Wait for connection (same pattern as Hindi app.js)
    await new Promise(resolve => setTimeout(resolve, 1500));

    if (ws.readyState !== WebSocket.OPEN) {
      setStatusText('Connection Failed');
      setButtonState('start');
      return;
    }

    // Start recording
    setIsRecording(true);
    isRecordingRef.current = true;
    vadRef.current.start();

    // UI Updates
    setButtonState('end');
    setCallActive(true);
    setStatusText('Listening...');
    setOrbMode('listening');
    setAssistantText('');
    setUserText('');
    if (visualizerRef.current) visualizerRef.current.setMode('recording');

  }, [scriptsLoaded, currentLang, fetchTestToken, stopAudioPlayback, handleWsMessage]);

  // ─── Stop Call (mirrors Hindi app.js stopCall) ───
  const stopCall = useCallback(() => {
    setIsRecording(false);
    isRecordingRef.current = false;

    // Stop VAD
    if (vadRef.current) {
      vadRef.current.pause();
    }

    stopAudioPlayback();

    // Send stop signal and close WS
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ signal: 'stop' }));
      wsRef.current.close();
    }
    wsRef.current = null;

    // Reset state
    setIsConnected(false);
    setIsProcessing(false);
    isProcessingRef.current = false;
    setIsSpeaking(false);
    setIsUserSpeaking(false);
    isUserSpeakingRef.current = false;
    chunkBufferRef.current = [];
    preSpeechBufferRef.current = [];
    tokenRef.current = null;
    sessionIdRef.current = null;

    // UI Updates
    setButtonState('start');
    setCallActive(false);
    setStatusText('Call Ended');
    setOrbMode('idle');
    setAssistantText('');
    setUserText('');
    if (visualizerRef.current) visualizerRef.current.setMode('idle');
  }, [stopAudioPlayback]);

  // ─── Toggle Call (mirrors Hindi app.js toggleCall) ───
  const toggleCall = useCallback(() => {
    if (isRecording) {
      stopCall();
    } else {
      startCall();
    }
  }, [isRecording, startCall, stopCall]);

  // ─── Keyboard shortcut (Space to toggle — same as Hindi) ───
  useEffect(() => {
    const handler = (e) => {
      if (e.code === 'Space' && e.target === document.body) {
        e.preventDefault();
        toggleCall();
      }
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [toggleCall]);

  // ─── Close lang dropdown when clicking outside ───
  useEffect(() => {
    const handler = (e) => {
      if (langDropdownOpen) setLangDropdownOpen(false);
    };
    document.addEventListener('click', handler);
    return () => document.removeEventListener('click', handler);
  }, [langDropdownOpen]);

  // ─── Cleanup on unmount ───
  useEffect(() => {
    return () => {
      if (vadRef.current) {
        try { vadRef.current.destroy(); } catch (e) {}
        vadRef.current = null;
      }
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
      if (audioContextRef.current && audioContextRef.current.state !== 'closed') {
        try { audioContextRef.current.close(); } catch (e) {}
        audioContextRef.current = null;
      }
    };
  }, []);

  // ─── Language options ───
  const languages = [
    { code: 'hi', label: 'हिंदी (Hindi)' },
    { code: 'en', label: 'English' },
    { code: 'ta', label: 'தமிழ் (Tamil)' },
    { code: 'te', label: 'తెలుగు (Telugu)' },
    { code: 'ar', label: 'العربية (Arabic)' },
  ];

  const selectedLangLabel = languages.find(l => l.code === currentLang)?.label || 'हिंदी (Hindi)';

  // ─── Button CSS classes ───
  const getButtonClasses = () => {
    const base = styles.btnCall;
    switch (buttonState) {
      case 'connecting': return `${base} ${styles.btnConnecting}`;
      case 'end': return `${base} ${styles.btnEnd}`;
      default: return `${base} ${styles.btnStart}`;
    }
  };

  const getButtonText = () => {
    switch (buttonState) {
      case 'connecting': return 'Connecting...';
      case 'end': return 'End Call';
      default: return 'Initiate Connection';
    }
  };

  // ─── Orb CSS classes based on mode ───
  const getSphereClass = () => {
    switch (orbMode) {
      case 'listening': return styles.coreSphereListening;
      case 'userSpeaking': return styles.coreSphereUserSpeaking;
      case 'speaking': return styles.coreSphereSpeaking;
      case 'processing': return styles.coreSphereProcessing;
      default: return '';
    }
  };

  const getGlowClass = () => {
    switch (orbMode) {
      case 'listening': return styles.coreGlowListening;
      case 'userSpeaking': return styles.coreGlowUserSpeaking;
      case 'speaking': return styles.coreGlowSpeaking;
      case 'processing': return styles.coreGlowProcessing;
      default: return '';
    }
  };

  const getRingClass = (ringNum) => {
    const modeMap = {
      'listening': { 1: styles.ring1Listening, 2: styles.ring2Listening, 3: styles.ring3Listening },
      'userSpeaking': { 1: styles.ring1Listening, 2: styles.ring2Listening, 3: styles.ring3Listening },
      'speaking': { 1: styles.ring1Speaking, 2: styles.ring2Speaking, 3: styles.ring3Speaking },
      'processing': { 1: styles.ring1Processing, 2: styles.ring2Processing, 3: styles.ring3Processing },
    };
    return modeMap[orbMode]?.[ringNum] || (callActive ? styles[`ring${ringNum}Active`] : '');
  };

  // ─── Render (mirrors Hindi index.html structure 1:1) ───
  return (
    <div className={styles.callContainer}>
      {/* Background Glows */}
      <div className={styles.heroGlow} />

      {/* Top Bar */}
      <div className={styles.topBar}>
        {/* Language Selector */}
        <div
          className={styles.langSelector}
          onClick={(e) => {
            e.stopPropagation();
            if (!isRecording) setLangDropdownOpen(!langDropdownOpen);
          }}
          style={{ cursor: isRecording ? 'not-allowed' : 'pointer' }}
        >
          <span>{selectedLangLabel}</span>
          <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="6 9 12 15 18 9" />
          </svg>

          <ul className={`${styles.langOptions} ${langDropdownOpen ? styles.langOptionsOpen : ''}`}>
            {languages.map((lang) => (
              <li
                key={lang.code}
                className={`${styles.langOption} ${currentLang === lang.code ? styles.langOptionSelected : ''}`}
                onClick={(e) => {
                  e.stopPropagation();
                  setCurrentLang(lang.code);
                  setLangDropdownOpen(false);
                }}
              >
                {lang.label}
              </li>
            ))}
          </ul>
        </div>

        {/* Connection Indicator */}
        <div className={styles.connectionIndicator}>
          <span className={`${styles.connectionDot} ${isConnected ? styles.connectionDotConnected : ''}`} />
          <span className={styles.connectionText}>
            {isConnected ? 'Connected' : 'Standby'}
          </span>
        </div>
      </div>

      {/* The "Neural Core" Interface */}
      <div className={styles.callCenter}>
        <div className={styles.heroH1Wrapper}>
          <h1 className={styles.heroH1}>
            Mudra <span className={styles.heroLangWord}>AI</span>
          </h1>
          <div className={`${styles.callStatus} ${callActive ? styles.callStatusActive : ''}`}
               style={{
                 color: orbMode === 'speaking' ? '#22C968' :
                        orbMode === 'processing' ? '#A78BFA' :
                        orbMode === 'userSpeaking' ? '#4A78FF' :
                        orbMode === 'listening' ? '#A1A1AA' : undefined,
                 textShadow: orbMode === 'speaking' ? '0 0 10px rgba(34,201,104,0.3)' :
                             orbMode === 'processing' ? '0 0 10px rgba(167,139,250,0.3)' :
                             orbMode === 'userSpeaking' ? '0 0 10px rgba(74,120,255,0.3)' : 'none',
                 transition: 'color 0.4s ease, text-shadow 0.4s ease'
               }}>
            {(orbMode === 'speaking' && assistantText) ? assistantText : statusText}
          </div>
        </div>

        <div className={styles.neuralCoreWrapper}>
          {/* Orbiting Rings */}
          <div className={`${styles.coreRing} ${styles.ring1} ${getRingClass(1)}`} />
          <div className={`${styles.coreRing} ${styles.ring2} ${getRingClass(2)}`} />
          <div className={`${styles.coreRing} ${styles.ring3} ${getRingClass(3)}`} />

          {/* The Core Sphere */}
          <div className={`${styles.coreSphere} ${getSphereClass()}`}>
            <div className={`${styles.coreGlowInner} ${getGlowClass()}`} />
            <svg viewBox="0 0 40 40" fill="none" className={styles.aiLogo}>
              <circle cx="20" cy="20" r="18" stroke="rgba(255,255,255,0.8)" strokeWidth="2"/>
              <path d="M14 20C14 16.6863 16.6863 14 20 14C23.3137 14 26 16.6863 26 20" stroke="rgba(255,255,255,0.8)" strokeWidth="2" strokeLinecap="round"/>
              <circle cx="20" cy="24" r="2" fill="rgba(255,255,255,0.8)"/>
            </svg>
          </div>

          {/* Integrated Visualizer */}
          <div className={`${styles.visualizerWrapper} ${callActive ? styles.visualizerWrapperActive : ''}`}>
            <canvas ref={canvasRef} width="300" height="300" style={{ width: '100%', height: '100%' }} />
          </div>
        </div>
      </div>

      {/* Bottom Controls */}
      <div className={styles.callControls}>
        <button
          className={getButtonClasses()}
          onClick={toggleCall}
          disabled={buttonState === 'connecting'}
        >
          <span className={styles.btnText}>{getButtonText()}</span>
          <div className={styles.btnGlow} />
        </button>
      </div>

      {/* Hidden audio element (for compatibility) */}
      <audio id="audioPlayer" style={{ display: 'none' }} />
    </div>
  );
}
