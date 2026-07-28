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
import uuid
import pickle
import grpc
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Request, UploadFile, File, Form, HTTPException
from pydantic import BaseModel
from PIL import Image, ImageDraw

# Append python paths so we can import from shared and doc-capture folders
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..', 'shared'))
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..', 'doc-capture'))
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'grpc_clients'))

from log_utils.logger import get_logger
from generated import ocr_pb2, ocr_pb2_grpc

# Import doc-capture pipeline components directly
from quality_metrics import build_quality_report
from recovery_engine import decide_recovery, apply_recovery
from recovery_actions import RECOVERY_ACTIONS
from quality_gate import run_quality_gate, calculate_blur_variance

logger = get_logger("gateway-sandbox")
router = APIRouter(prefix="/api/sandbox/pipeline", tags=["sandbox-pipeline"])

# In-memory + disk-backed sandbox session store for multi-worker Uvicorn support
SANDBOX_SESSIONS = {}
SANDBOX_TMP_DIR = "/tmp/sandbox_pipeline_sessions"
os.makedirs(SANDBOX_TMP_DIR, exist_ok=True)

def save_sandbox_session(session_id: str, data: dict):
    SANDBOX_SESSIONS[session_id] = data
    file_path = os.path.join(SANDBOX_TMP_DIR, f"{session_id}.pkl")
    try:
        with open(file_path, "wb") as f:
            pickle.dump(data, f)
    except Exception as e:
        logger.error(f"Failed to persist sandbox session to disk: {e}")

def get_sandbox_session(session_id: str) -> Optional[dict]:
    if not session_id:
        return None
    if session_id in SANDBOX_SESSIONS:
        return SANDBOX_SESSIONS[session_id]
    
    file_path = os.path.join(SANDBOX_TMP_DIR, f"{session_id}.pkl")
    if os.path.exists(file_path):
        try:
            with open(file_path, "rb") as f:
                data = pickle.load(f)
                SANDBOX_SESSIONS[session_id] = data
                return data
        except Exception as e:
            logger.error(f"Failed to load sandbox session from disk: {e}")
    return None

def remove_sandbox_session(session_id: str):
    SANDBOX_SESSIONS.pop(session_id, None)
    file_path = os.path.join(SANDBOX_TMP_DIR, f"{session_id}.pkl")
    if os.path.exists(file_path):
        try:
            os.remove(file_path)
        except Exception:
            pass

