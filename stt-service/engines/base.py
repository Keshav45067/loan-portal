"""
Abstract base class for STT engines.
"""
from abc import ABC, abstractmethod
from typing import AsyncIterator


class BaseSTTEngine(ABC):
    """Base interface for all STT engines."""

    @abstractmethod
    async def transcribe(self, audio_data: bytes, language: str,
                         sample_rate: int = 16000) -> dict:
        """
        Batch transcribe audio.
        Returns: dict with keys: text, confidence, language_detected
        """
        pass

    @abstractmethod
    async def stream_transcribe(self, audio_stream: AsyncIterator[bytes],
                                language: str, sample_rate: int = 16000
                                ) -> AsyncIterator[dict]:
        """
        Streaming transcription.
        Yields: dict with keys: text, is_final, confidence
        """
        pass
