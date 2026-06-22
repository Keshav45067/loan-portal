import os
import io
import cv2
import numpy as np
from PIL import Image, ExifTags
from typing import Optional

HAAR_PATHS = [
    cv2.data.haarcascades + "haarcascade_frontalface_default.xml",
    "haarcascade_frontalface_default.xml",
]

face_cascade = None
for p in HAAR_PATHS:
    if os.path.exists(p):
        face_cascade = cv2.CascadeClassifier(p)
        break

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 1. Extraction Prompts (Default Fallbacks)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

AADHAAR_PROMPT = """
You are a document extractor for Indian Aadhaar cards.
Decide if the images together represent a valid Aadhaar card. If not, return {}.
If yes, extract only the clearly readable fields based on the schema below.
Omit any key that is not clearly readable with high confidence. Do not use null, empty strings, or guesses.

JSON SCHEMA:
{
  "is_aadhaar": true,
  "document_type": "aadhaar_card",
  "holder": {
    "full_name": "string",
    "full_name_confidence": "high"|"medium"|"low",
    "date_of_birth": "DD-MM-YYYY",
    "date_of_birth_confidence": "high"|"medium"|"low",
    "year_of_birth": "YYYY",
    "year_of_birth_confidence": "high"|"medium"|"low",
    "gender": "MALE"|"FEMALE"|"OTHER",
    "gender_confidence": "high"|"medium"|"low"
  },
  "aadhaar_number": "12-digit string (digits only)",
  "aadhaar_number_confidence": "high"|"medium"|"low",
  "address": { // only if back side is clearly visible
    "care_of": "string", "care_of_confidence": "high"|"medium"|"low",
    "house": "string", "house_confidence": "high"|"medium"|"low",
    "street": "string", "street_confidence": "high"|"medium"|"low",
    "landmark": "string", "landmark_confidence": "high"|"medium"|"low",
    "locality": "string", "locality_confidence": "high"|"medium"|"low",
    "vtc": "string", "vtc_confidence": "high"|"medium"|"low",
    "district": "string", "district_confidence": "high"|"medium"|"low",
    "state": "string", "state_confidence": "high"|"medium"|"low",
    "pincode": "6-digit string", "pincode_confidence": "high"|"medium"|"low"
  },
  "warnings": ["array of strings"]
}
If only the front side is provided, omit the "address" key and add a warning "Only front side provided — address omitted".
"""

PAN_PROMPT = """
You are a document extractor for Indian PAN cards.
Decide if the images represent a valid PAN card. If not, return {}.
If yes, extract only the fields clearly readable with high confidence based on the schema below.
Omit any key that is not clearly readable. Do not use null, empty strings, or placeholders.

JSON SCHEMA:
{
  "is_pan": true,
  "document_type": "pan_card",
  "holder": {
    "full_name": "string",
    "full_name_confidence": "high"|"medium"|"low",
    "father_or_husband_name": "string",
    "father_or_husband_name_confidence": "high"|"medium"|"low",
    "date_of_birth": "DD-MM-YYYY",
    "date_of_birth_confidence": "high"|"medium"|"low"
  },
  "pan_number": "10-character string (uppercase, matching pattern AAAAA9999A)",
  "pan_number_confidence": "high"|"medium"|"low",
  "pan_format_valid": true,
  "warnings": ["array of strings"]
}
"""

VOTER_PROMPT = """
You are a document extractor for Indian Voter ID (EPIC) cards.
Decide if the images represent a valid Voter ID. If not, return {}.
If yes, extract only the fields clearly readable with high confidence.
Omit any key that is not clearly readable. Do not use null, empty strings, or placeholders.

JSON SCHEMA:
{
  "is_voter_id": true,
  "document_type": "voter_id",
  "card_metadata": {
    "epic_number": "string", "epic_number_confidence": "high"|"medium"|"low",
    "side_visible": "FRONT"|"BACK"|"BOTH"
  },
  "personal_details": {
    "full_name": "string", "full_name_confidence": "high"|"medium"|"low",
    "relative_name": "string", "relative_name_confidence": "high"|"medium"|"low",
    "relative_type": "FATHER"|"MOTHER"|"HUSBAND"
  },
  "demographic_details": {
    "gender": "MALE"|"FEMALE"|"OTHER", "gender_confidence": "high"|"medium"|"low",
    "date_of_birth": "DD-MM-YYYY", "date_of_birth_confidence": "high"|"medium"|"low",
    "year_of_birth": "YYYY", "year_of_birth_confidence": "high"|"medium"|"low",
    "age": number, "age_confidence": "high"|"medium"|"low"
  },
  "address_details": { // only if back side is visible
    "house": "string", "house_confidence": "high"|"medium"|"low",
    "street": "string", "street_confidence": "high"|"medium"|"low",
    "locality": "string", "locality_confidence": "high"|"medium"|"low",
    "vtc": "string", "vtc_confidence": "high"|"medium"|"low",
    "district": "string", "district_confidence": "high"|"medium"|"low",
    "state": "string", "state_confidence": "high"|"medium"|"low",
    "pincode": "6-digit string", "pincode_confidence": "high"|"medium"|"low"
  },
  "issuing_details": {
    "assembly_constituency": "string", "assembly_constituency_confidence": "high"|"medium"|"low"
  },
  "warnings": ["array of strings"]
}
"""

