# Force IPv4 resolution to bypass macOS IPv6 network blackhole for external APIs
import socket
_original_getaddrinfo = socket.getaddrinfo
def _ipv4_only_getaddrinfo(*args, **kwargs):
    try:
        res = _original_getaddrinfo(*args, **kwargs)
        filtered = [r for r in res if r[0] == socket.AF_INET]
        return filtered if filtered else res
    except Exception:
        return _original_getaddrinfo(*args, **kwargs)
socket.getaddrinfo = _ipv4_only_getaddrinfo

import sys
import os
import json
import asyncio
import traceback
from typing import Tuple
import grpc
from grpc import aio as grpc_aio

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'shared'))
from log_utils.logger import get_logger, extract_req_id

from generated import doc_capture_pb2 as pb2
from generated import doc_capture_pb2_grpc as pb2_grpc
from generated import llm_pb2, llm_pb2_grpc
from generated import ocr_pb2, ocr_pb2_grpc
from generated import app_orchestrator_pb2, app_orchestrator_pb2_grpc

from config import DOC_CAPTURE_PORT, LLM_SERVICE_ADDR, OCR_SERVICE_ADDR, APP_ORCHESTRATOR_ADDR
from config_loader import config_loader
from session_manager import session_manager, CaptureSession
from preprocessing import preprocess_image

logger = get_logger("doc-capture")


def build_faq_system_prompt(session: CaptureSession) -> Tuple[str, str]:
    """
    Builds the system and context prompts for the voice engine.
    """
    system_parts = []
    context_parts = []
    
    # 1. Scheme FAQ context
    scheme_faq = session.scheme_config.get("faq_context", {})
    if scheme_faq.get("system_prompt"):
        system_parts.append(scheme_faq["system_prompt"])
        
    # 2. Document FAQ context from Manifest
    manifest = session.current_document_config
    if manifest:
        doc_faq = manifest.get("llm_faq_context", {})
        if doc_faq.get("system_prompt"):
            system_parts.append(doc_faq["system_prompt"])
            
        if doc_faq.get("policies"):
            context_parts.append("Document Policies:")
            for policy in doc_faq["policies"]:
                context_parts.append(f"- {policy}")
                
        # 3. Current part context (letting LLM know which part is being captured now)
        next_part = session.get_next_uncovered_part()
        if next_part:
            doc_title = manifest.get("title", {}).get("English", "Document")
            part_id = next_part.get("id", "Page")
            part_title = "front side" if part_id == "front" else ("back side" if part_id == "back" else part_id)
            page_ctx = (
                f"The user is currently going to upload/capture the '{part_title}' of their '{doc_title}'. "
                f"Try to keep the response limited to that part, but if user insists, then explain "
                f"the details of other parts also, but only if user insists."
            )
            context_parts.append(page_ctx)
            
    # 4. History
    history = session.get_faq_history()
    if history:
        context_parts.append("\nPrevious Conversation Context for this Document:")
        for msg in history:
            role = msg.get("role", "unknown").upper()
            content = msg.get("content", "")
            context_parts.append(f"{role}: {content}")
            
    system_prompt = "\n\n".join(system_parts)
    context_prompt = "\n\n".join(context_parts)
    
    return system_prompt, context_prompt


def get_localized_prompt(manifest: dict, key: str, language: str) -> str:
    prompts = manifest.get("prompts", {})
    localized = prompts.get(key, {})
    return localized.get(language, localized.get("en", ""))


