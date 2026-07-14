import pytest
import json
from unittest.mock import AsyncMock, MagicMock
from server import DocumentCaptureServicer
from generated import doc_capture_pb2 as pb2
from session_manager import session_manager, parse_page_id
from config_loader import config_loader

class MockContext:
    def invocation_metadata(self):
        return []

@pytest.mark.asyncio
async def test_nested_array_and_multiple_pages():
    # 1. Setup and configs
    session_id = "test-session-nested-123"
    config_loader.load_registry()
    
    # Verify configs load doc_bank_statement_001
    manifest = config_loader.get_manifest("doc_bank_statement_001")
    assert manifest is not None
    
    session = session_manager.create_session(session_id, "scheme_micro_business_001", "en")
    assert session is not None
    
    # Overwrite current document in session to doc_bank_statement_001
    session.required_documents = ["doc_bank_statement_001"]
    session.current_document_index = 0
    assert session._load_current_document() is True
    
    # 2. Test initial page info routing (First page is page_count: 1, so it shouldn't have index suffix)
    page = session.get_current_page()
    assert page is not None
    assert page["page_id"] == "account_details"
    assert page["allow_multiple"] is False
    
    # 3. Simulate uploading the first page
    servicer = DocumentCaptureServicer()
    servicer.ocr_stub = AsyncMock()
    servicer.llm_stub = AsyncMock()
    servicer.orch_stub = AsyncMock()
    
    # Quality gate response for first page (account details)
    class MockQualityResponse:
        passed = True
        part_id = "account_details"
        ocr_text = "Statement of Account Account Details John Doe"
        ocr_confidence = 0.95
        failure_reason = ""
        anchor_hits = 3
        
    servicer.ocr_stub.ExtractText.return_value = AsyncMock()  # Stub out quality gate internal OCR
    
    # We will mock run_quality_gate directly inside the test by patch, or just bypass standard OCR in servicer
    # To keep it simple, we construct a fake request matching page info
    request1 = pb2.ProcessDocRequest(
        session_id=session_id,
        document_id="doc_bank_statement_001",
        page_id="account_details",
        image_data=b"dummy account image",
        content_type="image/jpeg",
        filename="first_page.jpg"
    )
    
    # We stub quality gate check results
    servicer.ocr_stub = AsyncMock()
    mock_ocr = MagicMock()
    mock_ocr.success = True
    mock_ocr.raw_text = "Statement of Account Account Details John Doe"
    mock_ocr.confidence = 0.95
    mock_ocr.blocks = []
    servicer.ocr_stub.ExtractText.return_value = mock_ocr
    
    res1 = await servicer.ProcessDocument(request1, MockContext())
    assert res1.success is True
    assert res1.page_complete is True
    assert res1.document_complete is False
    assert res1.next_page_id == "cheques_1"  # Next is first page of cheques
    
    # Check that session recorded the first page details correctly
    assert session.is_part_covered("account_details") is True
    assert session.part_ocr_texts["doc_bank_statement_001"]["account_details"][1] == mock_ocr.raw_text
    
    # 4. Upload Cheque Page 1 (cheques_1)
    request2 = pb2.ProcessDocRequest(
        session_id=session_id,
        document_id="doc_bank_statement_001",
        page_id="cheques_1",
        image_data=b"dummy cheques 1",
        content_type="image/jpeg",
        filename="cheque1.jpg"
    )
    mock_ocr2 = MagicMock()
    mock_ocr2.success = True
    mock_ocr2.raw_text = "Instrument Number Cheque CHQ 111222 amount 5000"
    mock_ocr2.confidence = 0.95
    mock_ocr2.blocks = []
    servicer.ocr_stub.ExtractText.return_value = mock_ocr2
    
    res2 = await servicer.ProcessDocument(request2, MockContext())
    assert res2.success is True
    assert res2.page_complete is True
    assert res2.next_page_id == "cheques_2"  # Since page_count is 0 (variable), it prompts cheques_2
    
    # Upload Cheque Page 2 (cheques_2)
    request3 = pb2.ProcessDocRequest(
        session_id=session_id,
        document_id="doc_bank_statement_001",
        page_id="cheques_2",
        image_data=b"dummy cheques 2",
        content_type="image/jpeg",
        filename="cheque2.jpg"
    )
    mock_ocr3 = MagicMock()
    mock_ocr3.success = True
    mock_ocr3.raw_text = "Instrument Number CHQ 333444 amount 10000 beneficiary ACME CORP"
    mock_ocr3.confidence = 0.95
    mock_ocr3.blocks = []
    servicer.ocr_stub.ExtractText.return_value = mock_ocr3
    
    res3 = await servicer.ProcessDocument(request3, MockContext())
    assert res3.success is True
    assert res3.next_page_id == "cheques_3"
    
    # 5. Signal variable part complete (cheques) via session.variable_parts_completed
    session.variable_parts_completed["doc_bank_statement_001"].add("cheques")
    assert session.is_coverage_complete() is True
    
    # 6. Test nested validations with low confidence targeting page indices
    # We will trigger extraction on cheques.
    # Page 1 (cheques_1) has low confidence cheque_number.
    # Page 2 (cheques_2) has low confidence beneficiary.
    # Both should fail and be queued in pending_retakes, but de-duplicated per page.
    class MockLLMResponse:
        success = True
        error = ""
        json_text = json.dumps({
            "document_id": "doc_bank_statement_001",
            "filled": [
                { "slot": "full_name", "value": "JOHN DOE", "confidence": 0.95, "evidence": { "page": "account_details", "span": "John Doe" } },
                {
                    "slot": "cheques",
                    "value": [
                        {
                            "cheque_number": { "value": "111222", "confidence": 0.50, "evidence": { "page": "cheques_1", "span": "111222" } },
                            "cheque_date": { "value": "2026-05-10", "confidence": 0.95, "evidence": { "page": "cheques_1", "span": "2026-05-10" } },
                            "amount": { "value": 5000, "confidence": 0.96, "evidence": { "page": "cheques_1", "span": "5000" } },
                            "beneficiary": { "value": "SELF", "confidence": 0.95, "evidence": { "page": "cheques_1", "span": "SELF" } }
                        },
                        {
                            "cheque_number": { "value": "333444", "confidence": 0.97, "evidence": { "page": "cheques_2", "span": "333444" } },
                            "cheque_date": { "value": "2026-05-11", "confidence": 0.95, "evidence": { "page": "cheques_2", "span": "2026-05-11" } },
                            "amount": { "value": 10000, "confidence": 0.96, "evidence": { "page": "cheques_2", "span": "10000" } },
                            "beneficiary": { "value": "ACME CORP", "confidence": 0.40, "evidence": { "page": "cheques_2", "span": "ACME CORP" } }
                        }
                    ],
                    "confidence": 0.95,
                    "evidence": { "page": "cheques_1", "span": "Cheque" }
                }
            ],
            "unmatched": [],
            "notes": ""
        })
        
    servicer.llm_stub.Extract.return_value = MockLLMResponse()
    
    # Run ProcessDocument on the final variable part complete upload trigger
    # In normal flow, ProcessDocument is run on the last upload, but here coverage is complete,
    # so we trigger ProcessDocument on cheques_2 again to simulate completion processing.
    res4 = await servicer.ProcessDocument(request3, MockContext())
    assert res4.success is False
    assert res4.validation_error_key == "error_low_confidence"
    
    # Check that both cheques_1 (index 1) and cheques_2 (index 2) are queued in pending_retakes!
    retakes = session.pending_retakes["doc_bank_statement_001"]["cheques"]
    assert 1 in retakes
    assert 2 in retakes
    
    # Check that failure reasons are tracked correctly
    reasons = session.failed_reasons["doc_bank_statement_001"]["cheques"]
    assert "Cheque Number" in reasons[1]
    assert "Beneficiary" in reasons[2]
    
    # 7. Check page routing requests retakes dynamically in sequence
    next_page_retake = session.get_current_page()
    assert next_page_retake["page_id"] == "cheques_1"  # Retake first faulty page (index 1)
    prompt_data = json.loads(next_page_retake["intro_prompt_json"])
    assert "Verification failed on page 1" in prompt_data["en"]
    assert prompt_data["previous_image_url"] == "test-session-nested-123_doc_bank_statement_001_cheques_1.jpg"
    assert prompt_data["failed_reasons"] == ["Cheque Number"]
    
    # 8. Re-upload page 1 successfully and check replacement of OCR texts
    request_re_upload = pb2.ProcessDocRequest(
        session_id=session_id,
        document_id="doc_bank_statement_001",
        page_id="cheques_1",
        image_data=b"dummy cheques 1 re-uploaded",
        content_type="image/jpeg",
        filename="cheque1_fixed.jpg"
    )
    mock_ocr_fixed = MagicMock()
    mock_ocr_fixed.success = True
    mock_ocr_fixed.raw_text = "Instrument Number Cheque CHQ 111222 amount 5000 beneficiary SELF"
    mock_ocr_fixed.confidence = 0.97
    mock_ocr_fixed.blocks = []
    servicer.ocr_stub.ExtractText.return_value = mock_ocr_fixed
    
    res_re = await servicer.ProcessDocument(request_re_upload, MockContext())
    assert res_re.success is True
    # Coverage is still incomplete because cheques_2 (index 2) is still pending retake
    assert res_re.document_complete is False
    assert res_re.next_page_id == "cheques_2"  # Prompts cheques_2 next
    
    # Verify that cheques_1 is cleared from pending retakes
    assert 1 not in session.pending_retakes["doc_bank_statement_001"]["cheques"]
    assert 2 in session.pending_retakes["doc_bank_statement_001"]["cheques"]
    
    # Verify that the ocr text was successfully replaced
    assert session.part_ocr_texts["doc_bank_statement_001"]["cheques"][1] == mock_ocr_fixed.raw_text

