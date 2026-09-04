"""
MC3Gateway — ProactiveVA WebSocket bridge for the VAST 2021 MC3 system.


"""
from __future__ import annotations

import asyncio
import time
from typing import Any
from uuid import uuid4

from mivais.gateway import Gateway



INTERACTION_LOG_LIMIT = 200


class MC3Gateway(Gateway):
    """ProactiveVA gateway. Subclass of mivais.Gateway."""

    
    _broadcast_exclude_keys = frozenset({"dataset", "hexgrid", "streets", "interaction_log"})

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        
        self._last_interaction_at: dict[str, float] = {}

    async def _on_state_changed(self, key: str, _value: object) -> None:
        """
        Override the base broadcast so we can (a) log unexpected failures and
        (b) include a `_changed_key` hint so the frontend can flash the
        update if it wants to.
        """
        
        if key in self._broadcast_exclude_keys:
            return
        import json as _json
        snapshot = self._ws.snapshot()
        snapshot_safe = {k: v for k, v in snapshot.items() if k not in self._broadcast_exclude_keys}
        audit_tail = self._audit.get_entries(limit=60)
        message = _json.dumps({
            "type": "state_update",
            "world_state": snapshot_safe,
            "audit_log": audit_tail,
            "cursors": self._cursors,
            "connected_users": self._presence_list(),
            "online_agents": self._online_agents,
            "_changed_key": key,
        }, default=str)

        dead: list[str] = []
        for sid, ws in list(self._connections.items()):
            try:
                await ws.send_text(message)
            except Exception as exc:
                print(f"[gateway/broadcast] send to {sid} failed on key={key!r}: {type(exc).__name__}: {exc}", flush=True)
                dead.append(sid)
        for sid in dead:
            self._cleanup_session(sid)

    async def _push_to(self, session_id: str, msg_type: str = "state_update") -> None:
        """
        Override the base implementation so even initial_state excludes the
        large static keys. The frontend fetches dataset / hexgrid / streets
        via REST instead, keeping WebSocket frames well under 1 MB.
        """
        ws = self._connections.get(session_id)
        if ws is None:
            return
        snapshot = self._ws.snapshot()
        snapshot = {k: v for k, v in snapshot.items() if k not in self._broadcast_exclude_keys}
        audit_tail = self._audit.get_entries(limit=60)
        import json as _json
        payload: dict = {
            "type": msg_type,
            "world_state": snapshot,
            "audit_log": audit_tail,
            "cursors": self._cursors,
            "connected_users": self._presence_list(),
        }
        if msg_type == "initial_state":
            role = self._roles.get(session_id, "")
            cfg = self._user_configs.get(role, {})
            payload["my_permissions"] = {
                "role": role,
                "can_write": cfg.get("can_write", []),
                "bus_publish_topics": cfg.get("bus_publish_topics", []),
            }
            payload["chat_history"]  = self._chat_history[-50:]
            payload["online_agents"] = self._online_agents
        try:
            await ws.send_text(_json.dumps(payload, default=str))
        except Exception:
            self._cleanup_session(session_id)

    # ── Action dispatch ──────────────────────────────────────────────────────

    async def _handle_action(self, agent_id: str, session_id: str, data: dict) -> None:
        action = (data.get("action") or "").strip()
        if not action:
            return

        

        if action == "set_focus_view":
            view = str(data.get("view", "")).strip()
            if view in {"map", "timeline", "messages", "graph", "notes", "chat"}:
                self._ws.write(agent_id, "focused_view", view)
            element = view
            self._record_interaction(agent_id, "focus", view, element, {"view": view})

        elif action == "select_hexagon":
            hex_id = data.get("hex_id")
            current = self._ws.get("selected_hex")
            new = None if hex_id == current else hex_id  # toggle off if re-clicked
            self._ws.write(agent_id, "selected_hex", new)
            self._record_interaction(
                agent_id, "select", "map",
                element=str(hex_id),
                data_={"hex_id": hex_id, "deselected": new is None},
            )

        elif action == "set_time_range":
            start = data.get("start")
            end = data.get("end")
            if start is None or end is None:
                self._ws.write(agent_id, "time_range", None)
            else:
                self._ws.write(agent_id, "time_range", {"start": float(start), "end": float(end)})
            self._record_interaction(
                agent_id, "brush", "timeline",
                element="time_range",
                data_={"start": start, "end": end},
            )

        elif action == "select_message":
            
            mid = str(data.get("message_id", "")).strip()
            if mid:
                staged = list(self._ws.get("staged_evidence") or [])
                if mid in staged:
                    staged.remove(mid)
                    op = "unstage"
                else:
                    if len(staged) < 50:
                        staged.append(mid)
                    op = "stage"
                self._ws.write(agent_id, "staged_evidence", staged)
                self._record_interaction(
                    agent_id, "click", "messages",
                    element=mid,
                    data_={"message_id": mid, "op": op, "n_staged": len(staged)},
                )

        elif action == "clear_staged_evidence":
            self._ws.write(agent_id, "staged_evidence", [])
            self._record_interaction(agent_id, "click", "messages", element="clear_staged", data_={})

        elif action == "hover_message":
            mid = str(data.get("message_id", "")).strip()
            if mid:
                self._record_interaction(agent_id, "hover", "messages", element=mid, data_={"message_id": mid})

        elif action == "select_entity":
            entity = data.get("entity")
            current = self._ws.get("selected_entity")
            new = None if entity == current else entity
            self._ws.write(agent_id, "selected_entity", new)
            self._record_interaction(
                agent_id, "select", "graph",
                element=str(entity),
                data_={"entity": entity, "deselected": new is None},
            )

        elif action == "set_keyword_filter":
            keywords = data.get("keywords") or []
            if isinstance(keywords, list):
                clean = [str(k).strip() for k in keywords if str(k).strip()]
                self._ws.write(agent_id, "keyword_filter", clean)
                self._record_interaction(
                    agent_id, "filter", "messages",
                    element="keyword",
                    data_={"keywords": clean},
                )

        # ── Notes ───────────────────────────────────────────────────────────

        elif action == "add_note":
            
            client_evidence = data.get("evidence") or []
            staged = list(self._ws.get("staged_evidence") or [])
            highlighted = list(self._ws.get("highlighted_message_ids") or [])
            if client_evidence:
                evidence = [str(x) for x in client_evidence]
            elif staged:
                evidence = staged[:50]
            else:
                evidence = highlighted[:50]
            patched = dict(data)
            patched["evidence"] = evidence
            note = self._build_note(agent_id, patched, by=agent_id)
            notes = list(self._ws.get("notes") or [])
            notes.append(note)
            self._ws.write(agent_id, "notes", notes)
           
            if staged:
                self._ws.write(agent_id, "staged_evidence", [])
            self._record_interaction(
                agent_id, "note", "notes",
                element=note["id"],
                data_={"title": note.get("title", ""), "label": note.get("label", ""),
                       "n_evidence": len(evidence)},
            )

        elif action == "update_note":
            note_id = data.get("id")
            patch = {k: v for k, v in data.items() if k not in {"action", "id"}}
            notes = list(self._ws.get("notes") or [])
            for n in notes:
                if n.get("id") == note_id:
                    n.update({k: v for k, v in patch.items() if k in {"title", "label", "view"}})
                    break
            self._ws.write(agent_id, "notes", notes)
            self._record_interaction(agent_id, "note_update", "notes", element=str(note_id), data_=patch)

        elif action == "delete_note":
            note_id = data.get("id")
            notes = [n for n in (self._ws.get("notes") or []) if n.get("id") != note_id]
            self._ws.write(agent_id, "notes", notes)
            self._record_interaction(agent_id, "note_delete", "notes", element=str(note_id), data_={})

        elif action == "highlight_messages":
            ids = data.get("message_ids") or []
            if isinstance(ids, list):
                clean = [str(x) for x in ids if x][:50]
                self._ws.write(agent_id, "highlighted_message_ids", clean)
                self._record_interaction(
                    agent_id, "highlight", "messages",
                    element="evidence",
                    data_={"count": len(clean)},
                )

        # ── Suggestion responses ────────────────────────────────────────────

        elif action == "accept_suggestion":
            sid = data.get("id")
            self._mark_suggestion_status(agent_id, sid, "accepted")
            await self._bus.publish(agent_id, "suggestion.accepted", {"id": sid})
            self._record_interaction(agent_id, "accept", "chat", element=str(sid), data_={"id": sid})

        elif action == "reject_suggestion":
            sid = data.get("id")
            self._mark_suggestion_status(agent_id, sid, "rejected")
            await self._bus.publish(agent_id, "suggestion.rejected", {"id": sid})
            self._record_interaction(agent_id, "reject", "chat", element=str(sid), data_={"id": sid})

        elif action == "dismiss_suggestion":
            sid = data.get("id")
            self._mark_suggestion_status(agent_id, sid, "dismissed")
            self._record_interaction(agent_id, "dismiss", "chat", element=str(sid), data_={"id": sid})

        # ── Controls ────────────────────────────────────────────────────────

        elif action == "set_threshold":
            secs = float(data.get("seconds", 3.0))
            secs = max(0.5, min(10.0, secs))
            self._ws.write(agent_id, "think_time_threshold_s", secs)
            self._record_interaction(agent_id, "config", "controls", element="threshold", data_={"seconds": secs})

        elif action == "set_toggle":
            name = str(data.get("name", "")).strip()
            value = bool(data.get("value", False))
            mapping = {
                "onboarding": "onboarding_enabled",
                "exploration": "exploration_enabled",
                "verification": "verification_enabled",
            }
            key = mapping.get(name)
            if key:
                self._ws.write(agent_id, key, value)
                self._record_interaction(agent_id, "config", "controls", element=name, data_={"name": name, "value": value})

        # ── Scroll / generic ────────────────────────────────────────────────

        elif action == "scroll_messages":
            top = data.get("top", 0)
            self._record_interaction(agent_id, "scroll", "messages", element="list", data_={"top": top})

    # ── Note helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def _build_note(agent_id: str, data: dict, by: str) -> dict:
        hex_id = data.get("hex_id")
        return {
            "id": data.get("id") or f"note_{uuid4().hex[:8]}",
            "by": by,
            "title": str(data.get("title", "")).strip() or "Finding",
            "label": str(data.get("label", "")).strip(),
            "view": str(data.get("view", "")).strip() or "messages",
            "hex_id": str(hex_id) if hex_id else None,    # pin to a map hex if created from map
            "screenshot": data.get("screenshot"),         # data URL or null
            "evidence": data.get("evidence") or [],
            "comments": [],
            "timestamp": time.time(),
        }

    def _mark_suggestion_status(self, agent_id: str, sid: str | None, status: str) -> None:
        if not sid:
            return
        suggestions = list(self._ws.get("pending_suggestions") or [])
        for s in suggestions:
            if s.get("id") == sid:
                s["status"] = status
        self._ws.write(agent_id, "pending_suggestions", suggestions)

    # ── Interaction recording ────────────────────────────────────────────────

    def _record_interaction(
        self,
        agent_id: str,
        action_type: str,
        view: str,
        element: str | None,
        data_: dict | None,
    ) -> None:
        
        now = time.time()
        prev = self._last_interaction_at.get(agent_id)
        think_time = (now - prev) if prev is not None else 0.0
        self._last_interaction_at[agent_id] = now

        event = {
            "id": uuid4().hex[:12],
            "actor": agent_id,
            "actionType": action_type,
            "view": view,
            "element": element,
            "data": data_ or {},
            "clickTime": now,
            "thinkTime": round(think_time, 3),
        }

        log = list(self._ws.get("interaction_log") or [])
        log.append(event)
        if len(log) > INTERACTION_LOG_LIMIT:
            log = log[-INTERACTION_LOG_LIMIT:]
        
        self._ws.system_write("interaction_log", log)

        
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._bus.publish("gateway", "interaction.event", event))
        except RuntimeError:
            pass
