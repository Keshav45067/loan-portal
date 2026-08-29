/**
 * Audio Processor — 5-Stage Voice DSP Pipeline Engine
 *
 * Implements:
 * 1. Stage 1: Raw 16kHz Mic capture
 * 2. Stage 2: 85Hz IIR High-Pass Filter (removes rumble, HVAC, micro-vibrations)
 * 3. Stage 3: RNNoise Neural Denoiser (client-side WASM background noise suppression)
 * 4. Stage 4: Silero VAD + RMS Energy Gating State Machine:
 *    - SILENT: VAD < negThreshold
 *    - NOISE_ONLY: VAD between neg and pos threshold
 *    - SPEECH_FAR: VAD >= posThreshold, but rolling RMS < rmsHighThreshold
 *    - SPEECH_NEAR: VAD >= posThreshold, and rolling RMS >= rmsHighThreshold
 * 5. Stage 5: Digital AGC (Dynamic gain boost up to +15dB with soft-knee tanh limiter)
 * 6. Ambient noise level tracker during non-speech frames
 * 7. Strict UX flag debouncing (Speak closer & High bg noise)
 */

import {
  HighPassFilter,
  RNNoiseDenoiser,
  DigitalAGC,
  calculateRmsMetrics
} from './rnnoiseProcessor';

