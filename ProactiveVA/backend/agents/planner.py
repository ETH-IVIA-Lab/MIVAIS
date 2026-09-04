"""
Planner 

"""
from __future__ import annotations

import asyncio
import json
import time
from collections import Counter
from typing import Any
from uuid import uuid4

from mivais.base_agent import BaseAgent
from llm_client import LLMUnavailable, get_client


CONTEXT_RECENT_EVENTS = 12


GLOBAL_SUGGESTION_COOLDOWN_S = 30.0
VERIFICATION_COOLDOWN_S      = 10.0


class Planner(BaseAgent):

    async def run(self) -> None:
        self._last_suggestion_at: dict[str, float] = {}  # actor → epoch
        self._subscribe("help_needed.event")
        await asyncio.Event().wait()

    # ── Bus ─────────────────────────────────────────────────────────────────

    async def on_message(self, message: dict) -> None:
        evt = message.get("payload") or {}
        category = evt.get("category", "")
        actor = evt.get("actor") or "unknown"

        
        cooldown = VERIFICATION_COOLDOWN_S if category == "verification" else GLOBAL_SUGGESTION_COOLDOWN_S
        last = self._last_suggestion_at.get(actor, 0.0)
        if time.time() - last < cooldown:
            return

        
        self._last_suggestion_at[actor] = time.time()

        if category == "verification":
            suggestion = self._build_verification_suggestion(evt)
        else:
            suggestion = await self._build_perception_suggestion(evt)

        if suggestion is None:
            
            self._last_suggestion_at[actor] = last
            return

        # Append to WorldState["pending_suggestions"] — append-only, capped to 50.
        suggestions = list(self._read("pending_suggestions", []) or [])
        suggestions.append(suggestion)
        if len(suggestions) > 50:
            suggestions = suggestions[-50:]
        self._write("pending_suggestions", suggestions)

        await self._publish("pending_suggestion.new", suggestion)

    # ── Onboarding / exploration ───────────────────────────────────────────

    async def _build_perception_suggestion(self, evt: dict) -> dict | None:
        category = evt.get("category", "exploration")
        knowledge = self._read("knowledge", {}) or {}
        focused = self._read("focused_view", "map")
        selected_hex = self._read("selected_hex")
        selected_entity = self._read("selected_entity")
        time_range = self._read("time_range")
        keyword_filter = self._read("keyword_filter", []) or []

        recent_log = (self._read("interaction_log", []) or [])
        recent_for_user = [e for e in recent_log if e.get("actor") == evt.get("actor")][-CONTEXT_RECENT_EVENTS:]
        dataset_summary = self._dataset_summary()

        client = get_client()
        if client.available:
            try:
                inferred = await asyncio.to_thread(
                    self._call_llm,
                    client, evt, knowledge, focused, selected_hex,
                    selected_entity, time_range, keyword_filter,
                    recent_for_user, dataset_summary,
                )
            except Exception as exc:
                print(f"[{self.agent_id}] LLM error: {exc}; using template")
                inferred = self._template_intent(evt, knowledge, focused)
        else:
            inferred = self._template_intent(evt, knowledge, focused)

        return {
            "id": uuid4().hex[:10],
            "origin_event_id": evt.get("id"),
            "category": category,
            "subcategory": evt.get("subcategory") or "",
            "pattern": evt.get("pattern") or "",
            "user_intent": inferred.get("user_intent", ""),
            "suggestion_text": inferred.get("suggestion_text", ""),
            "popover": inferred.get("popover"),
            "note_id": None,
            "note_issue": None,
            "status": "pending",
            "timestamp": time.time(),
        }

    def _call_llm(
        self,
        client: Any,
        evt: dict,
        knowledge: dict,
        focused: str | None,
        selected_hex: str | None,
        selected_entity: str | None,
        time_range: dict | None,
        keyword_filter: list[str],
        recent: list[dict],
        dataset_summary: dict,
    ) -> dict:
        category = evt.get("category", "exploration")

        system = (
            "You are the planning stage of a proactive UI agent for a visual "
            "analytics system (VAST 2021 MC3 — public-safety event analysis "
            "in the city of Abila). The perception layer has just detected "
            f"that the user may need help in the *{category}* category.\n\n"
            "Your job: infer the user's analytical intent from their current "
            "context and craft a single, concrete, non-intrusive suggestion. "
            "The suggestion must be phrased as a question that the user can "
            "accept with one click, e.g.:\n"
            "   \"It seems you're having trouble locating the Fire event. "
            "Would you like me to explore related messages for you?\"\n\n"
            "If the category is onboarding, the suggestion should TEACH "
            "(brief tip about a feature). If exploration, it should OFFER to "
            "do work on the user's behalf. Be specific to the user's "
            "current focus and selection state.\n\n"
            "Respond ONLY with JSON:\n"
            '  {"user_intent": str, "suggestion_text": str, "popover": '
            '{"level": "info"|"warning"|"ok", "title": str, "text": str, '
            '"target": {"view": str, "element": str|null}} | null}'
        )

        user = "\n".join([
            "Detected event:",
            json.dumps({k: evt.get(k) for k in
                        ("category", "subcategory", "pattern", "evidence_summary", "confidence")},
                       indent=2),
            "",
            f"Focused view: {focused}",
            f"selected_hex: {selected_hex}",
            f"selected_entity: {selected_entity}",
            f"time_range: {time_range}",
            f"keyword_filter: {keyword_filter}",
            "",
            f"Recent interactions ({len(recent)}):",
            json.dumps(recent, indent=2),
            "",
            "Dataset summary:",
            json.dumps(dataset_summary, indent=2),
            "",
            "System overview (for grounding):",
            knowledge.get("system_introduction", ""),
        ])

        return client.chat_json(
            system=system, user=user, model=client.perception_model, temperature=0.2,
        )

    def _template_intent(self, evt: dict, knowledge: dict, focused: str | None) -> dict:
        """Used when the LLM is unavailable — uses the tip_template from knowledge."""
        pattern = evt.get("pattern", "")
        info = next(
            (p for p in (knowledge.get("interaction_patterns") or [])
             if p.get("pattern") == pattern),
            {},
        )
        intent_lookup = {
            "onboarding": "User appears unfamiliar with this part of the system.",
            "exploration": "User appears stuck while exploring the data.",
            "verification": "User may need help verifying their findings.",
        }
        tip = info.get("tip_template", "I can help — would you like a tip?")
        category = evt.get("category", "exploration")
        prefix = "Need a hand?" if category == "onboarding" else "Want me to help?"
        suggestion = f"{prefix} {tip}"
        return {
            "user_intent": intent_lookup.get(category, ""),
            "suggestion_text": suggestion,
            "popover": {
                "level": "info",
                "title": (info.get("subcategory") or category).replace("_", " ").title(),
                "text": tip,
                "target": {"view": focused or "messages", "element": None},
            },
        }

    # ── Verification ────────────────────────────────────────────────────────

    def _build_verification_suggestion(self, evt: dict) -> dict | None:
        
        if evt.get("_via_behaviour"):
            return self._build_behavioural_verification_suggestion(evt)

        issue = evt.get("issue") or {}
        if not issue.get("comment"):
            return None
        issue_type = issue.get("type", "factual_error")
        title_map = {
            "factual_error": "Possible factual error",
            "conflict":      "Conflict between notes",
            "omission":      "Possible omission",
        }
        text = issue.get("comment", "")
        if issue.get("correction"):
            text += f"\nSuggested correction: {issue['correction']}"
        return {
            "id": uuid4().hex[:10],
            "origin_event_id": evt.get("id"),
            "category": "verification",
            "subcategory": issue_type,
            "pattern": evt.get("pattern", "note_review"),
            "user_intent": "User submitted a note that may need revision.",
            "suggestion_text": (
                f"I noticed a possible issue with your note: {issue.get('comment','')}"
            ),
            "popover": {
                "level": "warning",
                "title": title_map.get(issue_type, "Note issue"),
                "text": text,
                "target": {"view": "notes", "element": evt.get("note_id")},
            },
            "note_id": evt.get("note_id"),
            "note_issue": issue,
            "status": "pending",
            "timestamp": time.time(),
        }

    def _build_behavioural_verification_suggestion(self, evt: dict) -> dict | None:
        """Patterns 7-9 of paper Fig. 2 — behaviour suggests the user is
        questioning their own findings, so we offer a verification action."""
        sub = evt.get("subcategory") or "verification"
        title_map = {
            "incompleteness": "Anything missing from your notes?",
            "contradiction":  "Possible conflict between notes?",
            "inaccuracy":     "Cross-check a finding?",
        }
        text_map = {
            "incompleteness": "You've been reviewing the timeline a lot — want me to scan your notes and flag any time gaps that aren't yet covered?",
            "contradiction":  "You've been retracing your earlier path — want me to compare your notes for anything that contradicts itself?",
            "inaccuracy":     "You've been switching between views — want me to re-verify your most recent note against the underlying messages?",
        }
        return {
            "id": uuid4().hex[:10],
            "origin_event_id": evt.get("id"),
            "category": "verification",
            "subcategory": sub,
            "pattern": evt.get("pattern", "note_review"),
            "user_intent": "User behaviour suggests they may want to verify their findings.",
            "suggestion_text": text_map.get(sub, "Want me to verify your findings?"),
            "popover": {
                "level": "info",
                "title": title_map.get(sub, "Verify findings"),
                "text": text_map.get(sub, ""),
                "target": {"view": "notes", "element": None},
            },
            "note_id": None,
            "note_issue": None,
            "status": "pending",
            "timestamp": time.time(),
        }

    # ── Helpers ────────────────────────────────────────────────────────────

    def _dataset_summary(self) -> dict:
        """Cheap aggregate over the dataset for grounding the LLM."""
        dataset = self._read("dataset", []) or []
        if not dataset:
            return {}
        n = len(dataset)
        ents = Counter()
        sentiments = Counter()
        types = Counter()
        for m in dataset[:1500]:
            for e in m.get("entities", []):
                ents[e] += 1
            sentiments[m.get("sentiment", "neutral")] += 1
            types[m.get("type", "?")] += 1
        return {
            "n_messages": n,
            "by_type": dict(types),
            "by_sentiment": dict(sentiments),
            "top_entities": ents.most_common(10),
        }
