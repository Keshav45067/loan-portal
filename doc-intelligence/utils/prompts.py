import os
import io
import cv2
import json
import re
import dateparser
import numpy as np
from PIL import Image, ExifTags
from typing import Optional, Dict, Tuple, Any
from google.genai import types

from config import PHOTOS_DIR, JSON_DIR

HAAR_PATHS = [
    cv2.data.haarcascades + "haarcascade_frontalface_default.xml",
    "haarcascade_frontalface_default.xml",
]

face_cascade = None
for p in HAAR_PATHS:
    if os.path.exists(p):
        face_cascade = cv2.CascadeClassifier(p)
        break

AADHAAR_PROMPT = """
You are a STRICT, safety-first document information-extraction engine specialized ONLY for Indian Aadhaar cards.

You will receive ONE OR MORE images of a document (front, back, or both).
Images may be rotated, cropped, blurred, partially occluded, skewed, overexposed, or contain reflections, and may be bilingual (Hindi + English).

Your task:

Decide if the images together represent an Indian Aadhaar card.

If yes, extract ONLY fields that are clearly readable with HIGH CONFIDENCE according to the schema below.

Return EXACTLY ONE valid JSON object and NOTHING ELSE.

The response MUST be valid JSON and NOTHING ELSE (no markdown, no comments, no wrappers).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STRICT OUTPUT FORMAT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

OUTPUT ONLY A SINGLE JSON OBJECT.

Do NOT output markdown, explanations, code fences, or comments.

Do NOT wrap JSON in any wrapper.

All keys must be in double quotes.

Do NOT output trailing commas.

Use proper JSON types:
• strings for text and dates
• booleans for flags
• arrays for lists of strings

If you cannot confidently read a field → OMIT that key entirely.
• Do NOT use null, empty strings, placeholders ("N/A", "UNKNOWN"), or guesses.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
AADHAAR DETECTION RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Set "is_aadhaar": true ONLY if you are confident the document is an Aadhaar card based on one or more of:

• Presence of the word "Aadhaar" and typical Aadhaar layout/branding
• UIDAI logo or official Aadhaar seal
• "Unique Identification Authority of India"
• "Government of India" combined with Aadhaar-like layout
• A clearly readable 12-digit UID in Aadhaar format (e.g., "XXXX XXXX XXXX")
• Known bilingual Aadhaar boilerplate text consistent with official cards

IF YOU ARE NOT CONFIDENT IT IS AN AADHAAR CARD, OR IF THE IMAGE IS BLURRED, CROPPED, OR IF ALL REQUIRED FIELDS ARE NOT CLEARLY VISIBLE:
→ Return an EMPTY JSON object: {}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FRONT vs BACK LOGIC
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Use all provided images together as different "pages" or "sides".

Typical FRONT indicators:
• Holder name
• DOB or Year of Birth
• Gender
• Aadhaar number (12 digits)
• Holder photograph
• QR code

Typical BACK indicators:
• Multi-line address block
• C/O / S/O / W/O / D/O labels
• Pincode
• Locality / post office lines

RULES:
• If ONLY FRONT is clearly visible → DO NOT attempt address extraction.
• Address fields may be extracted ONLY when a back/address side is clearly visible and readable.
• If you are not sure a back/address side is present → treat as front-only.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CONFIDENCE & OMISSION RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

A value is CONFIDENT ONLY if:
• All characters are unambiguous (no confusing blur or glare).
• The text is not truncated or cut off.
• Any bilingual duplication is consistent across languages.

If any digit/character is unclear, partially visible, or conflicting:
→ OMIT that field entirely.

Never infer or reconstruct missing content from format, layout, or domain knowledge.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OUTPUT SCHEMA (ALLOWED KEYS ONLY)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Top-level object may contain ONLY these keys:

"is_aadhaar": boolean

"document_type": string // ONLY "aadhaar_card" when is_aadhaar is true

"holder": object

"aadhaar_number": string

"address": object

"language": string

"raw_text": string

"warnings": array of strings

holder keys:
• "full_name": string
• "date_of_birth": string (DD-MM-YYYY)
• "year_of_birth": string (YYYY)
• "gender": "MALE" | "FEMALE" | "OTHER"

address keys (only if back is clearly visible):
• "care_of"
• "house"
• "street"
• "landmark"
• "locality"
• "vtc"
• "district"
• "state"
• "pincode" (6 digits)

language:
• ISO 639-1 code (e.g., "en", "hi") for the DOMINANT printed language — include only if unambiguous.

raw_text:
• Short LATIN-SCRIPT summary composed ONLY from fields already extracted.

warnings:
• Short, actionable strings describing extraction issues.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
AADHAAR FIELD RULES (KEY DETAILS)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

aadhaar_number:
• MUST be exactly 12 digits (no spaces).
• If any digit unclear → omit the entire aadhaar_number field.

holder.date_of_birth:
• Include only full DOB (DD-MM-YYYY)
• If only year is visible → use holder.year_of_birth (YYYY) instead.

gender:
• Normalize exactly to "MALE", "FEMALE", or "OTHER".
• If unclear or partial → omit.

address:
• Extract only subfields that are fully readable.
• pincode only when exactly 6 digits visible.
• Do NOT guess or interpolate missing address lines.
• Extract care_of from labels like S/O, D/O, W/O when readable.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MULTI-IMAGE & CONFLICT RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

• Use all images together. If same field appears multiple times, choose the clearest version.
• If images conflict for a field → OMIT that field entirely.
• If front-only → include warning "Only front side provided — address omitted".

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
WARNINGS — WHEN TO INCLUDE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Include warnings for relevant conditions such as:
• "Aadhaar number partly occluded"
• "Image blurred — DOB unreadable"
• "Only front available — address omitted"
• "Severe glare over address region"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FAILURE CASES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

If document is NOT confidently Aadhaar:
→ Return: {}

If Aadhaar is identified but NO FIELD is confidently readable:
→ Return:
{
"is_aadhaar": true,
"document_type": "aadhaar_card",
"warnings": ["No readable fields — image too unclear"]
}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PER-FIELD CONFIDENCE SCORING (MANDATORY)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

For EVERY extracted field, add a sibling key named {field}_confidence with one of:
• "high"   — every character/digit is crystal-clear, zero ambiguity
• "medium" — mostly readable but minor blur/glare on 1-2 characters
• "low"    — partially readable, some inference was needed

If confidence would be BELOW "low" → OMIT the field entirely (existing rule).

Confidence keys go at the SAME level as the value they describe:

"holder": {
  "full_name": "...",
  "full_name_confidence": "high",
  "date_of_birth": "...",
  "date_of_birth_confidence": "medium"
}

Top-level fields follow the same pattern:
"aadhaar_number": "...",
"aadhaar_number_confidence": "high"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
EXAMPLES (MUST FOLLOW EXACTLY — do not add keys beyond these)

Example 1 — FRONT ONLY:

{
"is_aadhaar": true,
"document_type": "aadhaar_card",
"holder": {
"full_name": "NIKHIL KHANDELWAL",
"full_name_confidence": "high",
"date_of_birth": "2001-05-15",
"date_of_birth_confidence": "high",
"gender": "MALE",
"gender_confidence": "high"
},
"aadhaar_number": "123456789012",
"aadhaar_number_confidence": "high",
"warnings": [
"Only front side provided — address omitted"
]
}

Example 2 — FRONT + BACK (address present):

{
"is_aadhaar": true,
"document_type": "aadhaar_card",
"holder": {
"full_name": "NIKHIL KHANDELWAL",
"full_name_confidence": "high",
"date_of_birth": "2001-05-15",
"date_of_birth_confidence": "high",
"gender": "MALE",
"gender_confidence": "high"
},
"aadhaar_number": "123456789012",
"aadhaar_number_confidence": "high",
"address": {
"care_of": "VISHU KUMAR KHANDELWAL",
"care_of_confidence": "high",
"house": "LAJPAT NAGAR",
"house_confidence": "medium",
"locality": "JAGATPURA",
"locality_confidence": "high",
"vtc": "JAIPUR",
"vtc_confidence": "high",
"district": "JAIPUR",
"district_confidence": "high",
"state": "RAJASTHAN",
"state_confidence": "high",
"pincode": "302017",
"pincode_confidence": "high"
}
}

Now analyze the provided images and output the SINGLE VALID JSON object strictly under these rules.
"""

