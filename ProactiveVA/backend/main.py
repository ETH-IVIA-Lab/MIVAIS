"""
ProactiveVA — MIVAIS-based proactive visual analytics server (VAST 2021 MC3).

"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi.responses import JSONResponse

from mivais.rooms import Room, create_room_app

from gateway_mc3 import MC3Gateway

from agents.onboarding_detector import OnboardingDetector
from agents.exploration_detector import ExplorationDetector
from agents.verification_detector import VerificationDetector
from agents.planner import Planner
from agents.acting_agent import ActingAgent

BASE = Path(__file__).parent
DATA_DIR = BASE / "data"

_AGENT_CLASSES = {
    "onboarding_detector":   OnboardingDetector,
    "exploration_detector":  ExplorationDetector,
    "verification_detector": VerificationDetector,
    "planner":               Planner,
    "acting_agent":          ActingAgent,
}


# ── Static data — parsed once, shared read-only across all rooms ─────────────

_STATIC = {
    "dataset":  json.loads((DATA_DIR / "messages.json").read_text(encoding="utf-8")),
    "hexgrid":  json.loads((DATA_DIR / "hexgrid.json").read_text(encoding="utf-8")),
    "streets":  json.loads((DATA_DIR / "streets.geojson").read_text(encoding="utf-8")),
    "entities": json.loads((DATA_DIR / "entities.json").read_text(encoding="utf-8")),
    "knowledge": json.loads((DATA_DIR / "knowledge.json").read_text(encoding="utf-8")),
}
print(f"[startup] static data: {len(_STATIC['dataset'])} messages, "
      f"{len(_STATIC['hexgrid'])} hexes, "
      f"{len(_STATIC['streets'].get('features', []))} street segments")

_DATA_FIELDS = [
    {"field": "id",        "type": "id"},
    {"field": "type",      "type": "nominal"},
    {"field": "timestamp", "type": "temporal"},
    {"field": "epoch",     "type": "quantitative"},
    {"field": "author",    "type": "nominal"},
    {"field": "message",   "type": "text"},
    {"field": "lat",       "type": "quantitative"},
    {"field": "lon",       "type": "quantitative"},
    {"field": "location",  "type": "nominal"},
    {"field": "sentiment", "type": "ordinal"},
    {"field": "entities",  "type": "nominal"},
    {"field": "hex_id",    "type": "nominal"},
]


def _seed(room: Room, params: dict) -> None:
    """Seed one room's WorldState. Static keys hold shared references (agents
    and the gateway only read them; broadcasts exclude them anyway)."""
    ws = room.world_state
    for key in ("dataset", "hexgrid", "streets", "entities", "knowledge"):
        ws.system_write(key, _STATIC[key])
    ws.system_write("data_fields", _DATA_FIELDS)

    # User-mutable selection state
    ws.system_write("selected_hex", None)
    ws.system_write("time_range", None)
    ws.system_write("selected_entity", None)
    ws.system_write("keyword_filter", [])
    ws.system_write("focused_view", "map")
    ws.system_write("notes", [])
    ws.system_write("staged_evidence", [])

    # Agent output channels
    ws.system_write("highlighted_message_ids", [])
    ws.system_write("pending_suggestions", [])
    ws.system_write("agent_trace", [])
    ws.system_write("agent_status", {"state": "idle"})

    # Controls (user-adjustable)
    ws.system_write("think_time_threshold_s", 3.0)
    ws.system_write("onboarding_enabled", True)
    ws.system_write("exploration_enabled", True)
    ws.system_write("verification_enabled", True)

    # Telemetry
    ws.system_write("interaction_log", [])


# ── App ───────────────────────────────────────────────────────────────────────

va = create_room_app(
    title="ProactiveVA (MIVAIS)",
    base_dir=BASE,
    gateway_cls=MC3Gateway,
    agent_classes=_AGENT_CLASSES,
    seed=_seed,
    env_prefix="PROACTIVE",
    # The gateway republishes every raw user interaction on this topic for
    # the detectors — far too chatty for the session recording
    bus_record_exclude_topics={"interaction.event"},
)
app, rooms = va.app, va.rooms
DEFAULT_ROOM = va.default_room


# ── ProactiveVA-specific REST ─────────────────────────────────────────────────

@app.get("/state")
async def get_state(room: str = DEFAULT_ROOM):
    """Health check + slim snapshot. Does NOT create a room."""
    r = rooms.peek(room)
    if r is None:
        return {"ok": True, "room": room, "active": False}
    snap = r.world_state.snapshot()
    for k in ("dataset", "hexgrid", "streets"):
        snap.pop(k, None)
    return {"ok": True, "room": room, "active": True, "world_state": snap}


# Large static data over REST so WebSocket frames stay small. The data is
# identical for every room, so these are served from the module-level copy.

@app.get("/data/dataset")
async def get_dataset():
    return JSONResponse(_STATIC["dataset"])


@app.get("/data/hexgrid")
async def get_hexgrid():
    return JSONResponse(_STATIC["hexgrid"])


@app.get("/data/streets")
async def get_streets():
    return JSONResponse(_STATIC["streets"])


@app.get("/data/entities")
async def get_entities():
    return JSONResponse(_STATIC["entities"])


@app.get("/data/knowledge")
async def get_knowledge():
    return JSONResponse(_STATIC["knowledge"])


@app.get("/llm/health")
async def llm_health():
    """Quickly tell the operator whether the LLM key is set."""
    from llm_client import get_client
    c = get_client()
    return {"available": c.available, "perception_model": c.perception_model,
            "reasoning_model": c.reasoning_model}
