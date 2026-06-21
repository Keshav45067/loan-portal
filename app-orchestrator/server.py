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


class ApplicationOrchestratorServicer(pb2_grpc.ApplicationOrchestratorServicer):
    """gRPC servicer implementing the ApplicationOrchestrator service."""

    def __init__(self, db_pool):
        self._db_pool = db_pool

    # ─── Auth ───

    async def SendOtp(self, request, context):
        req_id = extract_req_id(context)
        logger.info("SendOtp", req_id=req_id, details={"phone": request.phone[-4:]})

        try:
            # Generate 4-digit OTP
            otp = str(random.randint(1000, 9999))
            
            with get_db_cursor(self._db_pool) as cur:
                # Save to DB (Upsert)
                cur.execute(
                    """INSERT INTO otp_verifications (phone, otp, expires_at, created_at)
                       VALUES (%s, %s, NOW() + INTERVAL '5 minutes', NOW())
                       ON CONFLICT (phone) 
                       DO UPDATE SET otp = %s, expires_at = NOW() + INTERVAL '5 minutes', created_at = NOW()""",
                    (request.phone, otp, otp)
                )

            logger.info(f"Generated OTP for {request.phone}: {otp}", req_id=req_id)

            # Try to send SMS via 2factor.in if API key is in environment
            api_key = os.getenv("TWO_FACTOR_API_KEY")
            url = os.getenv("TWO_FACTOR_URL")
            
            if api_key and url:
                try:
                    payload = urllib.parse.urlencode({
                        "module": "TRANS_SMS",
                        "apikey": api_key,
                        "to": request.phone,
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
                    logger.warning(f"[SMS API FAILED] Falling back to console Mock for {request.phone}. OTP: {otp}", req_id=req_id)
                    print(f"\n=============================\n OTP for {request.phone}: {otp}\n=============================\n", flush=True)
                    return pb2.SendOtpResponse(success=True)
                    
                except Exception as sms_err:
                    logger.error(f"Could not send SMS via 2Factor (Timeout/Error): {sms_err}", req_id=req_id)
                    logger.warning(f"[SMS API FAILED] Falling back to console Mock for {request.phone}. OTP: {otp}", req_id=req_id)
                    print(f"\n=============================\n OTP for {request.phone}: {otp}\n=============================\n", flush=True)
                    return pb2.SendOtpResponse(success=True)
            else:
                logger.warning(f"[SMS CONFIG MISSING] Mocking SMS for {request.phone}. OTP: {otp}", req_id=req_id)
                print(f"\n=============================\n OTP for {request.phone}: {otp}\n=============================\n", flush=True)
                return pb2.SendOtpResponse(success=True)
        except Exception as e:
            logger.error(f"SendOtp failed: {e}", req_id=req_id, error=traceback.format_exc())
            return pb2.SendOtpResponse(success=False, error=str(e))

    async def VerifyOtp(self, request, context):
        req_id = extract_req_id(context)
        logger.info("VerifyOtp", req_id=req_id, details={"phone": request.phone[-4:]})

        try:
            with get_db_cursor(self._db_pool) as cur:
                # 1. Verify OTP
                cur.execute(
                    "SELECT * FROM otp_verifications WHERE phone = %s AND otp = %s AND expires_at > NOW()",
                    (request.phone, request.otp)
                )
                otp_row = cur.fetchone()
                if not otp_row:
                    return pb2.VerifyOtpResponse(success=False, error="Invalid or expired OTP")

                # Delete OTP
                cur.execute("DELETE FROM otp_verifications WHERE phone = %s", (request.phone,))

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
                        
                        cur.execute("DELETE FROM docs WHERE user_id = %s", (session_id,))
                        logger.info(f"Reset application state and deleted documents for session {session_id}", req_id=req_id)
                    else:
                        # Update main user fields inside JSON data
                        user_fields = {
                            "applicant_name": fields.get("name") or fields.get("applicant_name") or fields.get("name_of_the_applicant") or fields.get("corrected_name"),
                            "business_type": fields.get("business_type") or fields.get("type_of_business"),
                            "business_revenue": fields.get("business_revenue") or fields.get("monthly_revenue") or fields.get("net_sales_present_year"),
                        }
                        for k, v in user_fields.items():
                            if v is not None:
                                existing_data[k] = v

                        # Merge new fields
                        for k, v in fields.items():
                            if k == "onboarding_finished":
                                if isinstance(v, str):
                                    existing_data[k] = v.lower() in ("true", "1", "yes")
                                else:
                                    existing_data[k] = bool(v)
                            elif v is not None and v != "":
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

            with get_db_cursor(self._db_pool) as cur:
                doc_id = str(uuid.uuid4())
                cur.execute(
                    """INSERT INTO docs (id, key, user_id, doc_type, name, created_at, updated_at)
                       VALUES (%s, %s, %s, %s, %s, NOW(), NOW())""",
                    (doc_id, request.key, request.session_id, db_doc_type, request.name)
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
                    "SELECT id, key, doc_type, name FROM docs WHERE user_id = %s",
                    (session_id,)
                )
                rows = cur.fetchall()
                docs_list = []
                for r in rows:
                    docs_list.append(pb2.DocumentItem(
                        id=str(r[0]),
                        key=r[1],
                        doc_type=str(r[2]),
                        name=r[3] or ""
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
