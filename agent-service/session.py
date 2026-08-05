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
    "demo_business_kyc": [
        "doc_aadhaar_002",
        "doc_pan_001",
        "doc_udyam_001",
        "doc_gst_001",
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

    def __init__(self, session_id: str, scheme_id: str, language: str = "en"):
        self.session_id = session_id
        self.scheme_id = scheme_id
        self.language = language or "en"

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
            scheme_path = os.path.normpath(os.path.join(MANIFESTS_DIR, "..", "schemes", f"{self.scheme_id}.json"))
            if os.path.exists(scheme_path):
                try:
                    with open(scheme_path, "r", encoding="utf-8") as f:
                        scheme_data = json.load(f)
                        doc_ids = scheme_data.get("required_documents", [])
                except Exception:
                    doc_ids = None

        if not doc_ids:
            doc_ids = SCHEME_DOCUMENTS.get("sandbox-demo")

        # Load mock completed pages ONLY for sandbox-demo
        completed_pages = MOCK_COMPLETED_PAGES if self.scheme_id == "sandbox-demo" else {}

        lang_key = "Hindi" if self.language == "hi" else ("French" if self.language == "fr" else ("Arabic" if self.language == "ar" else "English"))

        for doc_id in doc_ids:
            manifest = load_manifest(doc_id)
            if not manifest:
                continue

            self.manifests[doc_id] = manifest
            doc_title = manifest.get("title", {}).get(lang_key, manifest.get("title", {}).get("English", doc_id))
            doc_completed = completed_pages.get(doc_id, set())

            for part in manifest.get("parts", []):
                part_id = part["id"]
                part_name = part.get("name", {}).get(lang_key, part.get("name", {}).get("English", part_id))
                status = "COMPLETED" if part_id in doc_completed else "PENDING"

                self.document_queue.append({
                    "doc_id": doc_id,
                    "part_id": part_id,
                    "status": status,
                    "doc_title": doc_title,
                    "part_name": part_name,
                })

            # Load mock extracted data ONLY for sandbox-demo
            if self.scheme_id == "sandbox-demo" and doc_id in MOCK_EXTRACTED_DATA:
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
        """Mark a queue item as COMPLETED and advance to next pending document.
        Only advances the queue if the completed item was the ACTIVE one —
        prevents corrupting the active pointer when a different doc is marked completed."""
        item = self.get_queue_item(doc_id, part_id)
        if item:
            was_active = (item["status"] == "ACTIVE")
            item["status"] = "COMPLETED"
            if was_active:
                self.advance_queue(from_doc_id=doc_id, from_part_id=part_id)
            return True
        return False

    def advance_queue(self, from_doc_id: Optional[str] = None, from_part_id: Optional[str] = None) -> Optional[dict]:
        """
        Advance the queue to the next pending document.
        Search strategy:
        1. Search forward from specified completed item (or current active item) to end of queue.
        2. If none found, wrap around to beginning of queue (index 0).
        3. If no pending items exist anywhere -> return None (all complete!).
        """
        active_idx = -1
        if from_doc_id and from_part_id:
            for i, item in enumerate(self.document_queue):
                if item["doc_id"] == from_doc_id and item["part_id"] == from_part_id:
                    active_idx = i
                    break

        if active_idx == -1:
            for i, item in enumerate(self.document_queue):
                if item["status"] == "ACTIVE":
                    active_idx = i
                    break

        # Search forward from active_idx + 1
        for i in range(active_idx + 1, len(self.document_queue)):
            if self.document_queue[i]["status"] == "PENDING":
                self.set_active(self.document_queue[i]["doc_id"], self.document_queue[i]["part_id"])
                return self.document_queue[i]

        # Wrap around: search from index 0 to active_idx
        for i in range(0, max(0, active_idx)):
            if self.document_queue[i]["status"] == "PENDING":
                self.set_active(self.document_queue[i]["doc_id"], self.document_queue[i]["part_id"])
                return self.document_queue[i]

        return None

    def reset_page(self, doc_id: str, part_id: str):
        """Reset a completed page back to PENDING, clear its extracted data, and set it as ACTIVE."""
        item = self.get_queue_item(doc_id, part_id)
        if item:
            item["status"] = "PENDING"  # Explicitly reset to PENDING before activating
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
        if len(name_lower) < 2:
            return None
        for doc_id, manifest in self.manifests.items():
            title = manifest["title"].get("English", "").lower()
            # Exact or substring match (only if input is non-trivial)
            if name_lower in title or (len(name_lower) >= 4 and title in name_lower):
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

    def reconcile_state(self):
        """Self-healing state reconciliation: ensure queue statuses match extracted data & completion."""
        all_expects = []
        for manifest in self.manifests.values():
            all_expects.extend(manifest.get("expects", []))
        
        extracted_keys = set(self.extracted_data.keys())
        if all_expects and all(k in extracted_keys for k in all_expects):
            self.mark_all_completed()
            return

        if self.document_queue and all(item["status"] == "COMPLETED" for item in self.document_queue):
            return

        has_active = any(item["status"] == "ACTIVE" for item in self.document_queue)
        if not has_active:
            for item in self.document_queue:
                if item["status"] == "PENDING":
                    item["status"] = "ACTIVE"
                    break

    def reset(self):
        """Reset agent session state completely for redo / start over."""
        self.extracted_data.clear()
        self.pending_confirmation = None
        self.pending_faq_question = None
        self._init_queue()

    def mark_all_completed(self):
        """Mark all documents in the queue as COMPLETED."""
        for item in self.document_queue:
            item["status"] = "COMPLETED"

    def is_all_complete(self) -> bool:
        """Check if all documents in the queue are completed."""
        if not self.document_queue:
            return False
        return all(item.get("status") == "COMPLETED" for item in self.document_queue)

    def _get_active_summary(self) -> Optional[str]:
        if self.is_all_complete():
            return "All Documents Captured (Final Data Review)"
        active = self.get_active_item()
        if active:
            return f"{active['doc_title']} — {active['part_name']}"
        return None


# ─── Session Store ───
# Simple in-memory store. In production, use Redis.
_sessions: Dict[str, AgentSession] = {}


def create_session(scheme_id: str, session_id: Optional[str] = None, language: str = "en") -> AgentSession:
    """Create and initialize a new agent session."""
    if not session_id:
        session_id = str(uuid.uuid4())
    session = AgentSession(session_id=session_id, scheme_id=scheme_id, language=language)
    session.initialize()
    _sessions[session_id] = session
    log_session_snapshot(session, f"Session Created / Initialized ({scheme_id})")
    return session


def log_session_snapshot(session: AgentSession, event_title: str):
    """Log a complete, formatted snapshot of the session state to journalctl."""
    import logging
    logger = logging.getLogger("agent-service")

    queue_lines = []
    for item in session.document_queue:
        queue_lines.append(
            f"    [{item['status']}] {item['doc_title']} — {item['part_name']} (doc_id: {item['doc_id']}, part_id: {item['part_id']})"
        )
    queue_str = "\n".join(queue_lines) if queue_lines else "    (empty queue)"

    if session.extracted_data:
        ext_lines = []
        for k, v in session.extracted_data.items():
            if isinstance(v, dict):
                val = v.get('value')
                conf = v.get('confidence', 1.0)
                override = " ⚠️ [MANUALLY EDITED]" if v.get('manually_overridden') else ""
                ext_lines.append(f"    • {k}: {json.dumps(val)} (conf: {conf:.0%}){override}")
            else:
                ext_lines.append(f"    • {k}: {json.dumps(v)}")
        ext_str = "\n".join(ext_lines)
    else:
        ext_str = "    (no extracted data yet)"

    logger.info(
        f"\n======================================================\n"
        f"📋 [SESSION STATE SNAPSHOT] {event_title}\n"
        f"Session ID: {session.session_id} | Scheme: {session.scheme_id} | Turn: #{session.turn_count}\n"
        f"Active Doc: {session._get_active_summary() or 'None'}\n"
        f"Document Queue:\n{queue_str}\n"
        f"Extracted Data:\n{ext_str}\n"
        f"======================================================"
    )


def get_session(session_id: str) -> Optional[AgentSession]:
    """Retrieve an existing session."""
    return _sessions.get(session_id)
