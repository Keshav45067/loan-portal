import { useState, useEffect, useRef } from 'react';

export default function useCaptureGuard(videoRef, active, orientation = 'landscape') {
  const [cvLoaded, setCvLoaded] = useState(false);
  const [cvLoadingError, setCvLoadingError] = useState(false);
  const [guardState, setGuardState] = useState({
    brightness: 0.5,
    blur: 0,
    coverage: 0,
    isStable: false,
    documentQuad: null, // array of 4 points {x, y}
    overallReady: false,
    statusText: 'Initializing camera...',
    statusColor: '#94a3b8' // slate
  });
  
  const lastCentroidRef = useRef(null);
  const stableCountRef = useRef(0);
  const animationFrameRef = useRef(null);
  const offscreenCanvasRef = useRef(null);

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
        // OpenCV.js sets module on window.cv, but it might take a moment to initialize
        if (window.cv && window.cv.Mat) {
          setCvLoaded(true);
        } else {
          // Wait for runtime initialized
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
      // Script already injected but window.cv might not be fully ready yet
      const checkCv = setInterval(() => {
        if (window.cv && window.cv.Mat) {
          setCvLoaded(true);
          clearInterval(checkCv);
        }
      }, 100);
      return () => clearInterval(checkCv);
    }
  }, []);

  // Frame analysis loop
  useEffect(() => {
    if (!cvLoaded || !active || !videoRef.current) {
      if (animationFrameRef.current) {
        cancelAnimationFrame(animationFrameRef.current);
      }
      return;
    }

    const video = videoRef.current;
    
    // Create offscreen canvas if it doesn't exist
    if (!offscreenCanvasRef.current) {
      offscreenCanvasRef.current = document.createElement('canvas');
    }
    const canvas = offscreenCanvasRef.current;
    const ctx = canvas.getContext('2d', { willReadFrequently: true });

    const analyzeFrame = () => {
      if (video.paused || video.ended || video.readyState < 2) {
        animationFrameRef.current = requestAnimationFrame(analyzeFrame);
        return;
      }

      const cv = window.cv;
      if (!cv || !cv.Mat) {
        animationFrameRef.current = requestAnimationFrame(analyzeFrame);
        return;
      }

      try {
        const width = 320; // Downsample for fast processing
        const height = Math.floor(video.videoHeight * (width / video.videoWidth)) || 240;
        
        canvas.width = width;
        canvas.height = height;
        ctx.drawImage(video, 0, 0, width, height);

        const imgData = ctx.getImageData(0, 0, width, height);
        const src = cv.matFromImageData(imgData);
        
        // 1. Grayscale conversion
        const gray = new cv.Mat();
        cv.cvtColor(src, gray, cv.COLOR_RGBA2GRAY);

        // 2. Brightness
        const mean = cv.mean(gray)[0] / 255.0;

        // 3. Blur detection (Laplacian Variance)
        const laplacian = new cv.Mat();
        cv.Laplacian(gray, laplacian, cv.CV_64F, 1);
        const meanStd = new cv.Mat();
        const stddev = new cv.Mat();
        cv.meanStdDev(laplacian, meanStd, stddev);
        const stdVal = stddev.doubleAt(0, 0);
        const blurScore = stdVal * stdVal;

        // 4. Document / Quadrilateral detection
        const blurred = new cv.Mat();
        cv.GaussianBlur(gray, blurred, new cv.Size(5, 5), 0);
        
        const edges = new cv.Mat();
        cv.Canny(blurred, edges, 75, 200, 3);

        const contours = new cv.MatVector();
        const hierarchy = new cv.Mat();
        cv.findContours(edges, contours, hierarchy, cv.RETR_LIST, cv.CHAIN_APPROX_SIMPLE);

        let maxArea = 0;
        let bestContourIdx = -1;
        const totalArea = width * height;

        for (let i = 0; i < contours.size(); ++i) {
          const contour = contours.get(i);
          const area = cv.contourArea(contour);
          if (area > maxArea && area > totalArea * 0.1) {
            maxArea = area;
            bestContourIdx = i;
          }
        }

        let documentQuad = null;
        let coverage = 0;

        if (bestContourIdx !== -1) {
          const bestContour = contours.get(bestContourIdx);
          const peri = cv.arcLength(bestContour, true);
          const approx = new cv.Mat();
          cv.approxPolyDP(bestContour, approx, 0.02 * peri, true);

          if (approx.rows === 4) {
            // Found a quadrilateral!
            coverage = maxArea / totalArea;
            const points = [];
            for (let i = 0; i < 4; i++) {
              points.push({
                x: approx.data32S[i * 2] / width,
                y: approx.data32S[i * 2 + 1] / height
              });
            }
            // Sort points clockwise starting from top-left
            points.sort((a, b) => a.y - b.y);
            const top = points.slice(0, 2).sort((a, b) => a.x - b.x);
            const bottom = points.slice(2, 4).sort((a, b) => b.x - a.x);
            documentQuad = [top[0], top[1], bottom[0], bottom[1]];
          }
          approx.delete();
        }

        // 5. Camera stability check
        let isStable = false;
        if (documentQuad) {
          const centroidX = documentQuad.reduce((sum, p) => sum + p.x, 0) / 4;
          const centroidY = documentQuad.reduce((sum, p) => sum + p.y, 0) / 4;
          const currentCentroid = { x: centroidX, y: centroidY };

          if (lastCentroidRef.current) {
            const dx = currentCentroid.x - lastCentroidRef.current.x;
            const dy = currentCentroid.y - lastCentroidRef.current.y;
            const dist = Math.sqrt(dx * dx + dy * dy);

            if (dist < 0.015) {
              stableCountRef.current += 1;
            } else {
              stableCountRef.current = 0;
            }
          }
          lastCentroidRef.current = currentCentroid;
          isStable = stableCountRef.current >= 3; // Stable for 3 consecutive frames
        } else {
          stableCountRef.current = 0;
          lastCentroidRef.current = null;
        }

        // Threshold checks
        const brightnessOk = mean >= 0.25 && mean <= 0.85;
        const blurOk = blurScore >= 120.0; // Lower than server min to avoid false negatives in preview
        const coverageOk = coverage >= 0.25;

        let statusText = 'Align document in frame';
        let statusColor = '#e2e8f0'; // white/slate

        if (!documentQuad) {
          statusText = 'Searching for document...';
          statusColor = '#94a3b8';
        } else if (!brightnessOk) {
          if (mean < 0.25) {
            statusText = '🔆 Too dark — move to a well-lit area';
            statusColor = '#f59e0b'; // amber
          } else {
            statusText = '🔆 Too bright — avoid direct glare';
            statusColor = '#f59e0b';
          }
        } else if (!coverageOk) {
          statusText = '📐 Move closer to fill the guide';
          statusColor = '#3b82f6'; // blue
        } else if (!blurOk) {
          statusText = '📷 Blurry — hold camera steady';
          statusColor = '#ef4444'; // red
        } else if (!isStable) {
          statusText = '⏳ Hold steady...';
          statusColor = '#f59e0b';
        } else {
          statusText = '⚡ Ready! Capture starting...';
          statusColor = '#10b981'; // emerald
        }

        const overallReady = documentQuad && brightnessOk && blurOk && coverageOk && isStable;

        setGuardState({
          brightness: mean,
          blur: blurScore,
          coverage: coverage,
          isStable,
          documentQuad,
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

      animationFrameRef.current = requestAnimationFrame(analyzeFrame);
    };

    animationFrameRef.current = requestAnimationFrame(analyzeFrame);

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
