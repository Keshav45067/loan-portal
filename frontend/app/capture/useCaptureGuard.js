import { useState, useEffect, useRef } from 'react';

// Explicit UI states
const ST_SEARCHING = 'SEARCHING';
const ST_DETECTED_FAR = 'DETECTED_FAR';
const ST_ALIGNING = 'ALIGNING';
const ST_TOO_DARK = 'TOO_DARK';
const ST_TOO_BRIGHT = 'TOO_BRIGHT';
const ST_BLURRY = 'BLURRY';
const ST_STABLE = 'STABLE';

export default function useCaptureGuard(videoRef, active, orientation = 'landscape') {
  const [cvLoaded, setCvLoaded] = useState(false);
  const [cvLoadingError, setCvLoadingError] = useState(false);
  
  const [guardState, setGuardState] = useState({
    brightness: 0.5,
    blur: 0,
    coverage: 0,
    isStable: false,
    documentQuad: null, // Smoothed array of 4 points {x, y}
    overallReady: false,
    statusText: 'Initializing camera...',
    statusColor: '#94a3b8' // slate
  });

  // Keep state machine variables in refs to avoid stale closures
  const stateMachineRef = useRef({
    currentState: ST_SEARCHING,
    lastStateChangeTime: 0,
    
    // Metric hysteresis states
    isDetected: false,
    isInFarState: true,
    isInDarkState: false,
    isInBrightState: false,
    isInBlurryState: false,
    isInStableState: false,

    // Hit/Miss counters for stable promotion/demotion
    detectionHits: 0,
    detectionMisses: 0,
    farHits: 0,
    farMisses: 0,
    darkHits: 0,
    darkMisses: 0,
    brightHits: 0,
    brightMisses: 0,
    blurryHits: 0,
    blurryMisses: 0,
    stableHits: 0,
    stableMisses: 0,

    // Smoothed quad coordinates (EMA)
    smoothedQuad: null
  });

  const lastCentroidRef = useRef(null);
  const animationFrameRef = useRef(null);
  const offscreenCanvasRef = useRef(null);
  
  // Decoupled loop timing variables
  const lastDetectionTimeRef = useRef(0);
  const throttleIntervalRef = useRef(200); // starts at 200ms
  const executionTimesRef = useRef([]);

  // Load OpenCV.js dynamically
  useEffect(() => {
    if (typeof window === 'undefined') return;
    if (window.cv) {
      setCvLoaded(true);
      return;
    }

    const scriptId = 'opencv-js-cdn';
    let script = document.getElementById(scriptId);
    
    if (!script) {
      script = document.createElement('script');
      script.id = scriptId;
      script.src = 'https://docs.opencv.org/4.5.4/opencv.js';
      script.async = true;
      script.onload = () => {
        if (window.cv && window.cv.Mat) {
          setCvLoaded(true);
        } else {
          window.Module = window.Module || {};
          window.Module.onRuntimeInitialized = () => {
            setCvLoaded(true);
          };
        }
      };
      script.onerror = () => {
        console.error('Failed to load OpenCV.js');
        setCvLoadingError(true);
      };
      document.body.appendChild(script);
    } else {
      const checkCv = setInterval(() => {
        if (window.cv && window.cv.Mat) {
          setCvLoaded(true);
          clearInterval(checkCv);
        }
      }, 100);
      return () => clearInterval(checkCv);
    }
  }, []);

  // Handle visibility change to pause detection when tab is backgrounded
  useEffect(() => {
    const handleVisibilityChange = () => {
      if (document.hidden) {
        // Reset state machine on backgrounding
        stateMachineRef.current.currentState = ST_SEARCHING;
        stateMachineRef.current.isDetected = false;
        stateMachineRef.current.smoothedQuad = null;
        stateMachineRef.current.detectionHits = 0;
        stateMachineRef.current.detectionMisses = 0;
      }
    };
    document.addEventListener('visibilitychange', handleVisibilityChange);
    return () => {
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  }, []);

  // Decoupled Frame Analysis Loop
  useEffect(() => {
    if (!cvLoaded || !active || !videoRef.current) {
      if (animationFrameRef.current) {
        cancelAnimationFrame(animationFrameRef.current);
      }
      return;
    }

    const video = videoRef.current;
    
    if (!offscreenCanvasRef.current) {
      offscreenCanvasRef.current = document.createElement('canvas');
    }
    const canvas = offscreenCanvasRef.current;
    const ctx = canvas.getContext('2d', { willReadFrequently: true });

    const processFrame = () => {
      if (video.paused || video.ended || video.readyState < 2) {
        animationFrameRef.current = requestAnimationFrame(processFrame);
        return;
      }

      const cv = window.cv;
      if (!cv || !cv.Mat) {
        animationFrameRef.current = requestAnimationFrame(processFrame);
        return;
      }

      const now = performance.now();
      const throttleInterval = throttleIntervalRef.current;

      // Only run heavy detection at decoupled interval
      if (now - lastDetectionTimeRef.current >= throttleInterval) {
        const startExecution = performance.now();

        try {
          const width = 320; // Downsample for processing speed
          const height = Math.floor(video.videoHeight * (width / video.videoWidth)) || 240;
          
          canvas.width = width;
          canvas.height = height;
          ctx.drawImage(video, 0, 0, width, height);

          const imgData = ctx.getImageData(0, 0, width, height);
          const src = cv.matFromImageData(imgData);
          
          // 1. Grayscale Conversion
          const gray = new cv.Mat();
          cv.cvtColor(src, gray, cv.COLOR_RGBA2GRAY);

          // 2. Brightness Metric
          const mean = cv.mean(gray)[0] / 255.0;

          // 3. Blur Metric (Laplacian Variance)
          const laplacian = new cv.Mat();
          cv.Laplacian(gray, laplacian, cv.CV_64F, 1);
          const meanStd = new cv.Mat();
          const stddev = new cv.Mat();
          cv.meanStdDev(laplacian, meanStd, stddev);
          const stdVal = stddev.doubleAt(0, 0);
          const blurScore = stdVal * stdVal;

          // 4. Document Contours / Quadrilateral Detection
          const blurred = new cv.Mat();
          cv.GaussianBlur(gray, blurred, new cv.Size(5, 5), 0);
          
          const edges = new cv.Mat();
          cv.Canny(blurred, edges, 40, 120, 3); // Wider thresholds to pick up more faint edges

          // Add morphological operations to connect broken lines
          const kernel = cv.Mat.ones(5, 5, cv.CV_8U);
          cv.dilate(edges, edges, kernel, new cv.Point(-1, -1), 1);
          cv.erode(edges, edges, kernel, new cv.Point(-1, -1), 1);
          kernel.delete();

          const contours = new cv.MatVector();
          const hierarchy = new cv.Mat();
          cv.findContours(edges, contours, hierarchy, cv.RETR_LIST, cv.CHAIN_APPROX_SIMPLE);

          const totalArea = width * height;
          const minArea = totalArea * 0.10; // Must be at least 10% of screen to be a document
          const maxArea = totalArea * 0.95; // Reject if it spans the whole screen border

          const contourList = [];
          for (let i = 0; i < contours.size(); ++i) {
            const contour = contours.get(i);
            const area = cv.contourArea(contour);
            if (area >= minArea && area <= maxArea) {
              contourList.push({ contour, area, index: i });
            }
          }
          // Sort by largest area first
          contourList.sort((a, b) => b.area - a.area);

          let documentQuad = null;
          let coverage = 0;

          for (const item of contourList) {
            const contour = item.contour;
            const peri = cv.arcLength(contour, true);
            const approx = new cv.Mat();
            
            let foundQuad = false;
            // Scan epsilons to find clean 4 corners
            for (let eps = 0.02; eps <= 0.08; eps += 0.01) {
              cv.approxPolyDP(contour, approx, eps * peri, true);
              if (approx.rows === 4) {
                if (cv.isContourConvex(approx)) {
                  // Angle check
                  let maxCos = 0;
                  const pts = [];
                  for (let j = 0; j < 4; j++) {
                    pts.push({
                      x: approx.data32S[j * 2],
                      y: approx.data32S[j * 2 + 1]
                    });
                  }
                  for (let j = 0; j < 4; j++) {
                    const pt0 = pts[j];
                    const pt1 = pts[(j + 1) % 4];
                    const pt2 = pts[(j + 2) % 4];
                    
                    const dx1 = pt1.x - pt0.x;
                    const dy1 = pt1.y - pt0.y;
                    const dx2 = pt2.x - pt0.x;
                    const dy2 = pt2.y - pt0.y;
                    
                    const len1 = Math.sqrt(dx1 * dx1 + dy1 * dy1);
                    const len2 = Math.sqrt(dx2 * dx2 + dy2 * dy2);
                    const cos = (dx1 * dx2 + dy1 * dy2) / (len1 * len2 + 1e-10);
                    maxCos = Math.max(maxCos, Math.abs(cos));
                  }
                  
                  // If max cosine is small enough, it's a good quad (~ > 70 deg)
                  if (maxCos < 0.35) {
                    foundQuad = true;
                    break;
                  }
                }
              }
            }

            if (foundQuad) {
              coverage = item.area / totalArea;
              const points = [];
              for (let i = 0; i < 4; i++) {
                points.push({
                  x: approx.data32S[i * 2] / width,
                  y: approx.data32S[i * 2 + 1] / height
                });
              }
              // Sort points clockwise (top left, top right, bottom right, bottom left)
              points.sort((a, b) => a.y - b.y);
              const top = points.slice(0, 2).sort((a, b) => a.x - b.x);
              const bottom = points.slice(2, 4).sort((a, b) => b.x - a.x);
              documentQuad = [top[0], top[1], bottom[0], bottom[1]];
              approx.delete();
              break; // Found our document
            }
            approx.delete();
          }

          // --- Finite State Machine & Hysteresis Logic ---
          const sm = stateMachineRef.current;

          // A. Document Detection Hysteresis
          if (documentQuad) {
            sm.detectionHits += 1;
            sm.detectionMisses = 0;
            if (sm.detectionHits >= 3) {
              sm.isDetected = true;
            }
          } else {
            sm.detectionMisses += 1;
            sm.detectionHits = 0;
            if (sm.detectionMisses >= 8) { // demote slowly
              sm.isDetected = false;
              sm.smoothedQuad = null;
            }
          }

          // B. Coverage (Move Closer) Hysteresis
          if (sm.isDetected) {
            if (sm.isInFarState) {
              if (coverage >= 0.16) sm.farHits += 1;
              else sm.farHits = 0;
              if (sm.farHits >= 2) sm.isInFarState = false;
            } else {
              if (coverage < 0.10) sm.farMisses += 1;
              else sm.farMisses = 0;
              if (sm.farMisses >= 3) sm.isInFarState = true;
            }
          }

          // C. Brightness Hysteresis (Too Dark / Too Bright)
          if (sm.isDetected) {
            // Dark State
            if (sm.isInDarkState) {
              if (mean >= 0.28) sm.darkHits += 1;
              else sm.darkHits = 0;
              if (sm.darkHits >= 3) sm.isInDarkState = false;
            } else {
              if (mean < 0.22) sm.darkMisses += 1;
              else sm.darkMisses = 0;
              if (sm.darkMisses >= 3) sm.isInDarkState = true;
            }

            // Bright State
            if (sm.isInBrightState) {
              if (mean <= 0.77) sm.brightHits += 1;
              else sm.brightHits = 0;
              if (sm.brightHits >= 3) sm.isInBrightState = false;
            } else {
              if (mean > 0.82) sm.brightMisses += 1;
              else sm.brightMisses = 0;
              if (sm.brightMisses >= 3) sm.isInBrightState = true;
            }
          }

          // D. Blur Hysteresis
          if (sm.isDetected) {
            if (sm.isInBlurryState) {
              if (blurScore >= 130.0) sm.blurryHits += 1;
              else sm.blurryHits = 0;
              if (sm.blurryHits >= 3) sm.isInBlurryState = false;
            } else {
              if (blurScore < 100.0) sm.blurryMisses += 1;
              else sm.blurryMisses = 0;
              if (sm.blurryMisses >= 3) sm.isInBlurryState = true;
            }
          }

          // E. Stability Hysteresis
          let motion = 1.0;
          if (documentQuad) {
            const centroidX = documentQuad.reduce((sum, p) => sum + p.x, 0) / 4;
            const centroidY = documentQuad.reduce((sum, p) => sum + p.y, 0) / 4;
            const currentCentroid = { x: centroidX, y: centroidY };

            if (lastCentroidRef.current) {
              const dx = currentCentroid.x - lastCentroidRef.current.x;
              const dy = currentCentroid.y - lastCentroidRef.current.y;
              motion = Math.sqrt(dx * dx + dy * dy);
            }
            lastCentroidRef.current = currentCentroid;
          } else {
            lastCentroidRef.current = null;
          }

          if (sm.isDetected) {
            if (sm.isInStableState) {
              if (motion >= 0.025) sm.stableMisses += 1;
              else sm.stableMisses = 0;
              if (sm.stableMisses >= 2) sm.isInStableState = false;
            } else {
              if (motion < 0.015) sm.stableHits += 1;
              else sm.stableHits = 0;
              if (sm.stableHits >= 3) sm.isInStableState = true;
            }
          }

          // F. Exponential Moving Average (EMA) for outline smoothing
          if (documentQuad) {
            if (!sm.smoothedQuad) {
              // Snap immediately on first detection to avoid lagging box entry
              sm.smoothedQuad = documentQuad;
            } else {
              sm.smoothedQuad = sm.smoothedQuad.map((prevPt, idx) => ({
                x: prevPt.x * 0.70 + documentQuad[idx].x * 0.30,
                y: prevPt.y * 0.70 + documentQuad[idx].y * 0.30
              }));
            }
          }

          // G. Priority-based State Resolver
          let nextState = ST_SEARCHING;
          let statusText = 'Searching for document...';
          let statusColor = '#94a3b8'; // slate

          if (!sm.isDetected) {
            nextState = ST_SEARCHING;
            statusText = 'Searching for document...';
            statusColor = '#94a3b8';
          } else if (sm.isInFarState) {
            nextState = ST_DETECTED_FAR;
            statusText = '📐 Move closer to fill the guide';
            statusColor = '#3b82f6'; // blue
          } else if (sm.isInDarkState) {
            nextState = ST_TOO_DARK;
            statusText = '🔆 Too dark — move to a well-lit area';
            statusColor = '#f59e0b'; // amber
          } else if (sm.isInBrightState) {
            nextState = ST_TOO_BRIGHT;
            statusText = '🔆 Too bright — avoid direct glare';
            statusColor = '#f59e0b'; // amber
          } else if (sm.isInBlurryState) {
            nextState = ST_BLURRY;
            statusText = '📷 Blurry — hold camera steady';
            statusColor = '#ef4444'; // red
          } else if (!sm.isInStableState) {
            nextState = ST_ALIGNING;
            statusText = '⏳ Hold steady...';
            statusColor = '#f59e0b'; // amber
          } else {
            nextState = ST_STABLE;
            statusText = '⚡ Ready! Capture starting...';
            statusColor = '#10b981'; // emerald
          }

          // Enforce Minimum Dwell Time of 400ms per state change (except when transitioning out of ST_SEARCHING)
          if (nextState !== sm.currentState) {
            if (sm.currentState === ST_SEARCHING || now - sm.lastStateChangeTime >= 400) {
              sm.currentState = nextState;
              sm.lastStateChangeTime = now;
            } else {
              // Retain current resolved state to avoid flickering
              nextState = sm.currentState;
            }
          }

          const overallReady = (sm.currentState === ST_STABLE);

          // Update React State
          setGuardState({
            brightness: mean,
            blur: blurScore,
            coverage: coverage,
            isStable: sm.isInStableState,
            documentQuad: sm.smoothedQuad,
            overallReady,
            statusText,
            statusColor
          });

          // Cleanup cv mats
          src.delete();
          gray.delete();
          laplacian.delete();
          meanStd.delete();
          stddev.delete();
          blurred.delete();
          edges.delete();
          contours.delete();
          hierarchy.delete();

        } catch (err) {
          console.error('Error during frame analysis:', err);
        }

        const endExecution = performance.now();
        const duration = endExecution - startExecution;

        // Adaptive Throttling: track execution times and back off frequency if slow
        const execs = executionTimesRef.current;
        execs.push(duration);
        if (execs.length > 5) execs.shift();
        const avgDuration = execs.reduce((a, b) => a + b, 0) / execs.length;

        if (avgDuration > 100) {
          throttleIntervalRef.current = Math.min(600, throttleIntervalRef.current + 50);
        } else if (avgDuration < 30) {
          throttleIntervalRef.current = Math.max(150, throttleIntervalRef.current - 20);
        }

        lastDetectionTimeRef.current = now;
      }

      animationFrameRef.current = requestAnimationFrame(processFrame);
    };

    animationFrameRef.current = requestAnimationFrame(processFrame);

    return () => {
      if (animationFrameRef.current) {
        cancelAnimationFrame(animationFrameRef.current);
      }
    };
  }, [cvLoaded, active, videoRef, orientation]);

  return {
    cvLoaded,
    cvLoadingError,
    ...guardState
  };
}
