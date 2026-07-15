"""Recovery Action Registry for processing/improving document images."""

import io
from typing import List, Dict, Any
from PIL import Image, ImageEnhance, ImageFilter
import numpy as np
import cv2
from log_utils.logger import get_logger

logger = get_logger("doc-capture-actions")

def auto_deskew(img: Image.Image) -> Image.Image:
    """Detects rotation angle using Canny + minAreaRect and rotates to align."""
    try:
        from quality_metrics import measure_rotation
        angle = measure_rotation(img)
        if abs(angle) > 0.5:
            fill_color = (255, 255, 255) if img.mode == 'RGB' else 255
            # PIL rotate is counter-clockwise, so negative of measured angle aligns it
            return img.rotate(-angle, resample=Image.BICUBIC, expand=False, fillcolor=fill_color)
        return img
    except Exception as e:
        logger.error(f"Error in auto_deskew action: {e}")
        return img

def remove_glare(img: Image.Image) -> Image.Image:
    """Reduces high contrast/luminance highlights."""
    try:
        enhancer = ImageEnhance.Brightness(img)
        img = enhancer.enhance(0.9)
        enhancer2 = ImageEnhance.Contrast(img)
        return enhancer2.enhance(0.95)
    except Exception as e:
        logger.error(f"Error in remove_glare: {e}")
        return img

def enhance_contrast(img: Image.Image) -> Image.Image:
    """Enhances text contrast for readability."""
    try:
        enhancer = ImageEnhance.Contrast(img)
        return enhancer.enhance(1.2)
    except Exception as e:
        logger.error(f"Error in enhance_contrast: {e}")
        return img

def crop_to_overlay(img: Image.Image) -> Image.Image:
    """Trims a 5% margin around the borders."""
    try:
        w, h = img.size
        margin_w = int(w * 0.05)
        margin_h = int(h * 0.05)
        return img.crop((margin_w, margin_h, w - margin_w, h - margin_h))
    except Exception as e:
        logger.error(f"Error in crop_to_overlay: {e}")
        return img

def sharpen(img: Image.Image) -> Image.Image:
    """Applies PIL Sharpen filter."""
    try:
        return img.filter(ImageFilter.SHARPEN)
    except Exception as e:
        logger.error(f"Error in sharpen: {e}")
        return img

def denoise(img: Image.Image) -> Image.Image:
    """Applies cv2.medianBlur to reduce noise."""
    try:
        img_np = np.array(img)
        denoised = cv2.medianBlur(img_np, 3)
        return Image.fromarray(denoised)
    except Exception as e:
        logger.error(f"Error in denoise: {e}")
        return img

def gamma(img: Image.Image) -> Image.Image:
    """Applies gamma correction (brightens shadows) using Look-Up Table (LUT)."""
    try:
        img_np = np.array(img)
        # Brightens shadow/midtones
        invGamma = 1.0 / 1.2
        table = np.array([((i / 255.0) ** invGamma) * 255 for i in range(256)]).astype("uint8")
        corrected = cv2.LUT(img_np, table)
        return Image.fromarray(corrected)
    except Exception as e:
        logger.error(f"Error in gamma correction: {e}")
        return img

def white_balance(img: Image.Image) -> Image.Image:
    """Performs Gray-World white balance normalization in LAB color space."""
    try:
        img_np = np.array(img)
        if len(img_np.shape) == 3 and img_np.shape[2] == 3:
            result = cv2.cvtColor(img_np, cv2.COLOR_RGB2LAB)
            l, a, b = cv2.split(result)
            mean_a = np.mean(a)
            mean_b = np.mean(b)
            a = cv2.addWeighted(a, 1, np.zeros_like(a), 0, 128 - int(mean_a))
            b = cv2.addWeighted(b, 1, np.zeros_like(b), 0, 128 - int(mean_b))
            result = cv2.merge([l, a, b])
            balanced = cv2.cvtColor(result, cv2.COLOR_LAB2RGB)
            return Image.fromarray(balanced)
        return img
    except Exception as e:
        logger.error(f"Error in white_balance: {e}")
        return img

