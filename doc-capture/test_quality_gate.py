import pytest
from quality_gate import calculate_blur_variance, run_quality_gate, QualityResult

class MockOCRBlock:
    def __init__(self, text, confidence):
        self.text = text
        self.confidence = confidence

class MockOCRResponse:
    def __init__(self, success, error, raw_text, confidence, blocks):
        self.success = success
        self.error = error
        self.raw_text = raw_text
        self.confidence = confidence
        self.blocks = blocks

class MockOCRStub:
    def __init__(self, response):
        self.response = response
    async def ExtractText(self, request, timeout=None):
        return self.response

@pytest.mark.asyncio
async def test_run_quality_gate_passed():
    manifest = {
        "quality": {
            "blur_var_min": 10,
            "min_box_confidence": 0.50,
            "min_anchor_hits": 2
        },
        "parts": [
            {
                "id": "front",
                "anchors": ["Government of India", "DOB"]
            }
        ]
    }
    
    # Generate a dummy image with high variance
    from PIL import Image, ImageDraw
    import io
    img = Image.new('RGB', (100, 100), color='white')
    draw = ImageDraw.Draw(img)
    draw.line((0, 0, 100, 100), fill="black", width=2)
    img_bytes = io.BytesIO()
    img.save(img_bytes, format='JPEG')
    img_data = img_bytes.getvalue()
    
    # Mock successful OCR response containing anchors
    blocks = [
        MockOCRBlock("Government of India", 0.95),
        MockOCRBlock("DOB: 12/12/1990", 0.90)
    ]
    response = MockOCRResponse(
        success=True,
        error="",
        raw_text="Government of India\nDOB: 12/12/1990",
        confidence=0.92,
        blocks=blocks
    )
    stub = MockOCRStub(response)
    
    res = await run_quality_gate(img_data, manifest, stub, "en", "doc_aadhaar_002")
    assert res.passed is True
    assert res.part_id == "front"
    assert res.failure_reason == ""
    assert res.anchor_hits == 2

@pytest.mark.asyncio
async def test_run_quality_gate_blur_failure():
    manifest = {
        "quality": {
            "blur_var_min": 1000, # Set high to guarantee failure
            "min_box_confidence": 0.50,
            "min_anchor_hits": 2
        },
        "parts": []
    }
    
    # White blur image
    from PIL import Image
    import io
    img = Image.new('RGB', (100, 100), color='white')
    img_bytes = io.BytesIO()
    img.save(img_bytes, format='JPEG')
    img_data = img_bytes.getvalue()
    
    stub = MockOCRStub(None)
    res = await run_quality_gate(img_data, manifest, stub, "en", "doc_aadhaar_002")
    assert res.passed is False
    assert res.failure_reason == "blur"

def test_calculate_blur_variance_float_range():
    from PIL import Image, ImageDraw
    import io
    img = Image.new('L', (100, 100), color=0)
    draw = ImageDraw.Draw(img)
    for x in range(0, 100, 10):
        draw.rectangle([x, 0, x+5, 100], fill=255)
    img_bytes = io.BytesIO()
    img.save(img_bytes, format='PNG')
    data = img_bytes.getvalue()
    
    var = calculate_blur_variance(data)
    assert var > 300
