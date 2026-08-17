"""
Nudge Generator — Generates lightweight, contextual, non-robotic silence nudges.
Uses gRPC Generate call to LLM with low token overhead (~70 tokens).
Supports dynamic background noise advice when high ambient noise is detected.
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

# Fallback nudge templates if LLM is unavailable (Normal vs High Background Noise)
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

FALLBACK_NOISE_NUDGES = {
    "hi": [
        "माफ़ कीजिए, आपके पीछे थोड़ा शोर आ रहा है, क्या आप किसी शांत जगह जाकर बता सकते हैं?",
        "आसपास थोड़ा शोर लग रहा है, कृपया माइक के पास आकर आराम से उत्तर दीजिए।",
    ],
    "en": [
        "Sorry, it seems a bit noisy around you. Could you move to a quieter spot and let me know?",
        "There seems to be some background noise. Please speak closer to the mic or move to a quiet area.",
    ],
    "fr": [
        "Désolé, il y a un peu de bruit autour de vous. Pourriez-vous vous déplacer dans un endroit plus calme ?",
        "Il semble y avoir du bruit ambiant. N'hésitez pas à vous rapprocher du micro.",
    ],
    "ar": [
        "عذراً، يبدو أن هناك بعض الضوضاء حولك. هل يمكنك الانتقال إلى مكان أكثر هدوءاً؟",
        "هناك بعض الضجيج في الخلفية، يرجى التحدث بالقرب من الميكروفون.",
    ],
    "mr": [
        "माफ करा, तुमच्या मागे थोडा आवाज येतोय, कृपया शांत ठिकाणी जाऊन सांगू शकता का?",
        "आजूबाजूला थोडा आवाज आहे, कृपया माइकजवळ येऊन निवांत सांगा.",
    ]
}


async def generate_nudge(
    llm_stub,
    question_text: str,
    nudge_guideline: str,
    language: str = "hi",
    nudge_count: int = 1,
    is_high_bg_noise: bool = False,
    req_id: str = ""
) -> str:
    """
    Generate a 1-sentence contextual nudge for silence/inactivity.
    If is_high_bg_noise is True, advises the user to move to a quieter spot / speak closer.
    Only called for 'voice-qa' nodes.
    """
    lang_names = {"hi": "Hindi", "en": "English", "fr": "French", "ar": "Arabic", "mr": "Marathi"}
    lang_name = lang_names.get(language, "English")

    if is_high_bg_noise:
        noise_instruction = (
            "The user's environment currently has noticeable background noise. "
            "In addition to nudging them on the question, politely mention the background noise and "
            "kindly advise them to move to a quieter area or speak closer to the mic. "
        )
    else:
        noise_instruction = ""

    prompt = (
        f"You are a super warm, friendly, empathetic assistant speaking in {lang_name}.\n"
        f"The applicant has been silent after being asked: \"{question_text}\"\n"
        f"Attempt: {nudge_count}\n"
        f"{noise_instruction}"
        f"Task: Generate a 1-sentence (max 15 words) super friendly, natural, warm nudge. "
        f"Use natural conversational fillers. Output ONLY the nudge text in {lang_name}."
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
                logger.info(f"Generated contextual nudge in {elapsed_ms:.0f}ms (noise_mode={is_high_bg_noise}): '{clean_text}'", req_id=req_id)
                return clean_text
        except Exception as e:
            logger.warning(f"Nudge LLM generation failed: {e}. Using fallback.", req_id=req_id)

    # Fallback to local template list
    template_map = FALLBACK_NOISE_NUDGES if is_high_bg_noise else FALLBACK_NUDGES
    options = template_map.get(language, template_map.get("hi", FALLBACK_NUDGES["hi"]))
    idx = min(nudge_count - 1, len(options) - 1)
    return options[max(0, idx)]
