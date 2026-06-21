import re
from typing import Dict, Any, List

from utils.prompts import DOCUMENT_SCHEMAS
from utils.helpers import normalize_digits, try_normalize_date, normalize_pan, up_name, is_valid_string, fill_nulls

# ── confidence helpers ──────────────────────────────────────────────
def _copy_confidence(src: Dict[str,Any], dest: Dict[str,Any], field: str) -> None:
    """Copy a single {field}_confidence key if present."""
    key = f"{field}_confidence"
    if key in src:
        dest[key] = src[key]

def _copy_sub_confidence(src: Dict[str,Any], dest: Dict[str,Any], fields: List[str]) -> None:
    """Copy confidence for a list of fields."""
    for f in fields:
        _copy_confidence(src, dest, f)

# ── builders ────────────────────────────────────────────────────────

def build_aadhaar_response(parsed: Dict[str,Any]) -> Dict[str,Any]:
    clean = {"is_aadhaar": parsed.get("is_aadhaar", False)}
    holder = parsed.get("holder") or {}
    clean["holder"] = {
        "full_name": up_name(holder.get("full_name")),
        "date_of_birth": try_normalize_date(holder.get("date_of_birth")),
        "year_of_birth": normalize_digits(holder.get("year_of_birth")),
        "gender": up_name(holder.get("gender"))
    }
    _copy_sub_confidence(holder, clean["holder"], ["full_name", "date_of_birth", "year_of_birth", "gender"])

    clean["aadhaar_number"] = normalize_digits(parsed.get("aadhaar_number"))
    _copy_confidence(parsed, clean, "aadhaar_number")

    addr = parsed.get("address") or {}
    clean["address"] = {
        "care_of": up_name(addr.get("care_of")),
        "full_address_string": addr.get("full_address_string"),
        "house_number": addr.get("house_number"),
        "street": up_name(addr.get("street")),
        "locality": up_name(addr.get("locality")),
        "village_town_city": up_name(addr.get("village_town_city")),
        "subdistrict": up_name(addr.get("subdistrict")),
        "district": up_name(addr.get("district")),
        "state": up_name(addr.get("state")),
        "pincode": normalize_digits(addr.get("pincode")),
        "po": up_name(addr.get("po"))
    }
    _copy_sub_confidence(addr, clean["address"], [
        "care_of", "full_address_string", "house_number", "street",
        "locality", "village_town_city", "subdistrict", "district",
        "state", "pincode", "po"
    ])
    return clean

def build_pan_response(parsed: Dict[str,Any]) -> Dict[str,Any]:
    clean = {"is_pan": parsed.get("is_pan", False)}
    holder = parsed.get("holder") or {}
    clean["holder"] = {
        "full_name": up_name(holder.get("full_name")),
        "fathers_name": up_name(
            holder.get("fathers_name") or holder.get("father_or_husband_name")
            or holder.get("father_name")
        ),
        "date_of_birth": try_normalize_date(holder.get("date_of_birth")),
        "year_of_birth": normalize_digits(holder.get("year_of_birth")),
    }
    _copy_sub_confidence(holder, clean["holder"], [
        "full_name", "fathers_name", "father_or_husband_name", "date_of_birth", "year_of_birth"
    ])

    pan_num = normalize_pan(parsed.get("pan_number"))
    clean["pan_number"] = pan_num
    _copy_confidence(parsed, clean, "pan_number")

    # Derive pan_format_valid if LLM didn't provide it
    pan_format_valid = parsed.get("pan_format_valid")
    if pan_format_valid is None and pan_num:
        pan_format_valid = bool(re.match(r'^[A-Z]{5}\d{4}[A-Z]$', pan_num))
    clean["pan_format_valid"] = pan_format_valid
    return clean

