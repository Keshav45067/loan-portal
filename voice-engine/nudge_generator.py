"""
Nudge Generator — Generates lightweight, contextual, non-robotic silence nudges.
Uses gRPC Generate call to LLM with low token overhead (~70 tokens).
"""

import time
from typing import Optional
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'shared'))
from log_utils.logger import get_logger

sys.path.insert(0, os.path.dirname(__file__))
from generated import llm_pb2

logger = get_logger("voice-engine")

# Fallback nudge templates if LLM is unavailable
FALLBACK_NUDGES = {
    "hi": [
        "अरे सुनिए, क्या आपको मेरी आवाज आ रही है? कोई बात नहीं, आप आराम से बताइए!",
        "अरे कोई बात नहीं, आप आराम से उत्तर दे सकते हैं।",
    ],
    "en": [
        "Hey there, can you hear me alright? No worries at all, take your time!",
        "Take your time, please let me know if you need a hand with anything.",
    ],
    "fr": [
        "Ah, vous êtes là ? Pas de soucis du tout, prenez votre temps !",
        "Prenez votre temps, dites-moi si vous avez besoin d'aide.",
    ],
    "ar": [
        "أهلاً، هل تسمعني بشكل جيد؟ لا تقلق أبداً، خذ وقتك!",
        "خذ وقتك الكامل، وأخبرني إذا كنت بحاجة إلى أي مساعدة.",
    ],
    "mr": [
        "अहो ऐका, तुम्हाला माझा आवाज येतोय का? काही हरकत नाही, तुम्ही निवांत सांगा!",
        "काही काळजी करू नका, तुम्ही सवडीने उत्तर देऊ शकता.",
    ]
}


async def generate_nudge(
    llm_stub,
    question_text: str,
    nudge_guideline: str,
    language: str = "hi",
    nudge_count: int = 1,
    req_id: str = ""
) -> str:
    """
    Generate a 1-sentence contextual nudge for silence/inactivity.
    Only called for 'voice-qa' nodes.
    """
    lang_names = {"hi": "Hindi", "en": "English", "fr": "French", "ar": "Arabic", "mr": "Marathi"}
    lang_name = lang_names.get(language, "English")

    prompt = (
        f"You are a super warm, friendly, empathetic assistant speaking in {lang_name}\n"
        f"The applicant has been silent after being asked: \"{question_text}\"\n"
        f"Attempt: {nudge_count}\n"
        f"Task: Generate a 1-sentence (max 10 words) super friendly, natural, warm nudge asking if they can hear you or if they need a moment. Use natural conversational fillers. Output ONLY the nudge text in {lang_name}"
    )

    if llm_stub is not None:
        try:
            t0 = time.perf_counter()
            stream = llm_stub.GenerateStream(
                llm_pb2.GenerateRequest(
                    prompt=prompt,
                    model="gemini-2.5-flash",
                    temperature=0.7,
                    system_instruction=f"Use {lang_name} only. Be concise, polite, and natural.",
                    disable_thinking=True,
                    thinking_budget=0,
                ),
                metadata=[("x-request-id", req_id)] if req_id else []
            )

            full_text = ""
            async for msg in stream:
                if getattr(msg, 'text', None):
                    full_text += msg.text

            clean_text = full_text.strip().replace('"', '').replace('\n', ' ')
            if clean_text:
                elapsed_ms = (time.perf_counter() - t0) * 1000
                logger.info(f"Generated contextual nudge in {elapsed_ms:.0f}ms: '{clean_text}'", req_id=req_id)
                return clean_text
        except Exception as e:
            logger.warning(f"Nudge LLM generation failed: {e}. Using fallback.", req_id=req_id)

    # Fallback to local template list
    options = FALLBACK_NUDGES.get(language, FALLBACK_NUDGES["hi"])
    idx = min(nudge_count - 1, len(options) - 1)
    return options[max(0, idx)]
