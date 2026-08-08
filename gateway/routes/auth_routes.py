"""
Auth Routes — OTP send/verify, session creation, token generation.

These are the only unauthenticated REST endpoints.
After OTP verification, the client receives a JWT token for subsequent requests.
"""

from fastapi import APIRouter, Request
from pydantic import BaseModel

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'shared'))
from log_utils.logger import get_logger, get_req_id

from middleware.jwt_auth import create_token

from grpc_clients.generated import app_orchestrator_pb2

logger = get_logger("gateway")
router = APIRouter(prefix="/api/auth", tags=["auth"])


class SendOtpRequest(BaseModel):
    phone: str


class VerifyOtpRequest(BaseModel):
    phone: str
    otp: str
    rseti: str = ""


class SendOtpResponse(BaseModel):
    success: bool
    error: str = ""


class VerifyOtpResponse(BaseModel):
    success: bool
    session_id: str = ""
    token: str = ""
    requires_panchayat: bool = True
    registration_completed: bool = False
    error: str = ""


@router.post("/send-otp", response_model=SendOtpResponse)
async def send_otp(body: SendOtpRequest, request: Request):
    """
    Send OTP to user's phone.
    Forwards to App Orchestrator via gRPC.
    """
    req_id = request.state.req_id
    logger.info("Send OTP request", req_id=req_id, details={"phone": body.phone[-4:]})

    try:
        stub = request.app.state.orchestrator_stub
        response = await stub.SendOtp(
            app_orchestrator_pb2.SendOtpRequest(phone=body.phone),
            metadata=[("x-request-id", req_id)]
        )

        if not response.success:
            return SendOtpResponse(success=False, error=response.error)

        return SendOtpResponse(success=True)

    except Exception as e:
        logger.error(f"Send OTP failed: {e}", req_id=req_id, error=str(e))
        return SendOtpResponse(success=False, error=str(e))


@router.post("/verify-otp", response_model=VerifyOtpResponse)
async def verify_otp(body: VerifyOtpRequest, request: Request):
    """
    Verify OTP and return JWT token + session_id.
    After this, all subsequent requests must include the JWT.
    """
    req_id = request.state.req_id
    logger.info("Verify OTP request", req_id=req_id, details={"phone": body.phone[-4:]})

    try:
        stub = request.app.state.orchestrator_stub
        response = await stub.VerifyOtp(
            app_orchestrator_pb2.VerifyOtpRequest(
                phone=body.phone,
                otp=body.otp,
                rseti=body.rseti,
            ),
            metadata=[("x-request-id", req_id)]
        )

        if not response.success:
            return VerifyOtpResponse(success=False, error=response.error)

        # Generate JWT token
        token = create_token(session_id=response.session_id, phone=body.phone)

        return VerifyOtpResponse(
            success=True,
            session_id=response.session_id,
            token=token,
            requires_panchayat=response.requires_panchayat,
            registration_completed=getattr(response, "registration_completed", False),
        )

    except Exception as e:
        logger.error(f"Verify OTP failed: {e}", req_id=req_id, error=str(e))
        return VerifyOtpResponse(success=False, error=str(e))


@router.get("/test-token")
async def get_test_token():
    """
    Generate a mock JWT token and session ID for testing (/test-va).
    """
    import uuid
    session_id = str(uuid.uuid4())
    token = create_token(session_id=session_id, phone="9999999999")
    return {"token": token, "session_id": session_id}

