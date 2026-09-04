"""
VerificationDetector 
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import asdict
from typing import Any
from uuid import uuid4

from mivais.base_agent import BaseAgent
from interaction_features import extract_features
from llm_client import LLMUnavailable, get_client



MAX_EVIDENCE_MESSAGES = 12


BEHAVIOURAL_PATTERNS = (
    "review_timeline_repeatedly",       
    "explore_previous_path_repeatedly", 
    "switch_views_slowly",              
)
BEHAVIOURAL_COOLDOWN_S = 18.0


class VerificationDetector(BaseAgent):

    async def run(self) -> None:
        self._seen_note_ids: set[str] = set()
        self._note_signatures: dict[str, str] = {}  
        self._last_fired: dict[str, float] = {}     
        self._last_behavioural: dict[str, float] = {}  
        
        self._ws.watch("notes", self._on_notes_changed)
        self._subscribe("interaction.event")
        await asyncio.Event().wait()

    # ── Behavioural path ────────────────────────────────

    async def on_message(self, message: dict) -> None:
        payload = message.get("payload") or {}
        actor = payload.get("actor")
        if not actor or not actor.startswith("user:"):
            return
        if not bool(self._read("verification_enabled", True)):
            return
        
        notes = self._read("notes", []) or []
        if not notes:
            return

        threshold = float(self._read("think_time_threshold_s", 3.0) or 3.0)
        log = self._read("interaction_log", []) or []
        feats = extract_features(log, actor=actor, threshold_s=threshold)
        match = next((p for p in feats.pattern_hints if p in BEHAVIOURAL_PATTERNS), None)
        if not match:
            return

        now = time.time()
        if now - self._last_behavioural.get(actor, 0.0) < BEHAVIOURAL_COOLDOWN_S:
            return
        self._last_behavioural[actor] = now

        
        sub = {
            "review_timeline_repeatedly":       "incompleteness",
            "explore_previous_path_repeatedly": "contradiction",
            "switch_views_slowly":              "inaccuracy",
        }[match]

        evt = {
            "id": uuid4().hex[:10],
            "actor": actor,
            "category": "verification",
            "subcategory": sub,
            "pattern": match,
            "evidence_summary": (
                "User behaviour suggests they may be checking their findings. "
                "Offer to cross-check the existing notes against the data."
            ),
            "confidence": 0.6,
            "features": asdict(feats),
            "detected_at": now,
            "detector": self.agent_id,
            "_via_behaviour": True,   
        }
        await self._publish("help_needed.event", evt)

    # ── Watch ──────────────────────────────────────────────────────────────

    async def _on_notes_changed(self, key: str, value: Any) -> None:
        """
        Fire-and-forget: start verification work as a background task so the
        gateway's broadcast (which runs *after* this watcher in the _notify
        chain) fires immediately. Otherwise the user would not see their own
        note until the verification LLM call returned.
        """
        if not bool(self._read("verification_enabled", True)):
            return

        notes = list(value or [])
        for note in notes:
            note_id = note.get("id")
            if not note_id:
                continue
            sig = f"{note.get('title','')}|{note.get('label','')}|{len(note.get('evidence') or [])}"
            if self._note_signatures.get(note_id) == sig:
                continue
            self._note_signatures[note_id] = sig

            if not str(note.get("by", "")).startswith("user:"):
                continue

            now = time.time()
            if now - self._last_fired.get(note_id, 0.0) < 8.0:
                continue
            self._last_fired[note_id] = now

            # Detach the verification work so this watcher returns instantly.
            asyncio.create_task(self._verify_safe(note, notes))

    async def _verify_safe(self, note: dict, notes: list[dict]) -> None:
        try:
            await self._verify(note, notes)
        except Exception as exc:
            print(f"[{self.agent_id}] verification error on {note.get('id')}: {exc}")

    # ── Verification ───────────────────────────────────────────────────────

    async def _verify(self, note: dict, all_notes: list[dict]) -> None:
        dataset = self._read("dataset", []) or []
        knowledge = self._read("knowledge", {}) or {}

        evidence_ids = list(note.get("evidence") or [])
        evidence: list[dict] = []
        if evidence_ids:
            id_set = set(evidence_ids)
            evidence = [m for m in dataset if m.get("id") in id_set][:MAX_EVIDENCE_MESSAGES]
        else:
            
            evidence = self._retrieve_evidence_by_keyword(note, dataset)
        print(f"[verification] note={note.get('title')!r} evidence={len(evidence)}", flush=True)

        other_notes = [
            {"id": n.get("id"), "title": n.get("title", ""), "label": n.get("label", "")}
            for n in all_notes if n.get("id") != note.get("id")
        ]

        issues = await self._call_llm(note, evidence, other_notes, knowledge)
        if not issues:
            issues = self._heuristic(note, evidence, other_notes)
        if not issues:
            return
        print(f"[verification] {len(issues)} issue(s) on note={note.get('title')!r}", flush=True)

        
        for issue in issues:
            event = {
                "id": uuid4().hex[:10],
                "actor": note.get("by"),
                "category": "verification",
                "subcategory": issue.get("type", "factual_error"),
                "pattern": "note_review",
                "evidence_summary": issue.get("comment", ""),
                "confidence": float(issue.get("confidence", 0.7) or 0.7),
                "note_id": note.get("id"),
                "issue": issue,
                "detected_at": time.time(),
                "detector": self.agent_id,
            }
            await self._publish("help_needed.event", event)
            await self._publish("note.commented", {
                "note_id": note.get("id"),
                "type": issue.get("type"),
                "comment": issue.get("comment"),
                "correction": issue.get("correction"),
                "keywords": issue.get("keywords") or [],
                "confidence": event["confidence"],
                "timestamp": time.time(),
            })

    # ── LLM call ───────────────────────────────────────────────────────────

    async def _call_llm(
        self,
        note: dict,
        evidence: list[dict],
        other_notes: list[dict],
        knowledge: dict,
    ) -> list[dict]:
        client = get_client()
        if not client.available:
            return []

        compact_evidence = [
            {
                "id": m.get("id"),
                "type": m.get("type"),
                "timestamp": m.get("timestamp"),
                "author": m.get("author"),
                "message": m.get("message"),
                "location": m.get("location"),
                "entities": m.get("entities", []),
            }
            for m in evidence
        ]

        system = (
            "You are a verification agent inside ProactiveVA. The analyst has "
            "just submitted or edited a note about a public-safety event. Cross-"
            "check the note against the cited messages and the analyst's other "
            "notes. Identify problems of three types only:\n"
            "  factual_error — the note's claim contradicts the cited messages "
            "(e.g. wrong time, wrong location, wrong entity).\n"
            "  conflict      — the note contradicts another note the analyst "
            "submitted earlier.\n"
            "  omission      — the cited messages mention an important detail "
            "(time, location, person) the note leaves out.\n\n"
            "If the note is fine, return an empty list. Be conservative.\n"
            "Respond ONLY with JSON: {\"issues\": [...]} where each issue is\n"
            "{type, comment, correction, keywords, confidence}.\n"
            "  type:       factual_error | conflict | omission\n"
            "  comment:    short explanation for the analyst\n"
            "  correction: a corrected wording, or null\n"
            "  keywords:   words from the note's text to highlight\n"
            "  confidence: 0..1"
        )
        user = (
            "Task: " + (knowledge.get("task") or "") + "\n\n"
            "Note under review:\n"
            f"{json.dumps({k: note.get(k) for k in ('title','label','view','evidence')}, indent=2)}\n\n"
            f"Cited messages ({len(compact_evidence)}):\n"
            f"{json.dumps(compact_evidence, indent=2)}\n\n"
            f"Other notes:\n{json.dumps(other_notes, indent=2)}"
        )
        try:
            data = await asyncio.to_thread(
                client.chat_json,
                system=system, user=user, model=client.perception_model,
            )
            issues = data.get("issues") or []
            return [i for i in issues if isinstance(i, dict)]
        except LLMUnavailable:
            return []
        except Exception as exc:
            print(f"[{self.agent_id}] LLM error: {exc}")
            return []

    # ── Keyword-based evidence retrieval ───────────────────────────────────

    @staticmethod
    def _retrieve_evidence_by_keyword(note: dict, dataset: list[dict]) -> list[dict]:
        """
        When the analyst writes a note without staging evidence, fall back to
        fetching messages whose text mentions any salient keyword from the
        note's title or label. Common stop-words are skipped. Limited to
        MAX_EVIDENCE_MESSAGES, sorted by timestamp so the LLM can reason
        chronologically.
        """
        import re
        stop = {
            "the","a","an","and","or","but","to","of","in","on","at","for","is","are","was","were","be",
            "this","that","these","those","it","its","i","im","me","my","you","your","we","us","our","they",
            "as","if","have","has","had","with","near","reported","around","about",
            "people","person","time","note","event","incident",
        }
        text = (note.get("title", "") + " " + note.get("label", "")).lower()
        tokens = re.findall(r"[a-z']{3,}", text)
        keywords = [t for t in tokens if t not in stop]
        if not keywords:
            return dataset[-MAX_EVIDENCE_MESSAGES:]
        kws_set = set(keywords)
        
        scored = []
        for m in dataset:
            msg = (m.get("message") or "").lower()
            hits = sum(1 for kw in kws_set if kw in msg)
            if hits:
                scored.append((hits, m))
        scored.sort(key=lambda p: (-p[0], p[1].get("epoch") or 0))
        evidence = [m for _, m in scored[:MAX_EVIDENCE_MESSAGES]]
        evidence.sort(key=lambda m: m.get("epoch") or 0)
        return evidence

    # ── Heuristic fallback ─────────────────────────────────────────────────

    def _heuristic(
        self,
        note: dict,
        evidence: list[dict],
        other_notes: list[dict],
    ) -> list[dict]:
        """Cheap heuristic checks used when the LLM is unavailable."""
        issues: list[dict] = []

        title = (note.get("title") or "").lower()
        label = (note.get("label") or "").lower()
        if not (title or label):
            return issues

        
        for other in other_notes:
            other_t = (other.get("title") or "").lower()
            if other_t and other_t == title and (other.get("label") or "").lower() != label:
                issues.append({
                    "type": "conflict",
                    "comment": f"Another note already has the title '{note.get('title')}' but a different label.",
                    "correction": None,
                    "keywords": [w for w in title.split() if len(w) > 3][:3],
                    "confidence": 0.55,
                })
                break

        if evidence and ("time" not in label and "at " not in label):
            ts_seen = sorted(m.get("timestamp", "") for m in evidence if m.get("timestamp"))
            if ts_seen and len(ts_seen) >= 3:
                issues.append({
                    "type": "omission",
                    "comment": "The cited messages span a noticeable time range but the note does not mention a time.",
                    "correction": None,
                    "keywords": [w for w in label.split() if len(w) > 3][:3],
                    "confidence": 0.5,
                })
        return issues
