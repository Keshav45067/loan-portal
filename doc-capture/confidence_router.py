from typing import Dict
from extraction import SlotResult
from log_utils.logger import get_logger

logger = get_logger("doc-capture")

def route_slot(slot_result: SlotResult, slot_def: dict, bands: dict) -> str:
    """
    Routes a slot to 'accept', 'confirm', or 'retake' based on criticality
    and confidence bands threshold.
    """
    if slot_result.value is None or slot_result.confidence <= 0.0:
        if slot_def.get("optional", False):
            return "accept"
        return "retake"
        
    criticality = slot_def.get("criticality", "standard")
    
    default_bands = {
        "critical": { "accept": 0.92, "confirm": 0.75 },
        "standard": { "accept": 0.85, "confirm": 0.65 },
        "low":      { "accept": 0.75, "confirm": 0.50 }
    }
    
    selected_bands = bands.get(criticality, default_bands.get(criticality, default_bands["standard"]))
    
    accept_thresh = selected_bands.get("accept", 0.85)
    confirm_thresh = selected_bands.get("confirm", 0.65)
    
    conf = slot_result.confidence
    
    logger.info(f"Router: slot '{slot_result.slot}' (criticality={criticality}, conf={conf:.2f}) -> accept_thresh={accept_thresh:.2f}, confirm_thresh={confirm_thresh:.2f}")
    
    if conf >= accept_thresh:
        return "accept"
    elif conf >= confirm_thresh:
        return "confirm"
    else:
        return "retake"
