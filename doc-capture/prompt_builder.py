import json
from typing import Tuple
from session_manager import CaptureSession

def build_faq_system_prompt(session: CaptureSession) -> Tuple[str, str]:
    """
    Builds the system and context prompts for the RawAgentSession.
    Returns: (system_prompt, context_prompt)
    """
    system_parts = []
    context_parts = []
    
    # 1. Scheme FAQ context
    scheme_faq = session.scheme_config.get("faq_context", {})
    if scheme_faq.get("system_prompt"):
        system_parts.append(scheme_faq["system_prompt"])
        
    # 2. Document FAQ context
    doc_faq = session.current_document_config.get("llm_faq_context", {})
    if doc_faq.get("system_prompt"):
        system_parts.append(doc_faq["system_prompt"])
        
    if doc_faq.get("policies"):
        context_parts.append("Document Policies:")
        for policy in doc_faq["policies"]:
            context_parts.append(f"- {policy}")
            
    # 3. Current page context
    current_page = session.get_current_page()
    if current_page:
        doc_name = session.current_document_config.get("document_name", "Document")
        page_name = current_page.get("page_name", "Page")
        page_ctx = (
            f"The user is currently going to upload the '{page_name}' of their '{doc_name}'. "
            f"Try to keep the response limited to that page, but if user insists, then explain "
            f"the details of other pages also, but only if user insists."
        )
        context_parts.append(page_ctx)
        
    # 4. Conversation History (if we wanted it in system prompt, but usually we just send it as dialogue)
    # The RawAgentSession handles conversation history by keeping state, but if we need to inject it as context:
    history = session.get_faq_history()
    if history:
        context_parts.append("\nPrevious Conversation Context for this Document:")
        for msg in history:
            role = msg.get("role", "unknown").upper()
            content = msg.get("content", "")
            context_parts.append(f"{role}: {content}")
            
    system_prompt = "\n\n".join(system_parts)
    context_prompt = "\n\n".join(context_parts)
    
    return system_prompt, context_prompt


def build_extraction_prompt(page_config: dict, ocr_text: str) -> str:
    """
    Builds the exact prompt to send to the LLM for data extraction.
    """
    parts = []
    
    # 1. OCR Data
    parts.append("--- RAW OCR DATA START ---")
    parts.append(ocr_text if ocr_text else "<No text detected>")
    parts.append("--- RAW OCR DATA END ---\n")
    
    # 2. Page Extraction Prompt
    if page_config.get("extraction_prompt"):
        parts.append(page_config["extraction_prompt"])
        parts.append("")
        
    # 3. Field Instructions
    parts.append("Extract the following fields based on their specific instructions:")
    fields = page_config.get("fields_to_extract", [])
    for field in fields:
        f_id = field.get("field_id")
        f_type = field.get("type", "string")
        f_inst = field.get("extraction_instruction", "")
        parts.append(f"- {f_id} (Type: {f_type}): {f_inst}")
        
    # 4. Output Format
    parts.append("\nReturn ONLY a raw JSON object with the exact field IDs as keys. "
                 "For each field, provide an object with 'value' and 'confidence'. "
                 "If a value cannot be determined, set 'value' to null. "
                 "Do not include markdown formatting or backticks.")
    parts.append("Example format:")
    parts.append('{"name": {"value": "John Doe", "confidence": 0.95}, "dob": {"value": null, "confidence": 0.0}}')
    
    return "\n".join(parts)