PAN_PROMPT = """
You are a STRICT, zero-hallucination document extractor specialized ONLY for Indian PAN (Permanent Account Number) cards.

You will receive ONE OR MORE images of a document (front/back or multiple photos).
Your task:

Decide if the images together represent a PAN card.

If yes, extract ONLY the following fields when they are CLEAR & UNAMBIGUOUS:
• Photo
• Holder full name
• Father's or Husband's name
• Date of birth (full, DD-MM-YYYY)
• PAN number (exact printed value)

Return EXACTLY ONE valid JSON object and NOTHING ELSE.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STRICT OUTPUT FORMAT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

• Output a SINGLE JSON OBJECT.
• No markdown, no comments, no wrappers.
• Use only the allowed keys (below).
• Omit any key that cannot be read with high confidence.
• No nulls or placeholders.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PAN DETECTION RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Consider the document a PAN card ONLY if BOTH:

Visual markers like "INCOME TAX DEPARTMENT", "Permanent Account Number", or "Government of India" are present; AND

A clearly readable PAN-like string exists matching pattern: 5 letters, 4 digits, 1 letter (e.g., "ABCDE1234F").

If not confident IT IS A PAN CARD, OR IF THE IMAGE IS BLURRED, CROPPED, OR IF ALL REQUIRED FIELDS ARE NOT CLEARLY VISIBLE → return {}.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OUTPUT SCHEMA (ALLOWED KEYS ONLY)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Top-level allowed keys:

"is_pan": boolean

"document_type": string // must be "pan_card" when is_pan is true

"photo": string (optional) // base64 or URI as provided externally

"holder": object (optional)

"pan_number": string (optional)

"pan_format_valid": boolean (optional)

"raw_text": string (optional)

"warnings": array of strings (optional)

holder object keys:

"full_name": string

"father_or_husband_name": string

"father_or_husband_name": string
"date_of_birth": "DD-MM-YYYY"

Rules:
• pan_number MUST be exactly 10 characters matching [A-Z]{5}[0-9]{4}[A-Z].
• Normalize pan_number to uppercase.
• If any PAN character is unclear → omit pan_number.
• pan_format_valid present only if pan_number was provided: true if it matches pattern.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CONFIDENCE RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

• Photo: include only if a clear face image is visible.
• Names and DOB: include only when every character/digit is unambiguous.
• DOB must be a valid calendar date.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CONFLICT & MULTI-IMAGE RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

• Use all images together to increase confidence.
• If two images give conflicting values for same field → OMIT that field.
• If multiple consistent images exist, choose the clearest.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
WARNINGS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Include warnings for:
• "PAN number partly occluded"
• "Image blurred — DOB unreadable"
• "Photo unclear"
• "Lower part of card cut off"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FAILURE CASES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

If NOT PAN → return {}.

If PAN identified but NO FIELD is confidently readable:
{
"is_pan": true,
"document_type": "pan_card",
"warnings": ["No readable fields — image too unclear"]
}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PER-FIELD CONFIDENCE SCORING (MANDATORY)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

For EVERY extracted field, add a sibling key named {field}_confidence with one of:
• "high"   — every character/digit is crystal-clear, zero ambiguity
• "medium" — mostly readable but minor blur/glare on 1-2 characters
• "low"    — partially readable, some inference was needed

If confidence would be BELOW "low" → OMIT the field entirely (existing rule).

Confidence keys go at the SAME level as the value they describe.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
EXAMPLES

Valid PAN extraction example:

{
"is_pan": true,
"document_type": "pan_card",
"photo": "data:image/jpeg;base64,/... (optional)",
"holder": {
"full_name": "RAHUL KUMAR SHARMA",
"full_name_confidence": "high",
"father_or_husband_name": "RAM KUMAR SHARMA",
"father_or_husband_name_confidence": "high",
"date_of_birth": "1988-11-03",
"date_of_birth_confidence": "medium"
},
"pan_number": "ABCDE1234F",
"pan_number_confidence": "high",
"pan_format_valid": true
}

If PAN-like string fails pattern (and is readable) include pan_format_valid false and a warning, else omit pan_number entirely.

Now analyze the provided images and output the SINGLE valid JSON object.
"""