class DocumentCaptureServicer(pb2_grpc.DocumentCaptureServicer):
    
    def __init__(self):
        # Channels
        channel_options = [
            ("grpc.max_send_message_length", 100 * 1024 * 1024),
            ("grpc.max_receive_message_length", 100 * 1024 * 1024),
        ]
        self.llm_channel = grpc_aio.insecure_channel(LLM_SERVICE_ADDR)
        self.llm_stub = llm_pb2_grpc.LanguageModelStub(self.llm_channel)
        
        if "443" in OCR_SERVICE_ADDR:
            credentials = grpc.ssl_channel_credentials()
            self.ocr_channel = grpc_aio.secure_channel(OCR_SERVICE_ADDR, credentials, options=channel_options)
        else:
            self.ocr_channel = grpc_aio.insecure_channel(OCR_SERVICE_ADDR, options=channel_options)
        
        self.ocr_stub = ocr_pb2_grpc.OCRServiceStub(self.ocr_channel)
        
        self.orch_channel = grpc_aio.insecure_channel(APP_ORCHESTRATOR_ADDR, options=channel_options)
        self.orch_stub = app_orchestrator_pb2_grpc.ApplicationOrchestratorStub(self.orch_channel)

    def _build_page_info(self, page_config: dict, session) -> pb2.PageInfo:
        pi = pb2.PageInfo(
            page_id=page_config.get("page_id", ""),
            page_name=page_config.get("page_name", ""),
            allow_multiple=page_config.get("allow_multiple", False),
            ui_camera_overlay=page_config.get("ui_camera_overlay", ""),
        )
        
        pi.acceptable_formats.extend(page_config.get("acceptable_formats", []))
        pi.max_file_size_mb = page_config.get("max_file_size_mb", 10)
        
        pi.intro_prompt_json = page_config.get("intro_prompt_json", "{}")
        pi.success_prompt_json = page_config.get("success_prompt_json", "{}")
        pi.error_blur_prompt_json = page_config.get("error_blur_prompt_json", "{}")
        pi.error_invalid_doc_prompt_json = page_config.get("error_invalid_doc_prompt_json", "{}")
        
        pi.uploads_count = session.get_upload_count(page_config.get("page_id", ""))
        
        return pi

    async def StartSession(self, request, context):
        req_id = extract_req_id(context)
        logger.info(f"StartSession: scheme={request.scheme_id} lang={request.language}", req_id=req_id)
        
        try:
            session = session_manager.create_session(request.session_id, request.scheme_id, request.language)
            if not session:
                return pb2.CaptureSessionResponse(success=False, error="Failed to initialize session")
                
            page = session.get_current_page()
            page_info = self._build_page_info(page, session) if page else None
            
            return pb2.CaptureSessionResponse(
                success=True,
                session_id=request.session_id,
                current_document_id=session.get_current_document_id(),
                current_page_id=page.get("page_id") if page else "",
                current_document_index=session.current_document_index,
                total_documents=len(session.required_documents),
                current_page_index=session.current_page_index,
                total_pages=len(session.current_document_config.get("parts", [])) if session.current_document_config else 0,
                current_page_info=page_info,
                all_complete=session.is_all_complete()
            )
        except Exception as e:
            logger.error(f"StartSession error: {e}", req_id=req_id, error=traceback.format_exc())
            return pb2.CaptureSessionResponse(success=False, error=str(e))

    async def GetPageInfo(self, request, context):
        session = session_manager.get_session(request.session_id)
        if not session:
            return pb2.PageInfoResponse(success=False, error="Session not found")
            
        page = session.get_current_page()
        if not page:
            return pb2.PageInfoResponse(success=False, error="No current page")
            
        page_info = self._build_page_info(page, session)
        return pb2.PageInfoResponse(
            success=True,
            page_info=page_info,
            document_id=session.get_current_document_id(),
            document_name=session.current_document_config.get("title", {}).get("English", ""),
            document_index=session.current_document_index,
            total_documents=len(session.required_documents)
        )

    async def AdvancePage(self, request, context):
        req_id = extract_req_id(context)
        session = session_manager.get_session(request.session_id)
        if not session:
            return pb2.CaptureSessionResponse(success=False, error="Session not found")
            
        session.advance_page()
        
        page = session.get_current_page()
        page_info = self._build_page_info(page, session) if page else None
        
        return pb2.CaptureSessionResponse(
            success=True,
            session_id=request.session_id,
            current_document_id=session.get_current_document_id(),
            current_page_id=page.get("page_id") if page else "",
            current_document_index=session.current_document_index,
            total_documents=len(session.required_documents),
            current_page_index=session.current_page_index,
            total_pages=len(session.current_document_config.get("parts", [])) if session.current_document_config else 0,
            current_page_info=page_info,
            all_complete=session.is_all_complete()
        )

    async def ProcessDocument(self, request, context):
        req_id = extract_req_id(context)
        logger.info(f"ProcessDocument: doc={request.document_id} page={request.page_id}", req_id=req_id)
        
        session = session_manager.get_session(request.session_id)
        if not session:
            return pb2.ProcessDocResponse(success=False, error="Session not found")
            
        # 1. Verification of document/page ids matches session
        if request.document_id != session.get_current_document_id():
            return pb2.ProcessDocResponse(success=False, error="Document ID mismatch")
            
        doc_config = session.current_document_config
        doc_id = session.get_current_document_id()
        
        # 2. Validate file size and formats based on source configuration in manifest
        sources = doc_config.get("sources", [{}])
        first_source = sources[0] if sources else {}
        max_size_mb = first_source.get("max_mb", 10)
        if len(request.image_data) > max_size_mb * 1024 * 1024:
            return pb2.ProcessDocResponse(success=False, error=f"File exceeds maximum allowed size of {max_size_mb}MB")
            
        acceptable_formats = first_source.get("formats", ["image/jpeg", "image/png"])
        if acceptable_formats:
            ext = request.filename.split('.')[-1].lower() if '.' in request.filename else ''
            allowed_exts = []
            for f in acceptable_formats:
                f = f.lower()
                if '/' in f:
                    subtype = f.split('/')[-1]
                    if subtype == 'jpeg':
                        allowed_exts.extend(['jpg', 'jpeg'])
                    else:
                        allowed_exts.append(subtype)
                else:
                    allowed_exts.append(f.replace('.', ''))
            
            if ext not in allowed_exts:
                return pb2.ProcessDocResponse(success=False, error=f"Invalid file format. Allowed formats: {', '.join(acceptable_formats)}")
        
        is_pdf = (request.content_type == "application/pdf") or request.filename.lower().endswith(".pdf")
        
        if is_pdf:
            # ─── PDF Flow: Skip blur check and preprocessing, call OCR directly ───
            from generated import ocr_pb2
            try:
                logger.info(f"ProcessDocument: PDF detected. Calling OCR service directly...")
                ocr_res = await self.ocr_stub.ExtractText(ocr_pb2.OCRRequest(
                    image_data=request.image_data,
                    language=session.language,
                    hint=request.document_id
                ), timeout=30.0)
                
                if not ocr_res.success:
                    logger.error(f"ProcessDocument: PDF OCR failed: {ocr_res.error}")
                    return pb2.ProcessDocResponse(success=False, error=f"OCR failed: {ocr_res.error}")
                
                raw_text = ocr_res.raw_text
                ocr_confidence = ocr_res.confidence
            except grpc.RpcError as e:
                logger.error(f"ProcessDocument: PDF OCR gRPC call failed: {e}")
                return pb2.ProcessDocResponse(success=False, error=f"OCR Service Unavailable: {e.details()}")
                
            # OCR confidence gate check
            quality_config = doc_config.get("quality", {})
            min_box_confidence = quality_config.get("min_box_confidence", 0.50)
            if ocr_confidence < min_box_confidence:
                logger.warning(f"ProcessDocument: PDF OCR confidence ({ocr_confidence:.2f}) below threshold ({min_box_confidence})")
                error_text = get_localized_prompt(doc_config, "error_low_confidence", session.language)
                return pb2.ProcessDocResponse(
                    success=False,
                    validation_error_key="error_low_confidence",
                    validation_error_text=error_text
                )
                
            # Transliterate Devanagari numerals
            translit_map = str.maketrans("०१२३४५६७८९", "0123456789")
            clean_raw_text = raw_text.translate(translit_map)
            clean_lower_text = clean_raw_text.lower()
            
            # Anchor matching for ALL parts
            min_anchor_hits = quality_config.get("min_anchor_hits", 2)
            parts = doc_config.get("parts", [])
            
            from quality_gate import QualityResult
            matched_any = False
            for part in parts:
                part_id = part.get("id", "")
                anchors = part.get("anchors", [])
                hits = sum(1 for anchor in anchors if anchor.lower() in clean_lower_text)
                logger.info(f"ProcessDocument (PDF): Part '{part_id}' matched {hits} anchors (min={min_anchor_hits})")
                if hits >= min_anchor_hits:
                    quality_res = QualityResult(
                        passed=True,
                        part_id=part_id,
                        ocr_text=clean_raw_text,
                        ocr_confidence=ocr_confidence,
                        failure_reason="",
                        anchor_hits=hits
                    )
                    session.record_part_result(part_id, quality_res)
                    session.record_upload(part_id, request.filename)
                    matched_any = True
            
            # Check if all required parts have been successfully matched within this PDF
            if not session.is_coverage_complete():
                logger.warning("ProcessDocument: PDF upload did not match all required parts of the manifest.")
                # Clear any partially marked parts to ensure session is clean
                if doc_id in session.coverage_map:
                    session.coverage_map[doc_id].clear()
                error_text = get_localized_prompt(doc_config, "error_wrong_page", session.language)
                return pb2.ProcessDocResponse(
                    success=False,
                    validation_error_key="error_wrong_page",
                    validation_error_text=error_text + " (Incomplete PDF pages)"
                )
            
            # PDF matched all parts, flow directly to extraction step.
            part_id = "pdf"
        
        else:
            # ─── Standard Image Flow: Preprocess and check Quality Gate ───
            # 3. Preprocess image
            preprocessing_flags = doc_config.get("preprocessing", [])
            processed_img = preprocess_image(request.image_data, preprocessing_flags)
            
            # 4. Quality Gate
            from quality_gate import run_quality_gate
            quality_res = await run_quality_gate(
                image_bytes=processed_img,
                manifest=doc_config,
                ocr_stub=self.ocr_stub,
                language=session.language,
                document_id=request.document_id
            )
            
            if not quality_res.passed:
                logger.warning(f"ProcessDocument: quality gate failed with reason '{quality_res.failure_reason}'")
                val_error_key = f"error_{quality_res.failure_reason}" if quality_res.failure_reason else "error_invalid_document"
                error_text = get_localized_prompt(doc_config, val_error_key, session.language)
                return pb2.ProcessDocResponse(
                    success=False,
                    validation_error_key=val_error_key,
                    validation_error_text=error_text
                )
                
            # 5. Save quality gate result in coverage map
            part_id = quality_res.part_id
            session.record_part_result(part_id, quality_res)
            session.record_upload(part_id, request.filename)
            
            # 6. Check if coverage complete
            if not session.is_coverage_complete():
                # Advance part capture (not fully complete yet)
                session.advance_page()
                next_part = session.get_next_uncovered_part()
                next_part_id = next_part.get("id", "") if next_part else ""
                
                return pb2.ProcessDocResponse(
                    success=True,
                    page_complete=True,
                    document_complete=False,
                    all_complete=False,
                    part_id=part_id,
                    next_page_id=next_part_id,
                    next_part_id=next_part_id,
                    next_document_id=request.document_id
                )
            
        # 7. Coverage complete -> run extraction
        from extraction import run_extraction
        logger.info(f"ProcessDocument: coverage complete. Running extraction...")
        extraction_res = await run_extraction(
            all_page_texts=session.part_ocr_texts[doc_id],
            manifest=doc_config,
            llm_stub=self.llm_stub
        )
        
        # 8. Route extracted fields through confidence router
        from confidence_router import route_slot
        bands = config_loader.get_confidence_bands()
        
        flat_extracted_dict = {}
        confirm_fields = []
        failed_slot_id = None
        failed_part_id = None
        
        for slot_res in extraction_res.filled:
            slot_def = config_loader.get_slot_def(slot_res.slot)
            if not slot_def:
                continue
                
            action = route_slot(slot_res, slot_def, bands)
            
            if action == "retake":
                logger.warning(f"ProcessDocument: slot '{slot_res.slot}' routed to retake.")
                failed_slot_id = slot_res.slot
                
                # Identify which part of the document this slot belongs to
                evidence_page = slot_res.evidence.get("page", "")
                if not evidence_page:
                    for part in doc_config.get("parts", []):
                        if slot_res.slot in part.get("provides", []):
                            evidence_page = part.get("id", "")
                            break
                failed_part_id = evidence_page if evidence_page else "front"
                break
            elif action == "confirm":
                confirm_fields.append(slot_res.slot)
                flat_extracted_dict[slot_res.slot] = {"value": slot_res.value, "confidence": slot_res.confidence}
            else:  # accept
                flat_extracted_dict[slot_res.slot] = {"value": slot_res.value, "confidence": slot_res.confidence}
                
        if failed_slot_id:
            # A slot needs retake. Remove the failed part from coverage map so it must be captured again
            logger.warning(f"ProcessDocument: prompting user to retake part '{failed_part_id}' due to failed validation on slot '{failed_slot_id}'")
            if failed_part_id in session.coverage_map[doc_id]:
                del session.coverage_map[doc_id][failed_part_id]
            if failed_part_id in session.part_ocr_texts[doc_id]:
                del session.part_ocr_texts[doc_id][failed_part_id]
                
            error_text = get_localized_prompt(doc_config, "error_low_confidence", session.language)
            return pb2.ProcessDocResponse(
                success=False,
                validation_error_key="error_low_confidence",
                validation_error_text=error_text,
                validation_field_id=failed_slot_id,
                next_page_id=failed_part_id,
                next_part_id=failed_part_id
            )
            
        # 9. Success: Save state
        session.record_extraction(part_id, flat_extracted_dict)
        
        # Save final progress
        page_advanced, doc_advanced = session.advance_page()
        next_page = session.get_current_page()
        
        # Write to application orchestrator if document is complete
        if doc_advanced:
            try:
                flat_data = session.get_all_extracted_data()
                logger.info(f"ProcessDocument: upserting extracted data to app orchestrator: {json.dumps(flat_data)}")
                await self.orch_stub.UpsertExtractedData(
                    app_orchestrator_pb2.UpsertDataRequest(
                        application_id=session.session_id,
                        source="doc-capture",
                        json_fields=json.dumps(flat_data, ensure_ascii=False)
                    ),
                    timeout=5.0
                )
            except Exception as db_err:
                logger.error(f"Failed to upsert extracted data to App Orchestrator: {db_err}")
                
        return pb2.ProcessDocResponse(
            success=True,
            extracted_fields_json=json.dumps(flat_extracted_dict),
            page_complete=True,
            document_complete=doc_advanced,
            all_complete=session.is_all_complete(),
            confirm_fields=confirm_fields,
            part_id=part_id,
            next_page_id=next_page.get("page_id") if next_page else "",
            next_part_id=next_page.get("page_id") if next_page else "",
            next_document_id=session.get_current_document_id()
        )

    async def GetFAQPrompt(self, request, context):
        session = session_manager.get_session(request.session_id)
        if not session:
            return pb2.FAQPromptResponse(success=False, error="Session not found")
            
        sys_prompt, ctx_prompt = build_faq_system_prompt(session)
        return pb2.FAQPromptResponse(success=True, system_prompt=sys_prompt, context_prompt=ctx_prompt)

    async def GetSchemeConfig(self, request, context):
        scheme = config_loader.get_scheme(request.scheme_id)
        if not scheme:
            return pb2.SchemeConfigResponse(success=False, error="Not found")
            
        return pb2.SchemeConfigResponse(
            success=True,
            scheme_id=request.scheme_id,
            scheme_name=scheme.get("scheme_name", ""),
            description=scheme.get("description", ""),
            required_documents=scheme.get("required_documents", [])
        )

    async def GetDocumentConfig(self, request, context):
        doc = config_loader.get_manifest(request.document_id)
        if not doc:
            return pb2.DocConfigResponse(success=False, error="Not found")
            
        pages_summary = []
        for part in doc.get("parts", []):
            part_id = part.get("id", "")
            part_title_en = "front side" if part_id == "front" else ("back side" if part_id == "back" else part_id)
            part_title_hi = "सामने का हिस्सा" if part_id == "front" else ("पीछे का हिस्सा" if part_id == "back" else part_id)
            
            document_title_en = doc.get("title", {}).get("English", "Document")
            document_title_hi = doc.get("title", {}).get("Hindi", document_title_en)
            ask_part_template = doc.get("prompts", {}).get("ask_part", {})
            
            intro_prompts = {
                "en": ask_part_template.get("en", "Please capture the {part_id} of your {document_title}.").format(
                    part_id=part_title_en, document_title=document_title_en
                ),
                "hi": ask_part_template.get("hi", "कृपया अपने {document_title} का {part_id} कैप्चर करें।").format(
                    part_id=part_title_hi, document_title=document_title_hi
                )
            }
            
            prompts_dict = {
                "intro": intro_prompts,
                "success": doc.get("prompts", {}).get("success", {}),
                "error_blur": doc.get("prompts", {}).get("error_blur", {}),
                "error_invalid_document": doc.get("prompts", {}).get("error_wrong_page", {})
            }
            
            pages_summary.append(pb2.PageSummary(
                page_id=part_id,
                page_name="Front Side" if part_id == "front" else "Back Side",
                allow_multiple=False,
                ui_camera_overlay="landscape_id",
                prompts_json=json.dumps(prompts_dict)
            ))
            
        first_source = doc.get("sources", [{}])[0] if doc.get("sources") else {}
        return pb2.DocConfigResponse(
            success=True,
            document_id=request.document_id,
            document_name=doc.get("title", {}).get("English", ""),
            description=doc.get("description", ""),
            allowed_languages=doc.get("ocr", {}).get("lang", ["en", "hi"]),
            acceptable_formats=first_source.get("formats", ["image/jpeg", "image/png"]),
            max_file_size_mb=first_source.get("max_mb", 10),
            pages=pages_summary
        )

async def serve():
    server = grpc_aio.server()
    pb2_grpc.add_DocumentCaptureServicer_to_server(DocumentCaptureServicer(), server)
    server.add_insecure_port(f'[::]:{DOC_CAPTURE_PORT}')
    logger.info(f"Doc-Capture service starting on port {DOC_CAPTURE_PORT}")
    await server.start()
    await server.wait_for_termination()

if __name__ == '__main__':
    asyncio.run(serve())
