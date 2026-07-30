"""
Agent Tools — tool definitions, validation, and execution for the document capture agent.

Each tool:
1. Validates its arguments against session state
2. Returns a structured result with status, signal, and message
3. Does NOT actually execute anything — just validates and emits a signal

Signals are UI control commands that the frontend interprets.
"""

import re
from typing import Any, Dict, Optional
from session import AgentSession


# ─── Field Validation Rules ───

FIELD_VALIDATORS = {
    "pincode": {
        "pattern": r"^\d{6}$",
        "message": "Pincode must be exactly 6 digits (e.g., 126112)",
    },
    "doc_pan_number": {
        "pattern": r"^[A-Z]{5}[0-9]{4}[A-Z]$",
        "message": "PAN must be in format ABCDE1234F (5 letters, 4 digits, 1 letter)",
    },
    "dob": {
        "pattern": r"^\d{2}/\d{2}/\d{4}$",
        "message": "Date of birth must be in DD/MM/YYYY format",
    },
    "gender": {
        "values": ["male", "female", "other"],
        "message": "Gender must be Male, Female, or Other",
    },
    "doc_aadhaar_last4": {
        "pattern": r"^\d{4}$",
        "message": "Must be exactly 4 digits",
    },
}


def _get_validator_for_field(field_key: str) -> Optional[dict]:
    """Find the appropriate validator for a field key."""
    # Exact match first
    if field_key in FIELD_VALIDATORS:
        return FIELD_VALIDATORS[field_key]
    # Suffix match (e.g., any field ending in _dob)
    for suffix in ("dob", "pincode", "gender", "last4"):
        if field_key.endswith(f"_{suffix}") or field_key == suffix:
            return FIELD_VALIDATORS.get(suffix)
    # Check if it's a sub-field of an address (e.g., user says "pincode")
    if "pincode" in field_key.lower() or "pin" in field_key.lower():
        return FIELD_VALIDATORS["pincode"]
    return None


def _validate_field_value(field_key: str, value: str) -> Dict[str, Any]:
    """Validate a field value against its validation rules."""
    validator = _get_validator_for_field(field_key)
    if not validator:
        return {"valid": True}

    if "pattern" in validator:
        if not re.match(validator["pattern"], str(value)):
            return {"valid": False, "message": validator["message"]}
    elif "values" in validator:
        if str(value).lower() not in validator["values"]:
            return {"valid": False, "message": validator["message"]}

    return {"valid": True}


# ─── Tool Execution Functions ───

def execute_switch_document_page(
    session: AgentSession,
    doc_id: str,
    part_id: Optional[str] = None,
) -> dict:
    """
    Switch the active document page.

    Logic:
    1. Resolve doc_id (fuzzy match by name if needed)
    2. If single-part doc → auto-resolve part_id
    3. If multi-part and no part_id → return needs_clarification
    4. If target page is COMPLETED → return needs_confirmation (for reupload)
    5. Otherwise → switch and emit SWITCH_PAGE signal
    """
    # 1. Resolve document
    resolved_doc_id = session.find_doc_by_name(doc_id) if doc_id not in session.manifests else doc_id
    if not resolved_doc_id:
        available = [
            f"{m['title']['English']} ({did})"
            for did, m in session.manifests.items()
        ]
        return {
            "status": "error",
            "message": f"Document '{doc_id}' not found. Available documents: {', '.join(available)}",
            "signal": None,
        }

    manifest = session.manifests[resolved_doc_id]
    parts = manifest.get("parts", [])
    doc_title = manifest["title"].get("English", resolved_doc_id)

    # 2. Resolve part
    if part_id:
        # Try to match part by name
        resolved_part = session.find_part_by_name(resolved_doc_id, part_id)
        if not resolved_part:
            part_names = [p["name"]["English"] for p in parts]
            return {
                "status": "error",
                "message": f"Part '{part_id}' not found for {doc_title}. Available parts: {', '.join(part_names)}",
                "signal": None,
            }
        part_id = resolved_part
    elif len(parts) == 1:
        # Single-part doc → auto-resolve
        part_id = parts[0]["id"]
    else:
        # Multi-part, no part specified → ask
        part_names = [f"{p['name']['English']} ({p['id']})" for p in parts]
        return {
            "status": "needs_clarification",
            "message": f"{doc_title} has multiple parts: {', '.join(part_names)}. Which one would you like to switch to?",
            "signal": None,
        }

    # 3. Check if already completed
    queue_item = session.get_queue_item(resolved_doc_id, part_id)
    if queue_item and queue_item["status"] == "COMPLETED":
        part_name = next(
            (p["name"]["English"] for p in parts if p["id"] == part_id),
            part_id,
        )
        session.pending_confirmation = {
            "type": "reupload",
            "doc_id": resolved_doc_id,
            "part_id": part_id,
            "doc_title": doc_title,
            "part_name": part_name,
        }
        return {
            "status": "needs_confirmation",
            "message": (
                f"The {part_name} of {doc_title} has already been uploaded and processed. "
                f"Would you like to re-upload it? This will clear the existing extracted data for this page."
            ),
            "signal": None,
        }

    # 4. Switch
    session.set_active(resolved_doc_id, part_id)
    part_name = next(
        (p["name"]["English"] for p in parts if p["id"] == part_id),
        part_id,
    )

    return {
        "status": "success",
        "message": f"Switched to {doc_title} — {part_name}",
        "signal": {
            "type": "SWITCH_PAGE",
            "payload": {
                "doc_id": resolved_doc_id,
                "part_id": part_id,
                "doc_title": doc_title,
                "part_name": part_name,
            },
        },
    }


