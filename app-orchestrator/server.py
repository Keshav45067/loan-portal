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
Application Orchestrator gRPC Server.

Manages the full loan application lifecycle:
Registration → Documentation → Interview → Financials → Report.
"""

import asyncio
import signal
import sys
import os
import json
import traceback
import random
import uuid
import datetime
import urllib.request
import urllib.parse
from contextlib import contextmanager

import grpc
from grpc import aio as grpc_aio

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'shared'))
from log_utils.logger import get_logger, extract_req_id, set_req_id, LatencyTracker

sys.path.insert(0, os.path.dirname(__file__))
import psycopg2
from psycopg2 import pool

from generated import app_orchestrator_pb2 as pb2
from generated import app_orchestrator_pb2_grpc as pb2_grpc
from config import APP_ORCHESTRATOR_PORT, DATABASE_URL

logger = get_logger("app-orchestrator")


@contextmanager
def get_db_cursor(db_pool):
    """Context manager to obtain a cursor from the connection pool with checkout validation."""
    conn = None
    is_broken = False
    
    # Try to checkout a healthy connection (up to 3 attempts)
    for attempt in range(3):
        try:
            conn = db_pool.getconn()
            if conn.closed:
                db_pool.putconn(conn, close=True)
                conn = None
                continue
            
            # Set autocommit to True before pinging to prevent implicit transaction start
            conn.autocommit = True

            # Ping the connection
            with conn.cursor() as ping_cur:
                ping_cur.execute("SELECT 1")
            
            # Connection is healthy, break checkout loop
            break
        except (psycopg2.OperationalError, psycopg2.InterfaceError) as ping_err:
            logger.warning(f"Connection ping failed on checkout attempt {attempt + 1}: {ping_err}. Discarding connection.")
            if conn:
                db_pool.putconn(conn, close=True)
                conn = None
    
    if not conn:
        raise psycopg2.OperationalError("Failed to obtain a healthy database connection after retries")

    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            yield cur
    except (psycopg2.OperationalError, psycopg2.InterfaceError) as e:
        is_broken = True
        logger.error(f"Database query encountered operational error: {e}. Discarding connection.")
        raise
    finally:
        if conn:
            # Clean up connection state before putting it back in the pool
            try:
                if not conn.closed and not conn.autocommit:
                    conn.rollback()
            except Exception as rollback_err:
                logger.warning(f"Failed to rollback leaked transaction: {rollback_err}")
                is_broken = True
            
            try:
                if not conn.closed:
                    conn.autocommit = True
            except Exception as autocommit_err:
                logger.warning(f"Failed to restore autocommit state: {autocommit_err}")
                is_broken = True
                
            db_pool.putconn(conn, close=is_broken)



# Helper to resolve scheme config using inheritance
def load_resolved_scheme_config(scheme_id: str) -> dict:
    import copy
    import yaml
    
    if scheme_id == 'a74b1b43-7cc6-4385-8a8c-12af64cddb2b':
        scheme_id = 'base-mudra'
        
    config_dir = "/Users/keshavgarg/Documents/augmen/services/config-registry/configs"
    
    # Load all raw configurations
    raw_configs = {}
    if not os.path.exists(config_dir):
        logger.warning(f"Config dir not found: {config_dir}")
        return {}

    for filename in os.listdir(config_dir):
        if not filename.endswith((".yaml", ".yml")):
            continue
        filepath = os.path.join(config_dir, filename)
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f)
            s_id = cfg.get("scheme_id")
            if s_id:
                raw_configs[s_id] = cfg
        except Exception:
            pass

    def deep_merge(dict1, dict2):
        res = copy.deepcopy(dict1)
        for k, v in dict2.items():
            if isinstance(v, dict) and k in res and isinstance(res[k], dict):
                res[k] = deep_merge(res[k], v)
            else:
                res[k] = copy.deepcopy(v)
        return res

    def resolve(s_id, resolved=None, resolving=None):
        if resolved is None:
            resolved = {}
        if resolving is None:
            resolving = set()
        if s_id in resolved:
            return resolved[s_id]
        if s_id in resolving:
            raise ValueError(f"Circular inheritance: {s_id}")
        resolving.add(s_id)
        cfg = raw_configs.get(s_id)
        if not cfg:
            raise ValueError(f"Scheme not found: {s_id}")
        parent_id = cfg.get("extends")
        if parent_id:
            parent_cfg = resolve(parent_id, resolved, resolving)
            merged = deep_merge(parent_cfg, cfg)
            merged.pop("extends", None)
            resolved[s_id] = merged
        else:
            resolved[s_id] = copy.deepcopy(cfg)
        resolving.remove(s_id)
        return resolved[s_id]

    try:
        return resolve(scheme_id)
    except Exception as e:
        logger.error(f"Error resolving scheme config inheritance for {scheme_id}: {e}")
        return {}


async def run_post_processing_evaluations(session_id: str, db_pool):
    """Run background LLM credit evaluations using scheme configuration pipelines."""
    logger.info("Starting background post-processing evaluations", session_id=session_id)
    try:
        # 1. Fetch user_data row
        user_data_json = {}
        phone = None
        with get_db_cursor(db_pool) as cur:
            cur.execute("SELECT data, phone FROM user_data WHERE id = %s", (session_id,))
            row = cur.fetchone()
            if not row:
                logger.error(f"Post-processing failed: Session {session_id} not found in user_data")
                return
            user_data_json = row[0] or {}
            phone = row[1]

        scheme_id = user_data_json.get("scheme_id")
        if not scheme_id:
            logger.warning(f"No scheme_id found for session {session_id}")
            return

        # 2. Load resolved scheme config
        config = load_resolved_scheme_config(scheme_id)
        if not config:
            logger.warning(f"Could not load resolved configuration for scheme {scheme_id}")
            return

        # Check if the scheme is mudra
        is_mudra_scheme = (
            "mudra" in str(scheme_id).lower() or 
            scheme_id == 'a74b1b43-7cc6-4385-8a8c-12af64cddb2b' or
            (config and "mudra" in str(config.get("scheme_id", "")).lower()) or
            (config and "mudra" in str(config.get("display_name", "")).lower())
        )

        # Fetch valid columns in mudra_user_data
        valid_cols = set()
        try:
            with get_db_cursor(db_pool) as cur:
                cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'mudra_user_data'")
                valid_cols = {r[0] for r in cur.fetchall()}
        except Exception as e:
            logger.warning(f"Could not read columns from mudra_user_data: {e}")

        # Gather all current data (both from user_data JSON and mudra_user_data columns)
        all_fields = {}
        if user_data_json:
            all_fields.update(user_data_json)
        if phone:
            all_fields["phone"] = phone
            all_fields["mobile_number"] = phone

        # Read current mudra_user_data row
        try:
            with get_db_cursor(db_pool) as cur:
                cur.execute("SELECT * FROM mudra_user_data WHERE user_id = %s", (session_id,))
                row = cur.fetchone()
                if row:
                    col_names = [desc[0] for desc in cur.description]
                    for name, val in zip(col_names, row):
                        if name in ("id", "user_id", "created_at", "updated_at"):
                            continue
                        if val is not None and val != "":
                            # Prevent database zero/null values from clobbering valid voice/GCS values
                            is_db_zero = str(val).strip() in ("0", "0.0", "None", "Null")
                            voice_val = all_fields.get(name)
                            is_voice_valid = voice_val is not None and str(voice_val).strip() not in ("0", "0.0", "Not Available", "NA", "")
                            
                            if is_db_zero and is_voice_valid:
                                continue
                            all_fields[name] = val
        except Exception as e:
            logger.warning(f"Could not read from mudra_user_data: {e}")

        db_mapping = config.get("db_mapping", {})

        # Translate keys using db_mapping
        mapped_fields = {}
        for k, v in all_fields.items():
            mapped_k = db_mapping.get(k, k)
            mapped_fields[mapped_k] = v
        all_fields.update(mapped_fields)

        # Re-populate/fallback field names
        applicant_name_val = all_fields.get("applicant_name")
        if not applicant_name_val or applicant_name_val == "Applicant":
            def get_nested(d, keys):
                for k in keys:
                    if isinstance(d, dict):
                        d = d.get(k)
                    elif isinstance(d, str):
                        try:
                            d = json.loads(d).get(k)
                        except:
                            return None
                    else:
                        return None
                return d

            # Extract AADHAAR_FRONT from extractions namespace first
            extractions = all_fields.get("extractions", {})
            if isinstance(extractions, str):
                try: extractions = json.loads(extractions)
                except: extractions = {}
            
            aadhaar_ext = extractions.get("AADHAAR_FRONT") or extractions.get("AADHAR_FRONT") or {}
            aadhaar_name = get_nested(aadhaar_ext, ["holder", "full_name"])
            
            holder_name = get_nested(all_fields, ["holder", "full_name"])
            pan_name = get_nested(extractions.get("PAN") or {}, ["holder", "full_name"])
            
            resolved_name = (
                aadhaar_name or
                holder_name or
                pan_name or
                all_fields.get("name") or
                all_fields.get("full_name") or
                "Applicant"
            )
            all_fields["applicant_name"] = resolved_name

        if "business_type" not in all_fields:
            all_fields["business_type"] = all_fields.get("type_of_business") or "other"

        # If mudra, run general financial calculations
        if is_mudra_scheme:
            logger.info("Running Mudra financial calculations in background", session_id=session_id)
            from calculations import calculate_derived_fields
            try:
                derived = calculate_derived_fields(all_fields)
                all_fields.update(derived)
                logger.info(f"Mudra financial calculations complete. Derived keys: {list(derived.keys())}")
            except Exception as calc_err:
                logger.error(f"Failed to run Mudra financial calculations: {calc_err}", exc_info=True)

        # Sync all fields to mudra_user_data dynamically
        if valid_cols:
            columns = ["user_id"]
            values = [session_id]
            placeholders = ["%s"]
            seen_cols = set()

            # Map all_fields keys to DB columns
            for k, v in all_fields.items():
                db_col = db_mapping.get(k, k)
                if db_col in valid_cols and db_col not in seen_cols and db_col not in ("created_at", "updated_at", "id"):
                    if v is not None and v != "":
                        columns.append(db_col)
                        values.append(str(v))
                        placeholders.append("%s")
                        seen_cols.add(db_col)

            if len(columns) > 1:
                update_clauses = [f"{c} = EXCLUDED.{c}" for c in columns if c != "user_id"]
                sql = f"""
                    INSERT INTO mudra_user_data (id, {', '.join(columns)}, created_at, updated_at)
                    VALUES (gen_random_uuid(), {', '.join(placeholders)}, NOW(), NOW())
                    ON CONFLICT (user_id) DO UPDATE SET
                        {', '.join(update_clauses)},
                        updated_at = NOW()
                """
                try:
                    with get_db_cursor(db_pool) as cur:
                        cur.execute(sql, tuple(values))
                        logger.info(f"Synced {len(seen_cols)} fields to mudra_user_data dynamically in post-processing", session_id=session_id)
                except Exception as db_sync_err:
                    logger.error(f"Failed to sync fields to mudra_user_data: {db_sync_err}", exc_info=True)

        # Update user_data JSON
        for k, v in all_fields.items():
            user_data_json[k] = v
        try:
            with get_db_cursor(db_pool) as cur:
                cur.execute(
                    "UPDATE user_data SET data = %s::json WHERE id = %s",
                    (json.dumps(user_data_json, ensure_ascii=False), session_id)
                )
                logger.info("Updated user_data JSON with derived and mapped fields", session_id=session_id)
        except Exception as json_sync_err:
            logger.error(f"Failed to update user_data JSON: {json_sync_err}")

        # Now proceed with post-processing pipelines
        pipelines = config.get("post_processing_pipelines", {})
        if not pipelines:
            logger.info(f"No post-processing pipelines configured for scheme {scheme_id}")
            return

        # 3. Process each pipeline
        evaluation_results = {}
        for pipeline_name, pipeline_cfg in pipelines.items():
            trigger = pipeline_cfg.get("trigger", "on_complete")
            if trigger != "on_complete":
                continue

            input_fields = pipeline_cfg.get("input_fields", [])
            prompt_template = pipeline_cfg.get("prompt_template", "")
            system_instruction = pipeline_cfg.get("system_instruction", "")
            model_name = pipeline_cfg.get("model", "gemini-2.5-flash")
            output_mapping = pipeline_cfg.get("output_mapping", {})

            # Gather dynamic input fields
            input_lines = []
            for key in input_fields:
                val = user_data_json.get(key)
                if val is None:
                    # Safe fallback to mapping translation
                    db_col = db_mapping.get(key, key)
                    val = all_fields.get(db_col)
                if val is None:
                    val = "Not provided"
                input_lines.append(f"{key}: {val}")
            
            input_data_str = "\n".join(input_lines)
            prompt = prompt_template.replace("{input_data}", input_data_str)

            # Call LLM Service
            try:
                from generated import llm_pb2, llm_pb2_grpc
                async with grpc.aio.insecure_channel("localhost:50054") as channel:
                    stub = llm_pb2_grpc.LanguageModelStub(channel)
                    logger.info(f"Invoking LLM for pipeline {pipeline_name}", session_id=session_id)
                    response = await stub.Extract(
                        llm_pb2.ExtractRequest(
                            prompt=prompt,
                            model=model_name,
                            temperature=0.2,
                            system_instruction=system_instruction
                        )
                    )
                    if not response.success:
                        raise Exception(response.error)
                    
                    # Parse JSON text
                    logger.info(f"LLM extraction success for {pipeline_name}", response_json=response.json_text)
                    result_json = json.loads(response.json_text)
                    for src_field, target_db_field in output_mapping.items():
                        evaluation_results[target_db_field] = result_json.get(src_field)

            except Exception as llm_err:
                logger.error(f"LLM call failed for pipeline {pipeline_name}: {llm_err}")

        # 4. Save results to Database
        if evaluation_results:
            logger.info("Saving evaluation results to DB", results=evaluation_results)
            
            with get_db_cursor(db_pool) as cur:
                # Update mudra_user_data
                cur.execute("SELECT id FROM mudra_user_data WHERE user_id = %s", (session_id,))
                if cur.fetchone():
                    update_parts = []
                    update_params = []
                    for k, v in evaluation_results.items():
                        if k in valid_cols:
                            update_parts.append(f"{k} = %s")
                            if k == "financial_viability" and v is not None:
                                v_clean = "Yes" if "yes" in str(v).lower() else "No"
                                update_params.append(v_clean)
                            elif k == "business_status" and v is not None:
                                update_params.append(str(v).lower())
                            else:
                                update_params.append(str(v) if v is not None else None)
                                
                    if update_parts:
                        query = f"UPDATE mudra_user_data SET {', '.join(update_parts)}, updated_at = NOW() WHERE user_id = %s"
                        update_params.append(session_id)
                        cur.execute(query, tuple(update_params))
                        logger.info("Updated mudra_user_data evaluations dynamically", session_id=session_id)

                # Update user_data.data JSON
                cur.execute("SELECT data FROM user_data WHERE id = %s", (session_id,))
                row = cur.fetchone()
                if row:
                    u_data = row[0] or {}
                    for k, v in evaluation_results.items():
                        u_data[k] = v
                    cur.execute(
                        "UPDATE user_data SET data = %s::json WHERE id = %s",
                        (json.dumps(u_data, ensure_ascii=False), session_id)
                    )
                    logger.info("Updated user_data JSON evaluations", session_id=session_id)

    except Exception as eval_err:
        logger.error(f"Error running post-processing evaluations: {eval_err}", error=traceback.format_exc())


class ApplicationOrchestratorServicer(pb2_grpc.ApplicationOrchestratorServicer):
    """gRPC servicer implementing the ApplicationOrchestrator service."""

    def __init__(self, db_pool):
        self._db_pool = db_pool

    # ─── Auth ───

    async def SendOtp(self, request, context):
        req_id = extract_req_id(context)
        logger.info("SendOtp", req_id=req_id, details={"phone": request.phone[-4:]})

        try:
            # Normalize phone to 10 digits
            phone_clean = "".join(filter(str.isdigit, str(request.phone)))[-10:]
            if not phone_clean:
                phone_clean = str(request.phone).strip()

            # Generate 4-digit OTP
            otp = str(random.randint(1000, 9999))
            
            with get_db_cursor(self._db_pool) as cur:
                # Delete any previous/old OTP for this phone number to immediately invalidate old OTPs upon resend
                cur.execute(
                    "DELETE FROM otp_verifications WHERE phone = %s OR phone = %s OR phone = %s",
                    (phone_clean, f"+91{phone_clean}", request.phone)
                )
                # Save new OTP to DB (Upsert)
                cur.execute(
                    """INSERT INTO otp_verifications (phone, otp, expires_at, created_at)
                       VALUES (%s, %s, NOW() + INTERVAL '5 minutes', NOW())
                       ON CONFLICT (phone) 
                       DO UPDATE SET otp = %s, expires_at = NOW() + INTERVAL '5 minutes', created_at = NOW()""",
                    (phone_clean, otp, otp)
                )

            logger.info(f"Generated OTP for {phone_clean}: {otp}", req_id=req_id)

            # Try to send SMS via 2factor.in if API key is in environment
            api_key = os.getenv("TWO_FACTOR_API_KEY")
            url = os.getenv("TWO_FACTOR_URL")
            
            if api_key and url:
                try:
                    payload = urllib.parse.urlencode({
                        "module": "TRANS_SMS",
                        "apikey": api_key,
                        "to": phone_clean,
                        "from": "PWINVT",
                        "templatename": "Mudra OTP",
                        "var1": otp
                    }).encode('utf-8')
                    
                    req = urllib.request.Request(
                        url,
                        data=payload,
                        headers={"Content-Type": "application/x-www-form-urlencoded"},
                        method="POST"
                    )
                    
                    # Send async call using asyncio.to_thread with explicit timeout!
                    response = await asyncio.to_thread(urllib.request.urlopen, req, timeout=5)
                    res_data = json.loads(response.read().decode('utf-8'))
                    
                    if res_data.get("Status") == "Success":
                        logger.info("OTP sent successfully via 2Factor API", req_id=req_id)
                        return pb2.SendOtpResponse(success=True)
                    else:
                        logger.error(f"2Factor API error response: {res_data}", req_id=req_id)
                        
                    # Fallback on any failure
                    logger.warning(f"[SMS API FAILED] Falling back to console Mock for {phone_clean}. OTP: {otp}", req_id=req_id)
                    print(f"\n=============================\n OTP for {phone_clean}: {otp}\n=============================\n", flush=True)
                    return pb2.SendOtpResponse(success=True)
                    
                except Exception as sms_err:
                    logger.error(f"Could not send SMS via 2Factor (Timeout/Error): {sms_err}", req_id=req_id)
                    logger.warning(f"[SMS API FAILED] Falling back to console Mock for {phone_clean}. OTP: {otp}", req_id=req_id)
                    print(f"\n=============================\n OTP for {phone_clean}: {otp}\n=============================\n", flush=True)
                    return pb2.SendOtpResponse(success=True)
            else:
                logger.warning(f"[SMS CONFIG MISSING] Mocking SMS for {phone_clean}. OTP: {otp}", req_id=req_id)
                print(f"\n=============================\n OTP for {phone_clean}: {otp}\n=============================\n", flush=True)
                return pb2.SendOtpResponse(success=True)
        except Exception as e:
            logger.error(f"SendOtp failed: {e}", req_id=req_id, error=traceback.format_exc())
            return pb2.SendOtpResponse(success=False, error=str(e))

    async def VerifyOtp(self, request, context):
        req_id = extract_req_id(context)
        logger.info("VerifyOtp", req_id=req_id, details={"phone": request.phone[-4:]})

        try:
            phone_clean = "".join(filter(str.isdigit, str(request.phone)))[-10:]
            if not phone_clean:
                phone_clean = str(request.phone).strip()

            with get_db_cursor(self._db_pool) as cur:
                # 1. Verify OTP
                cur.execute(
                    """SELECT * FROM otp_verifications 
                       WHERE (phone = %s OR phone = %s OR phone = %s) 
                         AND otp = %s 
                         AND expires_at > NOW()""",
                    (phone_clean, f"+91{phone_clean}", request.phone, request.otp)
                )
                otp_row = cur.fetchone()
                if not otp_row:
                    return pb2.VerifyOtpResponse(success=False, error="Invalid or expired OTP")

                # Delete OTP immediately upon verification
                cur.execute(
                    "DELETE FROM otp_verifications WHERE phone = %s OR phone = %s OR phone = %s",
                    (phone_clean, f"+91{phone_clean}", request.phone)
                )

                # 2. Get or create session
                SBI_BANK_SCHEME_ID = 'a74b1b43-7cc6-4385-8a8c-12af64cddb2b'
                cur.execute(
                    "SELECT id FROM user_data WHERE phone = %s",
                    (request.phone,)
                )
                user_row = cur.fetchone()

                requires_panchayat = False
                if user_row:
                    session_id = user_row[0]
                else:
                    session_id = str(uuid.uuid4())
                    cur.execute(
                        """INSERT INTO user_data (id, phone, data) 
                           VALUES (%s, %s, %s::json)""",
                        (session_id, request.phone, json.dumps({
                            "scheme_id": SBI_BANK_SCHEME_ID,
                            "completion_status": "NEW",
                            "onboarding_finished": False,
                            "created_at": datetime.datetime.now().isoformat(),
                            "updated_at": datetime.datetime.now().isoformat()
                        }, ensure_ascii=False))
                    )
                    logger.info(f"Created new session {session_id} for user {request.phone}", req_id=req_id)

                return pb2.VerifyOtpResponse(
                    success=True,
                    session_id=session_id,
                    requires_panchayat=requires_panchayat,
                )
        except Exception as e:
            logger.error(f"VerifyOtp failed: {e}", req_id=req_id, error=traceback.format_exc())
            return pb2.VerifyOtpResponse(success=False, error=str(e))

    # ─── Application Lifecycle ───

    async def CreateApplication(self, request, context):
        req_id = extract_req_id(context)
        logger.info("CreateApplication", req_id=req_id,
                     scheme_id=request.scheme_id,
                     session_id=request.session_id)
        try:
            with get_db_cursor(self._db_pool) as cur:
                cur.execute("SELECT data FROM user_data WHERE id = %s", (request.session_id,))
                row = cur.fetchone()
                existing_data = {}
                if row and row[0]:
                    existing_data = row[0]
                
                existing_data["scheme_id"] = request.scheme_id
                existing_data["phone"] = request.phone
                existing_data["applicant_name"] = request.name
                existing_data["completion_status"] = "NEW"
                existing_data["onboarding_finished"] = False
                existing_data["created_at"] = existing_data.get("created_at") or datetime.datetime.now().isoformat()
                existing_data["updated_at"] = datetime.datetime.now().isoformat()

                cur.execute(
                    """INSERT INTO user_data (id, phone, data) VALUES (%s, %s, %s::json)
                       ON CONFLICT (id) DO UPDATE SET phone = EXCLUDED.phone, data = EXCLUDED.data""",
                    (request.session_id, request.phone, json.dumps(existing_data, ensure_ascii=False))
                )
                
                return pb2.Application(
                    application_id=existing_data.get("application_id", ""),
                    session_id=request.session_id,
                    scheme_id=request.scheme_id,
                    stage="REGISTRATION",
                    completion_status="NEW",
                    phone=request.phone,
                )
        except Exception as e:
            logger.error(f"CreateApplication failed: {e}", req_id=req_id)
            context.set_code(grpc.StatusCode.INTERNAL)
            return pb2.Application()

    async def GetApplication(self, request, context):
        req_id = extract_req_id(context)
        logger.info("GetApplication", req_id=req_id,
                     application_id=request.application_id)
        try:
            with get_db_cursor(self._db_pool) as cur:
                cur.execute(
                    "SELECT id, phone, data FROM user_data WHERE id = %s OR data->>'application_id' = %s", 
                    (request.application_id, request.application_id)
                )
                row = cur.fetchone()
                if row:
                    session_id, phone, data = row
                    data = data or {}
                    return pb2.Application(
                        application_id=data.get("application_id", ""),
                        session_id=session_id,
                        scheme_id=data.get("scheme_id", ""),
                        completion_status=data.get("completion_status", "NEW"),
                        phone=phone or data.get("phone", ""),
                        stage="INTERVIEW" if data.get("status") else "DOCUMENTATION"
                    )
            context.set_code(grpc.StatusCode.NOT_FOUND)
            return pb2.Application()
        except Exception as e:
            logger.error(f"GetApplication failed: {e}", req_id=req_id)
            return pb2.Application()

    async def AdvanceStage(self, request, context):
        req_id = extract_req_id(context)
        logger.info("AdvanceStage", req_id=req_id,
                     application_id=request.application_id)
        try:
            with get_db_cursor(self._db_pool) as cur:
                cur.execute(
                    "SELECT id, phone, data FROM user_data WHERE id = %s OR data->>'application_id' = %s", 
                    (request.application_id, request.application_id)
                )
                row = cur.fetchone()
                if not row:
                    context.set_code(grpc.StatusCode.NOT_FOUND)
                    return pb2.Application()
                
                session_id, phone, data = row
                data = data or {}
                data["completion_status"] = request.new_stage
                data["updated_at"] = datetime.datetime.now().isoformat()

                cur.execute(
                    "UPDATE user_data SET data = %s::json WHERE id = %s",
                    (json.dumps(data, ensure_ascii=False), session_id)
                )
                return pb2.Application(
                    application_id=data.get("application_id", ""),
                    session_id=session_id,
                    completion_status=request.new_stage,
                )
        except Exception as e:
            logger.error(f"AdvanceStage failed: {e}", req_id=req_id)
            return pb2.Application()

    async def GetApplicationStatus(self, request, context):
        req_id = extract_req_id(context)
        try:
            with get_db_cursor(self._db_pool) as cur:
                cur.execute(
                    "SELECT id, data FROM user_data WHERE id = %s OR data->>'application_id' = %s", 
                    (request.application_id, request.application_id)
                )
                row = cur.fetchone()
                if row:
                    session_id, data = row
                    data = data or {}
                    return pb2.ApplicationStatus(
                        application_id=request.application_id,
                        stage="INTERVIEW" if data.get("status") else "DOCUMENTATION",
                        completion_status=data.get("completion_status", ""),
                    )
            return pb2.ApplicationStatus()
        except Exception as e:
            logger.error(f"GetApplicationStatus failed: {e}", req_id=req_id)
            return pb2.ApplicationStatus()

    # ─── Panchayat / Location ───

    async def SavePanchayat(self, request, context):
        req_id = extract_req_id(context)
        logger.info("SavePanchayat", req_id=req_id,
                     session_id=request.session_id,
                     details={"panchayat": request.panchayat,
                              "block": request.block})
        try:
            block_name = request.block or "DEFAULT"
            is_rseti_user = (request.rseti == 'yes')
            target_cadre_id = None
            rseti_approved = False
            admin_found = False

            with get_db_cursor(self._db_pool) as cur:
                # 1. Generate application ID
                now = datetime.datetime.now()
                prefix = f"{now.year}/{now.month:02d}/{block_name}"
                cur.execute("SELECT COUNT(*) FROM user_data WHERE data->>'application_id' LIKE %s", (f"{prefix}%",))
                cnt = cur.fetchone()[0]
                application_id = f"{prefix}-{(cnt + 1):03d}"

                if request.skip and request.cadre_id:
                    target_cadre_id = request.cadre_id
                else:
                    if is_rseti_user:
                        cur.execute(
                            "SELECT id FROM admins WHERE scheme_id = 'a74b1b43-7cc6-4385-8a8c-12af64cddb2b' AND district_id = '0bf9b673-f349-4b50-a8c7-bbe500c0a6cf' AND role = 'LVL1' LIMIT 1"
                        )
                        r = cur.fetchone()
                        if r:
                            target_cadre_id = r[0]
                            rseti_approved = True
                            admin_found = True
                        else:
                            is_rseti_user = False

                    if not target_cadre_id:
                        cur.execute(
                            "SELECT id FROM admins WHERE %s = ANY(villages) AND role = 'LVL1' LIMIT 1",
                            (request.panchayat,)
                        )
                        r = cur.fetchone()
                        if r:
                            target_cadre_id = r[0]
                            admin_found = True

                # Fetch existing data from user_data
                cur.execute("SELECT data, phone FROM user_data WHERE id = %s", (request.session_id,))
                db_row = cur.fetchone()
                existing_data = {}
                phone = ""
                if db_row:
                    existing_data = db_row[0] or {}
                    phone = db_row[1] or ""

                # 2. Update user_data json fields
                existing_data["panchayat"] = request.panchayat
                existing_data["cadre_id"] = target_cadre_id or ""
                existing_data["application_id"] = application_id
                existing_data["rseti"] = request.rseti or ""
                existing_data["scheme_id"] = 'a74b1b43-7cc6-4385-8a8c-12af64cddb2b'
                existing_data["onboarding_finished"] = False
                existing_data["updated_at"] = now.isoformat()

                if is_rseti_user:
                    existing_data["status"] = 'APPROVED_BY_LVL_1'
                
                cur.execute(
                    """INSERT INTO user_data (id, phone, data) VALUES (%s, %s, %s::json)
                       ON CONFLICT (id) DO UPDATE SET data = EXCLUDED.data""",
                    (request.session_id, phone, json.dumps(existing_data, ensure_ascii=False))
                )

            return pb2.SavePanchayatResponse(
                success=True,
                application_id=application_id,
                admin_found=admin_found,
                rseti_approved=rseti_approved,
            )
        except Exception as e:
            logger.error(f"SavePanchayat failed: {e}", req_id=req_id, error=traceback.format_exc())
            return pb2.SavePanchayatResponse(success=False, error=str(e))

    async def GetLocationTree(self, request, context):
        req_id = extract_req_id(context)
        try:
            items = []
            with get_db_cursor(self._db_pool) as cur:
                if request.level == "states":
                    cur.execute("SELECT id, name FROM states")
                elif request.level == "districts" and request.parent_id:
                    cur.execute("SELECT id, name, state_id FROM districts WHERE state_id = %s", (request.parent_id,))
                elif request.level == "blocks" and request.parent_id:
                    cur.execute("SELECT id, name, district_id FROM blocks WHERE district_id = %s", (request.parent_id,))
                elif request.level == "panchayats" and request.parent_id:
                    cur.execute("SELECT id, name, block_id FROM panchayats WHERE block_id = %s", (request.parent_id,))
                else:
                    return pb2.LocationTree(items=[])

                rows = cur.fetchall()
                for row in rows:
                    parent_id = str(row[2]) if len(row) > 2 else ""
                    items.append(pb2.LocationItem(
                        id=str(row[0]),
                        name=row[1],
                        parent_id=parent_id
                    ))
            return pb2.LocationTree(items=items)
        except Exception as e:
            logger.error(f"GetLocationTree failed: {e}", req_id=req_id)
            return pb2.LocationTree(items=[])

    # ─── Data Operations ───

    async def UpsertExtractedData(self, request, context):
        req_id = extract_req_id(context)
        logger.info("UpsertExtractedData", req_id=req_id,
                     application_id=request.application_id,
                     details={"source": request.source})
        try:
            fields = json.loads(request.json_fields) if request.json_fields else {}
            if not fields:
                return pb2.UpsertDataResponse(success=True, fields_updated=0)

            with get_db_cursor(self._db_pool) as cur:
                conn = cur.connection
                conn.autocommit = False
                try:
                    # Resolve session_id (which is user_data.id) and lock row
                    cur.execute(
                        "SELECT id, phone, data FROM user_data WHERE id = %s OR data->>'application_id' = %s FOR UPDATE",
                        (request.application_id, request.application_id)
                    )
                    row = cur.fetchone()
                    if not row:
                        conn.commit()
                        return pb2.UpsertDataResponse(success=False, error="Application/User not found")
                    
                    session_id, phone, existing_data = row
                    existing_data = existing_data or {}

                    # Check if resetting/redoing process
                    onboarding_val = fields.get("onboarding_finished")
                    if onboarding_val is not None:
                        if isinstance(onboarding_val, str):
                            onboarding_val = onboarding_val.lower() in ("true", "1", "yes")
                        else:
                            onboarding_val = bool(onboarding_val)

                    if onboarding_val is False:
                        meta_keys = ["scheme_id", "created_at", "updated_at", "phone", "cadre_id", "panchayat", "application_id", "rseti", "status"]
                        existing_data = {k: existing_data[k] for k in meta_keys if k in existing_data}
                        existing_data["completion_status"] = "NEW"
                        existing_data["onboarding_finished"] = False
                        
                        cur.execute("DELETE FROM docs_test WHERE user_id = %s", (session_id,))
                        logger.info(f"Reset application state and deleted documents from docs_test for session {session_id}", req_id=req_id)
                    else:
                        # Save a copy under document-specific key to prevent clobbering
                        if request.source and request.source not in ("manual", "workflow"):
                            if "extractions" not in existing_data:
                                existing_data["extractions"] = {}
                            existing_data["extractions"][request.source] = fields

                        # Update main user fields inside JSON data
                        user_fields = {
                            "applicant_name": fields.get("name") or fields.get("applicant_name") or fields.get("name_of_the_applicant") or fields.get("corrected_name"),
                            "business_type": fields.get("business_type") or fields.get("type_of_business"),
                            "business_revenue": fields.get("business_revenue") or fields.get("monthly_revenue") or fields.get("net_sales_present_year"),
                        }
                        for k, v in user_fields.items():
                            if v is not None:
                                if k == "applicant_name":
                                    is_aadhaar_source = "AADHAAR" in str(request.source).upper() or "AADHAR" in str(request.source).upper()
                                    if not is_aadhaar_source and request.source not in ("manual", "workflow"):
                                        if existing_data.get("applicant_name") and existing_data.get("applicant_name") != "Applicant":
                                            continue
                                existing_data[k] = v

                        # Merge new fields
                        for k, v in fields.items():
                            if k == "onboarding_finished":
                                if isinstance(v, str):
                                    existing_data[k] = v.lower() in ("true", "1", "yes")
                                else:
                                    existing_data[k] = bool(v)
                            elif v is not None and v != "":
                                # Prevent non-Aadhaar documents from clobbering main Aadhaar holder/address keys
                                is_aadhaar_source = "AADHAAR" in str(request.source).upper() or "AADHAR" in str(request.source).upper()
                                if k in ("holder", "address") and not is_aadhaar_source and request.source not in ("manual", "workflow"):
                                    if k in existing_data and existing_data[k]:
                                        continue

                                if isinstance(v, dict):
                                    if k not in existing_data or not isinstance(existing_data[k], dict):
                                        existing_data[k] = {}
                                    
                                    def recursive_merge(target, source):
                                        for sub_k, sub_v in source.items():
                                            if sub_v is None or sub_v == "":
                                                continue
                                            if isinstance(sub_v, dict):
                                                if sub_k not in target or not isinstance(target[sub_k], dict):
                                                    target[sub_k] = {}
                                                recursive_merge(target[sub_k], sub_v)
                                            else:
                                                target[sub_k] = sub_v
                                    recursive_merge(existing_data[k], v)
                                else:
                                    if isinstance(v, (list, bool, int, float)):
                                        existing_data[k] = v
                                    else:
                                        existing_data[k] = str(v)

                    # Update phone column and JSON field if present in fields
                    if "phone" in fields and fields["phone"]:
                        phone = fields["phone"]
                        existing_data["phone"] = phone

                    # Upsert into user_data
                    merged_json_str = json.dumps(existing_data, ensure_ascii=False)
                    cur.execute(
                        """UPDATE user_data SET phone = %s, data = %s::json WHERE id = %s""",
                        (phone or None, merged_json_str, session_id)
                    )
                    conn.commit()
                    logger.info(f"Upserted {len(fields)} fields to user_data", req_id=req_id)
                    
                    # Trigger evaluations if onboarding_finished is True or trigger_evaluations is True
                    if existing_data.get("onboarding_finished") is True or fields.get("trigger_evaluations") is True:
                        asyncio.create_task(run_post_processing_evaluations(session_id, self._db_pool))
                except Exception as e:
                    conn.rollback()
                    raise
                finally:
                    conn.autocommit = True

            return pb2.UpsertDataResponse(
                success=True,
                fields_updated=len(fields),
            )
        except Exception as e:
            logger.error(f"UpsertExtractedData failed: {e}", req_id=req_id, error=traceback.format_exc())
            return pb2.UpsertDataResponse(success=False, error=str(e))

    async def GetExtractedData(self, request, context):
        req_id = extract_req_id(context)
        logger.info("GetExtractedData", req_id=req_id, application_id=request.application_id)
        try:
            with get_db_cursor(self._db_pool) as cur:
                cur.execute(
                    "SELECT id, phone, data FROM user_data WHERE id = %s OR data->>'application_id' = %s",
                    (request.application_id, request.application_id)
                )
                row = cur.fetchone()
                if not row:
                    return pb2.ExtractedData(application_id=request.application_id, json_data="{}")

                session_id, phone, data = row
                data = data or {}

                # Ensure phone is in data
                if phone and "phone" not in data:
                    data["phone"] = phone

                # On-the-fly derived fields calculation for Mudra schemes if they are missing
                scheme_id = data.get("scheme_id", "")
                is_mudra_scheme = (
                    "mudra" in str(scheme_id).lower() or 
                    scheme_id == 'a74b1b43-7cc6-4385-8a8c-12af64cddb2b'
                )
                if is_mudra_scheme:
                    logger.info("Mudra derived fields calculation in GetExtractedData. Calculating on the fly...", session_id=session_id)
                    from calculations import calculate_derived_fields
                    try:
                        # Gather current data
                        all_fields = {}
                        all_fields.update(data)
                        if phone:
                            all_fields["phone"] = phone
                            all_fields["mobile_number"] = phone
                        
                        # Read current mudra_user_data row if exists
                        cur.execute("SELECT * FROM mudra_user_data WHERE user_id = %s", (session_id,))
                        m_row = cur.fetchone()
                        if m_row:
                            col_names = [desc[0] for desc in cur.description]
                            for name, val in zip(col_names, m_row):
                                if name in ("id", "user_id", "created_at", "updated_at"):
                                    continue
                                if val is not None and val != "":
                                    # Prevent database zero/null values from clobbering valid voice/GCS values
                                    is_db_zero = str(val).strip() in ("0", "0.0", "None", "Null")
                                    voice_val = all_fields.get(name)
                                    is_voice_valid = voice_val is not None and str(voice_val).strip() not in ("0", "0.0", "Not Available", "NA", "")
                                    
                                    if is_db_zero and is_voice_valid:
                                        continue
                                    all_fields[name] = val
                        
                        # Load config db mapping
                        config = load_resolved_scheme_config(scheme_id)
                        db_mapping = config.get("db_mapping", {}) if config else {}
                        mapped_fields = {}
                        for k, v in all_fields.items():
                            mapped_k = db_mapping.get(k, k)
                            mapped_fields[mapped_k] = v
                        all_fields.update(mapped_fields)
                        
                        applicant_name_val = all_fields.get("applicant_name")
                        if not applicant_name_val or applicant_name_val == "Applicant":
                            def get_nested(d, keys):
                                for k in keys:
                                    if isinstance(d, dict):
                                        d = d.get(k)
                                    elif isinstance(d, str):
                                        try:
                                            d = json.loads(d).get(k)
                                        except:
                                            return None
                                    else:
                                        return None
                                return d
                            
                            # Extract AADHAAR_FRONT from extractions namespace first
                            extractions = all_fields.get("extractions", {})
                            if isinstance(extractions, str):
                                try: extractions = json.loads(extractions)
                                except: extractions = {}
                            
                            aadhaar_ext = extractions.get("AADHAAR_FRONT") or extractions.get("AADHAR_FRONT") or {}
                            aadhaar_name = get_nested(aadhaar_ext, ["holder", "full_name"])
                            
                            holder_name = get_nested(all_fields, ["holder", "full_name"])
                            pan_name = get_nested(extractions.get("PAN") or {}, ["holder", "full_name"])
                            
                            resolved_name = (
                                aadhaar_name or
                                holder_name or
                                pan_name or
                                all_fields.get("name") or
                                all_fields.get("full_name") or
                                "Applicant"
                            )
                            all_fields["applicant_name"] = resolved_name

                        if "business_type" not in all_fields:
                            all_fields["business_type"] = all_fields.get("type_of_business") or "other"
                            
                        derived = calculate_derived_fields(all_fields)
                        all_fields.update(derived)
                        
                        # Update local data
                        for k, v in all_fields.items():
                            data[k] = v
                            
                        # Save back to database JSON
                        cur.execute(
                            "UPDATE user_data SET data = %s::json WHERE id = %s",
                            (json.dumps(data, ensure_ascii=False), session_id)
                        )
                        logger.info("Successfully updated missing derived fields on the fly in GetExtractedData", session_id=session_id)
                    except Exception as calc_otf_err:
                        logger.error(f"Failed to calculate derived fields on the fly: {calc_otf_err}")

                # Trigger background evaluations if onboarding is finished but credit evaluation is missing/pending
                if data.get("onboarding_finished") is True:
                    cw = data.get("credit_worthiness")
                    if not cw or cw in ["Calculating...", "Not Available"]:
                        logger.info("Triggering background post-processing evaluations on demand from GetExtractedData", session_id=session_id)
                        asyncio.create_task(run_post_processing_evaluations(session_id, self._db_pool))

                return pb2.ExtractedData(
                    application_id=request.application_id,
                    json_data=json.dumps(data, ensure_ascii=False),
                )
        except Exception as e:
            logger.error(f"GetExtractedData failed: {e}", req_id=req_id)
            return pb2.ExtractedData(application_id=request.application_id, json_data="{}")

    # ─── Financial Calculations ───

    async def CalculateFinancials(self, request, context):
        req_id = extract_req_id(context)
        logger.info("CalculateFinancials", req_id=req_id,
                     application_id=request.application_id)
        # Placeholder
        return pb2.FinancialCalcResponse(success=True, derived_data_json="{}")

    # ─── Report Generation ───

    async def GenerateReport(self, request, context):
        req_id = extract_req_id(context)
        logger.info("GenerateReport", req_id=req_id,
                     application_id=request.application_id)
        return pb2.ReportResponse(success=True, report_data=b"", gcs_url="")

    # ─── Admin ───

    async def ListApplications(self, request, context):
        req_id = extract_req_id(context)
        try:
            with get_db_cursor(self._db_pool) as cur:
                cur.execute("SELECT id, phone, data FROM user_data LIMIT %s OFFSET %s", 
                            (request.limit or 10, request.offset or 0))
                rows = cur.fetchall()
                
                cur.execute("SELECT COUNT(*) FROM user_data")
                total = cur.fetchone()[0]

                summaries = []
                for row in rows:
                    session_id, phone, data = row
                    data = data or {}
                    status = data.get("status", "")
                    summaries.append(pb2.ApplicationSummary(
                        application_id=data.get("application_id", ""),
                        session_id=session_id,
                        phone=phone or data.get("phone", ""),
                        stage="INTERVIEW" if status else "DOCUMENTATION",
                        completion_status=data.get("completion_status", ""),
                        panchayat=data.get("panchayat", ""),
                        created_at=data.get("created_at", ""),
                    ))
                return pb2.ApplicationList(applications=summaries, total_count=total)
        except Exception as e:
            logger.error(f"ListApplications failed: {e}", req_id=req_id)
            return pb2.ApplicationList(applications=[], total_count=0)

    async def UpdateApplicationStatus(self, request, context):
        req_id = extract_req_id(context)
        logger.info("UpdateApplicationStatus", req_id=req_id,
                     application_id=request.application_id)
        try:
            with get_db_cursor(self._db_pool) as cur:
                cur.execute(
                    "SELECT id, phone, data FROM user_data WHERE id = %s OR data->>'application_id' = %s",
                    (request.application_id, request.application_id)
                )
                row = cur.fetchone()
                if not row:
                    context.set_code(grpc.StatusCode.NOT_FOUND)
                    return pb2.Application()
                
                session_id, phone, data = row
                data = data or {}
                data["status"] = request.new_status
                data["updated_at"] = datetime.datetime.now().isoformat()

                cur.execute(
                    "UPDATE user_data SET data = %s::json WHERE id = %s",
                    (json.dumps(data, ensure_ascii=False), session_id)
                )
                return pb2.Application(
                    application_id=data.get("application_id", ""),
                    session_id=session_id,
                    completion_status="APPROVED",
                    phone=phone or data.get("phone", "")
                )
        except Exception as e:
            logger.error(f"UpdateApplicationStatus failed: {e}", req_id=req_id)
            return pb2.Application()

    # ─── Document Operations ───

    async def SaveDocument(self, request, context):
        req_id = extract_req_id(context)
        logger.info("SaveDocument", req_id=req_id, session_id=request.session_id, doc_type=request.doc_type)
        try:
            raw_doc_type = request.doc_type.upper()
            if "WORKPLACE_VIDEO" in raw_doc_type or "WORKPLACE" in raw_doc_type:
                # Handle workplace geo-tagged video
                latitude = None
                longitude = None
                address = None
                doc_name = "workplace_video.webm"
                try:
                    import json
                    parsed = json.loads(request.name)
                    if isinstance(parsed, dict):
                        doc_name = parsed.get("name", doc_name)
                        latitude = parsed.get("latitude")
                        longitude = parsed.get("longitude")
                        address = parsed.get("address")
                except Exception:
                    doc_name = request.name or doc_name

                with get_db_cursor(self._db_pool) as cur:
                    # Ensure table exists
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS geo_tagged_videos (
                            id SERIAL PRIMARY KEY,
                            user_id UUID UNIQUE NOT NULL,
                            gcs_path VARCHAR(255) NOT NULL,
                            latitude NUMERIC,
                            longitude NUMERIC,
                            address TEXT,
                            recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        );
                    """)
                    
                    # Upsert into geo_tagged_videos
                    cur.execute("""
                        INSERT INTO geo_tagged_videos (user_id, gcs_path, latitude, longitude, address, recorded_at)
                        VALUES (%s, %s, %s, %s, %s, NOW())
                        ON CONFLICT (user_id) DO UPDATE SET
                            gcs_path = EXCLUDED.gcs_path,
                            latitude = EXCLUDED.latitude,
                            longitude = EXCLUDED.longitude,
                            address = EXCLUDED.address,
                            recorded_at = EXCLUDED.recorded_at,
                            created_at = CURRENT_TIMESTAMP;
                    """, (request.session_id, request.key, latitude, longitude, address))

                    # Insert mapping in docs_test as well
                    doc_id = str(uuid.uuid4())
                    cur.execute(
                        """INSERT INTO docs_test (id, key, user_id, name, created_at, updated_at)
                           VALUES (%s, %s, %s, %s, NOW(), NOW())""",
                        (doc_id, request.key, request.session_id, doc_name)
                    )
                return pb2.SaveDocResponse(success=True)

            if "AADHAAR_FRONT" in raw_doc_type or "AADHAR_FRONT" in raw_doc_type:
                db_doc_type = "AADHAR_FRONT"
            elif "AADHAAR_BACK" in raw_doc_type or "AADHAR_BACK" in raw_doc_type:
                db_doc_type = "AADHAR_BACK"
            elif "PAN" in raw_doc_type:
                db_doc_type = "PAN"
            elif "SELFIE" in raw_doc_type:
                db_doc_type = "SELFIE"
            elif "UDYAM" in raw_doc_type:
                db_doc_type = "UDYAM"
            elif "VOTERID_FRONT" in raw_doc_type:
                db_doc_type = "VOTERID_FRONT"
            elif "VOTERID_BACK" in raw_doc_type:
                db_doc_type = "VOTERID_BACK"
            elif "BANK" in raw_doc_type or "STATEMENT" in raw_doc_type:
                db_doc_type = "BANK_PASSBOOK"
            else:
                db_doc_type = raw_doc_type

            VALID_ENUM_VALUES = {
                "AADHAR_FRONT", "AADHAR_BACK", "SELFIE", "UDYAM", "VOTERID_FRONT", "VOTERID_BACK",
                "SESSION", "APPLICATION", "PAN", "PAN_FRONT", "INCOME_CERTIFICATE",
                "ADDITIONAL_DOCUMENT", "BANK_PASSBOOK", "ELECTRICITY_BILL", "LEASE_AGREEMENT",
                "FSSAI", "TRADE_LICENSE", "SPOUSE_PAN_FRONT", "MACHINE_QUOTATION"
            }
            if db_doc_type not in VALID_ENUM_VALUES:
                db_doc_type = "ADDITIONAL_DOCUMENT"

            doc_name = request.name or "document"
            with get_db_cursor(self._db_pool) as cur:
                doc_id = str(uuid.uuid4())
                cur.execute(
                    """INSERT INTO docs_test (id, key, user_id, name, created_at, updated_at)
                       VALUES (%s, %s, %s, %s, NOW(), NOW())""",
                    (doc_id, request.key, request.session_id, doc_name)
                )
            return pb2.SaveDocResponse(success=True)
        except Exception as e:
            logger.error(f"SaveDocument failed: {e}", req_id=req_id, error=traceback.format_exc())
            return pb2.SaveDocResponse(success=False, error=str(e))

    async def GetDocuments(self, request, context):
        req_id = extract_req_id(context)
        logger.info("GetDocuments", req_id=req_id, application_id=request.application_id)
        try:
            with get_db_cursor(self._db_pool) as cur:
                cur.execute(
                    "SELECT id FROM user_data WHERE id = %s OR data->>'application_id' = %s",
                    (request.application_id, request.application_id)
                )
                row = cur.fetchone()
                if not row:
                    return pb2.DocumentList(documents=[])
                
                session_id = row[0]
                cur.execute(
                    "SELECT id, key, name FROM docs_test WHERE user_id = %s",
                    (session_id,)
                )
                rows = cur.fetchall()
                docs_list = []
                for r in rows:
                    key = r[1]
                    doc_type = ""
                    if key and "/" in key:
                        parts = key.split("/")
                        if len(parts) >= 3:
                            doc_type = parts[2]
                    docs_list.append(pb2.DocumentItem(
                        id=str(r[0]),
                        key=key,
                        doc_type=doc_type,
                        name=r[2] or ""
                    ))
                return pb2.DocumentList(documents=docs_list)
        except Exception as e:
            logger.error(f"GetDocuments failed: {e}", req_id=req_id)
            return pb2.DocumentList(documents=[])


