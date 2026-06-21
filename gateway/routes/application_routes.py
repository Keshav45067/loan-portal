"""
Application Routes — CRUD, panchayat, financials, reports.

All endpoints require JWT auth (except health check).
All calls forward to App Orchestrator via gRPC.
"""

from fastapi import APIRouter, Request, Depends
from pydantic import BaseModel
from typing import Optional

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'shared'))
from log_utils.logger import get_logger, get_req_id

from middleware.jwt_auth import require_auth

from grpc_clients.generated import app_orchestrator_pb2

logger = get_logger("gateway")
router = APIRouter(prefix="/api/applications", tags=["applications"])


class SavePanchayatRequest(BaseModel):
    session_id: str
    panchayat: str = ""
    block: str = ""
    district: str = ""
    state: str = ""
    skip: bool = False
    cadre_id: str = ""
    rseti: str = ""


class SavePanchayatResponse(BaseModel):
    success: bool
    application_id: str = ""
    admin_found: bool = False
    rseti_approved: bool = False
    error: str = ""


class FinancialCalcRequest(BaseModel):
    application_id: str
    scheme_id: str
    business_type: str = ""


class ReportRequest(BaseModel):
    application_id: str
    format: str = "csv"
    scheme_id: str = ""


@router.post("/save-panchayat", response_model=SavePanchayatResponse)
async def save_panchayat(body: SavePanchayatRequest, request: Request,
                         auth: dict = Depends(require_auth)):
    """
    Save panchayat selection and generate application_id.
    Forwards to App Orchestrator via gRPC.
    """
    req_id = request.state.req_id
    logger.info("Save panchayat",
                 req_id=req_id, session_id=body.session_id,
                 details={"panchayat": body.panchayat, "block": body.block})

    try:
        stub = request.app.state.orchestrator_stub
        response = await stub.SavePanchayat(
            app_orchestrator_pb2.SavePanchayatRequest(
                session_id=body.session_id,
                panchayat=body.panchayat,
                block=body.block,
                district=body.district,
                state=body.state,
                skip=body.skip,
                cadre_id=body.cadre_id,
                rseti=body.rseti,
            ),
            metadata=[("x-request-id", req_id)]
        )

        if not response.success:
            return SavePanchayatResponse(success=False, error=response.error)

        return SavePanchayatResponse(
            success=True,
            application_id=response.application_id,
            admin_found=response.admin_found,
            rseti_approved=response.rseti_approved,
        )

    except Exception as e:
        logger.error(f"Save panchayat failed: {e}", req_id=req_id, error=str(e))
        return SavePanchayatResponse(success=False, error=str(e))


@router.get("/{application_id}")
async def get_application(application_id: str, request: Request,
                          auth: dict = Depends(require_auth)):
    """Get application details and extracted data."""
    req_id = request.state.req_id
    logger.info("Get application", req_id=req_id, application_id=application_id)

    try:
        stub = request.app.state.orchestrator_stub
        
        # 1. Get Application Meta
        app_resp = await stub.GetApplication(
            app_orchestrator_pb2.AppIdRequest(application_id=application_id),
            metadata=[("x-request-id", req_id)]
        )
        
        if not app_resp.session_id:
            return {"error": "Application not found", "status": "NOT_FOUND"}

        # 2. Get Extracted Data
        extracted_resp = await stub.GetExtractedData(
            app_orchestrator_pb2.AppIdRequest(application_id=application_id),
            metadata=[("x-request-id", req_id)]
        )
        
        import json
        extracted_json = {}
        if extracted_resp.json_data:
            try:
                extracted_json = json.loads(extracted_resp.json_data)
            except Exception:
                pass

        # 3. Get Documents
        docs_list = []
        try:
            docs_resp = await stub.GetDocuments(
                app_orchestrator_pb2.AppIdRequest(application_id=application_id),
                metadata=[("x-request-id", req_id)]
            )
            for d in docs_resp.documents:
                docs_list.append({
                    "id": d.id,
                    "key": d.key,
                    "doc_type": d.doc_type,
                    "name": d.name
                })
        except Exception as doc_err:
            logger.error(f"Failed to fetch documents: {doc_err}", req_id=req_id)

        return {
            "application_id": app_resp.application_id,
            "session_id": app_resp.session_id,
            "scheme_id": app_resp.scheme_id,
            "stage": app_resp.stage,
            "completion_status": app_resp.completion_status,
            "phone": app_resp.phone,
            "panchayat": app_resp.panchayat,
            "extracted_data": extracted_json,
            "documents": docs_list
        }
    except Exception as e:
        logger.error(f"Get application failed: {e}", req_id=req_id)
        return {"error": str(e), "status": "ERROR"}


@router.post("/calculate-financials")
async def calculate_financials(body: FinancialCalcRequest, request: Request,
                                auth: dict = Depends(require_auth)):
    """Run financial calculations on extracted data."""
    req_id = request.state.req_id
    logger.info("Calculate financials",
                 req_id=req_id, application_id=body.application_id)

    # TODO: Call App Orchestrator gRPC
    return {"success": True, "derived_data": {}}


@router.post("/save-metadata")
async def save_metadata(body: dict, request: Request, auth: dict = Depends(require_auth)):
    """Save manual reviewed metadata directly to DB."""
    req_id = request.state.req_id
    session_id = body.get("session_id")
    fields = body.get("fields", {})
    logger.info("Save metadata manually", req_id=req_id, session_id=session_id)
    try:
        stub = request.app.state.orchestrator_stub
        import json
        response = await stub.UpsertExtractedData(
            app_orchestrator_pb2.UpsertDataRequest(
                application_id=session_id,
                source="manual",
                json_fields=json.dumps(fields)
            ),
            metadata=[("x-request-id", req_id)]
        )
        return {"success": response.success}
    except Exception as e:
        logger.error(f"Save metadata failed: {e}", req_id=req_id)
        return {"success": False, "error": str(e)}