def test_passport_manifest_loading():
    config_loader.load_registry()
    manifest = config_loader.get_manifest("doc_passport_001")
    assert manifest is not None
    assert "doc_passport_number" in manifest["expects"]
    assert "doc_passport_visas" in manifest["expects"]
    assert len(manifest["parts"]) == 3
    assert manifest["parts"][2]["page_count"] == 0

@pytest.mark.asyncio
async def test_table_recognition_hint():
    from quality_gate import run_quality_gate
    
    # Create a mock manifest with a part having table=True
    mock_manifest = {
        "document_id": "doc_test_table",
        "quality": {
            "blur_var_min": 0,
            "min_anchor_hits": 1
        },
        "parts": [
            {
                "id": "table_part",
                "table": True,
                "anchors": ["Table"]
            }
        ]
    }
    
    # Mock OCR stub to verify the hint parameter passed
    ocr_stub = AsyncMock()
    mock_ocr = MagicMock()
    mock_ocr.success = True
    mock_ocr.raw_text = "Table Row 1 Cell 2"
    mock_ocr.confidence = 0.99
    mock_ocr.blocks = []
    ocr_stub.ExtractText.return_value = mock_ocr
    
    from PIL import Image
    import io
    img = Image.new('RGB', (100, 100), color='red')
    img_bytes = io.BytesIO()
    img.save(img_bytes, format='JPEG')
    dummy_jpeg = img_bytes.getvalue()
    
    res = await run_quality_gate(
        image_bytes=dummy_jpeg,
        manifest=mock_manifest,
        ocr_stub=ocr_stub,
        language="en",
        document_id="doc_test_table",
        part_id="table_part"
    )
    
    # Assert that ExtractText was called with hint="Table Recognition:"!
    call_args = ocr_stub.ExtractText.call_args[0][0]
    assert call_args.hint == "Table Recognition:"
    assert res.passed is True

