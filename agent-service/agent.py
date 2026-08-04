"""
Agent Orchestrator — core agentic loop using Gemini native function calling.

Handles:
- System prompt construction with live session state injection
- Gemini tool declarations
- Multi-turn function calling loop (call → validate → respond)
- Confirmation flow management
- Interrupt detection
"""

import json
import os
import time
import logging
import traceback
from typing import List, Dict, Any, Optional

from google import genai
from google.genai import types

from session import AgentSession
from tools import execute_tool
from config import (
    USE_VERTEX, GOOGLE_APPLICATION_CREDENTIALS, VERTEX_LOCATION,
    GEMINI_API_KEY, DEFAULT_MODEL,
)

logger = logging.getLogger("agent-service")


# ─── Gemini Client Singleton ───

_client: Optional[genai.Client] = None


def get_client() -> genai.Client:
    """Get or create the Gemini client."""
    global _client
    if _client is not None:
        return _client

    if USE_VERTEX:
        project_id = ""
        if GOOGLE_APPLICATION_CREDENTIALS and os.path.exists(GOOGLE_APPLICATION_CREDENTIALS):
            try:
                with open(GOOGLE_APPLICATION_CREDENTIALS, "r") as f:
                    creds = json.load(f)
                project_id = creds.get("project_id") or creds.get("quota_project_id") or ""
            except Exception as e:
                pass
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = GOOGLE_APPLICATION_CREDENTIALS

        kwargs = {"vertexai": True, "location": VERTEX_LOCATION}
        if project_id:
            kwargs["project"] = project_id

        _client = genai.Client(**kwargs)
    else:
        _client = genai.Client(api_key=GEMINI_API_KEY)

    return _client


# ─── Tool Declarations for Gemini ───

TOOL_DECLARATIONS = types.Tool(
    function_declarations=[
        types.FunctionDeclaration(
            name="switch_document_page",
            description=(
                "Switch the active document upload to a different document or page in the queue. "
                "Use this when the user wants to upload a different document or a specific page/side of a document. "
                "IMPORTANT: If the document has only 1 part, do NOT include part_id — it will be auto-resolved. "
                "Only include part_id when the document has multiple parts AND the user specified which part."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "doc_id": types.Schema(
                        type="STRING",
                        description="The document identifier or user-friendly name (e.g., 'Aadhaar', 'PAN Card', 'doc_pan_001')",
                    ),
                    "part_id": types.Schema(
                        type="STRING",
                        description="The specific part/page (e.g., 'front', 'back', 'certificate'). Only needed for multi-part documents when user specifies a part.",
                    ),
                },
                required=["doc_id"],
            ),
        ),
        types.FunctionDeclaration(
            name="update_extracted_field",
            description=(
                "Update a specific extracted data field with a new value provided by the user. "
                "Use this when the user says a field value is incorrect and provides the correct value. "
                "The update will be flagged as a manual override for human audit."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "field_key": types.Schema(
                        type="STRING",
                        description="The field key to update (e.g., 'doc_aadhaar_name', 'doc_pan_number', 'doc_aadhaar_last4')",
                    ),
                    "new_value": types.Schema(
                        type="STRING",
                        description="The corrected value from the user",
                    ),
                    "reason": types.Schema(
                        type="STRING",
                        description="Optional reason for the correction",
                    ),
                },
                required=["field_key", "new_value"],
            ),
        ),
        types.FunctionDeclaration(
            name="reset_document_page",
            description=(
                "Reset a previously uploaded document page, clearing all extracted data for it "
                "and marking it as pending for re-upload. Use after user confirms they want to re-upload."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "doc_id": types.Schema(
                        type="STRING",
                        description="The document identifier",
                    ),
                    "part_id": types.Schema(
                        type="STRING",
                        description="The part/page to reset",
                    ),
                },
                required=["doc_id", "part_id"],
            ),
        ),
        types.FunctionDeclaration(
            name="answer_faq",
            description=(
                "Answer a user's question about the document capture process, document requirements, "
                "or general KYC/loan-related queries. Use this for informational questions."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "user_query": types.Schema(
                        type="STRING",
                        description="The user's question to answer",
                    ),
                },
                required=["user_query"],
            ),
        ),
        types.FunctionDeclaration(
            name="submit_application",
            description=(
                "Submit the application for processing. Only succeeds if ALL document pages are completed. "
                "Use when the user explicitly says they want to submit or are done with all documents."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={},
            ),
        ),
    ]
)


# ─── System Prompt Builder ───

