"""
Faster-Whisper STT Engine (GPU only) — placeholder for future implementation.

Requires GPU for optimal performance.
Uses CTranslate2-optimized Whisper models for multilingual transcription.
"""

from typing import AsyncIterator
from engines.base import BaseSTTEngine

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'shared'))
from log_utils.logger import get_logger

logger = get_logger("stt-service")


class FasterWhisperEngine(BaseSTTEngine):
    """Faster-Whisper ASR engine (GPU preferred)."""

    def __init__(self, model_size: str = "large-v3"):
        self._model_size = model_size
        self._model = None

    def load(self):
        """Load Faster-Whisper model."""
        logger.warning("Faster-Whisper engine load() called — GPU recommended. Not loading in v1.")
        # In production:
        # from faster_whisper import WhisperModel
        # self._model = WhisperModel(self._model_size, device="cuda", compute_type="float16")

    async def transcribe(self, audio_data: bytes, language: str,
                         sample_rate: int = 16000) -> dict:
        raise NotImplementedError("Faster-Whisper engine not implemented in v1. Use Google Speech.")

    async def stream_transcribe(self, audio_stream: AsyncIterator[bytes],
                                language: str, sample_rate: int = 16000
                                ) -> AsyncIterator[dict]:
        raise NotImplementedError("Faster-Whisper engine not implemented in v1. Use Google Speech.")
        yield  # Make it a generator
