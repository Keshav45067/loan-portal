"""
Agent Session — in-memory state management for document capture agent sessions.

Each session tracks:
- Document queue (ordered list of doc+part items with status)
- Extracted data (field values with confidence and override flags)
- Conversation history (for multi-turn LLM context)
- Pending confirmation (for reupload flows)
- Document manifests (loaded from JSON files)
"""

import json
import os
import uuid
import copy
from typing import Dict, List, Optional, Any

from config import MANIFESTS_DIR


# ─── Scheme Definitions ───
# Maps scheme_id → list of required document IDs (in order)
SCHEME_DOCUMENTS = {
    "sandbox-demo": [
        "doc_aadhaar_002",
        "doc_pan_001",
        "doc_udyam_001",
    ],
    "mudra-grocery": [
        "doc_aadhaar_002",
        "doc_pan_001",
        "doc_gst_001",
        "doc_udyam_001",
        "doc_bank_statement_001",
    ],
}

# ─── Mock Extracted Data ───
# Pre-populated data simulating OCR results for completed pages
MOCK_EXTRACTED_DATA = {
    "doc_aadhaar_002": {
        "doc_aadhaar_name": {
            "value": "Keshav Garg",
            "confidence": 0.95,
            "manually_overridden": False,
            "override_reason": None,
            "source_part": "front",
        },
        "doc_aadhaar_dob": {
            "value": "15/08/1995",
            "confidence": 0.92,
            "manually_overridden": False,
            "override_reason": None,
            "source_part": "front",
        },
        "doc_aadhaar_gender": {
            "value": "Male",
            "confidence": 0.99,
            "manually_overridden": False,
            "override_reason": None,
            "source_part": "front",
        },
        "doc_aadhaar_last4": {
            "value": "4832",
            "confidence": 0.97,
            "manually_overridden": False,
            "override_reason": None,
            "source_part": "front",
        },
    },
    "doc_pan_001": {
        "doc_pan_number": {
            "value": "ABCPG1234K",
            "confidence": 0.97,
            "manually_overridden": False,
            "override_reason": None,
            "source_part": "front",
        },
        "doc_pan_name": {
            "value": "KESHAV GARG",
            "confidence": 0.96,
            "manually_overridden": False,
            "override_reason": None,
            "source_part": "front",
        },
        "doc_pan_father_name": {
            "value": "RAJESH GARG",
            "confidence": 0.94,
            "manually_overridden": False,
            "override_reason": None,
            "source_part": "front",
        },
        "doc_pan_dob": {
            "value": "15/08/1995",
            "confidence": 0.93,
            "manually_overridden": False,
            "override_reason": None,
            "source_part": "front",
        },
    },
}

# Which pages are pre-completed in mock
MOCK_COMPLETED_PAGES = {
    "doc_aadhaar_002": {"front"},  # Only front is done, back is pending
    "doc_pan_001": {"front"},       # Single-part doc, fully done
}


def load_manifest(doc_id: str) -> Optional[dict]:
    """Load a document manifest JSON file."""
    manifest_path = os.path.join(MANIFESTS_DIR, f"{doc_id}.json")
    if not os.path.exists(manifest_path):
        return None
    with open(manifest_path, "r") as f:
        return json.load(f)