def build_system_prompt(session: AgentSession) -> str:
    """Construct the system prompt with live session state."""

    # Build documents metadata
    docs_info = []
    for doc_id, manifest in session.manifests.items():
        title = manifest["title"].get("English", doc_id)
        parts = manifest.get("parts", [])
        part_count = len(parts)
        part_names = [f"{p['name']['English']} ({p['id']})" for p in parts]
        expects = manifest.get("expects", [])
        docs_info.append(
            f"  - {title} ({doc_id}): {part_count} part(s): {', '.join(part_names)}\n"
            f"    Expected fields: {', '.join(expects)}"
        )

    # Build queue status
    queue_lines = []
    for item in session.document_queue:
        status_emoji = {"COMPLETED": "✅", "ACTIVE": "🔵", "PENDING": "⏳"}.get(item["status"], "❓")
        queue_lines.append(
            f"  {status_emoji} {item['doc_title']} — {item['part_name']} [{item['status']}]"
        )

    # Build extracted data summary
    extracted_lines = []
    for key, data in session.extracted_data.items():
        override_tag = " ⚠️ MANUALLY OVERRIDDEN" if data.get("manually_overridden") else ""
        extracted_lines.append(
            f"  {key}: {json.dumps(data['value'])} (confidence: {data['confidence']:.0%}){override_tag}"
        )

    # Pending confirmation section
    confirmation_section = ""
    if session.pending_confirmation:
        pc = session.pending_confirmation
        confirmation_section = f"""
## PENDING CONFIRMATION
There is a pending confirmation waiting for the user's response:
Type: {pc['type']}
Details: Re-upload {pc.get('doc_title', '')} — {pc.get('part_name', '')}

IMPORTANT: Analyze the user's next message:
- If they confirm (e.g., "yes", "sure", "go ahead", "ok", "do it"), proceed with:
  1. Call reset_document_page for doc_id="{pc.get('doc_id', '')}" part_id="{pc.get('part_id', '')}"
  2. Then call switch_document_page for the same doc_id and part_id
- If they say something unrelated or a new request, abandon this confirmation and handle their new request instead.
"""

    stage_guidance = ""
    if session.is_all_complete():
        stage_guidance = """
## CURRENT STAGE: FINAL VERIFICATION & DATA REVIEW
All required documents have been captured and processed! The user is now reviewing their final extracted application details on screen.

CRITICAL INSTRUCTIONS FOR THIS STAGE:
1. When the user asks to change, update, fix, or edit ANY detail (such as name, address, pincode, DOB, PAN number, GSTIN, etc.):
   -> YOU CAN AND MUST call `update_extracted_field(field_key, new_value)` directly!
   -> Do NOT tell the user to upload a document! Confirm that you updated the field.
2. If the user asks to re-upload or replace a document (e.g., "I want to re-upload my PAN card" or "switch to PAN card"):
   -> Ask for confirmation, and when confirmed call `reset_document_page` followed by `switch_document_page`.
"""

    LANG_NAMES = {
        "en": "English",
        "hi": "Hindi (हिन्दी)",
        "fr": "French (Français)",
        "ar": "Arabic (العربية)"
    }
    target_lang_name = LANG_NAMES.get(session.language, "English")

    prompt = f"""You are a document capture assistant helping a user upload and verify their KYC documents for a loan application.
You control the document upload interface through tool calls.

## LANGUAGE INSTRUCTION
- You MUST communicate with the user ONLY in {target_lang_name} ({session.language}). All your text responses must be fluently written in {target_lang_name}.

## YOUR PERSONALITY
- Concise, friendly, and professional
- Use 1-2 sentences max for responses
- Never ask unnecessary questions (e.g., don't ask which part for single-part documents)

## CURRENT SESSION STATE
{stage_guidance}
### Document Queue (upload order):
{chr(10).join(queue_lines)}

### Extracted Data:
{chr(10).join(extracted_lines) if extracted_lines else "  (no data extracted yet)"}

### Active Document: {session._get_active_summary() or "None"}

## AVAILABLE DOCUMENTS
{chr(10).join(docs_info)}
{confirmation_section}
## TOOL USAGE RULES

### switch_document_page
- If the document has ONLY 1 part, do NOT ask which part. Auto-resolve it silently.
- If the document has multiple parts and user didn't specify which → ask them.
- If user says "all pages" of a document → you should call switch_document_page once for the first pending part. Mention the other parts are queued.
- NEVER call this tool if the target page is already COMPLETED. Instead, ask user if they want to re-upload.

### update_extracted_field
- Only update fields that exist in the extracted data above.
- If the user mentions a field that doesn't exist, tell them which fields are available.
- If the user's input is ambiguous (e.g., "fix the name" when multiple docs have name fields), ask which document they mean.
- Use the exact field_key from the extracted data (e.g., "doc_aadhaar_name", not "name").

### reset_document_page
- Only use this after user explicitly confirms they want to re-upload a completed page.
- This clears all extracted data from that page.

### answer_faq
- Use for informational questions about documents, requirements, or the process.

### submit_application
- Only when user explicitly wants to submit/finish.
- Will fail if any documents are still pending.

## RESPONSE GUIDELINES
- Keep responses under 2 sentences unless listing information.
- Be proactive: after switching documents, briefly tell user what to do next.
- If a tool call fails validation, explain the error clearly to the user.
"""
    return prompt


