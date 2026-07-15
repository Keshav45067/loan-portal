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
    Performs image QC, calls OCR service, identifies the page part via anchors,
    and returns a QualityResult.
    """
    quality_config = manifest.get("quality", {})
    blur_var_min = quality_config.get("blur_var_min", 100)
    min_box_confidence = quality_config.get("min_box_confidence", 0.50)
    min_anchor_hits = quality_config.get("min_anchor_hits", 2)
    
    # 1. Blur check
    blur_var = calculate_blur_variance(image_bytes)
    logger.info(f"QualityGate: calculated blur variance = {blur_var:.2f} (min threshold = {blur_var_min})")
    if blur_var < blur_var_min:
        return QualityResult(
            passed=False,
            part_id="",
            ocr_text="",
            ocr_confidence=0.0,
            failure_reason="blur",
            anchor_hits=0
        )
        
    # 2. OCR via OCR Service (with recovery retry loop)
    from generated import ocr_pb2
    attempts = 0
    max_attempts = 3
    current_image_bytes = image_bytes
    raw_text = ""
    ocr_confidence = 0.0

    while attempts < max_attempts:
        try:
            # Check if the expected part specifies table recognition format or spotting
            is_table = False
            spotting_flag = False
            if part_id:
                for part in manifest.get("parts", []):
                    if part.get("id") == part_id:
                        if part.get("table") is True:
                            is_table = True
                        if part.get("spotting") is True:
                            spotting_flag = True
                        break

            ocr_hint = "Table Recognition:" if is_table else document_id

            ocr_res = await ocr_stub.ExtractText(ocr_pb2.OCRRequest(
                image_data=current_image_bytes,
                language=language,
                hint=ocr_hint,
                spotting=spotting_flag
            ), timeout=30.0)
            
            if not ocr_res.success:
                logger.error(f"QualityGate: OCR service failed: {ocr_res.error}")
                ocr_confidence = 0.0
                raw_text = ""
            else:
                xml_layout = getattr(ocr_res, "xml_layout", "")
                if xml_layout and isinstance(xml_layout, str):
                    raw_text = xml_layout
                else:
                    formatted_text_blocks = []
                    for block in ocr_res.blocks:
                        formatted_text_blocks.append(f"[Conf: {block.confidence:.2f}] {block.text}")
                    raw_text = "\n".join(formatted_text_blocks) if formatted_text_blocks else ocr_res.raw_text
                ocr_confidence = ocr_res.confidence
        except grpc.RpcError as e:
            logger.error(f"QualityGate: OCR gRPC call failed: {e}")
            ocr_confidence = 0.0
            raw_text = ""

        logger.info(f"QualityGate: OCR confidence = {ocr_confidence:.2f} (min threshold = {min_box_confidence}) [Attempt {attempts + 1}/{max_attempts}]")
        
        if ocr_confidence >= min_box_confidence:
            break
            
        attempts += 1
        if attempts >= max_attempts:
            return QualityResult(
                passed=False,
                part_id="",
                ocr_text=raw_text,
                ocr_confidence=ocr_confidence,
                failure_reason="low_confidence",
                anchor_hits=0
            )

        from recovery_actions import enhance_contrast, gamma
        try:
            img = Image.open(io.BytesIO(image_bytes))
            if attempts == 1:
                logger.info("QualityGate: OCR confidence below threshold. Applying recovery action: enhance_contrast and retrying OCR.")
                img = enhance_contrast(img)
            else:
                logger.info("QualityGate: OCR confidence below threshold. Applying recovery action: gamma correction and retrying OCR.")
                img = gamma(img)
            out = io.BytesIO()
            img.save(out, format="JPEG", quality=85)
            current_image_bytes = out.getvalue()
        except Exception as e:
            logger.error(f"QualityGate: failed to apply OCR recovery action: {e}")
            pass
        
    # Translate Devanagari numerals to ASCII so LLM doesn't get confused
    translit_map = str.maketrans("०१२३४५६७८९", "0123456789")
    clean_raw_text = raw_text.translate(translit_map)
    clean_lower_text = clean_raw_text.lower()
    
    # 4. Anchor matching & identity classification
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
            
    # Check if we met the minimum anchor hit threshold
    logger.info(f"QualityGate: best part identified as '{best_part_id}' with {max_hits} hits (min = {min_anchor_hits})")
    if max_hits < min_anchor_hits:
        return QualityResult(
            passed=False,
            part_id="",
            ocr_text=clean_raw_text,
            ocr_confidence=ocr_confidence,
            failure_reason="wrong_page",
            anchor_hits=max_hits
        )
        
    return QualityResult(
        passed=True,
        part_id=best_part_id,
        ocr_text=clean_raw_text,
        ocr_confidence=ocr_confidence,
        failure_reason="",
        anchor_hits=max_hits
    )
