import io
import math
from dataclasses import dataclass
from PIL import Image, ImageFilter
from log_utils.logger import get_logger
import grpc

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
        img = Image.open(io.BytesIO(image_bytes)).convert('L')
        # Apply Laplacian filter (built-in 3x3 Laplacian in Pillow)
        laplacian_img = img.filter(ImageFilter.LAPLACIAN)
        pixels = list(laplacian_img.getdata())
        n = len(pixels)
        if n <= 1:
            return 0.0
        mean = sum(pixels) / n
        variance = sum((x - mean) ** 2 for x in pixels) / n
        return variance
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
        
    # 2. OCR via OCR Service
    from generated import ocr_pb2
    try:
        # Check if the expected part specifies table recognition format
        is_table = False
        if part_id:
            for part in manifest.get("parts", []):
                if part.get("id") == part_id:
                    if part.get("table") is True:
                        is_table = True
                    break

        ocr_hint = "Table Recognition:" if is_table else document_id

        ocr_res = await ocr_stub.ExtractText(ocr_pb2.OCRRequest(
            image_data=image_bytes,
            language=language,
            hint=ocr_hint
        ), timeout=30.0)
        
        if not ocr_res.success:
            logger.error(f"QualityGate: OCR service failed: {ocr_res.error}")
            return QualityResult(
                passed=False,
                part_id="",
                ocr_text="",
                ocr_confidence=0.0,
                failure_reason="low_confidence",
                anchor_hits=0
            )
            
        # Reconstruct raw_text with inline confidence scores for the LLM
        formatted_text_blocks = []
        for block in ocr_res.blocks:
            formatted_text_blocks.append(f"[Conf: {block.confidence:.2f}] {block.text}")
            
        raw_text = "\n".join(formatted_text_blocks) if formatted_text_blocks else ocr_res.raw_text
        ocr_confidence = ocr_res.confidence
    except grpc.RpcError as e:
        logger.error(f"QualityGate: OCR gRPC call failed: {e}")
        return QualityResult(
            passed=False,
            part_id="",
            ocr_text="",
            ocr_confidence=0.0,
            failure_reason="low_confidence",
            anchor_hits=0
        )
        
    # 3. Confidence gate
    logger.info(f"QualityGate: OCR confidence = {ocr_confidence:.2f} (min threshold = {min_box_confidence})")
    if ocr_confidence < min_box_confidence:
        return QualityResult(
            passed=False,
            part_id="",
            ocr_text=raw_text,
            ocr_confidence=ocr_confidence,
            failure_reason="low_confidence",
            anchor_hits=0
        )
        
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
