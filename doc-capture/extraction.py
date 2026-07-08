import json
import re
from datetime import datetime
from dataclasses import dataclass
from typing import Any, List, Dict, Optional, Tuple
from log_utils.logger import get_logger
from config_loader import config_loader
from verhoeff import verify_aadhaar
import grpc

logger = get_logger("doc-capture")

@dataclass
class SlotResult:
    slot: str
    value: Any
    confidence: float
    evidence: dict  # {"page": "front", "span": "..."}

@dataclass
class ExtractionResult:
    document_id: str
    filled: List[SlotResult]
    unmatched: List[dict]
    notes: str

def normalize_iso_date(val: Any) -> Optional[str]:
    if not val:
        return None
    val_str = str(val).strip()
    
    # Try YYYY-MM-DD
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            dt = datetime.strptime(val_str, fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            pass
            
    # Try YYYY
    if val_str.isdigit() and len(val_str) == 4:
        return f"{val_str}-01-01"
        
    # Search for a 4 digit year
    m = re.search(r'\b(19\d{2}|20\d{2})\b', val_str)
    if m:
        return f"{m.group(1)}-01-01"
        
    return None

def validate_and_coerce(slot_id: str, slot_def: dict, raw_val: Any, raw_conf: float) -> Tuple[Any, float]:
    """
    Validates a slot value against its type, normalize and pattern specs in registry.
    Returns (coerced_value, updated_confidence). If invalid, value is None and confidence is 0.0.
    """
    if raw_val is None or raw_val == "":
        return None, 0.0
        
    slot_type = slot_def.get("type", "text")
    normalize = slot_def.get("normalize")
    pattern = slot_def.get("pattern")
    pii = slot_def.get("pii", "none")
    
    checksum = slot_def.get("checksum")
    if checksum == "verhoeff":
        # Expecting a 12-digit number initially to validate via Verhoeff and store last-4 digits
        cleaned = "".join(c for c in str(raw_val) if c.isdigit())
        if verify_aadhaar(cleaned):
            logger.info(f"Checksum validation successful for slot '{slot_id}' using Verhoeff.")
            # Store only last-4 digits
            return cleaned[-4:], raw_conf
        else:
            logger.error(f"Value '{raw_val}' failed Verhoeff checksum validation for slot '{slot_id}'.")
            return None, 0.0
            
    if slot_type == "date" or normalize == "iso_date":
        date_val = normalize_iso_date(raw_val)
        if date_val:
            return date_val, raw_conf
        else:
            return None, 0.0
            
    elif slot_type == "categorical":
        allowed = [v.upper() for v in slot_def.get("values", [])]
        val_upper = str(raw_val).strip().upper()
        if val_upper in allowed:
            return val_upper, raw_conf
        else:
            # Maybe try a substring match for gender
            for a in allowed:
                if a in val_upper or val_upper in a:
                    return a, raw_conf
            return None, 0.0
            
    elif slot_type == "object":
        # Handle structured addresses
        if not isinstance(raw_val, dict):
            return None, 0.0
        expected_fields = slot_def.get("fields", [])
        coerced_obj = {}
        for f in expected_fields:
            coerced_obj[f] = raw_val.get(f, None)
        return coerced_obj, raw_conf
        
    elif slot_type == "number":
        try:
            # Remove commas or non-numeric chars except dot
            cleaned_num = re.sub(r'[^\d\.]', '', str(raw_val))
            if '.' in cleaned_num:
                return float(cleaned_num), raw_conf
            return int(cleaned_num), raw_conf
        except ValueError:
            return None, 0.0
            
    # Pattern regex check
    if pattern:
        try:
            if not re.match(pattern, str(raw_val).strip()):
                return None, 0.0
        except Exception as e:
            logger.error(f"Pattern matching failed for {slot_id}: {e}")
            return None, 0.0
            
    return str(raw_val).strip(), raw_conf

def build_prompt(manifest: dict, all_page_texts: Dict[str, str]) -> str:
    # 1. Format OCR Input text
    input_parts = []
    for part_id, text in all_page_texts.items():
        input_parts.append(f"--- PAGE: {part_id} ---\n{text}")
    input_text = "\n\n".join(input_parts)
    
    # 2. Build Slot Menu instructions
    expects = manifest.get("expects", [])
    menu_lines = []
    for slot_id in expects:
        slot_def = config_loader.get_slot_def(slot_id)
        if slot_def:
            label_dict = slot_def.get("label", {})
            english_label = label_dict.get("English", slot_id)
            slot_type = slot_def.get("type", "text")
            pii = slot_def.get("pii", "none")
            
            desc = f"- {slot_id} (Type: {slot_type}, Label: {english_label})"
            if slot_type == "categorical":
                desc += f", Allowed values: {slot_def.get('values', [])}"
            elif slot_type == "object":
                desc += f", Fields: {slot_def.get('fields', [])}"
                
            if pii == "masked" and slot_id == "doc_aadhaar_last4":
                desc += ". IMPORTANT: Extract the full 12-digit Aadhaar number if found in the text; it will be validated and masked."
            elif slot_type == "date":
                desc += ". Normalize date to YYYY-MM-DD. If only Year is present, return YYYY-01-01."
                
            if "pattern" in slot_def:
                desc += f", Pattern/Regex constraints: {slot_def.get('pattern')}"
                
            menu_lines.append(desc)
            
    slot_menu = "\n".join(menu_lines)
    
    # 3. Get generic slot and part examples dynamically for prompt structure
    first_slot = expects[0] if expects else "slot_id"
    first_part = manifest.get("parts", [{}])[0].get("id", "part_id")
    
    prompt = f"""IDENTITY: You extract structured data from a document's OCR text. You decide nothing else.

INPUT:
{input_text}

TARGET:
Slot menu — for each:
{slot_menu}

TASK:
For every slot you can fill with high confidence FROM THE INPUT ONLY, return
{{slot, value, confidence 0-1, evidence{{page, span}}}}. Omit slots not present. Never invent.
Also list strong entities that match no slot under "unmatched".

OUTPUT:
Return ONLY a raw JSON object matching the strict schema below. No markdown backticks (e.g. ```json), no conversation, no explanation.

Example JSON output structure:
{{
  "document_id": "{manifest.get('document_id')}",
  "filled": [
    {{ "slot": "{first_slot}", "value": "EXTRACTED_VALUE", "confidence": 0.95, "evidence": {{ "page": "{first_part}", "span": "MATCHING_TEXT" }} }}
  ],
  "unmatched": [],
  "notes": ""
}}
"""
    return prompt

async def run_extraction(
    all_page_texts: Dict[str, str],
    manifest: dict,
    llm_stub
) -> ExtractionResult:
    """
    Constructs extraction prompt, calls LLM, parses response, validates contract,
    and returns a clean ExtractionResult.
    """
    prompt = build_prompt(manifest, all_page_texts)
    
    from generated import llm_pb2
    try:
        logger.info(f"Extraction: sending prompt to LLM (model=gemini-2.5-flash)...")
        llm_res = await llm_stub.Extract(llm_pb2.ExtractRequest(
            prompt=prompt,
            model="gemini-2.5-flash",
            disable_thinking=True
        ), timeout=25.0)
        
        if not llm_res.success:
            logger.error(f"LLM extraction failed: {llm_res.error}")
            return ExtractionResult(document_id=manifest.get("document_id", ""), filled=[], unmatched=[], notes=llm_res.error)
            
        json_text = llm_res.json_text.strip()
        if json_text.startswith("```"):
            lines = json_text.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            json_text = "\n".join(lines).strip()
            
        logger.info(f"Extraction LLM response: {json_text}")
        data = json.loads(json_text)
    except Exception as e:
        logger.error(f"Error calling LLM extraction or parsing response: {e}")
        return ExtractionResult(document_id=manifest.get("document_id", ""), filled=[], unmatched=[], notes=str(e))
        
    filled_results = []
    expects = set(manifest.get("expects", []))
    
    raw_filled = data.get("filled", [])
    for entry in raw_filled:
        slot_id = entry.get("slot")
        if slot_id not in expects:
            logger.warning(f"Extraction: LLM returned slot '{slot_id}' which is not expected by manifest. Skipping.")
            continue
            
        slot_def = config_loader.get_slot_def(slot_id)
        if not slot_def:
            logger.warning(f"Extraction: slot '{slot_id}' not found in registry. Skipping.")
            continue
            
        raw_val = entry.get("value")
        raw_conf = entry.get("confidence", 0.0)
        evidence = entry.get("evidence", {})
        
        # Validate & Coerce
        coerced_val, coerced_conf = validate_and_coerce(slot_id, slot_def, raw_val, raw_conf)
        
        if coerced_val is not None:
            filled_results.append(SlotResult(
                slot=slot_id,
                value=coerced_val,
                confidence=coerced_conf,
                evidence=evidence
            ))
            logger.info(f"Extraction: validated slot '{slot_id}' -> {coerced_val} (conf={coerced_conf:.2f})")
        else:
            # Store with 0 confidence to trigger retake
            filled_results.append(SlotResult(
                slot=slot_id,
                value=None,
                confidence=0.0,
                evidence=evidence
            ))
            logger.warning(f"Extraction: validation failed for slot '{slot_id}' (raw_val='{raw_val}')")
            
    # For any expected slots that weren't returned at all, inject a None slot with 0.0 confidence
    returned_slots = {r.slot for r in filled_results}
    for slot_id in expects:
        if slot_id not in returned_slots:
            filled_results.append(SlotResult(
                slot=slot_id,
                value=None,
                confidence=0.0,
                evidence={}
            ))
            logger.info(f"Extraction: injecting missing slot '{slot_id}' as None with 0 confidence.")
            
    return ExtractionResult(
        document_id=manifest.get("document_id", ""),
        filled=filled_results,
        unmatched=data.get("unmatched", []),
        notes=data.get("notes", "")
    )