# --- Models ---
class StepRequest(BaseModel):
    image_base64: str
    action: str
    reason: str
    manifest_json: str
    page_id: str
    language: str = "en"
    document_id: str = "doc_sandbox"
    is_final_step: bool = False
    session_id: str = ""

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
    - Runs layout detection via PP-DocLayoutV3
    - Generates step-by-step pipeline decisions for each crop
    """
    logs = []
    try:
        image_bytes = await file.read()
        logs.append(f"[INFO] Loaded input image. Size: {len(image_bytes) / 1024:.1f} KB.")
        
        # 1. Parse manifest
        try:
            doc_config = json.loads(manifest_json)
            logs.append(f"[INFO] Successfully parsed Document Manifest (ID: {doc_config.get('document_id', 'unknown')}).")
        except Exception as json_err:
            logs.append(f"[ERROR] Failed to parse manifest JSON: {str(json_err)}")
            raise HTTPException(status_code=400, detail=f"Invalid manifest JSON: {str(json_err)}")

        # 2. Get OCR service address & call DetectLayout
        ocr_addr = os.getenv("OCR_SERVICE_ADDR", "ocr.augmen.io:443")
        channel_options = [
            ("grpc.max_send_message_length", 100 * 1024 * 1024),
            ("grpc.max_receive_message_length", 100 * 1024 * 1024),
        ]
        if "443" in ocr_addr:
            credentials = grpc.ssl_channel_credentials()
            channel = grpc.aio.secure_channel(ocr_addr, credentials, options=channel_options)
        else:
            channel = grpc.aio.insecure_channel(ocr_addr, options=channel_options)
        ocr_stub = ocr_pb2_grpc.OCRServiceStub(channel)

        logs.append("[INFO] Running layout detection on the whole image...")
        layouts = []
        try:
            layout_res = await ocr_stub.DetectLayout(ocr_pb2.LayoutRequest(
                image_data=image_bytes
            ), timeout=30.0)
            if layout_res.success:
                for layout_box in layout_res.layouts:
                    layouts.append({
                        "xmin": layout_box.xmin,
                        "ymin": layout_box.ymin,
                        "xmax": layout_box.xmax,
                        "ymax": layout_box.ymax,
                        "label": layout_box.label,
                        "score": layout_box.score
                    })
                logs.append(f"[INFO] Detected {len(layouts)} layout region(s).")
            else:
                logs.append(f"[WARNING] Layout detection returned success=False: {layout_res.error}")
        except Exception as e:
            logs.append(f"[ERROR] Layout detection gRPC call failed: {e}")
        finally:
            await channel.close()

        # Fallback to whole image if no layouts detected
        try:
            img = Image.open(io.BytesIO(image_bytes))
            width, height = img.size
        except Exception:
            width, height = 640, 480

        if not layouts:
            logs.append("[INFO] Falling back to whole image layout.")
            layouts.append({
                "xmin": 0,
                "ymin": 0,
                "xmax": width,
                "ymax": height,
                "label": "document",
                "score": 1.0
            })

        # 3. Build initial quality report for the whole image
        report = build_quality_report(image_bytes)
        metrics_dict = {
            "blur": report.blur,
            "brightness": report.brightness,
            "contrast": report.contrast,
            "noise": report.noise,
            "glare": report.glare,
            "shadow": report.shadow,
            "rotation": report.rotation,
            "resolution": report.resolution,
            "has_qr_codes": report.has_qr_codes,
            "qr_coordinates": report.qr_coordinates
        }

        # 4. Create and store sandbox session state
        session_id = str(uuid.uuid4())
        session_data = {
            "original_image_bytes": image_bytes,
            "layouts": layouts,
            "crop_images": {},
            "ocr_results": {}
        }
        save_sandbox_session(session_id, session_data)

        # 5. Populate step decisions list
        decisions_list = []
        decisions_list.append({
            "action": "detect_layouts",
            "reason": f"Visualize all {len(layouts)} detected layout regions on the whole image"
        })

        quality_policy = doc_config.get("quality_policy", {
            "allow_deskew": True,
            "allow_glare_removal": True,
            "allow_contrast_enhancement": True,
            "allow_denoise": False,
            "allow_gamma": False,
            "allow_white_balance": False,
            "allow_sharpen": True,
            "allow_qr_masking": True
        })
        quality_config = doc_config.get("quality", {})

        for idx, box in enumerate(layouts):
            decisions_list.append({
                "action": f"crop_layout_{idx}",
                "reason": f"Crop layout #{idx+1} (Label: {box['label']}, Score: {box['score']:.2f})"
            })
            
            # Check crop metrics and decide recovery steps
            try:
                xmin = max(0, min(box["xmin"], width))
                ymin = max(0, min(box["ymin"], height))
                xmax = max(0, min(box["xmax"], width))
                ymax = max(0, min(box["ymax"], height))
                
                if xmax > xmin and ymax > ymin:
                    crop_img = img.crop((xmin, ymin, xmax, ymax))
                    out = io.BytesIO()
                    crop_img.save(out, format="JPEG", quality=90)
                    crop_bytes = out.getvalue()
                    
                    crop_report = build_quality_report(crop_bytes)
                    crop_decisions = decide_recovery(crop_report, quality_policy, quality_config)
                    
                    for cd in crop_decisions:
                        decisions_list.append({
                            "action": f"preprocess_layout_{idx}_{cd.action}",
                            "reason": f"[Crop #{idx+1}] {cd.reason}"
                        })
            except Exception as e:
                logger.error(f"Failed to check recovery decisions for crop {idx}: {e}")

            decisions_list.append({
                "action": f"ocr_layout_{idx}",
                "reason": f"Perform OCR extraction on preprocessed crop #{idx+1}"
            })

        decisions_list.append({
            "action": "finalize",
            "reason": "Format and concatenate all layout OCR results into structured XML layout"
        })

        base64_image = base64.b64encode(image_bytes).decode("utf-8")

        return {
            "success": True,
            "session_id": session_id,
            "image_base64": base64_image,
            "decisions": decisions_list,
            "metrics": metrics_dict,
            "manifest": doc_config,
            "page_id": page_id,
            "language": language,
            "logs": logs,
            "quality_gate": None
        }
    except Exception as e:
        logger.error(f"Sandbox Init Failed: {e}", error=traceback.format_exc())
        return {"success": False, "error": str(e), "logs": logs}

@router.post("/step")
async def execute_pipeline_step(body: StepRequest):
    """
    Applies a single preprocessing crop, local recovery step, crop OCR, or final XML concat.
    """
    logs = []
    try:
        logs.append(f"[START] Executing step '{body.action}'...")
        session_id = body.session_id
        session = get_sandbox_session(session_id)
        if not session:
            logs.append("[ERROR] Sandbox session not found or expired.")
            return {"success": False, "error": "Sandbox session not found", "logs": logs}
            
        original_bytes = session["original_image_bytes"]
        layouts = session["layouts"]
        
        try:
            doc_config = json.loads(body.manifest_json)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid manifest JSON")

        new_image_bytes = None
        metrics_dict = None
        quality_gate_res = None

        if body.action == "detect_layouts":
            # Draw bounding boxes of layouts on the original image
            img = Image.open(io.BytesIO(original_bytes))
            if img.mode != "RGB":
                img = img.convert("RGB")
            draw = ImageDraw.Draw(img)
            for idx, box in enumerate(layouts):
                draw.rectangle([box["xmin"], box["ymin"], box["xmax"], box["ymax"]], outline="#3b82f6", width=4)
                draw.text((box["xmin"] + 5, box["ymin"] + 5), f"#{idx+1}: {box['label']} ({box['score']:.2f})", fill="#3b82f6")
            
            out = io.BytesIO()
            img.save(out, format="JPEG", quality=90)
            new_image_bytes = out.getvalue()
            logs.append(f"[SUCCESS] Visualized {len(layouts)} layout regions on original image.")
            
            # Recalculate metrics on whole image
            report = build_quality_report(original_bytes)
            metrics_dict = {
                "blur": report.blur, "brightness": report.brightness, "contrast": report.contrast,
                "noise": report.noise, "glare": report.glare, "shadow": report.shadow,
                "rotation": report.rotation, "resolution": report.resolution
            }

        elif body.action.startswith("crop_layout_"):
            idx = int(body.action.split("_")[-1])
            box = layouts[idx]
            
            img = Image.open(io.BytesIO(original_bytes))
            if img.mode != "RGB":
                img = img.convert("RGB")
            xmin = max(0, min(box["xmin"], img.width))
            ymin = max(0, min(box["ymin"], img.height))
            xmax = max(0, min(box["xmax"], img.width))
            ymax = max(0, min(box["ymax"], img.height))
            
            crop_img = img.crop((xmin, ymin, xmax, ymax))
            if crop_img.mode != "RGB":
                crop_img = crop_img.convert("RGB")
            out = io.BytesIO()
            crop_img.save(out, format="JPEG", quality=90)
            crop_bytes = out.getvalue()
            
            # Store in session state
            session["crop_images"][idx] = crop_bytes
            save_sandbox_session(session_id, session)
            new_image_bytes = crop_bytes
            logs.append(f"[SUCCESS] Cropped layout region #{idx+1} ({box['label']}). Size: {len(crop_bytes)/1024:.1f} KB.")
            
            # Recalculate metrics on crop
            report = build_quality_report(crop_bytes)
            metrics_dict = {
                "blur": report.blur, "brightness": report.brightness, "contrast": report.contrast,
                "noise": report.noise, "glare": report.glare, "shadow": report.shadow,
                "rotation": report.rotation, "resolution": report.resolution
            }

        elif body.action.startswith("preprocess_layout_"):
            # Format: preprocess_layout_{idx}_{recovery_action}
            parts = body.action.split("_")
            idx = int(parts[2])
            action = "_".join(parts[3:])
            
            crop_bytes = session["crop_images"].get(idx)
            if not crop_bytes:
                box = layouts[idx]
                img = Image.open(io.BytesIO(original_bytes))
                xmin = max(0, min(box["xmin"], img.width))
                ymin = max(0, min(box["ymin"], img.height))
                xmax = max(0, min(box["xmax"], img.width))
                ymax = max(0, min(box["ymax"], img.height))
                crop_img = img.crop((xmin, ymin, xmax, ymax))
                out = io.BytesIO()
                crop_img.save(out, format="JPEG", quality=90)
                crop_bytes = out.getvalue()
                
            func = RECOVERY_ACTIONS.get(action)
            if func:
                c_img = Image.open(io.BytesIO(crop_bytes))
                processed_img = func(c_img)
                out = io.BytesIO()
                processed_img.save(out, format="JPEG", quality=90)
                processed_bytes = out.getvalue()
                session["crop_images"][idx] = processed_bytes
                save_sandbox_session(session_id, session)
                new_image_bytes = processed_bytes
                logs.append(f"[SUCCESS] Applied recovery '{action}' to crop #{idx+1}.")
            else:
                new_image_bytes = crop_bytes
                logs.append(f"[WARNING] Recovery '{action}' not found. Skipping.")
                
            report = build_quality_report(new_image_bytes)
            metrics_dict = {
                "blur": report.blur, "brightness": report.brightness, "contrast": report.contrast,
                "noise": report.noise, "glare": report.glare, "shadow": report.shadow,
                "rotation": report.rotation, "resolution": report.resolution
            }

        elif body.action.startswith("ocr_layout_"):
            idx = int(body.action.split("_")[-1])
            crop_bytes = session["crop_images"].get(idx)
            box = layouts[idx]
            
            if not crop_bytes:
                img = Image.open(io.BytesIO(original_bytes))
                xmin = max(0, min(box["xmin"], img.width))
                ymin = max(0, min(box["ymin"], img.height))
                xmax = max(0, min(box["xmax"], img.width))
                ymax = max(0, min(box["ymax"], img.height))
                crop_img = img.crop((xmin, ymin, xmax, ymax))
                out = io.BytesIO()
                crop_img.save(out, format="JPEG", quality=90)
                crop_bytes = out.getvalue()
                session["crop_images"][idx] = crop_bytes

            ocr_addr = os.getenv("OCR_SERVICE_ADDR", "ocr.augmen.io:443")
            channel_options = [
                ("grpc.max_send_message_length", 100 * 1024 * 1024),
                ("grpc.max_receive_message_length", 100 * 1024 * 1024),
            ]
            if "443" in ocr_addr:
                credentials = grpc.ssl_channel_credentials()
                channel = grpc.aio.secure_channel(ocr_addr, credentials, options=channel_options)
            else:
                channel = grpc.aio.insecure_channel(ocr_addr, options=channel_options)
            ocr_stub = ocr_pb2_grpc.OCRServiceStub(channel)
            
            crop_text = ""
            crop_confidence = 0.0
            try:
                ocr_res = await ocr_stub.ExtractText(ocr_pb2.OCRRequest(
                    image_data=crop_bytes,
                    language=body.language,
                    hint=body.document_id,
                    spotting=False
                ), timeout=30.0)
                if ocr_res.success:
                    import re
                    crop_text = re.sub(r'<\|LOC_\d+\|>', '', ocr_res.raw_text).strip()
                    crop_confidence = ocr_res.confidence
                    logs.append(f"[OCR] Extracted text from crop #{idx+1} successfully.")
                else:
                    logs.append(f"[ERROR] OCR service failed for crop #{idx+1}: {ocr_res.error}")
            except Exception as e:
                logs.append(f"[ERROR] OCR gRPC call failed for crop #{idx+1}: {e}")
            finally:
                await channel.close()

            session["ocr_results"][idx] = {
                "text": crop_text,
                "confidence": crop_confidence,
                "box": box
            }
            save_sandbox_session(session_id, session)
            new_image_bytes = crop_bytes
            report = build_quality_report(crop_bytes)
            metrics_dict = {
                "blur": report.blur, "brightness": report.brightness, "contrast": report.contrast,
                "noise": report.noise, "glare": report.glare, "shadow": report.shadow,
                "rotation": report.rotation, "resolution": report.resolution
            }
            
            quality_gate_res = {
                "passed": crop_confidence >= doc_config.get("quality", {}).get("min_box_confidence", 0.50),
                "part_id": f"layout_crop_{idx}",
                "ocr_text": crop_text,
                "ocr_confidence": crop_confidence,
                "failure_reason": "" if crop_confidence >= doc_config.get("quality", {}).get("min_box_confidence", 0.50) else "low_confidence",
                "anchor_hits": 0,
                "anchors_detailed": {}
            }

        elif body.action == "finalize":
            xml_parts = []
            crop_confidences = []
            
            for idx in sorted(session["ocr_results"].keys()):
                res = session["ocr_results"][idx]
                box = res["box"]
                xmin = max(0, min(box["xmin"], 10000))
                ymin = max(0, min(box["ymin"], 10000))
                xmax = max(0, min(box["xmax"], 10000))
                ymax = max(0, min(box["ymax"], 10000))
                
                clean_text = res["text"].strip()
                xml_tag = f'<layout label="{box["label"]}" xmin="{xmin}" ymin="{ymin}" xmax="{xmax}" ymax="{ymax}">\n{clean_text}\n</layout>'
                xml_parts.append(xml_tag)
                crop_confidences.append(res["confidence"])

            final_xml = "\n".join(xml_parts)
            avg_confidence = sum(crop_confidences) / len(crop_confidences) if crop_confidences else 0.0
            
            translit_map = str.maketrans("०१२३४५६७८९", "0123456789")
            clean_raw_text = final_xml.translate(translit_map)
            clean_lower_text = clean_raw_text.lower()
            
            best_part_id = ""
            max_hits = -1
            
            parts = doc_config.get("parts", [])
            for part in parts:
                anchors = part.get("anchors", [])
                hits = 0
                for anchor in anchors:
                    if anchor.lower() in clean_lower_text:
                        hits += 1
                if hits > max_hits:
                    max_hits = hits
                    best_part_id = part.get("id", "")
                    
            anchors_detailed = {}
            for part in parts:
                p_id = part.get("id", "")
                anchors_detailed[p_id] = []
                for a in part.get("anchors", []):
                    matched = a.lower() in clean_lower_text
                    anchors_detailed[p_id].append({"anchor": a, "matched": matched})
                    
            passed = True
            failure_reason = ""
            main_blur = calculate_blur_variance(original_bytes)
            blur_var_min = doc_config.get("quality", {}).get("blur_var_min", 100)
            min_box_confidence = doc_config.get("quality", {}).get("min_box_confidence", 0.50)
            min_anchor_hits = doc_config.get("quality", {}).get("min_anchor_hits", 2)
            
            if main_blur < blur_var_min:
                passed = False
                failure_reason = "blur"
            elif avg_confidence < min_box_confidence:
                passed = False
                failure_reason = "low_confidence"
            elif max_hits < min_anchor_hits:
                passed = False
                failure_reason = "wrong_page"

            quality_gate_res = {
                "passed": passed,
                "part_id": best_part_id,
                "ocr_text": clean_raw_text,
                "ocr_confidence": avg_confidence,
                "failure_reason": failure_reason,
                "anchor_hits": max_hits,
                "anchors_detailed": anchors_detailed
            }
            logs.append(f"[SUCCESS] Finalized layout-based OCR pipeline. Passed: {passed}, Identity: '{best_part_id}', Average Confidence: {avg_confidence:.2f}")
            
            new_image_bytes = original_bytes
            report = build_quality_report(original_bytes)
            metrics_dict = {
                "blur": report.blur, "brightness": report.brightness, "contrast": report.contrast,
                "noise": report.noise, "glare": report.glare, "shadow": report.shadow,
                "rotation": report.rotation, "resolution": report.resolution
            }
            
            remove_sandbox_session(session_id)

        base64_image = base64.b64encode(new_image_bytes).decode("utf-8")
        return {
            "success": True,
            "image_base64": base64_image,
            "metrics": metrics_dict,
            "quality_gate": quality_gate_res,
            "logs": logs
        }
    except Exception as e:
        logs.append(f"[FATAL] Step Execution Failed: {str(e)}")
        logger.error(f"Sandbox Step Execution Failed: {e}", error=traceback.format_exc())
        return {"success": False, "error": str(e), "logs": logs}
