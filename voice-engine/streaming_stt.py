import asyncio
import time
import traceback
from log_utils.logger import get_logger

logger = get_logger("voice-engine")

class StreamingSTT:
    """
    True bidirectional streaming STT manager.
    Opens a gRPC stream to stt-service and pipes audio chunks live.
    Provides immediate partial transcripts back to the voice engine.
    """

    def __init__(self, stt_stub, language: str, req_id: str, sample_rate: int = 16000):
        self._stt_stub = stt_stub
        self._language = language
        self._req_id = req_id
        self._sample_rate = sample_rate
        
        self._audio_queue = asyncio.Queue()
        self._committed_text = ""
        self._uncommitted_text = ""
        
        self._stream_task = asyncio.create_task(self._run_stream())

    def add_audio(self, chunk: bytes):
        """Add audio chunk to the streaming queue."""
        self._audio_queue.put_nowait(chunk)

    async def _request_generator(self):
        from generated import stt_pb2
        
        # First chunk sends config
        yield stt_pb2.TranscribeRequest(
            language=self._language,
            sample_rate=self._sample_rate,
            engine="google"
        )
        
        while True:
            chunk = await self._audio_queue.get()
            if chunk is None:  # EOF
                yield stt_pb2.TranscribeRequest(is_final=True)
                break
            
            yield stt_pb2.TranscribeRequest(audio_data=chunk)

    async def _run_stream(self):
        try:
            stream = self._stt_stub.StreamTranscribe(
                self._request_generator(),
                metadata=[("x-request-id", self._req_id)]
            )
            
            async for response in stream:
                if response.is_final:
                    self._committed_text += " " + response.text
                    self._uncommitted_text = ""
                else:
                    self._uncommitted_text = response.text
                    
        except Exception as e:
            logger.error(f"Streaming STT stream failed: {e}", req_id=self._req_id, error=traceback.format_exc())

    def get_current_text(self) -> str:
        """Get the current transcribed text (committed + uncommitted)."""
        return (self._committed_text + " " + self._uncommitted_text).strip()

    async def finalize(self) -> str:
        """
        Called at speech_end. Signals EOF to the stream and waits for the final transcript.
        Returns the final full transcript.
        """
        # Send EOF
        self._audio_queue.put_nowait(None)
        
        # Wait for stream task to finish processing the final result
        try:
            await asyncio.wait_for(self._stream_task, timeout=5.0)
        except asyncio.TimeoutError:
            logger.warning("Streaming STT finalize timed out", req_id=self._req_id)
        except asyncio.CancelledError:
            logger.warning("Streaming STT stream was cancelled (empty segment or disconnected)", req_id=self._req_id)
            
        return self.get_current_text()

    def reset(self):
        """Reset for next turn."""
        self._committed_text = ""
        self._uncommitted_text = ""
        # The stream task is one-shot per speech segment.
        # To reuse, a new StreamingSTT instance must be created.
