"""
Kokoro TTS Engine — placeholder for future implementation.

Kokoro is a local neural TTS engine that runs on CPU.
Currently not active in v1.
"""

from typing import AsyncIterator
from engines.base import BaseTTSEngine

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'shared'))
from log_utils.logger import get_logger

logger = get_logger("tts-service")


class KokoroEngine(BaseTTSEngine):
    """Kokoro local TTS engine (CPU)."""

    def __init__(self):
        self._model = None

    def load(self):
        """Load Kokoro model."""
        logger.warning("Kokoro engine load() called — not active in v1.")

    async def synthesize(self, text: str, language: str, voice_name: str,
                         sample_rate: int = 24000) -> dict:
        raise NotImplementedError("Kokoro engine not implemented in v1. Use Google TTS.")

    async def synthesize_stream(self, text: str, language: str, voice_name: str,
                                sample_rate: int = 24000) -> AsyncIterator[dict]:
        raise NotImplementedError("Kokoro engine not implemented in v1. Use Google TTS.")
        yield  # Make it a generator
