import { useState, useEffect, useRef, useCallback } from 'react';

// ─── Explicit UI States ──────────────────────────────────────────────────────
const ST_SEARCHING = 'SEARCHING';
const ST_DETECTED_FAR = 'DETECTED_FAR';
const ST_ALIGNING = 'ALIGNING';
const ST_TOO_DARK = 'TOO_DARK';
const ST_TOO_BRIGHT = 'TOO_BRIGHT';
const ST_BLURRY = 'BLURRY';
const ST_STABLE = 'STABLE';

// ─── Default Tunable Configuration ───────────────────────────────────────────
const DEFAULT_CONFIG = {
  // Edge detection (now used as fallback if Otsu fails)
  cannyThresh1: 40,
  cannyThresh2: 120,
  useAdaptiveCanny: true,
  cannySigma: 0.33,

  // Pre-edge smoothing. Bilateral filtering suppresses high-frequency
  // texture (wood grain, patterned surfaces, etc.) while preserving strong
  // edges like the document boundary, which plain GaussianBlur does not do
  // well. Falls back to GaussianBlur if bilateralFilter throws.
  // d=7/sigma=50 is a lighter (cheaper) setting than the initial 9/75/75 —
  // drop to 5/50/50 first if this is still the slowest stage on low-end devices.
  useBilateralFilter: true,
  bilateralD: 7,
  bilateralSigmaColor: 50,
  bilateralSigmaSpace: 50,
  edgeBlurKernel: 5, // used only for the GaussianBlur fallback

  // Geometry
  minAreaPct: 0.03,
  maxAreaPct: 0.95,
  maxCos: 0.55,

  // Shape sanity filters — these catch the false positives that textured
  // backgrounds tend to produce (jagged noise contours forced into a quad
  // shape by a large approxPolyDP epsilon). 0.80 rather than a stricter
  // value because perspective-skewed or slightly curled real pages
  // routinely land at 0.75-0.85 solidity — going tighter starts rejecting
  // legitimate documents, not just noise.
  minSolidity: 0.80,             // contourArea / convexHullArea
  quadAreaConsistencyMin: 0.75,  // simplified-quad-area / raw-contour-area
  quadAreaConsistencyMax: 1.30,

  // Only run the (relatively expensive) convexHull/solidity + polygon
  // approximation pipeline on the N largest candidate contours per frame,
  // not every contour that survives the area filter.
  maxContoursToEvaluate: 12,

  // Secondary contour source: a saturation-based mask. Paper is often
  // near-white/low-saturation, but this is not universal (colored IDs,
  // invoices, brochures) and a low-saturation desk/table can generate a
  // competing false candidate. Off by default — enable it for known
  // scenarios (plain white paper on a textured surface) where it helps
  // more than it risks.
  useColorMaskAssist: false,

  // Edge-strength confidence signal: samples gradient magnitude along a
  // candidate quad's perimeter. A real document boundary has a much
  // stronger intensity gradient than a coincidental noise/texture quad or
  // a flat-region mask blob, so this is the strongest discriminator we
  // have against exactly that failure mode. edgeStrengthNormalization is
  // a heuristic starting point (raw Sobel magnitude units) — tune it
  // against real footage; it will vary with lighting/contrast.
  edgeStrengthSampleCount: 24,
  edgeStrengthNormalization: 120,

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
  reacquireConfidenceMargin: 0.22, // let a much-higher-confidence candidate override a tracked (possibly wrong) quad
  trackingMissIoUThresh: 0.15,     // below this, a frame counts as a "tracking miss"
  trackingMissStreakLimit: 4,      // consecutive misses before we drop the track and re-acquire cleanly
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

/** Shoelace-formula area of a 4-point polygon (points in px, any winding order) */
function polygonArea(pts) {
  let area = 0;
  for (let i = 0; i < pts.length; i++) {
    const j = (i + 1) % pts.length;
    area += pts[i].x * pts[j].y;
    area -= pts[j].x * pts[i].y;
  }
  return Math.abs(area) / 2;
}

/**
 * Average gradient-magnitude value sampled along a 4-point polygon's
 * perimeter (points in px). Used as a confidence signal: a real document
 * edge has a much stronger intensity gradient than a coincidental
 * texture/noise contour or a flat-region mask boundary.
 */
function sampleEdgeStrength(magnitudeData, matWidth, matHeight, pts, sampleCount) {
  let total = 0;
  let count = 0;
  for (let e = 0; e < 4; e++) {
    const p1 = pts[e];
    const p2 = pts[(e + 1) % 4];
    for (let s = 0; s < sampleCount; s++) {
      const t = sampleCount > 1 ? s / (sampleCount - 1) : 0;
      const x = Math.round(p1.x + (p2.x - p1.x) * t);
      const y = Math.round(p1.y + (p2.y - p1.y) * t);
      if (x < 0 || x >= matWidth || y < 0 || y >= matHeight) continue;
      total += magnitudeData[y * matWidth + x];
      count++;
    }
  }
  return count > 0 ? total / count : 0;
}

// ─── Capture-time corner refinement ─────────────────────────────────────────
// The main loop deliberately works on a downsampled (640px) frame — that's
// plenty for real-time guidance and keeps the loop fast. It is NOT enough
// precision for the final crop/warp. Call this once, at the moment you
// actually capture (e.g. when overallReady flips true and you snap the
// photo), against the live full-resolution video frame, to subpixel-refine
// the coarse quad's corners before using them to warp/crop the final image.
export function refineQuadCorners(videoEl, normalizedQuad) {
  const cv = window.cv;
  if (!cv || !cv.Mat || !videoEl || !normalizedQuad || normalizedQuad.length !== 4) {
    return normalizedQuad;
  }

  const w = videoEl.videoWidth;
  const h = videoEl.videoHeight;
  if (!w || !h) return normalizedQuad;

  const canvas = document.createElement('canvas');
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext('2d', { willReadFrequently: true });
  ctx.drawImage(videoEl, 0, 0, w, h);

  let src, gray, corners;
  try {
    const imgData = ctx.getImageData(0, 0, w, h);
    src = cv.matFromImageData(imgData);
    gray = new cv.Mat();
    cv.cvtColor(src, gray, cv.COLOR_RGBA2GRAY);

    const flatPts = normalizedQuad.flatMap(p => [p.x * w, p.y * h]);
    corners = cv.matFromArray(4, 1, cv.CV_32FC2, flatPts);

    const winSize = new cv.Size(11, 11);
    const zeroZone = new cv.Size(-1, -1);
    const criteria = new cv.TermCriteria(cv.TermCriteria_EPS + cv.TermCriteria_COUNT, 30, 0.01);
    cv.cornerSubPix(gray, corners, winSize, zeroZone, criteria);

    const refined = [];
    for (let i = 0; i < 4; i++) {
      refined.push({
        x: corners.data32F[i * 2] / w,
        y: corners.data32F[i * 2 + 1] / h,
      });
    }
    return refined;
  } catch (err) {
    console.warn('[useCaptureGuard] refineQuadCorners failed, using coarse quad:', err);
    return normalizedQuad;
  } finally {
    if (src) src.delete();
    if (gray) gray.delete();
    if (corners) corners.delete();
  }
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
    trackingMissStreak: 0,
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
    sm.trackingMissStreak = 0;
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
                0, 0, dstW, 0,
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

          // ── 3b. Gradient magnitude (for edge-strength confidence scoring) ──
          const sobelX = mat(new cv.Mat());
          const sobelY = mat(new cv.Mat());
          cv.Sobel(gray, sobelX, cv.CV_32F, 1, 0, 3);
          cv.Sobel(gray, sobelY, cv.CV_32F, 0, 1, 3);
          const gradMag = mat(new cv.Mat());
          cv.magnitude(sobelX, sobelY, gradMag);
          const gradMagData = gradMag.data32F;

          // ── 4. Edge extraction ───────────────────────────────────────
          // Bilateral filtering (rather than plain Gaussian) suppresses
          // high-frequency background texture while preserving strong
          // edges like the document boundary. Falls back gracefully.
          const blurred = mat(new cv.Mat());
          let usedBilateral = false;
          if (cfg.useBilateralFilter) {
            try {
              cv.bilateralFilter(gray, blurred, cfg.bilateralD, cfg.bilateralSigmaColor, cfg.bilateralSigmaSpace, cv.BORDER_DEFAULT);
              usedBilateral = true;
            } catch (bilateralErr) {
              usedBilateral = false;
            }
          }
          if (!usedBilateral) {
            cv.GaussianBlur(gray, blurred, new cv.Size(cfg.edgeBlurKernel, cfg.edgeBlurKernel), 0);
          }

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

          // ── 5. Contour extraction ─────────────────────────────────────
          // RETR_EXTERNAL (not RETR_LIST): we only care about outer
          // boundaries. RETR_LIST also pulls in every nested/internal
          // contour (text, print patterns, texture noise), which massively
          // inflates the candidate pool with things that were never
          // going to be the document.
          const contours = mat(new cv.MatVector());
          const hierarchy = mat(new cv.Mat());
          cv.findContours(edges, contours, hierarchy, cv.RETR_EXTERNAL, cv.CHAIN_APPROX_SIMPLE);

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

          // ── 5b. Secondary contour source: saturation-based mask ──────
          // Paper is typically near-white / low-saturation. This gives an
          // independent signal that often stays clean even when Canny
          // edges are swamped by a textured background/tablecloth/desk.
          if (cfg.useColorMaskAssist) {
            try {
              const rgb = mat(new cv.Mat());
              cv.cvtColor(src, rgb, cv.COLOR_RGBA2RGB);
              const hsv = mat(new cv.Mat());
              cv.cvtColor(rgb, hsv, cv.COLOR_RGB2HSV);

              const hsvPlanes = mat(new cv.MatVector());
              cv.split(hsv, hsvPlanes);
              const hChannel = mat(hsvPlanes.get(0));
              const satChannel = mat(hsvPlanes.get(1));
              const vChannel = mat(hsvPlanes.get(2));
              void hChannel; void vChannel; // unused, tracked only for cleanup

              const satMask = mat(new cv.Mat());
              cv.threshold(satChannel, satMask, 0, 255, cv.THRESH_BINARY_INV | cv.THRESH_OTSU);

              const maskKernel = mat(cv.Mat.ones(5, 5, cv.CV_8U));
              cv.morphologyEx(satMask, satMask, cv.MORPH_CLOSE, maskKernel);
              cv.morphologyEx(satMask, satMask, cv.MORPH_OPEN, maskKernel);

              const maskContours = mat(new cv.MatVector());
              const maskHierarchy = mat(new cv.Mat());
              cv.findContours(satMask, maskContours, maskHierarchy, cv.RETR_EXTERNAL, cv.CHAIN_APPROX_SIMPLE);

              for (let i = 0; i < maskContours.size(); ++i) {
                const contour = maskContours.get(i);
                contourMats.push(contour);
                const area = cv.contourArea(contour);
                if (area >= minArea && area <= maxArea) {
                  contourList.push({ contour, area, index: -1 });
                }
              }
            } catch (maskErr) {
              console.warn('[useCaptureGuard] Color-mask assist failed:', maskErr);
            }
          }

          contourList.sort((a, b) => b.area - a.area);
          const evaluatedContours = contourList.slice(0, cfg.maxContoursToEvaluate);

          // ── 6. Quadrilateral search with confidence scoring ──────────

          const candidates = []; // {quad, coverage, confidence, maxCos}

          for (const item of evaluatedContours) {
            // Solidity precheck — rejects jagged/noisy contours (the
            // hallmark of textured-background false positives) before
            // spending time on polygon approximation.
            let solidity = 1;
            try {
              const hull = mat(new cv.Mat());
              cv.convexHull(item.contour, hull);
              const hullArea = cv.contourArea(hull);
              solidity = hullArea > 0 ? item.area / hullArea : 0;
            } catch (hullErr) {
              solidity = 1; // fail open if hull computation errors
            }
            if (solidity < cfg.minSolidity) continue;

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
                  // Area-consistency check: reject quads whose area diverges
                  // too much from the original contour's area. This catches
                  // cases where approxPolyDP over-simplified a noisy/jagged
                  // contour into a shape that coincidentally has 4 convex
                  // points but doesn't actually represent it well.
                  const quadAreaPx = polygonArea(pts);
                  const areaRatio = item.area > 0 ? quadAreaPx / item.area : 0;
                  if (areaRatio < cfg.quadAreaConsistencyMin || areaRatio > cfg.quadAreaConsistencyMax) {
                    continue; // try a different epsilon rather than accepting a bad fit
                  }

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

                  // Edge strength: real document boundaries have a much
                  // stronger intensity gradient than a coincidental noise
                  // quad, so this is weighted as heavily as rectangularity.
                  const edgeStrengthRaw = sampleEdgeStrength(gradMagData, width, height, pts, cfg.edgeStrengthSampleCount);
                  const edgeStrengthScore = Math.min(1, edgeStrengthRaw / cfg.edgeStrengthNormalization);

                  const confidence = (
                    rectScore * 0.30 +
                    areaScore * 0.20 +
                    aspectScore * 0.20 +
                    edgeStrengthScore * 0.30
                  );

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

          // ── 7. Pick best candidate (confidence-aware IoU tracking) ────
          let documentQuad = null;
          let coverage = 0;
          let bestConfidence = 0;

          if (candidates.length > 0) {
            if (sm.isDetected && sm.smoothedQuad) {
              // IoU-weighted selection: prefer candidate closest to tracked quad,
              // but don't let that lock the tracker onto a wrong region forever.
              let bestByIoU = null;
              let bestIoUScore = -1;
              let bestByConfidence = null;

              for (const c of candidates) {
                const iou = computeQuadIoU(c.quad, sm.smoothedQuad);
                const combinedScore = iou * cfg.iouPreferenceWeight + c.confidence * (1 - cfg.iouPreferenceWeight);
                if (combinedScore > bestIoUScore) {
                  bestIoUScore = combinedScore;
                  bestByIoU = c;
                }
                if (!bestByConfidence || c.confidence > bestByConfidence.confidence) {
                  bestByConfidence = c;
                }
              }

              let chosen = bestByIoU;

              // Re-acquisition: if a much higher-confidence candidate exists
              // elsewhere in frame, don't stay locked onto a stale/wrong track.
              if (
                bestByConfidence &&
                bestByConfidence !== bestByIoU &&
                bestByConfidence.confidence - bestByIoU.confidence > cfg.reacquireConfidenceMargin
              ) {
                chosen = bestByConfidence;
              }

              // Track consecutive frames where we're tracking poorly. After
              // enough misses in a row, drop the smoothed quad so the next
              // pick is a clean, confidence-only re-acquisition instead of
              // staying biased toward a track that's drifted onto noise.
              const iouOfChosen = computeQuadIoU(chosen.quad, sm.smoothedQuad);
              if (iouOfChosen < cfg.trackingMissIoUThresh) {
                sm.trackingMissStreak = (sm.trackingMissStreak || 0) + 1;
                if (sm.trackingMissStreak >= cfg.trackingMissStreakLimit) {
                  sm.smoothedQuad = null;
                  sm.trackingMissStreak = 0;
                }
              } else {
                sm.trackingMissStreak = 0;
              }

              documentQuad = chosen.quad;
              coverage = chosen.coverage;
              bestConfidence = chosen.confidence;
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
          //
          // FIX: nativeW/nativeH used to be declared with `const` inside the
          // `if (documentQuad...)` block below and then referenced again
          // outside that block in the `else` branch — a ReferenceError on
          // every frame once isInFarState became false, silently caught by
          // the outer try/catch, which meant guardState stopped updating
          // right when the user got close enough for accurate tracking to
          // matter. Hoisted here and deduplicated into one helper.
          if (sm.isDetected) {
            const nativeW = video.videoWidth || 1920;
            const nativeH = video.videoHeight || 1080;

            const computeMinEdgeNative = (quad) => {
              if (!quad || quad.length !== 4) return null;
              const pts = quad.map(p => ({ x: p.x * nativeW, y: p.y * nativeH }));
              const widthTop = Math.hypot(pts[1].x - pts[0].x, pts[1].y - pts[0].y);
              const widthBot = Math.hypot(pts[2].x - pts[3].x, pts[2].y - pts[3].y);
              const heightL = Math.hypot(pts[3].x - pts[0].x, pts[3].y - pts[0].y);
              const heightR = Math.hypot(pts[2].x - pts[1].x, pts[2].y - pts[1].y);
              return Math.min(widthTop, widthBot, heightL, heightR);
            };

            let isCloseEnough = (coverage >= cfg.farExitCoverage);

            // Require shortest edge to be at least 500px or 45% of camera stream height
            const minEdgeForEntry = computeMinEdgeNative(documentQuad);
            if (minEdgeForEntry !== null) {
              const dynamicMinEdgeLimit = Math.min(500, nativeH * 0.45);
              if (minEdgeForEntry < dynamicMinEdgeLimit) {
                isCloseEnough = false;
              }
            }

            if (sm.isInFarState) {
              if (isCloseEnough) sm.farHits += 1;
              else sm.farHits = 0;
              if (sm.farHits >= 2) sm.isInFarState = false;
            } else {
              const isStillCloseEnough = (coverage >= cfg.farEnterCoverage);
              const minEdgeNative = computeMinEdgeNative(documentQuad) ?? 9999;
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