"""
Shared scaffolding for the three help-needed-event detectors.

Each detector inherits the cooldown logic, the feature-extraction call, and
the JSON LLM call. Only the category-specific prompt and rule-based fallback
are defined per subclass.

The cooldown matches the paper's _COOLDOWN constant in InsightAgent (8 s);
combined with the user-controlled ThinkTime threshold this prevents a flood
of help-needed events when several patterns match the same window.
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import asdict
from typing import Any
from uuid import uuid4

from mivais.base_agent import BaseAgent
from interaction_features import Features, extract_features
from llm_client import LLMUnavailable, get_client


COOLDOWN_S = 12.0


class DetectorBase(BaseAgent):
    """Common detector scaffolding for onboarding / exploration."""

    # Subclasses override
    CATEGORY: str = "onboarding"
    ENABLE_KEY: str = "onboarding_enabled"
    PATTERN_KEYS: tuple[str, ...] = ()  # which Fig. 2 patterns we own

    async def run(self) -> None:
        self._last_fired: dict[str, float] = {}  # actor → epoch
        self._subscribe("interaction.event")
        # Keep alive — work happens in on_message.
        import asyncio
        await asyncio.Event().wait()

    # ── Bus ─────────────────────────────────────────────────────────────────

    async def on_message(self, message: dict) -> None:
        payload = message.get("payload") or {}
        actor = payload.get("actor")
        if not actor or not actor.startswith("user:"):
            return

        if not bool(self._read(self.ENABLE_KEY, True)):
            return

        threshold = float(self._read("think_time_threshold_s", 3.0) or 3.0)
        log = self._read("interaction_log", []) or []
        feats = extract_features(log, actor=actor, threshold_s=threshold)

       
        if not self._gate(feats):
            return

        now = time.time()
        last = self._last_fired.get(actor, 0.0)
        if now - last < COOLDOWN_S:
            return

        
        verdict = await self._classify(feats)
        if not verdict or not verdict.get("needs_help"):
            return

        self._last_fired[actor] = now
        await self._emit(actor, feats, verdict)

    # ── Hooks ───────────────────────────────────────────────────────────────

    def _gate(self, feats: Features) -> bool:
        """Cheap behavioural pre-check before invoking the LLM."""
        if feats.long_pause or feats.pause_streak >= 2:
            return True
        if feats.toggle_back_and_forth:
            return True
        if feats.scroll_runs >= 4 or feats.hover_runs >= 5:
            return True
        if any(p in feats.pattern_hints for p in self.PATTERN_KEYS):
            return True
        return False

    async def _classify(self, feats: Features) -> dict | None:
        """Ask the LLM whether this window matches one of our patterns."""
        client = get_client()
        if not client.available:
            return self._heuristic_classify(feats)

        knowledge = self._read("knowledge", {}) or {}
        patterns = [
            p for p in (knowledge.get("interaction_patterns") or [])
            if p.get("category") == self.CATEGORY
        ]
        system = self._build_system_prompt(knowledge, patterns)
        user = (
            f"Recent behaviour summary:\n{feats.summary()}\n\n"
            f"Latest event:\n{json.dumps(feats.latest, default=str)}\n\n"
            "Decide whether this window matches one of the patterns above. "
            "Respond ONLY with a JSON object:\n"
            '{"needs_help": bool, "subcategory": str|null, "pattern": str|null, '
            '"evidence_summary": str, "confidence": number}'
        )
        try:
            
            return await asyncio.to_thread(
                client.chat_json,
                system=system, user=user, model=client.perception_model, temperature=0.0,
            )
        except LLMUnavailable:
            return self._heuristic_classify(feats)
        except Exception as exc:
            print(f"[{self.agent_id}] LLM error: {exc}; falling back to heuristic")
            return self._heuristic_classify(feats)

    def _heuristic_classify(self, feats: Features) -> dict:
        """Deterministic fallback used when no LLM is configured."""
        match = next((p for p in feats.pattern_hints if p in self.PATTERN_KEYS), None)
        if match is None:
            return {"needs_help": False}
        # Look up subcategory + tip template from the knowledge base.
        knowledge = self._read("knowledge", {}) or {}
        info = next(
            (p for p in (knowledge.get("interaction_patterns") or [])
             if p.get("pattern") == match), {},
        )
        return {
            "needs_help": True,
            "subcategory": info.get("subcategory", ""),
            "pattern": match,
            "evidence_summary": info.get("interpretation", ""),
            "confidence": 0.6,
        }

    def _build_system_prompt(self, knowledge: dict, patterns: list[dict]) -> str:
        operations = knowledge.get("available_operations", [])
        lines = [
            "You are a perception agent inside ProactiveVA, a mixed-initiative "
            "visual analytics assistant for the VAST 2021 Mini Challenge 3 "
            f"public-safety event-analysis system. You watch the *{self.CATEGORY}* "
            "category of help-needed events.",
            "",
            "System overview:",
            knowledge.get("system_introduction", ""),
            "",
            f"You are responsible for the following {self.CATEGORY} interaction patterns:",
        ]
        for p in patterns:
            lines.append(f"  - {p['pattern']} ({p['subcategory']}): {p['interpretation']}")
        lines += [
            "",
            "If the user appears to be exhibiting one of these patterns, set "
            "needs_help=true and pick the closest pattern. Otherwise set "
            "needs_help=false. Be conservative: only fire when the behaviour "
            "matches one of the listed patterns.",
        ]
        return "\n".join(lines)

    async def _emit(self, actor: str, feats: Features, verdict: dict) -> None:
        """Publish a help_needed.event to the bus and trace it."""
        event = {
            "id": uuid4().hex[:10],
            "actor": actor,
            "category": self.CATEGORY,
            "subcategory": verdict.get("subcategory"),
            "pattern": verdict.get("pattern"),
            "evidence_summary": verdict.get("evidence_summary", ""),
            "confidence": verdict.get("confidence", 0.5),
            "features": asdict(feats),
            "detected_at": time.time(),
            "detector": self.agent_id,
        }
        await self._publish("help_needed.event", event)
