"""
Graph Walker — scheme-agnostic interview state machine.

Walks the directed graph loaded from Config Registry.
Manages state transitions, edge evaluation, and context tracking.
This is a pure logic component — no network calls. The Session orchestrator
feeds it data and it decides what to do next.
"""

from typing import Dict, List, Optional, Tuple

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'shared'))
from log_utils.logger import get_logger, get_req_id

logger = get_logger("voice-engine")


class GraphWalker:
    """
    Walks an interview graph node by node.

    The graph is a dict of node_id → node_data loaded from Config Registry.
    Each node has:
    - text_template: Question text with {name} placeholder
    - targets: List of fields to extract at this node
    - edges: List of {condition, next} pairs
    - routing_prompt: Optional LLM routing instruction
    """

    def __init__(self, graph_data: dict, applicant_name: str = "", language: str = "hi"):
        """
        Args:
            graph_data: Interview graph dict from Config Registry
                        { "start_node_id": ..., "nodes": {...}, "context_map": {...} }
            applicant_name: For {name} template interpolation
            language: Selected language code (e.g. hi, en, te)
        """
        self._scheme_config = graph_data
        self._nodes: Dict[str, dict] = graph_data.get("nodes", {})
        self._start_node_id: str = graph_data.get("start_node_id", "START")
        self._context_map: Dict[str, list] = graph_data.get("context_map", {})
        self._language = language

        # Config-driven default applicant placeholder (Zero Hardcoding)
        default_placeholders = graph_data.get("default_applicant_placeholder", {})
        fallback_name = default_placeholders.get(language) or default_placeholders.get("hi") or "Applicant"
        self._name = applicant_name or fallback_name

        self._inactivity_defaults: Dict[str, any] = graph_data.get("inactivity_defaults", {})

        # State
        self._current_node_id: Optional[str] = None
        self._extracted_data: Dict[str, any] = {}
        self._turn_history: List[dict] = []  # [{node_id, question, answer, extracted}]
        self._history_objects: Dict[str, dict] = {}  # {node_id: {original_question, targets, user_answer, follow_ups}}
        self._step_number: int = 0
        self._completed: bool = False

    # ─── Inactivity Policy ───

    def get_inactivity_policy(self, node_id: str = None) -> dict:
        """
        Get resolved inactivity policy for a node.
        Nudges are STRICTLY applicable ONLY for nodes of type 'voice-qa'.
        Merges scheme-level inactivity_defaults with node-level inactivity_policy.
        """
        target_id = node_id or self._current_node_id
        if not target_id:
            return {"enabled": False}

        node = self._nodes.get(target_id, {})
        # Guard: Nudges apply ONLY for voice-qa nodes
        if node.get("type") != "voice-qa":
            return {"enabled": False}

        scheme_defaults = self._inactivity_defaults or {}
        if scheme_defaults.get("enabled") is False:
            return {"enabled": False}

        node_policy = node.get("inactivity_policy", {})
        if node_policy.get("enabled") is False:
            return {"enabled": False}

        return {
            "enabled": True,
            "timeout_seconds": float(node_policy.get("timeout_seconds") or scheme_defaults.get("default_timeout_seconds", 3.0)),
            "max_nudges": int(node_policy.get("max_nudges") or scheme_defaults.get("max_nudges_per_node", 2)),
            "decay_multiplier": float(node_policy.get("decay_multiplier") or scheme_defaults.get("decay_multiplier", 1.4)),
            "nudge_guideline": str(node_policy.get("nudge_guideline", "")),
        }

    # ─── Properties ───

    @property
    def current_node_id(self) -> Optional[str]:
        return self._current_node_id

    @property
    def current_node(self) -> Optional[dict]:
        if not self._current_node_id:
            return None
        return self._nodes.get(self._current_node_id)

    @property
    def extracted_data(self) -> dict:
        return self._extracted_data.copy()

    @property
    def step_number(self) -> int:
        return self._step_number

    @property
    def total_steps(self) -> int:
        return len(self._nodes)

    @property
    def is_completed(self) -> bool:
        return self._completed

    @property
    def turn_history(self) -> list:
        return self._turn_history.copy()

    def _get_node_text(self, node: dict) -> str:
        lang_key = f"text_template_{self._language}"
        return node.get(lang_key, "") or node.get("text_template_en", "") or node.get("text_template", "")

    def get_prompt(self, node: Optional[dict] = None) -> str:
        """Return localized, interpolated question text for current or given node."""
        target_node = node or self.current_node or {}
        return self._interpolate(self._get_node_text(target_node))

    def restore_state(self, last_node: Optional[str], extracted_data: dict = None):
        """
        Restore interview position to last_node and load historical extracted data.
        If last_node is null/empty or not in nodes, starts from beginning.
        """
        if extracted_data:
            self._extracted_data.update(extracted_data)
            import json
            logger.info("🔍 [STAGE 3 - GRAPHWALKER RESTORE_STATE]",
                         extracted_keys=list(self._extracted_data.keys()),
                         extracted_full=json.dumps(self._extracted_data, ensure_ascii=False))

        if last_node and last_node in self._nodes and last_node != "END":
            self._current_node_id = last_node
            node_ids = list(self._nodes.keys())
            if last_node in node_ids:
                self._step_number = node_ids.index(last_node) + 1
            else:
                self._step_number = 1
            self._completed = False
            logger.info("Restored GraphWalker to last_node", last_node=last_node, step_number=self._step_number)
        else:
            self._current_node_id = None

    # ─── Core Operations ───

    def start(self) -> dict:
        """
        Start or resume the interview. Returns the active node info.

        Returns:
            dict: {node_id, text, targets, has_routing, routing_prompt}
        """
        if not self._current_node_id or self._current_node_id not in self._nodes:
            self._current_node_id = self._start_node_id
            self._step_number = 1

        node = self._nodes.get(self._current_node_id, {})
        text = self._interpolate(self._get_node_text(node))

        logger.info("Graph started or resumed",
                     node_id=self._current_node_id,
                     step_number=self._step_number,
                     details={"total_nodes": len(self._nodes)})

        return {
            "node_id": self._current_node_id,
            "text": text,
            "type": node.get("type", "voice-qa"),
            "document_id": node.get("document_id", ""),
            "targets": node.get("targets", []),
            "has_routing": bool(node.get("routing_prompt")),
            "routing_prompt": node.get("routing_prompt", ""),
        }

    def advance(self, extracted_fields: dict = None,
                routing_decision: str = None) -> Optional[dict]:
        """
        Record extraction results and advance to the next node.

        Args:
            extracted_fields: Dict of field_name → value extracted at current node
            routing_decision: "YES" or "NO" from LLM routing (if applicable)

        Returns:
            dict: Next node info, or None if interview is complete
        """
        if self._completed:
            logger.warning("Attempted to advance completed graph")
            return None

        current_node = self._nodes.get(self._current_node_id, {})

        # Record extractions into walker state
        if extracted_fields:
            self._extracted_data.update(extracted_fields)
            logger.info("GraphWalker state updated",
                         node_id=self._current_node_id,
                         new_fields=list(extracted_fields.keys()))

        # Select edge
        edges = current_node.get("edges", [])
        state = {**self._extracted_data}
        if routing_decision:
            state["routing_decision"] = routing_decision

        next_node_id = self._evaluate_edges(edges, state)

        if not next_node_id or next_node_id == "END":
            self._completed = True
            logger.info("Interview completed",
                         final_node=self._current_node_id,
                         turns_taken=self._step_number)
            return None

        self._current_node_id = next_node_id
        self._step_number += 1

        next_node = self._nodes.get(self._current_node_id, {})
        text = self._interpolate(self._get_node_text(next_node))

        logger.info("Advanced to next node",
                     prev_node=current_node.get("node_id", self._current_node_id),
                     next_node=self._current_node_id,
                     step=self._step_number)

        return {
            "node_id": self._current_node_id,
            "text": text,
            "type": next_node.get("type", "voice-qa"),
            "document_id": next_node.get("document_id", ""),
            "targets": next_node.get("targets", []),
            "has_routing": bool(next_node.get("routing_prompt")),
            "routing_prompt": next_node.get("routing_prompt", ""),
        }

    def record_turn_start(self, node_id: str, user_answer: str, targets: list = None):
        """Record the initial user response for a node."""
        if node_id not in self._history_objects:
            node = self._nodes.get(node_id, {})
            text = self._interpolate(self._get_node_text(node))
            if targets is None:
                targets = node.get("targets", [])
            self._history_objects[node_id] = {
                "original_question": text,
                "targets": targets,
                "user_answer": user_answer,
                "follow_ups": []
            }
        else:
            # If re-entering a node for some reason, append to follow-ups instead
            pass

    def record_followup(self, node_id: str, followup_question: str, user_answer: str):
        """Record a follow-up question and the user's answer to it."""
        if node_id in self._history_objects:
            self._history_objects[node_id]["follow_ups"].append({
                "question": followup_question,
                "answer": user_answer
            })

    def build_context_string(self, node_id: str = None) -> str:
        """
        Build the rich context string from conversation history.
        Matches the logic exactly from the monolithic hindi repository.
        """
        target_node = node_id or self._current_node_id
        if not target_node:
            return ""

        context = ""
        deps = self._context_map.get(target_node, [])
        for dep_id in deps:
            if dep_id in self._history_objects:
                obj = self._history_objects[dep_id]
                context += f"\n[PREVIOUS QUESTION CONTEXT: {dep_id}]\n"
                context += f"Master Question: {obj['original_question']}\n"
                context += f"Targets: {obj['targets']}\n"
                context += f"Initial Answer: {obj['user_answer']}\n"
                for idx, fu in enumerate(obj['follow_ups'], 1):
                    context += f"Follow-up {idx} Question: {fu['question']}\n"
                    context += f"Follow-up {idx} Answer: {fu['answer']}\n"
        
        if target_node in self._history_objects:
            obj = self._history_objects[target_node]
            context += f"\n[CURRENT QUESTION CONTEXT: {target_node}]\n"
            context += f"Master Question: {obj['original_question']}\n"
            context += f"Targets: {obj['targets']}\n"
            context += f"Initial Answer: {obj['user_answer']}\n"
            for idx, fu in enumerate(obj['follow_ups'], 1):
                context += f"Follow-up {idx} Question: {fu['question']}\n"
                context += f"Follow-up {idx} Answer: {fu['answer']}\n"
                
        return context.strip()

    def get_context_history(self, node_id: str = None) -> list:
        """
        Legacy method kept for compatibility.
        """
        target_node = node_id or self._current_node_id
        deps = self._context_map.get(target_node, [])

        # If no deps specified, return empty (some nodes are standalone)
        if not deps:
            return []

        history = []
        for turn in self._turn_history:
            if turn["node_id"] in deps:
                # Include the question and answer for dependent nodes
                node = self._nodes.get(turn["node_id"], {})
                text = self._interpolate(self._get_node_text(node))
                history.append({"role": "assistant", "content": text})
                # We don't have the raw answer here, but extracted data is available
                if turn.get("extracted"):
                    answer_summary = ", ".join(
                        f"{k}: {v}" for k, v in turn["extracted"].items()
                    )
                    history.append({"role": "user", "content": answer_summary})

        return history

    def get_field_targets(self, node_id: str = None) -> list:
        """Get the target fields for the current/given node."""
        target_node = node_id or self._current_node_id
        node = self._nodes.get(target_node, {})
        return node.get("targets", [])

    # ─── Internal ───

    def _interpolate(self, template: str) -> str:
        """Replace placeholders in template with values from self._extracted_data."""
        if not template:
            return ""
        
        import json
        res = template
        
        # Flatten extracted data for key resolution
        flat = {}
        def recursive_flatten(d, prefix=""):
            if not isinstance(d, dict):
                return
            for k, v in d.items():
                full_key = f"{prefix}.{k}" if prefix else k
                if isinstance(v, dict):
                    recursive_flatten(v, full_key)
                elif v is not None and v != "":
                    flat[full_key] = v
                    if k not in flat or flat[k] is None or flat[k] == "":
                        flat[k] = v

        recursive_flatten(self._extracted_data)

        # Parse any string-serialized JSONs
        for k, v in list(flat.items()):
            if isinstance(v, str) and (v.startswith('{') or v.startswith('[')):
                try:
                    parsed = json.loads(v)
                    if isinstance(parsed, dict):
                        recursive_flatten(parsed, k)
                except Exception:
                    pass

        import re
        placeholders = re.findall(r"\{([^}]+)\}", res)
        extraction_mappings = self._scheme_config.get("extraction_mappings", {})
        ignored_placeholders = {"applicant", "आवेदक", "demandeur", "المتقدم", "none", "null", "not available", "not_available"}

        for ph in placeholders:
            field_cfg = extraction_mappings.get(ph, {})
            sources = field_cfg.get("sources", [ph]) if isinstance(field_cfg, dict) else [ph]
            if ph not in sources:
                sources = list(sources) + [ph]

            val = None
            matched_src = None
            for src in sources:
                candidate = flat.get(src)
                if candidate is not None:
                    candidate_str = str(candidate).strip()
                    if candidate_str and candidate_str.lower() not in ignored_placeholders:
                        val = candidate_str
                        matched_src = src
                        break

            if val is not None:
                logger.info(f"🎯 [PLACEHOLDER MATCHED] {{{ph}}} -> '{val}' from source key '{matched_src}'")
                res = res.replace(f"{{{ph}}}", val)
            else:
                fallback_map = self._scheme_config.get("default_applicant_placeholder", {})
                fallback = fallback_map.get(self._language) or ("Applicant" if self._language == "en" else "आवेदक")
                logger.info(f"⚠️ [PLACEHOLDER FALLBACK] {{{ph}}} not found in evaluated sources {sources}, using fallback '{fallback}'")
                res = res.replace(f"{{{ph}}}", fallback)

        logger.info("🔍 [STAGE 4 - GRAPHWALKER INTERPOLATION]",
                     template=template,
                     placeholders=placeholders,
                     flat_keys=list(flat.keys()),
                     flat_sample=json.dumps(flat, ensure_ascii=False)[:300],
                     result=res)

        return res

    def _evaluate_edges(self, edges: list, state: dict) -> Optional[str]:
        """
        Evaluate edges in order and return the next node_id.

        Edge conditions:
        - "always": Always matches (fallback)
        - "routing_decision == 'YES'": Check state variable
        """
        for edge in edges:
            condition = edge.get("condition", "")
            next_id = edge.get("next", "")

            if not next_id:
                continue

            if condition == "always":
                return next_id

            # Evaluate condition expression
            try:
                if "==" in condition:
                    parts = condition.split("==")
                    key = parts[0].strip()
                    expected = parts[1].strip().strip("'\"")
                    actual = str(state.get(key, "")).strip()
                    # Perform case-insensitive matching for string comparisons
                    if actual.upper() == expected.upper():
                        return next_id
                elif condition.startswith("not "):
                    key = condition[4:].strip()
                    if not state.get(key):
                        return next_id
                else:
                    # Treat as boolean check
                    if state.get(condition):
                        return next_id
            except Exception:
                continue

        return None  # No matching edge = end

    def to_state_dict(self) -> dict:
        """Serialize walker state for persistence/debugging."""
        return {
            "current_node_id": self._current_node_id,
            "step_number": self._step_number,
            "extracted_data": self._extracted_data,
            "turn_history": self._turn_history,
            "completed": self._completed,
        }

    @classmethod
    def from_state_dict(cls, graph_data: dict, state: dict,
                        applicant_name: str = "") -> "GraphWalker":
        """Restore walker from serialized state."""
        walker = cls(graph_data, applicant_name)
        walker._current_node_id = state.get("current_node_id")
        walker._step_number = state.get("step_number", 0)
        walker._extracted_data = state.get("extracted_data", {})
        walker._turn_history = state.get("turn_history", [])
        walker._completed = state.get("completed", False)
        return walker
