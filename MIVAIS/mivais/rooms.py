"""Generic multi-room hosting for MIVAIS applications.

One process hosts MANY isolated worlds ("rooms"), one per ``?room=<id>`` query
param on the WebSocket / page URL. Each room owns its own WorldState,
AuditLog, MessageBus, AgentRegistry, agent tasks and recorder, so two
participants on the same host never see each other's exploration unless they
share a room id. MIVAIS Studio sets the room to the participant's session id -
a private world per participant in singleplayer, one shared world per cohort
in multiplayer. Rooms are created lazily on the first WebSocket connect and
disposed after an idle timeout with no connections, so a participant who
refreshes mid-task rejoins the same world.

This module extracts what every hosted VA used to reimplement in its
``main.py``: the room lifecycle, the idle reaper, config parsing (all dialects
in the wild), agent wiring, config hot-reload, and the standard FastAPI
routes. A complete backend is one call:

    from mivais.rooms import Room, create_room_app

    def seed(room: Room, params: dict) -> None:            # initial WorldState
        room.world_state.system_write("dataset", DATASET)

    va = create_room_app(
        title="My VA (MIVAIS)",
        base_dir=Path(__file__).parent,                    # agents_config.yaml etc.
        gateway_cls=MyGateway,                             # _handle_action lives here
        agent_classes=AGENT_CLASSES,
        seed=seed,
        env_prefix="MYVA",                                 # MYVA_DEFAULT_ROOM, MYVA_ROOM_IDLE_TIMEOUT
    )
    app, rooms = va.app, va.rooms                          # extra routes go on `app`

The lower-level pieces (``Room``, ``RoomManager``, ``attach_room_routes``,
``load_agents_config``) stay public for apps that need custom wiring.
"""
from __future__ import annotations

import asyncio
import inspect
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterable

from fastapi import WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from mivais.agent_registry import AgentCapabilities, AgentRegistry
from mivais.audit_log import AuditLog
from mivais.config import MivaisConfig
from mivais.gateway import Gateway
from mivais.message_bus import MessageBus
from mivais.permission_guard import PermissionGuard
from mivais.session_recorder import SessionRecorder
from mivais.world_state import WorldState

__all__ = [
    "Room",
    "RoomApp",
    "RoomManager",
    "attach_room_routes",
    "capabilities_from_config",
    "create_room_app",
    "load_agents_config",
    "safe_room_dir",
    "watch_agents_config",
]


# ── Config parsing ────────────────────────────────────────────────────────────

def load_agents_config(path: str | Path) -> tuple[dict[str, dict], list[dict]]:
    """Parse ``agents_config.yaml`` into ``(user_configs, agent_configs)``.

    Accepts both user-section dialects found in the wild:
      - ``"users": [ {"role": "analyst", ...}, ... ]``   (list of role objects)
      - ``"roles": { "analyst": {...}, ... }``            (map keyed by role)
    Either reduces to the ``role → capability dict`` mapping the Gateway wants.
    """
    import yaml

    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    user_configs: dict[str, dict] = {}
    for u in raw.get("users", []) or []:
        user_configs[u["role"]] = dict(u)
    for role_name, role_def in (raw.get("roles", {}) or {}).items():
        user_configs[role_name] = {
            "role": role_name,
            "description": role_def.get("description", f"{role_name} user"),
            **{k: v for k, v in role_def.items() if k != "description"},
        }
    return user_configs, list(raw.get("agents", []) or [])


def capabilities_from_config(cfg: dict) -> AgentCapabilities:
    """Build AgentCapabilities from an agent config entry, accepting both the
    flat layout (``can_read`` at the top level) and the nested one
    (``observation.can_read`` / ``actions.can_write`` / ``bus.publish_topics``)."""
    obs = cfg.get("observation", {}) or {}
    act = cfg.get("actions", {}) or {}
    bus = cfg.get("bus", {}) or {}
    params = cfg.get("params", {}) or {}
    return AgentCapabilities(
        agent_id=cfg["agent_id"],
        role=cfg.get("role", "agent"),
        description=cfg.get("description", ""),
        can_read=cfg.get("can_read", obs.get("can_read", [])),
        can_write=cfg.get("can_write", act.get("can_write", [])),
        bus_publish_topics=cfg.get(
            "bus_publish_topics", cfg.get("bus_topics", bus.get("publish_topics", []))
        ),
        bus_subscribe_topics=cfg.get(
            "bus_subscribe_topics", bus.get("subscribe_topics", [])
        ),
        trigger=cfg.get("trigger", obs.get("strategy", "poll")),
        poll_interval_seconds=params.get("poll_interval_seconds"),
        params=params,
    )


