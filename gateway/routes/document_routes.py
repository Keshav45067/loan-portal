"""
Document Routes — verify, extract, upload documents.

All endpoints require JWT auth.
All calls forward to Document Intelligence Service via gRPC.
"""

from fastapi import APIRouter, Request, Depends, UploadFile, File, Form
from pydantic import BaseModel
from typing import Optional

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'shared'))
from log_utils.logger import get_logger

from middleware.jwt_auth import require_auth

from grpc_clients.generated import doc_intelligence_pb2

logger = get_logger("gateway")
router = APIRouter(prefix="/api/documents", tags=["documents"])


class VerifyResponse(BaseModel):
    is_valid: bool
    issues: list = []
    confidence: float = 0.0


class ExtractResponse(BaseModel):
    success: bool
    json_data: dict = {}
    gcs_path: str = ""
    error: str = ""


@router.post("/verify", response_model=VerifyResponse)
async def verify_document(
    request: Request,
    file: UploadFile = File(...),
    document_type: str = Form(...),
    scheme_id: str = Form(""),
    session_id: str = Form(""),
    auth: dict = Depends(require_auth),
):
    """
    Verify a document image (quality, correct type, readability).
    Forwards to Doc Intelligence via gRPC.
    """
    req_id = request.state.req_id
    image_bytes = await file.read()

    logger.info("Verify document",
                 req_id=req_id,
                 session_id=session_id,
                 document_type=document_type,
                 details={"file_size": len(image_bytes), "scheme_id": scheme_id})

    try:
        stub = request.app.state.doc_intel_stub
        response = await stub.VerifyDocument(
            doc_intelligence_pb2.VerifyRequest(
                image_data=image_bytes,
                document_type=document_type,
                scheme_id=scheme_id,
                session_id=session_id,
            ),
            metadata=[("x-request-id", req_id)]
        )

        return VerifyResponse(
            is_valid=response.is_valid,
            confidence=response.confidence,
            issues=list(response.issues),
        )

    except Exception as e:
        logger.error(f"Verify failed: {e}", req_id=req_id, error=str(e))
        return VerifyResponse(is_valid=False, issues=[str(e)])


@router.post("/extract", response_model=ExtractResponse)
async def extract_document(
    request: Request,
    file: UploadFile = File(...),
    document_type: str = Form(...),
    scheme_id: str = Form(""),
    session_id: str = Form(""),
    latitude: Optional[float] = Form(None),
    longitude: Optional[float] = Form(None),
    auth: dict = Depends(require_auth),
):
    """
    Extract structured data from document image.
    Forwards to Doc Intelligence via gRPC.
    """
    req_id = request.state.req_id
    image_bytes = await file.read()

    logger.info("Extract document",
                 req_id=req_id,
                 session_id=session_id,
                 document_type=document_type,
                 details={"file_size": len(image_bytes)})

    try:
        import json
        gcs_key = ""
        orch_stub = request.app.state.orchestrator_stub

        if document_type == "workplace_video":
            # Video bypass - directly upload to GCS and update DB metadata
            try:
                from services.gcs_service import upload_image_to_gcs
                content_type = file.content_type or "video/webm"
                gcs_key = upload_image_to_gcs(
                    image_bytes=image_bytes,
                    content_type=content_type,
                    session_id=session_id,
                    document_type=document_type,
                    filename=file.filename
                )
                logger.info(f"Uploaded workplace video to GCS: {gcs_key}", req_id=req_id)
            except Exception as write_err:
                logger.error(f"Failed to upload workplace video to GCS: {write_err}", req_id=req_id)
                return ExtractResponse(success=False, error=f"Upload to GCS failed: {str(write_err)}")

            try:
                from grpc_clients.generated import app_orchestrator_pb2
                # Upsert metadata fields
                await orch_stub.UpsertExtractedData(
                    app_orchestrator_pb2.UpsertDataRequest(
                        application_id=session_id,
                        source=document_type,
                        json_fields=json.dumps({
                            "workplace_video_gcs_key": gcs_key,
                            "latitude": latitude,
                            "longitude": longitude
                        }, ensure_ascii=False)
                    ),
                    metadata=[("x-request-id", req_id)]
                )
                
                # Save mapping to docs_test with JSON GPS metadata in name
                name_metadata = json.dumps({
                    "name": file.filename,
                    "latitude": latitude,
                    "longitude": longitude
                }, ensure_ascii=False)

                await orch_stub.SaveDocument(
                    app_orchestrator_pb2.SaveDocRequest(
                        session_id=session_id,
                        doc_type=document_type,
                        key=gcs_key,
                        name=name_metadata
                    ),
                    metadata=[("x-request-id", req_id)]
                )
                logger.info("Workplace video record saved to DB successfully", req_id=req_id)
            except Exception as db_err:
                logger.error(f"Failed to save video metadata: {db_err}", req_id=req_id)
                return ExtractResponse(success=False, error=f"Save metadata to DB failed: {str(db_err)}")

            return ExtractResponse(
                success=True,
                json_data={"gcs_key": gcs_key},
                gcs_path=gcs_key,
                error=""
            )

        stub = request.app.state.doc_intel_stub
        response = await stub.ExtractDocument(
            doc_intelligence_pb2.ExtractDocRequest(
                image_data=image_bytes,
                document_type=document_type,
                scheme_id=scheme_id,
                session_id=session_id,
            ),
            metadata=[("x-request-id", req_id)]
        )

        json_fields = {}
        if response.json_data:
            try:
                json_fields = json.loads(response.json_data)
            except Exception:
                pass

        if response.success:
            try:
                from services.gcs_service import upload_image_to_gcs
                content_type = file.content_type or "image/jpeg"
                gcs_key = upload_image_to_gcs(
                    image_bytes=image_bytes,
                    content_type=content_type,
                    session_id=session_id,
                    document_type=document_type,
                    filename=file.filename
                )
                logger.info(f"Saved document file to GCS: {gcs_key}", req_id=req_id)
            except Exception as write_err:
                logger.error(f"Failed to save document file to GCS: {write_err}", req_id=req_id)

        if response.success and response.json_data:
            try:
                from grpc_clients.generated import app_orchestrator_pb2
                await orch_stub.UpsertExtractedData(
                    app_orchestrator_pb2.UpsertDataRequest(
                        application_id=session_id,
                        source=document_type,
                        json_fields=response.json_data
                    ),
                    metadata=[("x-request-id", req_id)]
                )
                logger.info("Saved extracted fields to database via App Orchestrator", req_id=req_id, session_id=session_id)

                if gcs_key:
                    # Save document metadata mapping to docs table
                    await orch_stub.SaveDocument(
                        app_orchestrator_pb2.SaveDocRequest(
                            session_id=session_id,
                            doc_type=document_type,
                            key=gcs_key,
                            name=file.filename
                        ),
                        metadata=[("x-request-id", req_id)]
                    )
                    logger.info("Saved document mapping to docs table via App Orchestrator", req_id=req_id, session_id=session_id)
            except Exception as db_err:
                logger.error(f"Failed to save extracted data or doc to DB: {db_err}", req_id=req_id)

        return ExtractResponse(
            success=response.success,
            json_data=json_fields,
            gcs_path=response.gcs_path,
            error=response.error,
        )

    except Exception as e:
        logger.error(f"Extract failed: {e}", req_id=req_id, error=str(e))
        return ExtractResponse(success=False, error=str(e))

