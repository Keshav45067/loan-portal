// Client-side Voice Assistant Helper
// Handles CDN script loading, WebSocket bridge, client VAD, and Web Audio Queue.
// Designed for resilience: retries CDN loads, validates globals, and guards all audio operations.

export function floatTo16BitPCM(float32Array) {
  const buffer = new ArrayBuffer(float32Array.length * 2);
  const view = new DataView(buffer);
  for (let i = 0; i < float32Array.length; i++) {
    const s = Math.max(-1, Math.min(1, float32Array[i]));
    view.setInt16(i * 2, s < 0 ? s * 0x8000 : s * 0x7FFF, true);
  }
  return buffer;
}

export function unlockAudioContext() {
  if (typeof window === 'undefined') return;
  window.globalAudioContext = window.globalAudioContext || new (window.AudioContext || window.webkitAudioContext)();
  const ctx = window.globalAudioContext;
  if (ctx.state === 'suspended') {
    try { ctx.resume(); } catch (e) {}
  }
  // Play a silent 0.1s buffer to fully wake up the audio hardware
  const buffer = ctx.createBuffer(1, ctx.sampleRate * 0.1, ctx.sampleRate);
  const source = ctx.createBufferSource();
  source.buffer = buffer;
  source.connect(ctx.destination);
  source.start(0);
}

// ─── CDN Script Loader with Retries ───
// The single biggest source of instability was CDN loads silently failing.
// Now we: (1) actually reject on error, (2) retry up to 3 times with backoff,
// (3) validate that the expected global object exists after load.

if (typeof window !== 'undefined') {
  window._vadLoadingPromises = window._vadLoadingPromises || {};
}

function loadSingleScript(src, id, expectedGlobal) {
  if (typeof window !== 'undefined' && window[expectedGlobal]) {
    return Promise.resolve();
  }

  if (window._vadLoadingPromises && window._vadLoadingPromises[id]) {
    return window._vadLoadingPromises[id];
  }

  const p = new Promise((resolve, reject) => {
    const existing = document.getElementById(id);
    if (existing) {
      existing.addEventListener('load', () => {
        if (window[expectedGlobal]) resolve();
        else reject(new Error(`window.${expectedGlobal} is still undefined after load`));
      });
      existing.addEventListener('error', () => reject(new Error(`Failed to load script: ${src}`)));
      return;
    }
    const script = document.createElement('script');
    script.src = src;
    script.id = id;
    script.async = true;
    script.crossOrigin = "anonymous";
    script.onload = () => {
      if (window[expectedGlobal]) {
        resolve();
      } else {
        reject(new Error(`Script ${id} loaded but window.${expectedGlobal} is still undefined`));
      }
    };
    script.onerror = () => {
      reject(new Error(`Failed to load script: ${src}`));
    };
    document.body.appendChild(script);
  });

  window._vadLoadingPromises[id] = p;

  return p.catch((err) => {
    delete window._vadLoadingPromises[id];
    const existing = document.getElementById(id);
    if (existing) existing.remove();
    throw err;
  });
}

async function loadWithRetry(src, id, expectedGlobal, maxRetries = 3) {
  for (let attempt = 1; attempt <= maxRetries; attempt++) {
    try {
      await loadSingleScript(src, id, expectedGlobal);
      return true;
    } catch (err) {
      console.warn(`[voiceHelper] Attempt ${attempt}/${maxRetries} failed for ${id}: ${err.message}`);
      if (attempt < maxRetries) {
        // Exponential backoff: 500ms, 1000ms, 2000ms
        await new Promise(r => setTimeout(r, 500 * Math.pow(2, attempt - 1)));
      }
    }
  }
  return false;
}

