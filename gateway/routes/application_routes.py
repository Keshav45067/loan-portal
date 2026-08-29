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

from middleware.jwt_auth import require_auth, create_token

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
@router.get("/location-tree")
async def get_location_tree(level: str = "states", parent_id: str = "", request: Request = None):
    """Fetch dynamic location hierarchy (states, districts, blocks, panchayats)."""
    req_id = getattr(request.state, 'req_id', 'loc-req') if request else 'loc-req'
    try:
        stub = request.app.state.orchestrator_stub
        res = await stub.GetLocationTree(
            app_orchestrator_pb2.GetLocationTreeRequest(level=level, parent_id=parent_id),
            metadata=[("x-request-id", req_id)]
        )
        items = [{"id": item.id, "name": item.name, "parent_id": item.parent_id} for item in res.items]
        return {"success": True, "items": items}
    except Exception as e:
        logger.error(f"GetLocationTree failed: {e}", req_id=req_id)
        return {"success": False, "items": [], "error": str(e)}


class StartSchemeRequest(BaseModel):
    scheme_id: str
    name: Optional[str] = ""


@router.post("/start-scheme")
async def start_scheme(body: StartSchemeRequest, request: Request, auth: dict = Depends(require_auth)):
    """Create or load isolated scheme application session."""
    req_id = request.state.req_id
    phone = auth.get("phone", "")
    session_id = auth.get("session_id", "")
    logger.info("Start scheme application", req_id=req_id, scheme_id=body.scheme_id, phone=phone)
    try:
        stub = request.app.state.orchestrator_stub
        app_resp = await stub.CreateApplication(
            app_orchestrator_pb2.CreateAppRequest(
                scheme_id=body.scheme_id,
                phone=phone,
                name=body.name or "",
                session_id=session_id
            ),
            metadata=[("x-request-id", req_id)]
        )
        if not app_resp.session_id:
            return {"success": False, "error": "Failed to initialize scheme session"}
        
        app_token = create_token(
            session_id=app_resp.session_id,
            phone=phone,
            extra={"scheme_id": app_resp.scheme_id}
        )

        return {
            "success": True,
            "token": app_token,
            "session_id": app_resp.session_id,
            "application_id": app_resp.application_id or app_resp.session_id,
            "scheme_id": app_resp.scheme_id,
            "stage": app_resp.stage,
            "completion_status": app_resp.completion_status
        }
    except Exception as e:
        logger.error(f"Start scheme failed: {e}", req_id=req_id)
        return {"success": False, "error": str(e)}


@router.get("/my-applications")
async def get_my_applications(request: Request, auth: dict = Depends(require_auth)):
    """Fetch all user applications across multiple schemes."""
    req_id = request.state.req_id
    session_id = auth.get("session_id")
    phone = auth.get("phone", "")
    try:
        stub = request.app.state.orchestrator_stub
        import json
        
        # 1. Fetch all applications for user's phone
        list_resp = await stub.ListApplications(
            app_orchestrator_pb2.ListAppRequest(limit=100, offset=0),
            metadata=[("x-request-id", req_id)]
        )
        
        applications = []
        for app in list_resp.applications:
            if phone and app.phone and app.phone != phone:
                continue
            
            # Fetch extracted data for this session
            ext_resp = await stub.GetExtractedData(
                app_orchestrator_pb2.AppIdRequest(application_id=app.session_id),
                metadata=[("x-request-id", req_id)]
            )
            extracted_json = {}
            if ext_resp.json_data:
                try:
                    extracted_json = json.loads(ext_resp.json_data)
                except Exception:
                    pass
            
            target_scheme = extracted_json.get("scheme_id") or app.scheme_id or "base-mudra"
            applications.append({
                "application_id": app.application_id or app.session_id,
                "session_id": app.session_id,
                "scheme_id": target_scheme,
                "stage": app.stage or "VOICE_QA",
                "completion_status": app.completion_status or extracted_json.get("completion_status", "IN_PROGRESS"),
                "phone": app.phone or phone,
                "panchayat": app.panchayat or extracted_json.get("panchayat", ""),
                "state": extracted_json.get("state", ""),
                "district": extracted_json.get("district", ""),
                "onboarding_finished": extracted_json.get("onboarding_finished", False),
                "created_at": app.created_at or extracted_json.get("created_at", ""),
                "extracted_data": extracted_json
            })
            
        return {"success": True, "applications": applications}
    except Exception as e:
        logger.error(f"Get my applications failed: {e}", req_id=req_id)
        return {"success": False, "applications": [], "error": str(e)}


