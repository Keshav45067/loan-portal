"""
Voice Session — manages a single voice interview session.

Implements the Hindi-style 2-call streaming pipeline for low latency:
  Task A (Conversational): Streaming LLM → FollowupStreamParser → sentence-chunked TTS → immediate audio
  Task B (Extraction):     Async background extraction (non-blocking)

Each session holds:
- A GraphWalker (state machine)
- gRPC stubs to STT, TTS, LLM, Config services
- The extracted data accumulated across turns
"""

import json
import asyncio
from generated import llm_pb2
from generated import config_registry_pb2
from generated import voice_engine_pb2 as pb2
import time
from typing import AsyncIterator, Optional, Dict

import grpc

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'shared'))
from log_utils.logger import get_logger, set_req_id, get_req_id, LatencyTracker

from graph_walker import GraphWalker

logger = get_logger("voice-engine")


class ProgressiveSTT:
    """
    Async Sliding-Window STT manager (port of Hindi repo's SlidingWindowSTT).

    During speech, it runs STT inference every `step_duration` seconds using
    a sliding window of `window_duration` seconds. Text is stitched using
    sequence matching to avoid chopped-word boundary problems.

    At speech_end, only the final audio sliver (~0-1s) needs transcription,
    reducing latency from 1400-3200ms to ~200-400ms.
    """

    def __init__(self, stt_stub, language: str, req_id: str,
                 sample_rate: int = 16000,
                 window_duration: float = 3.0,
                 step_duration: float = 1.0):
        self._stt_stub = stt_stub
        self._language = language
        self._req_id = req_id
        self._sample_rate = sample_rate
        self._window_bytes = int(window_duration * sample_rate * 2)  # 16-bit PCM = 2 bytes/sample
        self._step_bytes = int(step_duration * sample_rate * 2)

        self._audio_buffer = bytearray()
        self._committed_text = ""
        self._uncommitted_text = ""
        self._last_transcribed_bytes = 0
        self._task = None
        self._lock = asyncio.Lock()

    def add_audio(self, chunk: bytes):
        """Add audio chunk to internal buffer."""
        self._audio_buffer.extend(chunk)

    async def process_progressive(self) -> str:
        """
        Called periodically. If enough new audio has accumulated (step_duration),
        runs STT on the latest window and stitches the result.
        Returns current full transcript.
        """
        current_len = len(self._audio_buffer)

        # Not enough new audio yet — skip inference
        if current_len - self._last_transcribed_bytes < self._step_bytes:
            return self._build_full_text()

        # Get the window of audio to transcribe
        window_audio = bytes(self._audio_buffer[-self._window_bytes:]) if current_len > self._window_bytes else bytes(self._audio_buffer)

        # Run STT via gRPC
        try:
            from generated import stt_pb2
            req = stt_pb2.TranscribeRequest(
                audio_data=window_audio,
                language=self._language,
                sample_rate=self._sample_rate,
                engine="google"
            )
            resp = await self._stt_stub.Transcribe(
                req, metadata=[("x-request-id", self._req_id)]
            )
            new_text = resp.text
            self._last_transcribed_bytes = current_len
        except Exception as e:
            logger.error(f"Progressive STT inference failed: {e}")
            return self._build_full_text()

        # If total audio is smaller than window, just replace uncommitted
        if current_len <= self._window_bytes:
            self._uncommitted_text = new_text
            return self._build_full_text()

        # Stitch text using sequence matching (same as Hindi repo)
        self._stitch_text(new_text)
        return self._build_full_text()

    async def finalize(self) -> str:
        """
        Called at speech_end. Transcribes any remaining audio and commits all text.
        Returns the final full transcript.
        """
        current_len = len(self._audio_buffer)

        if current_len == 0:
            return self._committed_text

        # If we have new audio since last transcription, process it
        if current_len - self._last_transcribed_bytes > 0:
            window_audio = bytes(self._audio_buffer[-self._window_bytes:]) if current_len > self._window_bytes else bytes(self._audio_buffer)
            try:
                from generated import stt_pb2
                req = stt_pb2.TranscribeRequest(
                    audio_data=window_audio,
                    language=self._language,
                    sample_rate=self._sample_rate,
                    engine="google"
                )
                resp = await self._stt_stub.Transcribe(
                    req, metadata=[("x-request-id", self._req_id)]
                )
                new_text = resp.text

                if current_len <= self._window_bytes:
                    self._uncommitted_text = new_text
                else:
                    self._stitch_text(new_text)
            except Exception as e:
                logger.error(f"Progressive STT finalize failed: {e}")

        # Commit everything
        full = self._build_full_text()
        self._committed_text = full
        self._uncommitted_text = ""
        return full

    def get_audio_buffer(self) -> bytes:
        """Get the raw audio buffer (for fallback batch STT)."""
        return bytes(self._audio_buffer)

    def reset(self):
        """Reset for next turn."""
        self._audio_buffer.clear()
        self._committed_text = ""
        self._uncommitted_text = ""
        self._last_transcribed_bytes = 0

    def _stitch_text(self, new_text: str):
        """Stitch new window text with existing text using sequence matching."""
        import difflib
        old_words = self._uncommitted_text.split()
        new_words = new_text.split()

        if not old_words:
            self._uncommitted_text = new_text
            return
        if not new_words:
            return

        matcher = difflib.SequenceMatcher(None, old_words, new_words)
        match = matcher.find_longest_match(0, len(old_words), 0, len(new_words))

        if match.size > 0:
            committed_part = " ".join(old_words[:match.a])
            if committed_part:
                self._committed_text += " " + committed_part if self._committed_text else committed_part
            self._uncommitted_text = " ".join(new_words[match.b:])
        else:
            self._committed_text += " " + self._uncommitted_text if self._committed_text else self._uncommitted_text
            self._uncommitted_text = new_text

    def _build_full_text(self) -> str:
        if self._committed_text and self._uncommitted_text:
            return self._committed_text + " " + self._uncommitted_text
        elif self._committed_text:
            return self._committed_text
        return self._uncommitted_text


# ── Sentence splitting punctuations (same as Hindi repo) ──
SENTENCE_PUNCS = [".", "!", "?", "؟", "\n", "।", "|", "،", ","]


