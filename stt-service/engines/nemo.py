"""
NeMo STT Engine (GPU only) — placeholder for future implementation.

Requires NVIDIA GPU with CUDA support.
Uses NVIDIA NeMo ASR models for Hindi transcription.
"""

from typing import AsyncIterator
from engines.base import BaseSTTEngine

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'shared'))
from log_utils.logger import get_logger

logger = get_logger("stt-service")


class NemoEngine(BaseSTTEngine):
    """NVIDIA NeMo ASR engine (GPU only)."""

    def __init__(self, model_name: str = "ai4b_indicConformer_hi"):
        self._model_name = model_name
        self._model = None

    def load(self):
        """Load NeMo model. Requires GPU."""
        logger.warning("NeMo engine load() called — GPU required. Not loading in v1.")
        # In production:
        # import nemo.collections.asr as nemo_asr
        # self._model = nemo_asr.models.ASRModel.from_pretrained(self._model_name)

    async def transcribe(self, audio_data: bytes, language: str,
                         sample_rate: int = 16000) -> dict:
        raise NotImplementedError("NeMo engine not implemented in v1. Use Google Speech.")

    async def stream_transcribe(self, audio_stream: AsyncIterator[bytes],
                                language: str, sample_rate: int = 16000
                                ) -> AsyncIterator[dict]:
        raise NotImplementedError("NeMo engine not implemented in v1. Use Google Speech.")
        yield  # Make it a generator