def execute_update_extracted_field(
    session: AgentSession,
    field_key: str,
    new_value: str,
    reason: Optional[str] = None,
) -> dict:
    """
    Update an extracted field value.

    Logic:
    1. Check field exists in extracted_data
    2. Validate new_value against field-specific rules
    3. Update with manually_overridden flag
    """
    # 1. Resolve field — try exact match first, then fuzzy
    resolved_key = None
    if field_key in session.extracted_data:
        resolved_key = field_key
    else:
        # Fuzzy match: user might say "pincode" meaning "doc_aadhaar_address.pincode"
        # Or "name" which could match multiple fields
        matches = []
        for existing_key in session.extracted_data:
            if field_key.lower() in existing_key.lower():
                matches.append(existing_key)

        if len(matches) == 1:
            resolved_key = matches[0]
        elif len(matches) > 1:
            return {
                "status": "ambiguous",
                "message": (
                    f"Multiple fields match '{field_key}': {', '.join(matches)}. "
                    f"Please specify which one you want to update."
                ),
                "signal": None,
            }

    if not resolved_key:
        available = list(session.extracted_data.keys())
        all_fields = session.get_all_field_keys()
        # Check if field exists in schema but hasn't been extracted yet
        schema_only = [f for f in all_fields if f not in session.extracted_data]
        msg = f"Field '{field_key}' not found in extracted data."
        if available:
            msg += f" Currently extracted fields: {', '.join(available)}."
        if schema_only:
            msg += f" Fields not yet extracted (document pending): {', '.join(schema_only)}."
        return {
            "status": "error",
            "message": msg,
            "signal": None,
        }

    # 2. Validate
    validation = _validate_field_value(resolved_key, new_value)
    if not validation["valid"]:
        return {
            "status": "validation_error",
            "message": f"Invalid value for {resolved_key}: {validation['message']}",
            "signal": None,
        }

    # 3. Update
    old_value = session.extracted_data[resolved_key]["value"]
    session.extracted_data[resolved_key]["value"] = new_value
    session.extracted_data[resolved_key]["manually_overridden"] = True
    session.extracted_data[resolved_key]["override_reason"] = reason or "User correction"
    session.extracted_data[resolved_key]["confidence"] = 1.0  # Manual = 100% confidence

    return {
        "status": "success",
        "message": f"Updated {resolved_key}: '{old_value}' → '{new_value}' (flagged as manual override)",
        "signal": {
            "type": "UPDATE_FIELD",
            "payload": {
                "field_key": resolved_key,
                "old_value": old_value,
                "new_value": new_value,
                "manually_overridden": True,
                "override_reason": reason or "User correction",
            },
        },
    }