def safe_room_dir(room_id: str) -> str:
    """Filesystem-safe folder name for a room's recordings."""
    cleaned = "".join(c for c in room_id if c.isalnum() or c in "-_")[:64]
    return cleaned or "room"


def _accepts_kwarg(cls: type, name: str) -> bool:
    try:
        sig = inspect.signature(cls.__init__)
    except (TypeError, ValueError):
        return False
    p = sig.parameters
    return name in p or any(x.kind is inspect.Parameter.VAR_KEYWORD for x in p.values())


# ── Room ──────────────────────────────────────────────────────────────────────

SeedFn = Callable[["Room", dict], None]


class Room:
    """One fully-isolated MIVAIS world: its own infrastructure, agents and
    recorder. Everything that used to be a module-level singleton in a
    single-world VA lives in a room."""

    def __init__(
        self,
        room_id: str,
        *,
        gateway_cls: type[Gateway] = Gateway,
        agent_classes: dict[str, type] | None = None,
        user_configs: dict[str, dict] | None = None,
        agent_configs: list[dict] | None = None,
        mivais_config: MivaisConfig | None = None,
        recordings_dir: str | Path | None = None,
        seed: SeedFn | None = None,
        params: dict | None = None,
        gateway_kwargs: dict | None = None,
        bus_record_exclude_topics: Iterable[str] = (),
    ) -> None:
        self.room_id = room_id
        self.params = dict(params or {})
        self._agent_classes = agent_classes or {}
        self._agent_configs = list(agent_configs or [])
        self._seed = seed

        self.audit_log = AuditLog()
        self.registry = AgentRegistry()
        self.guard = PermissionGuard(self.registry)
        self.world_state = WorldState(audit_log=self.audit_log, permission_guard=self.guard)

        cfg = mivais_config or MivaisConfig.default()
        self.recorder: SessionRecorder | None = None
        if recordings_dir is not None and cfg.audit.enabled:
            self.recorder = SessionRecorder(Path(recordings_dir) / safe_room_dir(room_id))

        # Bus messages are recorded so agent-to-agent traffic shows up in the
        # replay timeline; high-volume telemetry topics can be excluded.
        self.bus = MessageBus(
            audit_log=self.audit_log,
            recorder=self.recorder,
            record_exclude_topics=bus_record_exclude_topics,
        )

        self.gateway = gateway_cls(
            world_state=self.world_state,
            audit_log=self.audit_log,
            registry=self.registry,
            bus=self.bus,
            user_configs=user_configs or {},
            recorder=self.recorder,
            mivais_config=mivais_config,
            **(gateway_kwargs or {}),
        )
        self._agent_tasks: list[asyncio.Task] = []
        self._started = False

    @property
    def connection_count(self) -> int:
        return self.gateway.connection_count()

    def _resolve_agent_class(self, cfg: dict) -> type | None:
        """Class maps in the wild are keyed by class name OR by agent_id."""
        return self._agent_classes.get(cfg.get("class", "")) or self._agent_classes.get(
            cfg.get("agent_id", "")
        )

    async def start(self) -> None:
        """Seed the WorldState, then register and start every enabled agent."""
        if self._started:
            return
        if self._seed is not None:
            self._seed(self, self.params)

        for cfg in self._agent_configs:
            if not cfg.get("enabled", True):
                continue
            agent_id = cfg["agent_id"]
            cls = self._resolve_agent_class(cfg)
            if cls is None:
                print(f"[room {self.room_id}] WARNING: unknown agent class for '{agent_id}', skipping")
                continue

            cap = capabilities_from_config(cfg)
            kwargs: dict[str, Any] = {
                "agent_id": agent_id,
                "world_state": self.world_state,
                "message_bus": self.bus,
            }
            # Agent constructors differ only in whether they take `params`.
            if cap.params and _accepts_kwarg(cls, "params"):
                kwargs["params"] = cap.params
            instance = cls(**kwargs)
            self.registry.register(cap, instance)
            self._agent_tasks.append(
                asyncio.create_task(instance.run(), name=f"agent:{self.room_id}:{agent_id}")
            )

        # Expose the agent roster to clients (chat targets, Wizard-of-Oz panel).
        self.gateway.set_online_agents([
            {"id": a["agent_id"], "role": a.get("role", ""), "description": a.get("description", "")}
            for a in self._agent_configs
            if a.get("enabled", True)
        ])
        print(f"[room {self.room_id}] started ({len(self._agent_tasks)} agents)")
        self._started = True

    async def stop(self) -> None:
        """Cancel agent tasks and close the recorder for this room."""
        for task in self._agent_tasks:
            task.cancel()
        await asyncio.gather(*self._agent_tasks, return_exceptions=True)
        self._agent_tasks.clear()
        if self.recorder is not None:
            self.recorder.close()
        print(f"[room {self.room_id}] stopped")

    def reload_config(self, new_user_cfgs: dict[str, dict], new_agent_cfgs: list[dict]) -> None:
        """Apply a hot-reloaded agents_config.yaml to this room's live infrastructure."""
        self.gateway.reload_user_configs(new_user_cfgs)
        for agent_cfg in new_agent_cfgs:
            agent_id = agent_cfg.get("agent_id", "")
            if not agent_id:
                continue
            cap = self.registry.get(agent_id)
            if cap is None:
                continue

            new_cap = capabilities_from_config(agent_cfg)
            cap.can_read = new_cap.can_read
            cap.can_write = new_cap.can_write
            cap.bus_publish_topics = new_cap.bus_publish_topics
            cap.bus_subscribe_topics = new_cap.bus_subscribe_topics
            cap.params = new_cap.params

            instance = self.registry.get_instance(agent_id)
            if instance is not None and hasattr(instance, "on_config_reload"):
                try:
                    instance.on_config_reload(new_cap.params)
                except Exception as exc:
                    print(f"[config] {self.room_id}/{agent_id}.on_config_reload failed: {exc}")


