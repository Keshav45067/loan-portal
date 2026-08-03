"""
Capture Routes — API Gateway routes for the Smart Document Capture product.
Bridges REST endpoints to the DocCapture gRPC service, and WebSocket to Voice Engine RawAgentSession.
"""

import asyncio
import json
from fastapi import APIRouter, Request, Depends, UploadFile, File, Form, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'shared'))
from log_utils.logger import get_logger, generate_req_id, set_req_id
from middleware.jwt_auth import require_auth, verify_ws_token

from grpc_clients.generated import doc_capture_pb2
from grpc_clients.generated import voice_engine_pb2

logger = get_logger("gateway")
router = APIRouter(tags=["capture"])

# --- REST Models ---

class StartCaptureRequest(BaseModel):
    scheme_id: str
    language: str

# --- REST Endpoints ---

@router.post("/api/capture/start")
async def start_capture_session(body: StartCaptureRequest, request: Request, auth: dict = Depends(require_auth)):
    req_id = request.state.req_id
    session_id = auth.get("session_id")
    
    try:
        stub = request.app.state.doc_capture_stub
        res = await stub.StartSession(
            doc_capture_pb2.StartCaptureRequest(
                scheme_id=body.scheme_id,
                session_id=session_id,
                language=body.language
            ),
            metadata=[("x-request-id", req_id)]
        )
        
        if not res.success:
            return {"success": False, "error": res.error}
            
        page_info = None
        if res.HasField("current_page_info"):
            pi = res.current_page_info
            page_info = {
                "page_id": pi.page_id,
                "page_name": pi.page_name,
                "allow_multiple": pi.allow_multiple,
                "ui_camera_overlay": pi.ui_camera_overlay,
                "intro_prompt": json.loads(pi.intro_prompt_json) if pi.intro_prompt_json else {},
                "success_prompt": json.loads(pi.success_prompt_json) if pi.success_prompt_json else {},
                "error_blur_prompt": json.loads(pi.error_blur_prompt_json) if pi.error_blur_prompt_json else {},
                "error_invalid_doc_prompt": json.loads(pi.error_invalid_doc_prompt_json) if pi.error_invalid_doc_prompt_json else {},
                "acceptable_formats": list(pi.acceptable_formats),
                "max_file_size_mb": pi.max_file_size_mb,
                "uploads_count": pi.uploads_count
            }
            
        return {
            "success": True,
            "session_id": res.session_id,
            "current_document_id": res.current_document_id,
            "current_page_id": res.current_page_id,
            "current_document_index": res.current_document_index,
            "total_documents": res.total_documents,
            "current_page_index": res.current_page_index,
            "total_pages": res.total_pages,
            "current_page_info": page_info,
            "all_complete": res.all_complete
        }
    except Exception as e:
        logger.error(f"start_capture_session failed: {e}", req_id=req_id)
        return {"success": False, "error": str(e)}

@router.get("/api/capture/page-info")
async def get_page_info(session_id: str, request: Request, auth: dict = Depends(require_auth)):
    req_id = request.state.req_id
    try:
        stub = request.app.state.doc_capture_stub
        res = await stub.GetPageInfo(
            doc_capture_pb2.PageInfoRequest(session_id=session_id),
            metadata=[("x-request-id", req_id)]
        )
        if not res.success:
            return {"success": False, "error": res.error}
            
        page_info = None
        if res.HasField("page_info"):
            pi = res.page_info
            page_info = {
                "page_id": pi.page_id,
                "page_name": pi.page_name,
                "allow_multiple": pi.allow_multiple,
                "ui_camera_overlay": pi.ui_camera_overlay,
                "intro_prompt": json.loads(pi.intro_prompt_json) if pi.intro_prompt_json else {},
                "success_prompt": json.loads(pi.success_prompt_json) if pi.success_prompt_json else {},
                "error_blur_prompt": json.loads(pi.error_blur_prompt_json) if pi.error_blur_prompt_json else {},
                "error_invalid_doc_prompt": json.loads(pi.error_invalid_doc_prompt_json) if pi.error_invalid_doc_prompt_json else {},
                "acceptable_formats": list(pi.acceptable_formats),
                "max_file_size_mb": pi.max_file_size_mb,
                "uploads_count": pi.uploads_count
            }
            
        return {
            "success": True,
            "page_info": page_info,
            "document_id": res.document_id,
            "document_name": res.document_name,
            "document_index": res.document_index,
            "total_documents": res.total_documents
        }
    except Exception as e:
        logger.error(f"get_page_info failed: {e}", req_id=req_id)
        return {"success": False, "error": str(e)}

