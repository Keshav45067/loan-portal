/**
 * 5-Stage Voice Pipeline Audio Engine
 *
 * Implements end-to-end processing:
 * Mic -> HPF (85Hz) -> RNNoise Suppression -> Silero VAD -> AGC -> WebSocket STT
 *
 * Captures synchronized audio buffers at all 4 stages for instant auditioning & comparison.
 */

import {
  HighPassFilter,
  RNNoiseDenoiser,
  DigitalAGC,
  float32ToPcmBytes,
  float32ChunksToWavBlob,
  calculateRmsMetrics
} from './rnnoiseProcessor';

export class PipelineAudioEngine {
  /**
   * @param {Object} options
   * @param {number}   options.sampleRate              - Audio sample rate (default 16000)
   * @param {string}   options.language                - STT language ('hi', 'en', 'mr', etc.)
   * @param {string}   options.wsUrl                   - WebSocket URL for voice engine backend
   * @param {function} options.onTelemetry             - Real-time frame metrics for dashboard
   * @param {function} options.onSpeechStart           - Speech segment began
   * @param {function} options.onSpeechEnd             - Speech segment completed with 4-stage audio clips
   * @param {function} options.onTranscript            - Live STT transcription (partial & final)
   * @param {function} options.onBackgroundNoiseChange - Live ambient noise alert flag change
   * @param {function} options.onStateChange           - Session state changes
   * @param {function} options.onError                 - Error handler
   *
   * DSP Tuning Parameters:
   * @param {number}   options.hpfCutoff               - HPF cutoff frequency (default 85Hz)
   * @param {boolean}  options.rnnoiseEnabled          - RNNoise enable/disable (default true)
   * @param {number}   options.rnnoiseStrength         - RNNoise strength 0.0 - 1.0 (default 1.0)
   * @param {number}   options.positiveSpeechThreshold - VAD speech start prob (default 0.65)
   * @param {number}   options.negativeSpeechThreshold - VAD speech end prob (default 0.25)
   * @param {number}   options.minSpeechFrames         - Min frames to start speech (default 2)
   * @param {number}   options.redemptionFrames        - Frames before ending speech (default 8)
   * @param {number}   options.preSpeechPadFrames      - Pre-roll frames (default 10)
   * @param {number}   options.agcTargetRms            - AGC target RMS (default 0.125 ≈ -18 dBFS)
   * @param {number}   options.agcMaxGain              - AGC maximum boost (default 6.0)
   * @param {number}   options.ambientNoiseThreshold   - Background noise alarm threshold (default 0.0080)
   * @param {number}   options.ambientRecoveryThreshold - Background noise recovery threshold (default 0.0060)
   */
  constructor(options = {}) {
    this.sampleRate = options.sampleRate || 16000;
    this.language = options.language || 'hi';
    this.wsUrl = options.wsUrl || '';

    // Callbacks
    this.onTelemetry = options.onTelemetry || (() => {});
    this.onSpeechStart = options.onSpeechStart || (() => {});
    this.onSpeechEnd = options.onSpeechEnd || (() => {});
    this.onTranscript = options.onTranscript || (() => {});
    this.onBackgroundNoiseChange = options.onBackgroundNoiseChange || (() => {});
    this.onStateChange = options.onStateChange || (() => {});
    this.onError = options.onError || console.error;

    // DSP Units
    this.hpf = new HighPassFilter(options.hpfCutoff || 85, this.sampleRate);
    this.rnnoise = new RNNoiseDenoiser({
      sampleRate: this.sampleRate,
      enabled: options.rnnoiseEnabled ?? true,
      strength: options.rnnoiseStrength ?? 1.0,
    });
    this.agc = new DigitalAGC({
      targetRms: options.agcTargetRms || 0.125,
      maxGain: options.agcMaxGain || 6.0,
      enabled: true,
    });

    // VAD & Gating Config
    this.positiveSpeechThreshold = options.positiveSpeechThreshold ?? 0.65;
    this.negativeSpeechThreshold = options.negativeSpeechThreshold ?? 0.25;
    this.minSpeechFrames = options.minSpeechFrames ?? 2;
    this.redemptionFrames = options.redemptionFrames ?? 8;
    this.preSpeechPadFrames = options.preSpeechPadFrames ?? 10;
    this.ambientNoiseThreshold = options.ambientNoiseThreshold ?? 0.0080;
    this.ambientRecoveryThreshold = options.ambientRecoveryThreshold ?? 0.0060;

    // Web Audio & Stream state
    this.audioContext = null;
    this.mediaStream = null;
    this.sourceNode = null;
    this.processorNode = null;
    this.vadInstance = null;
    this.isRecording = false;

    // WebSocket state
    this.ws = null;
    this.wsConnected = false;
    this._sessionId = `pipeline_test_${Date.now()}`;
    this._token = 'sandbox_test_token';

    // 4-Stage Utterance Buffers
    this._isSpeaking = false;
    this._speechStartTimestamp = 0;
    this._preSpeechBuffers = {
      raw: [],
      hpf: [],
      rnnoise: [],
      agc: [],
    };
    this._activeSpeechBuffers = {
      raw: [],
      hpf: [],
      rnnoise: [],
      agc: [],
    };

    // Ambient Noise Tracking & Hysteresis State
    this._ambientNoiseHistory = [];
    this._isHighBackgroundNoise = false;
    this._speechFrameCounter = 0;
    this._silenceFrameCounter = 0;

    // Stats
    this.stats = {
      totalFrames: 0,
      speechFrames: 0,
      noiseFrames: 0,
      utterancesCount: 0,
    };
  }