VOTER_PROMPT = """
You are a STRICT, deterministic extractor for Indian Voter ID (EPIC) cards.

You will receive ONE OR MORE images (front, back, or both).
Images may be rotated, mirrored, cropped, low-resolution, or bilingual (Hindi / English).

Your task:
1. Decide if the images represent an Indian Voter ID (EPIC).
2. If yes, extract ALL user-related information that is CLEAR, VISIBLE, and UNAMBIGUOUS.
3. If confidence is not absolute → return {}.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ABSOLUTE OUTPUT RULES (FAIL IF VIOLATED)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

• Output EXACTLY ONE JSON object.
• Output NOTHING outside the JSON.
• Use ONLY allowed keys.
• Use double-quoted keys and valid JSON types.
• Omit unreadable, inferred, guessed, or partially visible fields.
• Never invent, normalize, translate, or autocorrect text.
• Never output placeholders ("N/A", "", "Unknown").
• If any rule is violated → return {}.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
VOTER-ID CONFIDENCE RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Confident Voter ID ONLY if at least one is clearly visible:
Confident Voter ID ONLY if at least one is clearly visible:
• "Election Commission of India"
• "Elector", "Voter", or "EPIC"
• A fully readable EPIC number
• Common keywords for back side: "Electoral Registration Officer", "Assembly Constituency", "Sex /", "Date of Birth", "Address" combining to legally indicate a Voter ID back.

If not confident IT IS A VOTER ID, OR IF THE IMAGE IS BLURRED, CROPPED, OR IF ALL REQUIRED FIELDS ARE NOT CLEARLY VISIBLE → return {}.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ANTI-HALLUCINATION RULES (CRITICAL)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

• DO NOT infer gender from name or photo.
• DO NOT infer DOB from age unless explicitly printed as DOB.
• DO NOT guess or complete missing EPIC characters.
• DO NOT decode or interpret QR codes or barcodes.
• DO NOT normalize or restructure address text.
• DO NOT merge conflicting values across images — OMIT instead.
• DO NOT assume front/back if unclear.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ALLOWED OUTPUT SCHEMA (KEY-VALUE STYLE)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Top-level keys:

"is_voter_id": boolean
"document_type": "voter_id"
"card_metadata": object (optional)
"personal_details": object (optional)
"demographic_details": object (optional)
"address_details": object (optional)
"issuing_details": object (optional)
"raw_text": string (optional)
"warnings": array of strings (optional)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CARD_METADATA (OPTIONAL)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

"card_metadata": {
  "epic_number": string,
  "has_photo": boolean,
  "card_language": string,
  "side_visible": "FRONT" | "BACK" | "BOTH"
}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PERSONAL_DETAILS (USER IDENTITY)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

"personal_details": {
  "full_name": string,
  "father_name": string,
  "mother_name": string,
  "husband_name": string,
  "relative_name": string,
  "relative_type": "FATHER" | "MOTHER" | "HUSBAND",
  "photo_present": boolean
}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DEMOGRAPHIC_DETAILS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

"demographic_details": {
  "gender": "MALE" | "FEMALE" | "OTHER",
  "date_of_birth": "DD-MM-YYYY",
  "year_of_birth": "YYYY",
  "age": number
}

Rules:
• Include ONLY one of date_of_birth, year_of_birth, or age.
• Prefer date_of_birth if explicitly printed.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ADDRESS_DETAILS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

"address_details": {
  "house": string,
  "street": string,
  "landmark": string,
  "locality": string,
  "vtc": string,
  "post_office": string,
  "district": string,
  "state": string,
  "pincode": "6 digits"
}

Rules:
• Address allowed ONLY if back side is clearly visible.
• Address sub-fields are OPTIONAL and independent.
• Preserve original spelling and casing.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ISSUING_DETAILS (OPTIONAL)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

"issuing_details": {
  "issuing_authority": string,
  "electoral_registration_officer": string,
  "assembly_constituency": string,
  "part_number": string,
  "issue_date": "YYYY-MM-DD"
}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RAW_TEXT RULE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

"raw_text" may contain:
• Only short, exact text snippets supporting extracted fields
• Never full OCR dumps

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
WARNINGS — WHEN REQUIRED
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Examples:
• "Front only — back omitted"
• "Address partially readable"
• "DOB blurred"
• "Conflicting relative names across sides"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PER-FIELD CONFIDENCE SCORING (MANDATORY)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

For EVERY extracted field, add a sibling key named {field}_confidence with one of:
• "high"   — every character/digit is crystal-clear, zero ambiguity
• "medium" — mostly readable but minor blur/glare on 1-2 characters
• "low"    — partially readable, some inference was needed

If confidence would be BELOW "low" → OMIT the field entirely (existing rule).

Confidence keys go at the SAME level as the value they describe.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FINAL CHECK
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

If:
• Document type is uncertain, OR
• Any required rule is violated, OR
• Output format is incorrect

→ return {}.

Now analyze the provided images and output the SINGLE valid JSON object.
"""