UDYAM_PROMPT = """
You are a document extractor for Indian Udyam Registration certificates.
Decide if the image represents a valid Udyam certificate. If not, return {}.
If yes, extract only the fields clearly readable with high confidence.
Omit any key that is not clearly readable. Do not use null, empty strings, or placeholders.

JSON SCHEMA:
{
  "is_udyam": true,
  "document_type": "udyam_certificate",
  "enterprise": {
    "udyam_registration_number": "string (format UDYAM-XX-00-0000000)",
    "udyam_registration_number_confidence": "high"|"medium"|"low",
    "enterprise_name": "string",
    "enterprise_name_confidence": "high"|"medium"|"low",
    "type_of_enterprise": "MICRO"|"SMALL"|"MEDIUM",
    "type_of_enterprise_confidence": "high"|"medium"|"low",
    "major_activity": "string",
    "major_activity_confidence": "high"|"medium"|"low",
    "social_category": "string",
    "social_category_confidence": "high"|"medium"|"low",
    "organization_type": "string",
    "organization_type_confidence": "high"|"medium"|"low",
    "date_of_incorporation_or_registration": "YYYY-MM-DD",
    "date_of_incorporation_or_registration_confidence": "high"|"medium"|"low",
    "date_of_commencement_of_business": "YYYY-MM-DD",
    "date_of_commencement_of_business_confidence": "high"|"medium"|"low",
    "official_address": {
      "flat_door_block_no": "string",
      "name_of_premises_building": "string",
      "village_town": "string",
      "block": "string",
      "road_street_lane": "string",
      "district": "string",
      "state": "string",
      "pincode": "6-digit string",
      "mobile": "string",
      "email": "string"
    }
  },
  "registration": {
    "date_of_registration": "YYYY-MM-DD"
  }
}
"""

BANK_STATEMENT_PROMPT = """
You are a document extractor for Indian Bank Statements.
Decide if the image represents a valid bank statement. If not, return {}.
If yes, extract only the fields clearly readable with high confidence.

JSON SCHEMA:
{
  "is_bank_statement": true,
  "document_type": "bank_statement",
  "holder": {
    "full_name": "string", "full_name_confidence": "high"|"medium"|"low",
    "date_of_birth": "YYYY-MM-DD", "date_of_birth_confidence": "high"|"medium"|"low",
    "year_of_birth": "YYYY", "year_of_birth_confidence": "high"|"medium"|"low"
  },
  "bank": {
    "name": "string", "name_confidence": "high"|"medium"|"low",
    "branch": "string", "branch_confidence": "high"|"medium"|"low",
    "ifsc": "string", "ifsc_confidence": "high"|"medium"|"low"
  },
  "statement_period": {
    "from_date": "YYYY-MM-DD", "from_date_confidence": "high"|"medium"|"low",
    "to_date": "YYYY-MM-DD", "to_date_confidence": "high"|"medium"|"low"
  },
  "account": {
    "account_number": "string", "account_number_confidence": "high"|"medium"|"low",
    "customer_id": "string", "customer_id_confidence": "high"|"medium"|"low",
    "account_type": "SAVINGS"|"CURRENT"
  },
  "raw_text": "string",
  "warnings": ["array of strings"]
}
"""

OFFICE_ID_PROMPT = """
You are a document extractor for Employee/Office ID cards.
Decide if the image represents a valid Office ID card. If not, return {}.
If yes, extract only the fields clearly readable with high confidence.

JSON SCHEMA:
{
  "is_office_id": true,
  "document_type": "office_id",
  "organization_name": "string",
  "organization_name_confidence": "high"|"medium"|"low",
  "place_of_posting": "string",
  "place_of_posting_confidence": "high"|"medium"|"low",
  "designation": "string",
  "designation_confidence": "high"|"medium"|"low",
  "employee_name": "string",
  "employee_name_confidence": "high"|"medium"|"low",
  "employee_id": "string",
  "employee_id_confidence": "high"|"medium"|"low"
}
"""

