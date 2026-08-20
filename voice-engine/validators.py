"""
Node Validation Registry and Predefined Handlers.
Supports CIBIL check via Surepass Experian API, parameter mapping, and validation actions.
"""

import sys
import os
import re
import json
import asyncio
import traceback
import urllib.request
import urllib.error
from typing import Dict, Any, Tuple

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'shared'))
try:
    from log_utils.logger import get_logger
    logger = get_logger("voice-engine")
except ImportError:
    import logging
    logger = logging.getLogger("voice-engine")

SUREPASS_CREDIT_REPORT_URL = "https://kyc-api.surepass.io/api/v1/credit-report-experian/fetch-report"


def _get_surepass_token() -> str:
    return os.getenv("SUREPASS_API_TOKEN") or os.getenv("SUREPASS_API_KEY") or ""


def resolve_arguments(raw_args: dict, session) -> dict:
    """
    Resolve arguments dictionary.
    - Template strings with '{var_name}' are looked up in session extracted data using
      recursive flattening and schema extraction_mappings (matching GraphWalker._interpolate).
    - Literal strings and primitives without braces are passed as-is.
    """
    if not raw_args:
        return {}

    walker = getattr(session, "walker", None)
    extracted = (walker._extracted_data if (walker and hasattr(walker, "_extracted_data")) else {}) or {}
    scheme_config = (walker._scheme_config if (walker and hasattr(walker, "_scheme_config")) else {}) or {}
    extraction_mappings = scheme_config.get("extraction_mappings", {})

    # Flatten extracted data for key resolution
    flat = {}
    def recursive_flatten(d, prefix=""):
        if not isinstance(d, dict):
            return
        for k, v in d.items():
            full_key = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                recursive_flatten(v, full_key)
            elif v is not None and v != "":
                flat[full_key] = v
                if k not in flat or flat[k] is None or flat[k] == "":
                    flat[k] = v

    recursive_flatten(extracted)

    # Parse any string-serialized JSONs
    for k, v in list(flat.items()):
        if isinstance(v, str) and (v.startswith('{') or v.startswith('[')):
            try:
                parsed = json.loads(v)
                if isinstance(parsed, dict):
                    recursive_flatten(parsed, k)
            except Exception:
                pass

    # Gather session-level fallbacks
    session_metadata = {
        "phone": getattr(session, "phone", "") or str(flat.get("phone") or flat.get("applicant_phone") or flat.get("mobile") or ""),
        "registration_phone": getattr(session, "phone", "") or str(flat.get("phone") or flat.get("applicant_phone") or flat.get("mobile") or ""),
        "applicant_name": getattr(session, "applicant_name", "") or str(flat.get("applicant_name") or flat.get("doc_pan_name") or flat.get("name") or ""),
        "doc_pan_number": str(flat.get("doc_pan_number") or flat.get("pan") or flat.get("pan_number") or ""),
        "doc_pan_name": str(flat.get("doc_pan_name") or flat.get("applicant_name") or flat.get("name") or ""),
        "spouse_phone": str(flat.get("spouse_phone") or flat.get("spouse_contact_number") or flat.get("spouse_mobile") or ""),
        "doc_spouse_pan_number": str(flat.get("doc_spouse_pan_number") or flat.get("spouse_pan") or flat.get("spouse_pan_number") or ""),
        "doc_spouse_pan_name": str(flat.get("doc_spouse_pan_name") or flat.get("spouse_name") or ""),
    }
    for sm_k, sm_v in session_metadata.items():
        if sm_v and (sm_k not in flat or not flat[sm_k]):
            flat[sm_k] = sm_v

    resolved = {}
    for arg_name, arg_val in raw_args.items():
        if isinstance(arg_val, str):
            placeholders = re.findall(r"\{([^}]+)\}", arg_val)
            if placeholders:
                val = arg_val
                for ph in placeholders:
                    field_cfg = extraction_mappings.get(ph, {})
                    sources = field_cfg.get("sources", [ph]) if isinstance(field_cfg, dict) else [ph]
                    if ph in ("name", "applicant_name"):
                        name_fallbacks = ["applicant_name", "doc_aadhaar_name", "doc_pan_name", "doc_voter_name", "name", "full_name"]
                        for nf in name_fallbacks:
                            if nf not in sources:
                                sources.append(nf)
                    elif ph not in sources:
                        sources = list(sources) + [ph]

                    ph_val = ""
                    for src in sources:
                        candidate = flat.get(src)
                        if candidate is not None and str(candidate).strip():
                            ph_val = str(candidate).strip()
                            break

                    val = val.replace(f"{{{ph}}}", ph_val)
                resolved[arg_name] = val
            else:
                # Raw literal string (e.g. "applicant" or "spouse")
                resolved[arg_name] = arg_val
        else:
            # Primitive literal (e.g. 650 or True)
            resolved[arg_name] = arg_val

    return resolved


