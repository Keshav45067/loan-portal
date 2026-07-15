"""
Sandbox Pipeline Routes — step-by-step document capture pipeline debugger.
Allows users to upload an image and manifest, inspect initial quality metrics,
and execute preprocessing recovery steps one by one, inspecting metrics and OCR/QualityGate at each step.
"""

import sys
import os
import io
import json
import base64
import traceback
import grpc
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Request, UploadFile, File, Form, HTTPException
from pydantic import BaseModel
from PIL import Image

# Insert python paths so we can import from shared and doc-capture folders
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'shared'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'doc-capture'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'grpc_clients'))

from log_utils.logger import get_logger
from generated import ocr_pb2, ocr_pb2_grpc

# Import doc-capture pipeline components directly (as requested to reflect updates automatically)
from quality_metrics import build_quality_report
from recovery_engine import decide_recovery
from recovery_actions import RECOVERY_ACTIONS
from quality_gate import run_quality_gate

logger = get_logger("gateway-sandbox")
router = APIRouter(prefix="/api/sandbox/pipeline", tags=["sandbox-pipeline"])

# --- Models ---
class StepRequest(BaseModel):
    image_base64: str
    action: str
    reason: str
    manifest_json: str
    page_id: str
    language: str = "en"
    document_id: str = "doc_sandbox"

@router.post("/init")
async def init_pipeline_sandbox(
    file: UploadFile = File(...),
    manifest_json: str = Form(...),
    page_id: str = Form(...),
    language: str = Form("en")
):
    """
    Initializes a step-by-step sandbox session:
    - Reads uploaded image bytes
    - Generates initial QualityReport
    - Computes planned recovery decisions based on manifest configuration
    """
    try:
        image_bytes = await file.read()
        
        # 1. Parse manifest
        try:
            doc_config = json.loads(manifest_json)
        except Exception as json_err:
            raise HTTPException(status_code=400, detail=f"Invalid manifest JSON: {str(json_err)}")
            
        # 2. Build initial quality report
        report = build_quality_report(image_bytes)
        
        # 3. Determine quality policy
        quality_policy = doc_config.get("quality_policy", {
            "allow_deskew": True,
            "allow_glare_removal": True,
            "allow_contrast_enhancement": True,
            "allow_denoise": False,
            "allow_gamma": False,
            "allow_white_balance": False,
            "allow_sharpen": False
        })
        if "quality_policy" not in doc_config and "preprocessing" in doc_config:
            pre_flags = doc_config["preprocessing"]
            quality_policy = {
                "allow_deskew": "auto_deskew" in pre_flags,
                "allow_glare_removal": "remove_glare" in pre_flags,
                "allow_contrast_enhancement": "enhance_contrast" in pre_flags,
                "allow_denoise": "denoise" in pre_flags,
                "allow_gamma": "gamma" in pre_flags,
                "allow_white_balance": "white_balance" in pre_flags,
                "allow_sharpen": "sharpen" in pre_flags
            }

        quality_config = doc_config.get("quality", {})
        
        # 4. Compute planned recovery decisions
        decisions = decide_recovery(report, quality_policy, quality_config)
        
        # Formulate response
        decisions_list = []
        for d in decisions:
            decisions_list.append({
                "action": d.action,
                "reason": d.reason
            })
            
        # Convert initial image to base64 for display
        base64_image = base64.b64encode(image_bytes).decode("utf-8")
        
        metrics_dict = {
            "blur": report.blur,
            "brightness": report.brightness,
            "contrast": report.contrast,
            "noise": report.noise,
            "glare": report.glare,
            "shadow": report.shadow,
            "rotation": report.rotation,
            "resolution": report.resolution
        }
        
        return {
            "success": True,
            "image_base64": base64_image,
            "decisions": decisions_list,
            "metrics": metrics_dict,
            "manifest": doc_config,
            "page_id": page_id,
            "language": language
        }
    except Exception as e:
        logger.error(f"Sandbox Init Failed: {e}", error=traceback.format_exc())
        return {"success": False, "error": str(e)}

@router.post("/step")
async def execute_pipeline_step(body: StepRequest):
    """
    Applies a single preprocessing step to the current base64 image,
    recalculates quality metrics, and runs the quality gate (OCR & Anchor Matching).
    """
    try:
        # 1. Decode base64 image
        try:
            image_bytes = base64.b64decode(body.image_base64)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid base64 image data")
            
        # 2. Parse manifest
        try:
            doc_config = json.loads(body.manifest_json)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid manifest JSON")
            
        # 3. Apply recovery action
        func = RECOVERY_ACTIONS.get(body.action)
        if func:
            try:
                img = Image.open(io.BytesIO(image_bytes))
                
                # Pillow RGBA to RGB conversion to prevent saving errors
                if img.mode == 'RGBA' or 'transparency' in img.info:
                    img = img.convert('RGB')
                    
                processed_img = func(img)
                
                # Save to JPEG bytes
                out = io.BytesIO()
                processed_img.save(out, format="JPEG", quality=90)
                new_image_bytes = out.getvalue()
            except Exception as proc_err:
                logger.error(f"Preprocessing action '{body.action}' failed: {proc_err}")
                new_image_bytes = image_bytes
        else:
            logger.warning(f"Action '{body.action}' not found in RECOVERY_ACTIONS. Skipping.")
            new_image_bytes = image_bytes
            
        # 4. Recalculate metrics on intermediate image
        report = build_quality_report(new_image_bytes)
        metrics_dict = {
            "blur": report.blur,
            "brightness": report.brightness,
            "contrast": report.contrast,
            "noise": report.noise,
            "glare": report.glare,
            "shadow": report.shadow,
            "rotation": report.rotation,
            "resolution": report.resolution
        }
        
        # 5. Initialize OCR gRPC client stub dynamically
        ocr_addr = os.getenv("OCR_SERVICE_ADDR", "localhost:50059")
        channel = grpc.aio.insecure_channel(ocr_addr, options=[
            ("grpc.max_send_message_length", 100 * 1024 * 1024),
            ("grpc.max_receive_message_length", 100 * 1024 * 1024),
        ])
        ocr_stub = ocr_pb2_grpc.OCRServiceStub(channel)
        
        # 6. Run Quality Gate (OCR + Anchor Matching)
        quality_gate_res = {"passed": False, "error": "Quality gate not run"}
        try:
            q_res = await run_quality_gate(
                image_bytes=new_image_bytes,
                manifest=doc_config,
                ocr_stub=ocr_stub,
                language=body.language,
                document_id=body.document_id,
                part_id=body.page_id
            )
            quality_gate_res = {
                "passed": q_res.passed,
                "part_id": q_res.part_id,
                "ocr_text": q_res.ocr_text,
                "ocr_confidence": q_res.ocr_confidence,
                "failure_reason": q_res.failure_reason,
                "anchor_hits": q_res.anchor_hits
            }
        except Exception as qg_err:
            logger.error(f"QualityGate run failed in sandbox: {qg_err}")
            quality_gate_res = {
                "passed": False,
                "error": str(qg_err),
                "ocr_text": "",
                "ocr_confidence": 0.0,
                "failure_reason": "gRPC_error",
                "anchor_hits": 0
            }
        finally:
            await channel.close()
            
        # Encode intermediate image back to base64
        base64_image = base64.b64encode(new_image_bytes).decode("utf-8")
        
        return {
            "success": True,
            "image_base64": base64_image,
            "metrics": metrics_dict,
            "quality_gate": quality_gate_res
        }
    except Exception as e:
        logger.error(f"Sandbox Step Execution Failed: {e}", error=traceback.format_exc())
        return {"success": False, "error": str(e)}