ADDRESS_PROOF_PROMPT = """
You are a document extractor for address proof documents (utility bills, rent agreements, etc.).
Decide if the image represents a valid address proof. If not, return {}.
If yes, extract only the fields clearly readable with high confidence.

JSON SCHEMA:
{
  "is_address_proof": true,
  "document_type": "address_proof",
  "holder_name": "string",
  "holder_name_confidence": "high"|"medium"|"low",
  "address": {
    "house": "string", "house_confidence": "high"|"medium"|"low",
    "street": "string", "street_confidence": "high"|"medium"|"low",
    "locality": "string", "locality_confidence": "high"|"medium"|"low",
    "district": "string", "district_confidence": "high"|"medium"|"low",
    "state": "string", "state_confidence": "high"|"medium"|"low",
    "pincode": "6-digit string", "pincode_confidence": "high"|"medium"|"low",
    "country": "string", "country_confidence": "high"|"medium"|"low"
  }
}
"""

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 2. Verification Prompts (Default Fallbacks)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

AADHAAR_VERIFY_PROMPT = """
Analyze the image. Decide if it represents a valid Indian Aadhaar card.
Return exactly:
{"is_aadhaar": true/false}
"""

PAN_VERIFY_PROMPT = """
Analyze the image. Decide if it represents a valid Indian PAN card and extract the cardholder name if visible.
Return exactly:
{
  "is_pan": true/false,
  "holder_name": "string" or null,
  "warnings": ["array of strings"]
}
"""

VOTER_VERIFY_PROMPT = """
Analyze the image. Decide if it represents a valid Indian Voter ID card and extract the voter's name if visible.
Return exactly:
{
  "is_voterid": true/false,
  "holder_name": "string" or null,
  "warnings": ["array of strings"]
}
"""

UDYAM_VERIFY_PROMPT = """
Analyze the image. Decide if it represents a valid Udyam Registration certificate and extract the enterprise name.
Return exactly:
{
  "is_udyam": true/false,
  "enterprise_name": "string" or null,
  "warnings": ["array of strings"]
}
"""

BANK_STATEMENT_VERIFY_PROMPT = """
Analyze the image. Decide if it represents a valid bank statement and extract the statement period.
Return exactly:
{
  "is_bank_statement": true/false,
  "document_type": "bank_statement",
  "confidence": "high"|"medium"|"low",
  "statement_period": {
    "from_date": "DD-MM-YYYY",
    "to_date": "DD-MM-YYYY"
  }
}
"""

OFFICE_ID_VERIFY_PROMPT = """
Analyze the image. Decide if it is a valid employee/office ID card.
Return exactly:
{"is_office_id": true/false}
"""

ADDRESS_PROOF_VERIFY_PROMPT = """
Analyze the image. Decide if it acts as a valid address proof (utility bill, rent agreement, etc.).
Return exactly:
{"is_address_proof": true/false}
"""

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 3. Image Pre-processing & Autorotating Utilities
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def pil_autorotate(img: Image.Image) -> Image.Image:
    try:
        exif = img._getexif()
        if not exif:
            return img
        orient_tag = None
        for k, v in ExifTags.TAGS.items():
            if v == "Orientation":
                orient_tag = k
                break
        if orient_tag is None:
            return img
        orient = exif.get(orient_tag, None)
        if orient == 3:
            img = img.rotate(180, expand=True)
        elif orient == 6:
            img = img.rotate(270, expand=True)
        elif orient == 8:
            img = img.rotate(90, expand=True)
    except Exception:
        pass
    return img

def preprocess_for_model(pil_img: Image.Image, max_dim: int = 1600) -> Image.Image:
    img = pil_autorotate(pil_img)
    w, h = img.size
    scale = min(1.0, max_dim / max(w, h))
    if scale < 1.0:
        img = img.resize((int(w*scale), int(h*scale)), Image.LANCZOS)
    cv_img = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
    ycrcb = cv2.cvtColor(cv_img, cv2.COLOR_BGR2YCrCb)
    y, cr, cb = cv2.split(ycrcb)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
    y2 = clahe.apply(y)
    ycrcb2 = cv2.merge([y2, cr, cb])
    cv_img2 = cv2.cvtColor(ycrcb2, cv2.COLOR_YCrCb2BGR)
    cv_img2 = cv2.bilateralFilter(cv_img2, d=9, sigmaColor=75, sigmaSpace=75)
    gaussian = cv2.GaussianBlur(cv_img2, (0,0), sigmaX=3)
    cv_img2 = cv2.addWeighted(cv_img2, 1.5, gaussian, -0.5, 0)
    pil_out = Image.fromarray(cv2.cvtColor(cv_img2, cv2.COLOR_BGR2RGB))
    return pil_out