# ─── Content Builder ───

def _build_contents(history: List[dict]) -> List[types.Content]:
    """Convert conversation history dicts to Gemini Content objects."""
    contents = []

    for entry in history:
        role = entry["role"]

        if role == "user":
            contents.append(
                types.Content(
                    role="user",
                    parts=[types.Part.from_text(text=entry["text"])],
                )
            )
        elif role == "model":
            parts = []
            if entry.get("text"):
                parts.append(types.Part.from_text(text=entry["text"]))
            if entry.get("function_calls"):
                for fc in entry["function_calls"]:
                    parts.append(
                        types.Part.from_function_call(
                            name=fc["name"],
                            args=fc["args"],
                        )
                    )
            if parts:
                contents.append(types.Content(role="model", parts=parts))

        elif role == "function_response":
            contents.append(
                types.Content(
                    role="user",
                    parts=[
                        types.Part.from_function_response(
                            name=entry["name"],
                            response=entry["response"],
                        )
                    ],
                )
            )

    return contents


# ─── Main Agent Loop ───

async def run_agent_turn(session: AgentSession, user_message: str) -> dict:
    """
    Execute one turn of the agent loop.

    Returns:
    {
        "agent_response": str,
        "tool_calls": [{ name, args, validation, signal }],
        "session_state": dict,
        "pending_confirmation": dict | None,
        "internal_log": [{ step, ... }],
    }
    """
    session.turn_count += 1
    internal_log = []
    tool_calls_results = []

    logger.info(f"🗣️ [TURN START] Session: {session.session_id} | Turn #{session.turn_count} | User: '{user_message}'")

    # 1. Add user message to history
    session.conversation_history.append({"role": "user", "text": user_message})

    # 2. Build system prompt
    t0 = time.time()
    system_prompt = build_system_prompt(session)
    internal_log.append({
        "step": "system_prompt_built",
        "system_prompt_length": len(system_prompt),
        "elapsed_ms": round((time.time() - t0) * 1000),
    })

    # 3. Build Gemini contents from history
    contents = _build_contents(session.conversation_history)

    # 4. Call Gemini
    client = get_client()
    config = types.GenerateContentConfig(
        tools=[TOOL_DECLARATIONS],
        system_instruction=system_prompt,
        temperature=0.3,
        max_output_tokens=2048,
        thinking_config=types.ThinkingConfig(thinking_budget=0),
    )

    t1 = time.time()
    try:
        response = await client.aio.models.generate_content(
            model=DEFAULT_MODEL,
            contents=contents,
            config=config,
        )
    except Exception as e:
        logger.error(f"❌ [GEMINI ERROR] Session: {session.session_id} | Error: {e}")
        internal_log.append({
            "step": "gemini_error",
            "error": str(e),
            "traceback": traceback.format_exc(),
        })
        error_text = f"I'm sorry, I encountered an error processing your request. Please try again."
        session.conversation_history.append({"role": "model", "text": error_text})
        return {
            "agent_response": error_text,
            "tool_calls": [],
            "session_state": session.to_dict(),
            "pending_confirmation": session.pending_confirmation,
            "internal_log": internal_log,
        }

    gemini_latency = round((time.time() - t1) * 1000)
    internal_log.append({
        "step": "gemini_called",
        "model": DEFAULT_MODEL,
        "latency_ms": gemini_latency,
    })

    # 5. Process response — check for function calls
    candidate = response.candidates[0] if response.candidates else None
    if not candidate or not candidate.content or not candidate.content.parts:
        error_text = "I didn't get a valid response. Could you rephrase that?"
        session.conversation_history.append({"role": "model", "text": error_text})
        logger.warning(f"⚠️ [EMPTY RESPONSE] Session: {session.session_id}")
        return {
            "agent_response": error_text,
            "tool_calls": [],
            "session_state": session.to_dict(),
            "pending_confirmation": session.pending_confirmation,
            "internal_log": internal_log,
        }

    # Check if the model wants to call function(s)
    function_call_parts = [part for part in candidate.content.parts if part.function_call]
    text_part = next((part for part in candidate.content.parts if part.text), None)

    if function_call_parts:
        needs_confirmation_return = None

        for function_call_part in function_call_parts:
            fc = function_call_part.function_call
            tool_name = fc.name
            tool_args = dict(fc.args) if fc.args else {}

            logger.info(f"🔧 [TOOL CALL] Session: {session.session_id} | Function: {tool_name}({json.dumps(tool_args)})")

            internal_log.append({
                "step": "function_call_received",
                "tool_name": tool_name,
                "arguments": tool_args,
            })

            # Add model's function call to history
            session.conversation_history.append({
                "role": "model",
                "text": None,
                "function_calls": [{"name": tool_name, "args": tool_args}],
            })

            # 6. Execute tool (validate + signal)
            t2 = time.time()
            tool_result = execute_tool(session, tool_name, tool_args)
            tool_latency = round((time.time() - t2) * 1000)

            logger.info(f"⚙️ [TOOL EXEC] Session: {session.session_id} | Status: {tool_result['status']} | Msg: '{tool_result['message']}'")
            if tool_result.get("signal"):
                logger.info(f"📡 [SIGNAL EMITTED] Session: {session.session_id} | Signal: {tool_result['signal']['type']} -> {json.dumps(tool_result['signal']['payload'])}")
                if tool_result["signal"].get("type") in ("SWITCH_PAGE", "RESET_PAGE"):
                    payload = tool_result["signal"]["payload"]
                    from tools import sync_doc_capture_page
                    page_info_data = await sync_doc_capture_page(session.session_id, payload.get("doc_id", ""), payload.get("part_id", ""))
                    if page_info_data:
                        payload["page_info"] = page_info_data

            internal_log.append({
                "step": "tool_executed",
                "tool_name": tool_name,
                "result_status": tool_result["status"],
                "result_message": tool_result["message"],
                "signal": tool_result.get("signal"),
                "elapsed_ms": tool_latency,
            })

            tool_calls_results.append({
                "tool_name": tool_name,
                "arguments": tool_args,
                "validation": {
                    "status": tool_result["status"],
                    "message": tool_result["message"],
                },
                "signal": tool_result.get("signal"),
            })

            # Append function response to history
            session.conversation_history.append({
                "role": "function_response",
                "name": tool_name,
                "response": {
                    "status": tool_result["status"],
                    "message": tool_result["message"],
                    "signal": tool_result.get("signal"),
                },
            })

            # If tool needs confirmation, capture early return state
            if tool_result["status"] == "needs_confirmation":
                agent_text = tool_result["message"]
                session.conversation_history.append({"role": "model", "text": agent_text})
                logger.info(f"🤖 [AGENT RESPONSE (CONFIRMATION NEEDED)] Session: {session.session_id} | Text: '{agent_text}'")
                needs_confirmation_return = {
                    "agent_response": agent_text,
                    "tool_calls": tool_calls_results,
                    "session_state": session.to_dict(),
                    "pending_confirmation": session.pending_confirmation,
                    "internal_log": internal_log,
                }
                break

            if tool_result["status"] in ("success", "error", "validation_error", "ambiguous", "blocked"):
                if tool_result["status"] == "success":
                    session.pending_confirmation = None

        if needs_confirmation_return:
            return needs_confirmation_return

        # 7. Send function responses back to Gemini for final text
        contents = _build_contents(session.conversation_history)

        t3 = time.time()
        try:
            final_response = await client.aio.models.generate_content(
                model=DEFAULT_MODEL,
                contents=contents,
                config=types.GenerateContentConfig(
                    tools=[TOOL_DECLARATIONS],
                    system_instruction=system_prompt,
                    temperature=0.3,
                    max_output_tokens=2048,
                    thinking_config=types.ThinkingConfig(thinking_budget=0),
                ),
            )
            final_latency = round((time.time() - t3) * 1000)

            agent_text = ""
            if final_response.candidates and final_response.candidates[0].content:
                for part in final_response.candidates[0].content.parts:
                    if part.text:
                        agent_text += part.text

            if not agent_text:
                agent_text = tool_result["message"]

            internal_log.append({
                "step": "gemini_final_response",
                "text": agent_text,
                "latency_ms": final_latency,
            })

        except Exception as e:
            agent_text = tool_result["message"]
            logger.error(f"❌ [GEMINI FINAL TEXT ERROR] Session: {session.session_id} | Error: {e}")
            internal_log.append({
                "step": "gemini_final_response_error",
                "error": str(e),
                "fallback_text": agent_text,
            })

    else:
        # No function call — pure text response
        agent_text = text_part.text if text_part else "I'm not sure how to help with that."

        internal_log.append({
            "step": "text_response",
            "text": agent_text,
        })

        # If there was a pending confirmation but the model didn't call any tool,
        # it means the model decided the user's message wasn't a confirmation.
        # Clear pending confirmation if the user said something unrelated.
        # (The model's system prompt handles this logic)

    # 8. Add agent response to history
    session.conversation_history.append({"role": "model", "text": agent_text})

    return {
        "agent_response": agent_text,
        "tool_calls": tool_calls_results,
        "session_state": session.to_dict(),
        "pending_confirmation": session.pending_confirmation,
        "internal_log": internal_log,
    }
