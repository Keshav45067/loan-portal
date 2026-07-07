import pytest
import json
from unittest.mock import AsyncMock, MagicMock
from server import DocumentCaptureServicer
from generated import doc_capture_pb2 as pb2
from session_manager import session_manager
from config_loader import config_loader

class MockContext:
    def invocation_metadata(self):
        return []

@pytest.mark.asyncio
async def test_process_document_pdf_success():
    # 1. Create a dummy session
    session_id = "test-session-pdf-123"
    config_loader.load_registry()
    
    session = session_manager.create_session(session_id, "scheme_micro_business_001", "en")
    assert session is not None
    
    # Clear any previous coverage map
    session.coverage_map[session.get_current_document_id()].clear()
    
    # 2. Mock stubs on servicer
    servicer = DocumentCaptureServicer()
    servicer.ocr_stub = AsyncMock()
    servicer.llm_stub = AsyncMock()
    servicer.orch_stub = AsyncMock()
    
    # Mock OCR response containing all front and back anchors
    class MockOCRResponse:
        success = True
        error = ""
        raw_text = "Government of India DOB Address PIN S/O"
        confidence = 0.95
        blocks = []
    
    servicer.ocr_stub.ExtractText.return_value = MockOCRResponse()
    
    # Mock LLM extraction response
    class MockLLMResponse:
        success = True
        error = ""
        json_text = json.dumps({
            "document_id": "doc_aadhaar_002",
            "filled": [
                { "slot": "doc_aadhaar_name", "value": "JOHN DOE", "confidence": 0.95, "evidence": { "page": "front", "span": "JOHN DOE" } },
                { "slot": "doc_aadhaar_dob", "value": "1990-12-12", "confidence": 0.95, "evidence": { "page": "front", "span": "1990-12-12" } },
                { "slot": "doc_aadhaar_gender", "value": "MALE", "confidence": 0.95, "evidence": { "page": "front", "span": "MALE" } },
                { "slot": "doc_aadhaar_last4", "value": "999912341234", "confidence": 0.95, "evidence": { "page": "front", "span": "999912341234" } },
                { "slot": "doc_aadhaar_address", "value": {
                    "care_of": "S/O SOMEONE", "street": "STREET", "city_village": "CITY", "district": "DIST", "state": "STATE", "pincode": "110001"
                }, "confidence": 0.95, "evidence": { "page": "back", "span": "Address" } }
            ],
            "unmatched": [],
            "notes": ""
        })
        
    servicer.llm_stub.Extract.return_value = MockLLMResponse()
    
    # 3. Create request
    request = pb2.ProcessDocRequest(
        session_id=session_id,
        document_id="doc_aadhaar_002",
        page_id="pdf",
        image_data=b"%PDF-1.4 dummy pdf bytes",
        content_type="application/pdf",
        filename="aadhaar.pdf"
    )
    
    response = await servicer.ProcessDocument(request, MockContext())
    
    assert response.success is True
    assert response.document_complete is True
    assert response.part_id == "pdf"
    
    # Verify that the extracted fields are present
    fields = json.loads(response.extracted_fields_json)
    assert fields["doc_aadhaar_name"]["value"] == "JOHN DOE"
    assert fields["doc_aadhaar_last4"]["value"] == "1234" # Verhoeff validated and masked to last 4 digits

@pytest.mark.asyncio
async def test_process_document_pdf_incomplete_failure():
    # 1. Create a dummy session
    session_id = "test-session-pdf-456"
    config_loader.load_registry()
    
    session = session_manager.create_session(session_id, "scheme_micro_business_001", "en")
    assert session is not None
    
    # Clear any previous coverage map
    session.coverage_map[session.get_current_document_id()].clear()
    
    # 2. Mock stubs on servicer
    servicer = DocumentCaptureServicer()
    servicer.ocr_stub = AsyncMock()
    
    # Mock OCR response missing the back anchors (only front anchors present)
    class MockOCRResponse:
        success = True
        error = ""
        raw_text = "Government of India DOB"
        confidence = 0.95
        blocks = []
    
    servicer.ocr_stub.ExtractText.return_value = MockOCRResponse()
    
    # 3. Create request
    request = pb2.ProcessDocRequest(
        session_id=session_id,
        document_id="doc_aadhaar_002",
        page_id="pdf",
        image_data=b"%PDF-1.4 dummy pdf bytes",
        content_type="application/pdf",
        filename="aadhaar.pdf"
    )
    
    response = await servicer.ProcessDocument(request, MockContext())
    
    # Should fail due to incomplete parts in the PDF
    assert response.success is False
    assert response.validation_error_key == "error_wrong_page"
    assert "Incomplete PDF pages" in response.validation_error_text