def local_face_crop_bytes(pil_img: Image.Image) -> Optional[bytes]:
    if face_cascade is None:
        return None
    cv_img = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
    gray = cv2.cvtColor(cv_img, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape[:2]
    scale = 800.0 / max(h, w) if max(h, w) > 800 else 1.0
    small = cv2.resize(gray, (int(w*scale), int(h*scale)))
    faces = face_cascade.detectMultiScale(small, scaleFactor=1.1, minNeighbors=4, minSize=(30,30))
    if len(faces) == 0:
        return None
    faces = sorted(faces, key=lambda r: r[2]*r[3], reverse=True)
    x, y, fw, fh = faces[0]
    x0 = int(x / scale)
    y0 = int(y / scale)
    x1 = int((x + fw) / scale)
    y1 = int((y + fh) / scale)
    pad_w = int((x1-x0) * 0.25)
    pad_h = int((y1-y0) * 0.45)
    x0 = max(0, x0 - pad_w)
    y0 = max(0, y0 - pad_h)
    x1 = min(w, x1 + pad_w)
    y1 = min(h, y1 + pad_h)
    face_crop = pil_img.crop((x0, y0, x1, y1))
    buf = io.BytesIO()
    face_crop.save(buf, format="PNG")
    return buf.getvalue()

def crop_by_normalized_bbox(pil_img: Image.Image, bbox: dict) -> Optional[bytes]:
    try:
        w, h = pil_img.size
        x = int(round(bbox["x"] * w))
        y = int(round(bbox["y"] * h))
        bw = int(round(bbox["w"] * w))
        bh = int(round(bbox["h"] * h))
        x2 = max(0, min(w, x + bw))
        y2 = max(0, min(h, y + bh))
        x1 = max(0, min(w, x))
        y1 = max(0, min(h, y))
        if x2 <= x1 or y2 <= y1:
            return None
        crop = pil_img.crop((x1, y1, x2, y2))
        buf = io.BytesIO()
        crop.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        return None

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 4. Fallback Document Schemas (fill_nulls)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

DOCUMENT_SCHEMAS = {
    "aadhaar_front": {
        "is_aadhaar": True, "document_type": True,
        "holder": {"full_name": True, "date_of_birth": True, "year_of_birth": True, "gender": True},
        "aadhaar_number": True, "language": True, "raw_text": True, "warnings": True
    },
    "aadhaar_back": {
        "is_aadhaar": True, "document_type": True,
        "address": {"care_of": True, "house": True, "street": True, "landmark": True, "locality": True, "vtc": True, "district": True, "state": True, "pincode": True},
        "language": True, "raw_text": True, "warnings": True
    },
    "pan": {
        "is_pan": True, "document_type": True,
        "holder": {"full_name": True, "father_name": True, "date_of_birth": True, "year_of_birth": True},
        "pan_number": True, "pan_format_valid": True, "raw_text": True, "warnings": True
    },
    "voter_front": {
        "is_voter_id": True, "document_type": True,
        "holder": {"full_name": True, "father_or_spouse_name": True, "date_of_birth": True, "year_of_birth": True, "gender": True},
        "epic_number": True, "constituency": True, "raw_text": True, "warnings": True
    },
    "voter_back": {
        "is_voter_id": True, "document_type": True,
        "holder": {"gender": True, "date_of_birth": True, "year_of_birth": True},
        "address": {"vtc": True, "district": True, "state": True, "pincode": True},
        "raw_text": True, "warnings": True
    },
    "udyam": {
        "is_udyam": True, "document_type": "udyam_registration_certificate",
        "enterprise": {"enterprise_name": True, "udyam_registration_number": True, "type_of_enterprise": True,
        "classification": {"enterprise_category": True, "classification_year": True, "classification_date": True},
        "major_activity": True, "social_category_of_entrepreneur": True,
        "units": {"number_of_units": True,"unit_names": True}},
        "business_address": {"flat_door_block": True, "building_name": True, "village_town": True,
        "road_street_lane": True, "city": True, "district": True, "state": True, "pincode": True},
        "contact_details": {"mobile": True, "email": True},
        "registration": {"date_of_incorporation": True, "date_of_commencement": True, "date_of_registration": True},
        "raw_text": True, "warnings": True
    },
    "bank_statement": {
        "is_bank_statement": True, "document_type": True,
        "holder": {"full_name": True, "date_of_birth": True, "year_of_birth": True},
        "bank": {"name": True, "branch": True, "ifsc": True},
        "statement_period": {"from_date": True, "to_date": True},
        "account": {"account_number": True, "customer_id": True, "account_type": True},
        "raw_text": True, "warnings": True
    },
    "office_id": {
        "is_office_id": True, "document_type": True,
        "organization_name": True, "place_of_posting": True,
        "designation": True, "employee_name": True, "employee_id": True
    },
    "address_proof": {
        "is_address_proof": True, "document_type": True,
        "holder_name": True,
        "address": {
            "house": True, "street": True, "locality": True,
            "district": True, "state": True, "pincode": True, "country": True
        }
    }
}