# ── Room manager ──────────────────────────────────────────────────────────────

RoomFactory = Callable[[str, dict], Room]


class RoomManager:
    """Owns the live rooms and reaps idle ones after ``idle_timeout_s``.

    ``factory(room_id, params)`` builds a room; ``params`` are the query
    params of the WebSocket connect that CREATED the room (later joiners share
    the existing world regardless of their own params - first-come semantics,
    matching the room id itself)."""

    def __init__(self, factory: RoomFactory, *, idle_timeout_s: float = 300.0) -> None:
        self._factory = factory
        self._idle_timeout_s = idle_timeout_s
        self._rooms: dict[str, Room] = {}
        self._dispose_tasks: dict[str, asyncio.Task] = {}
        self._lock = asyncio.Lock()

    async def get_or_create(self, room_id: str, params: dict | None = None) -> Room:
        async with self._lock:
            room = self._rooms.get(room_id)
            if room is None:
                room = self._factory(room_id, dict(params or {}))
                await room.start()
                self._rooms[room_id] = room
                print(f"[rooms] created '{room_id}' (active: {len(self._rooms)})")
            self._cancel_dispose(room_id)
            return room

    def peek(self, room_id: str) -> Room | None:
        return self._rooms.get(room_id)

    def all(self) -> list[Room]:
        return list(self._rooms.values())

    def _cancel_dispose(self, room_id: str) -> None:
        task = self._dispose_tasks.pop(room_id, None)
        if task is not None:
            task.cancel()

    def schedule_dispose_if_idle(self, room_id: str) -> None:
        room = self._rooms.get(room_id)
        if room is None or room.connection_count > 0:
            return
        self._cancel_dispose(room_id)
        self._dispose_tasks[room_id] = asyncio.create_task(
            self._dispose_after_idle(room_id), name=f"dispose:{room_id}"
        )

    async def _dispose_after_idle(self, room_id: str) -> None:
        try:
            await asyncio.sleep(self._idle_timeout_s)
        except asyncio.CancelledError:
            return
        async with self._lock:
            room = self._rooms.get(room_id)
            if room is None or room.connection_count > 0:
                return
            await room.stop()
            self._rooms.pop(room_id, None)
            self._dispose_tasks.pop(room_id, None)
            print(f"[rooms] disposed '{room_id}' after {self._idle_timeout_s}s idle "
                  f"(active: {len(self._rooms)})")

    async def stop_all(self) -> None:
        for task in list(self._dispose_tasks.values()):
            task.cancel()
        self._dispose_tasks.clear()
        for room in list(self._rooms.values()):
            await room.stop()
        self._rooms.clear()

    def lifespan(self, recordings_dir: str | Path | None = None,
                 extra: Callable[[], Awaitable[None]] | None = None,
                 background: Iterable[Callable[[], Awaitable[None]]] = ()):
        background = list(background)

        @asynccontextmanager
        async def _lifespan(app):  # noqa: ANN001 — FastAPI's contract
            if recordings_dir is not None:
                Path(recordings_dir).mkdir(parents=True, exist_ok=True)
            if extra is not None:
                await extra()
            tasks = [asyncio.create_task(fn(), name=f"background:{i}")
                     for i, fn in enumerate(background)]
            yield
            print("[shutdown] stopping rooms...")
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await self.stop_all()
            print("[shutdown] done")

        return _lifespan


