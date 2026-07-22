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
Voice Conversation Engine gRPC Server.

Implements bidirectional streaming for real-time voice interviews.
The API Gateway bridges WebSocket ↔ this gRPC stream.

Each client connection creates a VoiceSession that walks the interview graph
via the 2-call pipeline: STT → LLM (extract + route) → TTS → audio back.
"""

import asyncio
import signal
import sys
import os
import json
import traceback
import time
from typing import Dict

import grpc
from grpc import aio as grpc_aio

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'shared'))
from log_utils.logger import get_logger, extract_req_id, set_req_id, generate_req_id, LatencyTracker

sys.path.insert(0, os.path.dirname(__file__))

from generated import voice_engine_pb2 as pb2
from generated import voice_engine_pb2_grpc as pb2_grpc
from session import VoiceSession, RawAgentSession
from streaming_stt import StreamingSTT
from config import (
    VOICE_ENGINE_PORT, STT_SERVICE_ADDR, TTS_SERVICE_ADDR,
    LLM_SERVICE_ADDR, CONFIG_REGISTRY_ADDR, APP_ORCHESTRATOR_ADDR,
)

USE_STREAMING_STT = True

logger = get_logger("voice-engine")


class SessionStore:
    """Thread-safe in-memory session store."""

    def __init__(self):
        self._sessions: Dict[str, VoiceSession] = {}
        self._lock = asyncio.Lock()

    async def create(self, session_id: str, session: VoiceSession):
        async with self._lock:
            self._sessions[session_id] = session

    async def get(self, session_id: str) -> VoiceSession:
        return self._sessions.get(session_id)

    async def remove(self, session_id: str):
        async with self._lock:
            self._sessions.pop(session_id, None)

    async def count(self) -> int:
        return len(self._sessions)


class VoiceConversationServicer(pb2_grpc.VoiceConversationServicer):
    """gRPC servicer implementing the VoiceConversation service."""

    def __init__(self, session_store: SessionStore):
        self._store = session_store
        # gRPC stubs will be initialized on server startup
        self._stt_stub = None
        self._tts_stub = None
        self._llm_stub = None
        self._config_stub = None
        self._orchestrator_stub = None

    async def Session(self, request_iterator, context):
        """
        Bidirectional streaming RPC — one per voice interview session.

        Protocol:
        1. First message = SessionStart (scheme_id, session_id, language, name)
        2. Subsequent messages = audio chunks or control signals
        3. Server responds with status updates, transcriptions, audio, progress

        This is the core real-time voice pipeline.
        """
        req_id = extract_req_id(context)
        session: VoiceSession = None
        session_id = ""
        progressive_stt = None
        progressive_task = None

        input_queue = asyncio.Queue()

        async def _read_incoming_requests():
            try:
                async for req in request_iterator:
                    await input_queue.put(req)
            except Exception as read_err:
                await input_queue.put(read_err)
            finally:
                await input_queue.put(None)

        reader_task = asyncio.create_task(_read_incoming_requests())

        nudge_count_map = {}  # {node_id: int}
        inactivity_timer_task = None
        timer_deadline = None  # Live timestamp when current nudge window expires

        def cancel_timer_task_only():
            nonlocal inactivity_timer_task
            if inactivity_timer_task and not inactivity_timer_task.done():
                inactivity_timer_task.cancel()
            inactivity_timer_task = None

        def clear_inactivity_timer():
            nonlocal timer_deadline
            cancel_timer_task_only()
            timer_deadline = None

        def arm_inactivity_timer(current_node_id, fresh=True):
            nonlocal inactivity_timer_task, timer_deadline
            import time as _time
            cancel_timer_task_only()
            if not session or not session.walker or session.walker.is_completed:
                return
            
            # Policy is ONLY enabled for nodes of type 'voice-qa'
            policy = session.walker.get_inactivity_policy(current_node_id)
            if not policy.get("enabled"):
                return
            
            nudge_count = nudge_count_map.get(current_node_id, 0)
            max_nudges = policy.get("max_nudges", 2)
            if nudge_count >= max_nudges:
                return

            now = _time.time()
            if fresh or timer_deadline is None:
                base_timeout = policy.get("timeout_seconds", 3.0)
                decay = policy.get("decay_multiplier", 1.4)
                delay = base_timeout * (decay ** nudge_count)
                timer_deadline = now + delay
            else:
                delay = max(0.3, timer_deadline - now)

            async def _timer_worker(target_id, timeout_sec):
                try:
                    await asyncio.sleep(timeout_sec)
                    await input_queue.put({"type": "inactivity_timeout", "node_id": target_id})
                except asyncio.CancelledError:
                    pass

            logger.info(f"Armed inactivity timer for node '{current_node_id}' ({delay:.1f}s remaining, nudge #{nudge_count + 1})")
            inactivity_timer_task = asyncio.create_task(_timer_worker(current_node_id, delay))

        try:
            while True:
                item = await input_queue.get()
                if item is None:
                    break
                if isinstance(item, Exception):
                    raise item

                # ─── Inactivity Timeout Event ───
                if isinstance(item, dict) and item.get("type") == "inactivity_timeout":
                    target_node_id = item.get("node_id")
                    if not session or not session.walker or session.walker.is_completed:
                        continue
                    if session.walker.current_node_id != target_node_id:
                        continue
                    
                    policy = session.walker.get_inactivity_policy(target_node_id)
                    if not policy.get("enabled"):
                        continue

                    nudge_count = nudge_count_map.get(target_node_id, 0) + 1
                    nudge_count_map[target_node_id] = nudge_count

                    current_node = session.walker.current_node or {}
                    question_text = current_node.get("text_template", "")
                    nudge_guideline = policy.get("nudge_guideline", "")

                    logger.info(f"Inactivity timeout fired for node '{target_node_id}' (attempt {nudge_count}/{policy.get('max_nudges', 2)})", session_id=session_id)

                    from nudge_generator import generate_nudge
                    nudge_text = await generate_nudge(
                        llm_stub=self._llm_stub,
                        question_text=question_text,
                        nudge_guideline=nudge_guideline,
                        language=session.language,
                        nudge_count=nudge_count,
                        req_id=req_id
                    )

                    yield pb2.VoiceOutput(status=pb2.StatusUpdate(status="speaking"))
                    from session import split_sentences
                    sentences, remainder = split_sentences(nudge_text)
                    if remainder.strip():
                        sentences.append(remainder.strip())
                    for sentence in sentences:
                        clean = sentence.replace("|", "").strip()
                        if clean:
                            yield pb2.VoiceOutput(
                                transcription=pb2.TranscriptionUpdate(text=clean, is_final=False)
                            )
                            async for audio_chunk in session._synthesize_text(clean):
                                yield pb2.VoiceOutput(
                                    audio=pb2.AudioData(wav_data=audio_chunk, sample_rate=24000)
                                )
                    yield pb2.VoiceOutput(audio_end=True)
                    yield pb2.VoiceOutput(status=pb2.StatusUpdate(status="listening"))

                    arm_inactivity_timer(target_node_id)
                    continue

                # ─── VoiceInput Message ───
                voice_input = item
                input_type = voice_input.WhichOneof("input")

                if input_type in ("audio_chunk", "text_input", "control"):
                    cancel_timer_task_only()

                # ─── Session Start ───
                if input_type == "session_start":
                    start = voice_input.session_start
                    session_id = start.session_id
                    set_req_id(req_id)

                    logger.info("Session starting",
                                 req_id=req_id,
                                 session_id=session_id,
                                 scheme_id=start.scheme_id,
                                 language=start.language)

                    # Create session
                    session = VoiceSession(
                        session_id=session_id,
                        scheme_id=start.scheme_id,
                        language=start.language,
                        applicant_name=start.applicant_name,
                        application_id=start.application_id,
                        req_id=req_id,
                        stt_stub=self._stt_stub,
                        tts_stub=self._tts_stub,
                        llm_stub=self._llm_stub,
                        config_stub=self._config_stub,
                        orchestrator_stub=self._orchestrator_stub,
                    )

                    await session.init()
                    await self._store.create(session_id, session)

                    # Send connected status
                    yield pb2.VoiceOutput(
                        status=pb2.StatusUpdate(status="connected")
                    )

                    # Start interview — speak first question
                    first_node = await session.start()
                    yield pb2.VoiceOutput(
                        progress=pb2.ProgressUpdate(
                            current_step=session.walker.step_number,
                            total_steps=session.walker.total_steps,
                            current_node_id=first_node["node_id"],
                        )
                    )
                    if first_node.get("type") == "capture":
                        yield pb2.VoiceOutput(
                            node_change=pb2.NodeChange(
                                node_type="capture",
                                document_id=first_node.get("document_id", "")
                            )
                        )
                    else:
                        # Synthesize and stream first question audio via TTS (sentence-chunked)
                        yield pb2.VoiceOutput(
                            status=pb2.StatusUpdate(status="speaking")
                        )
                        from session import split_sentences, SENTENCE_PUNCS
                        sentences, remainder = split_sentences(first_node["text"])
                        if remainder.strip():
                            sentences.append(remainder.strip())
                        for sentence in sentences:
                            clean = sentence.replace("|", "").strip()
                            if clean:
                                # Send per-sentence text before its audio
                                yield pb2.VoiceOutput(
                                    transcription=pb2.TranscriptionUpdate(
                                        text=clean, is_final=False
                                    )
                                )
                                async for audio_chunk in session._synthesize_text(clean):
                                    yield pb2.VoiceOutput(
                                        audio=pb2.AudioData(wav_data=audio_chunk, sample_rate=24000)
                                    )
                        yield pb2.VoiceOutput(audio_end=True)

                        yield pb2.VoiceOutput(
                            status=pb2.StatusUpdate(status="listening")
                        )

                # ─── Audio Chunk ───
                elif input_type == "audio_chunk":
                    if not session:
                        logger.warning("Audio received before session start",
                                        req_id=req_id)
                        continue

                    audio_bytes = voice_input.audio_chunk
                    session.add_audio_chunk(audio_bytes)

                    # Feed audio to progressive STT if active
                    if progressive_stt is not None:
                        progressive_stt.add_audio(audio_bytes)
                        if not USE_STREAMING_STT:
                            # Trigger progressive inference (fire-and-forget background task)
                            if progressive_task is None or progressive_task.done():
                                progressive_task = asyncio.create_task(
                                    progressive_stt.process_progressive()
                                )

                # ─── Direct Text Input ───
                elif input_type == "text_input":
                    if not session:
                        logger.warning("Text input received before session start", req_id=req_id)
                        continue

                    text_val = voice_input.text_input
                    logger.info(f"Direct text input received: '{text_val}'", session_id=session_id)

                    import time as _time
                    t_turn_start = _time.perf_counter()

                    clear_inactivity_timer()

                    yield pb2.VoiceOutput(
                        status=pb2.StatusUpdate(status="processing")
                    )

                    # Send transcription/input text back to client so UI displays it
                    yield pb2.VoiceOutput(
                        transcription=pb2.TranscriptionUpdate(
                            text=text_val,
                            is_final=True
                        )
                    )

                    # Process the turn with streaming pipeline
                    first_audio_yielded = False
                    async for output in session.process_turn_streaming(text_val):
                        if not first_audio_yielded and output.HasField("audio"):
                            first_audio_ms = (_time.perf_counter() - t_turn_start) * 1000
                            logger.info(f"⏱ FIRST AUDIO from text_input: {first_audio_ms:.0f}ms",
                                         session_id=session_id, req_id=req_id)
                            first_audio_yielded = True
                        yield output

                    # Clear the session's audio buffer
                    session.clear_audio_buffer()

                    total_turn_ms = (_time.perf_counter() - t_turn_start) * 1000
                    logger.info(f"⏱ TOTAL TURN (from text_input): {total_turn_ms:.0f}ms",
                                 session_id=session_id, req_id=req_id)

                # ─── Control Signal ───
                elif input_type == "control":
                    signal_type = voice_input.control.signal

                    if not session:
                        continue

                    logger.info(f"Control signal: {signal_type}",
                                 req_id=req_id, session_id=session_id)

                    if signal_type == "speech_start":
                        cancel_timer_task_only()
                        # ─── Guard: Ignore speech if session is completed ───
                        if session and session.walker and session.walker.is_completed:
                            logger.info("Ignoring speech_start because session is completed", session_id=session_id)
                            continue
                        # ─── Guard: Ignore speech on capture nodes ───
                        if session and session._walker.current_node and session._walker.current_node.get("type") in ("capture", "video_capture"):
                            logger.info("Ignoring speech_start on capture node", session_id=session_id)
                            continue
                        # ─── Preserve pre-speech padding (~300ms = 9600 bytes) & clear older noise ───
                        existing_audio = session.get_audio_buffer()
                        pre_roll_bytes = min(len(existing_audio), 16000)  # max ~500ms safety buffer
                        pre_roll_audio = existing_audio[-pre_roll_bytes:] if pre_roll_bytes > 0 else b""
                        session.clear_audio_buffer()
                        if pre_roll_audio:
                            session.add_audio_chunk(pre_roll_audio)

                        if USE_STREAMING_STT:
                            if progressive_stt is not None:
                                logger.warning("Received duplicate speech_start. Ignoring.", session_id=session_id)
                                continue
                            progressive_stt = StreamingSTT(
                                stt_stub=self._stt_stub,
                                language=session.language,
                                req_id=session.req_id,
                                sample_rate=16000,
                            )
                        else:
                            # Create a fresh ProgressiveSTT for this speech segment
                            from session import ProgressiveSTT
                            if progressive_stt is not None:
                                logger.warning("Received duplicate speech_start. Ignoring.", session_id=session_id)
                                continue
                            progressive_stt = ProgressiveSTT(
                                stt_stub=self._stt_stub,
                                language=session.language,
                                req_id=session.req_id,
                                sample_rate=16000,
                                window_duration=3.0,
                                step_duration=1.0,
                            )
                            if pre_roll_audio:
                                progressive_stt.add_audio(pre_roll_audio)
                        progressive_task = None
                        yield pb2.VoiceOutput(
                            status=pb2.StatusUpdate(status="listening")
                        )

                    elif signal_type == "capture_complete":
                        logger.info("Capture complete, advancing graph", session_id=session_id)
                        import time as _time
                        t_turn_start = _time.perf_counter()
                        
                        first_audio_yielded = False
                        async for output in session.process_turn_streaming("", is_capture_complete=True):
                            if not first_audio_yielded and output.HasField("audio"):
                                first_audio_yielded = True
                            yield output

                    elif signal_type == "capture_processing":
                        logger.info("Capture processing started, playing audio feedback", session_id=session_id)
                        yield pb2.VoiceOutput(
                            status=pb2.StatusUpdate(status="speaking")
                        )
                        async for output in session.process_capture_processing():
                            yield output

                    elif signal_type.startswith("capture_success"):
                        parts = signal_type.split(":", 1)
                        doc_id = parts[1] if len(parts) > 1 else ""
                        logger.info(f"Capture success for {doc_id}, playing audio feedback", session_id=session_id)
                        
                        yield pb2.VoiceOutput(
                            status=pb2.StatusUpdate(status="speaking")
                        )
                        async for output in session.process_capture_success(doc_id):
                            yield output

                    elif signal_type.startswith("capture_error"):
                        parts = signal_type.split(":", 1)
                        err_msg = parts[1] if len(parts) > 1 else ""
                        logger.info(f"Capture error: {err_msg}, playing error audio feedback", session_id=session_id)
                        
                        yield pb2.VoiceOutput(
                            status=pb2.StatusUpdate(status="speaking")
                        )
                        async for output in session.process_capture_error(err_msg):
                            yield output

                    elif signal_type.startswith("capture_speak:"):
                        parts = signal_type.split(":", 1)
                        text = parts[1] if len(parts) > 1 else ""
                        logger.info(f"Capture speak text, playing audio feedback", session_id=session_id)
                        
                        yield pb2.VoiceOutput(
                            status=pb2.StatusUpdate(status="speaking")
                        )
                        async for output in session.process_capture_speak(text):
                            yield output

                    elif signal_type == "playback_complete":
                        logger.info("Playback complete received from client; arming inactivity timer", session_id=session_id)
                        if session and session.walker:
                            arm_inactivity_timer(session.walker.current_node_id, fresh=True)

                    elif signal_type == "speech_end":
                        # User stopped speaking — run the streaming 2-call pipeline
                        import time as _time
                        t_turn_start = _time.perf_counter()

                        # ─── Guard: Discard speech on capture nodes ───
                        if session and session._walker.current_node and session._walker.current_node.get("type") in ("capture", "video_capture"):
                            logger.info("Discarding speech_end on capture node — voice not applicable",
                                         session_id=session_id)
                            if progressive_stt is not None:
                                progressive_stt.reset()
                                progressive_stt = None
                                progressive_task = None
                            session.clear_audio_buffer()
                            if session and session.walker:
                                arm_inactivity_timer(session.walker.current_node_id, fresh=False)
                            continue

                        # ─── Guard: Discard short audio (e.g. noise or coughs) ───
                        audio_data = session.get_audio_buffer()
                        if not audio_data or len(audio_data) < 2560: # < 80ms of audio (16khz 16-bit)
                            logger.info("Discarding speech_end because audio buffer is too short (<80ms)", session_id=session_id)
                            if progressive_stt is not None:
                                progressive_stt.reset()
                                progressive_stt = None
                                progressive_task = None
                            session.clear_audio_buffer()
                            if session and session.walker:
                                arm_inactivity_timer(session.walker.current_node_id, fresh=False)
                            continue

                        logger.info("DEBUG: Before yield processing status", session_id=session_id)
                        yield pb2.VoiceOutput(
                            status=pb2.StatusUpdate(status="processing")
                        )
                        logger.info("DEBUG: After yield processing status", session_id=session_id)

                        # Use ProgressiveSTT to finalize (only transcribes final sliver)
                        t_stt_start = _time.perf_counter()

                        if progressive_stt is not None:
                            if not USE_STREAMING_STT:
                                # Wait for any in-flight progressive task to finish
                                if progressive_task is not None and not progressive_task.done():
                                    try:
                                        await asyncio.wait_for(progressive_task, timeout=2.0)
                                    except asyncio.TimeoutError:
                                        logger.warning("Progressive STT task timed out, continuing with finalize",
                                                        session_id=session_id)

                            logger.info("DEBUG: Calling progressive_stt.finalize()", session_id=session_id)
                            try:
                                transcribed = await progressive_stt.finalize()
                            except Exception as e:
                                logger.error(f"DEBUG: Exception in finalize: {type(e).__name__} - {e}")
                                transcribed = ""
                                yield pb2.VoiceOutput(error=pb2.ErrorMessage(code="STT_FAILED", message="Speech-to-Text service failed."))
                            logger.info(f"DEBUG: finalize returned: '{transcribed}'", session_id=session_id)
                            
                            stt_ms = (_time.perf_counter() - t_stt_start) * 1000
                            logger.info(f"⏱ STT (progressive finalize) in {stt_ms:.0f}ms | text='{transcribed[:60]}'",
                                         session_id=session_id, req_id=req_id)
                            if not transcribed:
                                audio_backup = session.get_audio_buffer()
                                if audio_backup and len(audio_backup) >= 1600:
                                    logger.info("Progressive STT returned empty text; attempting fallback transcription on session audio buffer", session_id=session_id)
                                    try:
                                        transcribed = await self._transcribe(audio_backup, session)
                                        logger.info(f"Fallback STT transcription succeeded: '{transcribed}'", session_id=session_id)
                                    except Exception as fb_err:
                                        logger.error(f"Fallback STT failed: {fb_err}", session_id=session_id)

                            progressive_stt.reset()
                            progressive_stt = None
                            progressive_task = None
                        else:
                            # Fallback: batch STT (old path)
                            audio_data = session.clear_audio_buffer()
                            if not audio_data:
                                logger.warning("Speech end received but audio buffer is empty", session_id=session_id)
                                yield pb2.VoiceOutput(
                                    status=pb2.StatusUpdate(status="listening")
                                )
                                if session and session.walker:
                                    arm_inactivity_timer(session.walker.current_node_id, fresh=False)
                                continue
                            transcribed = await self._transcribe(audio_data, session)
                            stt_ms = (_time.perf_counter() - t_turn_start) * 1000
                            logger.info(f"⏱ STT (batch fallback) in {stt_ms:.0f}ms | text='{transcribed[:60]}'",
                                         session_id=session_id, req_id=req_id)

                        # Clear the session's audio buffer (progressive STT had its own copy)
                        session.clear_audio_buffer()

                        if not transcribed:
                            logger.warning("STT returned empty text", session_id=session_id)
                            yield pb2.VoiceOutput(
                                status=pb2.StatusUpdate(status="listening")
                            )
                            if session and session.walker:
                                arm_inactivity_timer(session.walker.current_node_id, fresh=False)
                            continue

                        # Valid user transcript arrived — clear deadline completely before turn streaming
                        clear_inactivity_timer()

                        # Process the turn with streaming pipeline
                        first_audio_yielded = False
                        async for output in session.process_turn_streaming(transcribed):
                            if not first_audio_yielded and output.HasField("audio"):
                                first_audio_ms = (_time.perf_counter() - t_turn_start) * 1000
                                logger.info(f"⏱ FIRST AUDIO from speech_end: {first_audio_ms:.0f}ms",
                                             session_id=session_id, req_id=req_id)
                                first_audio_yielded = True
                            yield output

                        total_turn_ms = (_time.perf_counter() - t_turn_start) * 1000
                        logger.info(f"⏱ TOTAL TURN: {total_turn_ms:.0f}ms",
                                     session_id=session_id, req_id=req_id)

        except grpc.aio.AioRpcError as e:
            logger.warning(f"gRPC error in session: {e.code()}",
                            req_id=req_id, session_id=session_id)
        except Exception as e:
            logger.error(f"Session error: {type(e).__name__} - {e}",
                          req_id=req_id, session_id=session_id,
                          error=traceback.format_exc())
            yield pb2.VoiceOutput(
                error=pb2.ErrorMessage(code="INTERNAL", message=str(e))
            )
        finally:
            clear_inactivity_timer()
            if 'reader_task' in locals() and not reader_task.done():
                reader_task.cancel()
            if progressive_stt is not None:
                # Send EOF to close the STT gRPC stream
                try:
                    progressive_stt._audio_queue.put_nowait(None)
                except Exception:
                    pass
            if session:
                session.disconnect()
                await self._store.remove(session_id)
                logger.info("Session cleaned up",
                             req_id=req_id, session_id=session_id)

    async def RawAgentSession(self, request_iterator, context):
        """
        Generic raw voice session (bidirectional streaming).
        Bypasses GraphWalker state machine.
        """
        from session import RawAgentSession
        req_id = extract_req_id(context)
        set_req_id(req_id)

        logger.info("RawAgentSession started", req_id=req_id)

        session = None
        session_id = None
        progressive_stt = None
        progressive_task = None

        try:
            async for voice_input in request_iterator:
                input_type = voice_input.WhichOneof("input")
                if not input_type:
                    continue

                # ─── Session Start ───
                if input_type == "agent_start":
                    start_data = voice_input.agent_start
                    session_id = start_data.session_id

                    existing_session = await self._store.get(session_id)
                    if existing_session and isinstance(existing_session, RawAgentSession):
                        existing_session.system_prompt = start_data.system_prompt
                        existing_session.context_prompt = start_data.context_prompt
                        session = existing_session
                        logger.info(f"Updated existing RawAgentSession prompts dynamically: {session_id}", req_id=req_id)
                    else:
                        session = RawAgentSession(
                            session_id=session_id,
                            language=start_data.language,
                            system_prompt=start_data.system_prompt,
                            context_prompt=start_data.context_prompt,
                            req_id=req_id,
                            stt_stub=self._stt_stub,
                            tts_stub=self._tts_stub,
                            llm_stub=self._llm_stub,
                        )
                        await session.init()
                        await self._store.create(session_id, session)

                    # The API Gateway already sent the 'connected' status, 
                    # so we don't send it again here to avoid duplicate triggers.
                    # Generic agents default to listening immediately
                    yield pb2.VoiceOutput(
                        status=pb2.StatusUpdate(status="listening")
                    )

                # ─── Audio Chunk ───
                elif input_type == "audio_chunk":
                    if not session:
                        continue
                    audio_bytes = voice_input.audio_chunk
                    session.add_audio_chunk(audio_bytes)

                    # Feed audio to progressive STT if active
                    if progressive_stt is not None:
                        progressive_stt.add_audio(audio_bytes)
                        if not USE_STREAMING_STT:
                            if progressive_task is None or progressive_task.done():
                                progressive_task = asyncio.create_task(
                                    progressive_stt.process_progressive()
                                )

                # ─── Direct Text Input ───
                elif input_type == "text_input":
                    if not session:
                        continue

                    text_val = voice_input.text_input
                    logger.info(f"Raw Agent direct text input: '{text_val}'", session_id=session_id)

                    yield pb2.VoiceOutput(
                        status=pb2.StatusUpdate(status="processing")
                    )

                    async for output in session.process_turn_streaming(text_val):
                        yield output

                    session.clear_audio_buffer()

                # ─── Control Signal ───
                elif input_type == "control":
                    signal_type = voice_input.control.signal
                    if not session:
                        continue

                    logger.info(f"Raw Agent control signal: {signal_type}", session_id=session_id)

                    if signal_type == "speech_start":
                        if USE_STREAMING_STT:
                            if progressive_stt is not None:
                                continue
                            from streaming_stt import StreamingSTT
                            progressive_stt = StreamingSTT(
                                stt_stub=self._stt_stub,
                                language=session.language,
                                req_id=session.req_id,
                                sample_rate=16000,
                            )
                        else:
                            from session import ProgressiveSTT
                            if progressive_stt is not None:
                                continue
                            progressive_stt = ProgressiveSTT(
                                stt_stub=self._stt_stub,
                                language=session.language,
                                req_id=session.req_id,
                                sample_rate=16000,
                                window_duration=3.0,
                                step_duration=1.0,
                            )
                        progressive_task = None
                        yield pb2.VoiceOutput(
                            status=pb2.StatusUpdate(status="listening")
                        )

                    elif signal_type.startswith("capture_speak:"):
                        parts = signal_type.split(":", 1)
                        text = parts[1] if len(parts) > 1 else ""
                        logger.info(f"Raw Agent capture speak text", session_id=session_id)
                        
                        yield pb2.VoiceOutput(
                            status=pb2.StatusUpdate(status="speaking")
                        )
                        async for output in session.process_capture_speak(text):
                            yield output

                    elif signal_type == "capture_processing":
                        logger.info("Raw Agent capture processing started", session_id=session_id)
                        yield pb2.VoiceOutput(
                            status=pb2.StatusUpdate(status="speaking")
                        )
                        async for output in session.process_capture_processing():
                            yield output

                    elif signal_type.startswith("capture_success"):
                        parts = signal_type.split(":", 1)
                        doc_id = parts[1] if len(parts) > 1 else ""
                        logger.info(f"Raw Agent capture success for {doc_id}", session_id=session_id)
                        
                        yield pb2.VoiceOutput(
                            status=pb2.StatusUpdate(status="speaking")
                        )
                        async for output in session.process_capture_success(doc_id):
                            yield output

                    elif signal_type.startswith("capture_error"):
                        parts = signal_type.split(":", 1)
                        err_msg = parts[1] if len(parts) > 1 else ""
                        logger.info(f"Raw Agent capture error: {err_msg}", session_id=session_id)
                        
                        yield pb2.VoiceOutput(
                            status=pb2.StatusUpdate(status="speaking")
                        )
                        async for output in session.process_capture_error(err_msg):
                            yield output

                    elif signal_type == "speech_end":
                        yield pb2.VoiceOutput(
                            status=pb2.StatusUpdate(status="processing")
                        )

                        t_stt_start = time.perf_counter()

                        if progressive_stt is not None:
                            if not USE_STREAMING_STT:
                                if progressive_task is not None and not progressive_task.done():
                                    try:
                                        await asyncio.wait_for(progressive_task, timeout=1.0)
                                    except Exception:
                                        pass
                            try:
                                transcribed = await progressive_stt.finalize()
                            except Exception as e:
                                logger.error(f"Raw progressive STT finalize failed: {e}")
                                transcribed = ""
                                yield pb2.VoiceOutput(error=pb2.ErrorMessage(code="STT_FAILED", message="Speech-to-Text failed."))
                            
                            progressive_stt.reset()
                            progressive_stt = None
                            progressive_task = None
                        else:
                            audio_data = session.clear_audio_buffer()
                            if not audio_data:
                                yield pb2.VoiceOutput(status=pb2.StatusUpdate(status="listening"))
                                continue
                            transcribed = await self._transcribe(audio_data, session)

                        session.clear_audio_buffer()

                        if not transcribed:
                            yield pb2.VoiceOutput(status=pb2.StatusUpdate(status="listening"))
                            continue

                        # (Removed user transcription yield to keep screen clean as requested)

                        # Process response stream
                        async for output in session.process_turn_streaming(transcribed):
                            yield output

        except grpc.aio.AioRpcError as e:
            logger.warning(f"gRPC error in RawAgentSession: {e.code()}",
                            req_id=req_id, session_id=session_id)
        except Exception as e:
            logger.error(f"RawAgentSession error: {type(e).__name__} - {e}",
                          req_id=req_id, session_id=session_id,
                          error=traceback.format_exc())
            yield pb2.VoiceOutput(
                error=pb2.ErrorMessage(code="INTERNAL", message=str(e))
            )
        finally:
            if progressive_stt is not None:
                try:
                    progressive_stt._audio_queue.put_nowait(None)
                except Exception:
                    pass
            if session:
                session.disconnect()
                await self._store.remove(session_id)
                logger.info("RawAgentSession cleaned up",
                             req_id=req_id, session_id=session_id)

    async def GetSessionState(self, request, context):
        """Get current session state (for admin/debug)."""
        req_id = extract_req_id(context)
        session = await self._store.get(request.session_id)

        if not session:
            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details(f"Session '{request.session_id}' not found")
            return pb2.SessionState()

        state = session.get_state()
        return pb2.SessionState(
            session_id=state["session_id"],
            scheme_id=state["scheme_id"],
            current_node_id=state.get("current_node_id", ""),
            current_step=state.get("step_number", 0),
            total_steps=state.get("total_steps", 0),
            json_extracted_data=json.dumps(state.get("extracted_data", {}), ensure_ascii=False),
            status=state["status"],
            started_at=str(state.get("started_at", "")),
            total_turns=state.get("total_turns", 0),
        )

    async def _transcribe(self, audio_data: bytes, session: VoiceSession) -> str:
        from generated import stt_pb2
        try:
            req = stt_pb2.TranscribeRequest(
                audio_data=audio_data,
                language=session.language,
                sample_rate=16000,
                engine="google"
            )
            resp = await self._stt_stub.Transcribe(req, metadata=[("x-request-id", session.req_id)])
            return resp.text
        except Exception as e:
            logger.error(f"STT Transcribe failed: {e}", session_id=session.session_id)
            return ""




async def serve():
    """Start the Voice Engine gRPC server."""
    store = SessionStore()

    server = grpc_aio.server(
        options=[
            ("grpc.max_send_message_length", 50 * 1024 * 1024),
            ("grpc.max_receive_message_length", 50 * 1024 * 1024),
            ("grpc.keepalive_time_ms", 30000),
            ("grpc.keepalive_timeout_ms", 10000),
        ]
    )

    servicer = VoiceConversationServicer(store)

    # Initialize gRPC client stubs to STT, TTS, LLM, Config, Orchestrator services
    import grpc
    from generated import stt_pb2_grpc, tts_pb2_grpc, llm_pb2_grpc, config_registry_pb2_grpc, app_orchestrator_pb2_grpc

    stt_channel = grpc.aio.insecure_channel(STT_SERVICE_ADDR)
    servicer._stt_stub = stt_pb2_grpc.SpeechToTextStub(stt_channel)

    tts_channel = grpc.aio.insecure_channel(TTS_SERVICE_ADDR)
    servicer._tts_stub = tts_pb2_grpc.TextToSpeechStub(tts_channel)

    llm_channel = grpc.aio.insecure_channel(LLM_SERVICE_ADDR)
    servicer._llm_stub = llm_pb2_grpc.LanguageModelStub(llm_channel)

    config_channel = grpc.aio.insecure_channel(CONFIG_REGISTRY_ADDR)
    servicer._config_stub = config_registry_pb2_grpc.ConfigRegistryStub(config_channel)

    orchestrator_channel = grpc.aio.insecure_channel(APP_ORCHESTRATOR_ADDR)
    servicer._orchestrator_stub = app_orchestrator_pb2_grpc.ApplicationOrchestratorStub(orchestrator_channel)

    pb2_grpc.add_VoiceConversationServicer_to_server(servicer, server)

    listen_addr = f"[::]:{VOICE_ENGINE_PORT}"
    server.add_insecure_port(listen_addr)

    logger.info(f"Voice Engine starting on {listen_addr}",
                details={"port": VOICE_ENGINE_PORT})

    await server.start()
    logger.info("Voice Engine ready ✅")

    active_count = await store.count()
    logger.info(f"Active sessions: {active_count}")

    async def shutdown(sig):
        logger.info(f"Received {sig.name}, shutting down...")
        await server.stop(grace=10)

    loop = asyncio.get_event_loop()
    for sig_name in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig_name, lambda s=sig_name: asyncio.create_task(shutdown(s)))

    await server.wait_for_termination()


if __name__ == "__main__":
    asyncio.run(serve())