async def cibil_fetch(session, phone: str = "", pan: str = "", name: str = "", pan_type: str = "applicant", min_score: int = 650, **kwargs) -> Tuple[str, Dict[str, Any]]:
    """
    Fetch CIBIL credit score for applicant or spouse via Surepass Experian API.
    
    Returns:
        (status, details)
        status: "PASS" | "FAIL" | "ERROR"
    """
    phone_clean = str(phone or "").strip().replace(" ", "").replace("+91", "").replace("-", "")
    if phone_clean.startswith("91") and len(phone_clean) == 12:
        phone_clean = phone_clean[2:]

    pan_clean = str(pan or "").strip().upper()
    name_clean = str(name or "").strip()

    logger.info(f"Executing cibil_fetch: pan={pan_clean}, phone={phone_clean}, name={name_clean}, pan_type={pan_type}, min_score={min_score}",
                 session_id=getattr(session, "session_id", ""))

    if not phone_clean or not pan_clean:
        logger.warning(f"cibil_fetch missing required fields: phone='{phone_clean}', pan='{pan_clean}'")
        return "ERROR", {"error": "Missing phone or pan number"}

    if len(phone_clean) != 10:
        logger.warning(f"cibil_fetch: Invalid mobile number '{phone_clean}' (must be exactly 10 digits for Surepass CIBIL check). Skipping API call.",
                       session_id=getattr(session, "session_id", ""))
        return "ERROR", {"error": f"Invalid mobile number '{phone_clean}' (must be 10 digits)"}

    token = _get_surepass_token()
    if not token:
        logger.warning("cibil_fetch: SUREPASS_API_TOKEN not configured. Defaulting to PASS.")
        return "PASS", {"credit_score": 750, "mock": True}

    try:
        def _call_surepass():
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
                "User-Agent": "AugmenVoiceEngine/1.0"
            }
            payload = json.dumps({
                "name": name_clean or "Applicant",
                "consent": "Y",
                "mobile": phone_clean,
                "pan": pan_clean
            }).encode("utf-8")

            req = urllib.request.Request(
                SUREPASS_CREDIT_REPORT_URL,
                data=payload,
                headers=headers,
                method="POST"
            )
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    status_code = resp.getcode()
                    body = resp.read().decode("utf-8")
                    return status_code, body
            except urllib.error.HTTPError as http_err:
                body = http_err.read().decode("utf-8") if http_err.fp else str(http_err)
                return http_err.code, body
            except urllib.error.URLError as url_err:
                return 0, str(url_err.reason)

        status_code, body = await asyncio.to_thread(_call_surepass)

        if status_code != 200:
            logger.warning(f"Surepass API HTTP {status_code}: {body[:500]}")
            return "ERROR", {"error": f"HTTP {status_code}: {body[:500]}"}

        resp_json = json.loads(body)
        data = resp_json.get("data", {})
        credit_score_raw = data.get("credit_score")

        try:
            score_int = int(credit_score_raw)
        except (ValueError, TypeError):
            score_int = 0

        logger.info(f"CIBIL fetch completed: PAN={pan_clean}, score={score_int}, min_required={min_score}",
                     session_id=getattr(session, "session_id", ""))

        # Store CIBIL data in session extracted fields
        if session and hasattr(session, "walker") and session.walker:
            score_key = "cibil_score" if pan_type == "applicant" else f"{pan_type}_cibil_score"
            session.walker._extracted_data[score_key] = score_int
            session.walker._extracted_data[f"{pan_type}_cibil_score"] = score_int
            session.walker._extracted_data[f"{pan_type}_cibil_data"] = resp_json
            session.walker._extracted_data[f"{pan_type}_cibil_status"] = "PASS" if score_int >= int(min_score) else "FAIL"

        # Sync to orchestrator if available
        if session and getattr(session, "_orchestrator_stub", None):
            try:
                from generated import app_orchestrator_pb2
                score_key = "cibil_score" if pan_type == "applicant" else f"{pan_type}_cibil_score"
                await session._orchestrator_stub.UpsertExtractedData(
                    app_orchestrator_pb2.UpsertDataRequest(
                        application_id=session.session_id,
                        source=f"cibil-{pan_type}",
                        json_fields=json.dumps({
                            score_key: score_int,
                            f"{pan_type}_cibil_score": score_int,
                            f"{pan_type}_cibil_status": "PASS" if score_int >= int(min_score) else "FAIL"
                        })
                    )
                )
            except Exception as orch_err:
                logger.warning(f"Failed to sync CIBIL data to orchestrator: {orch_err}")

        if score_int >= int(min_score):
            return "PASS", {"credit_score": score_int, "pan": pan_clean, "pan_type": pan_type}
        else:
            logger.warning(f"🛑 Low CIBIL score for {pan_type}: {score_int} < {min_score}")
            if session and hasattr(session, "walker") and session.walker:
                session.walker._extracted_data["is_rejected_due_to_cibil"] = True
            return "FAIL", {"credit_score": score_int, "pan": pan_clean, "pan_type": pan_type, "min_score": min_score}

    except (TimeoutError, urllib.error.URLError) as timeout_err:
        logger.warning(f"Surepass API timeout/network error for PAN={pan_clean}: {timeout_err}")
        return "ERROR", {"error": f"API timeout or network error: {timeout_err}"}
    except Exception as e:
        logger.error(f"cibil_fetch exception: {e}", error=traceback.format_exc())
        return "ERROR", {"error": str(e)}