@router.get("/api/capture/scheme/{scheme_id}")
async def get_scheme_config(scheme_id: str, request: Request):
    req_id = request.state.req_id
    try:
        stub = request.app.state.doc_capture_stub
        res = await stub.GetSchemeConfig(
            doc_capture_pb2.SchemeConfigRequest(scheme_id=scheme_id),
            metadata=[("x-request-id", req_id)]
        )
        if not res.success:
            return {"success": False, "error": res.error}
        return {
            "success": True,
            "scheme_id": res.scheme_id,
            "scheme_name": res.scheme_name,
            "description": res.description,
            "required_documents": list(res.required_documents)
        }
    except Exception as e:
        logger.error(f"get_scheme_config failed: {e}", req_id=req_id)
        return {"success": False, "error": str(e)}

@router.get("/api/capture/document/{document_id}")
async def get_document_config(document_id: str, request: Request):
    req_id = request.state.req_id
    try:
        stub = request.app.state.doc_capture_stub
        res = await stub.GetDocumentConfig(
            doc_capture_pb2.DocConfigRequest(document_id=document_id),
            metadata=[("x-request-id", req_id)]
        )
        if not res.success:
            return {"success": False, "error": res.error}
            
        pages = []
        for p in res.pages:
            pages.append({
                "page_id": p.page_id,
                "page_name": p.page_name,
                "allow_multiple": p.allow_multiple,
                "ui_camera_overlay": p.ui_camera_overlay,
                "prompts": json.loads(p.prompts_json) if p.prompts_json else {}
            })
            
        return {
            "success": True,
            "document_id": res.document_id,
            "document_name": res.document_name,
            "description": res.description,
            "allowed_languages": list(res.allowed_languages),
            "acceptable_formats": list(res.acceptable_formats),
            "max_file_size_mb": res.max_file_size_mb,
            "pages": pages
        }
    except Exception as e:
        logger.error(f"get_document_config failed: {e}", req_id=req_id)
        return {"success": False, "error": str(e)}

@router.get("/api/capture/fields-registry")
def get_fields_registry():
    try:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(current_dir, "..", "..", "doc-capture", "configs", "fields.json")
        import json
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to read fields.json: {e}")
        return {}

@router.get("/api/capture/manifest/{document_id}")
def get_document_manifest(document_id: str):
    try:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(current_dir, "..", "..", "doc-capture", "configs", "manifests", f"{document_id}.json")
        import json
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to read manifest {document_id}: {e}")
        return {}

@router.get("/api/capture/scheme-docs/{scheme_id}")
def get_scheme_docs(scheme_id: str):
    """Return required_documents manifests + fields registry for a scheme, in a single call."""
    import json
    current_dir = os.path.dirname(os.path.abspath(__file__))
    try:
        # 1. Load scheme config
        scheme_path = os.path.join(current_dir, "..", "..", "doc-capture", "configs", "schemes", f"{scheme_id}.json")
        with open(scheme_path, "r", encoding="utf-8") as f:
            scheme = json.load(f)
        required_docs = scheme.get("required_documents", [])
        
        # 2. Load each manifest
        manifests = {}
        for doc_id in required_docs:
            manifest_path = os.path.join(current_dir, "..", "..", "doc-capture", "configs", "manifests", f"{doc_id}.json")
            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    manifests[doc_id] = json.load(f)
            except Exception as e:
                logger.error(f"Failed to read manifest {doc_id}: {e}")
        
        # 3. Load fields registry
        fields_path = os.path.join(current_dir, "..", "..", "doc-capture", "configs", "fields.json")
        fields_registry = {}
        try:
            with open(fields_path, "r", encoding="utf-8") as f:
                fields_registry = json.load(f)
        except Exception as e:
            logger.error(f"Failed to read fields.json: {e}")
        
        return {
            "success": True,
            "scheme_id": scheme_id,
            "required_documents": required_docs,
            "manifests": manifests,
            "fields_registry": fields_registry
        }
    except FileNotFoundError:
        logger.error(f"Scheme config not found: {scheme_id}")
        return {"success": False, "error": f"Scheme '{scheme_id}' not found", "manifests": {}, "fields_registry": {}}
    except Exception as e:
        logger.error(f"get_scheme_docs failed: {e}")
        return {"success": False, "error": str(e), "manifests": {}, "fields_registry": {}}

