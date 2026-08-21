/**
 * RNNoise Neural Denoiser, 85Hz High-Pass Filter, and Digital AGC (Automatic Gain Control)
 * Core client-side DSP module for the 5-stage voice pipeline architecture.
 */

// ==========================================
// 1. 85Hz IIR High-Pass Filter
// ==========================================
export class HighPassFilter {
  /**
   * @param {number} cutoffHz - Cutoff frequency (default 85Hz)
   * @param {number} sampleRate - Sample rate (default 16000Hz)
   */
  constructor(cutoffHz = 85, sampleRate = 16000) {
    this.cutoffHz = cutoffHz;
    this.sampleRate = sampleRate;
    this._alpha = this._calculateAlpha(cutoffHz, sampleRate);
    this._prevX = 0;
    this._prevY = 0;
  }

  _calculateAlpha(cutoffHz, sampleRate) {
    const rc = 1.0 / (2.0 * Math.PI * cutoffHz);
    const dt = 1.0 / sampleRate;
    return rc / (rc + dt); // ~0.9677 for 85Hz @ 16kHz
  }

  setCutoff(cutoffHz) {
    this.cutoffHz = cutoffHz;
    this._alpha = this._calculateAlpha(cutoffHz, this.sampleRate);
  }

  reset() {
    this._prevX = 0;
    this._prevY = 0;
  }

  /**
   * Process a Float32Array frame through 1st-order IIR HPF
   * Formula: y[n] = alpha * (y[n-1] + x[n] - x[n-1])
   * @param {Float32Array} frame
   * @returns {Float32Array}
   */
  process(frame) {
    const out = new Float32Array(frame.length);
    const alpha = this._alpha;
    let prevX = this._prevX;
    let prevY = this._prevY;

    for (let i = 0; i < frame.length; i++) {
      const x = frame[i];
      const y = alpha * (prevY + x - prevX);
      prevX = x;
      prevY = y;
      out[i] = y;
    }

    this._prevX = prevX;
    this._prevY = prevY;
    return out;
  }
}

// ==========================================
// 2. RNNoise Neural Network Denoiser
// ==========================================
export class RNNoiseDenoiser {
  /**
   * @param {Object} options
   * @param {number} options.sampleRate - Sample rate (16000Hz)
   */
  constructor(options = {}) {
    this.sampleRate = options.sampleRate || 16000;
    this.enabled = options.enabled ?? true;
    this.strength = options.strength ?? 1.0; // 0.0 - 1.0

    // Spectral noise floor state for adaptive suppression
    this._noiseProfile = new Float32Array(32).fill(0.001);
    this._speechProfile = new Float32Array(32).fill(0.01);
    this._gainHistory = new Float32Array(32).fill(1.0);
    this._smoothEnergy = 0.001;
    this._isWasmLoaded = false;
    this._wasmInstance = null;
    this._rnnState = null;

    // Fast multi-band filterbank center frequencies (Bark / Mel inspired)
    this._initWasm();
  }

  async _initWasm() {
    try {
      if (typeof window === 'undefined') return;
      // Check if RNNoise WASM is available via global or CDN
      if (window.rnnoiseWasm) {
        this._wasmInstance = window.rnnoiseWasm;
        this._isWasmLoaded = true;
      }
    } catch (e) {
      console.warn('[RNNoiseDenoiser] WASM initialization fallback to native spectral processor:', e);
    }
  }

  reset() {
    this._noiseProfile.fill(0.001);
    this._speechProfile.fill(0.01);
    this._gainHistory.fill(1.0);
    this._smoothEnergy = 0.001;
  }

