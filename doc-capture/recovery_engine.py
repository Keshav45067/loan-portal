"""Recovery Engine for analyzing metrics and applying image quality recovery."""

import io
from enum import Enum
from dataclasses import dataclass
from typing import List, Dict, Any
from PIL import Image
from log_utils.logger import get_logger
from quality_metrics import QualityReport
from recovery_actions import RECOVERY_ACTIONS

logger = get_logger("doc-capture-recovery")

class StageResult(Enum):
    PASS = "PASS"
    FIXABLE = "FIXABLE"
    RETRY_USER = "RETRY_USER"
    FAIL = "FAIL"

@dataclass
class RecoveryDecision:
    action: str
    reason: str

# Default quality thresholds
DEFAULT_THRESHOLDS = {
    "blur_var_min": 200.0,
    "brightness_min": 0.25,
    "brightness_max": 0.85,
    "contrast_min": 0.15,
    "glare_max": 0.05,
    "shadow_max": 0.10,
    "rotation_max": 3.0,
    "blur_unrecoverable_floor": 30.0
}

# Ordered recovery execution queue to ensure correct sequencing (e.g. deskew first, sharpen last)
ACTION_ORDER = [
    "auto_deskew",
    "crop_to_overlay",
    "mask_qr_codes",
    "white_balance",
    "denoise",
    "gamma",
    "remove_glare",
    "enhance_contrast",
    "adaptive_threshold",
    "sharpen"
]

def decide_recovery(
    report: QualityReport,
    quality_policy: Dict[str, bool],
    quality_thresholds: Dict[str, float] = None
) -> List[RecoveryDecision]:
    """Analyzes report and returns a list of recovery actions to apply."""
    if quality_thresholds is None:
        quality_thresholds = DEFAULT_THRESHOLDS
    else:
        # Merge defaults
        merged = DEFAULT_THRESHOLDS.copy()
        merged.update(quality_thresholds)
        quality_thresholds = merged

    decisions: List[RecoveryDecision] = []

    # 1. Check for unrecoverable blur floor
    blur_min = quality_thresholds.get("blur_var_min", 200.0)
    blur_floor = quality_thresholds.get("blur_unrecoverable_floor", 30.0)
    if report.blur < blur_floor:
        logger.warning(f"Blur ({report.blur:.1f}) is below unrecoverable floor ({blur_floor}), forcing RETRY_USER.")
        # We don't append any decisions; returning empty/incomplete lets pipeline know it's unrecoverable
        return []

    # 2. Rotation / Deskew
    rot_max = quality_thresholds.get("rotation_max", 3.0)
    if abs(report.rotation) > rot_max:
        if quality_policy.get("allow_deskew", True):
            decisions.append(RecoveryDecision("auto_deskew", f"Rotation of {report.rotation:.1f} degrees exceeds threshold of {rot_max}"))

    # 3. Brightness / Under-exposure / Over-exposure
    b_min = quality_thresholds.get("brightness_min", 0.25)
    b_max = quality_thresholds.get("brightness_max", 0.85)
    if report.brightness < b_min:
        if quality_policy.get("allow_gamma", True):
            decisions.append(RecoveryDecision("gamma", f"Brightness of {report.brightness:.2f} is below threshold of {b_min}"))
    elif report.brightness > b_max:
        if quality_policy.get("allow_glare_removal", True):
            decisions.append(RecoveryDecision("remove_glare", f"Brightness of {report.brightness:.2f} exceeds threshold of {b_max}"))

    # 4. Contrast
    c_min = quality_thresholds.get("contrast_min", 0.15)
    if report.contrast < c_min:
        if quality_policy.get("allow_contrast_enhancement", True):
            decisions.append(RecoveryDecision("enhance_contrast", f"Contrast of {report.contrast:.2f} is below threshold of {c_min}"))

    # 4b. Local Contrast (Adaptive Thresholding)
    if getattr(report, "has_low_contrast_regions", False):
        if quality_policy.get("allow_adaptive_thresholding", False):
            decisions.append(RecoveryDecision("adaptive_threshold", "Detected local low-contrast text regions in the document"))

    # 5. Glare
    g_max = quality_thresholds.get("glare_max", 0.05)
    if report.glare > g_max:
        if quality_policy.get("allow_glare_removal", True) and not any(d.action == "remove_glare" for d in decisions):
            decisions.append(RecoveryDecision("remove_glare", f"Glare fraction {report.glare:.2f} exceeds threshold of {g_max}"))

    # 6. Shadow
    s_max = quality_thresholds.get("shadow_max", 0.10)
    if report.shadow > s_max:
        if quality_policy.get("allow_gamma", True) and not any(d.action == "gamma" for d in decisions):
            decisions.append(RecoveryDecision("gamma", f"Shadow fraction {report.shadow:.2f} exceeds threshold of {s_max}"))

    # 7. Blur / Sharpen (if not below floor but below target)
    if report.blur < blur_min:
        if quality_policy.get("allow_sharpen", True):
            decisions.append(RecoveryDecision("sharpen", f"Blur variance {report.blur:.1f} is below threshold of {blur_min}"))

    # 8. White Balance (if enabled)
    if quality_policy.get("allow_white_balance", False):
        decisions.append(RecoveryDecision("white_balance", "White balance normalization requested by policy"))

    # 9. Denoise (if enabled)
    if quality_policy.get("allow_denoise", False):
        decisions.append(RecoveryDecision("denoise", "Noise reduction requested by policy"))

    # 10. QR Code Masking (if has QR code and enabled by policy)
    if report.has_qr_codes:
        if quality_policy.get("allow_qr_masking", True) or quality_policy.get("allow_qr_code_masking", True):
            decisions.append(RecoveryDecision("mask_qr_codes", f"Detected {len(report.qr_coordinates)} QR code(s) requiring masking"))

    # Cap total actions to 3 to prevent over-processing / high latency
    if len(decisions) > 3:
        logger.info(f"Capping decisions (found {len(decisions)}) to max 3 actions.")
        decisions = decisions[:3]

    return decisions

def apply_recovery(image_bytes: bytes, decisions: List[RecoveryDecision]) -> bytes:
    """Applies recovery decisions in sequential dependency order."""
    if not decisions:
        return image_bytes

    try:
        img = Image.open(io.BytesIO(image_bytes))
        
        # Sort decisions by ACTION_ORDER index, unmapped actions go to end
        def get_order_idx(d: RecoveryDecision) -> int:
            try:
                return ACTION_ORDER.index(d.action)
            except ValueError:
                return len(ACTION_ORDER)
                
        sorted_decisions = sorted(decisions, key=get_order_idx)

        for d in sorted_decisions:
            func = RECOVERY_ACTIONS.get(d.action)
            if func:
                logger.info(f"Applying recovery action '{d.action}' because: {d.reason}")
                img = func(img)
                
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=85)
        return out.getvalue()
    except Exception as e:
        logger.error(f"Error applying recovery actions: {e}")
        return image_bytes
