import re
import json
import base64
import dateutil.parser as dateparser
from typing import Optional, Dict, Any, Tuple

def safe_serialize(obj, _seen=None, _depth=0):
    if _seen is None:
        _seen = set()
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if _depth > 50:
        return "<depth-Exceeded>"
    oid = id(obj)
    if oid in _seen:
        return "<circular>"
    _seen.add(oid)
    if isinstance(obj, (bytes, bytearray)):
        try:
            return base64.b64encode(bytes(obj)).decode("ascii")
        except Exception:
            return "<bytes>"
    try:
        import numpy as _np
        if isinstance(obj, _np.ndarray):
            return obj.tolist()
        if isinstance(obj, (_np.int32, _np.int64, _np.float32, _np.float64)):
            return obj.item()
    except Exception:
        pass
    try:
        from PIL import Image as _PILImage
        if isinstance(obj, _PILImage.Image):
            return "<PIL.Image>"
    except Exception:
        pass
    try:
        from google.genai import types as _genai_types
        if isinstance(obj, _genai_types.Part):
            return "<genai.types.Part>"
    except Exception:
        pass
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            try:
                key = str(k)
            except Exception:
                key = "<non-string-key>"
            out[key] = safe_serialize(v, _seen=_seen, _depth=_depth+1)
        return out
    if isinstance(obj, (list, tuple, set)):
        return [safe_serialize(i, _seen=_seen, _depth=_depth+1) for i in obj]
    try:
        s = str(obj)
        if len(s) > 400:
            s = s[:400] + "...(truncated)"
        return s
    except Exception:
        return f"<unserializable:{type(obj).__name__}>"

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

def fill_nulls(target: Dict[str,Any], schema: Dict[str,Any]) -> None:
    for k, v in schema.items():
        if isinstance(v, dict):
            sub = target.get(k)
            if sub is None or not isinstance(sub, dict):
                target[k] = {}
            fill_nulls(target[k], v)
        else:
            if k not in target:
                target[k] = None
            if k not in ("is_aadhaar", "is_pan", "is_voter_id", "is_udyam", "is_bank_statement", "is_driving_license"):
                conf_key = f"{k}_confidence"
                if conf_key not in target:
                    target[conf_key] = None

def is_valid_string(v):
    return isinstance(v, str) and v.strip() != "" and v != "<circular>"

def up_name(s: Optional[str]) -> Optional[str]:
    if not is_valid_string(s):
        return None
    return s.strip().upper()
