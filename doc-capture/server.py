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
from session_manager import session_manager
from prompt_builder import build_faq_system_prompt, build_extraction_prompt
from validation_engine import validation_engine
from preprocessing import preprocess_image

logger = get_logger("doc-capture")


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
        
        # Load from document config
        doc = session.current_document_config
        if doc:
            pi.acceptable_formats.extend(doc.get("acceptable_formats", []))
            pi.max_file_size_mb = doc.get("max_file_size_mb", 5)
            
        prompts = page_config.get("prompts", {})
        pi.intro_prompt_json = json.dumps(prompts.get("intro", {}))
        pi.success_prompt_json = json.dumps(prompts.get("success", {}))
        pi.error_blur_prompt_json = json.dumps(prompts.get("error_blur", {}))
        pi.error_invalid_doc_prompt_json = json.dumps(prompts.get("error_invalid_document", {}))
        
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
                total_pages=len(session.current_document_config.get("pages", [])),
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
            document_name=session.current_document_config.get("document_name", ""),
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
            total_pages=len(session.current_document_config.get("pages", [])),
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
            
        page = session.get_current_page()
        if not page or page.get("page_id") != request.page_id:
            return pb2.ProcessDocResponse(success=False, error="Page ID mismatch")
            
        doc_config = session.current_document_config
        
        # 1.5 Validate file size and format
        max_size_mb = doc_config.get("max_file_size_mb", 5)
        if len(request.image_data) > max_size_mb * 1024 * 1024:
            return pb2.ProcessDocResponse(success=False, error=f"File exceeds maximum allowed size of {max_size_mb}MB")
            
        acceptable_formats = doc_config.get("acceptable_formats", [])
        if acceptable_formats:
            # Check file extension
            ext = request.filename.split('.')[-1].lower() if '.' in request.filename else ''
            
            allowed_exts = []
            for f in acceptable_formats:
                f = f.lower()
                if '/' in f:
                    # It's a mime type
                    subtype = f.split('/')[-1]
                    if subtype == 'jpeg':
                        allowed_exts.extend(['jpg', 'jpeg'])
                    else:
                        allowed_exts.append(subtype)
                else:
                    allowed_exts.append(f.replace('.', ''))
            
            if ext not in allowed_exts:
                return pb2.ProcessDocResponse(success=False, error=f"Invalid file format. Allowed formats: {', '.join(acceptable_formats)}")
        
        # 2. Preprocess
        processed_img = preprocess_image(request.image_data, page.get("preprocessing_flags", []))
        
        # 3. OCR via new OCR Service
        try:
            ocr_res = await self.ocr_stub.ExtractText(ocr_pb2.OCRRequest(
                image_data=processed_img,
                language=session.language,
                hint=request.document_id
            ), timeout=30.0)  # Generous timeout for batching queue and GPU warmup
            
            if not ocr_res.success:
                return pb2.ProcessDocResponse(success=False, error=f"OCR failed: {ocr_res.error}")
                
            # Reconstruct raw_text with inline confidence scores for the LLM
            formatted_text_blocks = []
            for block in ocr_res.blocks:
                formatted_text_blocks.append(f"[Conf: {block.confidence:.2f}] {block.text}")
                
            raw_text = "\n".join(formatted_text_blocks) if formatted_text_blocks else ocr_res.raw_text
            ocr_conf = ocr_res.confidence
        except grpc.RpcError as e:
            logger.error(f"OCR gRPC call failed: {e}")
            return pb2.ProcessDocResponse(success=False, error=f"OCR Service Unavailable: {e.details()}")
            
            
        # 4. Global doc confidence check
        doc_conf_thresh = doc_config.get("confidence_threshold", 0.0)
        if ocr_conf < doc_conf_thresh:
            return pb2.ProcessDocResponse(success=False, validation_error_key="error_blur")
            
        # 5. Signature text check
        sig = page.get("signature_text")
        if sig and sig.lower() not in raw_text.lower():
            return pb2.ProcessDocResponse(success=False, validation_error_key="error_invalid_document")
            
        # 6. Extraction via LLM
        prompt = build_extraction_prompt(page, raw_text)
        try:
            llm_res = await self.llm_stub.Extract(llm_pb2.ExtractRequest(
                prompt=prompt,
                model="gemini-2.5-flash",
                disable_thinking=True
            ), timeout=20.0)
            
            if not llm_res.success:
                return pb2.ProcessDocResponse(success=False, error=f"Extraction failed: {llm_res.error}")
                
            try:
                extracted = json.loads(llm_res.json_text)
            except Exception:
                extracted = {}
        except Exception as e:
            return pb2.ProcessDocResponse(success=False, error=f"LLM call failed: {e}")
            
        # 7. Validation
        val_res = validation_engine.validate_page(page.get("fields_to_extract", []), extracted)
        if not val_res.is_valid:
            return pb2.ProcessDocResponse(
                success=False,
                validation_error_key=val_res.error_key,
                validation_field_id=val_res.field_id
            )
            
        # 8. Success: Save state
        session.record_extraction(request.page_id, extracted)
        session.mark_page_complete(request.page_id)
        session.record_upload(request.page_id, request.filename)
        
        # Determine next steps
        page_advanced, doc_advanced = session.advance_page()
        next_page = session.get_current_page()
        
        return pb2.ProcessDocResponse(
            success=True,
            extracted_fields_json=json.dumps(extracted),
            page_complete=True,
            document_complete=doc_advanced,
            all_complete=session.is_all_complete(),
            next_page_id=next_page.get("page_id") if next_page else "",
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
        doc = config_loader.get_document(request.document_id)
        if not doc:
            return pb2.DocConfigResponse(success=False, error="Not found")
            
        pages_summary = []
        for p in doc.get("pages", []):
            pages_summary.append(pb2.PageSummary(
                page_id=p.get("page_id", ""),
                page_name=p.get("page_name", ""),
                allow_multiple=p.get("allow_multiple", False),
                ui_camera_overlay=p.get("ui_camera_overlay", ""),
                prompts_json=json.dumps(p.get("prompts", {}))
            ))
            
        return pb2.DocConfigResponse(
            success=True,
            document_id=request.document_id,
            document_name=doc.get("document_name", ""),
            description=doc.get("description", ""),
            allowed_languages=doc.get("allowed_languages", []),
            acceptable_formats=doc.get("acceptable_formats", []),
            max_file_size_mb=doc.get("max_file_size_mb", 5),
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
