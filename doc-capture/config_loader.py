import os
import json
from typing import Dict, Optional
from log_utils.logger import get_logger

logger = get_logger("doc-capture")

CONFIGS_DIR = os.path.join(os.path.dirname(__file__), "configs")

class ConfigLoader:
    def __init__(self):
        self._fields_registry: Dict[str, dict] = {}
        self._confidence_bands: Dict[str, dict] = {}
        self.load_registry()

    def load_registry(self):
        fields_path = os.path.join(CONFIGS_DIR, "fields.json")
        try:
            if os.path.exists(fields_path):
                with open(fields_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self._confidence_bands = data.pop("_defaults", {}).get("confidence_bands", {})
                    self._fields_registry = data
                logger.info("Loaded fields registry successfully.")
            else:
                logger.error(f"fields.json not found at {fields_path}")
        except Exception as e:
            logger.error(f"Failed to load fields registry: {e}")

    def get_scheme(self, scheme_id: str) -> Optional[dict]:
        scheme_path = os.path.join(CONFIGS_DIR, "schemes", f"{scheme_id}.json")
        try:
            if os.path.exists(scheme_path):
                with open(scheme_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            else:
                logger.error(f"Scheme file not found: {scheme_path}")
        except Exception as e:
            logger.error(f"Error loading scheme {scheme_id}: {e}")
        return None

    def get_document(self, document_id: str) -> Optional[dict]:
        """Alias for get_manifest to keep session_manager compatibility."""
        return self.get_manifest(document_id)

    def get_manifest(self, document_id: str) -> Optional[dict]:
        manifest_path = os.path.join(CONFIGS_DIR, "manifests", f"{document_id}.json")
        try:
            if os.path.exists(manifest_path):
                with open(manifest_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            else:
                logger.error(f"Manifest file not found: {manifest_path}")
        except Exception as e:
            logger.error(f"Error loading manifest {document_id}: {e}")
        return None

    def get_slot_def(self, slot_id: str) -> Optional[dict]:
        return self._fields_registry.get(slot_id)

    def get_confidence_bands(self) -> dict:
        return self._confidence_bands

    def build_slot_menu(self, expects_list: list) -> list:
        """
        Builds target slot menu description for LLM prompt.
        Format: list of strings containing slot ID and instructions.
        """
        menu = []
        for slot_id in expects_list:
            slot_def = self.get_slot_def(slot_id)
            if slot_def:
                label_dict = slot_def.get("label", {})
                english_label = label_dict.get("English", slot_id)
                slot_type = slot_def.get("type", "text")
                
                desc = f"- {slot_id} (Type: {slot_type}, Label: {english_label})"
                if slot_type == "categorical":
                    desc += f", Allowed values: {slot_def.get('values', [])}"
                elif slot_type == "object":
                    desc += f", Fields: {slot_def.get('fields', [])}"
                
                if "pattern" in slot_def:
                    p = slot_def.get("pattern")
                    if isinstance(p, list):
                        desc += f", Pattern/Regex (must match at least one): {', '.join(p)}"
                    else:
                        desc += f", Pattern/Regex: {p}"
                    
                menu.append(desc)
        return menu

# Singleton instance
config_loader = ConfigLoader()
