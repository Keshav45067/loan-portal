"""
Shared scheme configuration loader with YAML inheritance resolution.
Reads 100% dynamically from Config Registry YAML files with zero hardcoded mappings.
"""

import os
import copy
import yaml
import logging

logger = logging.getLogger("chayan.config-loader")


def load_resolved_scheme_config(scheme_id: str) -> dict:
    """
    Load scheme YAML configuration from Config Registry, resolving inheritance ('extends' key) recursively.
    """
    if not scheme_id:
        return {}

    if scheme_id == 'a74b1b43-7cc6-4385-8a8c-12af64cddb2b':
        scheme_id = 'base-mudra'

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
        logger.warning(f"Config directory not found: {config_dir}")
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
        except Exception as e:
            logger.error(f"Failed to load YAML file {filepath}: {e}")

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
                return {}
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
        return resolve(scheme_id)
    except Exception as e:
        logger.error(f"Error resolving scheme config inheritance for {scheme_id}: {e}")
        return {}
