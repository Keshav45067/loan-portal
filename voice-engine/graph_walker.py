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
        self._nodes: Dict[str, dict] = graph_data.get("nodes", {})
        self._start_node_id: str = graph_data.get("start_node_id", "START")
        self._context_map: Dict[str, list] = graph_data.get("context_map", {})
        self._name = applicant_name or ("आप" if language == "hi" else "you" if language == "en" else "మీరు")
        self._language = language

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

    def restore_state(self, last_node: Optional[str], extracted_data: dict = None):
        """
        Restore interview position to last_node and load historical extracted data.
        If last_node is null/empty or not in nodes, starts from beginning.
        """
        if extracted_data:
            self._extracted_data.update(extracted_data)

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
            return None

        current_node = self.current_node
        if not current_node:
            self._completed = True
            return None

        # Store extracted data
        if extracted_fields:
            self._extracted_data.update(extracted_fields)

        # Record turn history
        self._turn_history.append({
            "node_id": self._current_node_id,
            "step": self._step_number,
            "extracted": extracted_fields or {},
            "routing_decision": routing_decision,
        })

        # Evaluate edges to find next node
        state = {**self._extracted_data}
        if routing_decision:
            state["routing_decision"] = routing_decision

        next_node_id = self._evaluate_edges(current_node.get("edges", []), state)

        if not next_node_id:
            # No edges = end of interview
            self._completed = True
            logger.info("Graph completed",
                         node_id=self._current_node_id,
                         details={"total_steps": self._step_number,
                                  "total_fields": len(self._extracted_data)})
            return None

        # Move to next node
        self._current_node_id = next_node_id
        self._step_number += 1

        next_node = self._nodes.get(next_node_id, {})
        text = self._interpolate(self._get_node_text(next_node))

        logger.info("Advanced to node",
                     node_id=next_node_id,
                     details={"step": self._step_number,
                              "targets": next_node.get("targets", [])})

        return {
            "node_id": next_node_id,
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
        
        # Always replace name
        res = template.replace("{name}", self._name)
        
        # Flatten extracted data
        flat = {}
        # First, add all top-level keys that have truthy or non-empty values
        for k, v in self._extracted_data.items():
            if not isinstance(v, dict):
                if v is not None and v != "":
                    flat[k] = v

        # Then, add nested keys (don't overwrite top-level if top-level already has a value)
        for k, v in self._extracted_data.items():
            if isinstance(v, dict):
                for sub_k, sub_v in v.items():
                    flat[f"{k}.{sub_k}"] = sub_v
                    if sub_k not in flat or flat[sub_k] is None or flat[sub_k] == "":
                        flat[sub_k] = sub_v

        # Parse string-serialized dictionaries (fallback support)
        parsed_flat = {}
        for k, v in flat.items():
            if isinstance(v, str) and (v.startswith('{') or v.startswith('[')):
                try:
                    import ast
                    parsed_v = ast.literal_eval(v)
                    if isinstance(parsed_v, dict):
                        for sub_k, sub_v in parsed_v.items():
                            parsed_flat[f"{k}.{sub_k}"] = sub_v
                            if sub_k not in parsed_flat:
                                parsed_flat[sub_k] = sub_v
                except Exception:
                    pass
        flat.update(parsed_flat)
        
        # Friendly gender translation for Hindi voice output
        gender_val = flat.get("gender")
        if gender_val and isinstance(gender_val, str):
            g_upper = gender_val.strip().upper()
            if g_upper in ("MALE", "M"):
                flat["gender"] = "पुरुष"
            elif g_upper in ("FEMALE", "F"):
                flat["gender"] = "महिला"
            elif g_upper in ("TRANSGENDER", "T"):
                flat["gender"] = "ट्रांसजेंडर"
                
        # Aadhaar last four digits helper
        aadhaar_val = flat.get("aadhaar_number")
        if aadhaar_val and isinstance(aadhaar_val, str):
            clean_num = ''.join(c for c in aadhaar_val if c.isdigit())
            if len(clean_num) >= 4:
                flat["aadhaar_last_four"] = clean_num[-4:]
            else:
                flat["aadhaar_last_four"] = clean_num
                
        # PAN last four digits helper
        pan_val = flat.get("pan_number")
        if pan_val and isinstance(pan_val, str):
            if len(pan_val) >= 4:
                flat["pan_last_four"] = pan_val[-4:]
            else:
                flat["pan_last_four"] = pan_val

        # Replace dynamic placeholders
        import re
        placeholders = re.findall(r"\{([^}]+)\}", res)
        for ph in placeholders:
            if ph in ("name", "applicant_name", "full_name"):
                name_val = flat.get(ph) or flat.get("applicant_name") or flat.get("doc_aadhaar_name") or flat.get("name") or self._name
                if name_val and str(name_val).strip() not in ("", "None", "Null", "Not Available", "Not Provided", "उपलब्ध नहीं"):
                    res = res.replace(f"{{{ph}}}", str(name_val))
                else:
                    res = res.replace(f"{{{ph}}}", self._name)
                continue
            val = flat.get(ph)
            if val is not None and str(val).strip() not in ("", "None", "Null", "Not Available", "Not Provided", "not_available"):
                res = res.replace(f"{{{ph}}}", str(val))
            else:
                fallback_text = "उपलब्ध नहीं" if self._language == "hi" else "Not Available"
                res = res.replace(f"{{{ph}}}", fallback_text)
        
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
