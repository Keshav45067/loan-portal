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
from session_manager import parse_page_id

from generated import doc_capture_pb2 as pb2
from generated import doc_capture_pb2_grpc as pb2_grpc
from generated import llm_pb2, llm_pb2_grpc
from generated import ocr_pb2, ocr_pb2_grpc
from generated import app_orchestrator_pb2, app_orchestrator_pb2_grpc

from config import DOC_CAPTURE_PORT, LLM_SERVICE_ADDR, OCR_SERVICE_ADDR, APP_ORCHESTRATOR_ADDR
from config_loader import config_loader
from session_manager import session_manager, CaptureSession
from recovery_actions import preprocess_image
from quality_metrics import build_quality_report
from recovery_engine import decide_recovery, apply_recovery

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
            part_title = next_part.get("title", {}).get("English", part_id)
            
            # List other parts for negative constraints
            other_parts_list = []
            for p in manifest.get("parts", []):
                p_id = p.get("id", "")
                if p_id != part_id:
                    other_parts_list.append(p.get("title", {}).get("English", p_id))
            other_parts_str = ", ".join(other_parts_list)
            
            page_ctx = (
                f"The user is currently going to upload/capture the '{part_title}' of their '{doc_title}'.\n"
                f"CRITICAL: The active screen is for '{part_title}' only. Do NOT instruct the user to capture or upload "
                f"other parts (such as {other_parts_str}) unless they explicitly ask for help with them. "
                f"Focus your response and instructions entirely on the '{part_title}'."
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
        
        import json
        try:
            intro_data = json.loads(page_config.get("intro_prompt_json", "{}"))
        except Exception:
            intro_data = {}
        intro_data["orientation"] = page_config.get("orientation", "landscape")
        pi.intro_prompt_json = json.dumps(intro_data)
        
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
            
        # If the current next uncovered part is a variable page count part (page_count == 0),
        # mark it completed because the user explicitly requested to advance past it.
        current_part = session.get_next_uncovered_part()
        if current_part and current_part.get("page_count", 1) == 0:
            doc_id = session.get_current_document_id()
            part_id = current_part.get("id", "")
            if doc_id and part_id:
                if doc_id not in session.variable_parts_completed:
                    session.variable_parts_completed[doc_id] = set()
                session.variable_parts_completed[doc_id].add(part_id)
                logger.info(f"AdvancePage: Marking variable part '{part_id}' as completed for doc '{doc_id}'", req_id=req_id)
                
        # If coverage is complete, execute the extraction flow
        if session.is_coverage_complete():
            doc_config = session.current_document_config
            doc_id = session.get_current_document_id()
            part_id = current_part.get("id", "") if current_part else ""
            
            # This triggers LLM extraction, confidence routing, retake generation, and DB saving
            pipeline_res = await self._execute_extraction_flow(session, doc_config, doc_id, part_id, req_id)
            if not pipeline_res["success"]:
                page = session.get_current_page()
                page_info = self._build_page_info(page, session) if page else None
                return pb2.CaptureSessionResponse(
                    success=False,
                    error=pipeline_res["validation_error_text"],
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
        else:
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
        expected_part_id, page_index = parse_page_id(request.page_id)
        
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
                is_table = any(part.get("table") is True for part in doc_config.get("parts", []))
                ocr_hint = "Table Recognition:" if is_table else request.document_id
                ocr_res = await self.ocr_stub.ExtractText(ocr_pb2.OCRRequest(
                    image_data=request.image_data,
                    language=session.language,
                    hint=ocr_hint
                ), timeout=30.0)
                
                if not ocr_res.success:
                    logger.error(f"ProcessDocument: PDF OCR failed: {ocr_res.error}")
                    return pb2.ProcessDocResponse(success=False, error=f"OCR failed: {ocr_res.error}")
                
                xml_layout = getattr(ocr_res, "xml_layout", "")
                raw_text = xml_layout if xml_layout else ocr_res.raw_text
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
                    validation_error_text=error_text + " (Incomplete PDF pages)",
                    next_page_id=request.page_id,
                    next_document_id=request.document_id
                )
            
            # PDF matched all parts, flow directly to extraction step.
            part_id = "pdf"
        
        else:
            # ─── Standard Image Flow: Measure, Recover, and run Quality Gate ───
            quality_policy = doc_config.get("quality_policy", {
                "allow_deskew": True,
                "allow_glare_removal": True,
                "allow_contrast_enhancement": True,
                "allow_denoise": False,
                "allow_gamma": False,
                "allow_white_balance": False,
                "allow_sharpen": False
            })
            if "quality_policy" not in doc_config and "preprocessing" in doc_config:
                pre_flags = doc_config["preprocessing"]
                quality_policy = {
                    "allow_deskew": "auto_deskew" in pre_flags,
                    "allow_glare_removal": "remove_glare" in pre_flags,
                    "allow_contrast_enhancement": "enhance_contrast" in pre_flags,
                    "allow_denoise": "denoise" in pre_flags,
                    "allow_gamma": "gamma" in pre_flags,
                    "allow_white_balance": "white_balance" in pre_flags,
                    "allow_sharpen": "sharpen" in pre_flags
                }

            quality_config = doc_config.get("quality", {})
            report = build_quality_report(request.image_data)
            
            # Check if blur is below unrecoverable floor immediately
            blur_floor = quality_config.get("blur_unrecoverable_floor", 30.0)
            if report.blur < blur_floor:
                logger.warning(f"ProcessDocument: quality check failed: blur {report.blur:.2f} is below floor {blur_floor}")
                val_error_key = "error_blur"
                error_text = get_localized_prompt(doc_config, val_error_key, session.language)
                return pb2.ProcessDocResponse(
                    success=False,
                    validation_error_key=val_error_key,
                    validation_error_text=error_text,
                    next_page_id=request.page_id,
                    next_document_id=request.document_id
                )

            # Decide and apply recovery actions
            decisions = decide_recovery(report, quality_policy, quality_config)
            if decisions:
                logger.info(f"ProcessDocument: recovery decisions to apply: {[d.action for d in decisions]}")
                processed_img = apply_recovery(request.image_data, decisions)
            else:
                processed_img = request.image_data

            # 4. Quality Gate
            from quality_gate import run_quality_gate
            quality_res = await run_quality_gate(
                image_bytes=processed_img,
                manifest=doc_config,
                ocr_stub=self.ocr_stub,
                language=session.language,
                document_id=request.document_id,
                part_id=expected_part_id
            )
            
            if not quality_res.passed:
                logger.warning(f"ProcessDocument: quality gate failed with reason '{quality_res.failure_reason}'")
                val_error_key = f"error_{quality_res.failure_reason}" if quality_res.failure_reason else "error_invalid_document"
                error_text = get_localized_prompt(doc_config, val_error_key, session.language)
                return pb2.ProcessDocResponse(
                    success=False,
                    validation_error_key=val_error_key,
                    validation_error_text=error_text,
                    next_page_id=request.page_id,
                    next_document_id=request.document_id
                )
                
            part_id = quality_res.part_id
            # Enforce classified part matches expected part
            if part_id != expected_part_id:
                logger.warning(f"ProcessDocument: page classifier returned '{part_id}', but expected '{expected_part_id}'")
                error_text = get_localized_prompt(doc_config, "error_wrong_page", session.language)
                return pb2.ProcessDocResponse(
                    success=False,
                    validation_error_key="error_wrong_page",
                    validation_error_text=error_text,
                    next_page_id=request.page_id,
                    next_part_id=expected_part_id,
                    next_document_id=request.document_id
                )
                
            # 4. GCS upload via Orchestrator (done in background thread)
            ext = "jpg"
            if request.content_type == "application/pdf":
                ext = "pdf"
            elif request.content_type == "image/png":
                ext = "png"
                
            filename = f"{session.session_id}_{request.document_id}_{request.page_id}.{ext}"
            if request.filename:
                orig_ext = request.filename.split(".")[-1]
                if orig_ext:
                    filename = f"{session.session_id}_{request.document_id}_{request.page_id}.{orig_ext}"
                    
            session.record_upload(request.page_id, filename)
            
            # 5. Save quality gate result in coverage map
            session.record_part_result(request.page_id, quality_res)
            
            # Clear this page from pending retakes if it was a retake
            if part_id in session.pending_retakes.get(request.document_id, {}):
                session.pending_retakes[request.document_id][part_id].discard(page_index)
                if page_index in session.failed_reasons.get(request.document_id, {}).get(part_id, {}):
                    del session.failed_reasons[request.document_id][part_id][page_index]
            
            # 6. Check if coverage complete
            if not session.is_coverage_complete():
                # Advance part capture (not fully complete yet)
                session.advance_page()
                next_page = session.get_current_page()
                next_page_id = next_page.get("page_id") if next_page else ""
                
                return pb2.ProcessDocResponse(
                    success=True,
                    page_complete=True,
                    document_complete=False,
                    all_complete=False,
                    part_id=part_id,
                    next_page_id=next_page_id,
                    next_part_id=next_page_id,
                    next_document_id=request.document_id
                )
            
        # 7. Coverage complete -> run extraction
        pipeline_res = await self._execute_extraction_flow(session, doc_config, doc_id, part_id, req_id)
        if not pipeline_res["success"]:
            return pb2.ProcessDocResponse(
                success=False,
                validation_error_key=pipeline_res["validation_error_key"],
                validation_error_text=pipeline_res["validation_error_text"],
                next_page_id=pipeline_res["next_page_id"],
                next_part_id=pipeline_res["next_part_id"],
                confirm_fields=pipeline_res["confirm_fields"],
                extracted_fields_json=pipeline_res["extracted_fields_json"],
                next_document_id=request.document_id
            )
        else:
            return pb2.ProcessDocResponse(
                success=True,
                extracted_fields_json=pipeline_res["extracted_fields_json"],
                page_complete=True,
                document_complete=pipeline_res["document_complete"],
                all_complete=pipeline_res["all_complete"],
                confirm_fields=pipeline_res["confirm_fields"],
                part_id=pipeline_res["part_id"],
                next_page_id=pipeline_res["next_page_id"],
                next_part_id=pipeline_res["next_part_id"],
                next_document_id=pipeline_res["next_document_id"]
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
            part_title_en = part.get("title", {}).get("English", part_id)
            part_title_hi = part.get("title", {}).get("Hindi", part_title_en)
            
            document_title_en = doc.get("title", {}).get("English", "Document")
            document_title_hi = doc.get("title", {}).get("Hindi", document_title_en)
            ask_part_template = doc.get("prompts", {}).get("ask_part", {})
            
            intro_prompts = {
                "en": ask_part_template.get("en", "Please capture the {part_id} of your {document_title}.").format(
                    part_id=part_title_en, part_title=part_title_en, document_title=document_title_en
                ),
                "hi": ask_part_template.get("hi", "कृपया अपने {document_title} का {part_id} कैप्चर करें।").format(
                    part_id=part_title_hi, part_title=part_title_hi, document_title=document_title_hi
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
                page_name=part.get("name", {}).get("English", part_id),
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

    async def _execute_extraction_flow(self, session, doc_config, doc_id, part_id, req_id):
        # 7. Coverage complete -> run extraction
        from extraction import run_extraction
        logger.info(f"_execute_extraction_flow: Running extraction for doc {doc_id} in session {session.session_id}...")
        
        # Flatten OCR texts dictionary by page indices to pass to LLM
        flat_page_texts = {}
        for p in doc_config.get("parts", []):
            p_id = p.get("id")
            p_count = p.get("page_count", 1)
            uploaded = session.part_ocr_texts.get(doc_id, {}).get(p_id, {})
            if p_count == 1:
                flat_page_texts[p_id] = uploaded.get(1, "")
            else:
                for idx in sorted(list(uploaded.keys())):
                    flat_page_texts[f"{p_id}_{idx}"] = uploaded[idx]
                    
        extraction_res = await run_extraction(
            all_page_texts=flat_page_texts,
            manifest=doc_config,
            llm_stub=self.llm_stub
        )
        
        # 8. Route extracted fields through confidence router
        from confidence_router import route_slot
        bands = config_loader.get_confidence_bands()
        
        flat_extracted_dict = {}
        confirm_fields = []
        
        failed_pages_to_retake = {}
        
        def add_failure(slot_id, evidence_p):
            p_id, p_idx = parse_page_id(evidence_p)
            if not p_id or p_id not in [part.get("id") for part in doc_config.get("parts", [])]:
                p_id = None
                for part in doc_config.get("parts", []):
                    if slot_id in part.get("provides", []):
                        p_id = part.get("id")
                        break
                if not p_id:
                    p_id = doc_config.get("parts", [{}])[0].get("id", "Page")
                p_idx = 1
                
            slot_def = config_loader.get_slot_def(slot_id)
            label = slot_def.get("label", {}).get("English", slot_id) if slot_def else slot_id
            
            if (p_id, p_idx) not in failed_pages_to_retake:
                failed_pages_to_retake[(p_id, p_idx)] = set()
            failed_pages_to_retake[(p_id, p_idx)].add(label)
            
        for slot_res in extraction_res.filled:
            slot_def = config_loader.get_slot_def(slot_res.slot)
            if not slot_def:
                continue
                
            if slot_def.get("type") == "array":
                items_list = slot_res.value
                if isinstance(items_list, list):
                    items_def = slot_def.get("items", {})
                    for item in items_list:
                        if not isinstance(item, dict):
                            continue
                        for sub_field in items_def.get("fields", []):
                            sub_data = item.get(sub_field)
                            if isinstance(sub_data, dict):
                                sub_val = sub_data.get("value")
                                sub_conf = sub_data.get("confidence", slot_res.confidence)
                                sub_ev = sub_data.get("evidence", slot_res.evidence)
                            else:
                                sub_val = sub_data
                                sub_conf = slot_res.confidence
                                sub_ev = slot_res.evidence
                                
                            sub_def = config_loader.get_slot_def(sub_field)
                            if sub_def:
                                dummy_res = slot_res.__class__(
                                    slot=sub_field,
                                    value=sub_val,
                                    confidence=sub_conf,
                                    evidence=sub_ev
                                )
                                action = route_slot(dummy_res, sub_def, bands)
                                if action == "retake":
                                    evidence_page = sub_ev.get("page", "")
                                    add_failure(sub_field, evidence_page)
                                elif action == "confirm":
                                    confirm_fields.append(sub_field)
            else:
                action = route_slot(slot_res, slot_def, bands)
                if action == "retake":
                    evidence_page = slot_res.evidence.get("page", "")
                    add_failure(slot_res.slot, evidence_page)
                elif action == "confirm":
                    confirm_fields.append(slot_res.slot)
                    
            flat_extracted_dict[slot_res.slot] = {"value": slot_res.value, "confidence": slot_res.confidence}
            
        if failed_pages_to_retake:
            logger.warning(f"_execute_extraction_flow: slots failed validation. Queueing retakes.")
            for (p_id, p_idx), slot_labels in failed_pages_to_retake.items():
                if doc_id not in session.pending_retakes:
                    session.pending_retakes[doc_id] = {}
                if p_id not in session.pending_retakes[doc_id]:
                    session.pending_retakes[doc_id][p_id] = set()
                session.pending_retakes[doc_id][p_id].add(p_idx)
                
                if doc_id not in session.failed_reasons:
                    session.failed_reasons[doc_id] = {}
                if p_id not in session.failed_reasons[doc_id]:
                    session.failed_reasons[doc_id][p_id] = {}
                session.failed_reasons[doc_id][p_id][p_idx] = list(slot_labels)
                
                if p_id in session.part_ocr_texts.get(doc_id, {}):
                    if p_idx in session.part_ocr_texts[doc_id][p_id]:
                        del session.part_ocr_texts[doc_id][p_id][p_idx]
                        
            next_page = session.get_current_page()
            next_page_id = next_page.get("page_id") if next_page else ""
            
            failed_reasons_str = []
            for (p_id, p_idx), slot_labels in failed_pages_to_retake.items():
                reasons_joined = ", ".join(list(slot_labels))
                part_def = next((part for part in doc_config.get("parts", []) if part.get("id") == p_id), None)
                part_title = part_def.get("title", {}).get("English", p_id) if part_def else p_id
                failed_reasons_str.append(f"{part_title} page {p_idx} ({reasons_joined})")
                
            error_msg_en = "Some details could not be read clearly: " + "; ".join(failed_reasons_str) + ". Please re-capture."
            error_text_hi = get_localized_prompt(doc_config, "error_low_confidence", session.language)
            
            return {
                "success": False,
                "validation_error_key": "error_low_confidence",
                "validation_error_text": error_msg_en if session.language == "en" else error_text_hi,
                "next_page_id": next_page_id,
                "next_part_id": next_page_id,
                "confirm_fields": confirm_fields,
                "extracted_fields_json": json.dumps(flat_extracted_dict),
                "next_document_id": doc_id
            }
            
        session.record_extraction(part_id, flat_extracted_dict)
        page_advanced, doc_advanced = session.advance_page()
        next_page = session.get_current_page()
        
        if doc_advanced:
            try:
                flat_data = session.get_all_extracted_data()
                logger.info(f"_execute_extraction_flow: upserting extracted data to app orchestrator: {json.dumps(flat_data)}")
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
                
        return {
            "success": True,
            "extracted_fields_json": json.dumps(flat_extracted_dict),
            "page_complete": True,
            "document_complete": doc_advanced,
            "all_complete": session.is_all_complete(),
            "confirm_fields": confirm_fields,
            "part_id": part_id,
            "next_page_id": next_page.get("page_id") if next_page else "",
            "next_part_id": next_page.get("page_id") if next_page else "",
            "next_document_id": session.get_current_document_id()
        }

async def serve():
    server = grpc_aio.server()
    pb2_grpc.add_DocumentCaptureServicer_to_server(DocumentCaptureServicer(), server)
    server.add_insecure_port(f'[::]:{DOC_CAPTURE_PORT}')
    logger.info(f"Doc-Capture service starting on port {DOC_CAPTURE_PORT}")
    await server.start()
    await server.wait_for_termination()

if __name__ == '__main__':
    asyncio.run(serve())
