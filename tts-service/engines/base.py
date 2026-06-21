"""Abstract base class for TTS engines."""
from abc import ABC, abstractmethod
from typing import AsyncIterator


class BaseTTSEngine(ABC):
    """Base interface for all TTS engines."""

    @abstractmethod
    async def synthesize(self, text: str, language: str, voice_name: str,
                         sample_rate: int = 24000) -> dict:
        """
        Batch synthesize text to audio.
        Returns: dict with keys: audio_data (bytes), sample_rate, duration_seconds
        """
        pass

    @abstractmethod
    async def synthesize_stream(self, text: str, language: str, voice_name: str,
                                sample_rate: int = 24000) -> AsyncIterator[dict]:
        """
        Streaming synthesis — split text into sentences, yield audio per sentence.
        Yields: dict with keys: audio_data (bytes), sample_rate, is_last, fragment_index, duration_seconds
        """
        pass