# ── Config hot-reload ─────────────────────────────────────────────────────────

async def watch_agents_config(
    cfg_path: str | Path,
    manager: RoomManager,
    user_configs: dict[str, dict],
    agent_configs: list[dict],
    on_reload: Callable[[dict], None] | None = None,
) -> None:
    """Watch the agents config file and hot-reload it on every save.

    The passed ``user_configs`` / ``agent_configs`` containers are updated IN
    PLACE, so newly-created rooms (which hold references to them) pick up the
    change, and every live room gets :meth:`Room.reload_config` applied.
    ``on_reload(raw_config)`` lets the app react to non-agent sections. 
    Requires ``watchfiles``; without it, hot-reload is silently disabled."""
    try:
        from watchfiles import awatch
    except ImportError:
        print("[config] watchfiles not available — hot-reload disabled")
        return

    import yaml

    cfg_path = Path(cfg_path)
    print(f"[config] watching {cfg_path.name} for changes")
    async for _ in awatch(cfg_path):
        try:
            raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
            new_users, new_agents = load_agents_config(cfg_path)
        except Exception as exc:
            print(f"[config] reload failed (parse error): {exc}")
            continue

        user_configs.clear()
        user_configs.update(new_users)
        agent_configs[:] = new_agents
        if on_reload is not None:
            try:
                on_reload(raw)
            except Exception as exc:
                print(f"[config] on_reload hook failed: {exc}")
        for room in manager.all():
            room.reload_config(new_users, new_agents)

        print(f"[config] reloaded — roles: {list(new_users.keys())} "
              f"across {len(manager.all())} room(s)")


# ── Standard FastAPI routes ───────────────────────────────────────────────────

