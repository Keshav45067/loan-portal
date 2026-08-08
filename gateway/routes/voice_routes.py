"""
Voice Routes — WebSocket endpoint for voice streaming.

Bridges WebSocket ↔ gRPC bidirectional stream to Voice Conversation Engine.
JWT is verified on the first WebSocket message, NOT on upgrade, to minimize latency.
"""

import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'shared'))
from log_utils.logger import get_logger, generate_req_id, set_req_id

from middleware.jwt_auth import verify_ws_token

logger = get_logger("gateway")
router = APIRouter(tags=["voice"])


@router.websocket("/ws/voice")
async def voice_websocket(websocket: WebSocket):
    """
    WebSocket endpoint for voice interview sessions.

    Protocol:
    1. Client connects via WebSocket (no auth check on upgrade)
    2. First message must be JSON: { "token": "jwt...", "scheme_id": "...", ... }
    3. After auth, subsequent messages are binary PCM audio chunks
    4. Control signals are JSON: { "signal": "speech_start" } or { "signal": "speech_end" }
    5. Server sends back: binary audio chunks, JSON status/progress/extraction updates
    """
    await websocket.accept()

    req_id = generate_req_id()
    set_req_id(req_id)

    logger.info("WebSocket connected", req_id=req_id, method="voice_websocket")

    session_id = None
    authenticated = False

    try:
        # ─── Phase 1: Authentication (first message) ───
        raw = await asyncio.wait_for(websocket.receive_text(), timeout=10.0)
        init_data = json.loads(raw)

        token = init_data.get("token", "")
        payload = verify_ws_token(token)

        if not payload:
            await websocket.send_json({"error": "Invalid or expired token"})
            await websocket.close(code=4001, reason="Authentication failed")
            logger.warning("WebSocket auth failed", req_id=req_id)
            return

        authenticated = True
        session_id = payload.get("session_id", init_data.get("session_id", ""))
        scheme_id = init_data.get("scheme_id", "")
        language = init_data.get("language", "hi")
        applicant_name = init_data.get("applicant_name", "")

        logger.info("WebSocket authenticated",
                     req_id=req_id,
                     session_id=session_id,
                     details={"scheme_id": scheme_id, "language": language})

        # Send connected confirmation
        await websocket.send_json({
            "type": "status",
            "status": "connected",
            "session_id": session_id,
            "req_id": req_id,
        })

        # ─── Phase 2: Bridge WebSocket ↔ gRPC Voice Engine ───
        from grpc_clients.generated import voice_engine_pb2

        voice_stub = websocket.app.state.voice_engine_stub
        grpc_queue = asyncio.Queue()

        # Enqueue the first message (SessionStart)
        start_req = voice_engine_pb2.VoiceInput(
            session_start=voice_engine_pb2.SessionStart(
                scheme_id=scheme_id,
                session_id=session_id,
                language=language,
                applicant_name=applicant_name,
                application_id=init_data.get("application_id", "")
            )
        )
        await grpc_queue.put(start_req)

        # Async generator for the gRPC stream
        async def grpc_request_generator():
            while True:
                item = await grpc_queue.get()
                if item is None:
                    break
                yield item

        # Start the gRPC session stream
        grpc_stream = voice_stub.Session(
            grpc_request_generator(),
            metadata=[("x-request-id", req_id)]
        )

        async def ws_to_grpc():
            try:
                while True:
                    message = await websocket.receive()
                    if message.get("type") == "websocket.disconnect":
                        logger.info("WebSocket disconnected from client", req_id=req_id, session_id=session_id)
                        break

                    if "bytes" in message and message["bytes"]:
                        await grpc_queue.put(voice_engine_pb2.VoiceInput(
                            audio_chunk=message["bytes"]
                        ))
                    elif "text" in message and message["text"]:
                        try:
                            data = json.loads(message["text"])
                            text_input = data.get("text_input", "")
                            signal = data.get("signal", "")
                            if text_input:
                                await grpc_queue.put(voice_engine_pb2.VoiceInput(
                                    text_input=text_input
                                ))
                            elif signal:
                                await grpc_queue.put(voice_engine_pb2.VoiceInput(
                                    control=voice_engine_pb2.ControlSignal(signal=signal)
                                ))
                        except Exception:
                            pass
            except Exception as e:
                logger.error(f"Error in ws_to_grpc: {e}", req_id=req_id, session_id=session_id)
            finally:
                await grpc_queue.put(None)

        async def grpc_to_ws():
            pending_text = ''  # Text from transcription(is_final=false) to pair with next audio
            try:
                async for response in grpc_stream:
                    output_type = response.WhichOneof("output")
                    if output_type == "status":
                        await websocket.send_json({
                            "type": "status",
                            "status": response.status.status
                        })
                    elif output_type == "transcription":
                        if response.transcription.is_final:
                            # User's STT result — send as transcription
                            await websocket.send_json({
                                "type": "transcription",
                                "text": response.transcription.text,
                                "is_final": True
                            })
                        else:
                            # Assistant's per-sentence text — store as pending
                            # Will be sent as audio_chunk header with next audio binary
                            pending_text = response.transcription.text
                    elif output_type == "audio":
                        # Send JSON header with text before binary audio
                        # (exact same protocol as Hindi repo's _synthesize_and_send)
                        await websocket.send_json({
                            "type": "audio_chunk",
                            "sample_rate": response.audio.sample_rate,
                            "text": pending_text
                        })
                        pending_text = ''  # Clear after pairing
                        await websocket.send_bytes(response.audio.wav_data)
                    elif output_type == "progress":
                        await websocket.send_json({
                            "type": "progress",
                            "current_step": response.progress.current_step,
                            "total_steps": response.progress.total_steps,
                            "current_node_id": response.progress.current_node_id
                        })
                    elif output_type == "extraction":
                        await websocket.send_json({
                            "type": "extraction",
                            "node_id": response.extraction.node_id,
                            "json_fields": response.extraction.json_fields
                        })
                    elif output_type == "audio_end":
                        await websocket.send_json({
                            "type": "audio_end"
                        })
                    elif output_type == "node_change":
                        await websocket.send_json({
                            "type": "node_change",
                            "node_type": response.node_change.node_type,
                            "document_id": response.node_change.document_id,
                            "manifest_id": getattr(response.node_change, "manifest_id", ""),
                            "page_id": getattr(response.node_change, "page_id", "")
                        })
                    elif output_type == "error":
                        await websocket.send_json({
                            "type": "error",
                            "code": response.error.code,
                            "message": response.error.message
                        })
                    elif output_type == "complete":
                        # Auto-save voice session results to PostgreSQL
                        try:
                            from grpc_clients.generated import app_orchestrator_pb2
                            orch_stub = websocket.app.state.orchestrator_stub
                            source_name = "document-qa" if scheme_id == "documents-qa" else "interview"
                            import json
                            extracted_data_dict = json.loads(response.complete.json_extracted_data) if response.complete.json_extracted_data else {}
                            extracted_data_dict["onboarding_finished"] = True
                            extracted_data_dict["completion_status"] = "COMPLETED"

                            await orch_stub.UpsertExtractedData(
                                app_orchestrator_pb2.UpsertDataRequest(
                                    application_id=response.complete.session_id,
                                    source=source_name,
                                    json_fields=json.dumps(extracted_data_dict, ensure_ascii=False)
                                ),
                                metadata=[("x-request-id", req_id)]
                            )
                            logger.info("Successfully persisted voice session extraction to DB", 
                                        session_id=response.complete.session_id, source=source_name)
                        except Exception as db_err:
                            logger.error(f"Failed to auto-save completed voice session data: {db_err}", 
                                         req_id=req_id, session_id=response.complete.session_id)

                        await websocket.send_json({
                            "type": "complete",
                            "session_id": response.complete.session_id,
                            "json_extracted_data": response.complete.json_extracted_data,
                            "total_turns": response.complete.total_turns
                        })
            except Exception as e:
                logger.error(f"Error in grpc_to_ws: {e}", req_id=req_id, session_id=session_id)
                try:
                    await websocket.send_json({
                        "type": "error",
                        "code": "CONNECTION_LOST",
                        "message": f"सर्वर कनेक्शन त्रुटि: {str(e)}"
                    })
                except Exception:
                    pass

        # Run both tasks concurrently
        await asyncio.gather(ws_to_grpc(), grpc_to_ws())

    except asyncio.TimeoutError:
        logger.warning("WebSocket auth timeout (10s)", req_id=req_id)
        await websocket.close(code=4002, reason="Authentication timeout")
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected",
                     req_id=req_id, session_id=session_id)
    except Exception as e:
        logger.error(f"WebSocket error: {e}",
                     req_id=req_id, session_id=session_id, error=str(e))
        try:
            await websocket.close(code=1011, reason="Internal error")
        except Exception:
            pass