class PreviewResponse(BaseModel):
    success: bool
    url: str = ""
    error: str = ""

@router.get("/preview", response_model=PreviewResponse)
async def get_document_preview(key: str, request: Request):
    """Generate a proxy-signed URL for a given document key."""
    req_id = request.state.req_id
    logger.info(f"Generating preview URL for key: {key}", req_id=req_id)
    
    if not key:
        return PreviewResponse(success=False, error="Key is required")
        
    try:
        import hmac
        import hashlib
        import time
        from urllib.parse import quote
        from config import JWT_SECRET
        
        # 15 minutes expiration
        expires_at = int(time.time()) + 900
        
        # Generate signature
        msg = f"{key}:{expires_at}".encode('utf-8')
        signature = hmac.new(JWT_SECRET.encode('utf-8'), msg, hashlib.sha256).hexdigest()
        
        # Get base URL dynamically from request base_url
        base_url = str(request.base_url).rstrip('/')
        
        # Build signed preview URL
        url = f"{base_url}/api/documents/download?key={quote(key)}&expires={expires_at}&signature={signature}"
        
        return PreviewResponse(success=True, url=url)
    except Exception as e:
        logger.error(f"Failed to generate preview URL: {e}", req_id=req_id)
        return PreviewResponse(success=False, error=str(e))

from fastapi import Response, HTTPException

@router.get("/download")
async def download_document(
    key: str,
    expires: int,
    signature: str,
    request: Request
):
    """Securely download and serve document blob from GCS using signature verification."""
    req_id = request.state.req_id
    import time
    import hmac
    import hashlib
    from config import JWT_SECRET
    
    # 1. Verify expiration
    if expires < int(time.time()):
        raise HTTPException(status_code=403, detail="URL has expired")
        
    # 2. Verify signature
    msg = f"{key}:{expires}".encode('utf-8')
    expected_sig = hmac.new(JWT_SECRET.encode('utf-8'), msg, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_sig, signature):
        raise HTTPException(status_code=403, detail="Invalid signature")
        
    # 3. Download from GCS
    try:
        from services.gcs_service import download_blob_bytes
        data, content_type = download_blob_bytes(key)
        return Response(content=data, media_type=content_type)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Document not found")
    except Exception as e:
        logger.error(f"Download failed: {e}", req_id=req_id)
        raise HTTPException(status_code=500, detail=str(e))


