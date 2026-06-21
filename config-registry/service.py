"""
Config Registry Service — loads YAML configs, caches in Redis, serves via gRPC.

Configs are loaded from YAML files on startup and cached in Redis.
On updates, Redis cache is invalidated. All consumers call this service
at session start and cache the response in-process.
"""

import os
import yaml
import json
from typing import Dict, Optional

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'shared'))
from log_utils.logger import get_logger, get_req_id, LatencyTracker

from cache import RedisCache
from config import CONFIG_DIR

logger = get_logger("config-registry")


class ConfigService:
    """Manages loan scheme configurations."""

    def __init__(self, redis_cache: RedisCache):
        self._cache = redis_cache
        # In-memory store (always available, Redis is a performance layer on top)
        self._schemes: Dict[str, dict] = {}

    async def load_configs(self):
        """Load all YAML config files from CONFIG_DIR into memory and Redis."""
        config_dir = os.path.abspath(CONFIG_DIR)
        if not os.path.isdir(config_dir):
            logger.warning(f"Config directory not found: {config_dir}")
            return

        loaded = 0
        for filename in os.listdir(config_dir):
            if not filename.endswith((".yaml", ".yml")):
                continue

            filepath = os.path.join(config_dir, filename)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    config = yaml.safe_load(f)

                scheme_id = config.get("scheme_id")
                if not scheme_id:
                    logger.warning(f"Skipping {filename}: no scheme_id")
                    continue

                self._schemes[scheme_id] = config
                # Cache in Redis
                await self._cache.set_scheme_config(scheme_id, config)

                node_count = len(config.get("interview_graph", {}).get("nodes", {}))
                logger.info(f"Loaded scheme: {scheme_id}",
                            scheme_id=scheme_id,
                            details={"file": filename, "nodes": node_count})
                loaded += 1

            except Exception as e:
                logger.error(f"Failed to load {filename}: {e}", error=str(e))

        logger.info(f"Config Registry loaded {loaded} schemes",
                    details={"total": loaded, "schemes": list(self._schemes.keys())})

    # ─── Full Config ───

    async def get_scheme_config(self, scheme_id: str) -> Optional[dict]:
        """Get full scheme config. Checks Redis first, then in-memory."""
        # Try Redis cache
        cached = await self._cache.get_scheme_config(scheme_id)
        if cached:
            return cached

        # Fall back to in-memory
        config = self._schemes.get(scheme_id)
        if config:
            # Re-populate Redis cache
            await self._cache.set_scheme_config(scheme_id, config)
        return config

    # ─── Interview Graph ───

    async def get_interview_graph(self, scheme_id: str) -> Optional[dict]:
        """Get interview graph for a scheme."""
        # Try Redis graph cache
        cached = await self._cache.get_interview_graph(scheme_id)
        if cached:
            return cached

        config = await self.get_scheme_config(scheme_id)
        if not config:
            return None

        graph_data = config.get("interview_graph", {})
        context_map = config.get("context_map", {})

        result = {
            "scheme_id": scheme_id,
            "start_node_id": graph_data.get("start_node_id", "START"),
            "nodes": graph_data.get("nodes", {}),
            "context_map": context_map,
        }

        # Cache
        await self._cache.set_interview_graph(scheme_id, result)
        return result

    # ─── Document Requirements ───

    async def get_document_requirements(self, scheme_id: str) -> Optional[dict]:
        """Get document requirements for a scheme."""
        config = await self.get_scheme_config(scheme_id)
        if not config:
            return None
        return {
            "scheme_id": scheme_id,
            "documents": config.get("documents_required", []),
        }

    # ─── Field Instructions ───

    async def get_field_instruction(self, scheme_id: str, field_name: str) -> Optional[dict]:
        """Get extraction instruction for a specific field."""
        config = await self.get_scheme_config(scheme_id)
        if not config:
            return None

        instructions = config.get("field_instructions", {})
        instruction = instructions.get(field_name)
        if not instruction:
            return None

        return {
            "field_name": field_name,
            "instruction": instruction,
        }

    async def get_all_field_instructions(self, scheme_id: str) -> Optional[dict]:
        """Get all field instructions for a scheme."""
        config = await self.get_scheme_config(scheme_id)
        if not config:
            return None
        return config.get("field_instructions", {})

    # ─── Financial Rules ───

    async def get_financial_rules(self, scheme_id: str) -> Optional[dict]:
        """Get financial calculation rules for a scheme."""
        config = await self.get_scheme_config(scheme_id)
        if not config:
            return None
        rules = config.get("financial_rules", {})
        rules["scheme_id"] = scheme_id
        return rules

    # ─── Media Config ───

    async def get_media_config(self, scheme_id: str, language: str) -> Optional[dict]:
        """Get TTS/STT config for a scheme + language."""
        config = await self.get_scheme_config(scheme_id)
        if not config:
            return None

        tts_config = config.get("tts", {}).get(language, {})
        stt_config = config.get("stt", {}).get(language, {})

        return {
            "scheme_id": scheme_id,
            "language": language,
            "tts_voice_name": tts_config.get("voice_name", ""),
            "tts_engine": tts_config.get("engine", "google"),
            "tts_sample_rate": tts_config.get("sample_rate", 24000),
            "stt_engine": stt_config.get("engine", "google"),
            "stt_language_code": stt_config.get("language_code", ""),
        }

    # ─── Admin Operations ───

    async def create_scheme(self, config: dict) -> dict:
        """Create a new scheme from config dict."""
        scheme_id = config.get("scheme_id")
        if not scheme_id:
            return {"success": False, "error": "Missing scheme_id"}

        if scheme_id in self._schemes:
            return {"success": False, "error": f"Scheme {scheme_id} already exists"}

        self._schemes[scheme_id] = config
        await self._cache.set_scheme_config(scheme_id, config)

        # Save to disk
        filepath = os.path.join(os.path.abspath(CONFIG_DIR), f"{scheme_id}.yaml")
        with open(filepath, "w", encoding="utf-8") as f:
            yaml.dump(config, f, allow_unicode=True, default_flow_style=False)

        logger.info(f"Created scheme: {scheme_id}", scheme_id=scheme_id)
        return {"success": True, "scheme_id": scheme_id}

    async def update_scheme(self, config: dict) -> dict:
        """Update an existing scheme."""
        scheme_id = config.get("scheme_id")
        if not scheme_id:
            return {"success": False, "error": "Missing scheme_id"}

        self._schemes[scheme_id] = config
        # Invalidate all cached variants then re-cache
        await self._cache.invalidate_scheme(scheme_id)
        await self._cache.set_scheme_config(scheme_id, config)

        # Save to disk
        filepath = os.path.join(os.path.abspath(CONFIG_DIR), f"{scheme_id}.yaml")
        with open(filepath, "w", encoding="utf-8") as f:
            yaml.dump(config, f, allow_unicode=True, default_flow_style=False)

        logger.info(f"Updated scheme: {scheme_id}", scheme_id=scheme_id)
        return {"success": True, "scheme_id": scheme_id}

    async def list_schemes(self) -> list:
        """List all loaded schemes (summaries only)."""
        summaries = []
        for scheme_id, config in self._schemes.items():
            graph = config.get("interview_graph", {})
            summaries.append({
                "scheme_id": scheme_id,
                "display_name": config.get("display_name", ""),
                "languages": config.get("languages", []),
                "total_nodes": len(graph.get("nodes", {})),
            })
        return summaries

    async def delete_scheme(self, scheme_id: str) -> dict:
        """Delete a scheme."""
        if scheme_id not in self._schemes:
            return {"success": False, "error": f"Scheme {scheme_id} not found"}

        del self._schemes[scheme_id]
        await self._cache.invalidate_scheme(scheme_id)

        filepath = os.path.join(os.path.abspath(CONFIG_DIR), f"{scheme_id}.yaml")
        if os.path.exists(filepath):
            os.remove(filepath)

        logger.info(f"Deleted scheme: {scheme_id}", scheme_id=scheme_id)
        return {"success": True, "scheme_id": scheme_id}