export class AudioProcessor {
  /**
   * @param {Object} options
   * @param {number}   options.sampleRate              - Target sample rate (default 16000)
   * @param {function} options.onAudioChunk            - Called with PCM ArrayBuffer during confirmed speech
   * @param {function} options.onSpeechStart           - Called when speech begins and is confirmed
   * @param {function} options.onSpeechEnd             - Called when speech ends
   * @param {function} options.onVolumeLevel           - Volume level callback [0-1]
   * @param {function} options.onFrameClassified       - Detailed diagnostic frame callback
   * @param {function} options.onSpeechTooQuiet        - Debounced flag when speech is detected too far/quiet
   * @param {function} options.onHighBackgroundNoise   - Debounced flag when ambient noise is high
   *
   * DSP & AGC Tuning:
   * @param {number}   options.hpfCutoff               - HPF cutoff frequency (default 85Hz)
   * @param {boolean}  options.rnnoiseEnabled          - RNNoise enable/disable (default true)
   * @param {number}   options.rnnoiseStrength         - RNNoise strength 0.0 - 1.0 (default 1.0)
   * @param {number}   options.agcTargetRms            - AGC target RMS (default 0.125 ≈ -18 dBFS)
   * @param {number}   options.agcMaxGain              - AGC maximum boost (default 6.0)
   * @param {boolean}  options.agcEnabled              - AGC enable/disable (default true)
   *
   * Thresholds & State Machine tuning:
   * @param {number}   options.positiveSpeechThreshold - VAD speech start prob (default 0.75)
   * @param {number}   options.negativeSpeechThreshold - VAD speech end prob (default 0.25)
   * @param {number}   options.minSpeechFrames         - VAD min speech frames (default 2)
   * @param {number}   options.preSpeechPadFrames      - VAD pre-speech pad (default 14)
   * @param {number}   options.redemptionFrames        - VAD redemption frames (default 8)
   * @param {number}   options.rmsHighThreshold        - Near-field speech floor (default 0.015)
   * @param {number}   options.rmsLowThreshold         - Far-field / noise ceiling (default 0.004)
   * @param {number}   options.rmsWindowSize           - Frames for rolling RMS average (default 5)
   * @param {number}   options.minNearFrames           - SPEECH_NEAR frames to confirm (default 3)
   * @param {number}   options.maxEvalFrames           - Max far frames before quiet flag (default 30 = ~1s)
   * @param {number}   options.energyRedemptionFrames  - Low RMS frames before PAUSE state (default 12)
   * @param {number}   options.ambientNoiseThreshold   - Ambient RMS threshold for noise flag (default 0.008)
   * @param {number}   options.speakCloserCooldownMs   - Global cooldown for speak-closer flag (default 15000)
   */
  constructor(options = {}) {
    this.targetSampleRate = options.sampleRate || 16000;
    this.onAudioChunk = options.onAudioChunk || (() => {});
    this.onSpeechStart = options.onSpeechStart || (() => {});
    this.onSpeechEnd = options.onSpeechEnd || (() => {});
    this.onVolumeLevel = options.onVolumeLevel || (() => {});
    this.onFrameClassified = options.onFrameClassified || (() => {});
    this.onSpeechTooQuiet = options.onSpeechTooQuiet || (() => {});
    this.onHighBackgroundNoise = options.onHighBackgroundNoise || (() => {});

    // DSP Units
    this.hpf = new HighPassFilter(options.hpfCutoff || 85, this.targetSampleRate);
    this.rnnoise = new RNNoiseDenoiser({
      sampleRate: this.targetSampleRate,
      enabled: options.rnnoiseEnabled ?? true,
      strength: options.rnnoiseStrength ?? 1.0,
    });
    this.agc = new DigitalAGC({
      targetRms: options.agcTargetRms || 0.125,
      maxGain: options.agcMaxGain || 6.0,
      enabled: options.agcEnabled ?? true,
    });

    // Dynamic VAD Options
    this.positiveSpeechThreshold = options.positiveSpeechThreshold ?? 0.75;
    this.negativeSpeechThreshold = options.negativeSpeechThreshold ?? 0.25;
    this.minSpeechFrames = options.minSpeechFrames ?? 2;
    this.preSpeechPadFrames = options.preSpeechPadFrames ?? 14;
    this.redemptionFrames = options.redemptionFrames ?? 8;
    this.additionalAudioConstraints = options.additionalAudioConstraints || {
      echoCancellation: true,
      noiseSuppression: false,
      autoGainControl: true,
    };

    // RMS Energy Gating & State Machine Config
    this.rmsHighThreshold = options.rmsHighThreshold ?? 0.015;
    this.rmsLowThreshold = options.rmsLowThreshold ?? 0.004;
    this.rmsWindowSize = options.rmsWindowSize ?? 5;
    this.minNearFrames = options.minNearFrames ?? 3;
    this.maxEvalFrames = options.maxEvalFrames ?? 30;
    this.energyRedemptionFrames = options.energyRedemptionFrames ?? 12;
    this.ambientNoiseThreshold = options.ambientNoiseThreshold ?? 0.008;
    this.speakCloserCooldownMs = options.speakCloserCooldownMs ?? 15000;

    this.vadInstance = null;
    this.isRecording = false;

    // Buffer configuration (512 samples @ 16kHz ≈ 32ms)
    this.bufferSize = 512;
    this._chunkBuffer = [];
    this._preSpeechBuffer = [];
    this._evalSpeechBuffer = []; // Buffer held while EVALUATING before confirmation

    // Internal State
    this._energyState = 'ENERGY_IDLE'; // ENERGY_IDLE, ENERGY_EVALUATING, ENERGY_CONFIRMED, ENERGY_PAUSE, ENERGY_FLAGGED_QUIET
    this._vadSpeechActive = false;
    this._rmsHistory = [];
    this._ambientRmsHistory = [];

    // Counters
    this._nearCount = 0;
    this._farCount = 0;
    this._pauseCount = 0;
    this._recoveryCount = 0;

    // Debounce state
    this._startTime = 0;
    this._lastSpeakCloserTime = 0;
    this._speakCloserFiredThisSegment = false;
    this._ambientNoiseFlagged = false;
    this._lastAmbientCheckTime = 0;

    // Stats accumulator for diagnostics
    this.stats = {
      totalFrames: 0,
      silentFrames: 0,
      noiseFrames: 0,
      speechFarFrames: 0,
      speechNearFrames: 0,
      streamedChunks: 0,
      droppedChunks: 0,
    };
  }

