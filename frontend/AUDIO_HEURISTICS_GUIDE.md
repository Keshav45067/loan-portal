# Background Noise & Audio Triage Heuristics Guide

This document explains the mathematical formulas, algorithms, and state machines used in the client-side audio triage and ambient noise detection pipeline.

---

## 1. Pre-Filtering: 85 Hz IIR High-Pass Filter

Raw microphone samples undergo 1st-order IIR (Infinite Impulse Response) filtering before any energy calculation:

```text
Formula:
y[n] = 0.9677 * (y[n-1] + x[n] - x[n-1])

Where:
- x[n] = Current incoming raw audio sample
- x[n-1] = Previous raw audio sample
- y[n] = Current filtered audio sample
- y[n-1] = Previous filtered output sample
- alpha = 0.9677 (Corresponds to ~85 Hz cut-off at 16,000 Hz sample rate)
```

### Why it is used:
- Eliminates sub-audible mechanical rumblings (table vibrations, finger taps on the phone/laptop body).
- Strips 50 Hz / 60 Hz electrical AC hum from cheap power adapters and HVAC drone.
- Prevents sub-bass frequencies from artificially inflating RMS energy values.

---

## 2. Speech Isolation: Ambient Noise vs. User Voice

To ensure the user's voice is never mistakenly classified as "background noise":

1. Each frame is analyzed by Silero VAD (512 samples ≈ 32 ms).
2. **If VAD detects active speech (`vadSpeechActive == true`)**:
   - Ambient noise sampling is **completely paused**.
3. **If VAD detects silence/noise (`vadSpeechActive == false`)**:
   - The frame's clean RMS energy is measured and stored.

```text
Per-Frame RMS Formula:
RMS = sqrt( (1 / N) * sum(x[i]^2) )

Where:
- N = 512 samples in the frame
- x[i] = Value of sample i in the range [-1.0, 1.0]
```

---

## 3. Ambient Noise Rolling Average Buffer

To prevent transient noises (such as a single pen drop or mouse click) from triggering a false alert, the engine maintains a sliding FIFO buffer:

- **Buffer Size**: 150 non-speech frames (~4.8 seconds of ambient room sound).

```text
Rolling Ambient RMS:
Ambient_RMS = (RMS_1 + RMS_2 + ... + RMS_K) / K

Where:
- K = Number of non-speech frames in history (up to 150)
```

---

## 4. Dual-Threshold Hysteresis (Schmitt Trigger)

To prevent the alert from flickering on and off when ambient noise hovers near the boundary, a hysteresis corridor with two distinct thresholds is used:

```text
Ambient Energy Level
  │
  ├─ 0.0080 (High Noise Threshold) ────► [ALERT TURNS ON: active = true] ⚠️
  │   ▲
  │   │  (Hysteresis Deadband — Alert remains visible)
  │   ▼
  ├─ 0.0060 (Recovery Threshold = 0.75 * 0.0080) ────► [ALERT TURNS OFF: active = false] ✅
  │
  └─────────────────────────────────────────────────────────────► Time
```

### Transition Rules:
1. **Activation (`active = true`)**:
   - `Ambient_RMS > 0.0080` AND history has at least 60 non-speech frames (~2.0 seconds of sustained room noise).
2. **Deactivation (`active = false`)**:
   - `Ambient_RMS <= 0.0060` (Noise dropped by at least 25% below the trigger line).
   - Once quiet, the alert immediately turns off.

---

## 5. Timing Safeguards & Debouncing

```text
+------------------------------------+-----------------------------------------------------+
| Safeguard                          | Purpose                                             |
+------------------------------------+-----------------------------------------------------+
| 3.0s Session Warmup Grace Period   | Ignores initial mic AGC (Auto Gain Control) spikes  |
| 1.5s Evaluation Interval           | Prevents rapid recalculations and UI flicker        |
| Minimum 60 Sampled Frames (~2.0s)  | Prevents short bursts (coughs, taps) from flagging  |
+------------------------------------+-----------------------------------------------------+
```

---

## 6. End-to-End System Workflow

```text
[Microphone Ingestion]
         │
         ▼
[85 Hz High-Pass Filter]
         │
         ▼
[Silero VAD Check]
   ├─ If Speaking: Process for Speech STT (Do not update ambient buffer)
   └─ If Non-Speaking:
         │
         ▼
   [Add frame RMS to Ambient Buffer (150 frames)]
         │
         ▼
   [Calculate Rolling Ambient RMS]
         │
   ┌─────┴──────────────────────────────┐
   │                                    │
   ▼                                    ▼
[Ambient_RMS > 0.0080]        [Ambient_RMS <= 0.0060]
(Sustained for > 2.0s)        (Noise subsided)
   │                                    │
   ▼                                    ▼
- Top Red UI Overlay Appears   - Top UI Overlay Clears
- WS sends: bg_noise:true      - WS sends: bg_noise:false
- Backend adapts nudges        - Backend returns to standard nudges
```