@router.post("/api/capture/process")
async def process_document(
    request: Request,
    file: UploadFile = File(...),
    document_id: str = Form(...),
    page_id: str = Form(...),
    auth: dict = Depends(require_auth)
):
    req_id = request.state.req_id
    session_id = auth.get("session_id")
    image_bytes = await file.read()
    content_type = file.content_type or "image/jpeg"
    
    try:
        stub = request.app.state.doc_capture_stub
        res = await stub.ProcessDocument(
            doc_capture_pb2.ProcessDocRequest(
                session_id=session_id,
                document_id=document_id,
                page_id=page_id,
                image_data=image_bytes,
                content_type=content_type,
                filename=file.filename
            ),
            metadata=[("x-request-id", req_id)]
        )
        
        if res.success:
            try:
                import grpc
                from grpc_clients.generated import agent_pb2, agent_pb2_grpc
                agent_channel = grpc.aio.insecure_channel("localhost:50059")
                agent_stub = agent_pb2_grpc.AgentServiceStub(agent_channel)
                # Use backend's processed_document_id (source of truth), NOT client's form param
                sync_doc_id = res.processed_document_id or document_id
                await agent_stub.SyncExtractedData(
                    agent_pb2.SyncExtractedDataRequest(
                        session_id=session_id,
                        doc_id=sync_doc_id,
                        part_id=res.part_id or page_id,
                        json_extracted_fields=res.extracted_fields_json,
                        page_complete=res.page_complete
                    )
                )
            except Exception as agent_sync_err:
                logger.warning(f"Failed to sync extracted data with agent-service: {agent_sync_err}", req_id=req_id)

        # NOTE: GCS uploading is done in the doc-capture service via orchestrator
        return {
            "success": res.success,
            "error": res.error,
            "extracted_fields": json.loads(res.extracted_fields_json) if res.extracted_fields_json else {},
            "validation_error_key": res.validation_error_key,
            "validation_error_text": res.validation_error_text,
            "validation_field_id": res.validation_field_id,
            "page_complete": res.page_complete,
            "document_complete": res.document_complete,
            "all_complete": res.all_complete,
            "next_page_id": res.next_page_id,
            "next_document_id": res.next_document_id,
            "processed_document_id": res.processed_document_id or document_id,
        }
    except Exception as e:
        logger.error(f"process_document failed: {e}", req_id=req_id)
        return {"success": False, "error": str(e)}


@router.post("/api/capture/advance")
async def advance_capture_page(
    request: Request,
    auth: dict = Depends(require_auth)
):
    req_id = request.state.req_id
    session_id = auth.get("session_id")
    
    try:
        stub = request.app.state.doc_capture_stub
        res = await stub.AdvancePage(
            doc_capture_pb2.AdvancePageRequest(session_id=session_id),
            metadata=[("x-request-id", req_id)]
        )
        page_info = None
        if res.HasField("current_page_info"):
            pi = res.current_page_info
            page_info = {
                "page_id": pi.page_id,
                "page_name": pi.page_name,
                "allow_multiple": pi.allow_multiple,
                "ui_camera_overlay": pi.ui_camera_overlay,
                "intro_prompt": json.loads(pi.intro_prompt_json) if pi.intro_prompt_json else {},
                "success_prompt": json.loads(pi.success_prompt_json) if pi.success_prompt_json else {},
                "error_blur_prompt": json.loads(pi.error_blur_prompt_json) if pi.error_blur_prompt_json else {},
                "error_invalid_doc_prompt": json.loads(pi.error_invalid_doc_prompt_json) if pi.error_invalid_doc_prompt_json else {},
                "acceptable_formats": list(pi.acceptable_formats),
                "max_file_size_mb": pi.max_file_size_mb,
                "uploads_count": pi.uploads_count
            }
            
        return {
            "success": res.success,
            "error": res.error,
            "session_id": res.session_id,
            "current_document_id": res.current_document_id,
            "current_page_id": res.current_page_id,
            "current_document_index": res.current_document_index,
            "total_documents": res.total_documents,
            "current_page_index": res.current_page_index,
            "total_pages": res.total_pages,
            "all_complete": res.all_complete,
            "current_page_info": page_info,
            "validation_error_key": "error_low_confidence" if not res.success else "",
            "validation_error_text": res.error if not res.success else "",
            "next_page_id": res.current_page_id,
            "next_document_id": res.current_document_id
        }
    except Exception as e:
        logger.error(f"advance_capture_page failed: {e}", req_id=req_id)
        return {"success": False, "error": str(e)}


