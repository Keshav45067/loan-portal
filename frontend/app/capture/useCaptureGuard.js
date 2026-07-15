import { useState, useEffect, useRef, useCallback } from 'react';

// ─── Explicit UI States ──────────────────────────────────────────────────────
const ST_SEARCHING    = 'SEARCHING';
const ST_DETECTED_FAR = 'DETECTED_FAR';
const ST_ALIGNING     = 'ALIGNING';
const ST_TOO_DARK     = 'TOO_DARK';
const ST_TOO_BRIGHT   = 'TOO_BRIGHT';
const ST_BLURRY       = 'BLURRY';
const ST_STABLE       = 'STABLE';

// ─── Default Tunable Configuration ───────────────────────────────────────────
const DEFAULT_CONFIG = {
  // Edge detection (now used as fallback if Otsu fails)
  cannyThresh1: 40,
  cannyThresh2: 120,
  useAdaptiveCanny: true,
  cannySigma: 0.33,

  // Geometry
  minAreaPct: 0.03,
  maxAreaPct: 0.95,
  maxCos: 0.55,

  // Lighting hysteresis
  darkEnter: 0.30,
  darkExit: 0.35,
  brightEnter: 0.75,
  brightExit: 0.70,

  // Coverage thresholds (document area relative to frame)
  farEnterCoverage: 0.12,
  farExitCoverage: 0.16,

  // Blur hysteresis (calibrated for 300x200 cropped quad text focus)
  blurEnter: 35.0,
  blurExit: 55.0,

  // Confidence
  minConfidence: 0.30,

  // Frame-to-frame tracking
  iouPreferenceWeight: 0.6, // weight given to IoU vs confidence when tracking
};

// ─── Geometry Helpers ────────────────────────────────────────────────────────

/** Bounding-box IoU between two normalized quads (each is [{x,y}, ...]) */
function computeQuadIoU(quadA, quadB) {
  if (!quadA || !quadB || quadA.length !== 4 || quadB.length !== 4) return 0;
  const boxA = quadToBBox(quadA);
  const boxB = quadToBBox(quadB);

  const xOverlap = Math.max(0, Math.min(boxA.x2, boxB.x2) - Math.max(boxA.x1, boxB.x1));
  const yOverlap = Math.max(0, Math.min(boxA.y2, boxB.y2) - Math.max(boxA.y1, boxB.y1));
  const intersection = xOverlap * yOverlap;

  const areaA = (boxA.x2 - boxA.x1) * (boxA.y2 - boxA.y1);
  const areaB = (boxB.x2 - boxB.x1) * (boxB.y2 - boxB.y1);
  const union = areaA + areaB - intersection;
  return union > 0 ? intersection / union : 0;
}

function quadToBBox(quad) {
  const xs = quad.map(p => p.x);
  const ys = quad.map(p => p.y);
  return {
    x1: Math.min(...xs), y1: Math.min(...ys),
    x2: Math.max(...xs), y2: Math.max(...ys),
  };
}

/** Sort 4 points into clockwise order: TL, TR, BR, BL */
function sortQuadClockwise(pts) {
  const sorted = [...pts].sort((a, b) => a.y - b.y);
  const top = sorted.slice(0, 2).sort((a, b) => a.x - b.x);
  const bottom = sorted.slice(2, 4).sort((a, b) => b.x - a.x);
  return [top[0], top[1], bottom[0], bottom[1]];
}

// ─── Main Hook ───────────────────────────────────────────────────────────────