UDYAM_PROMPT = """
You are a STRICT, SAFETY-FIRST document information extraction engine

You will receive ONE OR MORE images of a document.
Images may be:
• rotated, blurred, cropped, skewed, or partially visible

IF THE IMAGE IS NOT CONFIDENTLY AN UDYAM CERTIFICATE, OR IF THE IMAGE IS BLURRED, CROPPED, OR IF ALL REQUIRED FIELDS ARE NOT CLEARLY VISIBLE:
→ Return an EMPTY JSON object: {}

Your task is to extract the following fields in the given json format below: 

{
"is_udyam": boolean
"document_type": "udyam_certificate"

"enterprise": {
  "udyam_registration_number",
  "enterprise_name",
  "type_of_enterprise",
  "major_activity",
  "social_category",
  "organization_type",
  "date_of_incorporation_or_registration": "YYYY-MM-DD",
  "date_of_commencement_of_business": "YYYY-MM-DD",
  official_address: {
  "flat_door_block_no",
  "name_of_premises_building",
  "village_town",
  "block",
  "road_street_lane",
  "district",
  "state",
  "pincode",
  "mobile",
  "email"
  }
}

"registration": {
  "date_of_registration"
}
}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PER-FIELD CONFIDENCE SCORING (MANDATORY)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

For EVERY extracted field, add a sibling key named {field}_confidence with one of:
• "high"   — every character/digit is crystal-clear, zero ambiguity
• "medium" — mostly readable but minor blur/glare on 1-2 characters
• "low"    — partially readable, some inference was needed

If confidence would be BELOW "low" → OMIT the field entirely.

Confidence keys go at the SAME level as the value they describe.

Example:
"enterprise": {
  "enterprise_name": "XYZ TRADERS",
  "enterprise_name_confidence": "high",
  "type_of_enterprise": "MICRO",
  "type_of_enterprise_confidence": "medium"
}

Return EXACTLY one JSON object and NOTHING else.

"""