def execute_reset_document_page(
    session: AgentSession,
    doc_id: str,
    part_id: str,
) -> dict:
    """
    Reset a document page (clear extracted data and mark PENDING).
    """
    # Resolve doc
    resolved_doc_id = session.find_doc_by_name(doc_id) if doc_id not in session.manifests else doc_id
    if not resolved_doc_id:
        return {
            "status": "error",
            "message": f"Document '{doc_id}' not found.",
            "signal": None,
        }

    # Resolve part
    resolved_part = session.find_part_by_name(resolved_doc_id, part_id)
    if not resolved_part:
        return {
            "status": "error",
            "message": f"Part '{part_id}' not found for document '{resolved_doc_id}'.",
            "signal": None,
        }

    manifest = session.manifests[resolved_doc_id]
    doc_title = manifest["title"].get("English", resolved_doc_id)
    part_name = next(
        (p["name"]["English"] for p in manifest["parts"] if p["id"] == resolved_part),
        resolved_part,
    )

    # Reset
    session.reset_page(resolved_doc_id, resolved_part)

    return {
        "status": "success",
        "message": f"Reset {doc_title} — {part_name}. Extracted data cleared, ready for re-upload.",
        "signal": {
            "type": "RESET_PAGE",
            "payload": {
                "doc_id": resolved_doc_id,
                "part_id": resolved_part,
                "doc_title": doc_title,
                "part_name": part_name,
            },
        },
    }


def execute_answer_faq(
    session: AgentSession,
    user_query: str,
) -> dict:
    """
    Answer an FAQ about a document.
    Returns the FAQ context for the LLM to use in its response.
    """
    # Find relevant document context
    active = session.get_active_item()
    faq_context = []

    if active:
        manifest = session.manifests.get(active["doc_id"], {})
        faq = manifest.get("llm_faq_context", {})
        if faq:
            faq_context.append({
                "document": manifest["title"].get("English", active["doc_id"]),
                "policies": faq.get("policies", []),
            })

    # Also gather FAQ from all documents for general questions
    for doc_id, manifest in session.manifests.items():
        if active and doc_id == active["doc_id"]:
            continue
        faq = manifest.get("llm_faq_context", {})
        if faq:
            faq_context.append({
                "document": manifest["title"].get("English", doc_id),
                "policies": faq.get("policies", []),
            })

    return {
        "status": "success",
        "message": f"FAQ context loaded for query: {user_query}",
        "faq_context": faq_context,
        "signal": {
            "type": "FAQ_ANSWERED",
            "payload": {"query": user_query},
        },
    }


def execute_submit_application(session: AgentSession) -> dict:
    """
    Submit the application — validates all documents are complete.
    """
    incomplete = [
        f"{item['doc_title']} — {item['part_name']}"
        for item in session.document_queue
        if item["status"] != "COMPLETED"
    ]

    if incomplete:
        return {
            "status": "blocked",
            "message": (
                f"Cannot submit yet. The following documents are still pending:\n"
                + "\n".join(f"  • {doc}" for doc in incomplete)
            ),
            "signal": None,
        }

    return {
        "status": "success",
        "message": "All documents are complete! Application submitted for processing.",
        "signal": {
            "type": "SUBMIT_APPLICATION",
            "payload": {
                "total_documents": len(session.document_queue),
                "total_fields": len(session.extracted_data),
                "overridden_fields": [
                    k for k, v in session.extracted_data.items()
                    if v.get("manually_overridden")
                ],
            },
        },
    }


# ─── Tool Dispatcher ───

TOOL_EXECUTORS = {
    "switch_document_page": execute_switch_document_page,
    "update_extracted_field": execute_update_extracted_field,
    "reset_document_page": execute_reset_document_page,
    "answer_faq": execute_answer_faq,
    "submit_application": execute_submit_application,
}


def execute_tool(session: AgentSession, tool_name: str, args: dict) -> dict:
    """Dispatch a tool call to its executor."""
    executor = TOOL_EXECUTORS.get(tool_name)
    if not executor:
        return {
            "status": "error",
            "message": f"Unknown tool: {tool_name}",
            "signal": None,
        }

    try:
        return executor(session, **args)
    except TypeError as e:
        return {
            "status": "error",
            "message": f"Invalid arguments for {tool_name}: {str(e)}",
            "signal": None,
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Tool execution error: {str(e)}",
            "signal": None,
        }