class FollowupStreamParser:
    """
    On-the-fly JSON stream parser that detects `is_followup` early
    and extracts `followup_question` text chunk-by-chunk.
    Ported from Hindi repo's stream_parser.py.
    """
    def __init__(self):
        self.buffer = ""
        self.is_followup = None
        self.in_question = False
        self.question_complete = False
        self.emitted_idx = 0

    def process_chunk(self, chunk: str):
        """
        Process a new chunk from the LLM stream.
        Returns (is_followup, text_chunk).
        """
        self.buffer += chunk

        # 1. Detect is_followup status ASAP
        if self.is_followup is None:
            buf_no_space = self.buffer.replace(" ", "").replace("\n", "").replace("\r", "")
            if '"is_followup":true' in buf_no_space:
                self.is_followup = True
            elif '"is_followup":false' in buf_no_space:
                self.is_followup = False
                return self.is_followup, ""

        # 2. Extract followup_question chunks if true
        if self.is_followup is True and not self.question_complete:
            # Find start of string value
            if not self.in_question:
                q_idx = self.buffer.find('"followup_question"')
                if q_idx != -1:
                    colon_idx = self.buffer.find(':', q_idx)
                    if colon_idx != -1:
                        quote_idx = self.buffer.find('"', colon_idx)
                        if quote_idx != -1:
                            self.in_question = True
                            self.emitted_idx = quote_idx + 1

            # Stream characters up to the end quote
            if self.in_question:
                end_quote_idx = -1
                for i in range(self.emitted_idx, len(self.buffer)):
                    if self.buffer[i] == '"' and (i == 0 or self.buffer[i-1] != '\\'):
                        end_quote_idx = i
                        break

                if end_quote_idx != -1:
                    new_text = self.buffer[self.emitted_idx:end_quote_idx]
                    self.emitted_idx = end_quote_idx + 1
                    self.in_question = False
                    self.question_complete = True
                    return True, new_text
                else:
                    new_text = self.buffer[self.emitted_idx:]
                    self.emitted_idx = len(self.buffer)
                    return True, new_text

        return self.is_followup, ""


def split_sentences(text_buffer: str):
    """
    Split text_buffer into complete sentences at punctuation boundaries.
    Returns (list_of_sentences, remaining_buffer).
    Same logic as Hindi repo.
    """
    sentences = []
    while True:
        idx = -1
        for punc in SENTENCE_PUNCS:
            p = text_buffer.find(punc)
            if p != -1 and (idx == -1 or p < idx):
                idx = p
        if idx == -1:
            break

        # Include consecutive punctuations (e.g. '...' or '!?')
        while idx + 1 < len(text_buffer) and text_buffer[idx + 1] in SENTENCE_PUNCS:
            idx += 1

        sentence = text_buffer[: idx + 1].strip()
        text_buffer = text_buffer[idx + 1:]
        if sentence:
            sentences.append(sentence)

    return sentences, text_buffer


