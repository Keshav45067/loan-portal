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
TTS Service gRPC Server — entry point.

Implements the TextToSpeech service with batch and streaming synthesis.
v1: Google Cloud TTS only (Chirp3 for Hindi, Neural2 for English).
Enforces 24kHz output everywhere.
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

from generated import tts_pb2, tts_pb2_grpc
from engines.google_tts import GoogleTTSEngine
from config import TTS_SERVICE_PORT, DEFAULT_ENGINE

logger = get_logger("tts-service")


class TextToSpeechServicer(tts_pb2_grpc.TextToSpeechServicer):
    """gRPC servicer implementing the TextToSpeech service."""

    def __init__(self):
        self._engines = {}
        google_engine = GoogleTTSEngine()
        google_engine.load()
        self._engines["google"] = google_engine
        logger.info("TTS engines loaded", details={"engines": list(self._engines.keys())})

    def _get_engine(self, engine_name: str):
        """Get engine by name, defaulting to Google."""
        name = engine_name or DEFAULT_ENGINE
        if name not in self._engines:
            logger.warning(f"Engine '{name}' not available, falling back to google")
            name = "google"
        return self._engines[name]

    async def Synthesize(self, request, context):
        """Batch synthesis (unary)."""
        req_id = extract_req_id(context)
        engine = self._get_engine(request.engine)

        # Enforce 24kHz
        sample_rate = request.output_sample_rate or 24000

        logger.info("Synthesize called",
                     req_id=req_id,
                     language=request.language,
                     method="Synthesize",
                     details={"text_len": len(request.text),
                              "voice": request.voice_name,
                              "engine": request.engine or DEFAULT_ENGINE})
        try:
            result = await engine.synthesize(
                text=request.text,
                language=request.language,
                voice_name=request.voice_name,
                sample_rate=sample_rate,
            )

            return tts_pb2.SynthesizeResponse(
                audio_data=result["audio_data"],
                sample_rate=result["sample_rate"],
                duration_seconds=result["duration_seconds"],
            )

        except Exception as e:
            logger.error(f"Synthesize failed: {e}",
                         req_id=req_id, error=traceback.format_exc())
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return tts_pb2.SynthesizeResponse()

    async def SynthesizeStream(self, request, context):
        """Server-side streaming synthesis — yields audio per sentence."""
        req_id = extract_req_id(context)
        engine = self._get_engine(request.engine)

        sample_rate = request.output_sample_rate or 24000

        logger.info("SynthesizeStream called",
                     req_id=req_id,
                     language=request.language,
                     method="SynthesizeStream",
                     details={"text_len": len(request.text),
                              "voice": request.voice_name})
        try:
            async for fragment in engine.synthesize_stream(
                text=request.text,
                language=request.language,
                voice_name=request.voice_name,
                sample_rate=sample_rate,
            ):
                yield tts_pb2.AudioFragment(
                    audio_data=fragment["audio_data"],
                    sample_rate=fragment["sample_rate"],
                    is_last=fragment["is_last"],
                    fragment_index=fragment["fragment_index"],
                    duration_seconds=fragment["duration_seconds"],
                )

            logger.info("SynthesizeStream completed", req_id=req_id)

        except Exception as e:
            logger.error(f"SynthesizeStream failed: {e}",
                         req_id=req_id, error=traceback.format_exc())
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))


async def serve():
    """Start the TTS gRPC server."""
    server = grpc_aio.server(
        options=[
            ("grpc.max_send_message_length", 50 * 1024 * 1024),
            ("grpc.max_receive_message_length", 50 * 1024 * 1024),
        ]
    )

    servicer = TextToSpeechServicer()
    tts_pb2_grpc.add_TextToSpeechServicer_to_server(servicer, server)

    listen_addr = f"[::]:{TTS_SERVICE_PORT}"
    server.add_insecure_port(listen_addr)

    logger.info(f"TTS Service starting on {listen_addr}",
                details={"port": TTS_SERVICE_PORT, "default_engine": DEFAULT_ENGINE,
                          "sample_rate": 24000})

    await server.start()
    logger.info("TTS Service ready ✅")

    async def shutdown(sig):
        logger.info(f"Received {sig.name}, shutting down...")
        await server.stop(grace=5)

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda s=sig: asyncio.create_task(shutdown(s)))

    await server.wait_for_termination()


if __name__ == "__main__":
    asyncio.run(serve())
