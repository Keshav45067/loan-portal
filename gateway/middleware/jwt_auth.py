"""
Lightweight JWT Auth Middleware for the API Gateway.

Design decisions:
- For REST endpoints: validate JWT in the middleware before processing.
- For WebSocket (voice): DO NOT validate on upgrade (avoids latency).
  Instead, validate the token in the first WebSocket message.
- Generate req_id for every request and pass it to downstream gRPC services.
"""

import jwt
import time
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import Request, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from starlette.middleware.base import BaseHTTPMiddleware

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'shared'))
from log_utils.logger import get_logger, set_req_id, generate_req_id

from config import JWT_SECRET, JWT_ALGORITHM, JWT_EXPIRY_HOURS

logger = get_logger("gateway")
security = HTTPBearer(auto_error=False)


def create_token(session_id: str, phone: str = "", extra: dict = None) -> str:
    """
    Create a JWT token for a client session.

    Payload:
    - session_id: the user's session UUID
    - phone: user's phone (optional)
    - iat: issued at
    - exp: expiry
    """
    now = datetime.now(timezone.utc)
    payload = {
        "session_id": session_id,
        "phone": phone,
        "iat": now,
        "exp": now + timedelta(hours=JWT_EXPIRY_HOURS),
    }
    if extra:
        payload.update(extra)

    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def verify_token(token: str) -> Optional[dict]:
    """
    Verify and decode a JWT token.

    Returns the decoded payload or None if invalid.
    """
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        logger.warning("JWT expired")
        return None
    except jwt.InvalidTokenError as e:
        logger.warning(f"JWT invalid: {e}")
        return None


class RequestIDMiddleware(BaseHTTPMiddleware):
    """
    Middleware that:
    1. Generates a unique req_id for every incoming request
    2. Sets it in the context for downstream logging
    3. Adds it to response headers for client-side correlation
    """

    async def dispatch(self, request: Request, call_next):
        # Generate req_id
        req_id = request.headers.get("x-request-id", generate_req_id())
        set_req_id(req_id)

        # Store req_id on request state for route handlers
        request.state.req_id = req_id

        # Track timing
        start = time.perf_counter()

        response = await call_next(request)

        # Add req_id and latency to response headers
        latency_ms = round((time.perf_counter() - start) * 1000, 2)
        response.headers["x-request-id"] = req_id
        response.headers["x-latency-ms"] = str(latency_ms)

        logger.info(f"{request.method} {request.url.path}",
                     req_id=req_id,
                     method=request.method,
                     latency_ms=latency_ms,
                     details={"status": response.status_code,
                              "path": str(request.url.path)})

        return response


async def require_auth(request: Request) -> dict:
    """
    FastAPI dependency that validates JWT for REST endpoints.

    Usage:
        @router.get("/protected")
        async def protected(auth: dict = Depends(require_auth)):
            session_id = auth["session_id"]
    """
    credentials: HTTPAuthorizationCredentials = await security(request)
    if not credentials:
        raise HTTPException(status_code=401, detail="Missing authorization header")

    payload = verify_token(credentials.credentials)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    return payload


def verify_ws_token(token: str) -> Optional[dict]:
    """
    Verify token for WebSocket connections.
    Called on first message, NOT on upgrade, to avoid voice latency.
    """
    return verify_token(token)