class SwitchCapturePageRequest(BaseModel):
    document_id: str
    page_id: str = ""

@router.post("/api/capture/switch-page")
async def switch_capture_page(
    body: SwitchCapturePageRequest,
    request: Request,
    auth: dict = Depends(require_auth)
):
    req_id = request.state.req_id
    session_id = auth.get("session_id")
    
    try:
        stub = request.app.state.doc_capture_stub
        res = await stub.SwitchPage(
            doc_capture_pb2.SwitchPageRequest(
                session_id=session_id,
                document_id=body.document_id,
                page_id=body.page_id
            ),
            metadata=[("x-request-id", req_id)]
        )
        page_info = None
        if res.HasField("current_page_info"):
            pi = res.current_page_info
            page_info = {
                "page_id": pi.page_id,
                "page_name": pi.page_name,
                "allow_multiple": pi.allow_multiple,
                "ui_camera_overlay": pi.ui_camera_overlay,
                "intro_prompt": json.loads(pi.intro_prompt_json) if pi.intro_prompt_json else {},
                "success_prompt": json.loads(pi.success_prompt_json) if pi.success_prompt_json else {},
                "acceptable_formats": list(pi.acceptable_formats),
                "max_file_size_mb": pi.max_file_size_mb,
                "uploads_count": pi.uploads_count
            }
            
        return {
            "success": res.success,
            "error": res.error,
            "session_id": res.session_id,
            "current_document_id": res.current_document_id,
            "current_page_id": res.current_page_id,
            "current_document_index": res.current_document_index,
            "total_documents": res.total_documents,
            "current_page_index": res.current_page_index,
            "total_pages": res.total_pages,
            "all_complete": res.all_complete,
            "current_page_info": page_info,
        }
    except Exception as e:
        logger.error(f"switch_capture_page failed: {e}", req_id=req_id)
        return {"success": False, "error": str(e)}


# --- WebSocket Endpoint for FAQ ---

