"""
Google Cloud Text-to-Speech Engine.

Uses Google Cloud TTS API with Chirp3, Neural2, and Wavenet voices.
Supports batch synthesis and sentence-level streaming.
Enforces 24kHz output everywhere.
"""

import asyncio
import io
import re
import struct
from typing import AsyncIterator

from google.cloud import texttospeech

from engines.base import BaseTTSEngine

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'shared'))
from log_utils.logger import get_logger, LatencyTracker, get_req_id

logger = get_logger("tts-service")

# Voice configuration per language
DEFAULT_VOICES = {
    "hi": {"language_code": "hi-IN", "name": "hi-IN-Neural2-A"},
    "en": {"language_code": "en-US", "name": "en-US-Neural2-F"},
    "fr": {"language_code": "fr-FR", "name": "fr-FR-Neural2-A"},
    "ta": {"language_code": "ta-IN", "name": "ta-IN-Wavenet-A"},
    "te": {"language_code": "te-IN", "name": "te-IN-Wavenet-A"},
    "ar": {"language_code": "ar-XA", "name": "ar-XA-Wavenet-A"},
    "kn": {"language_code": "kn-IN", "name": "kn-IN-Wavenet-A"},
}

# Sentence splitting regex — splits on Hindi purna viram, question mark,
# exclamation mark, or period followed by space.
SENTENCE_SPLIT_RE = re.compile(r'(?<=[।?!.।])\s+')


def _create_wav_header(data_size: int, sample_rate: int = 24000,
                       channels: int = 1, bits_per_sample: int = 16) -> bytes:
    """Create a WAV file header for raw PCM data."""
    byte_rate = sample_rate * channels * bits_per_sample // 8
    block_align = channels * bits_per_sample // 8
    header = struct.pack(
        '<4sI4s4sIHHIIHH4sI',
        b'RIFF',
        36 + data_size,
        b'WAVE',
        b'fmt ',
        16,                     # Chunk size
        1,                      # PCM format
        channels,
        sample_rate,
        byte_rate,
        block_align,
        bits_per_sample,
        b'data',
        data_size,
    )
    return header


class GoogleTTSEngine(BaseTTSEngine):
    """Google Cloud Text-to-Speech engine."""

    def __init__(self):
        self._client = None

    def load(self):
        """Initialize the Google Cloud TTS client."""
        self._client = texttospeech.TextToSpeechClient(transport="rest")
        logger.info("Google TTS client loaded (REST transport)")

    def _resolve_voice(self, language: str, voice_name: str) -> tuple[str, str]:
        """Resolve language code and voice name."""
        if voice_name:
            # Extract language code from voice name (e.g. "hi-IN-Neural2-A" → "hi-IN")
            parts = voice_name.split("-")
            if len(parts) >= 2:
                lang_code = f"{parts[0]}-{parts[1]}"
                return lang_code, voice_name

        # Fallback to defaults
        defaults = DEFAULT_VOICES.get(language, DEFAULT_VOICES["hi"])
        return defaults["language_code"], defaults["name"]

    def _synthesize_one(self, text: str, language_code: str,
                        voice_name: str, sample_rate: int) -> bytes:
        """Synchronous synthesis of a single text chunk. Returns raw WAV bytes."""
        synthesis_input = texttospeech.SynthesisInput(text=text)
        voice = texttospeech.VoiceSelectionParams(
            language_code=language_code,
            name=voice_name,
        )
        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.LINEAR16,
            sample_rate_hertz=sample_rate,
            speaking_rate=1.06,
        )

        response = self._client.synthesize_speech(
            input=synthesis_input, voice=voice, audio_config=audio_config
        )

        return response.audio_content

    async def synthesize(self, text: str, language: str, voice_name: str,
                         sample_rate: int = 24000) -> dict:
        """Batch synthesize — returns complete WAV audio."""
        if not self._client:
            raise RuntimeError("Client not loaded. Call load() first.")

        if not text or not text.strip():
            return {"audio_data": b"", "sample_rate": sample_rate, "duration_seconds": 0.0}

        req_id = get_req_id()
        lang_code, resolved_voice = self._resolve_voice(language, voice_name)

        with LatencyTracker() as t:
            loop = asyncio.get_event_loop()
            audio_bytes = await loop.run_in_executor(
                None,
                lambda: self._synthesize_one(text, lang_code, resolved_voice, sample_rate)
            )

        # Calculate approximate duration (WAV header = 44 bytes, 16-bit = 2 bytes per sample)
        pcm_size = max(0, len(audio_bytes) - 44)
        duration = pcm_size / (sample_rate * 2) if sample_rate > 0 else 0.0

        logger.info("Synthesize completed",
                     req_id=req_id, language=language,
                     latency_ms=t.elapsed_ms,
                     details={"voice": resolved_voice, "text_len": len(text),
                              "audio_bytes": len(audio_bytes), "duration_s": round(duration, 2)})

        return {
            "audio_data": audio_bytes,
            "sample_rate": sample_rate,
            "duration_seconds": duration,
        }

    async def synthesize_stream(self, text: str, language: str, voice_name: str,
                                sample_rate: int = 24000) -> AsyncIterator[dict]:
        """
        Streaming synthesis — splits text into sentences and synthesizes each.
        Yields AudioFragment-like dicts per sentence.
        """
        if not self._client:
            raise RuntimeError("Client not loaded. Call load() first.")

        if not text or not text.strip():
            yield {
                "audio_data": b"",
                "sample_rate": sample_rate,
                "is_last": True,
                "fragment_index": 0,
                "duration_seconds": 0.0,
            }
            return

        req_id = get_req_id()
        lang_code, resolved_voice = self._resolve_voice(language, voice_name)

        # Split text into sentences
        sentences = SENTENCE_SPLIT_RE.split(text.strip())
        sentences = [s.strip() for s in sentences if s.strip()]

        if not sentences:
            sentences = [text.strip()]

        logger.info("SynthesizeStream started",
                     req_id=req_id, language=language,
                     details={"voice": resolved_voice, "sentences": len(sentences)})

        loop = asyncio.get_event_loop()

        for idx, sentence in enumerate(sentences):
            is_last = (idx == len(sentences) - 1)

            with LatencyTracker() as t:
                audio_bytes = await loop.run_in_executor(
                    None,
                    lambda s=sentence: self._synthesize_one(s, lang_code, resolved_voice, sample_rate)
                )

            pcm_size = max(0, len(audio_bytes) - 44)
            duration = pcm_size / (sample_rate * 2) if sample_rate > 0 else 0.0

            logger.debug(f"Fragment {idx} synthesized",
                          req_id=req_id,
                          latency_ms=t.elapsed_ms,
                          details={"sentence_len": len(sentence), "is_last": is_last})

            yield {
                "audio_data": audio_bytes,
                "sample_rate": sample_rate,
                "is_last": is_last,
                "fragment_index": idx,
                "duration_seconds": duration,
            }