def attach_room_routes(
    app,
    manager: RoomManager,
    *,
    default_room: str = "default",
    default_role: str = "analyst",
    frontend_dir: str | Path | None = None,
    user_configs: dict[str, dict] | None = None,
    recordings_dir: str | Path | None = None,
    audit_viewer: bool = True,
) -> None:
    """Attach the routes every hosted MIVAIS VA serves:

    - ``WS /ws/{session_id}?room=&role=&...`` — the real-time channel. ALL
      query params are forwarded to the room factory, so an app can consume
      extra ones (e.g. Voyager's ``?dataset=``) without new endpoint code.
    - ``GET /`` — the built frontend (``<frontend_dir>/dist/index.html``).
    - ``GET /audit?room=&limit=`` — recent audit entries (never creates a room).
    - ``GET /agents?room=`` — registered agents with capabilities.
    - ``GET /users`` — role definitions (if ``user_configs`` given).
    - ``GET /recordings`` + ``GET /recordings/{file}`` (if ``recordings_dir`` given).
    - ``GET /log`` — a plain HTML audit-log viewer (disable with ``audit_viewer=False``).
    """
    @app.websocket("/ws/{session_id}")
    async def _ws_endpoint(websocket: WebSocket, session_id: str):  
        q = dict(websocket.query_params)
        room_id = (q.get("room") or default_room)[:128]
        role = q.get("role") or default_role
        room = await manager.get_or_create(room_id, params=q)
        await room.gateway.connect(session_id, websocket, role=role)
        try:
            while True:
                raw = await websocket.receive_text()
                await room.gateway.receive_and_apply(session_id, raw)
        except WebSocketDisconnect:
            pass
        finally:
            await room.gateway.disconnect(session_id)
            manager.schedule_dispose_if_idle(room_id)

    @app.get("/audit")
    async def _audit(limit: int = 200, room: str = default_room):  
        r = manager.peek(room)
        if r is None:
            return {"entries": [], "total": 0}
        return {"entries": r.audit_log.get_entries(limit=limit),
                "total": len(r.audit_log.get_all())}

    @app.get("/agents")
    async def _agents(room: str = default_room):  
        r = manager.peek(room)
        if r is None:
            return {"agents": []}
        return {"agents": r.registry.summary()}

    if user_configs is not None:
        @app.get("/users")
        async def _users():  
            # `user_configs` is read live so hot-reload shows up.
            return {"users": list(user_configs.values())}

    if recordings_dir is not None:
        from datetime import datetime

        from fastapi import HTTPException
        from fastapi.responses import FileResponse

        rec_root = Path(recordings_dir)

        @app.get("/recordings")
        async def _recordings():  
            if not rec_root.exists():
                return {"recordings": []}
            files = sorted(rec_root.rglob("*.jsonl"),
                           key=lambda f: f.stat().st_mtime, reverse=True)
            return {"recordings": [
                {
                    "filename": str(f.relative_to(rec_root)).replace("\\", "/"),
                    "size_bytes": f.stat().st_size,
                    "created_at": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
                }
                for f in files
            ]}

        @app.get("/recordings/{filename:path}")
        async def _recording(filename: str):  
            # Prevent path traversal
            if ".." in filename or filename.startswith(("/", "\\")):
                raise HTTPException(status_code=400, detail="Invalid filename")
            path = (rec_root / filename).resolve()
            if rec_root.resolve() not in path.parents or path.suffix != ".jsonl" or not path.exists():
                raise HTTPException(status_code=404, detail="Recording not found")
            return FileResponse(str(path), media_type="application/x-ndjson", filename=path.name)

    if audit_viewer:
        @app.get("/log")
        async def _audit_log_page():  
            return HTMLResponse(content=AUDIT_VIEWER_HTML)

    if frontend_dir is not None:
        dist = Path(frontend_dir) / "dist"
        if (dist / "assets").is_dir():
            app.mount("/assets", StaticFiles(directory=str(dist / "assets")), name="assets")

        @app.get("/")
        async def _index():  
            index = dist / "index.html"
            if not index.is_file():
                return {"ok": True,
                        "note": "frontend not built (dev mode) — build it into frontend/dist"}
            return HTMLResponse(content=index.read_text(encoding="utf-8"))


# ── High-level app factory ────────────────────────────────────────────────────

class RoomApp:
    """Everything :func:`create_room_app` built, for the app module to reference."""

    def __init__(self, app, rooms: RoomManager, user_configs: dict[str, dict],
                 agent_configs: list[dict], mivais_config: MivaisConfig | None,
                 recordings_dir: Path, default_room: str) -> None:
        self.app = app
        self.rooms = rooms
        self.user_configs = user_configs
        self.agent_configs = agent_configs
        self.mivais_config = mivais_config
        self.recordings_dir = recordings_dir
        self.default_room = default_room


