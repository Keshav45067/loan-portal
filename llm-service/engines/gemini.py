"""
Gemini LLM Engine — wraps the google-genai SDK for Gemini models.

Supports:
- Vertex AI (service account) and AI Studio (API key) modes
- Streaming and non-streaming generation
- Structured JSON extraction
- Multimodal (images + text) generation
- Configurable thinking budget
"""

import json
import traceback
import io
from typing import AsyncIterator, Optional

from google import genai
from google.genai import types

from engines.base import BaseLLMEngine

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'shared'))
from log_utils.logger import get_logger

logger = get_logger("llm-service")


class GeminiEngine(BaseLLMEngine):
    """
    Google Gemini LLM engine.

    Can initialize in two modes:
    - API Key mode: Uses GEMINI_API_KEY (simpler, for dev)
    - Vertex AI mode: Uses service account credentials (for prod)
    """

    def __init__(
        self,
        api_key: str = "",
        project_id: str = "",
        location: str = "asia-south1",
        use_vertex: bool = False,
    ):
        self._api_key = api_key
        self._project_id = project_id
        self._location = location
        self._use_vertex = use_vertex
        self._client: Optional[genai.Client] = None

    def load(self):
        """Initialize the Gemini client."""
        try:
            if self._use_vertex:
                self._client = genai.Client(
                    vertexai=True,
                    project=self._project_id,
                    location=self._location,
                )
                logger.info("Gemini client loaded (Vertex AI mode)",
                            project=self._project_id, location=self._location)
            else:
                self._client = genai.Client(api_key=self._api_key)
                logger.info("Gemini client loaded (API Key mode)")
        except Exception as e:
            logger.error(f"Failed to initialize Gemini client: {e}", error=str(e))
            raise

    def _resolve_model(self, model: str) -> str:
        """Resolve model name, applying aliases if needed."""
        aliases = {
            "flash": "gemini-2.5-flash",
            "pro": "gemini-2.5-pro",
            "flash-lite": "gemini-2.0-flash-lite",
        }
        return aliases.get(model, model) if model else "gemini-2.5-flash"

    def _build_config(
        self,
        temperature: float,
        max_tokens: int,
        thinking_budget: int,
        system_instruction: str,
        response_mime_type: str = None,
        disable_thinking: bool = False,
    ) -> types.GenerateContentConfig:
        """Build Gemini generation config."""
        kwargs = {
            "max_output_tokens": max(max_tokens, 8192),
            "temperature": temperature,
        }

        if system_instruction:
            kwargs["system_instruction"] = system_instruction

        if response_mime_type:
            kwargs["response_mime_type"] = response_mime_type

        # Apply thinking config — even in JSON mode (matching Hindi repo)
        # Hindi uses both response_mime_type="application/json" AND thinking_budget=0
        if disable_thinking:
            kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
        elif thinking_budget > 0:
            kwargs["thinking_config"] = types.ThinkingConfig(
                thinking_budget=thinking_budget
            )
        # else: no ThinkingConfig → model uses default (can think freely)

        return types.GenerateContentConfig(**kwargs)

    async def generate(
        self,
        prompt: str,
        model: str,
        temperature: float = 1.0,
        max_tokens: int = 8192,
        thinking_budget: int = 0,
        system_instruction: str = "",
        disable_thinking: bool = False,
    ) -> dict:
        """Generate text from a prompt (unary)."""
        if not self._client:
            raise RuntimeError("Client not loaded. Call load() first.")

        resolved_model = self._resolve_model(model)

        config = self._build_config(
            temperature=temperature,
            max_tokens=max_tokens,
            thinking_budget=thinking_budget,
            system_instruction=system_instruction,
            disable_thinking=disable_thinking,
        )

        response = await self._client.aio.models.generate_content(
            model=resolved_model,
            contents=prompt,
            config=config,
        )

        text = response.text.strip() if response.text else ""
        usage = getattr(response, "usage_metadata", None)

        return {
            "text": text,
            "prompt_tokens": getattr(usage, "prompt_token_count", 0) if usage else 0,
            "completion_tokens": getattr(usage, "candidates_token_count", 0) if usage else 0,
        }

    async def generate_stream(
        self,
        prompt: str,
        model: str,
        temperature: float = 1.0,
        max_tokens: int = 8192,
        thinking_budget: int = 0,
        system_instruction: str = "",
        disable_thinking: bool = False,
    ) -> AsyncIterator[str]:
        """Stream text generation chunk by chunk."""
        if not self._client:
            raise RuntimeError("Client not loaded. Call load() first.")

        resolved_model = self._resolve_model(model)

        config = self._build_config(
            temperature=temperature,
            max_tokens=max_tokens,
            thinking_budget=thinking_budget,
            system_instruction=system_instruction,
            disable_thinking=disable_thinking,
        )

        response_stream = await self._client.aio.models.generate_content_stream(
            model=resolved_model,
            contents=prompt,
            config=config,
        )

        async for chunk in response_stream:
            if chunk.text:
                yield chunk.text

    async def extract_json(
        self,
        prompt: str,
        model: str,
        temperature: float = 0.2,
        system_instruction: str = "",
        thinking_budget: int = 0,
        disable_thinking: bool = False,
    ) -> dict:
        """Generate structured JSON output."""
        if not self._client:
            raise RuntimeError("Client not loaded. Call load() first.")

        resolved_model = self._resolve_model(model)

        config = self._build_config(
            temperature=temperature,
            max_tokens=8192,
            thinking_budget=thinking_budget,
            system_instruction=system_instruction,
            response_mime_type="application/json",
            disable_thinking=disable_thinking,
        )

        try:
            response = await self._client.aio.models.generate_content(
                model=resolved_model,
                contents=prompt,
                config=config,
            )

            result = response.text.strip() if response.text else "{}"

            # Clean markdown wrapping
            if result.startswith("```json"):
                result = result[7:]
            if result.startswith("```"):
                result = result[3:]
            if result.endswith("```"):
                result = result[:-3]

            return {"json_text": result.strip(), "success": True, "error": ""}

        except Exception as e:
            logger.error(f"JSON extraction failed: {e}", error=str(e))
            return {"json_text": "{}", "success": False, "error": str(e)}

    async def generate_multimodal(
        self,
        prompt: str,
        images: list[bytes],
        model: str,
        temperature: float = 1.0,
        system_instruction: str = "",
        thinking_budget: int = 0,
        disable_thinking: bool = False,
    ) -> dict:
        """Generate text from prompt + images."""
        if not self._client:
            raise RuntimeError("Client not loaded. Call load() first.")

        resolved_model = self._resolve_model(model)

        response_mime_type = None
        if "json" in prompt.lower() or "schema" in prompt.lower():
            response_mime_type = "application/json"

        config = self._build_config(
            temperature=temperature,
            max_tokens=8192,
            thinking_budget=thinking_budget,
            system_instruction=system_instruction,
            response_mime_type=response_mime_type,
            disable_thinking=disable_thinking,
        )

        # Build multimodal content parts
        parts = []
        for image_bytes in images:
            parts.append(types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"))
        parts.append(types.Part.from_text(text=prompt))

        contents = [types.Content(role="user", parts=parts)]

        response = await self._client.aio.models.generate_content(
            model=resolved_model,
            contents=contents,
            config=config,
        )

        text = response.text.strip() if response.text else ""
        usage = getattr(response, "usage_metadata", None)

        return {
            "text": text,
            "prompt_tokens": getattr(usage, "prompt_token_count", 0) if usage else 0,
            "completion_tokens": getattr(usage, "candidates_token_count", 0) if usage else 0,
        }