  /**
   * Update DSP and VAD tuning parameters dynamically
   */
  updateConfig(params = {}) {
    if (params.hpfCutoff !== undefined) this.hpf.setCutoff(params.hpfCutoff);
    if (params.rnnoiseEnabled !== undefined) this.rnnoise.enabled = params.rnnoiseEnabled;
    if (params.rnnoiseStrength !== undefined) this.rnnoise.strength = params.rnnoiseStrength;
    if (params.agcTargetRms !== undefined) this.agc.setTargetRms(params.agcTargetRms);
    if (params.agcMaxGain !== undefined) this.agc.setMaxGain(params.agcMaxGain);
    if (params.positiveSpeechThreshold !== undefined) this.positiveSpeechThreshold = params.positiveSpeechThreshold;
    if (params.negativeSpeechThreshold !== undefined) this.negativeSpeechThreshold = params.negativeSpeechThreshold;
    if (params.ambientNoiseThreshold !== undefined) this.ambientNoiseThreshold = params.ambientNoiseThreshold;
    if (params.ambientRecoveryThreshold !== undefined) this.ambientRecoveryThreshold = params.ambientRecoveryThreshold;
    if (params.language !== undefined) {
      this.language = params.language;
      // If WebSocket is active, notify backend of language update
      if (this.ws && this.wsConnected) {
        this._sendWsControl({ signal: 'set_language', language: this.language });
      }
    }
  }

