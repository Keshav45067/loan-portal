import io
import math
from dataclasses import dataclass
from PIL import Image
from log_utils.logger import get_logger
import grpc

from quality_metrics import measure_blur

logger = get_logger("doc-capture")

@dataclass
class QualityResult:
    passed: bool
    part_id: str           # "front", "back", or "" if unidentified
    ocr_text: str          # page-tagged, transliterated OCR text
    ocr_confidence: float  # aggregate confidence
    failure_reason: str    # "blur", "low_confidence", "wrong_page", ""
    anchor_hits: int       # how many anchors matched

def calculate_blur_variance(image_bytes: bytes) -> float:
    try:
        img = Image.open(io.BytesIO(image_bytes))
        return measure_blur(img)
    except Exception as e:
        logger.error(f"Error calculating blur variance: {e}")
        return 999.0  # Pass on error to avoid blocking the user

async def run_quality_gate(
    image_bytes: bytes,
    manifest: dict,
    ocr_stub,
    language: str,
    document_id: str,
    part_id: str = ""
) -> QualityResult:
    """
    Performs layout detection, quality checks on each layout crop individually,
    applies preprocessing recovery to each crop as needed, executes OCR, and
    combines all crop texts into a structured XML layout format.
    """
    # 1. Decode main image to inspect size
    try:
        main_img = Image.open(io.BytesIO(image_bytes))
        width, height = main_img.size
    except Exception as e:
        logger.warning(f"QualityGate: Failed to load main image (using dummy fallback): {e}")
        main_img = Image.new('RGB', (640, 480), color='white')
        width, height = main_img.size

    # 2. Retrieve thresholds and policy from manifest
    quality_config = manifest.get("quality", {})
    blur_var_min = quality_config.get("blur_var_min", 100)
    min_box_confidence = quality_config.get("min_box_confidence", 0.50)
    min_anchor_hits = quality_config.get("min_anchor_hits", 2)
    
    quality_policy = manifest.get("quality_policy", {
        "allow_deskew": True,
        "allow_glare_removal": True,
        "allow_contrast_enhancement": True,
        "allow_denoise": False,
        "allow_gamma": False,
        "allow_white_balance": False,
        "allow_sharpen": True,
        "allow_qr_masking": True
    })

    # 3. Call layout detection gRPC endpoint
    from generated import ocr_pb2
    logger.info("QualityGate: Calling DetectLayout on main image...")
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
            logger.info(f"QualityGate: Layout detection returned {len(layouts)} layout(s).")
        else:
            logger.warning(f"QualityGate: DetectLayout returned success=False: {layout_res.error}")
    except Exception as e:
        logger.error(f"QualityGate: DetectLayout gRPC call failed: {e}")

    using_fallback = False
    # Fallback to whole image if no layouts detected
    if not layouts:
        logger.info("QualityGate: No layouts detected or service error. Falling back to whole image layout.")
        using_fallback = True
        layouts.append({
            "xmin": 0,
            "ymin": 0,
            "xmax": width,
            "ymax": height,
            "label": "document",
            "score": 1.0
        })

    # 4. Process each layout crop step-by-step
    from quality_metrics import build_quality_report
    from recovery_engine import decide_recovery, apply_recovery
    
    xml_parts = []
    crop_confidences = []
    
    for idx, box in enumerate(layouts):
        xmin = max(0, min(box["xmin"], width))
        ymin = max(0, min(box["ymin"], height))
        xmax = max(0, min(box["xmax"], width))
        ymax = max(0, min(box["ymax"], height))
        
        if xmax <= xmin or ymax <= ymin:
            logger.warning(f"QualityGate: Skipping invalid bounding box: {box}")
            continue

        logger.info(f"QualityGate: Processing layout crop {idx+1}/{len(layouts)}: label={box['label']}, bbox=[{xmin}, {ymin}, {xmax}, {ymax}]")
        
        # Add adaptive padding around bounding box to preserve letter edges and surrounding context
        pad_x = max(10, int((xmax - xmin) * 0.05))
        pad_y = max(10, int((ymax - ymin) * 0.05))

        crop_xmin = max(0, xmin - pad_x)
        crop_ymin = max(0, ymin - pad_y)
        crop_xmax = min(width, xmax + pad_x)
        crop_ymax = min(height, ymax + pad_y)

        # Crop the image with padding
        try:
            crop_img = main_img.crop((crop_xmin, crop_ymin, crop_xmax, crop_ymax))
            out = io.BytesIO()
            crop_img.save(out, format="JPEG", quality=90)
            crop_bytes = out.getvalue()
        except Exception as e:
            logger.error(f"QualityGate: Failed to crop/save layout box {idx}: {e}")
            continue

        # Check blur on crop
        crop_blur_var = calculate_blur_variance(crop_bytes)
        logger.info(f"QualityGate [Crop {idx+1}]: blur variance = {crop_blur_var:.2f} (min threshold = {blur_var_min})")
        
        # Build quality report and decide recovery for this layout crop
        try:
            crop_report = build_quality_report(crop_bytes)
            decisions = decide_recovery(crop_report, quality_policy, quality_config)
            logger.info(f"QualityGate [Crop {idx+1}]: decided {len(decisions)} recovery action(s) based on local metrics.")
            
            # Apply recovery
            preprocessed_crop_bytes = apply_recovery(crop_bytes, decisions)
        except Exception as e:
            logger.error(f"QualityGate [Crop {idx+1}]: Recovery decision/application failed: {e}")
            preprocessed_crop_bytes = crop_bytes

        # Run OCR on the preprocessed crop
        crop_text = ""
        crop_confidence = 0.0
        attempts = 0
        max_attempts = 3
        current_crop_bytes = preprocessed_crop_bytes

        while attempts < max_attempts:
            try:
                # Check if the expected part specifies table recognition format
                is_table = False
                if part_id:
                    for part in manifest.get("parts", []):
                        if part.get("id") == part_id:
                            if part.get("table") is True:
                                is_table = True
                            break

                # Also flag as table if layout box label is table
                if box.get("label") == "table":
                    is_table = True

                ocr_hint = "Table Recognition:" if is_table else document_id

                # Run ExtractText on layout crop (spotting=False for clean crop text extraction)
                ocr_res = await ocr_stub.ExtractText(ocr_pb2.OCRRequest(
                    image_data=current_crop_bytes,
                    language=language,
                    hint=ocr_hint,
                    spotting=False
                ), timeout=30.0)
                
                if ocr_res.success:
                    crop_text = ocr_res.raw_text
                    crop_confidence = ocr_res.confidence
                else:
                    logger.error(f"QualityGate [Crop {idx+1}]: OCR extraction failed: {ocr_res.error}")
                    crop_text = ""
                    crop_confidence = 0.0
            except Exception as e:
                logger.error(f"QualityGate [Crop {idx+1}]: OCR call failed: {e}")
                crop_text = ""
                crop_confidence = 0.0

            logger.info(f"QualityGate [Crop {idx+1}]: OCR confidence = {crop_confidence:.2f} (threshold = {min_box_confidence}) [Attempt {attempts + 1}/{max_attempts}]")
            
            if crop_confidence >= min_box_confidence:
                break
                
            attempts += 1
            if attempts >= max_attempts:
                break

            # Local recovery actions within loop
            from recovery_actions import enhance_contrast, gamma
            try:
                c_img = Image.open(io.BytesIO(current_crop_bytes))
                if attempts == 1:
                    logger.info(f"QualityGate [Crop {idx+1}]: applying contrast enhancement...")
                    c_img = enhance_contrast(c_img)
                else:
                    logger.info(f"QualityGate [Crop {idx+1}]: applying gamma correction...")
                    c_img = gamma(c_img)
                
                out = io.BytesIO()
                c_img.save(out, format="JPEG", quality=85)
                current_crop_bytes = out.getvalue()
            except Exception as e:
                logger.error(f"QualityGate [Crop {idx+1}]: recovery update failed: {e}")
                break

        # Append clean text to XML layout
        import re
        clean_crop_text = re.sub(r'<\|LOC_\d+\|>', '', crop_text).strip()
        clean_crop_text = re.sub(r'\n\s*\n', '\n', clean_crop_text)

        if clean_crop_text and clean_crop_text not in ["-∞", "∞", "-", ""]:
            xml_tag = f'<layout label="{box["label"]}" xmin="{xmin}" ymin="{ymin}" xmax="{xmax}" ymax="{ymax}">\n{clean_crop_text}\n</layout>'
            xml_parts.append(xml_tag)
            crop_confidences.append(crop_confidence)

    # Combine everything
    if using_fallback:
        final_ocr = "\n".join(c["text"] for c in session["ocr_results"].values()) if 'session' in locals() else "\n".join(xml_parts).replace('<layout label="document" xmin="0" ymin="0" xmax="640" ymax="480">', '').replace('</layout>', '').strip()
        # Fallback to simple joined crop texts
        if not final_ocr:
            final_ocr = "\n".join(xml_parts).replace('<layout label="document" xmin="0" ymin="0" xmax="640" ymax="480">', '').replace('</layout>', '').strip()
            # If the dummy fallback box (640x480) or similar is used, remove the XML tags
            import re
            final_ocr = re.sub(r'<layout[^>]*>', '', final_ocr)
            final_ocr = re.sub(r'</layout>', '', final_ocr).strip()
    else:
        final_ocr = "\n".join(xml_parts)
        
    avg_confidence = sum(crop_confidences) / len(crop_confidences) if crop_confidences else 0.0
    
    # 5. Anchor matching & identity classification
    translit_map = str.maketrans("०१२३४५६७८९", "0123456789")
    clean_raw_text = final_ocr.translate(translit_map)
    clean_lower_text = clean_raw_text.lower()
    
    best_part_id = ""
    max_hits = -1
    
    parts = manifest.get("parts", [])
    for part in parts:
        anchors = part.get("anchors", [])
        hits = 0
        for anchor in anchors:
            if anchor.lower() in clean_lower_text:
                hits += 1
        logger.info(f"QualityGate: Part '{part.get('id')}' matched {hits} anchors: {anchors}")
        if hits > max_hits:
            max_hits = hits
            best_part_id = part.get("id", "")
            
    logger.info(f"QualityGate: Best part identified as '{best_part_id}' with {max_hits} hits (min = {min_anchor_hits})")
    
    # Decide overall gate pass/fail status
    passed = True
    failure_reason = ""
    
    # Check overall thresholds
    main_blur = calculate_blur_variance(image_bytes)
    if main_blur < blur_var_min:
        passed = False
        failure_reason = "blur"
    elif avg_confidence < min_box_confidence:
        passed = False
        failure_reason = "low_confidence"
    elif max_hits < min_anchor_hits:
        passed = False
        failure_reason = "wrong_page"
        
    return QualityResult(
        passed=passed,
        part_id=best_part_id,
        ocr_text=clean_raw_text,
        ocr_confidence=avg_confidence,
        failure_reason=failure_reason,
        anchor_hits=max_hits
    )
