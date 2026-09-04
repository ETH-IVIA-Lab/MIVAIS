"""Starter VA - a small useful mixed-initiative VA system on MIVAIS.

One scatterplot, one agent. This is the application the /setup
tutorial on MIVAIS Studio walks through step by step. It exists so you can
see every moving part of a MIVAIS application in one file, then swap the
scatterplot for your own interface.

What it does
    The analyst picks two numeric attributes of a small car dataset; the
    scatterplot re-renders live. The InsightAgent watches that selection and
    - unprompted - writes a correlation insight back into the shared state
    and comments in the chat. That loop (human acts - agent observes -
    agent acts - human sees it) is mixed-initiative VA in miniature.

What the infrastructure does for you
    Permissions, audit logging, real-time broadcast to every connected
    client, chat, presence, and a JSONL session recording for replay: all of
    it comes from the seven MIVAIS components wired up below. The
    application code contains none of it.

Run it
    pip install -r requirements.txt        (installs ../../MIVAIS editably)
    python main.py                         → http://127.0.0.1:7300

Studio integration
    When MIVAIS Studio spawns this app for a study session it passes
    STUDIO_VA_PORT and STUDIO_VA_RECORDING_DIR in the environment; we honour
    both, so each session gets a private instance and Studio tails the
    recording this instance writes. No further cooperation is required.
"""
from __future__ import annotations

import asyncio
import yaml
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse

from mivais.agent_registry import AgentCapabilities, AgentRegistry
from mivais.audit_log import AuditLog
from mivais.gateway import Gateway
from mivais.message_bus import MessageBus
from mivais.permission_guard import PermissionGuard
from mivais.session_recorder import SessionRecorder
from mivais.world_state import WorldState

from agents.insight_agent import InsightAgent

# ── Configuration ─────────────────────────────────────────────────────────────

HERE = Path(__file__).resolve().parent
PORT = int(os.environ.get("STUDIO_VA_PORT", os.environ.get("PORT", "7300")))
RECORDINGS_DIR = Path(os.environ.get("STUDIO_VA_RECORDING_DIR", HERE / "recordings"))

_config = yaml.safe_load((HERE / "agents_config.yaml").read_text(encoding="utf-8"))
_user_configs = {u["role"]: u for u in _config.get("users", [])}

# The classes an `agents` entry may name. Add your own agent here.
_AGENT_CLASSES = {"InsightAgent": InsightAgent}

# A small, embedded dataset (classic Auto-MPG excerpt) so the example has no
# file or database dependency. Replace with your own data loading.
DATASET = [
    {"name": "Chevrolet Chevelle", "mpg": 18.0, "horsepower": 130, "weight": 3504, "acceleration": 12.0, "year": 70},
    {"name": "Buick Skylark",      "mpg": 15.0, "horsepower": 165, "weight": 3693, "acceleration": 11.5, "year": 70},
    {"name": "Plymouth Satellite", "mpg": 18.0, "horsepower": 150, "weight": 3436, "acceleration": 11.0, "year": 70},
    {"name": "Ford Torino",        "mpg": 17.0, "horsepower": 140, "weight": 3449, "acceleration": 10.5, "year": 70},
    {"name": "Datsun PL510",       "mpg": 27.0, "horsepower": 88,  "weight": 2130, "acceleration": 14.5, "year": 71},
    {"name": "Toyota Corona",      "mpg": 25.0, "horsepower": 95,  "weight": 2228, "acceleration": 14.0, "year": 71},
    {"name": "Ford Pinto",         "mpg": 25.0, "horsepower": 75,  "weight": 2265, "acceleration": 18.2, "year": 71},
    {"name": "VW Super Beetle",    "mpg": 26.0, "horsepower": 46,  "weight": 1950, "acceleration": 21.0, "year": 73},
    {"name": "Chevrolet Impala",   "mpg": 11.0, "horsepower": 150, "weight": 4997, "acceleration": 14.0, "year": 73},
    {"name": "Datsun B210",        "mpg": 31.0, "horsepower": 67,  "weight": 1950, "acceleration": 19.0, "year": 74},
    {"name": "Toyota Corolla",     "mpg": 32.0, "horsepower": 75,  "weight": 2155, "acceleration": 16.4, "year": 76},
    {"name": "Honda Accord CVCC",  "mpg": 31.5, "horsepower": 68,  "weight": 2045, "acceleration": 18.5, "year": 77},
    {"name": "Ford Fiesta",        "mpg": 36.1, "horsepower": 66,  "weight": 1800, "acceleration": 14.4, "year": 78},
    {"name": "VW Rabbit Custom",   "mpg": 29.0, "horsepower": 78,  "weight": 1940, "acceleration": 14.5, "year": 77},
    {"name": "BMW 320i",           "mpg": 21.5, "horsepower": 110, "weight": 2600, "acceleration": 12.8, "year": 77},
    {"name": "Mercury Zephyr",     "mpg": 20.8, "horsepower": 85,  "weight": 3070, "acceleration": 16.7, "year": 78},
    {"name": "Chevrolet Citation", "mpg": 28.8, "horsepower": 115, "weight": 2595, "acceleration": 11.3, "year": 79},
    {"name": "Mazda GLC",          "mpg": 34.1, "horsepower": 65,  "weight": 1975, "acceleration": 15.2, "year": 79},
    {"name": "Plymouth Horizon",   "mpg": 34.2, "horsepower": 70,  "weight": 2200, "acceleration": 13.2, "year": 79},
    {"name": "Datsun 310",         "mpg": 37.2, "horsepower": 86,  "weight": 2019, "acceleration": 16.4, "year": 80},
    {"name": "Toyota Tercel",      "mpg": 37.7, "horsepower": 62,  "weight": 2050, "acceleration": 17.3, "year": 81},
    {"name": "Honda Civic 1300",   "mpg": 35.1, "horsepower": 60,  "weight": 1760, "acceleration": 16.1, "year": 81},
    {"name": "Dodge Charger 2.2",  "mpg": 36.0, "horsepower": 84,  "weight": 2370, "acceleration": 13.0, "year": 82},
    {"name": "Chevy S-10",         "mpg": 31.0, "horsepower": 82,  "weight": 2720, "acceleration": 19.4, "year": 82},
]
NUMERIC_COLS = ["mpg", "horsepower", "weight", "acceleration", "year"]

