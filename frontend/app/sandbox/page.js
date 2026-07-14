'use client';

import { useState, useRef, useEffect } from 'react';
import useCaptureGuard from '../capture/useCaptureGuard';
import styles from './sandbox.module.css';

const DEFAULT_CONFIG = {
  cannyThresh1: 40,
  cannyThresh2: 120,
  useAdaptiveCanny: true,
  cannySigma: 0.33,
  minAreaPct: 0.03,
  maxAreaPct: 0.95,
  maxCos: 0.55,
  darkEnter: 0.30,
  darkExit: 0.35,
  brightEnter: 0.75,
  brightExit: 0.70,
  blurEnter: 20.0,
  blurExit: 35.0,
  minConfidence: 0.30,
  iouPreferenceWeight: 0.6,
};

export default function SandboxPage() {
  const videoRef = useRef(null);
  const [isStarted, setIsStarted] = useState(false);
  const [config, setConfig] = useState(DEFAULT_CONFIG);

  const captureState = useCaptureGuard(videoRef, isStarted, 'portrait', config);
  const cvLoaded = captureState.cvLoaded;

  const startCamera = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: 'environment', width: { ideal: 1920 }, height: { ideal: 1080 } },
        audio: false
      });
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        videoRef.current.onloadedmetadata = () => {
          videoRef.current.play();
          setIsStarted(true);
        };
      }
    } catch (err) {
      console.error("Failed to start camera", err);
      alert("Could not start camera for sandbox.");
    }
  };

  const stopCamera = () => {
    if (videoRef.current && videoRef.current.srcObject) {
      videoRef.current.srcObject.getTracks().forEach(t => t.stop());
    }
    setIsStarted(false);
  };

  useEffect(() => {
    return () => stopCamera();
  }, []);

  const handleChange = (key, value) => {
    setConfig(prev => ({ ...prev, [key]: parseFloat(value) }));
  };

  const handleToggle = (key) => {
    setConfig(prev => ({ ...prev, [key]: !prev[key] }));
  };

  const exportConfig = () => {
    console.log(JSON.stringify(config, null, 2));
    alert("Configuration copied to console!\n\n" + JSON.stringify(config, null, 2));
  };

  return (
    <div className={styles.container}>
      {/* CAMERA PREVIEW */}
      <div className={styles.cameraSection}>
        {!isStarted && (
          <div style={{ position: 'absolute', zIndex: 50 }}>
            <button className={styles.btnPrimary} onClick={startCamera} style={{ padding: '16px 32px', fontSize: '1.2rem', borderRadius: '999px', border: 'none', cursor: 'pointer' }}>
              Start Camera
            </button>
          </div>
        )}
        
        <video ref={videoRef} autoPlay playsInline muted className={styles.videoElement} style={{ display: isStarted ? 'block' : 'none' }} />
        
        {isStarted && captureState.documentQuad && (
          <svg className={styles.overlaySvg} viewBox="0 0 1000 1000" preserveAspectRatio="none">
            <polygon
              points={captureState.documentQuad.map(p => `${Math.round(p.x * 1000)},${Math.round(p.y * 1000)}`).join(' ')}
              className={`${styles.detectedPoly} ${captureState.overallReady ? styles.detectedPolyReady : ''}`}
            />
            {captureState.documentQuad.map((p, i) => (
              <circle
                key={i}
                cx={Math.round(p.x * 1000)}
                cy={Math.round(p.y * 1000)}
                r="8"
                fill={captureState.overallReady ? '#10b981' : 'rgba(255,255,255,0.9)'}
              />
            ))}
          </svg>
        )}

        {isStarted && (
          <div className={styles.statusBadge} style={{ color: captureState.statusColor !== '#94a3b8' ? captureState.statusColor : '#000' }}>
            <span>{captureState.statusText}</span>
            {captureState.statusDetail && <span style={{ fontSize: '0.72rem', color: '#64748b', fontWeight: 400 }}>{captureState.statusDetail}</span>}
          </div>
        )}
      </div>

      {/* CONTROL PANEL */}
      <div className={styles.sidebar}>
        <div className={styles.sidebarHeader}>
          <h2>Detection Sandbox</h2>
          <p>Tune OpenCV parameters in real-time</p>
        </div>

        <div className={styles.controlGroup}>
          <div className={styles.groupTitle}>Edge Detection (Canny)</div>
          <div className={styles.sliderRow}>
            <div className={styles.sliderLabel}>
              <span>Adaptive Canny (Otsu)</span>
              <button onClick={() => handleToggle('useAdaptiveCanny')} style={{ background: config.useAdaptiveCanny ? '#10b981' : '#475569', color: '#fff', border: 'none', borderRadius: '4px', padding: '2px 8px', cursor: 'pointer', fontSize: '0.75rem' }}>
                {config.useAdaptiveCanny ? 'ON' : 'OFF'}
              </button>
            </div>
          </div>
          {!config.useAdaptiveCanny && (
            <>
              <div className={styles.sliderRow}>
                <div className={styles.sliderLabel}><span>Threshold 1 (Min)</span> <span className={styles.sliderValue}>{config.cannyThresh1}</span></div>
                <input type="range" min="0" max="255" step="1" className={styles.slider} value={config.cannyThresh1} onChange={e => handleChange('cannyThresh1', e.target.value)} />
              </div>
              <div className={styles.sliderRow}>
                <div className={styles.sliderLabel}><span>Threshold 2 (Max)</span> <span className={styles.sliderValue}>{config.cannyThresh2}</span></div>
                <input type="range" min="0" max="255" step="1" className={styles.slider} value={config.cannyThresh2} onChange={e => handleChange('cannyThresh2', e.target.value)} />
              </div>
            </>
          )}
          {config.useAdaptiveCanny && (
            <div className={styles.sliderRow}>
              <div className={styles.sliderLabel}><span>Canny Sigma</span> <span className={styles.sliderValue}>{config.cannySigma}</span></div>
              <input type="range" min="0.1" max="0.8" step="0.01" className={styles.slider} value={config.cannySigma} onChange={e => handleChange('cannySigma', e.target.value)} />
            </div>
          )}
        </div>

        <div className={styles.controlGroup}>
          <div className={styles.groupTitle}>Geometry</div>
          <div className={styles.sliderRow}>
            <div className={styles.sliderLabel}><span>Max Cosine (Perspective)</span> <span className={styles.sliderValue}>{config.maxCos}</span></div>
            <input type="range" min="0.1" max="1.0" step="0.05" className={styles.slider} value={config.maxCos} onChange={e => handleChange('maxCos', e.target.value)} />
          </div>
          <div className={styles.sliderRow}>
            <div className={styles.sliderLabel}><span>Min Area (%)</span> <span className={styles.sliderValue}>{Math.round(config.minAreaPct * 100)}%</span></div>
            <input type="range" min="0.01" max="0.5" step="0.01" className={styles.slider} value={config.minAreaPct} onChange={e => handleChange('minAreaPct', e.target.value)} />
          </div>
          <div className={styles.sliderRow}>
            <div className={styles.sliderLabel}><span>Max Area (%)</span> <span className={styles.sliderValue}>{Math.round(config.maxAreaPct * 100)}%</span></div>
            <input type="range" min="0.5" max="1.0" step="0.01" className={styles.slider} value={config.maxAreaPct} onChange={e => handleChange('maxAreaPct', e.target.value)} />
          </div>
        </div>

        <div className={styles.controlGroup}>
          <div className={styles.groupTitle}>Confidence &amp; Tracking</div>
          <div className={styles.sliderRow}>
            <div className={styles.sliderLabel}><span>Min Confidence</span> <span className={styles.sliderValue}>{config.minConfidence}</span></div>
            <input type="range" min="0.05" max="0.8" step="0.05" className={styles.slider} value={config.minConfidence} onChange={e => handleChange('minConfidence', e.target.value)} />
          </div>
          <div className={styles.sliderRow}>
            <div className={styles.sliderLabel}><span>IoU Preference Weight</span> <span className={styles.sliderValue}>{config.iouPreferenceWeight}</span></div>
            <input type="range" min="0" max="1.0" step="0.05" className={styles.slider} value={config.iouPreferenceWeight} onChange={e => handleChange('iouPreferenceWeight', e.target.value)} />
          </div>
        </div>

        <div className={styles.controlGroup}>
          <div className={styles.groupTitle}>Blur Detection</div>
          <div className={styles.sliderRow}>
            <div className={styles.sliderLabel}><span>Enter Blur (Lower = sharper)</span> <span className={styles.sliderValue}>{config.blurEnter}</span></div>
            <input type="range" min="5" max="150" step="1" className={styles.slider} value={config.blurEnter} onChange={e => handleChange('blurEnter', e.target.value)} />
          </div>
          <div className={styles.sliderRow}>
            <div className={styles.sliderLabel}><span>Exit Blur</span> <span className={styles.sliderValue}>{config.blurExit}</span></div>
            <input type="range" min="5" max="150" step="1" className={styles.slider} value={config.blurExit} onChange={e => handleChange('blurExit', e.target.value)} />
          </div>
        </div>

        <div className={styles.controlGroup}>
          <div className={styles.groupTitle}>Lighting</div>
          <div className={styles.sliderRow}>
            <div className={styles.sliderLabel}><span>Dark Enter</span> <span className={styles.sliderValue}>{config.darkEnter}</span></div>
            <input type="range" min="0.05" max="0.5" step="0.01" className={styles.slider} value={config.darkEnter} onChange={e => handleChange('darkEnter', e.target.value)} />
          </div>
          <div className={styles.sliderRow}>
            <div className={styles.sliderLabel}><span>Bright Enter</span> <span className={styles.sliderValue}>{config.brightEnter}</span></div>
            <input type="range" min="0.5" max="0.95" step="0.01" className={styles.slider} value={config.brightEnter} onChange={e => handleChange('brightEnter', e.target.value)} />
          </div>
        </div>

        <div className={styles.controlGroup}>
          <div className={styles.groupTitle}>Live Engine Metrics</div>
          <div className={styles.statsBox}>
            <div className={styles.statsRow}><span>OpenCV Loaded:</span> <span style={{ color: cvLoaded ? '#10b981' : '#ef4444' }}>{cvLoaded ? 'YES' : 'NO'}</span></div>
            <div className={styles.statsRow}><span>Brightness (mean):</span> <span style={{ color: '#f8fafc' }}>{captureState.brightness?.toFixed(3)}</span></div>
            <div className={styles.statsRow}><span>Blur Variance:</span> <span style={{ color: '#f8fafc' }}>{captureState.blur?.toFixed(1)}</span></div>
            <div className={styles.statsRow}><span>Coverage:</span> <span style={{ color: '#f8fafc' }}>{((captureState.coverage || 0) * 100).toFixed(1)}%</span></div>
            <div className={styles.statsRow}><span>Confidence:</span> <span style={{ color: captureState.confidence > 0.5 ? '#10b981' : '#f59e0b' }}>{((captureState.confidence || 0) * 100).toFixed(0)}%</span></div>
            <div className={styles.statsRow}><span>Readiness:</span> <span style={{ color: '#f8fafc' }}>{((captureState.readinessScore || 0) * 100).toFixed(0)}%</span></div>
          </div>
        </div>

        <div className={styles.buttonRow}>
          <button className={styles.btn + ' ' + styles.btnSecondary} onClick={() => setConfig(DEFAULT_CONFIG)}>Reset</button>
          <button className={styles.btn + ' ' + styles.btnPrimary} onClick={exportConfig}>Export JSON</button>
        </div>
      </div>
    </div>
  );
}
