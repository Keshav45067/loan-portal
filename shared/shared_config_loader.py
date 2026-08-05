"""
Shared scheme configuration loader with YAML inheritance resolution and built-in fallback mappings.
"""

import os
import copy
import logging

logger = logging.getLogger("chayan.config-loader")

DEFAULT_EXTRACTION_MAPPINGS = {
    "applicant_name": {
        "sources": [
            "applicant_name",
            "full_name",
            "name",
            "name_of_the_applicant",
            "corrected_name",
            "doc_aadhaar_name",
            "extractions.aadhaar_front.holder.full_name",
            "extractions.aadhaar_back.holder.full_name",
            "extractions.AADHAAR_FRONT.holder.full_name",
            "extractions.pan.holder.full_name",
            "extractions.PAN.holder.full_name",
            "extractions.voter_front.holder.full_name",
            "holder.full_name",
            "holder.name"
        ]
    },
    "aadhaar_number": {
        "sources": [
            "aadhaar_number",
            "doc_aadhaar_number",
            "extractions.aadhaar_front.aadhaar_number",
            "extractions.aadhaar_back.aadhaar_number",
            "holder.aadhaar_number"
        ]
    },
    "gender": {
        "sources": [
            "gender",
            "holder.gender",
            "extractions.aadhaar_front.holder.gender"
        ]
    },
    "father_name": {
        "sources": [
            "father_name",
            "fathers_name",
            "holder.father_name",
            "address.care_of"
        ]
    }
}

DEFAULT_APPLICANT_PLACEHOLDER = {
    "hi": "आवेदक",
    "en": "Applicant",
    "fr": "Demandeur",
    "ar": "المتقدم"
}


def load_resolved_scheme_config(scheme_id: str) -> dict:
    """
    Load scheme YAML configuration, resolving inheritance ('extends' key) recursively.
    Guarantees default extraction mappings even if PyYAML is missing.
    """
    base_default = {
        "extraction_mappings": DEFAULT_EXTRACTION_MAPPINGS,
        "default_applicant_placeholder": DEFAULT_APPLICANT_PLACEHOLDER
    }

    if not scheme_id:
        return base_default

    if scheme_id == 'a74b1b43-7cc6-4385-8a8c-12af64cddb2b':
        scheme_id = 'base-mudra'

    try:
        import yaml
    except ImportError:
        logger.warning("PyYAML not installed in Python environment, using built-in default extraction mappings")
        return base_default

    config_dir = os.getenv(
        "CONFIG_REGISTRY_PATH",
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "config-registry", "configs"))
    )
    if not os.path.exists(config_dir):
        alt_paths = [
            os.path.abspath("config-registry/configs"),
            os.path.abspath("services/config-registry/configs"),
            "/var/www/augmen/testing-services/config-registry/configs"
        ]
        for alt in alt_paths:
            if os.path.exists(alt):
                config_dir = alt
                break

    raw_configs = {}
    if not os.path.exists(config_dir):
        return base_default

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
            cfg = raw_configs.get("base-mudra", {})
            if not cfg:
                return base_default
        parent_id = cfg.get("extends")
        if parent_id and parent_id in raw_configs:
            parent_cfg = resolve(parent_id, resolved, resolving)
            merged = deep_merge(parent_cfg, cfg)
            merged.pop("extends", None)
            resolved[s_id] = merged
        else:
            resolved[s_id] = copy.deepcopy(cfg)
        resolving.remove(s_id)
        return resolved[s_id]

    try:
        resolved_cfg = resolve(scheme_id)
        if "extraction_mappings" not in resolved_cfg:
            resolved_cfg["extraction_mappings"] = DEFAULT_EXTRACTION_MAPPINGS
        if "default_applicant_placeholder" not in resolved_cfg:
            resolved_cfg["default_applicant_placeholder"] = DEFAULT_APPLICANT_PLACEHOLDER
        return resolved_cfg
    except Exception as e:
        logger.error(f"Error resolving scheme config inheritance for {scheme_id}: {e}")
        return base_default
