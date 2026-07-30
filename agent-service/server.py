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
Agent Service — FastAPI server for the document capture agent.

Endpoints:
  POST /init     — Create a new agent session with mock data
  POST /chat     — Send a message and get agent response with tool calls
  GET  /session   — Get current session state
  GET  /health   — Health check
"""

import asyncio
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional

from config import AGENT_SERVICE_PORT
from session import create_session, get_session
from agent import run_agent_turn

# ─── FastAPI App ───

app = FastAPI(
    title="Augmen Agent Service",
    description="Agentic Document Capture Co-Pilot — Gemini Function Calling",
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
    return {"status": "healthy", "service": "agent-service", "version": "0.1.0"}


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
        raise HTTPException(status_code=404, detail="Session not found")

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


# ─── Entry Point ───

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=AGENT_SERVICE_PORT,
        reload=True,
        log_level="info",
    )
