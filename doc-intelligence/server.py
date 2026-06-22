# Force IPv4 resolution to bypass macOS IPv6 network blackhole for external APIs
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
Doc Intelligence gRPC Server — document verification, OCR extraction, CIBIL checks.

v1: Delegates to LLM Service via gRPC for document verification and extraction.
Ports logic from loan-doc-scanner-final repository.
"""

import asyncio
import signal
import sys
import os
import json
import traceback

import grpc
from grpc import aio as grpc_aio

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'shared'))
from log_utils.logger import get_logger, extract_req_id, LatencyTracker

sys.path.insert(0, os.path.dirname(__file__))

from generated import doc_intelligence_pb2 as pb2
from generated import doc_intelligence_pb2_grpc as pb2_grpc
from generated import llm_pb2
from generated import llm_pb2_grpc
from generated import config_registry_pb2
from generated import config_registry_pb2_grpc
from config import DOC_INTELLIGENCE_PORT, LLM_SERVICE_ADDR, CONFIG_REGISTRY_ADDR, REDIS_URL, REDIS_TTL_SECONDS

from utils.prompts import (
    AADHAAR_PROMPT, AADHAAR_VERIFY_PROMPT,
    PAN_PROMPT, PAN_VERIFY_PROMPT,
    UDYAM_PROMPT, UDYAM_VERIFY_PROMPT,
    BANK_STATEMENT_PROMPT, BANK_STATEMENT_VERIFY_PROMPT,
    VOTER_PROMPT, VOTER_VERIFY_PROMPT
)
from utils.helpers import extract_json_clean, fill_nulls
from utils.response_builders import build_clean_response
from utils.cache import DocIntelCache

logger = get_logger("doc-intelligence")


class DocumentIntelligenceServicer(pb2_grpc.DocumentIntelligenceServicer):
    """gRPC servicer implementing the DocumentIntelligence service."""

    def __init__(self):
        self._llm_stub = None
        self._config_stub = None
        self._cache = None
        # TODO: Initialize GCS client for uploads

    async def VerifyDocument(self, request, context):
        """Verify a document image using LLM Service."""
        req_id = extract_req_id(context)
        logger.info("VerifyDocument called",
                     req_id=req_id,
                     document_type=request.document_type,
                     session_id=request.session_id,
                     details={"image_size": len(request.image_data)})

        try:
            # Determine verify prompt fallback
            doc_type = request.document_type.lower()
            prompt_text = ""
            target_key = ""
            fallback_prompt = ""
            
            if "aadhaar" in doc_type:
                target_key = "is_aadhaar"
                fallback_prompt = AADHAAR_VERIFY_PROMPT
            elif "pan" in doc_type:
                target_key = "is_pan"
                fallback_prompt = PAN_VERIFY_PROMPT
            elif "voter" in doc_type:
                target_key = "is_voterid"
                fallback_prompt = VOTER_VERIFY_PROMPT
            elif "udyam" in doc_type:
                target_key = "is_udyam"
                fallback_prompt = UDYAM_VERIFY_PROMPT
            elif "bank_statement" in doc_type or "bank" in doc_type:
                target_key = "is_bank_statement"
                fallback_prompt = BANK_STATEMENT_VERIFY_PROMPT
            elif "office_id" in doc_type or "company_id" in doc_type:
                from utils.prompts import OFFICE_ID_VERIFY_PROMPT
                target_key = "is_office_id"
                fallback_prompt = OFFICE_ID_VERIFY_PROMPT
            elif "address_proof" in doc_type or "correspondence" in doc_type:
                from utils.prompts import ADDRESS_PROOF_VERIFY_PROMPT
                target_key = "is_address_proof"
                fallback_prompt = ADDRESS_PROOF_VERIFY_PROMPT
            elif "selfie" in doc_type:
                logger.info("Selfie document verification bypassed successfully", req_id=req_id)
                return pb2.VerifyResponse(is_valid=True, confidence=1.0)
            else:
                target_key = "is_valid"
                fallback_prompt = ""

            # Check config registry / cache
            cached_req = None
            if request.scheme_id:
                cached_req = await self._cache.get_requirement(request.scheme_id, request.document_type)
                if not cached_req:
                    try:
                        logger.info("Fetching requirements from Config Registry", req_id=req_id, scheme_id=request.scheme_id)
                        resp = await self._config_stub.GetDocumentRequirements(
                            config_registry_pb2.SchemeRequest(scheme_id=request.scheme_id),
                            metadata=[("x-request-id", req_id)],
                            timeout=5
                        )
                        for doc_req in resp.documents:
                            req_dict = {
                                "document_type": doc_req.document_type,
                                "verify_prompt": doc_req.verify_prompt,
                                "extract_prompt": doc_req.extract_prompt,
                                "required": doc_req.required,
                                "max_pages": doc_req.max_pages,
                                "schema_json": doc_req.schema_json
                            }
                            await self._cache.set_requirement(request.scheme_id, doc_req.document_type, req_dict)
                            if doc_req.document_type == request.document_type:
                                cached_req = req_dict
                    except Exception as config_err:
                        logger.warning("Failed to fetch requirements from Config Registry", req_id=req_id, error=str(config_err))

            # Select prompt
            if cached_req and cached_req.get("verify_prompt"):
                prompt_text = cached_req["verify_prompt"]
            else:
                prompt_text = fallback_prompt

            if not prompt_text:
                if not request.scheme_id:
                    logger.warning(f"Unrecognized document type for verification: {request.document_type}")
                return pb2.VerifyResponse(is_valid=True, confidence=1.0)

            from PIL import Image
            import io
            from utils.prompts import preprocess_for_model

            # Preprocess image for model input
            try:
                img = Image.open(io.BytesIO(request.image_data)).convert("RGB")
                preprocessed_img = preprocess_for_model(img)
                buf = io.BytesIO()
                preprocessed_img.save(buf, format="JPEG", quality=85)
                processed_image_bytes = buf.getvalue()
            except Exception as img_err:
                logger.warning("Failed to preprocess image for verification, using raw bytes", 
                               req_id=req_id, error=str(img_err))
                processed_image_bytes = request.image_data

            # Call LLM Service GenerateMultimodal
            llm_req = llm_pb2.MultimodalRequest(
                prompt=prompt_text,
                images=[processed_image_bytes],
                model="gemini-2.5-flash",
                temperature=0.0
            )
            llm_resp = await self._llm_stub.GenerateMultimodal(
                llm_req,
                metadata=[("x-request-id", req_id)]
            )
            parsed, _ = extract_json_clean(llm_resp.text)
            
            if parsed is None:
                logger.error("LLM verification output could not be parsed as JSON", req_id=req_id, raw_output=llm_resp.text)
                return pb2.VerifyResponse(is_valid=False, confidence=0.0, issues=["Model response was not valid JSON"])

            is_valid = False
            issues = []
            
            if target_key == "is_bank_statement":
                if parsed.get("is_bank_statement") is True:
                    sp = parsed.get("statement_period", {})
                    f_date = sp.get("from_date")
                    t_date = sp.get("to_date")
                    if f_date and t_date:
                        from utils.helpers import try_normalize_date
                        from datetime import datetime
                        f_norm = try_normalize_date(f_date)
                        t_norm = try_normalize_date(t_date)
                        if f_norm and t_norm:
                            try:
                                d1 = datetime.strptime(f_norm, "%d-%m-%Y")
                                d2 = datetime.strptime(t_norm, "%d-%m-%Y")
                                delta = (d2 - d1).days
                                if delta >= 170:
                                    is_valid = True
                                else:
                                    issues.append(f"Statement period too short ({delta} days). Minimum 170 days required.")
                            except Exception as e:
                                issues.append(f"Date parsing error: {e}")
                        else:
                            issues.append("Could not normalize statement dates.")
                    else:
                        issues.append("Missing statement period dates.")
                else:
                    issues.append("Document not recognized as a bank statement.")
            else:
                is_valid = parsed.get(target_key) is True or parsed.get("is_" + doc_type) is True or parsed.get(doc_type) is True
                if not is_valid:
                    issues.append(f"Document not recognized as {request.document_type}.")

            return pb2.VerifyResponse(
                is_valid=is_valid,
                confidence=1.0 if is_valid else 0.0,
                issues=issues
            )

        except Exception as e:
            logger.error(f"VerifyDocument failed: {e}",
                         req_id=req_id, error=traceback.format_exc())
            return pb2.VerifyResponse(is_valid=False, confidence=0.0,
                                       issues=[str(e)])

    async def ExtractDocument(self, request, context):
        """Extract structured data from document using LLM Service."""
        req_id = extract_req_id(context)
        logger.info("ExtractDocument called",
                     req_id=req_id,
                     document_type=request.document_type,
                     session_id=request.session_id,
                     details={"image_size": len(request.image_data)})

        try:
            doc_type = request.document_type.lower()
            prompt_text = ""
            schema_key = ""
            fallback_prompt = ""
            
            if "aadhaar" in doc_type:
                fallback_prompt = AADHAAR_PROMPT
                schema_key = "aadhaar_back" if "back" in doc_type else "aadhaar_front"
            elif "pan" in doc_type:
                fallback_prompt = PAN_PROMPT
                schema_key = "pan"
            elif "voter" in doc_type:
                fallback_prompt = VOTER_PROMPT
                schema_key = "voter_back" if "back" in doc_type else "voter_front"
            elif "udyam" in doc_type:
                fallback_prompt = UDYAM_PROMPT
                schema_key = "udyam"
            elif "bank" in doc_type:
                fallback_prompt = BANK_STATEMENT_PROMPT
                schema_key = "bank_statement"
            elif "office_id" in doc_type or "company_id" in doc_type:
                from utils.prompts import OFFICE_ID_PROMPT
                fallback_prompt = OFFICE_ID_PROMPT
                schema_key = "office_id"
            elif "address_proof" in doc_type or "correspondence" in doc_type:
                from utils.prompts import ADDRESS_PROOF_PROMPT
                fallback_prompt = ADDRESS_PROOF_PROMPT
                schema_key = "address_proof"
            elif "selfie" in doc_type:
                return pb2.ExtractDocResponse(success=True, json_data="{}")
            else:
                fallback_prompt = ""
                schema_key = "custom"

            # Check config registry / cache
            cached_req = None
            if request.scheme_id:
                cached_req = await self._cache.get_requirement(request.scheme_id, request.document_type)
                if not cached_req:
                    try:
                        logger.info("Fetching requirements from Config Registry", req_id=req_id, scheme_id=request.scheme_id)
                        resp = await self._config_stub.GetDocumentRequirements(
                            config_registry_pb2.SchemeRequest(scheme_id=request.scheme_id),
                            metadata=[("x-request-id", req_id)],
                            timeout=5
                        )
                        for doc_req in resp.documents:
                            req_dict = {
                                "document_type": doc_req.document_type,
                                "verify_prompt": doc_req.verify_prompt,
                                "extract_prompt": doc_req.extract_prompt,
                                "required": doc_req.required,
                                "max_pages": doc_req.max_pages,
                                "schema_json": doc_req.schema_json
                            }
                            await self._cache.set_requirement(request.scheme_id, doc_req.document_type, req_dict)
                            if doc_req.document_type == request.document_type:
                                cached_req = req_dict
                    except Exception as config_err:
                        logger.warning("Failed to fetch requirements from Config Registry", req_id=req_id, error=str(config_err))

            # Select prompt
            if cached_req and cached_req.get("extract_prompt"):
                prompt_text = cached_req["extract_prompt"]
            else:
                prompt_text = fallback_prompt

            if not prompt_text:
                return pb2.ExtractDocResponse(success=False, error=f"Unknown document type {request.document_type}")

            # Parse custom schema if provided
            custom_schema = None
            if cached_req and cached_req.get("schema_json"):
                try:
                    custom_schema = json.loads(cached_req["schema_json"])
                except Exception as parse_err:
                    logger.warning("Failed to parse dynamic schema JSON", req_id=req_id, error=str(parse_err))

            from PIL import Image
            import io
            from utils.prompts import preprocess_for_model

            # Preprocess image for model input
            try:
                img = Image.open(io.BytesIO(request.image_data)).convert("RGB")
                preprocessed_img = preprocess_for_model(img)
                buf = io.BytesIO()
                preprocessed_img.save(buf, format="JPEG", quality=85)
                processed_image_bytes = buf.getvalue()
            except Exception as img_err:
                logger.warning("Failed to preprocess image for extraction, using raw bytes", 
                               req_id=req_id, error=str(img_err))
                processed_image_bytes = request.image_data

            # Call LLM Service GenerateMultimodal
            llm_req = llm_pb2.MultimodalRequest(
                prompt=prompt_text,
                images=[processed_image_bytes],
                model="gemini-2.5-flash",
                temperature=0.0
            )
            llm_resp = await self._llm_stub.GenerateMultimodal(
                llm_req,
                metadata=[("x-request-id", req_id)]
            )
            parsed, raw_clean = extract_json_clean(llm_resp.text)
            if parsed is None:
                logger.error("LLM extraction output could not be parsed as JSON", req_id=req_id, raw_output=llm_resp.text)
                return pb2.ExtractDocResponse(
                    success=False,
                    error="LLM extraction failed to return valid JSON",
                    raw_llm_output=llm_resp.text
                )

            # Clean and format response
            cleaned = build_clean_response(parsed, schema_key)
            if custom_schema:
                fill_nulls(cleaned, custom_schema)

            # Strict validation
            is_valid_doc = True
            missing_fields = []

            if schema_key == "aadhaar_front":
                if not cleaned.get("is_aadhaar"):
                    is_valid_doc = False
                else:
                    if not cleaned.get("aadhaar_number") or len(str(cleaned.get("aadhaar_number"))) < 12:
                        missing_fields.append("aadhaar_number")
                    holder = cleaned.get("holder", {})
                    if not holder.get("full_name") or len(str(holder.get("full_name")).strip()) < 2:
                        missing_fields.append("full_name")
                    if not holder.get("date_of_birth") and not holder.get("year_of_birth"):
                        missing_fields.append("date_of_birth/year_of_birth")
                    if not holder.get("gender"):
                        missing_fields.append("gender")
            
            elif schema_key == "aadhaar_back":
                if not cleaned.get("is_aadhaar"):
                    is_valid_doc = False
                else:
                    addr = cleaned.get("address", {})
                    if not addr.get("pincode") and not addr.get("state"):
                        missing_fields.append("resident_address (pincode or state missing)")
            
            elif schema_key == "pan":
                if not cleaned.get("is_pan"):
                    is_valid_doc = False
                else:
                    if not cleaned.get("pan_number") or len(str(cleaned.get("pan_number"))) < 10:
                        missing_fields.append("pan_number")
                    holder = cleaned.get("holder", {})
                    if not holder.get("full_name") or len(str(holder.get("full_name")).strip()) < 2:
                        missing_fields.append("full_name")
            
            elif schema_key == "udyam":
                if not cleaned.get("is_udyam"):
                    is_valid_doc = False
                else:
                    if not cleaned.get("udyam_number") or len(str(cleaned.get("udyam_number"))) < 5:
                        missing_fields.append("udyam_number")
                    ent = cleaned.get("enterprise", {})
                    if not ent.get("enterprise_name") or len(str(ent.get("enterprise_name")).strip()) < 2:
                        missing_fields.append("enterprise_name")
                    if not ent.get("social_category"):
                        missing_fields.append("social_category")
                    reg = cleaned.get("registration", {})
                    if not reg.get("date_of_registration") and not reg.get("date_of_commencement"):
                        missing_fields.append("date_of_commencement/registration")
                    biz_addr = cleaned.get("business_address", {})
                    if not biz_addr.get("state"):
                        missing_fields.append("state")
                    if not biz_addr.get("district"):
                        missing_fields.append("district")
                    if not biz_addr.get("pincode"):
                        missing_fields.append("pin_code")

            elif schema_key == "bank_statement":
                if not cleaned.get("is_bank_statement"):
                    is_valid_doc = False
                else:
                    acc = cleaned.get("account_details", {})
                    if not acc.get("account_number"):
                        missing_fields.append("account_number")
                    if not acc.get("bank_name"):
                        missing_fields.append("bank_name")
                    if not acc.get("ifsc_code"):
                        missing_fields.append("ifsc_code")

            elif schema_key == "office_id":
                if not cleaned.get("is_office_id"):
                    is_valid_doc = False
                else:
                    if not cleaned.get("organization_name"):
                        missing_fields.append("organization_name")

            elif schema_key == "address_proof":
                if not cleaned.get("is_address_proof"):
                    is_valid_doc = False
                else:
                    addr = cleaned.get("address", {})
                    if not addr.get("pincode") and not addr.get("state"):
                        missing_fields.append("address (pincode or state missing)")

            if not is_valid_doc:
                readable_names = {
                    "aadhaar_front": "Aadhaar Card Front",
                    "aadhaar_back": "Aadhaar Card Back",
                    "pan": "PAN Card",
                    "udyam": "Udyam Certificate",
                    "bank_statement": "Bank Statement",
                    "office_id": "Office ID / Employee ID",
                    "address_proof": "Address Proof Document"
                }
                readable_name = readable_names.get(schema_key, "requested document")
                return pb2.ExtractDocResponse(
                    success=False,
                    error=f"This does not appear to be a valid {readable_name}. Please upload a clear image of the correct document.",
                    raw_llm_output=llm_resp.text
                )
            elif missing_fields:
                error_msg = f"The image is blurred or cropped. Could not extract required fields: {', '.join(missing_fields)}. Please take a clearer photo."
                return pb2.ExtractDocResponse(
                    success=False,
                    error=error_msg,
                    raw_llm_output=llm_resp.text
                )

            return pb2.ExtractDocResponse(
                success=True,
                json_data=json.dumps(cleaned, ensure_ascii=False),
                raw_llm_output=llm_resp.text
            )

        except Exception as e:
            logger.error(f"ExtractDocument failed: {e}",
                         req_id=req_id, error=traceback.format_exc())
            return pb2.ExtractDocResponse(success=False, error=str(e))

    async def ClassifyBusiness(self, request, context):
        """Classify business category from description using LLM."""
        req_id = extract_req_id(context)
        logger.info("ClassifyBusiness called", req_id=req_id,
                     details={"purpose": request.business_purpose[:100]})

        try:
            # TODO: Call LLM Service with classification prompt
            return pb2.ClassifyResponse(category="GROCERY", confidence=0.8)
        except Exception as e:
            logger.error(f"ClassifyBusiness failed: {e}", req_id=req_id)
            return pb2.ClassifyResponse(category="", confidence=0.0)

    async def CheckCibil(self, request, context):
        """CIBIL credit check via Surepass Experian API."""
        req_id = extract_req_id(context)
        logger.info("CheckCibil called", req_id=req_id,
                     session_id=request.session_id,
                     details={"pan_type": request.pan_type})

        try:
            # TODO: Call Surepass Experian API
            return pb2.CibilResponse(success=True, credit_score=0)
        except Exception as e:
            logger.error(f"CheckCibil failed: {e}", req_id=req_id)
            return pb2.CibilResponse(success=False, error=str(e))

    async def ScoreActivity(self, request, context):
        """Activity score from business photos using LLM."""
        req_id = extract_req_id(context)
        logger.info("ScoreActivity called", req_id=req_id,
                     session_id=request.session_id,
                     details={"num_images": len(request.images)})

        try:
            # TODO: Call LLM Service GenerateMultimodal
            return pb2.ActivityScoreResponse(
                success=True,
                json_result=json.dumps({"activity_score": 0, "reasoning": ""}),
            )
        except Exception as e:
            logger.error(f"ScoreActivity failed: {e}", req_id=req_id)
            return pb2.ActivityScoreResponse(success=False, error=str(e))

    async def UploadDocument(self, request, context):
        """Upload document image to GCS."""
        req_id = extract_req_id(context)
        logger.info("UploadDocument called", req_id=req_id,
                     session_id=request.session_id,
                     document_type=request.document_type,
                     details={"file_size": len(request.image_data)})

        try:
            # TODO: Upload to GCS
            return pb2.UploadResponse(success=True, gcs_uri="gs://placeholder")
        except Exception as e:
            logger.error(f"UploadDocument failed: {e}", req_id=req_id)
            return pb2.UploadResponse(success=False, error=str(e))


async def serve():
    """Start the Doc Intelligence gRPC server."""
    server = grpc_aio.server(
        options=[
            ("grpc.max_send_message_length", 100 * 1024 * 1024),  # 100MB for images
            ("grpc.max_receive_message_length", 100 * 1024 * 1024),
        ]
    )

    servicer = DocumentIntelligenceServicer()

    # Initialize Cache
    cache = DocIntelCache(REDIS_URL, REDIS_TTL_SECONDS)
    await cache.connect()
    servicer._cache = cache

    # Initialize gRPC client stubs
    llm_channel = grpc.aio.insecure_channel(LLM_SERVICE_ADDR)
    servicer._llm_stub = llm_pb2_grpc.LanguageModelStub(llm_channel)

    config_channel = grpc.aio.insecure_channel(CONFIG_REGISTRY_ADDR)
    servicer._config_stub = config_registry_pb2_grpc.ConfigRegistryStub(config_channel)

    pb2_grpc.add_DocumentIntelligenceServicer_to_server(servicer, server)

    listen_addr = f"[::]:{DOC_INTELLIGENCE_PORT}"
    server.add_insecure_port(listen_addr)

    logger.info(f"Doc Intelligence starting on {listen_addr}",
                details={"port": DOC_INTELLIGENCE_PORT,
                         "redis": cache._available})

    await server.start()
    logger.info("Doc Intelligence ready ✅")

    async def shutdown(sig):
        logger.info(f"Received {sig.name}, shutting down...")
        await server.stop(grace=5)
        await cache.close()

    loop = asyncio.get_event_loop()
    for sig_name in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig_name, lambda s=sig_name: asyncio.create_task(shutdown(s)))

    await server.wait_for_termination()


if __name__ == "__main__":
    asyncio.run(serve())