class VoiceSession:
    """
    Manages a single voice interview session.

    Lifecycle:
    1. init() — fetch config from Config Registry, create GraphWalker
    2. start() — speak the first question, begin listening
    3. process_audio(audio) — 2-call pipeline per turn
    4. Repeat until GraphWalker says interview is complete
    """

    def __init__(
        self,
        session_id: str,
        scheme_id: str,
        language: str,
        applicant_name: str,
        application_id: str,
        req_id: str,
        # gRPC stubs (injected by the server)
        stt_stub=None,
        tts_stub=None,
        llm_stub=None,
        config_stub=None,
        orchestrator_stub=None,
    ):
        self.session_id = session_id
        self.scheme_id = scheme_id
        self.language = language
        self.applicant_name = applicant_name
        self.application_id = application_id
        self.req_id = req_id

        self._stt_stub = stt_stub
        self._tts_stub = tts_stub
        self._llm_stub = llm_stub
        self._config_stub = config_stub
        self._orchestrator_stub = orchestrator_stub

        # Session state
        self._walker: Optional[GraphWalker] = None
        self._config: Optional[dict] = None
        self._field_instructions: Dict[str, str] = {}
        self._media_config: dict = {}
        self._status: str = "initializing"  # initializing, active, completed, disconnected
        self._started_at = time.time()
        self._total_turns = 0
        self._last_followup_question = ""

    @property
    def status(self) -> str:
        return self._status

    @property
    def walker(self) -> Optional[GraphWalker]:
        return self._walker

    async def init(self):
        """
        Initialize session: fetch config from Config Registry, create GraphWalker.
        """
        set_req_id(self.req_id)
        logger.info("Initializing session",
                     session_id=self.session_id,
                     scheme_id=self.scheme_id,
                     language=self.language)

        # Fetch from Config Registry via gRPC
        try:
            config_resp = await self._config_stub.GetSchemeConfig(
                config_registry_pb2.SchemeRequest(scheme_id=self.scheme_id),
                metadata=[("x-request-id", self.req_id)]
            )
            
            # Convert interview graph nodes to dict format for walker
            graph_nodes = {}
            for node_id, proto_node in config_resp.interview_graph.nodes.items():
                edges = []
                for edge in proto_node.edges:
                    edges.append({
                        "condition": edge.condition,
                        "next": edge.next_node_id
                    })
                graph_nodes[node_id] = {
                    "node_id": node_id,
                    "text_template": proto_node.text_template,
                    "text_template_en": proto_node.text_template_en,
                    "text_template_te": proto_node.text_template_te,
                    "targets": list(proto_node.targets),
                    "edges": edges,
                    "routing_prompt": proto_node.routing_prompt,
                    "type": proto_node.type,
                    "document_id": proto_node.document_id
                }
                
            context_map = {}
            for node_id, deps in config_resp.interview_graph.context_map.items():
                context_map[node_id] = list(deps.dependencies)
                
            graph_data = {
                "nodes": graph_nodes,
                "start_node_id": config_resp.interview_graph.start_node_id,
                "context_map": context_map
            }
            
            field_instructions = {}
            for name, fi in config_resp.field_instructions.items():
                field_instructions[name] = fi.instruction
                
            # Extract media config for the selected language
            media_config = {}
            if self.language in config_resp.media_configs:
                mc = config_resp.media_configs[self.language]
                media_config = {
                    "tts_voice_name": mc.tts_voice_name,
                    "tts_engine": mc.tts_engine,
                    "tts_sample_rate": mc.tts_sample_rate,
                    "stt_engine": mc.stt_engine,
                    "stt_language_code": mc.stt_language_code,
                }
                
            self.set_graph(graph_data, field_instructions, media_config)
            await self._sync_extracted_data()
            
        except Exception as e:
            logger.error(f"Failed to fetch scheme config from Config Registry: {e}",
                         session_id=self.session_id, error=str(e))
            # Fallback to a basic empty graph to avoid crash
            self.set_graph({"nodes": {}, "start_node_id": "START", "context_map": {}})

        self._status = "active"
        logger.info("Session initialized",
                     session_id=self.session_id)

    async def _sync_extracted_data(self):
        """Fetch historical extracted data from DB via App Orchestrator."""
        if not self._orchestrator_stub:
            logger.warning("Orchestrator stub not available, skipping data sync", session_id=self.session_id)
            return
        try:
            from generated import app_orchestrator_pb2
            resp = await self._orchestrator_stub.GetExtractedData(
                app_orchestrator_pb2.AppIdRequest(application_id=self.session_id),
                metadata=[("x-request-id", self.req_id)]
            )
            if resp and resp.json_data:
                import json
                data = json.loads(resp.json_data)
                if data and self._walker:
                    self._walker._extracted_data.update(data)
                    logger.info("Successfully synced extracted data from DB",
                                 session_id=self.session_id,
                                 keys=list(data.keys()))
                    # Extract and sync applicant name from historical data
                    holder_dict = data.get("holder") if isinstance(data.get("holder"), dict) else {}
                    ext_name = (
                        data.get("applicant_name") or 
                        data.get("name") or 
                        data.get("full_name") or
                        holder_dict.get("full_name") or
                        holder_dict.get("name")
                    )
                    if ext_name and ext_name != "आवेदक":
                        self.applicant_name = ext_name
                        self._walker._name = ext_name
        except Exception as e:
            logger.error(f"Failed to sync extracted data: {e}", session_id=self.session_id)

    def add_audio_chunk(self, chunk: bytes):
        if not hasattr(self, "_audio_buffer"):
            self._audio_buffer = bytearray()
        self._audio_buffer.extend(chunk)

    def get_audio_buffer(self) -> bytes:
        if not hasattr(self, "_audio_buffer"):
            self._audio_buffer = bytearray()
        return bytes(self._audio_buffer)

    def clear_audio_buffer(self) -> bytes:
        if not hasattr(self, "_audio_buffer"):
            self._audio_buffer = bytearray()
        data = bytes(self._audio_buffer)
        self._audio_buffer.clear()
        return data

    def set_graph(self, graph_data: dict, field_instructions: dict = None,
                  media_config: dict = None):
        """
        Set graph data directly (used in v1 until Config Registry is wired).
        In production, this is fetched via gRPC in init().
        """
        self._walker = GraphWalker(graph_data, self.applicant_name, self.language)
        self._field_instructions = field_instructions or {}
        self._media_config = media_config or {}

    async def start(self) -> dict:
        """
        Start the interview. Returns the first question.

        Returns:
            dict: {node_id, text, targets, has_routing, routing_prompt}
        """
        if not self._walker:
            raise RuntimeError("Graph not set. Call init() and set_graph() first.")

        first_node = self._walker.start()
        self._total_turns += 1

        logger.info("Interview started",
                     session_id=self.session_id,
                     node_id=first_node["node_id"],
                     details={"text": first_node["text"][:80]})

        return first_node

    async def process_turn_streaming(self, transcribed_text: str, is_capture_complete: bool = False):
        """
        Process one turn with Hindi-style streaming architecture.

        This is an async generator that yields pb2.VoiceOutput messages
        as they become available, enabling real-time audio delivery.

        Pipeline (matches Hindi repo):
          Task A (Conversational LLM — streaming):
            Stream LLM → FollowupStreamParser → sentence-chunked TTS → yield audio immediately
          Task B (Extraction LLM — async background):
            Fire-and-forget extraction via unary LLM call, does NOT block audio

        Yields:
            pb2.VoiceOutput messages (status, transcription, audio, progress, extraction, complete)
        """
        set_req_id(self.req_id)
        t_turn_start = time.perf_counter()

        if is_capture_complete:
            await self._sync_extracted_data()

        if not self._walker or self._walker.is_completed:
            if self._walker:
                self._walker._extracted_data["onboarding_finished"] = True
                self._walker._extracted_data["completion_status"] = "COMPLETED"
                # Persist completed state directly from voice-engine
                if self._orchestrator_stub:
                    try:
                        from generated import app_orchestrator_pb2
                        await self._orchestrator_stub.UpsertExtractedData(
                            app_orchestrator_pb2.UpsertDataRequest(
                                application_id=self.session_id,
                                source="voice-qa-complete-early",
                                json_fields=json.dumps({
                                    "onboarding_finished": True,
                                    "completion_status": "COMPLETED"
                                }, ensure_ascii=False)
                            ),
                            metadata=[("x-request-id", self.req_id)]
                        )
                        logger.info("Direct early complete persist successful from voice-engine", session_id=self.session_id)
                    except Exception as db_err:
                        logger.error(f"Failed to direct early complete persist from voice-engine: {db_err}", session_id=self.session_id)

            yield pb2.VoiceOutput(
                complete=pb2.SessionComplete(
                    session_id=self.session_id,
                    json_extracted_data=json.dumps(self._walker.extracted_data if self._walker else {}, ensure_ascii=False),
                    total_turns=self._total_turns,
                )
            )
            return

        # Sync applicant name if it was extracted (e.g. from Aadhaar)
        if not self.applicant_name or self.applicant_name == "आवेदक":
            holder_dict = self._walker.extracted_data.get("holder") if isinstance(self._walker.extracted_data.get("holder"), dict) else {}
            extracted_name = (
                self._walker.extracted_data.get("full_name") or 
                self._walker.extracted_data.get("name") or
                self._walker.extracted_data.get("applicant_name") or
                holder_dict.get("full_name") or
                holder_dict.get("name")
            )
            if extracted_name:
                logger.info(f"Syncing extracted applicant name: '{extracted_name}'", session_id=self.session_id)
                self.applicant_name = extracted_name
                self._walker._name = extracted_name

        current_node = self._walker.current_node
        if current_node is None:
            logger.error("Current node not found in graph, ending session gracefully to avoid crash", session_id=self.session_id)
            yield pb2.VoiceOutput(
                error=pb2.ErrorMessage(
                    code="INTERNAL",
                    message="Configuration error: current graph node is empty or not found."
                )
            )
            return

        current_node_id = self._walker.current_node_id
        targets = self._walker.get_field_targets()

        # Build prompts / instructions map first
        target_instructions = {}
        for target in targets:
            if target in self._field_instructions:
                target_instructions[target] = self._field_instructions[target]

        # Update GraphWalker History Objects
        if current_node_id not in self._walker._history_objects:
            self._walker.record_turn_start(current_node_id, transcribed_text, list(target_instructions.keys()))
        else:
            self._walker.record_followup(current_node_id, self._last_followup_question, transcribed_text)
            self._last_followup_question = ""

        logger.info("⏱ Processing turn (streaming)",
                     session_id=self.session_id,
                     node_id=current_node_id,
                     details={"transcript": transcribed_text[:100],
                              "targets": targets})

        question_text = current_node.get("text_template", "")
        routing_prompt = current_node.get("routing_prompt", "")

        context_str = self._walker.build_context_string()

        if current_node.get("type") in ("capture", "video_capture") and not is_capture_complete:
            logger.info("Ignoring voice turn on capture/video node — re-sending node_change",
                         session_id=self.session_id, node_id=current_node_id)
            yield pb2.VoiceOutput(
                node_change=pb2.NodeChange(
                    node_type=current_node.get("type"),
                    document_id=current_node.get("document_id", "")
                )
            )
            return

        # ─── Shortcut: If there are no extraction targets, skip Task A ───
        # For nodes like START and Q_STATUS that have no targets,
        # any user response is sufficient — advance the graph immediately.
        if not targets and not routing_prompt:
            logger.info("No targets and no routing — auto-advancing graph",
                         session_id=self.session_id, node_id=current_node_id)

            next_node = self._walker.advance(
                extracted_fields={},
                routing_decision="NONE",
            )
            self._total_turns += 1

            if next_node:
                yield pb2.VoiceOutput(
                    progress=pb2.ProgressUpdate(
                        current_step=self._walker.step_number,
                        total_steps=self._walker.total_steps,
                        current_node_id=next_node["node_id"],
                    )
                )

                node_type = next_node.get("type", "voice-qa")
                if node_type in ("capture", "video_capture"):
                    yield pb2.VoiceOutput(
                        node_change=pb2.NodeChange(
                            node_type=node_type,
                            document_id=next_node.get("document_id", "")
                        )
                    )
                else:
                    yield pb2.VoiceOutput(
                        node_change=pb2.NodeChange(
                            node_type="voice-qa",
                            document_id=""
                        )
                    )
                
                full_text = next_node.get("text", "")
                if full_text.strip():
                    yield pb2.VoiceOutput(status=pb2.StatusUpdate(status="speaking"))

                    sentences, remainder = split_sentences(full_text)
                    if remainder.strip():
                        sentences.append(remainder.strip())

                    for sentence in sentences:
                        clean_sentence = sentence.replace("|", "").strip()
                        if clean_sentence:
                            yield pb2.VoiceOutput(
                                transcription=pb2.TranscriptionUpdate(
                                    text=clean_sentence, is_final=False
                                )
                            )
                            async for audio_data in self._synthesize_text(clean_sentence):
                                yield pb2.VoiceOutput(
                                    audio=pb2.AudioData(wav_data=audio_data, sample_rate=24000)
                                )

                    total_turn_ms = (time.perf_counter() - t_turn_start) * 1000
                    logger.info(f"⏱ TOTAL TURN (auto-advance): {total_turn_ms:.0f}ms",
                                 session_id=self.session_id)
                    yield pb2.VoiceOutput(audio_end=True)
                
                if next_node.get("type") != "capture":
                    yield pb2.VoiceOutput(status=pb2.StatusUpdate(status="listening"))
            else:
                self._walker._extracted_data["onboarding_finished"] = True
                self._walker._extracted_data["completion_status"] = "COMPLETED"
                # Persist completed state directly from voice-engine
                if self._orchestrator_stub:
                    try:
                        from generated import app_orchestrator_pb2
                        await self._orchestrator_stub.UpsertExtractedData(
                            app_orchestrator_pb2.UpsertDataRequest(
                                application_id=self.session_id,
                                source="voice-qa-complete",
                                json_fields=json.dumps({
                                    "onboarding_finished": True,
                                    "completion_status": "COMPLETED"
                                }, ensure_ascii=False)
                            ),
                            metadata=[("x-request-id", self.req_id)]
                        )
                        logger.info("Direct complete persist successful from voice-engine", session_id=self.session_id)
                    except Exception as db_err:
                        logger.error(f"Failed to direct complete persist from voice-engine: {db_err}", session_id=self.session_id)

                yield pb2.VoiceOutput(
                    complete=pb2.SessionComplete(
                        session_id=self.session_id,
                        json_extracted_data=json.dumps(self._walker.extracted_data, ensure_ascii=False),
                        total_turns=self._total_turns,
                    )
                )
            return

        # ─── TASK A: Conversational LLM (streaming) ───
        # This prompt asks the LLM to decide: follow-up or move on,
        # exactly like Hindi repo's conversation_prompt
        conversation_prompt = self._build_conversational_prompt(
            context_str=context_str,
            target_instructions=target_instructions,
            routing_prompt=routing_prompt,
            transcribed_text=transcribed_text,
        )

        user_prompt = f"Question asked: {question_text}\nUser's response: {transcribed_text}"

        text_buffer = ""
        accumulated_text = ""  # All followup text accumulated so far (for live display)
        parser = FollowupStreamParser()
        is_followup_detected = None
        ttft_ms = None
        first_audio_sent = False
        t_llm_start = time.perf_counter()

        try:
            # Stream from LLM via gRPC GenerateStream
            # Use gemini-2.5-flash for Task A — low latency, supported region
            stream = self._llm_stub.GenerateStream(
                llm_pb2.GenerateRequest(
                    prompt=f"{conversation_prompt}",
                    model="gemini-2.5-flash",
                    temperature=0.3,
                    system_instruction=f"You must use {self.language} only.",
                    disable_thinking=True,
                    thinking_budget=0,
                ),
                metadata=[("x-request-id", self.req_id)]
            )

            async for text_chunk_msg in stream:
                text_chunk = text_chunk_msg.text
                if not text_chunk:
                    continue

                if ttft_ms is None:
                    ttft_ms = (time.perf_counter() - t_llm_start) * 1000
                    logger.info(f"LLM TTFT: {ttft_ms:.0f}ms", session_id=self.session_id)

                # Parse chunk through FollowupStreamParser
                status, parsed_text = parser.process_chunk(text_chunk)

                if status is False:
                    # Not a followup — let stream finish to capture routing_decision
                    if is_followup_detected is None:
                        is_followup_detected = False
                        logger.info("is_followup: false → waiting for routing_decision",
                                     session_id=self.session_id)

                if status is True:
                    is_followup_detected = True
                    # It's a followup — stream the extracted question text to TTS
                    if parsed_text:
                        text_buffer += parsed_text
                        accumulated_text += parsed_text

                        # Sentence chunking — synthesize and yield complete sentences immediately
                        sentences, text_buffer = split_sentences(text_buffer)
                        for sentence in sentences:
                            clean_sentence = sentence.replace("|", "").strip()
                            if clean_sentence:
                                # Send THIS sentence's text to frontend (per-chunk, not accumulated)
                                yield pb2.VoiceOutput(
                                    transcription=pb2.TranscriptionUpdate(
                                        text=clean_sentence, is_final=False
                                    )
                                )
                                yield pb2.VoiceOutput(
                                    status=pb2.StatusUpdate(status="speaking")
                                )
                                t_tts = time.perf_counter()
                                async for audio_data in self._synthesize_text(clean_sentence):
                                    if not first_audio_sent:
                                        first_audio_ms = (time.perf_counter() - t_turn_start) * 1000
                                        logger.info(f"⏱ FIRST AUDIO (followup): {first_audio_ms:.0f}ms from turn start",
                                                     session_id=self.session_id)
                                        first_audio_sent = True
                                    yield pb2.VoiceOutput(
                                        audio=pb2.AudioData(wav_data=audio_data, sample_rate=24000)
                                    )

            llm_total_ms = (time.perf_counter() - t_llm_start) * 1000
            logger.info(f"LLM Task A completed in: {llm_total_ms:.0f}ms", session_id=self.session_id)

        except Exception as e:
            logger.error(f"LLM streaming failed: {e}", session_id=self.session_id)
            yield pb2.VoiceOutput(error=pb2.ErrorMessage(code="LLM_FAILED", message=f"LLM streaming failed: {e}"))
            return

        # ─── Handle result ───
        if is_followup_detected is False:
            # Question fully answered — extract routing_decision from full JSON
            routing_decision = "NONE"
            try:
                import re
                s = parser.buffer.strip()
                s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.IGNORECASE)
                s = re.sub(r"\s*```$", "", s)
                first = s.find("{")
                last = s.rfind("}")
                if first != -1 and last != -1 and last >= first:
                    cand = s[first:last+1]
                    full_json = json.loads(cand)
                    routing_decision = full_json.get("routing_decision", "NONE")
                else:
                    full_json = json.loads(s)
                    routing_decision = full_json.get("routing_decision", "NONE")
                logger.info(f"Extracted routing_decision: {routing_decision}",
                             session_id=self.session_id)
            except Exception as e:
                logger.warning(f"Failed to parse JSON for routing_decision: {e}. Raw buffer: {parser.buffer[:200]}",
                                session_id=self.session_id)

            # ─── TASK B: Extraction (async, non-blocking) ───
            # Fire extraction in the background — does NOT block audio delivery
            if target_instructions:
                extraction_prompt = (
                    f"{context_str}\n\n"
                    f"Question asked: {question_text}\n"
                    f"User's response: {transcribed_text}\n\n"
                    f"Extract the following fields based on these instructions:\n"
                    f"{json.dumps(target_instructions, ensure_ascii=False, indent=2)}\n"
                    "Output ONLY a valid JSON dictionary."
                )
                # Run extraction asynchronously — don't await
                asyncio.create_task(self._async_extract(extraction_prompt, targets))

            # Advance graph using routing_decision from Task A
            next_node = self._walker.advance(
                extracted_fields={},  # Will be filled by async Task B
                routing_decision=routing_decision,
            )

            self._total_turns += 1

            if next_node:
                # Send progress
                yield pb2.VoiceOutput(
                    progress=pb2.ProgressUpdate(
                        current_step=self._walker.step_number,
                        total_steps=self._walker.total_steps,
                        current_node_id=next_node["node_id"],
                    )
                )

                node_type = next_node.get("type", "voice-qa")
                if node_type in ("capture", "video_capture"):
                    yield pb2.VoiceOutput(
                        node_change=pb2.NodeChange(
                            node_type=node_type,
                            document_id=next_node.get("document_id", "")
                        )
                    )
                else:
                    yield pb2.VoiceOutput(
                        node_change=pb2.NodeChange(
                            node_type="voice-qa",
                            document_id=""
                        )
                    )

                # Build response text (empathetic acknowledgment + next question)
                # Try to get response_text from parsed LLM JSON (Task A may have included it)
                response_text = ""
                try:
                    full_json = json.loads(parser.buffer)
                    response_text = full_json.get("response_text", "")
                except Exception:
                    pass

                full_text = ""
                if response_text:
                    full_text = response_text + " "
                full_text += next_node.get("text", "")

                if full_text.strip():
                    # Synthesize and stream the response sentence by sentence
                    yield pb2.VoiceOutput(status=pb2.StatusUpdate(status="speaking"))

                    # Split full text into sentences and stream TTS per sentence
                    sentences, remainder = split_sentences(full_text)
                    if remainder.strip():
                        sentences.append(remainder.strip())

                    for sentence in sentences:
                        clean_sentence = sentence.replace("|", "").strip()
                        if clean_sentence:
                            # Send per-sentence text before its audio
                            yield pb2.VoiceOutput(
                                transcription=pb2.TranscriptionUpdate(
                                    text=clean_sentence, is_final=False
                                )
                            )
                            t_tts = time.perf_counter()
                            async for audio_data in self._synthesize_text(clean_sentence):
                                if not first_audio_sent:
                                    first_audio_ms = (time.perf_counter() - t_turn_start) * 1000
                                    logger.info(f"⏱ FIRST AUDIO (next-q): {first_audio_ms:.0f}ms from turn start",
                                                 session_id=self.session_id)
                                    first_audio_sent = True
                                yield pb2.VoiceOutput(
                                    audio=pb2.AudioData(wav_data=audio_data, sample_rate=24000)
                                )

                    yield pb2.VoiceOutput(audio_end=True)
                
                if next_node["node_id"] == "END":
                    self._status = "completed"
                    self._walker._extracted_data["onboarding_finished"] = True
                    self._walker._extracted_data["completion_status"] = "COMPLETED"
                    if self._orchestrator_stub:
                        try:
                            from generated import app_orchestrator_pb2
                            await self._orchestrator_stub.UpsertExtractedData(
                                app_orchestrator_pb2.UpsertDataRequest(
                                    application_id=self.session_id,
                                    source="voice-qa-complete",
                                    json_fields=json.dumps({
                                        "onboarding_finished": True,
                                        "completion_status": "COMPLETED"
                                    }, ensure_ascii=False)
                                ),
                                metadata=[("x-request-id", self.req_id)]
                            )
                            logger.info("Direct complete persist successful from voice-engine", session_id=self.session_id)
                        except Exception as db_err:
                            logger.error(f"Failed to direct complete persist from voice-engine: {db_err}", session_id=self.session_id)

                    yield pb2.VoiceOutput(
                        complete=pb2.SessionComplete(
                            session_id=self.session_id,
                            json_extracted_data=json.dumps(self._walker.extracted_data, ensure_ascii=False),
                            total_turns=self._total_turns,
                        )
                    )
                else:
                    if next_node.get("type") != "capture":
                        yield pb2.VoiceOutput(status=pb2.StatusUpdate(status="listening"))

                total_turn_ms = (time.perf_counter() - t_turn_start) * 1000
                logger.info(f"⏱ TOTAL TURN (next-q path): {total_turn_ms:.0f}ms",
                             session_id=self.session_id)

            else:
                # Interview complete
                self._status = "completed"
                self._walker._extracted_data["onboarding_finished"] = True
                self._walker._extracted_data["completion_status"] = "COMPLETED"
                logger.info("Interview completed",
                             session_id=self.session_id,
                             details={"total_turns": self._total_turns,
                                      "total_fields": len(self._walker.extracted_data)})
                
                # Persist completed state directly from voice-engine
                if self._orchestrator_stub:
                    try:
                        from generated import app_orchestrator_pb2
                        await self._orchestrator_stub.UpsertExtractedData(
                            app_orchestrator_pb2.UpsertDataRequest(
                                application_id=self.session_id,
                                source="voice-qa-complete",
                                json_fields=json.dumps({
                                    "onboarding_finished": True,
                                    "completion_status": "COMPLETED"
                                }, ensure_ascii=False)
                            ),
                            metadata=[("x-request-id", self.req_id)]
                        )
                        logger.info("Direct complete persist successful from voice-engine", session_id=self.session_id)
                    except Exception as db_err:
                        logger.error(f"Failed to direct complete persist from voice-engine: {db_err}", session_id=self.session_id)

                yield pb2.VoiceOutput(
                    complete=pb2.SessionComplete(
                        session_id=self.session_id,
                        json_extracted_data=json.dumps(self._walker.extracted_data, ensure_ascii=False),
                        total_turns=self._total_turns,
                    )
                )
        else:
            # It's a follow-up or safety fallback (is_followup_detected is True or None)
            if is_followup_detected is None:
                logger.warning("is_followup_detected is None, defaulting to follow-up to prevent deadlock",
                               session_id=self.session_id)

            # It's a follow-up — cache the question for the next turn's context
            self._last_followup_question = parser.buffer.strip()

            # Flush remaining followup text
            remaining, _ = split_sentences(text_buffer)
            if remaining:
                clean_remaining = remaining.replace("|", "").strip()
                if clean_remaining:
                    # Send remaining sentence text
                    yield pb2.VoiceOutput(
                        transcription=pb2.TranscriptionUpdate(
                            text=clean_remaining, is_final=False
                        )
                    )
                    async for audio_data in self._synthesize_text(clean_remaining):
                        yield pb2.VoiceOutput(
                            audio=pb2.AudioData(wav_data=audio_data, sample_rate=24000)
                        )
            yield pb2.VoiceOutput(audio_end=True)
            yield pb2.VoiceOutput(status=pb2.StatusUpdate(status="listening"))

    async def _async_extract(self, prompt: str, targets: list):
        """
        Background extraction task (Task B).
        Calls LLM Extract (unary) and updates the walker's extracted data.
        Does NOT block audio delivery.
        """
        try:
            response = await self._llm_stub.Extract(
                llm_pb2.ExtractRequest(
                    prompt=prompt,
                    model="gemini-2.5-flash",
                    temperature=0.2,
                    system_instruction="Extract data from the conversation. Output ONLY valid JSON.",
                    disable_thinking=True,
                ),
                metadata=[("x-request-id", self.req_id)]
            )

            if response.success:
                parsed = json.loads(response.json_text)
                extracted_fields = {}
                for target in targets:
                    if target in parsed:
                        extracted_fields[target] = parsed[target]

                if extracted_fields:
                    self._walker._extracted_data.update(extracted_fields)
                    logger.info("Background extraction completed",
                                 session_id=self.session_id,
                                 details={"extracted": list(extracted_fields.keys())})
                    if self._orchestrator_stub:
                        try:
                            from generated import app_orchestrator_pb2
                            await self._orchestrator_stub.UpsertExtractedData(
                                app_orchestrator_pb2.UpsertDataRequest(
                                    application_id=self.session_id,
                                    source="voice-qa",
                                    json_fields=json.dumps(extracted_fields, ensure_ascii=False)
                                ),
                                metadata=[("x-request-id", self.req_id)]
                            )
                            logger.info("Successfully persisted voice-extracted fields to DB", 
                                        session_id=self.session_id, keys=list(extracted_fields.keys()))
                        except Exception as db_err:
                            logger.error(f"Failed to persist voice-extracted fields to DB: {db_err}",
                                         session_id=self.session_id)
            else:
                logger.error(f"Background extraction failed: {response.error}",
                              session_id=self.session_id)
        except Exception as e:
            logger.error(f"Background extraction error: {e}",
                          session_id=self.session_id)

    async def _synthesize_text(self, text: str):
        """
        Synthesize text via TTS gRPC stream.
        Yields raw audio bytes for each fragment.
        """
        from generated import tts_pb2

        if self.language == "hi":
            voice_name = "hi-IN-Neural2-A"
        elif self.language == "te":
            voice_name = "te-IN-Wavenet-A"
        else:
            voice_name = "en-US-Neural2-F"
        engine = "google"
        sample_rate = 24000

        if self._media_config:
            voice_name = self._media_config.get("tts_voice_name", voice_name)
            engine = self._media_config.get("tts_engine", engine)
            sample_rate = self._media_config.get("tts_sample_rate", sample_rate)

        req = tts_pb2.SynthesizeRequest(
            text=text,
            language=self.language,
            voice_name=voice_name,
            engine=engine,
            output_sample_rate=sample_rate,
            session_id=self.session_id
        )
        try:
            t0 = time.perf_counter()
            async for frag in self._tts_stub.SynthesizeStream(req, metadata=[("x-request-id", self.req_id)]):
                if frag.audio_data:
                    yield frag.audio_data
            tts_ms = (time.perf_counter() - t0) * 1000
            logger.info(f"TTS chunk: '{text[:50]}...' in {tts_ms:.0f}ms",
                         session_id=self.session_id)
        except Exception as e:
            logger.error(f"TTS SynthesizeStream failed: {e}", session_id=self.session_id)
            raise e

    def _build_conversational_prompt(self, context_str: str, target_instructions: dict,
                                      routing_prompt: str, transcribed_text: str) -> str:
        """
        Build the conversational LLM prompt for Task A.
        Same structure as Hindi repo's conversation_prompt.
        """
        lang_prompts = {
            "hi": {
                "lang_name": "Hindi",
                "filler": (
                    "CRITICAL: If 'is_followup' is true, your 'followup_question' MUST be highly conversational and natural. "
                    "1) Start with a warm, expressive reaction to what the user just said using natural Hindi conversational words "
                    "(e.g., 'जी बिल्कुल', 'अच्छा', 'समझ गई', 'अरे वाह', 'हम्म'). Do not use English words like 'umm' or 'hmm', "
                    "write them in Hindi script. End this short acknowledgment exactly with a '|' or '।' character. "
                    "2) If the user asked a question, answer it sweetly and directly. "
                    "3) Finally, ask your followup question in a friendly tone to extract the required target.\n"
                )
            },
            "en": {
                "lang_name": "English",
                "filler": (
                    "CRITICAL: If 'is_followup' is true, your 'followup_question' MUST be highly conversational and natural. "
                    "1) Start with a warm, expressive reaction (e.g., 'Oh, I see!', 'That sounds great.', 'Ah, got it.'). "
                    "End this short acknowledgment with a '.' or ',' character. "
                    "2) If the user asked a question, answer it sweetly and directly. "
                    "3) Finally, ask your followup question in a friendly tone.\n"
                )
            },
            "ar": {
                "lang_name": "Arabic",
                "filler": (
                    "CRITICAL: If 'is_followup' is true, your 'followup_question' MUST be highly conversational and natural. "
                    "1) Start with a warm reaction using Arabic words (e.g. 'آه فهمت', 'حسناً', 'يا سلام'). "
                    "End acknowledgment with '.' or '،'. "
                    "2) Answer user questions sweetly. 3) Ask followup to extract the target.\n"
                )
            },
            "te": {
                "lang_name": "Telugu",
                "filler": (
                    "CRITICAL: If 'is_followup' is true, your 'followup_question' MUST be highly conversational and natural. "
                    "1) Start with a warm reaction using Telugu words (e.g., 'అవును', 'మంచిది', 'అర్థమైంది', 'చాలా బాగుంది'). "
                    "End acknowledgment with '.' or ','. "
                    "2) Answer user questions sweetly. 3) Ask followup to extract the target.\n"
                )
            },
        }

        p_config = lang_prompts.get(self.language, lang_prompts["hi"])

        routing_instruction = ""
        if routing_prompt:
            routing_instruction = f"\nIf is_followup is false, {routing_prompt}\n"

        scheme_type = "bank account opening / form filling"
        if "loan" in str(self.scheme_id).lower() or "mudra" in str(self.scheme_id).lower():
            scheme_type = "loan application"

        import json
        extracted_data_str = json.dumps(self._walker.extracted_data if self._walker else {}, ensure_ascii=False, indent=2)
        targets_str = json.dumps(target_instructions, ensure_ascii=False, indent=2)

        if self.applicant_name and self.applicant_name != "आवेदक":
            name_instruction = f"You are talking to the applicant. Their name is: {self.applicant_name}."
        else:
            extracted_name = self._walker.extracted_data.get("full_name") or self._walker.extracted_data.get("name") if self._walker else None
            if extracted_name and extracted_name != "आवेदक":
                self.applicant_name = extracted_name
                name_instruction = f"You are talking to the applicant. Their name is: {self.applicant_name}."
            else:
                if self.language == "hi":
                    name_instruction = "You are talking to the applicant. Their name is not known yet. Do NOT use placeholder names like 'आवेदक' or 'आवेदक जी'. Address them politely without using a name."
                elif self.language == "te":
                    name_instruction = "You are talking to the applicant. Their name is not known yet. Address them politely without using a name."
                else:
                    name_instruction = "You are talking to the applicant. Their name is not known yet. Address them politely as 'sir/ma'am' or just speak without a name. Do NOT use Hindi words like 'Aavedak ji' or 'Aavedak'."

        return (
            f"{name_instruction}\n"
            f"Here is the data you have already extracted so far:\n{extracted_data_str}\n\n"
            f"{context_str}\n\n"
            f"You are acting as a highly expressive, sweet, and friendly female customer service agent conducting a {scheme_type} interview in {p_config['lang_name']}. Do not sound like a robot.\n"
            f"CRITICAL RULE: You MUST speak exclusively in {p_config['lang_name']}. Do NOT use any other language in your response.\n"
            f"Your goal is to warmly chat with the user and extract the following fields based on these instructions:\n{targets_str}\n"
            "If the user's latest answer is adequate to extract the targets completely, set 'is_followup': false and 'followup_question': ''.\n"
            f"If the answer is irrelevant, incomplete, or vague, set 'is_followup': true and write a very friendly, polite 'followup_question' in {p_config['lang_name']}.\n"
            f"{p_config['filler']}"
            f"Stay within the boundaries of this {scheme_type}. Do not answer questions wildly unrelated to the {scheme_type} or the personal details provided in the context.\n"
            f"{routing_instruction}"
            f"The applicant's latest response that you are evaluating right now is: '{transcribed_text}'.\n"
            "Respond with a JSON object containing: is_followup (bool), followup_question (str), and optionally routing_decision (str)."
        )

    async def process_capture_processing(self):
        """Play processing audio message."""
        processing_msgs = {
            "en": "Your document is processing. Please wait.",
            "hi": "आपका दस्तावेज प्रोसेस हो रहा है। कृपया प्रतीक्षा करें।",
            "te": "మీ పత్రం ప్రాసెస్ చేయబడుతోంది. దయచేసి వేచి ఉండండి.",
            "ar": "مستندك قيد المعالجة. يرجى الانتظار."
        }
        text = processing_msgs.get(self.language, processing_msgs["en"])
        
        # Yield transcription for display
        yield pb2.VoiceOutput(
            transcription=pb2.TranscriptionUpdate(text=text, is_final=False)
        )
        
        async for audio_chunk in self._synthesize_text(text):
            yield pb2.VoiceOutput(
                audio=pb2.AudioData(wav_data=audio_chunk, sample_rate=24000)
            )
        yield pb2.VoiceOutput(audio_end=True)

    async def process_capture_success(self, document_type: str):
        """Play document capture success audio message."""
        doc_names = {
            "en": {
                "aadhaar_front": "Aadhaar front",
                "aadhaar_back": "Aadhaar back",
                "pan": "PAN card",
                "address_proof": "Address proof",
                "correspondence": "Correspondence address proof",
                "correspondence_proof": "Correspondence address proof",
                "default": "document"
            },
            "hi": {
                "aadhaar_front": "आधार कार्ड का अगला हिस्सा",
                "aadhaar_back": "आधार कार्ड का पिछला हिस्सा",
                "pan": "पैन कार्ड",
                "address_proof": "पते का प्रमाण",
                "correspondence": "पत्राचार का पता प्रमाण",
                "correspondence_proof": "पत्राचार का पता प्रमाण",
                "default": "दस्तावेज़"
            },
            "te": {
                "aadhaar_front": "ఆధార్ కార్డ్ ముందు భాగం",
                "aadhaar_back": "ఆధార్ కార్డ్ వెనుక భాగం",
                "pan": "పాన్ కార్డ్",
                "address_proof": "చిరునామా రుజువు",
                "correspondence": "చిరునామా రుజువు",
                "correspondence_proof": "చిరునామా రుజువు",
                "default": "పత్రం"
            },
            "ar": {
                "aadhaar_front": "الوجه الأمامي لبطاقة الهوية",
                "aadhaar_back": "الوجه الخلفي لبطاقة الهوية",
                "pan": "بطاقة الرقم الضريبي",
                "address_proof": "إثبات العنوان",
                "correspondence": "إثبات عنوان المراسلات",
                "correspondence_proof": "إثبات عنوان المراسلات",
                "default": "المستند"
            }
        }
        
        lang_names = doc_names.get(self.language, doc_names["en"])
        doc_name = lang_names.get(document_type, lang_names.get(document_type.lower(), lang_names["default"]))
        
        success_templates = {
            "en": f"Details from your {doc_name} have been extracted.",
            "hi": f"आपके {doc_name} से विवरण निकाल लिए गए हैं।",
            "te": f"మీ {doc_name} నుండి వివరాలు సేకరించబడ్డాయి.",
            "ar": f"تم استخراج البيانات من {doc_name} بنجاح."
        }
        text = success_templates.get(self.language, success_templates["en"])
        
        # Yield transcription for display
        yield pb2.VoiceOutput(
            transcription=pb2.TranscriptionUpdate(text=text, is_final=False)
        )
        
        async for audio_chunk in self._synthesize_text(text):
            yield pb2.VoiceOutput(
                audio=pb2.AudioData(wav_data=audio_chunk, sample_rate=24000)
            )
        yield pb2.VoiceOutput(audio_end=True)

    async def process_capture_error(self, error_message: str):
        """Play error audio message."""
        text = self._get_localized_error(error_message)
        
        # Yield transcription for display
        yield pb2.VoiceOutput(
            transcription=pb2.TranscriptionUpdate(text=text, is_final=False)
        )
        
        async for audio_chunk in self._synthesize_text(text):
            yield pb2.VoiceOutput(
                audio=pb2.AudioData(wav_data=audio_chunk, sample_rate=24000)
            )
        yield pb2.VoiceOutput(audio_end=True)
        yield pb2.VoiceOutput(status=pb2.StatusUpdate(status="listening"))

    async def process_capture_speak(self, text: str):
        """Play arbitrary text as audio message."""
        yield pb2.VoiceOutput(
            transcription=pb2.TranscriptionUpdate(text=text, is_final=False)
        )
        
        async for audio_chunk in self._synthesize_text(text):
            yield pb2.VoiceOutput(
                audio=pb2.AudioData(wav_data=audio_chunk, sample_rate=24000)
            )
        yield pb2.VoiceOutput(audio_end=True)
        yield pb2.VoiceOutput(status=pb2.StatusUpdate(status="listening"))

    def _get_localized_error(self, err_msg: str) -> str:
        err_msg_lower = str(err_msg).lower()
        
        # Check for blurred/cropped
        if "blur" in err_msg_lower or "crop" in err_msg_lower or "clearer" in err_msg_lower:
            errs = {
                "en": "The image is blurred or cropped. Please take a clearer photo.",
                "hi": "फ़ोटो धुंधली या कटी हुई है। कृपया एक स्पष्ट फ़ोटो लें।",
                "te": "చిత్రం అస్పష్టంగా లేదా కత్తిరించబడింది. దయచేసి మరింత స్పష్టమైన చిత్రాన్ని తీసుకోండి.",
                "ar": "الصورة غير واضحة أو مقصوصة. يرجى التقاط صورة أكثر وضوحًا."
            }
            return errs.get(self.language, errs["en"])
            
        # Check for invalid document type
        if "not appear to be a valid" in err_msg_lower or "incorrect document" in err_msg_lower or "intended document" in err_msg_lower or "invalid" in err_msg_lower:
            errs = {
                "en": "This does not appear to be a valid document. Please upload a clear image of the correct document.",
                "hi": "यह सही दस्तावेज़ नहीं लग रहा है। कृपया सही दस्तावेज़ की एक स्पष्ट फ़ोटो अपलोड करें।",
                "te": "ఇది సరైన పత్రం వలె కనిపించడం లేదు. దయచేసి సరైన పత్రం యొక్క స్పష్టమైన చిత్రాన్ని అప్‌లోడ్ చేయండి.",
                "ar": "لا يبدو هذا المستند صالحًا. يرجى تحميل صورة واضحة للمستند الصحيح."
            }
            return errs.get(self.language, errs["en"])
            
        # Default error
        errs = {
            "en": "Verification failed. Please upload a valid document.",
            "hi": "सत्यापन विफल रहा। कृपया एक मान्य दस्तावेज़ अपलोड करें।",
            "te": "ధృవీకరణ విఫలమైంది. దయచేసి ఒక చెల్లుబాటు అయ్యే పత్రాన్ని అప్‌లోడ్ చేయండి.",
            "ar": "فشل التحقق. يرجى تحميل مستند صالح."
        }
        return errs.get(self.language, errs["en"])

    def get_state(self) -> dict:
        """Get current session state (for admin/debug)."""
        return {
            "session_id": self.session_id,
            "scheme_id": self.scheme_id,
            "language": self.language,
            "status": self._status,
            "current_node_id": self._walker.current_node_id if self._walker else None,
            "step_number": self._walker.step_number if self._walker else 0,
            "total_steps": self._walker.total_steps if self._walker else 0,
            "extracted_data": self._walker.extracted_data if self._walker else {},
            "total_turns": self._total_turns,
            "started_at": self._started_at,
        }

    def disconnect(self):
        """Mark session as disconnected."""
        self._status = "disconnected"
        logger.info("Session disconnected",
                     session_id=self.session_id,
                     details={"turns": self._total_turns})