def create_room_app(
    *,
    title: str,
    base_dir: str | Path,
    gateway_cls: type[Gateway] = Gateway,
    agent_classes: dict[str, type] | None = None,
    seed: SeedFn | None = None,
    env_prefix: str = "MIVAIS",
    room_cls: type[Room] = Room,
    frontend_dir: str | Path | None = None,
    bus_record_exclude_topics: Iterable[str] = (),
    cors: bool = False,
    watch_config: bool = False,
    on_config_reload: Callable[[dict], None] | None = None,
    version: str | None = None,
) -> RoomApp:
    """Build a complete multi-room MIVAIS FastAPI app from one call.

    Loads ``<base_dir>/agents_config.yaml`` (and ``mivais_config.yaml`` if
    present; legacy ``.json`` files are picked up as a fallback), reads
    ``{env_prefix}_DEFAULT_ROOM`` / ``{env_prefix}_ROOM_IDLE_TIMEOUT``
    from the environment, wires the RoomManager and attaches the standard
    routes. The app module keeps only its Gateway subclass, agent classes,
    seed function and any extra REST routes (registered on ``result.app``
    after this call).

    Args:
        base_dir:           The backend directory (configs + recordings live here).
        seed:               ``seed(room, params)`` - write the initial WorldState.
        env_prefix:         Env-var prefix
        frontend_dir:       Defaults to ``<base_dir>/../frontend``.
        cors:               Add a permissive CORS middleware.
        watch_config:       Hot-reload agents_config.yaml into live rooms
                            (requires ``watchfiles``).
        on_config_reload:   Called with the raw reloaded config mapping - for
                            app-specific sections such as PODIUM's
                            ``infrastructure`` block.
    """
    from fastapi import FastAPI

    base_dir = Path(base_dir)

    def _prefer_yaml(stem: str) -> Path:
        yaml_path = base_dir / f"{stem}.yaml"
        return yaml_path if yaml_path.exists() else base_dir / f"{stem}.json"

    cfg_path = _prefer_yaml("agents_config")
    user_configs, agent_configs = load_agents_config(cfg_path)

    mivais_cfg: MivaisConfig | None = None
    mivais_cfg_path = _prefer_yaml("mivais_config")
    if mivais_cfg_path.exists():
        mivais_cfg = MivaisConfig.load(mivais_cfg_path)

    recordings_dir = base_dir / (
        mivais_cfg.audit.recording_dir if mivais_cfg is not None else "recordings"
    )
    default_room = os.environ.get(f"{env_prefix}_DEFAULT_ROOM", "default")
    idle_timeout_s = float(os.environ.get(f"{env_prefix}_ROOM_IDLE_TIMEOUT", "300"))
    if frontend_dir is None:
        frontend_dir = base_dir.parent / "frontend"

    rooms = RoomManager(
        lambda room_id, params: room_cls(
            room_id,
            gateway_cls=gateway_cls,
            agent_classes=agent_classes,
            user_configs=user_configs,
            agent_configs=agent_configs,
            mivais_config=mivais_cfg,
            recordings_dir=recordings_dir,
            seed=seed,
            params=params,
            bus_record_exclude_topics=bus_record_exclude_topics,
        ),
        idle_timeout_s=idle_timeout_s,
    )

    background = []
    if watch_config:
        background.append(lambda: watch_agents_config(
            cfg_path, rooms, user_configs, agent_configs, on_reload=on_config_reload,
        ))

    fastapi_kwargs: dict[str, Any] = {"title": title}
    if version is not None:
        fastapi_kwargs["version"] = version
    app = FastAPI(lifespan=rooms.lifespan(recordings_dir, background=background),
                  **fastapi_kwargs)

    if cors:
        from fastapi.middleware.cors import CORSMiddleware
        app.add_middleware(CORSMiddleware, allow_origins=["*"],
                           allow_methods=["*"], allow_headers=["*"])

    attach_room_routes(
        app, rooms,
        default_room=default_room,
        frontend_dir=frontend_dir,
        user_configs=user_configs,
        recordings_dir=recordings_dir,
    )
    return RoomApp(app, rooms, user_configs, agent_configs, mivais_cfg,
                   recordings_dir, default_room)