def mask_qr_codes(img: Image.Image) -> Image.Image:
    """Detects QR codes and masks their regions with solid white blocks."""
    try:
        cv_img = np.array(img.convert('RGB'))
        cv_img = cv2.cvtColor(cv_img, cv2.COLOR_RGB2BGR)
        detector = cv2.QRCodeDetector()
        retval, points = detector.detectMulti(cv_img)
        if retval and points is not None:
            for pts in points:
                min_x = int(np.min(pts[:, 0]))
                min_y = int(np.min(pts[:, 1]))
                max_x = int(np.max(pts[:, 0]))
                max_y = int(np.max(pts[:, 1]))
                # Draw a solid white rectangle to mask the QR code region
                cv2.rectangle(cv_img, (min_x, min_y), (max_x, max_y), (255, 255, 255), -1)
            masked_rgb = cv2.cvtColor(cv_img, cv2.COLOR_BGR2RGB)
            return Image.fromarray(masked_rgb)
        return img
    except Exception as e:
        logger.error(f"Error in mask_qr_codes action: {e}")
        return img

RECOVERY_ACTIONS = {
    "auto_deskew": auto_deskew,
    "remove_glare": remove_glare,
    "enhance_contrast": enhance_contrast,
    "crop_to_overlay": crop_to_overlay,
    "sharpen": sharpen,
    "denoise": denoise,
    "gamma": gamma,
    "white_balance": white_balance,
    "mask_qr_codes": mask_qr_codes
}

RECOVERY_METADATA: Dict[str, Dict[str, Any]] = {
    "auto_deskew": {
        "purpose": "Correct document tilt and rotation.",
        "safe_before_detector": True,
        "safe_after_detector": False,
        "estimated_cost": 5.0
    },
    "remove_glare": {
        "purpose": "Reduce high reflection and glare spots.",
        "safe_before_detector": True,
        "safe_after_detector": True,
        "estimated_cost": 2.0
    },
    "enhance_contrast": {
        "purpose": "Enhance text contrast for OCR readability.",
        "safe_before_detector": True,
        "safe_after_detector": True,
        "estimated_cost": 1.0
    },
    "crop_to_overlay": {
        "purpose": "Trim unused borders.",
        "safe_before_detector": True,
        "safe_after_detector": False,
        "estimated_cost": 1.0
    },
    "sharpen": {
        "purpose": "Improve edge sharpness.",
        "safe_before_detector": True,
        "safe_after_detector": True,
        "estimated_cost": 1.5
    },
    "denoise": {
        "purpose": "Reduce sensor noise.",
        "safe_before_detector": True,
        "safe_after_detector": True,
        "estimated_cost": 3.0
    },
    "gamma": {
        "purpose": "Adjust brightness and bring out shadow details.",
        "safe_before_detector": True,
        "safe_after_detector": True,
        "estimated_cost": 1.0
    },
    "white_balance": {
        "purpose": "Normalize colors and white point.",
        "safe_before_detector": True,
        "safe_after_detector": True,
        "estimated_cost": 2.5
    },
    "mask_qr_codes": {
        "purpose": "Find and mask QR codes with solid blocks.",
        "safe_before_detector": True,
        "safe_after_detector": True,
        "estimated_cost": 2.0
    }
}

def preprocess_image(image_bytes: bytes, flags: List[str]) -> bytes:
    """Backward-compatible shim that delegates to recovery actions."""
    if not flags:
        return image_bytes
    try:
        img = Image.open(io.BytesIO(image_bytes))
        if img.mode != 'RGB':
            img = img.convert('RGB')
        for flag in flags:
            func = RECOVERY_ACTIONS.get(flag)
            if func:
                img = func(img)
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=85)
        return out.getvalue()
    except Exception as e:
        logger.error(f"Error in preprocess_image shim: {e}")
        return image_bytes