class RawAgentSession(VoiceSession):
    """
    State-free generic voice session. Bypasses GraphWalker.
    Stitches system and context prompts with incoming user speech / text.
    """

    def __init__(
        self,
        session_id: str,
        language: str,
        system_prompt: str,
        context_prompt: str,
        req_id: str,
        stt_stub=None,
        tts_stub=None,
        llm_stub=None,
    ):
        super().__init__(
            session_id=session_id,
            scheme_id="raw_agent",
            language=language,
            applicant_name="",
            application_id="",
            req_id=req_id,
            stt_stub=stt_stub,
            tts_stub=tts_stub,
            llm_stub=llm_stub,
            config_stub=None,
            orchestrator_stub=None,
        )
        self.system_prompt = system_prompt
        self.context_prompt = context_prompt
        self._status = "active"

    async def init(self):
        """Override parent init to skip config loading and walker setup."""
        set_req_id(self.req_id)
        self._status = "active"
        logger.info("Raw agent session initialized", session_id=self.session_id)

    async def process_turn_streaming(self, transcribed_text: str):
        """
        Stream conversational LLM response for raw agent turn.
        Directly queries the LLM and streams TTS sentence by sentence.
        """
        set_req_id(self.req_id)
        t_turn_start = time.perf_counter()

        user_prompt = f"Context:\n{self.context_prompt}\n\nUser's message:\n{transcribed_text}"

        try:
            # Stream from LLM via gRPC GenerateStream with thinking budget disabled
            stream = self._llm_stub.GenerateStream(
                llm_pb2.GenerateRequest(
                    prompt=user_prompt,
                    model="gemini-2.5-flash",
                    temperature=0.3,
                    system_instruction=self.system_prompt,
                    disable_thinking=True,
                    thinking_budget=0,
                ),
                metadata=[("x-request-id", self.req_id)]
            )

            yield pb2.VoiceOutput(status=pb2.StatusUpdate(status="speaking"))

            current_sentence = ""
            async for text_chunk_msg in stream:
                text_chunk = text_chunk_msg.text
                if not text_chunk:
                    continue
                current_sentence += text_chunk

                # Split sentences using voice-engine's helper
                sentences, remainder = split_sentences(current_sentence)
                current_sentence = remainder

                for sentence in sentences:
                    clean = sentence.replace("|", "").strip()
                    if clean:
                        # Send transcription to client
                        yield pb2.VoiceOutput(
                            transcription=pb2.TranscriptionUpdate(
                                text=clean, is_final=False
                            )
                        )
                        # Synthesize speech audio chunks
                        async for audio_chunk in self._synthesize_text(clean):
                            yield pb2.VoiceOutput(
                                audio=pb2.AudioData(wav_data=audio_chunk, sample_rate=24000)
                            )

            # Process remainder sentence in the text buffer
            if current_sentence.strip():
                clean = current_sentence.replace("|", "").strip()
                if clean:
                    yield pb2.VoiceOutput(
                        transcription=pb2.TranscriptionUpdate(
                            text=clean, is_final=False
                        )
                    )
                    async for audio_chunk in self._synthesize_text(clean):
                        yield pb2.VoiceOutput(
                            audio=pb2.AudioData(wav_data=audio_chunk, sample_rate=24000)
                        )

            # Signal end of playback
            yield pb2.VoiceOutput(audio_end=True)
            yield pb2.VoiceOutput(status=pb2.StatusUpdate(status="listening"))

            total_turn_ms = (time.perf_counter() - t_turn_start) * 1000
            logger.info(f"⏱ RAW AGENT TURN COMPLETE: {total_turn_ms:.0f}ms", session_id=self.session_id)

        except Exception as e:
            logger.error(f"RawAgentSession turn generation failed: {e}",
                         session_id=self.session_id)
            yield pb2.VoiceOutput(
                error=pb2.ErrorMessage(code="INTERNAL", message=str(e))
            )