async def serve():
    """Start the App Orchestrator gRPC server."""
    # Initialize DB pool with TCP Keepalives to prevent GCP/Firewall silent timeouts and connection loss
    conn_url = DATABASE_URL
    if "postgresql://" in conn_url or "postgres://" in conn_url:
        if "?" in conn_url:
            conn_url += "&keepalives=1&keepalives_idle=30&keepalives_interval=10&keepalives_count=3"
        else:
            conn_url += "?keepalives=1&keepalives_idle=30&keepalives_interval=10&keepalives_count=3"

    db_pool = psycopg2.pool.ThreadedConnectionPool(2, 20, conn_url)
    
    server = grpc_aio.server()
    servicer = ApplicationOrchestratorServicer(db_pool)
    pb2_grpc.add_ApplicationOrchestratorServicer_to_server(servicer, server)

    listen_addr = f"[::]:{APP_ORCHESTRATOR_PORT}"
    server.add_insecure_port(listen_addr)

    logger.info(f"App Orchestrator starting on {listen_addr}",
                details={"port": APP_ORCHESTRATOR_PORT})

    await server.start()
    logger.info("App Orchestrator ready ✅")

    async def shutdown(sig):
        logger.info(f"Received {sig.name}, shutting down...")
        await server.stop(grace=5)
        db_pool.closeall()

    loop = asyncio.get_event_loop()
    for sig_name in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig_name, lambda s=sig_name: asyncio.create_task(shutdown(s)))

    await server.wait_for_termination()


if __name__ == "__main__":
    asyncio.run(serve())