# BANK_STATEMENT_PROMPT = """
# You are a STRICT, SAFETY-FIRST document information extraction engine
# specialized ONLY for Indian Bank Statements.

# You will receive ONE OR MORE images of a document.
# Images may be:
# • scanned pages
# • photographed pages
# • PDF page images
# • rotated, blurred, cropped, skewed, or partially visible

# Your task is to extract the following fields:
# - Bank name
# - Bank branch
# - Customer name
# - Customer ID
# - Account type
# - IFSC code
# - Statement period (from date and to date)
# - Account number



# Return EXACTLY one JSON object and NOTHING else.
# """

BANK_STATEMENT_PROMPT = """
You are a STRICT, SAFETY-FIRST document information extraction engine


You will receive ONE OR MORE images of a document.
Images may be:
• rotated, blurred, cropped, skewed, or partially visible

IF THE IMAGE IS NOT CONFIDENTLY A BANK STATEMENT, OR IF THE IMAGE IS BLURRED, CROPPED, OR IF ALL REQUIRED FIELDS ARE NOT CLEARLY VISIBLE:
→ Return an EMPTY JSON object: {}

Your task is to extract the following fields in the given json format below: 

{
"is_bank_statement": boolean
"document_type": "bank_statement"

"holder": {
  "full_name": string,
  "date_of_birth": "YYYY-MM-DD" (optional),
  "year_of_birth": "YYYY" (optional)
}

"bank": {
  "name": string,
  "branch": string (optional),
  "ifsc": string (optional)
}

"statement_period": {
  "from_date": "YYYY-MM-DD",
  "to_date": "YYYY-MM-DD"
}

"account": {
  "account_number": string (optional, masked allowed),
  "customer_id": string (optional),
  "account_type": string (optional)
}

"raw_text": string (optional)
"warnings": [string] (optional)
}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PER-FIELD CONFIDENCE SCORING (MANDATORY)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

For EVERY extracted field, add a sibling key named {field}_confidence with one of:
• "high"   — every character/digit is crystal-clear, zero ambiguity
• "medium" — mostly readable but minor blur/glare on 1-2 characters
• "low"    — partially readable, some inference was needed

If confidence would be BELOW "low" → OMIT the field entirely.

Confidence keys go at the SAME level as the value they describe.

Example:
"holder": {
  "full_name": "RAHUL SHARMA",
  "full_name_confidence": "high"
}

Return EXACTLY one JSON object and NOTHING else.
"""

ACTIVITY_SCORE_PROMPT = """
SYSTEM INSTRUCTIONS:
<Name> has applied for a Mudra loan for his <enterprise name>, registered as a proprietorship.

You are provided with MULTIPLE bank statement pages in SEQUENTIAL ORDER.
All images belong to the SAME bank account.

Analyze transactions ACROSS ALL PAGES and assign an ACTIVITY SCORE (0–10).

Evaluate based on:
1. Regular cash flows
2. Avg monthly balance & MoM trend
3. Revenue stability
4. Expense patterns
5. Loan obligations
6. Account conduct
7. Business vs personal mixing
8. Seasonality

IMPORTANT:
- Consider ALL pages together (do NOT score per page)
- Use trends across months if visible

Return STRICT JSON:
{
"activity_score": number,
"reasoning": string (max 50 words)
}
"""

AADHAAR_VERIFY_PROMPT = """
You are a STRICT, safety-first document information-extraction engine specialized ONLY for Indian Aadhaar cards.

Your task:
Decide if the images together represent an Indian Aadhaar card.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STRICT OUTPUT FORMAT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Return EXACTLY one JSON object and NOTHING else.
FORMAT:
{
  "is_aadhaar": true | false
}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
AADHAAR DETECTION RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Set "is_aadhaar": true ONLY if you are confident the document is an Aadhaar card based on one or more of:
• Presence of the word "Aadhaar" and typical Aadhaar layout/branding
• UIDAI logo or official Aadhaar seal
• "Unique Identification Authority of India"
• "Government of India" combined with Aadhaar-like layout
• A clearly readable 12-digit UID in Aadhaar format (e.g., "XXXX XXXX XXXX")
• Known bilingual Aadhaar boilerplate text consistent with official cards

IF YOU ARE NOT CONFIDENT IT IS AN AADHAAR CARD:
→ Return an EMPTY JSON object: {}
"""