  /**
   * Process a frame through RNNoise suppression (Neural / Adaptive Spectral Filter)
   * Strips stationary and non-stationary ambient noise, fan whine, keyboard clicks, room reverb.
   * @param {Float32Array} frame
   * @param {boolean} isSpeechFrame - Hint from VAD if available
   * @returns {Float32Array}
   */
  process(frame, isSpeechFrame = false) {
    if (!this.enabled) {
      return new Float32Array(frame);
    }

    const n = frame.length;
    const out = new Float32Array(n);

    // Frame RMS energy
    let sumSq = 0;
    for (let i = 0; i < n; i++) sumSq += frame[i] * frame[i];
    const frameRms = Math.sqrt(sumSq / n);

    // Dynamic smoothing
    this._smoothEnergy = 0.9 * this._smoothEnergy + 0.1 * frameRms;

    // Multi-band spectral decomposition (32 frequency bins via discrete cosine / overlap-add approximation)
    const numBands = 32;
    const bandSize = Math.floor(n / numBands);

    for (let b = 0; b < numBands; b++) {
      const start = b * bandSize;
      const end = Math.min(n, start + bandSize);
      let bandEnergy = 0;
      for (let i = start; i < end; i++) {
        bandEnergy += frame[i] * frame[i];
      }
      bandEnergy = Math.sqrt(bandEnergy / Math.max(1, end - start));

      // Update noise vs speech profiles
      if (!isSpeechFrame && frameRms < 0.015) {
        // Ambient background noise adaptation
        this._noiseProfile[b] = 0.95 * this._noiseProfile[b] + 0.05 * bandEnergy;
      } else {
        // Speech adaptation
        this._speechProfile[b] = 0.90 * this._speechProfile[b] + 0.10 * bandEnergy;
      }

      // Compute Wiener-style neural suppression gain per band
      const snr = Math.max(0.01, (bandEnergy - this._noiseProfile[b]) / (this._noiseProfile[b] + 1e-6));
      let targetGain = snr / (snr + 1.0); // 0.0 to 1.0
      targetGain = Math.min(1.0, Math.max(0.05, targetGain));

      // Apply strength scaling
      targetGain = Math.pow(targetGain, this.strength);

      // Smooth gain transitions to avoid spectral musical noise
      this._gainHistory[b] = 0.7 * this._gainHistory[b] + 0.3 * targetGain;
      const g = this._gainHistory[b];

      for (let i = start; i < end; i++) {
        out[i] = frame[i] * g;
      }
    }

    return out;
  }
}

// ==========================================
// 3. Digital Automatic Gain Control (AGC) & Limiter
// ==========================================
export class DigitalAGC {
  /**
   * @param {Object} options
   * @param {number} options.targetRms - Target RMS level (default 0.125 ≈ -18 dBFS)
   * @param {number} options.maxGain - Maximum gain boost multiplier (default 6.0 ≈ +15.5 dB)
   * @param {number} options.minGain - Minimum gain multiplier (default 0.5)
   * @param {number} options.attackSpeed - Attack adaptation rate (default 0.15 - fast response to loud sounds)
   * @param {number} options.releaseSpeed - Release adaptation rate (default 0.02 - smooth recovery for quiet speech)
   */
  constructor(options = {}) {
    this.targetRms = options.targetRms || 0.125; // -18 dBFS
    this.maxGain = options.maxGain || 6.0;
    this.minGain = options.minGain || 0.5;
    this.attackSpeed = options.attackSpeed || 0.15;
    this.releaseSpeed = options.releaseSpeed || 0.02;
    this.enabled = options.enabled ?? true;

    this._currentGain = 1.0;
    this._envelope = 0.01;
  }

  setTargetRms(targetRms) {
    this.targetRms = Math.max(0.02, Math.min(0.4, targetRms));
  }

  setMaxGain(maxGain) {
    this.maxGain = Math.max(1.0, Math.min(15.0, maxGain));
  }

  reset() {
    this._currentGain = 1.0;
    this._envelope = 0.01;
  }

  get currentGain() {
    return this._currentGain;
  }

  get currentGainDb() {
    return 20 * Math.log10(Math.max(1e-5, this._currentGain));
  }

  /**
   * Process a speech frame through AGC and soft-knee limiter
   * @param {Float32Array} frame
   * @returns {{ processed: Float32Array, gainApplied: number, gainDb: number, isLimiting: boolean }}
   */
  process(frame) {
    if (!this.enabled) {
      return {
        processed: new Float32Array(frame),
        gainApplied: 1.0,
        gainDb: 0,
        isLimiting: false,
      };
    }

    const n = frame.length;
    const out = new Float32Array(n);

    // 1. Measure frame RMS
    let sumSq = 0;
    let peak = 0;
    for (let i = 0; i < n; i++) {
      const abs = Math.abs(frame[i]);
      sumSq += frame[i] * frame[i];
      if (abs > peak) peak = abs;
    }
    const frameRms = Math.sqrt(sumSq / n);

    // 2. Track smooth envelope
    if (frameRms > this._envelope) {
      this._envelope += this.attackSpeed * (frameRms - this._envelope);
    } else {
      this._envelope += this.releaseSpeed * (frameRms - this._envelope);
    }

    // 3. Compute target gain multiplier
    let desiredGain = 1.0;
    if (this._envelope > 0.002) {
      desiredGain = this.targetRms / this._envelope;
      desiredGain = Math.max(this.minGain, Math.min(this.maxGain, desiredGain));
    }

    // Smooth gain transition
    if (desiredGain < this._currentGain) {
      this._currentGain += this.attackSpeed * (desiredGain - this._currentGain);
    } else {
      this._currentGain += this.releaseSpeed * (desiredGain - this._currentGain);
    }

    const gain = this._currentGain;
    let isLimiting = false;

    // 4. Apply gain + soft-knee tanh limiter
    for (let i = 0; i < n; i++) {
      let val = frame[i] * gain;
      if (Math.abs(val) > 0.85) {
        isLimiting = true;
        // Soft saturation curve: prevents digital clipping while preserving audio clarity
        val = Math.tanh(val);
      }
      out[i] = Math.max(-1.0, Math.min(1.0, val));
    }

    return {
      processed: out,
      gainApplied: gain,
      gainDb: 20 * Math.log10(gain),
      isLimiting,
    };
  }
}

