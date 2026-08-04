# Force IPv4 resolution to bypass macOS IPv6 network blackhole
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

"""
Agent Service — Dual gRPC (port 50059) and FastAPI HTTP (port 8090) server.
"""

import json
import asyncio
import logging
import grpc
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from config import AGENT_SERVICE_PORT, AGENT_GRPC_PORT
from session import create_session, get_session
from agent import run_agent_turn

# Import generated gRPC stubs
try:
    from generated import agent_pb2, agent_pb2_grpc
    GRPC_AVAILABLE = True
except ImportError:
    GRPC_AVAILABLE = False

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("agent-service")

# ─── FastAPI App ───

app = FastAPI(
    title="Augmen Agent Service",
    description="Agentic Document Capture Co-Pilot — gRPC & FastAPI Server",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Request/Response Models ───

class InitRequest(BaseModel):
    scheme_id: str = "sandbox-demo"

class ChatRequest(BaseModel):
    session_id: str
    message: str


# ─── Endpoints ───

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "agent-service",
        "version": "0.1.0",
        "grpc_port": AGENT_GRPC_PORT,
        "http_port": AGENT_SERVICE_PORT
    }


@app.post("/init")
async def init_session(body: InitRequest):
    """Create a new agent session with mock data."""
    session = create_session(scheme_id=body.scheme_id)
    if not session.manifests:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to initialize session. Scheme '{body.scheme_id}' not found or no manifests loaded.",
        )

    return {
        "success": True,
        "session_id": session.session_id,
        "session_state": session.to_dict(),
    }


@app.post("/chat")
async def chat(body: ChatRequest):
    """Send a message to the agent and get a response."""
    session = get_session(body.session_id)
    if not session:
        session = create_session(scheme_id="sandbox-demo", session_id=body.session_id)

    if not body.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    result = await run_agent_turn(session, body.message.strip())

    return {
        "success": True,
        **result,
    }


@app.get("/session/{session_id}")
async def get_session_state(session_id: str):
    """Get current session state."""
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    return {
        "success": True,
        "session_state": session.to_dict(),
    }


# ─── gRPC Servicer Implementation ───

if GRPC_AVAILABLE:
    class AgentServiceServicer(agent_pb2_grpc.AgentServiceServicer):
        async def InitSession(self, request, context):
            try:
                scheme_id = request.scheme_id or "demo_business_kyc"
                sess_id = request.session_id if request.session_id else None
                session = create_session(scheme_id=scheme_id, session_id=sess_id)
                if not session.manifests:
                    return agent_pb2.InitSessionResponse(
                        success=False,
                        error=f"Failed to initialize scheme '{scheme_id}'"
                    )
                return agent_pb2.InitSessionResponse(
                    success=True,
                    session_id=session.session_id,
                    json_session_state=json.dumps(session.to_dict())
                )
            except Exception as e:
                logger.error(f"gRPC InitSession error: {e}")
                return agent_pb2.InitSessionResponse(success=False, error=str(e))

        async def RunTurn(self, request, context):
            try:
                session = get_session(request.session_id)
                if not session:
                    session = create_session(scheme_id="demo_business_kyc", session_id=request.session_id)

                result = await run_agent_turn(session, request.message)

                tool_calls_pb = []
                for tc in result.get("tool_calls", []):
                    tool_calls_pb.append(agent_pb2.ToolCallInfo(
                        tool_name=tc.get("tool_name", ""),
                        json_arguments=json.dumps(tc.get("arguments", {})),
                        status=tc.get("validation", {}).get("status", ""),
                        message=tc.get("validation", {}).get("message", ""),
                        json_signal=json.dumps(tc.get("signal") or {})
                    ))

                return agent_pb2.RunTurnResponse(
                    success=True,
                    agent_response=result.get("agent_response", ""),
                    tool_calls=tool_calls_pb,
                    json_session_state=json.dumps(result.get("session_state", {})),
                    json_pending_confirmation=json.dumps(result.get("pending_confirmation") or {}),
                    json_internal_log=json.dumps(result.get("internal_log", []))
                )
            except Exception as e:
                logger.error(f"gRPC RunTurn error: {e}")
                return agent_pb2.RunTurnResponse(success=False, error=str(e))

        async def GetSessionState(self, request, context):
            try:
                session = get_session(request.session_id)
                if not session:
                    return agent_pb2.GetSessionStateResponse(success=False, error="Session not found")
                return agent_pb2.GetSessionStateResponse(
                    success=True,
                    json_session_state=json.dumps(session.to_dict())
                )
            except Exception as e:
                logger.error(f"gRPC GetSessionState error: {e}")
                return agent_pb2.GetSessionStateResponse(success=False, error=str(e))

        async def SyncExtractedData(self, request, context):
            try:
                session = get_session(request.session_id)
                if not session:
                    logger.error(f"SyncExtractedData failed: Session {request.session_id} not found.")
                    return agent_pb2.SyncExtractedDataResponse(success=False, error="Session not found")

                if request.json_extracted_fields:
                    try:
                        fields = json.loads(request.json_extracted_fields)
                        for k, v in fields.items():
                            existing = session.extracted_data.get(k)
                            if existing and existing.get("manually_overridden"):
                                logger.info(f"SyncExtractedData: Preserving manual override for field '{k}'")
                                continue
                            session.extracted_data[k] = v
                    except Exception as parse_err:
                        logger.error(f"Failed to parse json_extracted_fields: {parse_err}")

                if request.page_complete and request.doc_id and request.part_id:
                    session.mark_completed(request.doc_id, request.part_id)

                if request.all_complete:
                    session.mark_all_completed()

                from session import log_session_snapshot
                log_session_snapshot(session, f"Document Uploaded & Processed ({request.doc_id} — {request.part_id})")

                return agent_pb2.SyncExtractedDataResponse(
                    success=True,
                    json_session_state=json.dumps(session.to_dict())
                )
            except Exception as e:
                logger.error(f"gRPC SyncExtractedData error: {e}")
                return agent_pb2.SyncExtractedDataResponse(success=False, error=str(e))


async def serve_grpc():
    if not GRPC_AVAILABLE:
        logger.warning("gRPC stubs not generated. Skipping gRPC server.")
        return

    server = grpc.aio.server()
    agent_pb2_grpc.add_AgentServiceServicer_to_server(AgentServiceServicer(), server)
    listen_addr = f"0.0.0.0:{AGENT_GRPC_PORT}"
    server.add_insecure_port(listen_addr)
    logger.info(f"🚀 Agent gRPC Service listening on {listen_addr}")
    await server.start()
    await server.wait_for_termination()


async def main():
    import uvicorn
    # Run gRPC server in background task alongside FastAPI
    grpc_task = asyncio.create_task(serve_grpc())
    
    config = uvicorn.Config("server:app", host="0.0.0.0", port=AGENT_SERVICE_PORT, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()
    await grpc_task


if __name__ == "__main__":
    asyncio.run(main())
