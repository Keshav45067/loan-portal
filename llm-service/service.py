"""
LLM Service — business logic layer.
Routes gRPC requests to the appropriate engine.
"""

import sys
import os
import traceback

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'shared'))
from log_utils.logger import get_logger, LatencyTracker, get_req_id

from engines.gemini import GeminiEngine
from config import GEMINI_API_KEY, DEFAULT_MODEL, USE_VERTEX, GOOGLE_APPLICATION_CREDENTIALS, VERTEX_LOCATION

logger = get_logger("llm-service")


class LLMService:
    """Manages LLM engines and routes requests."""

    def __init__(self):
        self._engines = {}
        self._default_engine_name = "gemini"

    def load(self):
        """Initialize all configured engines."""
        # Gemini engine (primary)
        if USE_VERTEX:
            project_id = ""
            if GOOGLE_APPLICATION_CREDENTIALS and os.path.exists(GOOGLE_APPLICATION_CREDENTIALS):
                try:
                    import json
                    with open(GOOGLE_APPLICATION_CREDENTIALS, "r") as f:
                        creds = json.load(f)
                    project_id = creds.get("project_id") or creds.get("quota_project_id") or ""
                except Exception as e:
                    logger.error(f"Failed to read GOOGLE_APPLICATION_CREDENTIALS: {e}")

            # Ensure env var is set for genai.Client to pick up
            if GOOGLE_APPLICATION_CREDENTIALS:
                os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = GOOGLE_APPLICATION_CREDENTIALS

            gemini = GeminiEngine(
                use_vertex=True,
                project_id=project_id,
                location=VERTEX_LOCATION
            )
        else:
            gemini = GeminiEngine(api_key=GEMINI_API_KEY)

        gemini.load()
        self._engines["gemini"] = gemini
        logger.info("LLM Service loaded", engine="gemini", model=DEFAULT_MODEL, use_vertex=USE_VERTEX)

    def _get_engine(self, model: str = "") -> GeminiEngine:
        """Get the appropriate engine for the model. Currently always Gemini."""
        return self._engines[self._default_engine_name]

    async def generate(self, prompt: str, model: str, temperature: float,
                       max_tokens: int, thinking_budget: int,
                       system_instruction: str,
                       disable_thinking: bool = False) -> dict:
        """Unary text generation."""
        engine = self._get_engine(model)
        req_id = get_req_id()

        with LatencyTracker() as t:
            result = await engine.generate(
                prompt=prompt,
                model=model or DEFAULT_MODEL,
                temperature=temperature,
                max_tokens=max_tokens,
                thinking_budget=thinking_budget,
                system_instruction=system_instruction,
                disable_thinking=disable_thinking,
            )

        logger.info("Generate completed",
                     req_id=req_id,
                     model=model or DEFAULT_MODEL,
                     latency_ms=t.elapsed_ms,
                     prompt_tokens=result.get("prompt_tokens", 0),
                     completion_tokens=result.get("completion_tokens", 0))
        return result

    async def generate_stream(self, prompt: str, model: str, temperature: float,
                              max_tokens: int, thinking_budget: int,
                              system_instruction: str,
                              disable_thinking: bool = False):
        """Streaming text generation. Yields text chunks."""
        engine = self._get_engine(model)
        req_id = get_req_id()
        chunk_count = 0

        logger.info("GenerateStream started", req_id=req_id, model=model or DEFAULT_MODEL)

        async for chunk in engine.generate_stream(
            prompt=prompt,
            model=model or DEFAULT_MODEL,
            temperature=temperature,
            max_tokens=max_tokens,
            thinking_budget=thinking_budget,
            system_instruction=system_instruction,
            disable_thinking=disable_thinking,
        ):
            chunk_count += 1
            yield chunk

        logger.info("GenerateStream completed",
                     req_id=req_id, model=model or DEFAULT_MODEL,
                     details={"total_chunks": chunk_count})

    async def extract(self, prompt: str, model: str, temperature: float,
                      system_instruction: str, thinking_budget: int,
                      disable_thinking: bool = False) -> dict:
        """Structured JSON extraction."""
        engine = self._get_engine(model)
        req_id = get_req_id()

        with LatencyTracker() as t:
            result = await engine.extract_json(
                prompt=prompt,
                model=model or DEFAULT_MODEL,
                temperature=temperature,
                system_instruction=system_instruction,
                thinking_budget=thinking_budget,
                disable_thinking=disable_thinking,
            )

        logger.info("Extract completed",
                     req_id=req_id, model=model or DEFAULT_MODEL,
                     latency_ms=t.elapsed_ms,
                     details={"success": result.get("success", False)})
        return result

    async def generate_multimodal(self, prompt: str, images: list[bytes],
                                  model: str, temperature: float,
                                  system_instruction: str,
                                  thinking_budget: int,
                                  disable_thinking: bool = False) -> dict:
        """Multimodal generation (images + text)."""
        engine = self._get_engine(model)
        req_id = get_req_id()

        with LatencyTracker() as t:
            result = await engine.generate_multimodal(
                prompt=prompt,
                images=images,
                model=model or DEFAULT_MODEL,
                temperature=temperature,
                system_instruction=system_instruction,
                thinking_budget=thinking_budget,
                disable_thinking=disable_thinking,
            )

        logger.info("GenerateMultimodal completed",
                     req_id=req_id, model=model or DEFAULT_MODEL,
                     latency_ms=t.elapsed_ms,
                     details={"num_images": len(images)})
        return result
