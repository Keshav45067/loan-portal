/**
 * Audio Processor — Uses @ricky0123/vad-web for browser-side VAD.
 *
 * During speech, it sends raw PCM audio chunks to the server for
 * streaming STT. It also sends control messages for speech_start
 * and speech_end.
 */

export class AudioProcessor {
  /**
   * @param {Object} options
   * @param {number}   options.sampleRate   - Target sample rate (default 16000)
   * @param {function} options.onAudioChunk - Called with PCM ArrayBuffer during speech
   * @param {function} options.onSpeechStart - Called when speech begins
   * @param {function} options.onSpeechEnd   - Called when speech ends
   * @param {function} options.onVolumeLevel  - Volume level callback [0-1]
   */
  constructor(options = {}) {
    this.targetSampleRate = options.sampleRate || 16000;
    this.onAudioChunk = options.onAudioChunk || (() => {});
    this.onSpeechStart = options.onSpeechStart || (() => {});
    this.onSpeechEnd = options.onSpeechEnd || (() => {});
    this.onVolumeLevel = options.onVolumeLevel || (() => {});

    // Dynamic VAD options (with fallback defaults)
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

    this.vadInstance = null;
    this.isRecording = false;
    this._isSpeaking = false;
    
    // Chunk accumulation buffer (16000 samples = 1s, we'll send ~512 samples)
    this.bufferSize = 512;
    this._chunkBuffer = [];
    this._preSpeechBuffer = [];

    // 85Hz IIR High-Pass Filter state (removes low-frequency room rumble & AC hum)
    this._hpfPrevX = 0;
    this._hpfPrevY = 0;
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
   * Initialize the @ricky0123/vad-web MicVAD instance.
   * @returns {Promise<boolean>}
   */
  async initialize() {
    try {
      if (typeof window === 'undefined') return false;

      // Set ONNX WASM paths early (before MicVAD.new tries to use them)
      if (window.ort && window.ort.env) {
        window.ort.env.wasm.wasmPaths = "https://cdn.jsdelivr.net/npm/onnxruntime-web@1.14.0/dist/";
      }

      console.log('Initializing @ricky0123/vad-web MicVAD...');
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
          console.log('[VAD] Speech started');
          this._isSpeaking = true;
          this._chunkBuffer = [...this._preSpeechBuffer];
          this._preSpeechBuffer = [];
          if (this.isRecording) {
            this.onSpeechStart();
            this._flushChunkBuffer();
          }
        },

        onSpeechEnd: (audio) => {
          console.log(`[VAD] Speech ended`);
          this._isSpeaking = false;
          
          if (this.isRecording) {
            // Flush any remaining audio in the buffer
            this._flushBuffer();
            this.onSpeechEnd(audio);
          }
        },

        onFrameProcessed: (probabilities, frame) => {
          if (!this.isRecording) return;
          
          // Apply 85Hz High-Pass Filter to remove low-frequency room rumble
          const cleanFrame = this._applyHighPassFilter(frame);

          // Estimate volume from the filtered frame
          let sum = 0;
          for (let i = 0; i < cleanFrame.length; i++) {
            sum += Math.abs(cleanFrame[i]);
          }
          const avgVolume = sum / cleanFrame.length;
          this.onVolumeLevel(Math.min(1, avgVolume * 5));

          // If speaking, accumulate frames and send chunks
          if (this._isSpeaking) {
            const pcmData = this._float32ToInt16(cleanFrame);
            this._chunkBuffer.push(...pcmData);

            while (this._chunkBuffer.length >= this.bufferSize * 2) { // 2 bytes per sample
              const chunk = new Uint8Array(
                this._chunkBuffer.splice(0, this.bufferSize * 2)
              );
              this.onAudioChunk(chunk.buffer);
            }
          } else {
            // Keep a pre-roll buffer of the last ~300ms
            const pcmData = this._float32ToInt16(cleanFrame);
            this._preSpeechBuffer.push(...pcmData);
            
            // Keep max 40 frames worth of samples (~1.2 seconds)
            const maxPreSpeechSamples = cleanFrame.length * 40;
            if (this._preSpeechBuffer.length > maxPreSpeechSamples) {
              this._preSpeechBuffer.splice(0, this._preSpeechBuffer.length - maxPreSpeechSamples);
            }
          }
        },
      });

      console.log('MicVAD initialized successfully.');
      return true;
    } catch (error) {
      console.error('AudioProcessor (vad-web) initialization failed:', error);
      return false;
    }
  }

  _flushChunkBuffer() {
    while (this._chunkBuffer.length >= this.bufferSize * 2) {
      const chunk = new Uint8Array(
        this._chunkBuffer.splice(0, this.bufferSize * 2)
      );
      this.onAudioChunk(chunk.buffer);
    }
  }

  _flushBuffer() {
    if (this._chunkBuffer.length > 0) {
      const chunk = new Uint8Array(this._chunkBuffer);
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
    this.vadInstance.start();
    console.log('[AudioProcessor] Started');
  }

  stop() {
    this.isRecording = false;
    this._isSpeaking = false;
    this._chunkBuffer = [];
    this._preSpeechBuffer = [];
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
    return this._isSpeaking;
  }
}