  /**
   * Apply a 1st-order IIR High-Pass Filter (cut-off ~85Hz at 16kHz sample rate)
   * Formula: y[n] = alpha * (y[n-1] + x[n] - x[n-1])
   * @param {Float32Array} frame
   * @returns {Float32Array}
   */
  _applyHighPassFilter(frame) {
    const filtered = new Float32Array(frame.length);
    const alpha = 0.9677; // 85Hz cut-off at 16kHz
    for (let i = 0; i < frame.length; i++) {
      const x = frame[i];
      const y = alpha * (this._hpfPrevY + x - this._hpfPrevX);
      this._hpfPrevX = x;
      this._hpfPrevY = y;
      filtered[i] = y;
    }
    return filtered;
  }

  /**
   * Calculate RMS energy and convert to dB
   */
  _calculateRms(frame) {
    let sumSq = 0;
    for (let i = 0; i < frame.length; i++) {
      sumSq += frame[i] * frame[i];
    }
    const rms = Math.sqrt(sumSq / frame.length);
    const db = 20 * Math.log10(rms + 1e-10);
    return { rms, db };
  }

  /**
   * Get ambient RMS average over recent non-speech frames
   */
  _getAmbientRms() {
    if (this._ambientRmsHistory.length === 0) return 0;
    const sum = this._ambientRmsHistory.reduce((a, b) => a + b, 0);
    return sum / this._ambientRmsHistory.length;
  }

  /**
   * Update configuration parameters dynamically
   */
  updateConfig(newOptions = {}) {
    if (newOptions.positiveSpeechThreshold !== undefined) this.positiveSpeechThreshold = newOptions.positiveSpeechThreshold;
    if (newOptions.negativeSpeechThreshold !== undefined) this.negativeSpeechThreshold = newOptions.negativeSpeechThreshold;
    if (newOptions.rmsHighThreshold !== undefined) this.rmsHighThreshold = newOptions.rmsHighThreshold;
    if (newOptions.rmsLowThreshold !== undefined) this.rmsLowThreshold = newOptions.rmsLowThreshold;
    if (newOptions.rmsWindowSize !== undefined) this.rmsWindowSize = newOptions.rmsWindowSize;
    if (newOptions.minNearFrames !== undefined) this.minNearFrames = newOptions.minNearFrames;
    if (newOptions.maxEvalFrames !== undefined) this.maxEvalFrames = newOptions.maxEvalFrames;
    if (newOptions.energyRedemptionFrames !== undefined) this.energyRedemptionFrames = newOptions.energyRedemptionFrames;
    if (newOptions.ambientNoiseThreshold !== undefined) this.ambientNoiseThreshold = newOptions.ambientNoiseThreshold;
  }

  /**
   * Reset stats
   */
  resetStats() {
    this.stats = {
      totalFrames: 0,
      silentFrames: 0,
      noiseFrames: 0,
      speechFarFrames: 0,
      speechNearFrames: 0,
      streamedChunks: 0,
      droppedChunks: 0,
    };
  }