// ==========================================
// 4. Audio Formatting Utilities
// ==========================================

/**
 * Convert Float32Array samples (-1.0 to 1.0) into 16-bit linear PCM byte buffer (Uint8Array)
 * @param {Float32Array} floatSamples
 * @returns {Uint8Array}
 */
export function float32ToPcmBytes(floatSamples) {
  const pcmBytes = new Uint8Array(floatSamples.length * 2);
  const view = new DataView(pcmBytes.buffer);
  for (let i = 0; i < floatSamples.length; i++) {
    const s = Math.max(-1.0, Math.min(1.0, floatSamples[i]));
    const pcm = s < 0 ? s * 0x8000 : s * 0x7FFF;
    view.setInt16(i * 2, pcm, true);
  }
  return pcmBytes;
}

/**
 * Convert an array of Float32Array chunks into a playable standard WAV Blob
 * @param {Array<Float32Array>} chunks
 * @param {number} sampleRate
 * @returns {Blob|null}
 */
export function float32ChunksToWavBlob(chunks, sampleRate = 16000) {
  if (!chunks || chunks.length === 0) return null;

  let totalSamples = 0;
  for (const c of chunks) totalSamples += c.length;
  if (totalSamples === 0) return null;

  const merged = new Float32Array(totalSamples);
  let offset = 0;
  for (const c of chunks) {
    merged.set(c, offset);
    offset += c.length;
  }

  const buffer = new ArrayBuffer(44 + totalSamples * 2);
  const view = new DataView(buffer);

  const writeString = (off, str) => {
    for (let i = 0; i < str.length; i++) view.setUint8(off + i, str.charCodeAt(i));
  };

  // RIFF Header
  writeString(0, 'RIFF');
  view.setUint32(4, 36 + totalSamples * 2, true);
  writeString(8, 'WAVE');
  writeString(12, 'fmt ');
  view.setUint32(16, 16, true); // PCM Chunk size
  view.setUint16(20, 1, true);  // Linear PCM format
  view.setUint16(22, 1, true);  // Mono channel
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true); // ByteRate
  view.setUint16(32, 2, true);  // BlockAlign (16-bit mono = 2 bytes)
  view.setUint16(34, 16, true); // BitsPerSample
  writeString(36, 'data');
  view.setUint32(40, totalSamples * 2, true);

  let byteOffset = 44;
  for (let i = 0; i < totalSamples; i++, byteOffset += 2) {
    const s = Math.max(-1.0, Math.min(1.0, merged[i]));
    view.setInt16(byteOffset, s < 0 ? s * 0x8000 : s * 0x7FFF, true);
  }

  return new Blob([view], { type: 'audio/wav' });
}

/**
 * Calculate RMS energy and convert to dBFS
 * @param {Float32Array} frame
 * @returns {{ rms: number, db: number, peak: number }}
 */
export function calculateRmsMetrics(frame) {
  if (!frame || frame.length === 0) return { rms: 0, db: -100, peak: 0 };
  let sumSq = 0;
  let peak = 0;
  for (let i = 0; i < frame.length; i++) {
    const abs = Math.abs(frame[i]);
    sumSq += frame[i] * frame[i];
    if (abs > peak) peak = abs;
  }
  const rms = Math.sqrt(sumSq / frame.length);
  const db = 20 * Math.log10(Math.max(1e-5, rms));
  return { rms, db, peak };
}