VALIDATOR_REGISTRY = {
    "cibil_fetch": cibil_fetch,
    "cibil_check": cibil_fetch,
}


async def execute_node_validation(validation_config: dict, session) -> Tuple[str, Dict[str, Any]]:
    """
    Execute validation for a node if configured.
    Returns (status, details) where status is "PASS", "FAIL", "ERROR", or "SKIPPED".
    """
    if not validation_config or not isinstance(validation_config, dict):
        return "SKIPPED", {}

    func_name = validation_config.get("function", "").strip()
    if not func_name:
        return "SKIPPED", {}

    validator_fn = VALIDATOR_REGISTRY.get(func_name)
    if not validator_fn:
        logger.warning(f"Validator function '{func_name}' not found in registry. Skipping.")
        return "SKIPPED", {"error": f"Unknown validator: {func_name}"}

    raw_args = validation_config.get("arguments", {})
    resolved_args = resolve_arguments(raw_args, session)

    logger.info(f"Running node validation '{func_name}' with resolved arguments: {resolved_args}",
                 session_id=getattr(session, "session_id", ""))

    try:
        status, details = await validator_fn(session=session, **resolved_args)
        logger.info(f"Node validation '{func_name}' result: status={status}, details={details}",
                     session_id=getattr(session, "session_id", ""))
        return status, details
    except Exception as e:
        logger.error(f"Error executing validator '{func_name}': {e}", error=traceback.format_exc())
        return "ERROR", {"error": str(e)}
