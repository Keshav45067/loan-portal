import pytest
from quality_gate import run_quality_gate, QualityResult
from PIL import Image
import io

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

class MockOCRRetryStub:
    def __init__(self, confidences):
        self.confidences = confidences
        self.calls = 0
        
    async def ExtractText(self, request, timeout=None):
        conf = self.confidences[min(self.calls, len(self.confidences) - 1)]
        self.calls += 1
        blocks = [MockOCRBlock("Government of India", conf)]
        return MockOCRResponse(
            success=True,
            error="",
            raw_text="Government of India",
            confidence=conf,
            blocks=blocks
        )

@pytest.mark.asyncio
async def test_ocr_recovery_loop_success():
    # First attempt: 0.30 (fails confidence check)
    # Second attempt: 0.60 (passes confidence check)
    stub = MockOCRRetryStub([0.30, 0.60])
    
    manifest = {
        "quality": {
            "blur_var_min": 0, # Use 0 to pass on flat white test image
            "min_box_confidence": 0.50,
            "min_anchor_hits": 1
        },
        "parts": [
            {
                "id": "front",
                "anchors": ["Government of India"]
            }
        ]
    }
    
    img = Image.new('RGB', (100, 100), color='white')
    img_bytes = io.BytesIO()
    img.save(img_bytes, format='JPEG')
    data = img_bytes.getvalue()
    
    res = await run_quality_gate(data, manifest, stub, "en", "doc_aadhaar_002", "front")
    
    assert res.passed is True
    assert res.failure_reason == ""
    assert stub.calls == 2

@pytest.mark.asyncio
async def test_ocr_recovery_loop_failure():
    # All 3 attempts fail confidence check
    stub = MockOCRRetryStub([0.30, 0.40, 0.45])
    
    manifest = {
        "quality": {
            "blur_var_min": 0, # Use 0 to pass on flat white test image
            "min_box_confidence": 0.50,
            "min_anchor_hits": 1
        },
        "parts": [
            {
                "id": "front",
                "anchors": ["Government of India"]
            }
        ]
    }
    
    img = Image.new('RGB', (100, 100), color='white')
    img_bytes = io.BytesIO()
    img.save(img_bytes, format='JPEG')
    data = img_bytes.getvalue()
    
    res = await run_quality_gate(data, manifest, stub, "en", "doc_aadhaar_002", "front")
    
    assert res.passed is False
    assert res.failure_reason == "low_confidence"
    assert stub.calls == 3