PAN_VERIFY_PROMPT = """
You are a STRICT, safety-first document verification and light-extraction engine specialized ONLY for Indian PAN cards.

Your task:
Decide if the images together represent a valid Indian PAN card AND extract the cardholder’s name if clearly visible.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STRICT OUTPUT FORMAT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Return EXACTLY one JSON object and NOTHING else.

FORMAT:
{
  "is_pan": true | false,
  "holder_name": string | null,
  "warnings": string[]
}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PAN CARD DETECTION RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Set "is_pan": true ONLY if you are confident the document is a PAN card based on one or more of:
• Presence of the text "Permanent Account Number"
• Presence of "Income Tax Department" or "Government of India"
• A clearly readable PAN number in format: AAAAA9999A
• Typical PAN card layout with name, father’s name, DOB

EXTRACTION RULES:
• Extract "holder_name" ONLY if clearly readable and unambiguous
• Do NOT guess or hallucinate names

FAILURE CONDITIONS:
If any of the following are unclear or missing:
• PAN card confidence
• Holder name not clearly readable

→ Set "is_pan": false
→ Set "holder_name": null
→ Add a suitable warning explaining why

WARNINGS:
• Use short, clear reasons (e.g., "PAN number not readable", "Name unclear")

If confident and extracted correctly:
→ "warnings": []
"""

VOTER_VERIFY_PROMPT = """
You are a STRICT, safety-first document verification and light-extraction engine specialized ONLY for Indian Voter ID (EPIC) cards.

Your task:
Decide if the images together represent a valid Indian Voter ID card AND extract the voter’s name if clearly visible.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STRICT OUTPUT FORMAT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Return EXACTLY one JSON object and NOTHING else.

FORMAT:
{
  "is_voterid": true | false,
  "holder_name": string | null,
  "warnings": string[]
}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
VOTER ID DETECTION RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Set "is_voterid": true ONLY if confident based on:
• "Election Commission of India"
• Words like "Voter", "Elector", "EPIC"
• A clearly readable EPIC number
• Typical voter ID layout with elector details

EXTRACTION RULES:
• Extract "holder_name" ONLY if clearly readable
• Ignore partially visible or ambiguous text

FAILURE CONDITIONS:
If any of the following are unclear:
• Confidence that document is a Voter ID
• Holder name not clearly readable

→ Set "is_voterid": false
→ Set "holder_name": null
→ Add a suitable warning

WARNINGS:
• Example: "EPIC number not visible", "Name text blurred"

If confident:
→ "warnings": []
"""

UDYAM_VERIFY_PROMPT = """
You are a STRICT, safety-first document verification and light-extraction engine specialized ONLY for Indian Udyam Registration certificates.

Your task:
Decide if the images together represent a valid Udyam Registration certificate AND extract the Enterprise Name if clearly visible.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STRICT OUTPUT FORMAT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Return EXACTLY one JSON object and NOTHING else.

FORMAT:
{
  "is_udyam": true | false,
  "enterprise_name": string | null,
  "warnings": string[]
}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
UDYAM CERTIFICATE DETECTION RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Set "is_udyam": true ONLY if confident based on:
• Presence of "UDYAM REGISTRATION"
• "Ministry of Micro, Small and Medium Enterprises"
• Udyam Registration Number (format: UDYAM-XX-00-0000000)
• Typical government certificate layout

EXTRACTION RULES:
• Extract "enterprise_name" ONLY if clearly readable
• Do NOT infer or guess business names

FAILURE CONDITIONS:
If any of the following are unclear:
• Document is not confidently Udyam certificate
• Enterprise name not clearly readable

→ Set "is_udyam": false
→ Set "enterprise_name": null
→ Add suitable warning

WARNINGS:
• Example: "Enterprise name missing", "Udyam number unclear"

If confident:
→ "warnings": []
"""

BANK_STATEMENT_VERIFY_PROMPT = """
You are a FAST document verification engine for bank statements.

Your tasks: 
1.	Determine if this is a valid bank statement.
2.	Identify the from and to date of the statement mentioned in the first page

Return EXACTLY ONE JSON object:

{
  "is_bank_statement": true/false,
  "document_type": "bank_statement",
  "confidence": "high" | "medium" | "low",
  "statement_period": {
    "from_date": "DD-MM-YYYY",
    "to_date": "DD-MM-YYYY"
  }
}

Rules:
- is_bank_statement: true ONLY if you see bank logo/name AND valid transaction details.
- Dates: Use DD-MM-YYYY format.
- confidence:
  - "high" = clear bank markers + dates + readable account details
  - "medium" = partial markers or dates unclear
  - "low" = document unclear or not bank statement

Output ONLY valid JSON, nothing else. Do NOT return raw_text or warnings.
"""

# ------------------------
# Utilities
# ------------------------
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

def encode_image_for_gemini(img: Image.Image) -> types.Part:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return types.Part.from_bytes(data=buf.getvalue(), mime_type="image/png")