  /**
   * Initialize @ricky0123/vad-web MicVAD instance with robust triage callbacks
   * @returns {Promise<boolean>}
   */
  async initialize() {
    try {
      if (typeof window === 'undefined') return false;

      // Set ONNX WASM paths early
      if (window.ort && window.ort.env) {
        window.ort.env.wasm.wasmPaths = "https://cdn.jsdelivr.net/npm/onnxruntime-web@1.14.0/dist/";
      }

      console.log('Initializing AudioProcessor MicVAD...');
      this.vadInstance = await window.vad.MicVAD.new({
        workletURL: "https://cdn.jsdelivr.net/npm/@ricky0123/vad-web@0.0.19/dist/vad.worklet.bundle.min.js",
        modelURL: "https://cdn.jsdelivr.net/npm/@ricky0123/vad-web@0.0.19/dist/silero_vad.onnx",
        positiveSpeechThreshold: this.positiveSpeechThreshold,
        negativeSpeechThreshold: this.negativeSpeechThreshold,
        minSpeechFrames: this.minSpeechFrames,
        preSpeechPadFrames: this.preSpeechPadFrames,
        redemptionFrames: this.redemptionFrames,
        additionalAudioConstraints: this.additionalAudioConstraints,

        onSpeechStart: () => {
          console.log('[AudioProcessor] Layer 1 (Silero) detected Speech Start');
          this._vadSpeechActive = true;
          this._energyState = 'ENERGY_EVALUATING';
          this._nearCount = 0;
          this._farCount = 0;
          this._pauseCount = 0;
          this._recoveryCount = 0;
          this._speakCloserFiredThisSegment = false;

          // Copy pre-speech buffer into evaluation buffer
          this._evalSpeechBuffer = [...this._preSpeechBuffer];
          this._preSpeechBuffer = [];
          this._chunkBuffer = [];
        },

        onSpeechEnd: (audio) => {
          console.log(`[AudioProcessor] Layer 1 (Silero) detected Speech End. Prior Energy State: ${this._energyState}`);
          const wasConfirmed = this._energyState === 'ENERGY_CONFIRMED' || this._energyState === 'ENERGY_PAUSE';

          this._vadSpeechActive = false;
          this._energyState = 'ENERGY_IDLE';
          this._nearCount = 0;
          this._farCount = 0;
          this._pauseCount = 0;
          this._recoveryCount = 0;

          if (this.isRecording && wasConfirmed) {
            this._flushBuffer();
            this.onSpeechEnd(audio);
          } else {
            // Speech was dropped/false alarm
            this._chunkBuffer = [];
            this._evalSpeechBuffer = [];
            this.stats.droppedChunks++;
          }
        },

        onFrameProcessed: (probabilities, frame) => {
          if (!this.isRecording) return;
          this.stats.totalFrames++;

          // ─── Stage 2: 85Hz IIR High-Pass Filter ───
          const hpfFrame = this.hpf.process(frame);

          // ─── Stage 3: RNNoise Neural Denoiser ───
          const denoisedFrame = this.rnnoise.process(hpfFrame);

          // ─── Stage 4: Silero VAD + Energy Gating Classification ───
          const { rms: rmsEnergy, db: rmsDb } = calculateRmsMetrics(denoisedFrame);

          // Update Rolling RMS Window
          this._rmsHistory.push(rmsEnergy);
          if (this._rmsHistory.length > this.rmsWindowSize) {
            this._rmsHistory.shift();
          }
          const rollingRms = this._rmsHistory.reduce((a, b) => a + b, 0) / this._rmsHistory.length;

          // Classify Frame
          const vadProb = probabilities.isSpeech ?? 0;
          let classification;
          if (vadProb < this.negativeSpeechThreshold) {
            classification = 'SILENT';
            this.stats.silentFrames++;
          } else if (vadProb < this.positiveSpeechThreshold) {
            classification = 'NOISE_ONLY';
            this.stats.noiseFrames++;
          } else if (rollingRms >= this.rmsHighThreshold) {
            classification = 'SPEECH_NEAR';
            this.stats.speechNearFrames++;
          } else {
            classification = 'SPEECH_FAR';
            this.stats.speechFarFrames++;
          }

          // Track Ambient Noise (only during non-speech)
          if (!this._vadSpeechActive) {
            this._ambientRmsHistory.push(rmsEnergy);
            if (this._ambientRmsHistory.length > 150) { // ~5 seconds window
              this._ambientRmsHistory.shift();
            }
            this._checkAmbientNoise();
          }

          const ambientRms = this._getAmbientRms();

          // ─── Stage 5: Digital AGC (Dynamic Gain Control + Soft-Knee Limiter) ───
          const { processed: agcFrame, gainApplied, gainDb, isLimiting } = this.agc.process(denoisedFrame);

          // Convert leveled audio to 16-bit linear PCM
          const pcmData = this._float32ToInt16(agcFrame);

          // Energy Gate State Machine
          if (this._vadSpeechActive) {
            this._processEnergyGate(classification, rollingRms, pcmData);
          } else {
            // Maintain rolling pre-speech pad
            this._preSpeechBuffer.push(...pcmData);
            const maxPreSpeechSamples = agcFrame.length * this.preSpeechPadFrames;
            if (this._preSpeechBuffer.length > maxPreSpeechSamples) {
              this._preSpeechBuffer.splice(0, this._preSpeechBuffer.length - maxPreSpeechSamples);
            }
          }

          // Fire Diagnostic Callback with full 5-stage telemetry
          this.onFrameClassified({
            vadProbability: vadProb,
            rmsEnergy,
            rmsDb,
            rollingRms,
            classification,
            energyState: this._energyState,
            ambientRms,
            gainApplied,
            gainDb,
            isLimiting,
            isStreaming: (this._energyState === 'ENERGY_CONFIRMED' || this._energyState === 'ENERGY_PAUSE'),
            timestamp: Date.now(),
          });

          // Emit Volume Level
          this.onVolumeLevel(Math.min(1, rollingRms * 8));
        },
      });

      console.log('AudioProcessor initialized successfully.');
      return true;
    } catch (error) {
      console.error('AudioProcessor initialization failed:', error);
      return false;
    }
  }