class AgentSession:
    """In-memory state for a single agent session."""

    def __init__(self, session_id: str, scheme_id: str):
        self.session_id = session_id
        self.scheme_id = scheme_id

        # Document manifests: {doc_id: manifest_dict}
        self.manifests: Dict[str, dict] = {}

        # Document queue: ordered list of {doc_id, part_id, status, doc_title, part_name}
        # Status: PENDING | ACTIVE | COMPLETED
        self.document_queue: List[dict] = []

        # Extracted data: {field_key: {value, confidence, manually_overridden, override_reason, source_part}}
        self.extracted_data: Dict[str, dict] = {}

        # Conversation history for LLM context (list of Content-like dicts)
        self.conversation_history: List[dict] = []

        # Pending confirmation (e.g., reupload an already-completed page)
        self.pending_confirmation: Optional[dict] = None

        # Turn counter
        self.turn_count: int = 0

    def initialize(self) -> bool:
        """Load manifests and build initial queue from scheme."""
        doc_ids = SCHEME_DOCUMENTS.get(self.scheme_id)
        if not doc_ids:
            return False

        completed_pages = MOCK_COMPLETED_PAGES

        for doc_id in doc_ids:
            manifest = load_manifest(doc_id)
            if not manifest:
                continue

            self.manifests[doc_id] = manifest
            doc_title = manifest["title"].get("English", doc_id)
            doc_completed = completed_pages.get(doc_id, set())

            for part in manifest.get("parts", []):
                part_id = part["id"]
                part_name = part["name"].get("English", part_id)
                status = "COMPLETED" if part_id in doc_completed else "PENDING"

                self.document_queue.append({
                    "doc_id": doc_id,
                    "part_id": part_id,
                    "status": status,
                    "doc_title": doc_title,
                    "part_name": part_name,
                })

            # Load mock extracted data if available
            if doc_id in MOCK_EXTRACTED_DATA:
                self.extracted_data.update(copy.deepcopy(MOCK_EXTRACTED_DATA[doc_id]))

        # Set first PENDING item as ACTIVE
        for item in self.document_queue:
            if item["status"] == "PENDING":
                item["status"] = "ACTIVE"
                break

        return True

    # ─── Queue Operations ───

    def get_queue_item(self, doc_id: str, part_id: str) -> Optional[dict]:
        """Find a specific item in the queue."""
        for item in self.document_queue:
            if item["doc_id"] == doc_id and item["part_id"] == part_id:
                return item
        return None

    def get_active_item(self) -> Optional[dict]:
        """Get the currently active queue item."""
        for item in self.document_queue:
            if item["status"] == "ACTIVE":
                return item
        return None

    def set_active(self, doc_id: str, part_id: str) -> bool:
        """Set a queue item as ACTIVE, deactivating any current active item."""
        target = self.get_queue_item(doc_id, part_id)
        if not target:
            return False

        # Deactivate current active (set back to PENDING if it was ACTIVE)
        for item in self.document_queue:
            if item["status"] == "ACTIVE":
                item["status"] = "PENDING"

        target["status"] = "ACTIVE"
        return True

    def mark_completed(self, doc_id: str, part_id: str) -> bool:
        """Mark a queue item as COMPLETED."""
        item = self.get_queue_item(doc_id, part_id)
        if item:
            item["status"] = "COMPLETED"
            return True
        return False

    def reset_page(self, doc_id: str, part_id: str):
        """Reset a completed page back to PENDING, clear its extracted data, and set it as ACTIVE."""
        item = self.get_queue_item(doc_id, part_id)
        if item:
            self.set_active(doc_id, part_id)

        # Clear extracted data that came from this part
        manifest = self.manifests.get(doc_id)
        if manifest:
            for part in manifest.get("parts", []):
                if part["id"] == part_id:
                    for field_key in part.get("provides", []):
                        if field_key in self.extracted_data:
                            del self.extracted_data[field_key]
                    break

    def get_pending_count(self) -> int:
        """Count non-COMPLETED items."""
        return sum(1 for item in self.document_queue if item["status"] != "COMPLETED")

    def get_all_field_keys(self) -> List[str]:
        """Get all known field keys from all manifests."""
        fields = set()
        for doc_id, manifest in self.manifests.items():
            for field in manifest.get("expects", []):
                fields.add(field)
        return sorted(fields)

    # ─── Manifest Helpers ───

    def find_doc_by_name(self, name: str) -> Optional[str]:
        """Fuzzy match a document by user-friendly name. Returns doc_id or None."""
        name_lower = name.lower().strip()
        for doc_id, manifest in self.manifests.items():
            title = manifest["title"].get("English", "").lower()
            # Exact or substring match
            if name_lower in title or title in name_lower:
                return doc_id
            # Match common aliases
            aliases = {
                "aadhaar": "doc_aadhaar",
                "aadhar": "doc_aadhaar",
                "pan": "doc_pan",
                "pan card": "doc_pan",
                "udyam": "doc_udyam",
                "gst": "doc_gst",
                "bank": "doc_bank",
                "bank statement": "doc_bank",
                "passport": "doc_passport",
            }
            for alias, prefix in aliases.items():
                if alias in name_lower and doc_id.startswith(prefix):
                    return doc_id
        return None

    def get_doc_parts(self, doc_id: str) -> List[dict]:
        """Get parts list for a document."""
        manifest = self.manifests.get(doc_id)
        if not manifest:
            return []
        return manifest.get("parts", [])

    def find_part_by_name(self, doc_id: str, part_name: str) -> Optional[str]:
        """Fuzzy match a part name. Returns part_id or None."""
        name_lower = part_name.lower().strip()
        parts = self.get_doc_parts(doc_id)

        for part in parts:
            pid = part["id"].lower()
            pname = part["name"].get("English", "").lower()
            # Match by id or name
            if name_lower in pid or pid in name_lower:
                return part["id"]
            if name_lower in pname or pname in name_lower:
                return part["id"]
            # Common aliases
            if "front" in name_lower and "front" in pid:
                return part["id"]
            if "back" in name_lower and "back" in pid:
                return part["id"]
            if "main" in name_lower and "main" in pid:
                return part["id"]
            if "certificate" in name_lower and "certificate" in pid:
                return part["id"]

        return None

    # ─── Serialization ───

    def to_dict(self) -> dict:
        """Serialize session state for API response / system prompt injection."""
        return {
            "session_id": self.session_id,
            "scheme_id": self.scheme_id,
            "document_queue": self.document_queue,
            "extracted_data": self.extracted_data,
            "pending_confirmation": self.pending_confirmation,
            "turn_count": self.turn_count,
            "active_document": self._get_active_summary(),
            "pending_documents": [
                f"{item['doc_title']} — {item['part_name']}"
                for item in self.document_queue
                if item["status"] in ("PENDING", "ACTIVE")
            ],
            "completed_documents": [
                f"{item['doc_title']} — {item['part_name']}"
                for item in self.document_queue
                if item["status"] == "COMPLETED"
            ],
        }

    def _get_active_summary(self) -> Optional[str]:
        active = self.get_active_item()
        if active:
            return f"{active['doc_title']} — {active['part_name']}"
        return None


# ─── Session Store ───
# Simple in-memory store. In production, use Redis.
_sessions: Dict[str, AgentSession] = {}


def create_session(scheme_id: str) -> AgentSession:
    """Create and initialize a new agent session."""
    session_id = str(uuid.uuid4())
    session = AgentSession(session_id=session_id, scheme_id=scheme_id)
    session.initialize()
    _sessions[session_id] = session
    return session


def get_session(session_id: str) -> Optional[AgentSession]:
    """Retrieve an existing session."""
    return _sessions.get(session_id)