def test_passport_fields_validation():
    config_loader.load_registry()
    from extraction import validate_and_coerce
    from confidence_router import route_slot, SlotResult
    
    passport_num_def = config_loader.get_slot_def("doc_passport_number")
    spouse_name_def = config_loader.get_slot_def("doc_passport_spouse_name")
    
    # 1. Test 1-letter passport number
    val, conf = validate_and_coerce("doc_passport_number", passport_num_def, "A1234567", 0.95)
    assert val == "A1234567"
    assert conf == 0.95
    
    # 2. Test 2-letter passport number
    val, conf = validate_and_coerce("doc_passport_number", passport_num_def, "TI7332300", 0.95)
    assert val == "TI7332300"
    assert conf == 0.95
    
    # 3. Test invalid passport formats
    val, conf = validate_and_coerce("doc_passport_number", passport_num_def, "12345678", 0.95)
    assert val is None
    assert conf == 0.0
    
    val, conf = validate_and_coerce("doc_passport_number", passport_num_def, "T123", 0.95)
    assert val is None
    assert conf == 0.0

    # 4. Test optional spouse name routing when None/empty
    dummy_spouse_slot = SlotResult(slot="doc_passport_spouse_name", value=None, confidence=0.0, evidence={})
    action = route_slot(dummy_spouse_slot, spouse_name_def, config_loader.get_confidence_bands())
    assert action == "accept"
    
    # Test non-optional field routing fails on None/empty
    dummy_given_name_slot = SlotResult(slot="doc_passport_given_name", value=None, confidence=0.0, evidence={})
    given_name_def = config_loader.get_slot_def("doc_passport_given_name")
    action_req = route_slot(dummy_given_name_slot, given_name_def, config_loader.get_confidence_bands())
    assert action_req == "retake"