  /**
   * Process frame through the Energy Gate State Machine
   */
  _processEnergyGate(classification, rollingRms, pcmData) {
    switch (this._energyState) {
      case 'ENERGY_EVALUATING': {
        // Buffer frame data in eval buffer
        this._evalSpeechBuffer.push(...pcmData);

        if (rollingRms >= this.rmsHighThreshold) {
          this._nearCount++;
          this._farCount = 0;
        } else {
          this._farCount++;
          this._nearCount = 0;
        }

        // CONFIRM NEAR-FIELD SPEECH
        if (this._nearCount >= this.minNearFrames) {
          console.log('[AudioProcessor] Speech CONFIRMED near-field! Starting stream.');
          this._energyState = 'ENERGY_CONFIRMED';
          this.onSpeechStart();

          // Flush all buffered pre-speech & eval speech to chunk buffer
          this._chunkBuffer = [...this._evalSpeechBuffer];
          this._evalSpeechBuffer = [];
          this._flushChunkBuffer();
        }
        // FLAG FAR-FIELD SPEECH (Too quiet / distant)
        else if (this._farCount >= this.maxEvalFrames) {
          console.log('[AudioProcessor] Speech evaluated as TOO QUIET / FAR-FIELD.');
          this._energyState = 'ENERGY_FLAGGED_QUIET';
          this._triggerSpeakCloserFlag();
        }
        break;
      }

      case 'ENERGY_CONFIRMED': {
        // Actively stream audio
        this._chunkBuffer.push(...pcmData);
        this._flushChunkBuffer();

        // Track natural speech pauses
        if (rollingRms < this.rmsHighThreshold) {
          this._pauseCount++;
          if (this._pauseCount >= this.energyRedemptionFrames) {
            this._energyState = 'ENERGY_PAUSE';
          }
        } else {
          this._pauseCount = 0;
        }
        break;
      }

      case 'ENERGY_PAUSE': {
        // KEEP STREAMING during natural pauses between sentences! Trust VAD.
        this._chunkBuffer.push(...pcmData);
        this._flushChunkBuffer();

        if (rollingRms >= this.rmsHighThreshold) {
          // Resumed energetic speech
          this._energyState = 'ENERGY_CONFIRMED';
          this._pauseCount = 0;
        }
        break;
      }

      case 'ENERGY_FLAGGED_QUIET': {
        // Audio is not streamed, but held in eval buffer in case of recovery
        this._evalSpeechBuffer.push(...pcmData);
        // Keep max 2 seconds of eval buffer
        if (this._evalSpeechBuffer.length > 16000 * 2 * 2) {
          this._evalSpeechBuffer.splice(0, this._evalSpeechBuffer.length - 16000 * 2 * 2);
        }

        // Allow recovery if user starts speaking louder/closer within the same utterance
        if (rollingRms >= this.rmsHighThreshold) {
          this._recoveryCount++;
          if (this._recoveryCount >= this.minNearFrames) {
            console.log('[AudioProcessor] User recovered volume! Transitioning to CONFIRMED.');
            this._energyState = 'ENERGY_CONFIRMED';
            this.onSpeechStart();
            this._chunkBuffer = [...this._evalSpeechBuffer];
            this._evalSpeechBuffer = [];
            this._flushChunkBuffer();
          }
        } else {
          this._recoveryCount = 0;
        }
        break;
      }

      default:
        break;
    }
  }