def upload_to_storage(endpoint: str, filename: str, data: bytes, subfolder: str) -> str:
    base = PHOTOS_DIR if subfolder == "photos" else JSON_DIR
    dest_dir = os.path.join(base, endpoint)
    os.makedirs(dest_dir, exist_ok=True)
    dest_path = os.path.join(dest_dir, filename)
    with open(dest_path, "wb") as f:
        f.write(data)
    return f"file://{os.path.abspath(dest_path)}"

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

def crop_by_normalized_bbox(pil_img: Image.Image, bbox: Dict[str,float]) -> Optional[bytes]:
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

def extract_json_clean(text: str) -> Tuple[Optional[Dict[str,Any]], str]:
    if not isinstance(text, str):
        return None, str(text)
    s = text.strip()
    s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*```$", "", s)
    s = s.replace("`", "")
    first = s.find("{")
    last = s.rfind("}")
    if first == -1 or last == -1 or last < first:
        return None, s
    cand = s[first:last+1]
    try:
        parsed = json.loads(cand)
        if isinstance(parsed, dict):
            return parsed, cand
        else:
            return None, cand
    except Exception:
        cand2 = re.sub(r",(\s*[}\]])", r"\1", cand)
        try:
            parsed = json.loads(cand2)
            if isinstance(parsed, dict):
                return parsed, cand2
            else:
                return None, cand2
        except Exception:
            return None, cand

def normalize_digits(s: Optional[str]) -> Optional[str]:
    if not s: return None
    digits = re.sub(r"\D", "", s)
    return digits if digits else None

def normalize_pan(s: Optional[str]) -> Optional[str]:
    if not s: return None
    s2 = re.sub(r"[^A-Za-z0-9]", "", s).upper()
    if re.match(r"^[A-Z]{5}\d{4}[A-Z]$", s2):
        return s2
    return s2 if s2 else None

def try_normalize_date(s: Optional[str], output_format: str = "%d-%m-%Y") -> Optional[str]:
    if not s or not isinstance(s, str):
        return None
    s = s.strip()
    try:
        # Prefer Day-First (India standard)
        dt = dateparser.parse(s, fuzzy=True, dayfirst=True)
        if dt:
            return dt.strftime(output_format)
    except Exception:
        pass
    m = re.search(r"\b(19|20)\d{2}\b", s)
    if m:
        return m.group(0)
    return None

# ------------------------
# Document schemas (for null-filling)
# ------------------------
DOCUMENT_SCHEMAS = {
    "aadhaar_front": {
        "is_aadhaar": True, "document_type": True, 
        "holder": {"full_name": True, "date_of_birth": True, "year_of_birth": True, "gender": True}, 
        "aadhaar_number": True, "language": True, "raw_text": True, "warnings": True
        },
    "aadhaar_back": {
        "is_aadhaar": True, "document_type": True, 
        "address": {"care_of": True, "house": True, "street": True, "landmark": True, "locality": True, "vtc": True, "district": True, "state": True, "pincode": True},
        "language": True, "raw_text": True, "warnings": True},
    "pan": {"is_pan": True, "document_type": True, 
            "holder": {"full_name": True, "father_name": True, "date_of_birth": True, "year_of_birth": True}, 
            "pan_number": True, "pan_format_valid": True, "raw_text": True, "warnings": True},
    "voter_front": {"is_voter_id": True, "document_type": True, 
                    "holder": {"full_name": True, "father_or_spouse_name": True, "date_of_birth": True, "year_of_birth": True, "gender": True}, 
                    "epic_number": True, "constituency": True, "raw_text": True, "warnings": True},
    "voter_back": {"is_voter_id": True, "document_type": True, 
                   "holder": {"gender": True, "date_of_birth": True, "year_of_birth": True}, 
                   "address": {"vtc": True, "district": True, "state": True, "pincode": True}, 
                   "raw_text": True, "warnings": True},
    "udyam": {"is_udyam": True, "document_type": "udyam_registration_certificate",
          "enterprise": {"enterprise_name": True, "udyam_registration_number": True, "type_of_enterprise": True, 
          "classification": {"enterprise_category": True, "classification_year": True, "classification_date": True},
          "major_activity": True, "social_category_of_entrepreneur": True,              
          "units": {"number_of_units": True,"unit_names": True}},
          "business_address": {"flat_door_block": True, "building_name": True, "village_town": True,
          "road_street_lane": True, "city": True, "district": True, "state": True, "pincode": True},
          "contact_details": {"mobile": True, "email": True},
          "registration": {"date_of_incorporation": True, "date_of_commencement": True, "date_of_registration": True},
          "raw_text": True, "warnings": True },
    "bank_statement": {"is_bank_statement": True, "document_type": True,
                       "holder": {"full_name": True, "date_of_birth": True, "year_of_birth": True},
                       "bank": {"name": True, "branch": True, "ifsc": True},
                       "statement_period": {"from_date": True, "to_date": True},
                       "account": {"account_number": True, "customer_id": True, "account_type": True},
                       "raw_text": True, "warnings": True }
}