export async function loadVADScripts() {
  if (typeof window === 'undefined') return false;

  // Already fully loaded and validated
  if (window.ort && window.vad && window.vad.MicVAD) {
    return true;
  }

  const ortLoaded = await loadWithRetry(
    "https://cdn.jsdelivr.net/npm/onnxruntime-web@1.14.0/dist/ort.js",
    "ort-script",
    "ort"
  );

  if (!ortLoaded) {
    console.error('[voiceHelper] Failed to load ONNX Runtime after retries');
    return false;
  }

  const vadLoaded = await loadWithRetry(
    "https://cdn.jsdelivr.net/npm/@ricky0123/vad-web@0.0.19/dist/bundle.min.js",
    "vad-script",
    "vad"
  );

  if (!vadLoaded) {
    console.error('[voiceHelper] Failed to load VAD library after retries');
    return false;
  }

  // Final deep validation — check MicVAD constructor exists
  if (!window.vad || !window.vad.MicVAD) {
    console.error('[voiceHelper] VAD loaded but MicVAD constructor is missing');
    return false;
  }

  return true;
}


import { AudioProcessor } from './audioProcessor';

export class VoiceSessionManager {
  constructor(options) {
    this.token = options.token;
    this.sessionId = options.sessionId;
    this.applicationId = options.applicationId;
    this.applicantName = options.applicantName;
    this.schemeId = options.schemeId;
    this.language = options.language || 'hi';
    this.wsUrl = options.wsUrl || 'ws://localhost:8080/ws/voice';

    // Callbacks
    this.onStateChange = options.onStateChange || (() => {});
    this.onTranscript = options.onTranscript || (() => {});
    this.onProgress = options.onProgress || (() => {});
    this.onNodeChange = options.onNodeChange || (() => {});
    this.onExtraction = options.onExtraction || (() => {});
    this.onComplete = options.onComplete || (() => {});
    this.onSystemMessage = options.onSystemMessage || (() => {});
    this.onError = options.onError || (() => {});

    // Audio Refs
    this.ws = null;
    this.vadInstance = null;
    this.audioContext = null;
    this.currentAudioSource = null;
    this.audioQueue = [];

    // State flags
    this.isRecording = false;
    this.isPlayingAudio = false;
    this.audioEndReceived = false;
    this.isProcessing = false;
    this.isSpeaking = false;
    this.isUserSpeaking = false;
    this.pendingText = ''; // Stores text from audio_chunk header before binary audio
    this._disconnected = false; // Guard against post-disconnect operations
    this._inCaptureMode = false; // True when in document capture mode (suppress VAD)
  }

