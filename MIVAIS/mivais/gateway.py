"""
Gateway — WebSocket bridge between the MIVAIS infrastructure and frontend clients.

The Gateway:
  1. Maintains active WebSocket connections
  2. Registers each connected user as a proper agent in AgentRegistry with
     declared permissions — user actions go through PermissionGuard
  3. Subscribes to WorldState.watch_any() — pushes full snapshot + audit tail
     to all connected clients on every state write
  4. Routes incoming user actions to WorldState.write() — permission-checked
     and audit-logged
  5. Tracks cursor and drag state per user in-memory (not in WorldState)
  6. Broadcasts presence (connected_users) and cursors with every push
  7. Acts as a MessageBus bridge:
       - System-level subscription to "chat.message" → routes to connected clients
       - Per-user subscriptions based on role's bus_subscribe_topics → delivers
         bus messages directly to each user's WebSocket
  8. Never calls agent instances directly

Domain-specific actions:
  Override _handle_action() in a subclass to add application-specific
  WebSocket message handling. Built-in actions are always available.

Excluding large keys from broadcasts:
  Set _broadcast_exclude_keys on the class or instance to prevent large,
  rarely-changing values (such as a full dataset) from being re-sent on
  every state update. These keys are still sent in the initial_state message.

  Example:
      class MyGateway(Gateway):
          _broadcast_exclude_keys = frozenset({"dataset", "raw_corpus"})

          async def _handle_action(self, agent_id, session_id, data):
              action = data.get("action")
              if action == "submit_ranking":
                  self._ws.write(agent_id, "user_ranking", data.get("ranking", []))
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from fastapi import WebSocket

from .agent_registry import AgentCapabilities
from .session_recorder import SessionRecorder
from .config import MivaisConfig

if TYPE_CHECKING:
    from .world_state import WorldState
    from .audit_log import AuditLog
    from .agent_registry import AgentRegistry
    from .message_bus import MessageBus


class Gateway:
    """
    WebSocket bridge.

    Typical lifecycle per connection:
      await gateway.connect(session_id, websocket, role="analyst")
      while True:
          raw = await websocket.receive_text()
          await gateway.receive_and_apply(session_id, raw)
      await gateway.disconnect(session_id)
    """

    # Keys excluded from state_update broadcasts (still included in initial_state).
    # Override in subclasses to prevent large payloads from being re-sent every cycle.
    _broadcast_exclude_keys: frozenset[str] = frozenset()

    # Roles whose connections are invisible to other clients: excluded from the
    # presence list and barred from placing a shared cursor. Used for observer
    # connections (Studio live spectators, the replay driver, the Wizard-of-Oz
    # panel) that must not show up as fellow "users" to participants.
    _HIDDEN_PRESENCE_ROLES: frozenset[str] = frozenset({"studio_replayer", "studio_spectator", "studio_collector"})

    def __init__(
        self,
        world_state: "WorldState",
        audit_log: "AuditLog",
        registry: "AgentRegistry",
        bus: "MessageBus",
        user_configs: dict[str, dict],
        recorder: SessionRecorder | None = None,
        mivais_config: MivaisConfig | None = None,
    ) -> None:
        """
        Args:
            world_state:    The shared WorldState blackboard.
            audit_log:      The AuditLog for this session.
            registry:       AgentRegistry used to register users as agents on connect.
            bus:            MessageBus for inter-agent and user-facing messaging.
            user_configs:   Role definitions keyed by role name. Each entry should
                            contain: can_read, can_write, bus_subscribe_topics,
                            bus_publish_topics, description.
            recorder:       Optional SessionRecorder; pass None to disable recording.
            mivais_config:  Library-level config (chat, cursors, audit, broadcast).
                            If None, all features are enabled with defaults.
        """
        self._ws = world_state
        self._audit = audit_log
        self._registry = registry
        self._bus = bus
        self._user_configs = user_configs
        self._recorder = recorder
        self._config = mivais_config or MivaisConfig.default()

        # Apply broadcast exclude keys from config
        if self._config.broadcast.exclude_keys:
            self._broadcast_exclude_keys = frozenset(self._config.broadcast.exclude_keys) | self._broadcast_exclude_keys

        self._connections: dict[str, WebSocket] = {}      # session_id -> WebSocket
        self._roles: dict[str, str] = {}                  # session_id -> role
        self._cursors: dict[str, dict] = {}               # "user:<sid>" -> cursor/drag info
        self._user_sub_topics: dict[str, list[str]] = {}  # session_id -> [subscribed topics]
        self._user_pub_topics: dict[str, list[str]] = {}  # session_id -> [publishable topics]
        self._cursor_rows: dict[str, str | None] = {}     # "user:<sid>" -> last logged row_name
        self._snapshot_recorded = False
        self._chat_history: list[dict] = []
        self._chat_history_size = self._config.chat.history_size
        self._online_agents: list[dict] = []
        self._collector_sessions: set[str] = set()

        # Push state updates to all clients on every WorldState write
        self._ws.watch_any(self._on_state_changed)

        # Route chat messages from the bus to connected WebSocket clients
        if self._config.chat.enabled:
            self._bus.subscribe("gateway", "chat.message", self._on_chat_via_bus)

    # ── Configuration ─────────────────────────────────────────────────────────

    def reload_user_configs(self, user_configs: dict[str, dict]) -> None:
        """Hot-reload user role definitions (e.g. after config file change)."""
        self._user_configs = user_configs

    def set_online_agents(self, agents: list[dict]) -> None:
        """Register the list of running non-user agents (id, role, description)."""
        self._online_agents = agents

    # ── Connection management ─────────────────────────────────────────────────

    async def connect(self, session_id: str, websocket: WebSocket, role: str = "analyst") -> None:
        """
        Accept a new WebSocket connection.

        Looks up the role in user_configs to determine permissions.
        Registers the user as a proper agent,
        pushes the full initial snapshot to the newcomer, then notifies all
        other connected clients of the new arrival.
        """
        await websocket.accept()

        
        if role == "studio_replayer":
            cfg = {
                "description":          "MIVAIS Studio replay driver (read all, push state)",
                "can_read":             [],   # empty = no restriction
                "can_write":            [],   # standard writes denied; replay.* uses system_write
                "bus_publish_topics":   [],
                "bus_subscribe_topics": [],
            }
        elif role == "studio_spectator":

            cfg = {
                "description":          "MIVAIS Studio live spectator (read-only observer)",
                "can_read":             [],   # empty = no restriction
                "can_write":            [],
                "bus_publish_topics":   [],
                "bus_subscribe_topics": [],
            }
        elif role == "studio_collector":
            cfg = {
                "description":          "MIVAIS Studio provenance collector (receives a live tap of every recorded event)",
                "can_read":             [],
                "can_write":            [],
                "bus_publish_topics":   [],
                "bus_subscribe_topics": [],
            }
            self._collector_sessions.add(session_id)
        else:
            # Resolve permissions from config — fall back to first defined role if unknown
            if role not in self._user_configs and self._user_configs:
                role = next(iter(self._user_configs))
            cfg = self._user_configs.get(role, {})

        # Register user as an agent so their writes go through PermissionGuard
        agent_id = f"user:{session_id}"
        self._registry.register_dynamic(AgentCapabilities(
            agent_id=agent_id,
            role=role,
            description=cfg.get("description", f"User with role '{role}'"),
            can_read=cfg.get("can_read", []),
            can_write=cfg.get("can_write", []),
        ))
        self._roles[session_id] = role

        # Subscribe this user to their permitted bus topics
        pub_topics = cfg.get("bus_publish_topics", [])
        self._user_pub_topics[session_id] = list(pub_topics)

        topics = cfg.get("bus_subscribe_topics", [])
        self._user_sub_topics[session_id] = list(topics)
        for topic in topics:
            # Skip chat.message — the gateway's _on_chat_via_bus already
            # broadcasts/routes these to all connected clients.
            if topic == "chat.message":
                continue
            def _make_handler(sid: str):
                async def _handler(message: dict) -> None:
                    await self._push_bus_message_to(sid, message)
                return _handler
            self._bus.subscribe(agent_id, topic, _make_handler(session_id))

        self._connections[session_id] = websocket

        
        if self._recorder and role not in ("studio_spectator", "studio_collector"):
            self._recorder.record("connect", {"session_id": session_id, "role": role})
            await self._tap_recorder_event("connect", {"session_id": session_id, "role": role})
            if not self._snapshot_recorded:
                self._snapshot_recorded = True
                snapshot = self._ws.snapshot()
                audit_entries = self._audit.get_entries(limit=200)
                self._recorder.record_state(
                    snapshot, audit_entries,
                    self._cursors, self._presence_list(), full_snapshot=True,
                )
                await self._tap_recorder_event("snapshot", {
                    "world_state": snapshot, "audit_log": audit_entries,
                    "cursors": self._cursors, "connected_users": self._presence_list(),
                })

        # Push full initial state (including excluded keys) to the newcomer only
        await self._push_to(session_id, msg_type="initial_state")

        # Notify all other connected clients about the new user
        await self._broadcast_all(exclude=session_id)

    async def disconnect(self, session_id: str) -> None:
        """Deregister the user agent, clean up state, notify remaining clients."""
        if self._recorder and self._roles.get(session_id) not in ("studio_spectator", "studio_collector"):
            self._recorder.record("disconnect", {"session_id": session_id})
            await self._tap_recorder_event("disconnect", {"session_id": session_id})
        self._cleanup_session(session_id)
        await self._broadcast_all()

    def connection_count(self) -> int:
        """Number of currently-connected WebSocket clients. A multi-room host
        uses this to decide when a room is idle and can be torn down."""
        return len(self._connections)

    # ── Incoming messages ─────────────────────────────────────────────────────

    async def receive_and_apply(self, session_id: str, raw: str) -> None:
        """
        Parse a JSON message from the frontend and dispatch it.

        Built-in actions:
          {"action": "cursor_move",  "row_name": "...", "x": 0.5, "y": 0.3}
          {"action": "drag_update",  "dragging": "...", "drag_over": "..."}
          {"action": "chat_message", "text": "...", "to": "broadcast"}
          {"action": "publish_bus",  "topic": "...", "payload": {...}}

        Any other action is forwarded to _handle_action(), which subclasses
        should override to implement domain-specific behaviour.

        All state-mutating actions go through WorldState.write() which enforces
        PermissionGuard and writes to AuditLog with actor="user:<session_id>".
        """
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return

        agent_id = f"user:{session_id}"
        action = data.get("action")

        
        if self._roles.get(session_id) in ("studio_spectator", "studio_collector"):
            return

        if self._recorder and action and action != "cursor_move":
            user_action_data = {
                "actor": agent_id,
                "action": action,
                "data": {k: v for k, v in data.items() if k != "action"},
            }
            self._recorder.record("user_action", user_action_data)
            await self._tap_recorder_event("user_action", user_action_data)

        if action == "cursor_move":
            if not self._config.cursors.enabled:
                return
            
            if self._roles.get(session_id) in self._HIDDEN_PRESENCE_ROLES:
                return
            row_name = data.get("row_name") or None
            x = data.get("x")
            y = data.get("y")
            entry = self._cursors.get(agent_id, {})
            if row_name:
                entry["row_name"] = str(row_name)
            else:
                entry.pop("row_name", None)
            if x is not None and y is not None:
                entry["x"] = round(float(x), 4)
                entry["y"] = round(float(y), 4)
            if entry:
                self._cursors[agent_id] = entry
            else:
                self._cursors.pop(agent_id, None)
            last_row = self._cursor_rows.get(agent_id)
            if row_name != last_row:
                self._cursor_rows[agent_id] = row_name
                self._audit.record(
                    actor=agent_id,
                    key="cursor",
                    value=row_name if row_name else "(left)",
                    accepted=True,
                    event_type="cursor_move",
                )
            await self._broadcast_cursors()

        elif action == "drag_update":
            # Same rule as cursor_move: hidden roles never place shared cursors.
            if self._roles.get(session_id) in self._HIDDEN_PRESENCE_ROLES:
                return
            dragging  = data.get("dragging")
            drag_over = data.get("drag_over")
            entry = self._cursors.get(agent_id, {})
            if dragging:
                entry["dragging"]  = str(dragging)
                entry["drag_over"] = str(drag_over) if drag_over else None
            else:
                entry.pop("dragging",  None)
                entry.pop("drag_over", None)
            self._cursors[agent_id] = entry
            await self._broadcast_cursors()

        elif action == "chat_message":
            if not self._config.chat.enabled:
                return
            text = str(data.get("text", "")).strip()
            to   = str(data.get("to", "broadcast")).strip()
            if not text:
                return
            if "chat.message" not in self._user_pub_topics.get(session_id, []):
                return
            payload = {
                "from":         agent_id,
                "from_display": session_id[:6],
                "from_role":    self._roles.get(session_id, "unknown"),
                "to":           to,
                "text":         text,
                "timestamp":    datetime.now(timezone.utc).isoformat(),
            }
            await self._bus.publish(agent_id, "chat.message", payload)

        elif action == "publish_bus":
            topic   = data.get("topic", "")
            payload = data.get("payload", {})
            allowed = self._user_pub_topics.get(session_id, [])
            if topic and topic in allowed:
                payload["from"] = agent_id
                await self._bus.publish(agent_id, topic, payload)

        elif action == "replay.push_state":
            # MIVAIS Studio replay driver. 
            if self._roles.get(session_id) != "studio_replayer":
                return
            state = data.get("state") or {}
            if not isinstance(state, dict):
                return
            for key, value in state.items():
                self._ws.system_write(str(key), value)

        elif action == "wizard.act":
            if self._roles.get(session_id) != "studio_replayer":
                return
            actor = str(data.get("actor") or "wizard")
            key = data.get("key")
            if key is not None:
                self._ws.system_write(str(key), data.get("value"), actor=actor)

        elif action == "wizard.say":
            # Wizard-of-Oz: post a chat message as a chosen AGENT.
            if self._roles.get(session_id) != "studio_replayer":
                return
            actor = str(data.get("actor") or "wizard")
            text = str(data.get("text") or "").strip()
            if text:
                await self._bus.publish(actor, "chat.message", {
                    "from": actor,
                    "from_display": actor,
                    "from_role": "agent",
                    "to": str(data.get("to") or "broadcast"),
                    "text": text,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })

        else:
            await self._handle_action(agent_id, session_id, data)

    async def _handle_action(self, agent_id: str, session_id: str, data: dict) -> None:
        """
        Override in subclasses to handle domain-specific WebSocket actions.

        Called for every action not handled by the built-in Gateway actions.

        Args:
            agent_id:   The agent identifier for this user, e.g. "user:abc123".
            session_id: The raw session identifier.
            data:       The parsed JSON payload from the client.

        Example:
            async def _handle_action(self, agent_id, session_id, data):
                action = data.get("action")
                if action == "submit_ranking":
                    ranking = data.get("ranking", [])
                    if len(ranking) >= 2:
                        self._ws.write(
                            agent_id, "user_ranking",
                            [int(i) for i in ranking],
                            event_type="user_input",
                        )
        """
        pass

    # ── Outgoing pushes ────────────────────────────────────────────────────────

    async def _on_state_changed(self, key: str, _value: object) -> None:
        """
        Called by WorldState on every write.
        Broadcasts the current snapshot + audit tail to all sessions.
        """
        snapshot = self._ws.snapshot()
        snapshot_safe = {
            k: v for k, v in snapshot.items()
            if k not in self._broadcast_exclude_keys
        }
        audit_tail = self._audit.get_entries(limit=60)

        message = json.dumps({
            "type": "state_update",
            "world_state": snapshot_safe,
            "audit_log": audit_tail,
            "cursors": self._cursors,
            "connected_users": self._presence_list(),
            "online_agents": self._online_agents,
        }, default=str)

        dead: list[str] = []
        for sid, ws in list(self._connections.items()):
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(sid)
        for sid in dead:
            self._cleanup_session(sid)

    async def _broadcast_all(self, exclude: str | None = None) -> None:
        """Push current state to all connected sessions (optionally skipping one)."""
        snapshot = self._ws.snapshot()
        snapshot_safe = {
            k: v for k, v in snapshot.items()
            if k not in self._broadcast_exclude_keys
        }
        audit_tail = self._audit.get_entries(limit=60)
        presence = self._presence_list()

        message = json.dumps({
            "type": "state_update",
            "world_state": snapshot_safe,
            "audit_log": audit_tail,
            "cursors": self._cursors,
            "connected_users": presence,
            "online_agents": self._online_agents,
        }, default=str)

        if self._recorder:
            self._recorder.record_state(
                snapshot_safe, audit_tail, self._cursors, presence,
            )
            await self._tap_recorder_event("state_update", {
                "world_state": snapshot_safe, "audit_log": audit_tail,
                "cursors": self._cursors, "connected_users": presence,
            })

        dead: list[str] = []
        for sid, ws in list(self._connections.items()):
            if sid == exclude:
                continue
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(sid)
        for sid in dead:
            self._cleanup_session(sid)

    async def _broadcast_cursors(self) -> None:
        """Push a lightweight cursor-only message to all clients."""
        presence = self._presence_list()
        message = json.dumps({
            "type": "cursor_update",
            "cursors": self._cursors,
            "connected_users": presence,
        })
        if self._recorder:
            self._recorder.record_cursors(self._cursors, presence)
            await self._tap_recorder_event("cursor_update", {
                "cursors": self._cursors, "connected_users": presence,
            })

        dead: list[str] = []
        for sid, ws in list(self._connections.items()):
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(sid)
        for sid in dead:
            self._cleanup_session(sid)

    async def _push_to(self, session_id: str, msg_type: str = "state_update") -> None:
        """Push the current snapshot to a single session."""
        ws = self._connections.get(session_id)
        if ws is None:
            return
        snapshot = self._ws.snapshot()
        if msg_type != "initial_state":
            snapshot = {
                k: v for k, v in snapshot.items()
                if k not in self._broadcast_exclude_keys
            }
        audit_tail = self._audit.get_entries(limit=60)
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
            await ws.send_text(json.dumps(payload, default=str))
        except Exception:
            self._cleanup_session(session_id)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _presence_list(self) -> list[dict]:
        """Return a list of {session_id, role} for every connected user.

        Sessions in a hidden role are omitted, so
        participants never see the observer as a fellow user.
        """
        return [
            {"session_id": sid, "role": self._roles.get(sid, "unknown")}
            for sid in self._connections
            if self._roles.get(sid) not in self._HIDDEN_PRESENCE_ROLES
        ]

    async def _on_chat_via_bus(self, message: dict) -> None:
        """Route chat.message — broadcast or private — and persist in history."""
        self._chat_history.append(message)
        if len(self._chat_history) > 100:
            self._chat_history.pop(0)

        to = (message.get("payload") or {}).get("to", "broadcast")

        if to in ("broadcast", "all", None, ""):
            await self._broadcast_bus_message(message)
        else:
            sender = (message.get("payload") or {}).get("from", "")
            targets = {to, sender}
            push = json.dumps({"type": "bus_message", "message": message})
            dead: list[str] = []
            for sid, ws in list(self._connections.items()):
                agent_id = f"user:{sid}"
                if agent_id in targets or sid in targets:
                    try:
                        await ws.send_text(push)
                    except Exception:
                        dead.append(sid)
            for sid in dead:
                self._cleanup_session(sid)

    async def _broadcast_bus_message(self, message: dict) -> None:
        """Push a bus message envelope to every connected WebSocket."""
        payload = json.dumps({"type": "bus_message", "message": message})
        dead: list[str] = []
        for sid, ws in list(self._connections.items()):
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(sid)
        for sid in dead:
            self._cleanup_session(sid)

    async def _tap_recorder_event(self, event_type: str, data: dict) -> None:
        """Live-push every event the SessionRecorder writes to disk to any
        connected `studio_collector` client, so a study environment can
        collect provenance directly over the WebSocket connection instead of
        tailing the recording file."""
        if not self._collector_sessions:
            return
        payload = json.dumps({"type": "recorder_event", "event_type": event_type, "data": data}, default=str)
        dead: list[str] = []
        for sid in list(self._collector_sessions):
            ws = self._connections.get(sid)
            if ws is None:
                continue
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(sid)
        for sid in dead:
            self._cleanup_session(sid)

    async def _push_bus_message_to(self, session_id: str, message: dict) -> None:
        """Push a bus message directly to one user's WebSocket."""
        ws = self._connections.get(session_id)
        if ws is None:
            return
        try:
            await ws.send_text(json.dumps({
                "type": "bus_message",
                "message": message,
            }))
        except Exception:
            self._cleanup_session(session_id)

    def _cleanup_session(self, session_id: str) -> None:
        """Minimal teardown for a session — callers handle any broadcast."""
        agent_id = f"user:{session_id}"
        for topic in self._user_sub_topics.pop(session_id, []):
            self._bus.unsubscribe(agent_id, topic)
        self._user_pub_topics.pop(session_id, None)
        self._registry.deregister(agent_id)
        self._cursors.pop(agent_id, None)
        self._cursor_rows.pop(agent_id, None)
        self._connections.pop(session_id, None)
        self._roles.pop(session_id, None)
        self._collector_sessions.discard(session_id)