# ── Infrastructure wiring — the seven MIVAIS components ──────────────────────
# This block is the same in every MIVAIS application, whatever it analyzes.

audit_log   = AuditLog()
registry    = AgentRegistry()
guard       = PermissionGuard(registry)
world_state = WorldState(audit_log=audit_log, permission_guard=guard)
recorder    = SessionRecorder(RECORDINGS_DIR)
# Passing the recorder makes agent-to-agent bus messages part of the session
# recording, so they show up in the replay timeline.
bus         = MessageBus(audit_log=audit_log, recorder=recorder)


class StarterGateway(Gateway):
    """One override: translate this app's domain action into a state write.

    Everything else — connect/disconnect, permissions, chat, presence,
    broadcasting — is inherited from the base Gateway unchanged.
    """

    async def _handle_action(self, agent_id: str, session_id: str, data: dict) -> None:
        if data.get("action") == "select_attributes":
            x, y = data.get("x"), data.get("y")
            if x in NUMERIC_COLS and y in NUMERIC_COLS:
                # The write is attributed to the CONNECTED USER (agent_id),
                # checked against their role's can_write, and audit-logged.
                self._ws.write(agent_id, "selected_attributes", {"x": x, "y": y},
                               event_type="user_action")


gateway = StarterGateway(
    world_state=world_state,
    audit_log=audit_log,
    registry=registry,
    bus=bus,
    user_configs=_user_configs,
    recorder=recorder,
)

# ── Application lifespan: register agents, seed state ────────────────────────

_agent_tasks: list[asyncio.Task] = []


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Register every enabled agent from the config and start its run() loop.
    online: list[dict] = []
    for cfg in _config.get("agents", []):
        if not cfg.get("enabled", True):
            continue
        cap = AgentCapabilities(
            agent_id=cfg["agent_id"],
            role=cfg.get("role", "agent"),
            description=cfg.get("description", ""),
            can_read=cfg.get("can_read", []),
            can_write=cfg.get("can_write", []),
            bus_publish_topics=cfg.get("bus_publish_topics", []),
            bus_subscribe_topics=cfg.get("bus_subscribe_topics", []),
            params=cfg.get("params", {}),
        )
        cls = _AGENT_CLASSES.get(cfg["class"])
        if cls is None:
            print(f"[starter] unknown agent class {cfg['class']!r}, skipping")
            continue
        instance = cls(agent_id=cap.agent_id, world_state=world_state,
                       message_bus=bus, params=cap.params)
        registry.register(cap, instance)
        _agent_tasks.append(asyncio.create_task(instance.run(), name=f"agent:{cap.agent_id}"))
        online.append({"agent_id": cap.agent_id, "role": cap.role,
                       "description": cap.description})
    gateway.set_online_agents(online)

    # 2. Seed the World State. system_write bypasses the Permission Guard —
    #    it is the one infrastructure-level loophole, used only at startup.
    world_state.system_write("dataset", DATASET)
    world_state.system_write("numeric_cols", NUMERIC_COLS)
    world_state.system_write("selected_attributes", {"x": "horsepower", "y": "mpg"})

    yield

    for t in _agent_tasks:
        t.cancel()
    await asyncio.gather(*_agent_tasks, return_exceptions=True)
    recorder.close()


app = FastAPI(title="Starter VA — mixed-initiative scatterplot", lifespan=lifespan)

# ── The three endpoints every MIVAIS VA exposes ───────────────────────────────


@app.get("/")
async def index() -> FileResponse:
    """The frontend: one static HTML file, no build step."""
    return FileResponse(HERE.parent / "frontend" / "index.html")


@app.websocket("/ws/{session_id}")
async def websocket_endpoint(ws: WebSocket, session_id: str, role: str = "analyst") -> None:
    """The real-time channel. The Gateway does everything:
    registers the user as an agent, pushes the initial state, applies
    incoming actions, and broadcasts every change to every client."""
    await gateway.connect(session_id, ws, role=role)
    try:
        while True:
            raw = await ws.receive_text()
            await gateway.receive_and_apply(session_id, raw)
    except WebSocketDisconnect:
        pass
    finally:
        await gateway.disconnect(session_id)


@app.get("/state")
async def state() -> JSONResponse:
    """Health check + snapshot. Studio probes this before mounting the iframe."""
    snapshot = {k: v for k, v in world_state.snapshot().items() if k != "dataset"}
    return JSONResponse({"ok": True, "world_state": snapshot,
                         "connected_users": gateway.connection_count()})


if __name__ == "__main__":
    import uvicorn
    print(f"[starter] serving on http://127.0.0.1:{PORT}  (recordings → {RECORDINGS_DIR})")
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="warning")
