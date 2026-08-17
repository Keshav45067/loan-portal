# Force IPv4 resolution to bypass macOS IPv6 network blackhole for external APIs
import socket
_original_getaddrinfo = socket.getaddrinfo
def _ipv4_only_getaddrinfo(*args, **kwargs):
    try:
        res = _original_getaddrinfo(*args, **kwargs)
        filtered = [r for r in res if r[0] == socket.AF_INET]
        return filtered if filtered else res
    except Exception:
        return _original_getaddrinfo(*args, **kwargs)
socket.getaddrinfo = _ipv4_only_getaddrinfo

"""
STT Service gRPC Server — entry point.

Implements the SpeechToText service with batch and streaming transcription.
v1: Google Speech API only. NeMo and Faster-Whisper stubs are written but not active.
"""

import asyncio
import signal
import sys
import os
import traceback
import grpc
from grpc import aio as grpc_aio

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'shared'))
from log_utils.logger import get_logger, extract_req_id, LatencyTracker

sys.path.insert(0, os.path.dirname(__file__))

from generated import stt_pb2, stt_pb2_grpc
from engines.google_speech import GoogleSpeechEngine
from engines.rnnoise_denoiser import RNNoiseStreamDenoiser
from config import STT_SERVICE_PORT, DEFAULT_ENGINE

logger = get_logger("stt-service")


class SpeechToTextServicer(stt_pb2_grpc.SpeechToTextServicer):
    """gRPC servicer implementing the SpeechToText service."""

    def __init__(self):
        self._engines = {}
        # Load Google Speech engine (v1 default)
        google_engine = GoogleSpeechEngine()
        google_engine.load()
        self._engines["google"] = google_engine
        logger.info("STT engines loaded with RNNoise noise suppression active", details={"engines": list(self._engines.keys())})

    def _get_engine(self, engine_name: str):
        """Get engine by name, defaulting to Google."""
        name = engine_name or DEFAULT_ENGINE
        if name not in self._engines:
            logger.warning(f"Engine '{name}' not available, falling back to google")
            name = "google"
        return self._engines[name]

    async def Transcribe(self, request, context):
        """Batch transcription (unary) with RNNoise noise suppression."""
        req_id = extract_req_id(context)
        engine = self._get_engine(request.engine)
        sample_rate = request.sample_rate or 16000

        logger.info("Transcribe called",
                     req_id=req_id,
                     language=request.language,
                     engine=request.engine or DEFAULT_ENGINE,
                     method="Transcribe",
                     details={"audio_bytes": len(request.audio_data)})

        try:
            with LatencyTracker() as t:
                # 1. Apply RNNoise Denoising
                denoised_audio = RNNoiseStreamDenoiser.denoise_bytes(
                    request.audio_data, sample_rate=sample_rate
                )
                # 2. Transcribe clean audio
                result = await engine.transcribe(
                    audio_data=denoised_audio,
                    language=request.language,
                    sample_rate=sample_rate,
                )

            logger.info("Transcribe completed",
                         req_id=req_id, latency_ms=t.elapsed_ms,
                         details={"text": result["text"][:100]})

            return stt_pb2.TranscribeResponse(
                text=result["text"],
                confidence=result.get("confidence", 0.0),
                language_detected=result.get("language_detected", ""),
            )

        except Exception as e:
            logger.error(f"Transcribe failed: {e}",
                         req_id=req_id, error=traceback.format_exc())
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return stt_pb2.TranscribeResponse()

    async def StreamTranscribe(self, request_iterator, context):
        """Bidirectional streaming transcription with real-time RNNoise streaming suppression."""
        req_id = extract_req_id(context)

        logger.info("StreamTranscribe started", req_id=req_id, method="StreamTranscribe")

        try:
            first_request = await request_iterator.__anext__()
        except StopAsyncIteration:
            logger.warning("StreamTranscribe received empty stream", req_id=req_id)
            yield stt_pb2.TranscriptChunk(text="", is_final=True, confidence=0.0)
            return

        engine_name = first_request.engine or DEFAULT_ENGINE
        language = first_request.language or "hi"
        sample_rate = first_request.sample_rate or 16000
        engine = self._get_engine(engine_name)

        logger.info("StreamTranscribe processing with RNNoise streaming",
                     req_id=req_id, engine=engine_name, language=language)

        async def audio_stream_generator():
            denoiser = RNNoiseStreamDenoiser(sample_rate=sample_rate)
            try:
                if getattr(first_request, 'audio_data', None):
                    clean_chunk = denoiser.process_chunk(first_request.audio_data)
                    if clean_chunk:
                        yield clean_chunk
                if getattr(first_request, 'is_final', False):
                    clean_flush = denoiser.flush()
                    if clean_flush:
                        yield clean_flush
                    return
                
                async for request in request_iterator:
                    if getattr(request, 'audio_data', None):
                        clean_chunk = denoiser.process_chunk(request.audio_data)
                        if clean_chunk:
                            yield clean_chunk
                    if getattr(request, 'is_final', False):
                        break

                clean_flush = denoiser.flush()
                if clean_flush:
                    yield clean_flush
            finally:
                denoiser.destroy()

        try:
            async for result in engine.stream_transcribe(
                audio_stream=audio_stream_generator(),
                language=language,
                sample_rate=sample_rate,
            ):
                yield stt_pb2.TranscriptChunk(
                    text=result["text"],
                    is_final=result.get("is_final", False),
                    confidence=result.get("confidence", 0.0),
                    language_detected=result.get("language_detected", ""),
                    result_index=result.get("result_index", 0),
                )

        except Exception as e:
            logger.error(f"StreamTranscribe failed: {e}",
                         req_id=req_id, error=traceback.format_exc())
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))


async def serve():
    """Start the STT gRPC server."""
    server = grpc_aio.server(
        options=[
            ("grpc.max_send_message_length", 50 * 1024 * 1024),
            ("grpc.max_receive_message_length", 50 * 1024 * 1024),
        ]
    )

    servicer = SpeechToTextServicer()
    stt_pb2_grpc.add_SpeechToTextServicer_to_server(servicer, server)

    listen_addr = f"[::]:{STT_SERVICE_PORT}"
    server.add_insecure_port(listen_addr)

    logger.info(f"STT Service starting on {listen_addr}",
                details={"port": STT_SERVICE_PORT, "default_engine": DEFAULT_ENGINE})

    await server.start()
    logger.info("STT Service ready ✅")

    async def shutdown(sig):
        logger.info(f"Received {sig.name}, shutting down...")
        await server.stop(grace=5)

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda s=sig: asyncio.create_task(shutdown(s)))

    await server.wait_for_termination()


if __name__ == "__main__":
    asyncio.run(serve())