def load_scheme_form_schema(scheme_id: str) -> dict:
    try:
        import yaml
        base_dir = os.getenv(
            "CONFIG_REGISTRY_DIR",
            os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "config-registry", "configs"))
        )
        if not os.path.exists(base_dir):
            for alt in [
                os.path.abspath("config-registry/configs"),
                os.path.abspath("services/config-registry/configs"),
                "/var/www/augmen/testing-services/config-registry/configs"
            ]:
                if os.path.exists(alt):
                    base_dir = alt
                    break

        clean_id = (scheme_id or "").lower().strip()
        candidates = [
            f"{clean_id}.yaml",
            f"base-{clean_id}.yaml",
            "base-pmfme.yaml" if "pmfme" in clean_id else "base-mudra.yaml"
        ]
        for cand in candidates:
            cand_path = os.path.join(base_dir, cand)
            if os.path.exists(cand_path):
                with open(cand_path, "r", encoding="utf-8") as f:
                    cfg = yaml.safe_load(f)
                    if cfg and "admin_portal" in cfg and "form_schema" in cfg["admin_portal"]:
                        return cfg["admin_portal"]["form_schema"]
    except Exception as e:
        logger.warning(f"Could not load form_schema for scheme {scheme_id}: {e}")
    return {}


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
            import hmac
            import hashlib
            import time
            from urllib.parse import quote
            from config import JWT_SECRET

            base_url = str(request.base_url).rstrip('/')

            for d in docs_resp.documents:
                # Build signed URL
                key = d.key
                expires_at = int(time.time()) + 3600  # 1 hour expiration
                msg = f"{key}:{expires_at}".encode('utf-8')
                signature = hmac.new(JWT_SECRET.encode('utf-8'), msg, hashlib.sha256).hexdigest()
                signed_url = f"{base_url}/api/documents/download?key={quote(key)}&expires={expires_at}&signature={signature}"

                docs_list.append({
                    "id": d.id,
                    "key": signed_url, # Frontend will render this signed_url directly
                    "doc_type": d.doc_type,
                    "name": d.name
                })
        except Exception as doc_err:
            logger.error(f"Failed to fetch documents: {doc_err}", req_id=req_id)

        form_schema = load_scheme_form_schema(app_resp.scheme_id)

        return {
            "application_id": app_resp.application_id,
            "session_id": app_resp.session_id,
            "scheme_id": app_resp.scheme_id,
            "stage": app_resp.stage,
            "completion_status": app_resp.completion_status,
            "phone": app_resp.phone,
            "panchayat": app_resp.panchayat,
            "extracted_data": extracted_json,
            "documents": docs_list,
            "form_schema": form_schema
        }
    except Exception as e:
        logger.error(f"Get application failed: {e}", req_id=req_id)
        return {"error": str(e), "status": "ERROR"}


@router.get("/scheme-schema/{scheme_id}")
async def get_scheme_form_schema(scheme_id: str, request: Request):
    """Fetch dynamic form_schema from config registry YAML."""
    form_schema = load_scheme_form_schema(scheme_id)
    return {"success": True, "scheme_id": scheme_id, "form_schema": form_schema}


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


@router.post("/trigger-evaluations")
async def trigger_evaluations(body: dict, request: Request):
    """Trigger background evaluations for a completed session."""
    req_id = request.state.req_id
    session_id = body.get("session_id")
    logger.info("Trigger background evaluations request", req_id=req_id, session_id=session_id)
    if not session_id:
        return {"success": False, "error": "session_id is required"}
    try:
        from grpc_clients.generated import app_orchestrator_pb2
        stub = request.app.state.orchestrator_stub
        import json
        await stub.UpsertExtractedData(
            app_orchestrator_pb2.UpsertDataRequest(
                application_id=session_id,
                source="manual",
                json_fields=json.dumps({"trigger_evaluations": True})
            ),
            metadata=[("x-request-id", req_id)]
        )
        return {"success": True}
    except Exception as e:
        logger.error(f"Trigger evaluations failed: {e}", req_id=req_id)
        return {"success": False, "error": str(e)}