  /**
   * Debounced "Speak Closer" trigger
   */
  _triggerSpeakCloserFlag() {
    const now = Date.now();
    if (this._speakCloserFiredThisSegment) return;
    if (now - this._lastSpeakCloserTime < this.speakCloserCooldownMs) return;

    this._speakCloserFiredThisSegment = true;
    this._lastSpeakCloserTime = now;
    console.warn('[AudioProcessor] Triggering debounced onSpeechTooQuiet event.');
    this.onSpeechTooQuiet({
      reason: 'far_field_or_mumble',
      rollingRms: this._rmsHistory[this._rmsHistory.length - 1] || 0,
      threshold: this.rmsHighThreshold,
    });
  }

  /**
   * Debounced ambient background noise check
   */
  _checkAmbientNoise() {
    const now = Date.now();
    // Don't flag in first 3 seconds of session warmup
    if (now - this._startTime < 3000) return;
    // Check every 1.5 seconds
    if (now - this._lastAmbientCheckTime < 1500) return;
    this._lastAmbientCheckTime = now;

    const ambientRms = this._getAmbientRms();
    if (ambientRms > this.ambientNoiseThreshold && this._ambientRmsHistory.length >= 60) {
      if (!this._ambientNoiseFlagged) {
        this._ambientNoiseFlagged = true;
        console.warn(`[AudioProcessor] High ambient background noise detected: RMS=${ambientRms.toFixed(4)}`);
        this.onHighBackgroundNoise({
          ambientRms,
          threshold: this.ambientNoiseThreshold,
          active: true,
        });
      }
    } else if (ambientRms <= this.ambientNoiseThreshold * 0.75) {
      if (this._ambientNoiseFlagged) {
        this._ambientNoiseFlagged = false;
        console.log('[AudioProcessor] Ambient noise returned to normal.');
        this.onHighBackgroundNoise({
          ambientRms,
          threshold: this.ambientNoiseThreshold,
          active: false,
        });
      }
    }
  }

  _flushChunkBuffer() {
    while (this._chunkBuffer.length >= this.bufferSize * 2) {
      const chunk = new Uint8Array(
        this._chunkBuffer.splice(0, this.bufferSize * 2)
      );
      this.stats.streamedChunks++;
      this.onAudioChunk(chunk.buffer);
    }
  }

  _flushBuffer() {
    if (this._chunkBuffer.length > 0) {
      const chunk = new Uint8Array(this._chunkBuffer);
      this.stats.streamedChunks++;
      this.onAudioChunk(chunk.buffer);
      this._chunkBuffer = [];
    }
  }

  start() {
    if (!this.vadInstance) {
      console.error('AudioProcessor not initialized');
      return;
    }
    this.isRecording = true;
    this._startTime = Date.now();
    this.vadInstance.start();
    console.log('[AudioProcessor] Started');
  }

  stop() {
    this.isRecording = false;
    this._vadSpeechActive = false;
    this._energyState = 'ENERGY_IDLE';
    this._chunkBuffer = [];
    this._preSpeechBuffer = [];
    this._evalSpeechBuffer = [];
    if (this.hpf) this.hpf.reset();
    if (this.rnnoise) this.rnnoise.reset();
    if (this.agc) this.agc.reset();
    if (this.vadInstance) {
      this.vadInstance.pause();
    }
    console.log('[AudioProcessor] Stopped');
  }

  destroy() {
    this.stop();
    if (this.vadInstance) {
      this.vadInstance.destroy();
      this.vadInstance = null;
    }
  }

  _float32ToInt16(float32Array) {
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

  get isSpeaking() {
    return this._energyState === 'ENERGY_CONFIRMED' || this._energyState === 'ENERGY_PAUSE';
  }

  get energyState() {
    return this._energyState;
  }
}
