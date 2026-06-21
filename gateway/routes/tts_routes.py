"""
TTS Routes — REST endpoint for text-to-speech synthesis.

Proxies to the TTS gRPC service. Returns WAV audio bytes.
"""

import sys
import os
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

import grpc

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'shared'))
from log_utils.logger import get_logger, generate_req_id, set_req_id

logger = get_logger("gateway")

router = APIRouter(prefix="/api/tts", tags=["TTS"])


class SynthesizeRequest(BaseModel):
    text: str
    languageCode: str = "hi-IN"   # "hi-IN", "en-US", etc.
    voice_name: str = ""
    engine: str = ""


@router.post("/synthesize")
async def synthesize(body: SynthesizeRequest, request: Request):
    """Synthesize text to speech audio (WAV).

    Returns audio/wav binary directly for playback in the browser.
    """
    req_id = getattr(request.state, "req_id", generate_req_id())
    set_req_id(req_id)

    if not body.text or not body.text.strip():
        raise HTTPException(status_code=400, detail="text is required")

    # Map languageCode (e.g. "hi-IN") to short code (e.g. "hi")
    language = body.languageCode.split("-")[0] if body.languageCode else "hi"

    try:
        from grpc_clients.generated import tts_pb2

        stub = request.app.state.tts_stub

        tts_req = tts_pb2.SynthesizeRequest(
            text=body.text,
            language=language,
            voice_name=body.voice_name,
            engine=body.engine,
            output_sample_rate=24000,
        )

        resp = await stub.Synthesize(
            tts_req,
            metadata=[("x-request-id", req_id)],
        )

        if not resp.audio_data:
            raise HTTPException(status_code=500, detail="TTS returned empty audio")

        logger.info("TTS synthesize OK",
                     req_id=req_id,
                     language=language,
                     details={"text_len": len(body.text),
                              "audio_bytes": len(resp.audio_data),
                              "duration_s": round(resp.duration_seconds, 2)})

        return Response(
            content=resp.audio_data,
            media_type="audio/wav",
            headers={
                "Content-Disposition": "inline",
                "Cache-Control": "no-cache",
            },
        )

    except grpc.aio.AioRpcError as e:
        logger.error(f"TTS gRPC error: {e.code()} {e.details()}", req_id=req_id)
        raise HTTPException(status_code=502, detail=f"TTS service error: {e.details()}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"TTS synthesize failed: {e}", req_id=req_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))