def build_voter_response(parsed: Dict[str,Any], face: str) -> Dict[str,Any]:
    clean = {"is_voter_id": parsed.get("is_voter_id", False)}

    # LLM returns personal_details/card_metadata/demographic_details (per VOTER_PROMPT).
    # Fall back to old holder/parsed keys for backward compatibility.
    personal = parsed.get("personal_details") or {}
    card_meta = parsed.get("card_metadata") or {}
    demographics = parsed.get("demographic_details") or {}
    holder = parsed.get("holder") or {}  # fallback

    if face == "front":
        clean["holder"] = {
            "full_name": up_name(personal.get("full_name") or holder.get("full_name")),
            "father_or_spouse_name": up_name(
                personal.get("father_name") or personal.get("relative_name")
                or holder.get("relative_name") or holder.get("father_or_spouse_name")
            ),
            "relative_type": up_name(personal.get("relative_type") or holder.get("relative_type")),
            "gender": up_name(demographics.get("gender") or holder.get("gender")),
            "date_of_birth": try_normalize_date(
                demographics.get("date_of_birth") or holder.get("date_of_birth")
            ),
            "year_of_birth": demographics.get("year_of_birth") or holder.get("year_of_birth"),
            "age": normalize_digits(str(demographics.get("age") or holder.get("age") or ""))
        }
        # Copy confidence from whichever source has the data
        for src in [personal, demographics, holder]:
            _copy_sub_confidence(src, clean["holder"], [
                "full_name", "father_or_spouse_name", "relative_type",
                "gender", "date_of_birth", "year_of_birth", "age"
            ])

        clean["epic_number"] = up_name(
            card_meta.get("epic_number") or parsed.get("epic_number")
        )
        _copy_confidence(card_meta or parsed, clean, "epic_number")

        # Constituency from issuing_details or top-level
        issuing = parsed.get("issuing_details") or {}
        clean["constituency"] = up_name(
            issuing.get("assembly_constituency") or parsed.get("constituency")
        )
    else:
        addr = parsed.get("address_details") or parsed.get("address") or {}
        clean["address"] = {
            "full_address_string": addr.get("full_address_string"),
            "house": up_name(addr.get("house")),
            "street": up_name(addr.get("street")),
            "locality": up_name(addr.get("locality")),
            "vtc": up_name(addr.get("vtc")),
            "tehsil": up_name(addr.get("tehsil")),
            "district": up_name(addr.get("district")),
            "state": up_name(addr.get("state")),
            "pincode": normalize_digits(addr.get("pincode"))
        }
        _copy_sub_confidence(addr, clean["address"], [
            "full_address_string", "house", "street", "locality",
            "vtc", "tehsil", "district", "state", "pincode"
        ])

        # Back side may also have holder demographics
        clean["holder"] = {
            "gender": up_name(demographics.get("gender") or holder.get("gender")),
            "date_of_birth": try_normalize_date(
                demographics.get("date_of_birth") or holder.get("date_of_birth")
            ),
            "year_of_birth": demographics.get("year_of_birth") or holder.get("year_of_birth"),
        }

        clean["epic_number"] = up_name(
            card_meta.get("epic_number") or parsed.get("epic_number")
        )
        _copy_confidence(card_meta or parsed, clean, "epic_number")
    return clean