@router.websocket("/ws/capture-voice")
async def capture_voice_websocket(websocket: WebSocket):
    """
    WebSocket endpoint for Smart Document Capture FAQ voice interface.
    Bridges to VoiceEngine's RawAgentSession.
    """
    await websocket.accept()
    req_id = generate_req_id()
    set_req_id(req_id)

    session_id = None
    try:
        raw = await asyncio.wait_for(websocket.receive_text(), timeout=10.0)
        init_data = json.loads(raw)
        token = init_data.get("token", "")
        payload = verify_ws_token(token)
        if not payload:
            await websocket.send_json({"error": "Invalid token"})
            await websocket.close(code=4001)
            return

        session_id = payload.get("session_id")
        language = init_data.get("language", "en")
        
        # 1. Fetch system and context prompts from doc-capture service
        doc_capture_stub = websocket.app.state.doc_capture_stub
        faq_res = await doc_capture_stub.GetFAQPrompt(
            doc_capture_pb2.FAQPromptRequest(session_id=session_id),
            metadata=[("x-request-id", req_id)]
        )
        
        system_prompt = faq_res.system_prompt if faq_res.success else "You are a helpful assistant."
        context_prompt = faq_res.context_prompt if faq_res.success else ""
        
        # Send connected confirmation
        await websocket.send_json({
            "type": "status",
            "status": "connected",
            "session_id": session_id,
            "req_id": req_id,
        })
        
        # 2. Bridge to VoiceEngine's RawAgentSession
        voice_stub = websocket.app.state.voice_engine_stub
        grpc_queue = asyncio.Queue()
        
        # Start message
        start_req = voice_engine_pb2.RawAgentInput(
            agent_start=voice_engine_pb2.AgentStart(
                session_id=session_id,
                language=language,
                system_prompt=system_prompt,
                context_prompt=context_prompt
            )
        )
        await grpc_queue.put(start_req)
        
        async def grpc_request_generator():
            while True:
                item = await grpc_queue.get()
                if item is None:
                    break
                yield item
                
        grpc_stream = voice_stub.RawAgentSession(
            grpc_request_generator(),
            metadata=[("x-request-id", req_id)]
        )
        
        async def ws_to_grpc():
            try:
                while True:
                    message = await websocket.receive()
                    if message.get("type") == "websocket.disconnect":
                        break
                        
                    if "bytes" in message and message["bytes"]:
                        await grpc_queue.put(voice_engine_pb2.RawAgentInput(audio_chunk=message["bytes"]))
                    elif "text" in message and message["text"]:
                        try:
                            data = json.loads(message["text"])
                            text_input = data.get("text_input", "")
                            signal = data.get("signal", "")
                            if text_input:
                                await grpc_queue.put(voice_engine_pb2.RawAgentInput(text_input=text_input))
                            elif signal:
                                if signal == "update_page_context":
                                    try:
                                        faq_res = await doc_capture_stub.GetFAQPrompt(
                                            doc_capture_pb2.FAQPromptRequest(session_id=session_id),
                                            metadata=[("x-request-id", req_id)]
                                        )
                                        if faq_res.success:
                                            await grpc_queue.put(voice_engine_pb2.RawAgentInput(
                                                agent_start=voice_engine_pb2.AgentStart(
                                                    session_id=session_id,
                                                    language=language,
                                                    system_prompt=faq_res.system_prompt,
                                                    context_prompt=faq_res.context_prompt
                                                )
                                            ))
                                            logger.info(f"Dynamically updated voice context prompts on page change.", req_id=req_id)
                                    except Exception as context_err:
                                        logger.error(f"Failed to fetch updated FAQ prompts on signal: {context_err}", req_id=req_id)
                                else:
                                    await grpc_queue.put(voice_engine_pb2.RawAgentInput(
                                        control=voice_engine_pb2.ControlSignal(signal=signal)
                                    ))
                        except Exception:
                            pass
            finally:
                await grpc_queue.put(None)
                
        async def grpc_to_ws():
            pending_text = ''
            try:
                async for response in grpc_stream:
                    output_type = response.WhichOneof("output")
                    if output_type == "status":
                        await websocket.send_json({"type": "status", "status": response.status.status})
                    elif output_type == "transcription":
                        if response.transcription.is_final:
                            await websocket.send_json({
                                "type": "transcription",
                                "text": response.transcription.text,
                                "is_final": True
                            })
                        else:
                            pending_text = response.transcription.text
                    elif output_type == "audio":
                        await websocket.send_json({
                            "type": "audio_chunk",
                            "sample_rate": response.audio.sample_rate,
                            "text": pending_text
                        })
                        pending_text = ''
                        await websocket.send_bytes(response.audio.wav_data)
                    elif output_type == "audio_end":
                        await websocket.send_json({"type": "audio_end"})
                    elif output_type == "extraction":
                        try:
                            payload_obj = json.loads(response.extraction.json_fields)
                            if isinstance(payload_obj, dict) and payload_obj.get("type") == "control_signal":
                                await websocket.send_json({
                                    "type": "control_signal",
                                    "signal": payload_obj.get("signal"),
                                    "payload": payload_obj.get("payload", {})
                                })
                            else:
                                await websocket.send_json({
                                    "type": "extraction",
                                    "json_fields": response.extraction.json_fields
                                })
                        except Exception:
                            await websocket.send_json({
                                "type": "extraction",
                                "json_fields": response.extraction.json_fields
                            })
                    elif output_type == "node_change":
                        await websocket.send_json({
                            "type": "node_change",
                            "node_type": response.node_change.node_type,
                            "document_id": response.node_change.document_id
                        })
                    elif output_type == "error":
                        await websocket.send_json({
                            "type": "error",
                            "code": response.error.code,
                            "message": response.error.message
                        })
            except Exception as e:
                logger.error(f"grpc_to_ws error: {e}", req_id=req_id)
                try:
                    await websocket.send_json({"type": "error", "code": "CONNECTION_LOST", "message": str(e)})
                except: pass
                
        await asyncio.gather(ws_to_grpc(), grpc_to_ws())
        
    except WebSocketDisconnect:
        logger.info("capture_voice_websocket disconnected")
    except Exception as e:
        logger.error(f"capture_voice_websocket error: {e}")
        try:
            await websocket.close(code=1011)
        except: pass
