"""
ActingAgent


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


MAX_STEPS = 6                
MESSAGES_PER_READ = 8        
HIGHLIGHT_LIMIT = 25


def _parse_tool_args(raw: str) -> tuple[dict, str | None]:
    """
    Robustly parse a tool-call's `arguments` string from the LLM. Returns
    (parsed_dict, None) on success or (empty_dict, error_message) on failure.

    The error message is fed back to the LLM so it can retry with valid args
    instead of silently running the tool with `{}` and getting a confusing
    "unknown filter" downstream.
    """
    if not raw:
        return {}, None
    s = raw.strip()
    def _ok(result):
        if isinstance(result, dict):
            return result, None
        return {}, f"expected JSON object, got {type(result).__name__}"

    
    try:
        return _ok(json.loads(s))
    except json.JSONDecodeError:
        pass
    
    if s.startswith("```"):
        s2 = s.strip("`")
        if s2.lower().startswith("json"):
            s2 = s2[4:]
        s2 = s2.strip()
        try:
            return _ok(json.loads(s2))
        except json.JSONDecodeError:
            pass
    
    start = s.find("{")
    end = s.rfind("}")
    if start != -1 and end > start:
        try:
            return _ok(json.loads(s[start:end + 1]))
        except json.JSONDecodeError as exc:
            return {}, f"JSONDecodeError: {exc.msg} at pos {exc.pos}"
    return {}, "no JSON object found in tool arguments"


# ── Tool schemas ──────────────────────────────────────────────────────────────

def _tool(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }


TOOLS = [
    _tool(
        "read_data",
        "Return a small JSON summary of one of the views, optionally filtered. "
        "Use this to look at the data before deciding what to do.",
        {
            "view": {"type": "string", "enum": ["map", "timeline", "messages", "graph"]},
            "filter": {
                "type": "object",
                "description": "Optional filter: {hex_id?, entity?, keyword?, time_start?, time_end?}",
            },
        },
        ["view"],
    ),
    _tool(
        "select",
        "Select an element on a view. Writes to WorldState so all linked views "
        "update. view='map' selects a hexagon; view='graph' selects an entity.",
        {
            "view": {"type": "string", "enum": ["map", "graph"]},
            "element": {"type": "string", "description": "hex id (e.g. H05_07) or entity name"},
        },
        ["view", "element"],
    ),
    _tool(
        "filter",
        "Apply a filter to the linked views. channel='time' takes "
        "{start, end} epoch seconds; 'keyword' takes a list of strings.",
        {
            "channel": {"type": "string", "enum": ["time", "keyword"]},
            "value": {"description": "channel-specific value"},
        },
        ["channel", "value"],
    ),
    _tool(
        "highlight",
        "Flash a set of messages in the Messages view to draw the user's "
        "attention to evidence.",
        {"message_ids": {"type": "array", "items": {"type": "string"}}},
        ["message_ids"],
    ),
    _tool(
        "add_finding",
        "Append a finding to the Notes view. Use this once you have completed "
        "an analysis step worth recording.",
        {
            "title": {"type": "string"},
            "label": {"type": "string"},
            "view": {"type": "string"},
            "evidence": {"type": "array", "items": {"type": "string"}},
        },
        ["title", "label"],
    ),
    _tool(
        "reply",
        "Send a final, short confirmation back to the user. Always end with "
        "this tool — it terminates the reasoning loop.",
        {"message": {"type": "string"}},
        ["message"],
    ),
]


# ── Agent ─────────────────────────────────────────────────────────────────────

class ActingAgent(BaseAgent):

    async def run(self) -> None:
        self._subscribe("suggestion.accepted")
        self._subscribe("chat.message")
        self._busy = False  
        await asyncio.Event().wait()

    async def on_message(self, message: dict) -> None:
        topic = message.get("topic", "")
        payload = message.get("payload") or {}
        try:
            if topic == "suggestion.accepted":
                sid = payload.get("id")
                suggestion = self._find_suggestion(sid)
                if suggestion is None:
                    return
                await self._run_react(suggestion)
            elif topic == "chat.message":
                if not self._addressed_to_me(payload):
                    return
                if self._busy:
                    await self._final_reply(
                        "I'm already working on something — give me a few seconds and ask again."
                    )
                    return
                task = self._task_from_chat(payload)
                await self._run_react(task)
        except Exception as exc:
            print(f"[{self.agent_id}] ReAct error: {exc}")
            self._write("agent_status", {"state": "idle", "error": str(exc)})
            self._busy = False
            try:
                await self._final_reply(
                    f"Sorry — I hit an error while working on that: {exc}"
                )
            except Exception:
                pass

    # ── Chat addressing ────────────────────────────────────────────────────

    def _addressed_to_me(self, payload: dict) -> bool:
        """Reply when (a) `to` field targets us, or (b) text starts with @assistant / @agent."""
        if (payload.get("to") or "") == self.agent_id:
            return True
        text = (payload.get("text") or "").strip().lower()
        return text.startswith("@assistant") or text.startswith("@agent") or text.startswith("/ask")

    def _task_from_chat(self, payload: dict) -> dict:
        """Wrap a user chat message in the same shape the suggestion path uses."""
        text = (payload.get("text") or "").strip()
        # Strip the @assistant prefix if present so the model doesn't see it.
        for prefix in ("@assistant", "@agent", "/ask"):
            if text.lower().startswith(prefix):
                text = text[len(prefix):].lstrip(": ").strip()
                break
        return {
            "id": uuid4().hex[:10],
            "category": "chat",
            "subcategory": "user_question",
            "pattern": "direct_chat",
            "user_intent": "User asked a direct question or gave a direct instruction in chat.",
            "suggestion_text": text or "(empty question)",
            "_via_chat": True,
            "_from": payload.get("from", ""),
        }

    # ── ReAct loop ─────────────────────────────────────────────────────────

    async def _run_react(self, suggestion: dict) -> None:
        sid = suggestion.get("id")
        via_chat = bool(suggestion.get("_via_chat"))
        client = get_client()
        self._busy = True

        if not via_chat:
            self._mark_suggestion(sid, "acting")
        self._write("agent_trace", [])
        self._write("agent_status", {
            "state": "thinking",
            "target_suggestion_id": sid,
            "started_at": time.time(),
            "via_chat": via_chat,
        })

        if not client.available:
            try:
                await self._react_fallback(suggestion)
            finally:
                self._busy = False
            return

        system = self._build_system_prompt()
        user = self._build_user_prompt(suggestion)
        messages: list[dict] = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

        for step_idx in range(MAX_STEPS):
            try:
                response = await asyncio.to_thread(
                    client.chat,
                    system="", user="",
                    messages=messages,
                    model=client.reasoning_model,
                    temperature=0.2,
                    tools=TOOLS,
                    tool_choice="auto",
                )
            except LLMUnavailable:
                await self._react_fallback(suggestion)
                return
            except Exception as exc:
                print(f"[{self.agent_id}] LLM error: {exc}")
                await self._append_trace({
                    "step": step_idx, "thought": f"LLM error: {exc}",
                    "action": None, "action_args": None,
                    "observation": "aborting",
                })
                break

            msg = response.choices[0].message
            messages.append(msg.model_dump() if hasattr(msg, "model_dump") else dict(msg))

            thought = (msg.content or "").strip()
            tool_calls = getattr(msg, "tool_calls", None) or []

            
            if not tool_calls:
                final = thought or "Done."
                await self._append_trace({
                    "step": step_idx, "thought": thought, "action": "reply",
                    "action_args": {"message": final},
                    "observation": "(end)",
                })
                await self._final_reply(final)
                break

            
            terminated = False
            for tc in tool_calls:
                fn = tc.function.name
                raw_args = tc.function.arguments or "{}"
                args, parse_err = _parse_tool_args(raw_args)
                if parse_err:
                    
                    print(f"[{self.agent_id}] tool {fn!r} arg parse error: {parse_err}; raw={raw_args[:120]!r}", flush=True)
                    obs = (
                        f"ERROR: arguments to `{fn}` were not valid JSON ({parse_err}). "
                        f"Got: {raw_args[:200]}. Please retry with valid JSON arguments."
                    )
                    finished = False
                else:
                    obs, finished = await self._execute_tool(fn, args)

                await self._append_trace({
                    "step": step_idx,
                    "thought": thought if thought else None,
                    "action": fn,
                    "action_args": args,
                    "observation": obs,
                })
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": obs[:1500],
                })
                if finished:
                    terminated = True
            if terminated:
                break

        if not via_chat:
            self._mark_suggestion(sid, "completed")
        self._write("agent_status", {"state": "idle"})
        self._busy = False

    async def _react_fallback(self, suggestion: dict) -> None:
        """
        Deterministic fallback when no LLM is configured. Mirrors enough of
        the ReAct shape (thought → action → observation → reply) for the
        Chat View to render a coherent demo.
        """
        category = suggestion.get("category", "exploration")
        sid = suggestion.get("id")

        await self._append_trace({
            "step": 0,
            "thought": (
                "(LLM unavailable — running scripted plan based on the help-needed pattern.)"
            ),
            "action": "read_data",
            "action_args": {"view": self._read("focused_view", "messages") or "messages"},
            "observation": json.dumps(self._summarise_messages_view({}))[:400],
        })

        if category == "verification":
            note_id = suggestion.get("note_id")
            issue = suggestion.get("note_issue") or {}
            if note_id:
                await self._publish("chat.message", self._chat_payload(
                    f"I flagged a {issue.get('type','possible issue')} on your note: {issue.get('comment','')}",
                ))
            self._mark_suggestion(sid, "completed")
            self._write("agent_status", {"state": "idle"})
            return

        
        dataset = self._read("dataset", []) or []
        ents = Counter()
        for m in dataset:
            for e in m.get("entities", []):
                ents[e] += 1
        top_entity = ents.most_common(1)[0][0] if ents else None
        if top_entity:
            ids = [m["id"] for m in dataset if top_entity in m.get("entities", [])][:HIGHLIGHT_LIMIT]
            self._write("highlighted_message_ids", ids)
            self._write("selected_entity", top_entity)
            await self._append_trace({
                "step": 1,
                "thought": f"The most active entity is '{top_entity}' — surface those messages.",
                "action": "highlight",
                "action_args": {"message_ids": ids},
                "observation": f"Highlighted {len(ids)} messages mentioning {top_entity}.",
            })
        await self._final_reply(
            f"I highlighted activity related to {top_entity!r}. "
            "Open the Messages view to follow up." if top_entity
            else "I scanned the dataset; nothing notable to highlight.",
        )
        self._mark_suggestion(sid, "completed")
        self._write("agent_status", {"state": "idle"})

    # ── Tool execution ─────────────────────────────────────────────────────

    async def _execute_tool(self, name: str, args: dict) -> tuple[str, bool]:
        if name == "read_data":
            view = args.get("view", "messages")
            filt = args.get("filter") or {}
            data = self._summarise_view(view, filt)
            return json.dumps(data, default=str)[:1400], False

        if name == "select":
            view = args.get("view")
            element = args.get("element")
            if view == "map" and element:
                self._write("selected_hex", str(element))
                return f"selected hex {element}", False
            if view == "graph" and element:
                self._write("selected_entity", str(element))
                return f"selected entity {element}", False
            return f"unknown select target {view}/{element}", False

        if name == "filter":
            channel = args.get("channel")
            value = args.get("value")
            if channel == "time" and isinstance(value, dict):
                start = value.get("start"); end = value.get("end")
                if start is not None and end is not None:
                    self._write("time_range", {"start": float(start), "end": float(end)})
                    return f"time range set to [{start}, {end}]", False
            if channel == "keyword":
                kws = value if isinstance(value, list) else [str(value)]
                self._write("keyword_filter", [str(k) for k in kws])
                return f"keyword filter set to {kws}", False
            return f"unknown filter {channel}={value}", False

        if name == "highlight":
            ids = args.get("message_ids") or []
            ids = [str(x) for x in ids][:HIGHLIGHT_LIMIT]
            self._write("highlighted_message_ids", ids)
            return f"highlighted {len(ids)} messages", False

        if name == "add_finding":
            title = args.get("title", "Finding")
            label = args.get("label", "")
            view = args.get("view", self._read("focused_view", "messages") or "messages")
            evidence = args.get("evidence") or []
            note = {
                "id": f"note_{uuid4().hex[:8]}",
                "by": self.agent_id,
                "title": str(title),
                "label": str(label),
                "view": str(view),
                "screenshot": None,
                "evidence": [str(e) for e in evidence],
                "comments": [],
                "timestamp": time.time(),
            }
            notes = list(self._read("notes", []) or [])
            notes.append(note)
            self._write("notes", notes)
            return f"added finding {note['id']}: {title}", False

        if name == "reply":
            message = str(args.get("message", "Done."))
            await self._final_reply(message)
            return "(end)", True

        return f"unknown tool {name}", False

    # ── Read helpers ───────────────────────────────────────────────────────

    def _summarise_view(self, view: str, filt: dict) -> dict:
        if view == "map":
            return self._summarise_map_view(filt)
        if view == "timeline":
            return self._summarise_timeline_view(filt)
        if view == "messages":
            return self._summarise_messages_view(filt)
        if view == "graph":
            return self._summarise_graph_view(filt)
        return {"error": f"unknown view {view}"}

    def _filtered_messages(self, filt: dict) -> list[dict]:
        dataset = self._read("dataset", []) or []
        msgs = dataset
        hex_id = filt.get("hex_id") or self._read("selected_hex")
        if hex_id:
            msgs = [m for m in msgs if m.get("hex_id") == hex_id]
        entity = filt.get("entity") or self._read("selected_entity")
        if entity:
            msgs = [m for m in msgs if entity in (m.get("entities") or [])]
        keyword = filt.get("keyword")
        if keyword:
            kws = [keyword] if isinstance(keyword, str) else list(keyword)
            kws = [k.lower() for k in kws]
            msgs = [m for m in msgs if any(k in (m.get("message") or "").lower() for k in kws)]
        ts = filt.get("time_start"); te = filt.get("time_end")
        rng = self._read("time_range")
        if ts is None and rng: ts = rng.get("start")
        if te is None and rng: te = rng.get("end")
        if ts is not None:
            msgs = [m for m in msgs if (m.get("epoch") or 0) >= ts]
        if te is not None:
            msgs = [m for m in msgs if (m.get("epoch") or 0) <= te]
        return msgs

    def _summarise_map_view(self, filt: dict) -> dict:
        msgs = self._filtered_messages(filt)
        hex_counts = Counter(m.get("hex_id") for m in msgs if m.get("hex_id"))
        return {
            "n_messages": len(msgs),
            "top_hexes": hex_counts.most_common(8),
            "n_geotagged": sum(1 for m in msgs if m.get("hex_id")),
        }

    def _summarise_timeline_view(self, filt: dict) -> dict:
        msgs = self._filtered_messages(filt)
        # 10-minute buckets
        buckets: Counter = Counter()
        for m in msgs:
            ep = m.get("epoch")
            if ep is None:
                continue
            buckets[int(ep // 600) * 600] += 1
        timeline = [{"t": k, "n": v} for k, v in sorted(buckets.items())]
        return {"n_messages": len(msgs), "buckets_10min": timeline[:36]}

    def _summarise_messages_view(self, filt: dict) -> dict:
        msgs = self._filtered_messages(filt)
        sample = msgs[: MESSAGES_PER_READ]
        return {
            "n_messages": len(msgs),
            "sentiment": Counter(m.get("sentiment", "neutral") for m in msgs),
            "sample": [
                {
                    "id": m.get("id"),
                    "timestamp": m.get("timestamp"),
                    "author": m.get("author"),
                    "message": (m.get("message") or "")[:240],
                    "entities": m.get("entities", []),
                    "location": m.get("location"),
                }
                for m in sample
            ],
        }

    def _summarise_graph_view(self, filt: dict) -> dict:
        msgs = self._filtered_messages(filt)
        ents = Counter()
        cooc: Counter = Counter()
        for m in msgs:
            es = m.get("entities") or []
            for e in es:
                ents[e] += 1
            for i in range(len(es)):
                for j in range(i + 1, len(es)):
                    a, b = sorted((es[i], es[j]))
                    cooc[(a, b)] += 1
        return {
            "n_messages": len(msgs),
            "top_entities": ents.most_common(10),
            "top_pairs": [
                {"a": a, "b": b, "count": n}
                for (a, b), n in cooc.most_common(10)
            ],
        }

    # ── Trace + chat helpers ───────────────────────────────────────────────

    async def _append_trace(self, step: dict) -> None:
        step = {**step, "timestamp": time.time()}
        trace = list(self._read("agent_trace", []) or [])
        trace.append(step)
        self._write("agent_trace", trace)
        await self._publish("agent.trace", step)

    async def _final_reply(self, text: str) -> None:
        await self._publish("chat.message", self._chat_payload(text))

    def _chat_payload(self, text: str) -> dict:
        return {
            "from": self.agent_id,
            "from_display": "Assistant",
            "from_role": "agent",
            "to": "broadcast",
            "text": text,
            "timestamp": time.time(),
        }

    # ── Suggestion bookkeeping ─────────────────────────────────────────────

    def _find_suggestion(self, sid: str | None) -> dict | None:
        if not sid:
            return None
        for s in self._read("pending_suggestions", []) or []:
            if s.get("id") == sid:
                return s
        return None

    def _mark_suggestion(self, sid: str | None, status: str) -> None:
        if not sid:
            return
        suggestions = list(self._read("pending_suggestions", []) or [])
        for s in suggestions:
            if s.get("id") == sid:
                s["status"] = status
        self._write("pending_suggestions", suggestions)

    # ── Prompts ────────────────────────────────────────────────────────────

    def _build_system_prompt(self) -> str:
        knowledge = self._read("knowledge", {}) or {}
        ops = "\n".join(f"  - {o['name']}: {o['description']}"
                        for o in (knowledge.get("available_operations") or []))
        return (
            "You are the reasoning + acting stage of a proactive UI agent for the "
            "VAST 2021 MC3 public-safety event-analysis system. "
            "You operate the visual analytics interface on the user's behalf "
            "after they accepted a suggestion.\n\n"
            "Follow ReAct: produce a short `thought` (in plain content), then "
            "call ONE tool. The tool result is shown to you and you continue. "
            "Stop when you have enough; ALWAYS end the loop with the `reply` "
            "tool. Keep the loop short — typically 2 to 5 steps.\n\n"
            f"System overview:\n{knowledge.get('system_introduction', '')}\n\n"
            f"Available operations:\n{ops}\n\n"
            "Be concise. Highlight evidence so the user can see the basis for "
            "your reasoning. Add a finding only when you have a clear answer."
        )

    def _build_user_prompt(self, suggestion: dict) -> str:
        focused = self._read("focused_view")
        selected_hex = self._read("selected_hex")
        selected_entity = self._read("selected_entity")
        time_range = self._read("time_range")
        keyword_filter = self._read("keyword_filter", []) or []
        via_chat = bool(suggestion.get("_via_chat"))
        if via_chat:
            header = (
                f'The user asked you in chat: "{suggestion.get("suggestion_text", "")}". '
                "Decide whether to (a) just answer in plain language with `reply`, "
                "or (b) carry out an action (filter / select / highlight / add_finding) "
                "and then `reply` with what you did. Prefer (a) for descriptive questions "
                "(\"what is the most active area?\") and (b) for instructions "
                "(\"filter to fire-related messages\")."
            )
        else:
            header = (
                "The user accepted this suggestion:\n"
                + json.dumps({k: suggestion.get(k) for k in
                              ("category", "subcategory", "pattern",
                               "user_intent", "suggestion_text")}, indent=2)
                + "\n\nTake the user through the analysis: read what's relevant, "
                  "apply a selection or filter, highlight evidence, optionally "
                  "add a finding to the Notes view, then call `reply`."
            )
        return "\n".join([
            header, "",
            f"Focused view: {focused}",
            f"selected_hex: {selected_hex}",
            f"selected_entity: {selected_entity}",
            f"time_range: {time_range}",
            f"keyword_filter: {keyword_filter}",
        ])
