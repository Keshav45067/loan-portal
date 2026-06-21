"""
Abstract base class for LLM engines.
All engines must implement this interface.
"""
from abc import ABC, abstractmethod
from typing import AsyncIterator, Optional


class BaseLLMEngine(ABC):
    """Base interface for all LLM engines (Gemini, OpenAI, etc.)."""

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        model: str,
        temperature: float = 1.0,
        max_tokens: int = 8192,
        thinking_budget: int = 0,
        system_instruction: str = "",
    ) -> dict:
        """
        Generate text from a prompt.

        Returns:
            dict with keys: text, prompt_tokens, completion_tokens
        """
        pass

    @abstractmethod
    async def generate_stream(
        self,
        prompt: str,
        model: str,
        temperature: float = 1.0,
        max_tokens: int = 8192,
        thinking_budget: int = 0,
        system_instruction: str = "",
    ) -> AsyncIterator[str]:
        """
        Stream text generation chunk by chunk.

        Yields:
            str chunks of generated text
        """
        pass

    @abstractmethod
    async def extract_json(
        self,
        prompt: str,
        model: str,
        temperature: float = 0.2,
        system_instruction: str = "",
        thinking_budget: int = 0,
    ) -> dict:
        """
        Generate structured JSON output.

        Returns:
            dict with keys: json_text (raw string), success, error
        """
        pass

    @abstractmethod
    async def generate_multimodal(
        self,
        prompt: str,
        images: list[bytes],
        model: str,
        temperature: float = 1.0,
        system_instruction: str = "",
        thinking_budget: int = 0,
    ) -> dict:
        """
        Generate text from prompt + images.

        Returns:
            dict with keys: text, prompt_tokens, completion_tokens
        """
        pass