  /**
   * Initialize microphone capture and start the 5-stage pipeline
   */
  async start() {
    if (this.isRecording) return;
    this.onStateChange('connecting');

    try {
      // 1. Initialize Web Audio Context at 16kHz
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      this.audioContext = new AudioCtx({ sampleRate: this.sampleRate });
      if (this.audioContext.state === 'suspended') {
        await this.audioContext.resume();
      }

      // 2. Request user microphone (raw stream without browser pre-mangling)
      this.mediaStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          sampleRate: this.sampleRate,
          echoCancellation: true,
          noiseSuppression: false, // We use RNNoise for high-quality suppression!
          autoGainControl: false,  // We use our DigitalAGC!
        },
      });

      // 3. Connect WebSocket to Voice / STT backend
      this._connectWebSocket();

      // 4. Initialize Silero VAD (using vad-web CDN bundle)
      await this._initSileroVad();

      this.isRecording = true;
      this.onStateChange('running');
    } catch (err) {
      console.error('[PipelineAudioEngine] Failed to start pipeline:', err);
      this.onStateChange('error');
      this.onError(err);
      this.stop();
    }
  }

  /**
   * Initialize Silero VAD via window.vad or fallback Web Audio ScriptProcessor
   */
  async _initSileroVad() {
    // If window.vad is available, instantiate MicVAD
    if (typeof window !== 'undefined' && window.vad && window.vad.MicVAD) {
      try {
        if (window.ort && window.ort.env) {
          window.ort.env.wasm.wasmPaths = 'https://cdn.jsdelivr.net/npm/onnxruntime-web@1.14.0/dist/';
        }

        this.vadInstance = await window.vad.MicVAD.new({
          stream: this.mediaStream,
          workletURL: 'https://cdn.jsdelivr.net/npm/@ricky0123/vad-web@0.0.19/dist/vad.worklet.bundle.min.js',
          modelURL: 'https://cdn.jsdelivr.net/npm/@ricky0123/vad-web@0.0.19/dist/silero_vad.onnx',
          positiveSpeechThreshold: this.positiveSpeechThreshold,
          negativeSpeechThreshold: this.negativeSpeechThreshold,
          minSpeechFrames: this.minSpeechFrames,
          redemptionFrames: this.redemptionFrames,
          preSpeechPadFrames: this.preSpeechPadFrames,

          onFrameProcessed: (probs, rawFrame) => {
            const vadProb = probs ? probs.isSpeech : 0;
            this._processPipelineFrame(rawFrame, vadProb);
          },
          onSpeechStart: () => {
            this._handleSpeechStart();
          },
          onSpeechEnd: () => {
            this._handleSpeechEnd();
          },
        });

        this.vadInstance.start();
        return;
      } catch (e) {
        console.warn('[PipelineAudioEngine] Silero VAD failed, falling back to Web Audio script processor:', e);
      }
    }

    // Fallback Web Audio ScriptProcessor
    this.sourceNode = this.audioContext.createMediaStreamSource(this.mediaStream);
    this.processorNode = this.audioContext.createScriptProcessor(512, 1, 1);

    this.processorNode.onaudioprocess = (e) => {
      if (!this.isRecording) return;
      const rawFrame = e.inputBuffer.getChannelData(0);
      const metrics = calculateRmsMetrics(rawFrame);
      // Fast energy-based VAD probability estimation
      const vadProb = Math.min(1.0, Math.max(0.0, (metrics.rms - 0.003) / 0.02));
      this._processPipelineFrame(rawFrame, vadProb);

      if (vadProb >= this.positiveSpeechThreshold && !this._isSpeaking) {
        this._speechFrameCounter++;
        if (this._speechFrameCounter >= this.minSpeechFrames) {
          this._handleSpeechStart();
        }
      } else if (vadProb < this.negativeSpeechThreshold && this._isSpeaking) {
        this._silenceFrameCounter++;
        if (this._silenceFrameCounter >= this.redemptionFrames) {
          this._handleSpeechEnd();
        }
      } else {
        if (this._isSpeaking) this._silenceFrameCounter = 0;
        else this._speechFrameCounter = 0;
      }
    };

    this.sourceNode.connect(this.processorNode);
    this.processorNode.connect(this.audioContext.destination);
  }

  /**
   * Process a single 512-sample frame through the 5 stages
   * @param {Float32Array} rawFrame - Stage 1 (Raw Mic)
   * @param {number} vadProbability - Stage 4 (VAD Prob)
   */
  _processPipelineFrame(rawFrame, vadProbability) {
    if (!rawFrame || rawFrame.length === 0) return;
    this.stats.totalFrames++;

    // ──────────────────────────────────────────
    // STAGE 1: Raw Mic Frame Metrics
    // ──────────────────────────────────────────
    const rawMetrics = calculateRmsMetrics(rawFrame);

    // ──────────────────────────────────────────
    // STAGE 2: High-Pass Filter (85Hz Cutoff)
    // ──────────────────────────────────────────
    const hpfFrame = this.hpf.process(rawFrame);
    const hpfMetrics = calculateRmsMetrics(hpfFrame);
    const hpfSubBassCutDb = Math.max(0, rawMetrics.db - hpfMetrics.db);

    // ──────────────────────────────────────────
    // STAGE 3: RNNoise Suppression
    // ──────────────────────────────────────────
    const isSpeechHint = vadProbability >= this.positiveSpeechThreshold;
    const rnnoiseFrame = this.rnnoise.process(hpfFrame, isSpeechHint);
    const rnnoiseMetrics = calculateRmsMetrics(rnnoiseFrame);
    const noiseReductionDb = Math.max(0, hpfMetrics.db - rnnoiseMetrics.db);

    // ──────────────────────────────────────────
    // STAGE 4: VAD & Ambient Noise Hysteresis
    // ──────────────────────────────────────────
    const isSpeechActive = vadProbability >= this.positiveSpeechThreshold || this._isSpeaking;

    if (!isSpeechActive) {
      // Track ambient background noise during non-speech frames
      this._ambientNoiseHistory.push(rnnoiseMetrics.rms);
      if (this._ambientNoiseHistory.length > 150) this._ambientNoiseHistory.shift();
      this.stats.noiseFrames++;
    } else {
      this.stats.speechFrames++;
    }

    // Rolling Ambient Noise RMS
    const ambientRms = this._ambientNoiseHistory.length > 0
      ? this._ambientNoiseHistory.reduce((a, b) => a + b, 0) / this._ambientNoiseHistory.length
      : 0;

    // Dual-threshold Schmitt trigger hysteresis for High Background Noise
    if (!this._isHighBackgroundNoise && ambientRms >= this.ambientNoiseThreshold && this._ambientNoiseHistory.length >= 40) {
      this._isHighBackgroundNoise = true;
      this.onBackgroundNoiseChange(true, ambientRms);
    } else if (this._isHighBackgroundNoise && ambientRms <= this.ambientRecoveryThreshold) {
      this._isHighBackgroundNoise = false;
      this.onBackgroundNoiseChange(false, ambientRms);
    }

    // ──────────────────────────────────────────
    // STAGE 5: Automatic Gain Control (AGC)
    // ──────────────────────────────────────────
    const agcResult = this.agc.process(rnnoiseFrame);
    const agcFrame = agcResult.processed;
    const agcMetrics = calculateRmsMetrics(agcFrame);

    // ──────────────────────────────────────────
    // Maintain Pre-Speech Ring Buffer
    // ──────────────────────────────────────────
    if (!this._isSpeaking) {
      this._preSpeechBuffers.raw.push(new Float32Array(rawFrame));
      this._preSpeechBuffers.hpf.push(new Float32Array(hpfFrame));
      this._preSpeechBuffers.rnnoise.push(new Float32Array(rnnoiseFrame));
      this._preSpeechBuffers.agc.push(new Float32Array(agcFrame));

      if (this._preSpeechBuffers.raw.length > this.preSpeechPadFrames) {
        this._preSpeechBuffers.raw.shift();
        this._preSpeechBuffers.hpf.shift();
        this._preSpeechBuffers.rnnoise.shift();
        this._preSpeechBuffers.agc.shift();
      }
    } else {
      // Speech is active: record chunks for all 4 stages
      this._activeSpeechBuffers.raw.push(new Float32Array(rawFrame));
      this._activeSpeechBuffers.hpf.push(new Float32Array(hpfFrame));
      this._activeSpeechBuffers.rnnoise.push(new Float32Array(rnnoiseFrame));
      this._activeSpeechBuffers.agc.push(new Float32Array(agcFrame));

      // Stream Stage 5 (AGC) linear 16-bit PCM bytes to backend STT
      if (this.ws && this.wsConnected) {
        const pcmBytes = float32ToPcmBytes(agcFrame);
        this.ws.send(pcmBytes.buffer);
      }
    }

    // ──────────────────────────────────────────
    // Emit Real-Time Frame Telemetry to Dashboard
    // ──────────────────────────────────────────
    this.onTelemetry({
      timestamp: performance.now(),
      vadProbability,
      isSpeaking: this._isSpeaking,
      isHighBackgroundNoise: this._isHighBackgroundNoise,
      ambientRms,
      // Stage 1 (Raw)
      raw: { rms: rawMetrics.rms, db: rawMetrics.db, peak: rawMetrics.peak, frame: rawFrame },
      // Stage 2 (HPF)
      hpf: { rms: hpfMetrics.rms, db: hpfMetrics.db, peak: hpfMetrics.peak, subBassCutDb, frame: hpfFrame },
      // Stage 3 (RNNoise)
      rnnoise: { rms: rnnoiseMetrics.rms, db: rnnoiseMetrics.db, peak: rnnoiseMetrics.peak, noiseReductionDb, frame: rnnoiseFrame },
      // Stage 4 (AGC)
      agc: {
        rms: agcMetrics.rms,
        db: agcMetrics.db,
        peak: agcMetrics.peak,
        gainApplied: agcResult.gainApplied,
        gainDb: agcResult.gainDb,
        isLimiting: agcResult.isLimiting,
        frame: agcFrame
      },
    });
  }

  /**
   * Speech started handler
   */
  _handleSpeechStart() {
    if (this._isSpeaking) return;
    this._isSpeaking = true;
    this._speechStartTimestamp = performance.now();
    this._speechFrameCounter = 0;
    this._silenceFrameCounter = 0;

    // Move pre-speech pads into active speech buffers
    this._activeSpeechBuffers.raw = [...this._preSpeechBuffers.raw];
    this._activeSpeechBuffers.hpf = [...this._preSpeechBuffers.hpf];
    this._activeSpeechBuffers.rnnoise = [...this._preSpeechBuffers.rnnoise];
    this._activeSpeechBuffers.agc = [...this._preSpeechBuffers.agc];

    // Notify backend
    this._sendWsControl({ signal: 'speech_start' });
    this.onSpeechStart({ timestamp: this._speechStartTimestamp });
  }

  /**
   * Speech ended handler — packages 4-stage playable WAV audio clips
   */
  _handleSpeechEnd() {
    if (!this._isSpeaking) return;
    this._isSpeaking = false;
    const durationMs = Math.round(performance.now() - this._speechStartTimestamp);
    this.stats.utterancesCount++;

    // Notify backend
    this._sendWsControl({ signal: 'speech_end' });

    // Generate Playable WAV Blobs for all 4 stages
    const rawWavBlob = float32ChunksToWavBlob(this._activeSpeechBuffers.raw, this.sampleRate);
    const hpfWavBlob = float32ChunksToWavBlob(this._activeSpeechBuffers.hpf, this.sampleRate);
    const rnnoiseWavBlob = float32ChunksToWavBlob(this._activeSpeechBuffers.rnnoise, this.sampleRate);
    const agcWavBlob = float32ChunksToWavBlob(this._activeSpeechBuffers.agc, this.sampleRate);

    // Calculate aggregated stage metrics
    const utteranceData = {
      id: `utt_${Date.now()}_${this.stats.utterancesCount}`,
      timestamp: new Date().toLocaleTimeString(),
      durationMs,
      language: this.language,
      blobs: {
        raw: rawWavBlob,
        hpf: hpfWavBlob,
        rnnoise: rnnoiseWavBlob,
        agc: agcWavBlob,
      },
      urls: {
        raw: rawWavBlob ? URL.createObjectURL(rawWavBlob) : null,
        hpf: hpfWavBlob ? URL.createObjectURL(hpfWavBlob) : null,
        rnnoise: rnnoiseWavBlob ? URL.createObjectURL(rnnoiseWavBlob) : null,
        agc: agcWavBlob ? URL.createObjectURL(agcWavBlob) : null,
      },
      sampleCount: this._activeSpeechBuffers.raw.length * 512,
    };

    this.onSpeechEnd(utteranceData);

    // Reset buffers
    this._activeSpeechBuffers = { raw: [], hpf: [], rnnoise: [], agc: [] };
    this._preSpeechBuffers = { raw: [], hpf: [], rnnoise: [], agc: [] };
  }

  /**
   * WebSocket Connection & Message Handling
   */
  _connectWebSocket() {
    if (typeof window === 'undefined') return;

    try {
      const defaultHost = window.location.hostname || 'localhost';
      const wsUrl = this.wsUrl || `ws://${defaultHost}:8080/ws/voice`;
      this.ws = new WebSocket(wsUrl);

      this.ws.onopen = () => {
        this.wsConnected = true;
        // Send initial auth message
        this.ws.send(JSON.stringify({
          token: this._token,
          session_id: this._sessionId,
          scheme_id: 'rural-voice-test',
          language: this.language,
          applicant_name: 'Test Voice User',
        }));
      };

      this.ws.onmessage = (event) => {
        if (typeof event.data === 'string') {
          try {
            const data = JSON.parse(event.data);
            if (data.type === 'transcription') {
              this.onTranscript({
                text: data.text || '',
                isFinal: data.is_final ?? true,
                latencyMs: data.latency_ms || null,
              });
            }
          } catch (e) {
            console.error('[PipelineAudioEngine] WS JSON parse error:', e);
          }
        }
      };

      this.ws.onerror = (e) => {
        console.warn('[PipelineAudioEngine] WebSocket connection notice:', e);
      };

      this.ws.onclose = () => {
        this.wsConnected = false;
      };
    } catch (err) {
      console.warn('[PipelineAudioEngine] WS Init warning:', err);
    }
  }

  _sendWsControl(msgObj) {
    if (this.ws && this.wsConnected && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(msgObj));
    }
  }

  /**
   * Stop pipeline and release all audio/network resources
   */
  stop() {
    this.isRecording = false;
    this._isSpeaking = false;

    if (this.vadInstance) {
      try { this.vadInstance.pause(); } catch (e) {}
      this.vadInstance = null;
    }

    if (this.mediaStream) {
      this.mediaStream.getTracks().forEach(t => t.stop());
      this.mediaStream = null;
    }

    if (this.processorNode) {
      try { this.processorNode.disconnect(); } catch (e) {}
      this.processorNode = null;
    }

    if (this.sourceNode) {
      try { this.sourceNode.disconnect(); } catch (e) {}
      this.sourceNode = null;
    }

    if (this.audioContext && this.audioContext.state !== 'closed') {
      try { this.audioContext.close(); } catch (e) {}
      this.audioContext = null;
    }

    if (this.ws) {
      try { this.ws.close(); } catch (e) {}
      this.ws = null;
      this.wsConnected = false;
    }

    this.onStateChange('stopped');
  }
}