# Plain HTML audit-log viewer served at /log — zero-dependency operator view
# of a room's AuditLog (fetches /audit client-side).
AUDIT_VIEWER_HTML = """<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Audit Log</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:Inter,system-ui,sans-serif;background:#f8f9fa;color:#1e293b;padding:20px}
h1{font-size:18px;margin-bottom:16px}
.controls{margin-bottom:12px;display:flex;gap:8px;align-items:center}
.controls select,.controls input{padding:4px 8px;border:1px solid #d0d7de;border-radius:4px;font-size:12px}
.controls button{padding:4px 12px;border:1px solid #d0d7de;border-radius:4px;font-size:12px;cursor:pointer;background:white}
.controls button:hover{background:#f0f0f0}
table{width:100%;border-collapse:collapse;font-size:12px;background:white;border:1px solid #d0d7de;border-radius:6px;overflow:hidden}
th{background:#f1f5f9;text-align:left;padding:8px 10px;font-size:10px;text-transform:uppercase;letter-spacing:0.5px;color:#64748b;border-bottom:1px solid #d0d7de}
td{padding:6px 10px;border-bottom:1px solid #f1f5f9;vertical-align:top;max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
tr:hover td{background:#f8fafc}
.accepted{color:#16a34a;font-weight:600} .denied{color:#dc2626;font-weight:600}
.actor-user{color:#0550ae} .actor-agent{color:#6e40c9} .actor-system{color:#64748b}
.type-write{background:#dce9ff;color:#0969da;padding:1px 6px;border-radius:3px;font-size:10px;font-weight:600}
.type-bus{background:#ede9fe;color:#8250df;padding:1px 6px;border-radius:3px;font-size:10px;font-weight:600}
.type-cursor{background:#f1f5f9;color:#94a3b8;padding:1px 6px;border-radius:3px;font-size:10px;font-weight:600}
.type-denied{background:#ffe0e0;color:#dc2626;padding:1px 6px;border-radius:3px;font-size:10px;font-weight:600}
a{color:#0969da;text-decoration:none}
a:hover{text-decoration:underline}
.stats{display:flex;gap:16px;margin-bottom:16px;font-size:12px;color:#64748b}
.stats b{color:#1e293b}
</style></head><body>
<h1>Audit Log <a href="/" style="font-size:12px;margin-left:12px">Back to Dashboard</a></h1>
<div class="controls">
  <label>Filter actor: <input id="filterActor" placeholder="e.g. insight_agent"></label>
  <label>Type: <select id="filterType"><option value="">All</option><option>write</option><option>bus_message</option><option>cursor_move</option><option>user_input</option><option>denied</option></select></label>
  <button onclick="loadLog()">Refresh</button>
  <label><input type="checkbox" id="hideCursors" checked> Hide cursor events</label>
</div>
<div class="stats" id="stats"></div>
<table><thead><tr><th>Time</th><th>Actor</th><th>Type</th><th>Key</th><th>Status</th><th>Value (preview)</th></tr></thead><tbody id="logBody"></tbody></table>
<script>
async function loadLog() {
  const room = new URLSearchParams(location.search).get('room') || 'default';
  const res = await fetch('/audit?limit=500&room=' + encodeURIComponent(room));
  const data = await res.json();
  const actor = document.getElementById('filterActor').value.toLowerCase();
  const type = document.getElementById('filterType').value;
  const hideCursors = document.getElementById('hideCursors').checked;
  let entries = data.entries || [];
  if (actor) entries = entries.filter(e => (e.actor||'').toLowerCase().includes(actor));
  if (type) entries = entries.filter(e => e.event_type === type);
  if (hideCursors) entries = entries.filter(e => e.event_type !== 'cursor_move');
  document.getElementById('stats').innerHTML = 'Showing <b>' + entries.length + '</b> of <b>' + data.total + '</b> total entries';
  const body = document.getElementById('logBody');
  body.innerHTML = entries.reverse().map(e => {
    const ts = (e.timestamp||'').slice(11,19);
    const actorCls = (e.actor||'').startsWith('user:') ? 'actor-user' : (e.actor==='system'?'actor-system':'actor-agent');
    const typeCls = e.event_type==='denied'?'type-denied':e.event_type==='bus_message'?'type-bus':e.event_type==='cursor_move'?'type-cursor':'type-write';
    const status = e.accepted!==false ? '<span class="accepted">OK</span>' : '<span class="denied">DENIED</span>';
    const val = typeof e.value==='object'?JSON.stringify(e.value).slice(0,80):String(e.value||'').slice(0,80);
    return '<tr><td>'+ts+'</td><td class="'+actorCls+'">'+(e.actor||'')+'</td><td><span class="'+typeCls+'">'+(e.event_type||'')+'</span></td><td><b>'+(e.key||'')+'</b></td><td>'+status+'</td><td title="'+val.replace(/"/g,'&quot;')+'">'+val+'</td></tr>';
  }).join('');
}
loadLog();
document.getElementById('filterActor').addEventListener('input', loadLog);
document.getElementById('filterType').addEventListener('change', loadLog);
document.getElementById('hideCursors').addEventListener('change', loadLog);
</script></body></html>"""
