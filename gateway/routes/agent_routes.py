"""
Agent Routes — API Gateway proxy routes to the Agent Service.
Forwards /api/agent/* requests to the agent-service microservice.
"""

import httpx
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
from typing import Optional

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'shared'))
from log_utils.logger import get_logger

from config import AGENT_SERVICE_ADDR

logger = get_logger("gateway")
router = APIRouter(tags=["agent"])

AGENT_BASE_URL = f"http://{AGENT_SERVICE_ADDR}"


# ─── Request Models ───

class AgentInitRequest(BaseModel):
    scheme_id: str = "sandbox-demo"

class AgentChatRequest(BaseModel):
    session_id: str
    message: str


# ─── Proxy Endpoints ───

@router.post("/api/agent/init")
async def agent_init(body: AgentInitRequest, request: Request):
    """Proxy session init to agent service."""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{AGENT_BASE_URL}/init",
                json=body.model_dump(),
            )
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPStatusError as e:
        logger.error(f"Agent init failed: {e.response.status_code} — {e.response.text}")
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text)
    except Exception as e:
        logger.error(f"Agent init error: {e}")
        raise HTTPException(status_code=502, detail=f"Agent service unavailable: {str(e)}")


@router.post("/api/agent/chat")
async def agent_chat(body: AgentChatRequest, request: Request):
    """Proxy chat message to agent service."""
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{AGENT_BASE_URL}/chat",
                json=body.model_dump(),
            )
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPStatusError as e:
        logger.error(f"Agent chat failed: {e.response.status_code} — {e.response.text}")
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text)
    except Exception as e:
        logger.error(f"Agent chat error: {e}")
        raise HTTPException(status_code=502, detail=f"Agent service unavailable: {str(e)}")


@router.get("/api/agent/session/{session_id}")
async def agent_session(session_id: str, request: Request):
    """Proxy session state query to agent service."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{AGENT_BASE_URL}/session/{session_id}")
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text)
    except Exception as e:
        logger.error(f"Agent session error: {e}")
        raise HTTPException(status_code=502, detail=f"Agent service unavailable: {str(e)}")
