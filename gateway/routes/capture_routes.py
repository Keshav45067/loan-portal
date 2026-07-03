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
router = APIRouter(prefix="/api/capture", tags=["capture"])

# --- REST Models ---

class StartCaptureRequest(BaseModel):
    scheme_id: str
    language: str

# --- REST Endpoints ---

@router.post("/start")
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

@router.get("/scheme/{scheme_id}")
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

@router.get("/document/{document_id}")
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

@router.post("/process")
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
            "next_document_id": res.next_document_id
        }
    except Exception as e:
        logger.error(f"process_document failed: {e}", req_id=req_id)
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
        start_req = voice_engine_pb2.RawVoiceInput(
            session_start=voice_engine_pb2.RawSessionStart(
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
                        await grpc_queue.put(voice_engine_pb2.RawVoiceInput(audio_chunk=message["bytes"]))
                    elif "text" in message and message["text"]:
                        try:
                            data = json.loads(message["text"])
                            text_input = data.get("text_input", "")
                            signal = data.get("signal", "")
                            if text_input:
                                await grpc_queue.put(voice_engine_pb2.RawVoiceInput(text_input=text_input))
                            elif signal:
                                await grpc_queue.put(voice_engine_pb2.RawVoiceInput(
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