QA_QUESTIONS = [
    {
        "key": "name_confirmation",
        "question": "कृपया बताएं, क्या मेरी बात {extracted_name} से हो रही है?",
        "expected_output": '{"is_name_confirmed": true/false, "corrected_name": "string (only if user provided their name when saying no)", "is_sufficient_response": true/false, "follow_up_question": ""}',
        "description": 'Return {"is_name_confirmed": boolean} where true means the user confirmed their name, false means they denied it. If they denied it AND provided their correct name, set "corrected_name" to their exact string name. If they denied it but did NOT provide a correct name, then set "is_sufficient_response": false and provide a "follow_up_question" asking for their name.'
    },
    {
        "key": "business_purpose",
        "question": "बढ़िया, और आप किस व्यवसाय के लिए मुद्रा लोन चाहते हैं?",
        "expected_output": '{"business_purpose": "string", "is_sufficient_response": true/false, "follow_up_question": ""}',
        "description": 'Return {"business_purpose": string} with the type of business or purpose for which they want the loan.'
    },
    {
        "key": "is_married",
        "question": "ठीक है। क्या आप विवाहित हैं?",
        "expected_output": '{"is_married": true/false, "is_sufficient_response": true/false, "follow_up_question": ""}',
        "description": 'Return {"is_married": boolean} where true means the user is married, false means they are not married.'
    },
    {
        "key": "spouse_mobile",
        "question": "कृपया अपने पति या पत्नी का मोबाइल नंबर दर्ज करें।",
        "expected_output": '{"spouse_mobile": "string", "is_sufficient_response": true/false, "follow_up_question": ""}',
        "description": 'Return {"spouse_mobile": "string"} with their 10-digit mobile number.'
    }
]

def build_qa_prompt(question_key: str, question_text: str, expected_output_description: str, user_response: str, conversation_history: list = None) -> str:
    history_text = ""
    if conversation_history:
        history_text = "\nConversation History:\n"
        for h in conversation_history:
            history_text += f"- Assistant: {h.get('question')}\n- User: {h.get('response')}\n"
            
    return f"""You are analyzing an interview response.
    
The question asked was: "{question_text}"
{history_text}
The user answered: "{user_response}"

Task: {expected_output_description}

If the user's response is unclear or doesn't answer the question, set "is_sufficient_response": false and provide a helpful "follow_up_question" in Hindi to ask again.
Otherwise, set "is_sufficient_response": true and "follow_up_question": "".

Return ONLY valid JSON.
"""

OFFICE_ID_PROMPT = """
You are a STRICT, SAFETY-FIRST document information extraction engine.
You will receive ONE OR MORE images of an Office ID card.

Extract the following fields into JSON:
{
  "is_office_id": boolean,
  "document_type": "office_id",
  "organization_name": string,
  "organization_name_confidence": "high"|"medium"|"low",
  "place_of_posting": string (e.g. City or Branch name, if visible),
  "place_of_posting_confidence": "high"|"medium"|"low",
  "designation": string (e.g. Software Engineer, Manager),
  "designation_confidence": "high"|"medium"|"low",
  "employee_name": string,
  "employee_name_confidence": "high"|"medium"|"low",
  "employee_id": string (if visible),
  "employee_id_confidence": "high"|"medium"|"low"
}

Rules:
- If you are not confident it is an employee/office ID card, return {}.
- Omit keys that are not clearly visible.
"""

OFFICE_ID_VERIFY_PROMPT = """
Analyze the image. Is it an employee ID card or Office ID card?
Return exactly:
{"is_office_id": true/false}
"""

ADDRESS_PROOF_PROMPT = """
You are a STRICT document information extraction engine.
You will receive ONE OR MORE images of an Address Proof document (e.g., utility bill, rent agreement, bank passbook).

Extract the following fields into JSON:
{
  "is_address_proof": boolean,
  "document_type": "address_proof",
  "holder_name": string,
  "holder_name_confidence": "high"|"medium"|"low",
  "address": {
    "house": string,
    "street": string,
    "locality": string,
    "district": string,
    "state": string,
    "pincode": string (6 digits),
    "country": string
  }
}
Also add confidence fields for address keys like "house_confidence", "pincode_confidence", etc.

Rules:
- If you are not confident it is an address proof document, return {}.
- Omit keys that are not clearly visible.
"""

ADDRESS_PROOF_VERIFY_PROMPT = """
Analyze the image. Is it a document acting as an address proof (e.g. utility bill, electricity bill, rent agreement)?
Return exactly:
{"is_address_proof": true/false}
"""
