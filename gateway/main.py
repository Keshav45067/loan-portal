"""
API Gateway — main entry point.

Custom-built lightweight gateway using FastAPI:
- REST endpoints (JSON) for client-facing APIs
- WebSocket endpoint for voice streaming
- gRPC client connections to all internal services
- JWT auth middleware (lightweight — skips on WS upgrade)
- req_id generation and propagation via gRPC metadata
- CORS for frontend

Only component that speaks REST/WebSocket. Everything behind it is gRPC.
"""

import sys
import os
import asyncio

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'shared'))
from log_utils.logger import get_logger

from config import GATEWAY_PORT
from middleware.jwt_auth import RequestIDMiddleware
from routes.auth_routes import router as auth_router
from routes.voice_routes import router as voice_router
from routes.application_routes import router as application_router
from routes.document_routes import router as document_router
from routes.tts_routes import router as tts_router
from routes.capture_routes import router as capture_router
from routes.sandbox_pipeline_routes import router as sandbox_pipeline_router

logger = get_logger("gateway")

# ─── Create FastAPI App ───
app = FastAPI(
    title="Augmen Gateway",
    description="API Gateway for Chayan AI Platform — REST/WS ↔ gRPC bridge",
    version="1.0.0",
)

# ─── Middleware ───
# Request ID middleware (generates req_id, tracks latency)
app.add_middleware(RequestIDMiddleware)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Tighten in production
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Register Routes ───
app.include_router(auth_router)
app.include_router(voice_router)
app.include_router(application_router)
app.include_router(document_router)
app.include_router(tts_router)
app.include_router(capture_router)
app.include_router(sandbox_pipeline_router)


# ─── Health Check ───
@app.get("/health")
async def health_check():
    """Health check endpoint — no auth required."""
    return {
        "status": "healthy",
        "service": "gateway",
        "version": "1.0.0",
    }


# ─── Startup/Shutdown Events ───
@app.on_event("startup")
async def startup():
    """Initialize gRPC client connections to all services."""
    logger.info(f"Gateway starting on port {GATEWAY_PORT}")

    import grpc
    from grpc_clients.generated import app_orchestrator_pb2_grpc
    from grpc_clients.generated import doc_intelligence_pb2_grpc
    from grpc_clients.generated import voice_engine_pb2_grpc
    from grpc_clients.generated import tts_pb2_grpc
    from grpc_clients.generated import doc_capture_pb2_grpc
    from config import APP_ORCHESTRATOR_ADDR, DOC_INTELLIGENCE_ADDR, VOICE_ENGINE_ADDR, TTS_SERVICE_ADDR, DOC_CAPTURE_ADDR

    # Max message size to 100MB for image data transferring
    channel_options = [
        ("grpc.max_send_message_length", 100 * 1024 * 1024),
        ("grpc.max_receive_message_length", 100 * 1024 * 1024),
    ]

    app.state.orchestrator_channel = grpc.aio.insecure_channel(APP_ORCHESTRATOR_ADDR, options=channel_options)
    app.state.orchestrator_stub = app_orchestrator_pb2_grpc.ApplicationOrchestratorStub(app.state.orchestrator_channel)

    app.state.doc_intel_channel = grpc.aio.insecure_channel(DOC_INTELLIGENCE_ADDR, options=channel_options)
    app.state.doc_intel_stub = doc_intelligence_pb2_grpc.DocumentIntelligenceStub(app.state.doc_intel_channel)

    app.state.voice_engine_channel = grpc.aio.insecure_channel(VOICE_ENGINE_ADDR, options=channel_options)
    app.state.voice_engine_stub = voice_engine_pb2_grpc.VoiceConversationStub(app.state.voice_engine_channel)

    app.state.tts_channel = grpc.aio.insecure_channel(TTS_SERVICE_ADDR, options=channel_options)
    app.state.tts_stub = tts_pb2_grpc.TextToSpeechStub(app.state.tts_channel)

    app.state.doc_capture_channel = grpc.aio.insecure_channel(DOC_CAPTURE_ADDR, options=channel_options)
    app.state.doc_capture_stub = doc_capture_pb2_grpc.DocumentCaptureStub(app.state.doc_capture_channel)

    logger.info("Gateway ready ✅")


@app.on_event("shutdown")
async def shutdown():
    """Close gRPC channels."""
    logger.info("Gateway shutting down...")

    await app.state.orchestrator_channel.close()
    await app.state.doc_intel_channel.close()
    await app.state.voice_engine_channel.close()
    await app.state.tts_channel.close()
    await app.state.doc_capture_channel.close()

    logger.info("Gateway stopped")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=GATEWAY_PORT,
        reload=False,
        log_level="info",
    )
