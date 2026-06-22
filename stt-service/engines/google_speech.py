"""
Google Cloud Speech-to-Text Engine.

Uses the Google Cloud Speech V1 API for both batch and streaming recognition.
This is the v1 default engine for all languages.
"""

import asyncio
import queue
import threading
from typing import AsyncIterator

from google.cloud import speech_v1 as speech
from google.api_core import exceptions as gcp_exceptions

from engines.base import BaseSTTEngine

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'shared'))
from log_utils.logger import get_logger, LatencyTracker, get_req_id

logger = get_logger("stt-service")

# Language code mapping
LANGUAGE_MAP = {
    "hi": "hi-IN",
    "en": "en-IN",
    "ar": "ar-SA",
    "kn": "kn-IN",
}


class GoogleSpeechEngine(BaseSTTEngine):
    """Google Cloud Speech-to-Text engine."""

    def __init__(self):
        self._client = None

    def load(self):
        """Initialize the Google Speech client."""
        self._client = speech.SpeechClient()
        logger.info("Google Speech client loaded")

    def _get_language_code(self, language: str) -> str:
        """Resolve short language code to BCP-47."""
        return LANGUAGE_MAP.get(language, language)

    async def transcribe(self, audio_data: bytes, language: str,
                         sample_rate: int = 16000) -> dict:
        """Batch transcribe audio using Google Speech V1."""
        if not self._client:
            raise RuntimeError("Client not loaded. Call load() first.")

        req_id = get_req_id()
        lang_code = self._get_language_code(language)

        recognition_config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=sample_rate,
            language_code=lang_code,
            enable_automatic_punctuation=True,
            model="latest_short",
        )

        audio = speech.RecognitionAudio(content=audio_data)

        with LatencyTracker() as t:
            # Run synchronous API call in thread pool
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self._client.recognize(config=recognition_config, audio=audio)
            )

        text = ""
        confidence = 0.0
        if response.results:
            top_result = response.results[0]
            if top_result.alternatives:
                text = top_result.alternatives[0].transcript
                confidence = top_result.alternatives[0].confidence

        logger.info("Batch transcription completed",
                     req_id=req_id, language=lang_code,
                     latency_ms=t.elapsed_ms,
                     details={"text_length": len(text), "confidence": confidence})

        return {
            "text": text,
            "confidence": confidence,
            "language_detected": lang_code,
        }

    async def stream_transcribe(self, audio_stream: AsyncIterator[bytes],
                                language: str, sample_rate: int = 16000
                                ) -> AsyncIterator[dict]:
        """
        Streaming transcription using Google Speech streaming_recognize.

        This wraps the synchronous streaming API in an async-friendly way.
        """
        if not self._client:
            raise RuntimeError("Client not loaded. Call load() first.")

        req_id = get_req_id()
        lang_code = self._get_language_code(language)

        streaming_config = speech.StreamingRecognitionConfig(
            config=speech.RecognitionConfig(
                encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
                sample_rate_hertz=sample_rate,
                language_code=lang_code,
                enable_automatic_punctuation=True,
                model="latest_short",
            ),
            interim_results=True,
        )

        logger.info("Streaming transcription started",
                     req_id=req_id, language=lang_code)

        in_queue = queue.Queue()
        out_queue = asyncio.Queue()
        loop = asyncio.get_event_loop()

        def _sync_stream():
            """Synchronous streaming request generator."""
            while True:
                chunk = in_queue.get()
                if chunk is None:
                    break
                yield speech.StreamingRecognizeRequest(audio_content=chunk)

        def _worker_thread():
            try:
                responses = self._client.streaming_recognize(config=streaming_config, requests=_sync_stream())
                segment_index = 0
                for response in responses:
                    for result in response.results:
                        if result.alternatives:
                            alt = result.alternatives[0]
                            data = {
                                "text": alt.transcript,
                                "is_final": result.is_final,
                                "result_index": segment_index,
                                "confidence": alt.confidence if result.is_final else 0.0,
                                "language_detected": lang_code,
                            }
                            loop.call_soon_threadsafe(out_queue.put_nowait, data)
                            if result.is_final:
                                segment_index += 1
            except gcp_exceptions.OutOfRange:
                logger.warning("Streaming exceeded time limit", req_id=req_id)
            except Exception as e:
                logger.error(f"Streaming transcription error: {e}", req_id=req_id, error=str(e))
                loop.call_soon_threadsafe(out_queue.put_nowait, e)
            finally:
                loop.call_soon_threadsafe(out_queue.put_nowait, None)

        thread = threading.Thread(target=_worker_thread)
        thread.start()

        async def _feed_input():
            try:
                async for chunk in audio_stream:
                    if chunk:
                        in_queue.put(chunk)
            except Exception as e:
                logger.error(f"Error reading audio stream: {e}", req_id=req_id)
            finally:
                in_queue.put(None)

        feed_task = asyncio.create_task(_feed_input())

        try:
            while True:
                result = await out_queue.get()
                if result is None:
                    break
                if isinstance(result, Exception):
                    raise result
                yield result
        finally:
            feed_task.cancel()
            in_queue.put(None)
