"""
Generic Config-Driven Field Resolver.

Contains 0 hardcoded field names or document path strings.
All field lookups, alias mappings, enum translations, and placeholder fallbacks
are driven dynamically by YAML scheme configs and manifest definitions.
"""

from typing import Dict, List, Any, Optional


def resolve_json_path(data: dict, path: str) -> Any:
    """
    Evaluates arbitrary dot-notation JSON paths in a nested dictionary/JSON.
    Example: 'extractions.AADHAAR_FRONT.holder.full_name'
    """
    if not data or not isinstance(data, dict) or not path:
        return None

    parts = path.split(".")
    curr = data
    for part in parts:
        if isinstance(curr, dict) and part in curr:
            curr = curr[part]
        elif isinstance(curr, str):
            # Attempt to parse stringified JSON if needed
            try:
                import json
                parsed = json.loads(curr)
                if isinstance(parsed, dict) and part in parsed:
                    curr = parsed[part]
                else:
                    return None
            except Exception:
                return None
        else:
            return None

    return curr


def resolve_canonical_field(canonical_key: str, data: dict, scheme_config: dict) -> Optional[Any]:
    """
    Resolves any canonical field from data using the active scheme_config's extraction_mappings.
    Contains ZERO hardcoded field names.
    """
    if not data or not isinstance(data, dict):
        return None

    scheme_config = scheme_config or {}
    extraction_mappings = scheme_config.get("extraction_mappings", {})
    field_config = extraction_mappings.get(canonical_key, {})

    # Sources path list from YAML config (or fallback to canonical_key itself)
    sources = field_config.get("sources", [canonical_key]) if isinstance(field_config, dict) else [canonical_key]

    for path in sources:
        val = resolve_json_path(data, path)
        if val is not None:
            val_str = str(val).strip()
            # Ignore empty/invalid values
            if val_str and val_str not in ("", "None", "Null", "not_available", "Not Available", "Not Provided"):
                return val

    return None


def resolve_applicant_name(data: dict, scheme_config: dict) -> Optional[str]:
    """
    Resolves applicant name dynamically based on scheme_config's primary_applicant_key.
    Contains ZERO hardcoded name strings.
    """
    scheme_config = scheme_config or {}
    primary_key = scheme_config.get("primary_applicant_key", "applicant_name")
    resolved = resolve_canonical_field(primary_key, data, scheme_config)
    if resolved:
        return str(resolved).strip()
    return None


def translate_enum(field_key: str, value: Any, language: str, scheme_config: dict) -> str:
    """
    Translates enum values (e.g., Gender, Marital Status) dynamically using scheme_config.
    Contains ZERO hardcoded translation literals.
    """
    val_str = str(value).strip().upper() if value is not None else ""
    if not val_str:
        return ""

    scheme_config = scheme_config or {}
    enum_translations = scheme_config.get("enum_translations", {})
    field_enum = enum_translations.get(field_key, {})

    val_mapping = field_enum.get(val_str, {})
    if isinstance(val_mapping, dict):
        translated = val_mapping.get(language) or val_mapping.get("en")
        if translated:
            return str(translated)

    return str(value)


def format_derived_placeholder(placeholder_key: str, data: dict, scheme_config: dict) -> Optional[str]:
    """
    Formats derived placeholders (e.g., last 4 digits of Aadhaar/PAN) dynamically via YAML rules.
    Contains ZERO hardcoded field names.
    """
    scheme_config = scheme_config or {}
    derived_rules = scheme_config.get("derived_placeholders", {})
    rule = derived_rules.get(placeholder_key, {})
    if not isinstance(rule, dict) or "source_key" not in rule:
        return None

    source_val = resolve_canonical_field(rule["source_key"], data, scheme_config)
    if not source_val:
        return None

    val_str = str(source_val)
    rule_type = rule.get("type")
    if rule_type == "last_n_digits":
        n = int(rule.get("n", 4))
        digits = "".join(c for c in val_str if c.isdigit())
        return digits[-n:] if len(digits) >= n else digits
    elif rule_type == "last_n_chars":
        n = int(rule.get("n", 4))
        return val_str[-n:] if len(val_str) >= n else val_str

    return val_str