def build_udyam_response(parsed: Dict[str,Any]) -> Dict[str,Any]:
    enterprise = parsed.get("enterprise") or {}
    official_addr = enterprise.get("official_address") or {}
    registration = parsed.get("registration") or {}
    classification = enterprise.get("classification") or {}

    clean = {
        "is_udyam": parsed.get("is_udyam", False),
        "udyam_number": up_name(
            enterprise.get("udyam_registration_number") or parsed.get("udyam_number")
        ),
        "enterprise": {
            "enterprise_name": up_name(
                enterprise.get("enterprise_name") or enterprise.get("name")
            ),
            "type_of_enterprise": up_name(enterprise.get("type_of_enterprise")),
            "major_activity": up_name(enterprise.get("major_activity")),
            "social_category": up_name(
                enterprise.get("social_category") or enterprise.get("social_category_of_entrepreneur")
            ),
            "gender": up_name(enterprise.get("gender")),
            "date_of_incorporation": try_normalize_date(
                enterprise.get("date_of_incorporation_or_registration")
                or enterprise.get("date_of_incorporation")
            ),
            "classification": {
                "enterprise_category": up_name(classification.get("enterprise_category")),
                "classification_year": classification.get("classification_year"),
                "classification_date": try_normalize_date(classification.get("classification_date")),
            },
            "units": enterprise.get("units") or {},
        },
        "business_address": {
            "flat_door_block": up_name(official_addr.get("flat_door_block_no") or official_addr.get("flat_door_block")),
            "building_name": up_name(official_addr.get("name_of_premises_building") or official_addr.get("building_name")),
            "village_town": up_name(official_addr.get("village_town")),
            "road_street_lane": up_name(official_addr.get("road_street_lane")),
            "city": up_name(official_addr.get("city")),
            "district": up_name(official_addr.get("district")),
            "state": up_name(official_addr.get("state")),
            "pincode": normalize_digits(official_addr.get("pincode")),
        },
        "contact_details": {
            "mobile": official_addr.get("mobile") or (parsed.get("contact_details") or {}).get("mobile"),
            "email": official_addr.get("email") or (parsed.get("contact_details") or {}).get("email"),
        },
        "registration": {
            "date_of_incorporation": try_normalize_date(registration.get("date_of_incorporation")),
            "date_of_commencement": try_normalize_date(registration.get("date_of_commencement")),
            "date_of_registration": try_normalize_date(
                registration.get("date_of_registration")
                or enterprise.get("date_of_commencement_of_business")
            ),
        },
        "registration_status": {
            "is_manufacturing": parsed.get("registration_status", {}).get("is_manufacturing"),
            "is_service": parsed.get("registration_status", {}).get("is_service")
        }
    }
    _copy_confidence(enterprise, clean, "udyam_registration_number")
    if "udyam_registration_number_confidence" in enterprise:
        clean["udyam_number_confidence"] = enterprise["udyam_registration_number_confidence"]
    _copy_sub_confidence(enterprise, clean["enterprise"], [
        "enterprise_name", "type_of_enterprise", "major_activity",
        "social_category", "gender", "date_of_incorporation"
    ])
    _copy_sub_confidence(official_addr, clean["business_address"], [
        "flat_door_block", "building_name", "village_town",
        "road_street_lane", "city", "district", "state", "pincode"
    ])
    _copy_sub_confidence(official_addr, clean["contact_details"], ["mobile", "email"])
    return clean

def build_bank_response(parsed: Dict[str,Any]) -> Dict[str,Any]:
    clean = {"is_bank_statement": parsed.get("is_bank_statement", False)}
    acc = parsed.get("account_details") or {}
    clean["account_details"] = {
        "account_number": normalize_digits(acc.get("account_number")),
        "account_name": up_name(acc.get("account_name")),
        "ifsc_code": up_name(acc.get("ifsc_code")),
        "bank_name": up_name(acc.get("bank_name")),
        "branch_name": up_name(acc.get("branch_name"))
    }
    _copy_sub_confidence(acc, clean["account_details"], [
        "account_number", "account_name", "ifsc_code", "bank_name", "branch_name"
    ])

    period = parsed.get("statement_period") or {}
    clean["statement_period"] = {
        "from_date": try_normalize_date(period.get("from_date")),
        "to_date": try_normalize_date(period.get("to_date"))
    }
    _copy_sub_confidence(period, clean["statement_period"], ["from_date", "to_date"])

    bals = parsed.get("balances") or {}
    clean["balances"] = {
        "opening_balance": bals.get("opening_balance"),
        "closing_balance": bals.get("closing_balance")
    }
    _copy_sub_confidence(bals, clean["balances"], ["opening_balance", "closing_balance"])

    clean["fraud_indicators"] = parsed.get("fraud_indicators", {})
    return clean

def build_clean_response(parsed: Dict[str,Any], schema_key: str) -> Dict[str,Any]:
    if schema_key.startswith("aadhaar"):
        clean = build_aadhaar_response(parsed)
    elif schema_key.startswith("pan"):
        clean = build_pan_response(parsed)
    elif schema_key.startswith("voter"):
        face = "front" if "front" in schema_key else "back"
        clean = build_voter_response(parsed, face)
    elif schema_key.startswith("udyam"):
        clean = build_udyam_response(parsed)
    elif schema_key.startswith("bank_statement"):
        clean = build_bank_response(parsed)
    else:
        clean = parsed

    if "warnings" in parsed:
        clean["warnings"] = parsed["warnings"]

    if schema_key in DOCUMENT_SCHEMAS:
        fill_nulls(clean, DOCUMENT_SCHEMAS[schema_key])
        
    return clean
