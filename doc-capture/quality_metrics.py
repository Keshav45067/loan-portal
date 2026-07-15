"""Quality Metrics Registry for measuring document images."""

import io
from dataclasses import dataclass
from PIL import Image
import numpy as np
import cv2
from log_utils.logger import get_logger

logger = get_logger("doc-capture-metrics")

@dataclass
class QualityReport:
    blur: float
    brightness: float
    contrast: float
    noise: float
    glare: float
    shadow: float
    rotation: float
    resolution: dict  # {"width": int, "height": int}
    has_qr_codes: bool = False
    qr_coordinates: list = None

def measure_blur(img: Image.Image) -> float:
    """Calculates Laplacian variance as a proxy for blur."""
    try:
        img_gray = np.array(img.convert('L'), dtype=np.uint8)
        laplacian = cv2.Laplacian(img_gray, cv2.CV_64F, ksize=1)
        # Crop 1-pixel border to eliminate border artifacts
        h, w = laplacian.shape
        if w > 2 and h > 2:
            laplacian = laplacian[1:-1, 1:-1]
        return float(np.var(laplacian))
    except Exception as e:
        logger.error(f"Error measuring blur: {e}")
        return 0.0

def measure_brightness(img: Image.Image) -> float:
    """Mean luminance normalized to [0, 1]."""
    try:
        img_gray = np.array(img.convert('L'), dtype=np.uint8)
        return float(np.mean(img_gray)) / 255.0
    except Exception as e:
        logger.error(f"Error measuring brightness: {e}")
        return 0.5

def measure_contrast(img: Image.Image) -> float:
    """RMS contrast (standard deviation of luminance) normalized to [0, 1]."""
    try:
        img_gray = np.array(img.convert('L'), dtype=np.uint8)
        return float(np.std(img_gray)) / 255.0
    except Exception as e:
        logger.error(f"Error measuring contrast: {e}")
        return 0.0

def measure_noise(img: Image.Image) -> float:
    """Estimates noise level by taking std dev of original vs median filtered image."""
    try:
        img_gray = np.array(img.convert('L'), dtype=np.uint8)
        median = cv2.medianBlur(img_gray, 3)
        diff = np.abs(img_gray.astype(np.int16) - median.astype(np.int16))
        return float(np.std(diff)) / 255.0
    except Exception as e:
        logger.error(f"Error measuring noise: {e}")
        return 0.0

def measure_glare(img: Image.Image) -> float:
    """Fraction of pixels that are near-white (potential glare)."""
    try:
        img_gray = np.array(img.convert('L'), dtype=np.uint8)
        glare_pixels = np.sum(img_gray > 250)
        return float(glare_pixels) / img_gray.size
    except Exception as e:
        logger.error(f"Error measuring glare: {e}")
        return 0.0

def measure_shadow(img: Image.Image) -> float:
    """Fraction of pixels that are near-black (potential underexposure)."""
    try:
        img_gray = np.array(img.convert('L'), dtype=np.uint8)
        shadow_pixels = np.sum(img_gray < 15)
        return float(shadow_pixels) / img_gray.size
    except Exception as e:
        logger.error(f"Error measuring shadow: {e}")
        return 0.0

def measure_rotation(img: Image.Image) -> float:
    """Estimates rotation angle of the document in degrees using minAreaRect on edges."""
    try:
        img_gray = np.array(img.convert('L'), dtype=np.uint8)
        edges = cv2.Canny(img_gray, 50, 150, apertureSize=3)
        pts = np.argwhere(edges > 0)
        if len(pts) > 20:
            # Swap columns to get (x, y)
            pts = pts[:, ::-1]
            rect = cv2.minAreaRect(pts)
            (cx, cy), (w, h), angle = rect
            if w < h:
                angle = angle + 90
            # Normalize to [-45, 45] range
            if angle > 45:
                angle -= 90
            elif angle < -45:
                angle += 90
            return float(angle)
        return 0.0
    except Exception as e:
        logger.error(f"Error measuring rotation: {e}")
        return 0.0

def detect_qr_codes(img: Image.Image) -> tuple:
    """Detects QR codes using OpenCV's QRCodeDetector.
    Returns (has_qr_codes, list_of_coordinates) where coordinate is {"x": int, "y": int, "width": int, "height": int}
    """
    try:
        cv_img = np.array(img.convert('RGB'))
        cv_img = cv2.cvtColor(cv_img, cv2.COLOR_RGB2BGR)
        detector = cv2.QRCodeDetector()
        retval, points = detector.detectMulti(cv_img)
        if retval and points is not None:
            coords = []
            for pts in points:
                min_x = int(np.min(pts[:, 0]))
                min_y = int(np.min(pts[:, 1]))
                max_x = int(np.max(pts[:, 0]))
                max_y = int(np.max(pts[:, 1]))
                w = max(0, max_x - min_x)
                h = max(0, max_y - min_y)
                coords.append({"x": min_x, "y": min_y, "width": w, "height": h})
            return True, coords
        return False, []
    except Exception as e:
        logger.error(f"Error detecting QR codes: {e}")
        return False, []

def measure_resolution(img: Image.Image) -> dict:
    """Returns width and height of the image."""
    return {"width": img.width, "height": img.height}

def build_quality_report(image_bytes: bytes) -> QualityReport:
    """Loads image and builds a full QualityReport."""
    try:
        img = Image.open(io.BytesIO(image_bytes))
        has_qr, qr_coords = detect_qr_codes(img)
        return QualityReport(
            blur=measure_blur(img),
            brightness=measure_brightness(img),
            contrast=measure_contrast(img),
            noise=measure_noise(img),
            glare=measure_glare(img),
            shadow=measure_shadow(img),
            rotation=measure_rotation(img),
            resolution=measure_resolution(img),
            has_qr_codes=has_qr,
            qr_coordinates=qr_coords
        )
    except Exception as e:
        logger.error(f"Failed to build quality report: {e}")
        # Return fallback report
        return QualityReport(
            blur=0.0,
            brightness=0.5,
            contrast=0.0,
            noise=0.0,
            glare=0.0,
            shadow=0.0,
            rotation=0.0,
            resolution={"width": 0, "height": 0},
            has_qr_codes=False,
            qr_coordinates=[]
        )