  async connect() {
    this.disconnect();
    this._disconnected = false;
    this.onStateChange('connecting');
    this.onSystemMessage('connecting', 'माइक और सर्वर से जुड़ रहे हैं...');

    try {
      // ─── Step 1: Validate VAD ───
      if (typeof window === 'undefined') {
        throw new Error('Not in browser environment');
      }

      // Set ONNX WASM paths early (before MicVAD.new tries to use them)
      if (window.ort && window.ort.env) {
        window.ort.env.wasm.wasmPaths = "https://cdn.jsdelivr.net/npm/onnxruntime-web@1.14.0/dist/";
      }

      // Deep validation of VAD availability
      if (!window.ort) {
        throw new Error('ONNX Runtime (window.ort) is not loaded. Please reload the page.');
      }
      if (!window.vad || !window.vad.MicVAD) {
        throw new Error('VAD library (window.vad.MicVAD) is not loaded. Please reload the page.');
      }

      // ─── Step 2: Initialize AudioProcessor ───
      this.audioProcessor = new AudioProcessor({
        sampleRate: 16000,

        onAudioChunk: (chunk) => {
          if (this.isRecording && !this._disconnected && !this.isPlayingAudio && !this.isProcessing) {
            if (this.ws?.readyState === WebSocket.OPEN) {
              this.ws.send(chunk);
            }
          }
        },

        onSpeechStart: () => {
          if (!this.isRecording || this._disconnected || this.isPlayingAudio || this.isProcessing || this._inCaptureMode) return;
          
          this.ws?.send(JSON.stringify({ signal: 'speech_start' }));
          this.stopAudioPlayback();
          this.onStateChange('listening');
        },

        onSpeechEnd: () => {
          if (!this.isRecording || this._disconnected || this.isPlayingAudio || this.isProcessing || this._inCaptureMode) return;

          console.log(`[VoiceSessionManager] Speech ended`);
          this.ws?.send(JSON.stringify({ signal: 'speech_end' }));
          this.isProcessing = true;
          this.onStateChange('processing');
        },

        onVolumeLevel: (level) => {
          // Can be used for visualizer later if needed
        }
      });

      const vadLoaded = await this.audioProcessor.initialize();
      if (!vadLoaded) {
        console.warn('[VoiceSessionManager] VAD initialization failed (e.g. microphone permission denied). Disabling microphone input.');
        this.audioProcessor = null;
        this.onSystemMessage('warning', 'माइक एक्सेस उपलब्ध नहीं है (या अनुमति नहीं दी गई)। आप केवल टाइप करके बातचीत कर सकते हैं।');
      }

      // If disconnected during VAD initialization, bail
      if (this._disconnected) return;

      // ─── Step 3: Initialize WebSocket ───
      const ws = new WebSocket(this.wsUrl);
      this.ws = ws;
      ws.binaryType = 'arraybuffer';

      // Wait for WS to actually open (or fail) before proceeding
      await new Promise((resolve, reject) => {
        const timeout = setTimeout(() => {
          reject(new Error('WebSocket connection timed out (10s)'));
        }, 10000);

        ws.onopen = () => {
          clearTimeout(timeout);
          resolve();
        };

        ws.onerror = (err) => {
          clearTimeout(timeout);
          reject(new Error('WebSocket connection failed'));
        };
      });

      // If disconnected during the await above, bail out
      if (this._disconnected) return;

      // Verify WS is still alive after open
      if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
        console.warn('WebSocket closed during VAD initialization.');
        this.onSystemMessage('error', 'सर्वर से संपर्क टूट गया。 कृपया पुनः लॉगिन करें (Token expired).');
        this.disconnect();
        return;
      }

      // ─── Step 4: Set up WS message handlers ───
      ws.onmessage = async (e) => {
        if (this._disconnected) return;

        if (e.data instanceof ArrayBuffer) {
          if (this.isProcessing) {
            console.warn('[voiceHelper] Discarding late-arriving audio chunk of interrupted turn');
            return;
          }
          const isFirst = !this.isPlayingAudio;
          // Pair binary audio chunk (WAV) with pending text and push to queue
          this.audioQueue.push({ buffer: e.data, text: this.pendingText });
          this.pendingText = '';
          this.playNextAudioChunk(isFirst);
        } else {
          try {
            const data = JSON.parse(e.data);
            if (data.error) {
              const errMsg = typeof data.error === 'object' ? data.error.message || JSON.stringify(data.error) : data.error;
              this.onSystemMessage('error', `त्रुटि: ${errMsg}`);
              this.disconnect();
              return;
            }

            if (data.type === 'status') {
              if (!this.isPlayingAudio) {
                if (data.status === 'listening') {
                  this.isProcessing = false;
                  this.isSpeaking = false;
                  this.onStateChange('listening');
                } else if (data.status === 'processing') {
                  this.isProcessing = true;
                  this.onStateChange('processing');
                } else if (data.status === 'speaking') {
                  this.isProcessing = false; // Reset processing flag
                  this.isSpeaking = true;
                  this.onStateChange('speaking');
                }
              }
            } else if (data.type === 'transcription') {
              if (data.is_final) {
                // Only send final user transcription. Assistant text is handled via audio_chunk.
                this.onTranscript(data.text, true);
              }
            } else if (data.type === 'audio_chunk') {
              if (this.isProcessing) {
                this.pendingText = '';
              } else {
                this.pendingText = data.text || '';
              }
            } else if (data.type === 'progress') {
              console.log('[voiceHelper] ws received progress:', data.current_step, data.total_steps, data.current_node_id);
              this.onProgress(data.current_step, data.total_steps, data.current_node_id);
            } else if (data.type === 'node_change') {
              console.log('[voiceHelper] ws received node_change:', data.node_type, data.document_id);
              if (data.node_type === 'capture') {
                console.log('[voiceHelper] Switching to CAPTURE mode — stopping VAD/audio');
                this._inCaptureMode = true;
                this.stopAudioPlayback();
                this.isProcessing = false;
                this.isSpeaking = false;
                this.isRecording = false;
                if (this.audioProcessor) {
                  try { this.audioProcessor.stop(); } catch (e) {}
                }
                this.onStateChange('idle');
              } else if (data.node_type === 'voice-qa') {
                console.log('[voiceHelper] Switching to VOICE-QA mode — resuming VAD');
                this._inCaptureMode = false;
                this.isRecording = true;
                this.isProcessing = true; // Wait for new question audio to play
                if (this.audioProcessor) {
                  try { this.audioProcessor.start(); } catch (e) {}
                }
              }
              this.onNodeChange(data.node_type, data.document_id);
            } else if (data.type === 'extraction') {
              try {
                const fields = JSON.parse(data.json_fields);
                this.onExtraction(fields);
              } catch (ex) {}
            } else if (data.type === 'audio_end') {
              this.audioEndReceived = true;
              if (!this.isPlayingAudio && this.audioQueue.length === 0) {
                this.finalizeSpeakingTurn();
              }
            } else if (data.type === 'complete') {
              this.onStateChange('idle');
              this.disconnect();
              this.onComplete(data);
            }
          } catch (ex) {
            console.error('Failed to parse WS text message:', ex);
          }
        }
      };

      ws.onerror = (err) => {
        console.error('WebSocket error:', err);
        this.onSystemMessage('error', 'सर्वर से संपर्क टूट गया。');
        this.onError('WebSocket connection error');
        this.onStateChange('idle');
      };

      ws.onclose = () => {
        if (!this._disconnected) {
          this.onSystemMessage('error', 'The connection to the AI Assistant was unexpectedly closed.');
          this.onStateChange('error');
          this.disconnect();
        }
      };

      // ─── Step 5: Start recording & send auth signal ───
      this.isRecording = true;
      this.isProcessing = true; // Block VAD until the first TTS question begins to play
      if (this.audioProcessor) {
        this.audioProcessor.start();
      }
      this.onStateChange('connecting');

      this.onSystemMessage('info', 'सफलतापूर्वक जुड़े! प्रश्नोत्तर शुरू हो रहा है...');
      this.ws.send(JSON.stringify({
        token: this.token,
        scheme_id: this.schemeId,
        session_id: this.sessionId,
        language: this.language,
        applicant_name: this.applicantName,
        application_id: this.applicationId || ''
      }));

    } catch (err) {
      console.error('VoiceSessionManager start failure:', err);
      this.onSystemMessage('error', err.message || 'माइक अनुमति अस्वीकार कर दी गई है या सर्वर अनुपलब्ध है।');
      this.onError(err.message);
      this.disconnect();
    }
  }

  playNextAudioChunk(isFirstOfTurn = false) {
    if (this._disconnected) return;
    if (this.isPlayingAudio && !isFirstOfTurn) return;

    if (this.audioQueue.length === 0) {
      if (this.audioEndReceived) {
        this.finalizeSpeakingTurn();
      }
      return;
    }

    const chunk = this.audioQueue.shift();
    this.isPlayingAudio = true;
    this.onStateChange('speaking');

    if (chunk.text && chunk.text.trim().length > 0) {
      this.onTranscript(chunk.text, false);
    }

    // Initialize or reuse AudioContext
    if (!this.audioContext || this.audioContext.state === 'closed') {
      window.globalAudioContext = window.globalAudioContext || new (window.AudioContext || window.webkitAudioContext)();
      this.audioContext = window.globalAudioContext;
    }
    if (this.audioContext.state === 'suspended') {
      try { this.audioContext.resume(); } catch {}
    }

    // Guard: if the buffer is empty or too small to be valid WAV, skip it
    if (!chunk.buffer || chunk.buffer.byteLength < 44) {
      console.warn('[voiceHelper] Skipping invalid/empty audio chunk');
      this.isPlayingAudio = false;
      this.playNextAudioChunk(false);
      return;
    }

    const bufferCopy = chunk.buffer.slice(0);
    this.audioContext.decodeAudioData(
      bufferCopy,
      (decodedData) => {
        if (this._disconnected) return;

        const source = this.audioContext.createBufferSource();
        source.buffer = decodedData;
        source.connect(this.audioContext.destination);
        this.currentAudioSource = source;

        source.onended = () => {
          this.isPlayingAudio = false;
          if (this.currentAudioSource === source) {
            this.currentAudioSource = null;
          }
          this.playNextAudioChunk(false);
        };

        // Add 300ms hardware wake-up padding ONLY for the very first chunk of a turn
        try {
          if (isFirstOfTurn) {
            source.start(this.audioContext.currentTime + 0.3);
          } else {
            source.start(0);
          }
        } catch (playErr) {
          // Catches "The play() request was interrupted" and similar errors
          console.warn('[voiceHelper] Audio start error (non-fatal):', playErr.message);
          this.isPlayingAudio = false;
          this.playNextAudioChunk(false);
        }
      },
      (error) => {
        console.error("Error decoding audio data:", error);
        this.isPlayingAudio = false;
        this.playNextAudioChunk(false);
      }
    );
  }

  finalizeSpeakingTurn() {
    this.isSpeaking = false;
    this.isPlayingAudio = false;
    this.audioEndReceived = false;
    this.isProcessing = false;

    if (this._disconnected) return;

    if (this.isRecording) {
      this.onStateChange('listening');
      if (this.audioProcessor && this.audioProcessor.isSpeaking) {
        console.log('[VoiceSessionManager] User is already speaking! Firing delayed speech_start');
        this.ws?.send(JSON.stringify({ signal: 'speech_start' }));
      }
    } else {
      this.onStateChange('idle');
    }
  }

  sendTextInput(text) {
    if (this._disconnected || !this.ws || this.ws.readyState !== WebSocket.OPEN) {
      console.warn('[voiceHelper] Cannot send text input: session disconnected or WebSocket not open');
      return;
    }
    this.stopAudioPlayback();
    this.isProcessing = true;
    this.onStateChange('processing');
    this.ws.send(JSON.stringify({ text_input: text }));
  }

  sendControlSignal(action) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ signal: action }));
    }
  }

  stopAudioPlayback() {
    if (this.currentAudioSource) {
      try {
        this.currentAudioSource.onended = null;
        this.currentAudioSource.stop();
      } catch (e) {}
      this.currentAudioSource = null;
    }
    this.audioQueue = [];
    this.pendingText = '';
    this.isPlayingAudio = false;
    this.audioEndReceived = false;
  }

  disconnect() {
    this._disconnected = true;
    this.isRecording = false;
    this.isProcessing = false;
    this.audioEndReceived = false;
    this.isUserSpeaking = false;

    this.stopAudioPlayback();

    if (this.ws) {
      try { this.ws.close(); } catch (e) {}
      this.ws = null;
    }

    if (this.audioProcessor) {
      try {
        this.audioProcessor.destroy();
      } catch (e) {}
      this.audioProcessor = null;
    }

    if (this.audioContext) {
      this.audioContext = null;
    }

    this.onStateChange('idle');
  }
}