export default function useCaptureGuard(videoRef, active, orientation = 'landscape', configOverrides = {}) {
  const [cvLoaded, setCvLoaded] = useState(false);
  const [cvLoadingError, setCvLoadingError] = useState(false);

  const configRef = useRef({ ...DEFAULT_CONFIG, ...configOverrides });
  useEffect(() => {
    configRef.current = { ...DEFAULT_CONFIG, ...configOverrides };
  }, [configOverrides]);

  const [guardState, setGuardState] = useState({
    brightness: 0.5,
    blur: 0,
    coverage: 0,
    confidence: 0,
    isStable: false,
    documentQuad: null,
    overallReady: false,
    statusText: 'Initializing camera...',
    statusDetail: '',
    statusColor: '#94a3b8',
    readinessScore: 0, // 0-1 float, how many checks pass
  });

  // State machine — kept in ref to avoid stale closures in rAF loop
  const stateMachineRef = useRef({
    currentState: ST_SEARCHING,
    lastStateChangeTime: 0,

    isDetected: false,
    isInFarState: true,
    isInDarkState: false,
    isInBrightState: false,
    isInBlurryState: false,
    isInStableState: false,

    detectionHits: 0,
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

    smoothedQuad: null,
    lastConfidence: 0,
  });

  const lastCentroidRef = useRef(null);
  const animationFrameRef = useRef(null);
  const offscreenCanvasRef = useRef(null);

  const lastDetectionTimeRef = useRef(0);
  const throttleIntervalRef = useRef(200);
  const executionTimesRef = useRef([]);

  // ─── Reset helper ────────────────────────────────────────────────────────
  const resetStateMachine = useCallback(() => {
    const sm = stateMachineRef.current;
    sm.currentState = ST_SEARCHING;
    sm.lastStateChangeTime = 0;
    sm.isDetected = false;
    sm.isInFarState = true;
    sm.isInDarkState = false;
    sm.isInBrightState = false;
    sm.isInBlurryState = false;
    sm.isInStableState = false;
    sm.detectionHits = 0;
    sm.farHits = 0; sm.farMisses = 0;
    sm.darkHits = 0; sm.darkMisses = 0;
    sm.brightHits = 0; sm.brightMisses = 0;
    sm.blurryHits = 0; sm.blurryMisses = 0;
    sm.stableHits = 0; sm.stableMisses = 0;
    sm.smoothedQuad = null;
    sm.lastConfidence = 0;
    lastCentroidRef.current = null;
  }, []);

  // ─── Load OpenCV.js ──────────────────────────────────────────────────────
  useEffect(() => {
    if (typeof window === 'undefined') return;
    if (window.cv && window.cv.Mat) {
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

  // ─── Visibility change handler ───────────────────────────────────────────
  useEffect(() => {
    const handleVisibilityChange = () => {
      if (document.hidden) resetStateMachine();
    };
    document.addEventListener('visibilitychange', handleVisibilityChange);
    return () => document.removeEventListener('visibilitychange', handleVisibilityChange);
  }, [resetStateMachine]);

  // ─── Main Detection Loop ────────────────────────────────────────────────
  useEffect(() => {
    if (!cvLoaded || !active || !videoRef.current) {
      if (animationFrameRef.current) {
        cancelAnimationFrame(animationFrameRef.current);
        animationFrameRef.current = null;
      }
      // Reset state when deactivated so stale data doesn't carry over
      resetStateMachine();
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

      if (now - lastDetectionTimeRef.current >= throttleInterval) {
        const startExecution = performance.now();

        // ─── Track all Mats for guaranteed cleanup ────────────────────
        const matsToDelete = [];
        const mat = (m) => { matsToDelete.push(m); return m; };

        try {
          const sm = stateMachineRef.current;
          const cfg = configRef.current;

          // ── 1. Downsample & convert ──────────────────────────────────
          const width = 640;
          const vw = video.videoWidth || 640;
          const vh = video.videoHeight || 480;
          const height = Math.floor(vh * (width / vw)) || 480;

          canvas.width = width;
          canvas.height = height;
          ctx.drawImage(video, 0, 0, width, height);

          const imgData = ctx.getImageData(0, 0, width, height);
          const src = mat(cv.matFromImageData(imgData));

          const gray = mat(new cv.Mat());
          cv.cvtColor(src, gray, cv.COLOR_RGBA2GRAY);

          // ── 2. Brightness metric ─────────────────────────────────────
          const mean = cv.mean(gray)[0] / 255.0;

          // ── 3. Blur metric (Laplacian variance) ──────────────────────
          let blurScore = 0;
          let calculatedBlurOnCrop = false;

          // If we have a tracked quad from the previous frame, calculate blur on its cropped/warped version
          if (sm.isDetected && sm.smoothedQuad && sm.smoothedQuad.length === 4) {
            try {
              const srcPts = sm.smoothedQuad.map(p => [p.x * width, p.y * height]);
              const srcMat = mat(cv.matFromArray(4, 1, cv.CV_32FC2, srcPts.flat()));
              
              const dstW = 300;
              const dstH = 200;
              const dstMat = mat(cv.matFromArray(4, 1, cv.CV_32FC2, [
                0, 0,       dstW, 0,
                dstW, dstH, 0, dstH
              ]));
              
              const M = mat(cv.getPerspectiveTransform(srcMat, dstMat));
              const warpedGray = mat(new cv.Mat());
              cv.warpPerspective(gray, warpedGray, M, new cv.Size(dstW, dstH));
              
              const laplacian = mat(new cv.Mat());
              cv.Laplacian(warpedGray, laplacian, cv.CV_64F, 1);
              
              const lapMean = mat(new cv.Mat());
              const lapStddev = mat(new cv.Mat());
              cv.meanStdDev(laplacian, lapMean, lapStddev);
              
              const stdVal = lapStddev.doubleAt(0, 0);
              blurScore = stdVal * stdVal;
              calculatedBlurOnCrop = true;
            } catch (warpErr) {
              console.warn('[useCaptureGuard] Failed to calculate blur on cropped quad:', warpErr);
            }
          }

          if (!calculatedBlurOnCrop) {
            const laplacian = mat(new cv.Mat());
            cv.Laplacian(gray, laplacian, cv.CV_64F, 1);
            const lapMean = mat(new cv.Mat());
            const lapStddev = mat(new cv.Mat());
            cv.meanStdDev(laplacian, lapMean, lapStddev);
            const stdVal = lapStddev.doubleAt(0, 0);
            blurScore = stdVal * stdVal;
          }



          // ── 4. Edge extraction ───────────────────────────────────────
          const blurred = mat(new cv.Mat());
          cv.GaussianBlur(gray, blurred, new cv.Size(5, 5), 0);

          const edges = mat(new cv.Mat());

          if (cfg.useAdaptiveCanny) {
            // Otsu-based adaptive Canny thresholding
            const otsuDst = mat(new cv.Mat());
            const otsuThresh = cv.threshold(blurred, otsuDst, 0, 255, cv.THRESH_BINARY | cv.THRESH_OTSU);
            const sigma = cfg.cannySigma;
            const lower = Math.max(0, (1 - sigma) * otsuThresh);
            const upper = Math.min(255, (1 + sigma) * otsuThresh);
            cv.Canny(blurred, edges, lower, upper, 3);
          } else {
            cv.Canny(blurred, edges, cfg.cannyThresh1, cfg.cannyThresh2, 3);
          }

          // Morphological close — bridge small gaps in edge lines
          const kernel = mat(cv.Mat.ones(5, 5, cv.CV_8U));
          cv.dilate(edges, edges, kernel, new cv.Point(-1, -1), 1);
          cv.erode(edges, edges, kernel, new cv.Point(-1, -1), 1);

          // ── 5. Contour extraction — EXTERNAL ONLY ────────────────────
          const contours = mat(new cv.MatVector());
          const hierarchy = mat(new cv.Mat());
          cv.findContours(edges, contours, hierarchy, cv.RETR_LIST, cv.CHAIN_APPROX_SIMPLE);

          const totalArea = width * height;
          const minArea = totalArea * cfg.minAreaPct;
          const maxArea = totalArea * cfg.maxAreaPct;

          // Collect valid contours (and track their Mats for cleanup)
          const contourMats = [];
          const contourList = [];
          for (let i = 0; i < contours.size(); ++i) {
            const contour = contours.get(i);
            contourMats.push(contour); // track for deletion
            const area = cv.contourArea(contour);
            if (area >= minArea && area <= maxArea) {
              contourList.push({ contour, area, index: i });
            }
          }
          contourList.sort((a, b) => b.area - a.area);

          // ── 6. Quadrilateral search with confidence scoring ──────────

          const candidates = []; // {quad, coverage, confidence, maxCos}

          for (const item of contourList) {
            const peri = cv.arcLength(item.contour, true);
            const approx = mat(new cv.Mat());

            for (let eps = 0.02; eps <= 0.08; eps += 0.01) {
              cv.approxPolyDP(item.contour, approx, eps * peri, true);

              if (approx.rows === 4 && cv.isContourConvex(approx)) {
                // ── Angle check (vector dot product) ──
                let maxCos = 0;
                const pts = [];
                for (let j = 0; j < 4; j++) {
                  pts.push({
                    x: approx.data32S[j * 2],
                    y: approx.data32S[j * 2 + 1],
                  });
                }

                for (let j = 0; j < 4; j++) {
                  const pt1 = pts[j];
                  const pt0 = pts[(j + 3) % 4];
                  const pt2 = pts[(j + 1) % 4];

                  const dx1 = pt0.x - pt1.x, dy1 = pt0.y - pt1.y;
                  const dx2 = pt2.x - pt1.x, dy2 = pt2.y - pt1.y;

                  const len1 = Math.sqrt(dx1 * dx1 + dy1 * dy1);
                  const len2 = Math.sqrt(dx2 * dx2 + dy2 * dy2);
                  const cos = (dx1 * dx2 + dy1 * dy2) / (len1 * len2 + 1e-10);
                  maxCos = Math.max(maxCos, Math.abs(cos));
                }

                if (maxCos < cfg.maxCos) {
                  // ── Compute confidence score ──
                  const rectScore = 1.0 - (maxCos / cfg.maxCos); // 0-1, higher = more rectangular
                  const coveragePct = item.area / totalArea;

                  // Area plausibility: peaks in 20-80% range, penalizes extremes
                  let areaScore;
                  if (coveragePct < 0.15) areaScore = coveragePct / 0.15;
                  else if (coveragePct > 0.90) areaScore = (1.0 - coveragePct) / 0.10;
                  else areaScore = 1.0;

                  // Aspect ratio plausibility
                  const widths = [
                    Math.sqrt((pts[1].x - pts[0].x) ** 2 + (pts[1].y - pts[0].y) ** 2),
                    Math.sqrt((pts[2].x - pts[3].x) ** 2 + (pts[2].y - pts[3].y) ** 2),
                  ];
                  const heights = [
                    Math.sqrt((pts[3].x - pts[0].x) ** 2 + (pts[3].y - pts[0].y) ** 2),
                    Math.sqrt((pts[2].x - pts[1].x) ** 2 + (pts[2].y - pts[1].y) ** 2),
                  ];
                  const avgW = (widths[0] + widths[1]) / 2;
                  const avgH = (heights[0] + heights[1]) / 2;
                  const aspect = Math.max(avgW, avgH) / (Math.min(avgW, avgH) + 1e-10);
                  const aspectScore = aspect > 4 ? 0.3 : 1.0;

                  const confidence = (rectScore * 0.4 + areaScore * 0.35 + aspectScore * 0.25);

                  if (confidence >= cfg.minConfidence) {
                    // Build normalized quad
                    const normPts = pts.map(p => ({ x: p.x / width, y: p.y / height }));
                    const quad = sortQuadClockwise(normPts);

                    candidates.push({
                      quad,
                      coverage: coveragePct,
                      confidence,
                      maxCos,
                    });
                  }
                  break; // found a valid quad for this contour, move to next
                }
              }
            }
          }

          // ── 7. Pick best candidate (IoU-aware when tracking) ─────────
          let documentQuad = null;
          let coverage = 0;
          let bestConfidence = 0;

          if (candidates.length > 0) {
            if (sm.isDetected && sm.smoothedQuad) {
              // IoU-weighted selection: prefer candidate closest to tracked quad
              let bestScore = -1;
              for (const c of candidates) {
                const iou = computeQuadIoU(c.quad, sm.smoothedQuad);
                const combinedScore = iou * cfg.iouPreferenceWeight + c.confidence * (1 - cfg.iouPreferenceWeight);
                if (combinedScore > bestScore) {
                  bestScore = combinedScore;
                  documentQuad = c.quad;
                  coverage = c.coverage;
                  bestConfidence = c.confidence;
                }
              }
            } else {
              // No prior — pick highest confidence
              candidates.sort((a, b) => b.confidence - a.confidence);
              documentQuad = candidates[0].quad;
              coverage = candidates[0].coverage;
              bestConfidence = candidates[0].confidence;
            }
          }

          // ── Clean up individual contour Mats ────────────────────────
          for (const cm of contourMats) {
            cm.delete();
          }

          // ═══════════════════════════════════════════════════════════════
          // STATE MACHINE & HYSTERESIS
          // ═══════════════════════════════════════════════════════════════

          // A. Document Detection Hysteresis
          if (documentQuad) {
            sm.detectionHits = Math.min(5, sm.detectionHits + 1);
            if (sm.detectionHits >= 3) {
              sm.isDetected = true;
            }
          } else {
            sm.detectionHits = Math.max(0, sm.detectionHits - 1);
            if (sm.detectionHits <= 0) {
              sm.isDetected = false;
              sm.smoothedQuad = null;
            }
          }

          // B. Coverage & Native Resolution (Move Closer) Hysteresis
          if (sm.isDetected) {
            let isCloseEnough = (coverage >= cfg.farExitCoverage);
            
            // Check native resolution of document if quad is present
            if (documentQuad && documentQuad.length === 4) {
              const nativeW = video.videoWidth || 1920;
              const nativeH = video.videoHeight || 1080;
              
              const pts = documentQuad.map(p => ({ x: p.x * nativeW, y: p.y * nativeH }));
              const widthTop = Math.hypot(pts[1].x - pts[0].x, pts[1].y - pts[0].y);
              const widthBot = Math.hypot(pts[2].x - pts[3].x, pts[2].y - pts[3].y);
              const heightL  = Math.hypot(pts[3].x - pts[0].x, pts[3].y - pts[0].y);
              const heightR  = Math.hypot(pts[2].x - pts[1].x, pts[2].y - pts[1].y);
              
              const minEdgeNative = Math.min(widthTop, widthBot, heightL, heightR);
              // Require shortest edge to be at least 500px or 45% of camera stream height
              const dynamicMinEdgeLimit = Math.min(500, nativeH * 0.45);
              if (minEdgeNative < dynamicMinEdgeLimit) {
                isCloseEnough = false;
              }
            }

            if (sm.isInFarState) {
              if (isCloseEnough) sm.farHits += 1;
              else sm.farHits = 0;
              if (sm.farHits >= 2) sm.isInFarState = false;
            } else {
              const isStillCloseEnough = (coverage >= cfg.farEnterCoverage);
              // Check native resolution for hysteresis too
              let minEdgeNative = 9999;
              if (documentQuad && documentQuad.length === 4) {
                const nativeW = video.videoWidth || 1920;
                const nativeH = video.videoHeight || 1080;
                const pts = documentQuad.map(p => ({ x: p.x * nativeW, y: p.y * nativeH }));
                const widthTop = Math.hypot(pts[1].x - pts[0].x, pts[1].y - pts[0].y);
                const widthBot = Math.hypot(pts[2].x - pts[3].x, pts[2].y - pts[3].y);
                const heightL  = Math.hypot(pts[3].x - pts[0].x, pts[3].y - pts[0].y);
                const heightR  = Math.hypot(pts[2].x - pts[1].x, pts[2].y - pts[1].y);
                minEdgeNative = Math.min(widthTop, widthBot, heightL, heightR);
              }

              const dynamicMinEdgeHysteresisLimit = Math.min(450, nativeH * 0.40);
              if (!isStillCloseEnough || minEdgeNative < dynamicMinEdgeHysteresisLimit) sm.farMisses += 1;
              else sm.farMisses = 0;
              if (sm.farMisses >= 3) sm.isInFarState = true;
            }
          }

          // C. Brightness Hysteresis (ALWAYS CHECKED)
          if (sm.isInDarkState) {
            if (mean >= cfg.darkExit) sm.darkHits += 1;
            else sm.darkHits = 0;
            if (sm.darkHits >= 3) sm.isInDarkState = false;
          } else {
            if (mean < cfg.darkEnter) sm.darkMisses += 1;
            else sm.darkMisses = 0;
            if (sm.darkMisses >= 3) sm.isInDarkState = true;
          }

          if (sm.isInBrightState) {
            if (mean <= cfg.brightExit) sm.brightHits += 1;
            else sm.brightHits = 0;
            if (sm.brightHits >= 3) sm.isInBrightState = false;
          } else {
            if (mean > cfg.brightEnter) sm.brightMisses += 1;
            else sm.brightMisses = 0;
            if (sm.brightMisses >= 3) sm.isInBrightState = true;
          }

          // D. Blur Hysteresis (ALWAYS CHECKED)
          if (sm.isInBlurryState) {
            if (blurScore >= cfg.blurExit) sm.blurryHits += 1;
            else sm.blurryHits = 0;
            if (sm.blurryHits >= 3) sm.isInBlurryState = false;
          } else {
            if (blurScore < cfg.blurEnter) sm.blurryMisses += 1;
            else sm.blurryMisses = 0;
            if (sm.blurryMisses >= 3) sm.isInBlurryState = true;
          }

          // E. Stability Hysteresis (centroid-based motion detection)
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
              if (motion >= 0.020) sm.stableMisses += 1;
              else sm.stableMisses = 0;
              if (sm.stableMisses >= 2) sm.isInStableState = false;
            } else {
              if (motion < 0.012) sm.stableHits += 1;
              else sm.stableHits = 0;
              if (sm.stableHits >= 5) sm.isInStableState = true;
            }
          }

          // F. Adaptive-Alpha EMA for quad smoothing
          if (documentQuad) {
            if (!sm.smoothedQuad) {
              sm.smoothedQuad = documentQuad;
            } else {
              // Higher alpha (less smoothing, faster tracking) when document is moving
              // Lower alpha (more smoothing) when document is still
              const baseAlpha = motion > 0.02 ? 0.50 : 0.25;
              sm.smoothedQuad = sm.smoothedQuad.map((prevPt, idx) => ({
                x: prevPt.x * (1 - baseAlpha) + documentQuad[idx].x * baseAlpha,
                y: prevPt.y * (1 - baseAlpha) + documentQuad[idx].y * baseAlpha,
              }));
            }
          }

          sm.lastConfidence = bestConfidence;

          // G. Readiness score (0-1 float showing how many checks pass)
          let readinessChecks = 0;
          let totalChecks = 5;
          if (!sm.isInDarkState && !sm.isInBrightState) readinessChecks++;
          if (sm.isDetected) readinessChecks++;
          if (sm.isDetected && !sm.isInFarState) readinessChecks++;
          if (!sm.isInBlurryState) readinessChecks++;
          if (sm.isInStableState) readinessChecks++;
          const readinessScore = readinessChecks / totalChecks;

          // H. Priority-based State Resolver with detailed feedback
          let nextState = ST_SEARCHING;
          let statusText = 'Searching for document...';
          let statusDetail = 'Place a document on a flat, contrasting surface';
          let statusColor = '#94a3b8';

          if (sm.isInDarkState) {
            nextState = ST_TOO_DARK;
            statusText = '🔆 Too dark';
            statusDetail = 'Move to a well-lit area or turn on a light';
            statusColor = '#f59e0b';
          } else if (sm.isInBrightState) {
            nextState = ST_TOO_BRIGHT;
            statusText = '🔆 Too bright';
            statusDetail = 'Avoid direct glare or strong reflections';
            statusColor = '#f59e0b';
          } else if (!sm.isDetected) {
            nextState = ST_SEARCHING;
            statusText = 'Searching for document...';
            statusDetail = 'Place a document on a flat, contrasting surface';
            statusColor = '#94a3b8';
          } else if (sm.isInFarState) {
            nextState = ST_DETECTED_FAR;
            statusText = '📐 Move closer';
            statusDetail = `Fill more of the frame · Coverage: ${Math.round(coverage * 100)}%`;
            statusColor = '#3b82f6';
          } else if (sm.isInBlurryState) {
            nextState = ST_BLURRY;
            statusText = '📷 Image blurry';
            statusDetail = 'Hold the camera steady and ensure good focus';
            statusColor = '#ef4444';
          } else if (!sm.isInStableState) {
            nextState = ST_ALIGNING;
            statusText = '⏳ Hold steady...';
            statusDetail = `Aligning · Confidence: ${Math.round(bestConfidence * 100)}%`;
            statusColor = '#f59e0b';
          } else {
            nextState = ST_STABLE;
            statusText = '✅ Perfect — capturing now';
            statusDetail = `Confidence: ${Math.round(bestConfidence * 100)}%`;
            statusColor = '#10b981';
          }

          // Minimum dwell time (400ms) to prevent flicker
          if (nextState !== sm.currentState) {
            if (sm.currentState === ST_SEARCHING || now - sm.lastStateChangeTime >= 400) {
              sm.currentState = nextState;
              sm.lastStateChangeTime = now;
            } else {
              nextState = sm.currentState;
            }
          }

          const overallReady = (sm.currentState === ST_STABLE);

          // I. Update React State
          setGuardState({
            brightness: mean,
            blur: blurScore,
            coverage,
            confidence: bestConfidence,
            isStable: sm.isInStableState,
            documentQuad: sm.smoothedQuad,
            overallReady,
            statusText,
            statusDetail,
            statusColor,
            readinessScore,
          });

        } catch (err) {
          console.error('Error during frame analysis:', err);
        } finally {
          // ── Guaranteed WASM Mat cleanup ───────────────────────────────
          for (const m of matsToDelete) {
            try { m.delete(); } catch (_) { /* already deleted or invalid */ }
          }
        }

        const endExecution = performance.now();
        const duration = endExecution - startExecution;

        // Adaptive Throttling
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
        animationFrameRef.current = null;
      }
    };
  }, [cvLoaded, active, videoRef, orientation, resetStateMachine]);

  return {
    cvLoaded,
    cvLoadingError,
    ...guardState,
  };
}
