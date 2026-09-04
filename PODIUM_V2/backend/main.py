"""
PODIUM

"""
from __future__ import annotations

import yaml
from pathlib import Path

import pandas as pd
from fastapi.responses import HTMLResponse

from mivais.gateway import Gateway
from mivais.rooms import Room, create_room_app

from agents.svm_ranking_agent import SVMRankingAgent

BASE = Path(__file__).parent


_config = yaml.safe_load((BASE / "agents_config.yaml").read_text(encoding="utf-8"))

_AGENT_CLASSES: dict[str, type] = {
    "SVMRankingAgent":    SVMRankingAgent,
}


# ── Gateway ───────────────────────────────────────────────────────────────────

class PodiumGateway(Gateway):
    """Routes PODIUM-specific WebSocket actions into WorldState writes or
    MessageBus publishes.

    Without this override the base Gateway's ``_handle_action`` is a no-op
    (see ``mivais/gateway.py``), so user clicks on Compute Weights / Rank All,
    weight-nudge arrows, and drag-to-reorder all log a ``user_action`` to the
    recorder but never reach the SVM ranker.
    """
    async def _handle_action(self, agent_id: str, session_id: str, data: dict) -> None:
        action = data.get("action")
        if action == "set_nudges":
            self._ws.write(agent_id, "session_nudges", data.get("nudges") or {})
        elif action == "compute_weights":
            ranking = [int(i) for i in (data.get("ranking") or [])]
            await self._bus.publish(agent_id, "weights.compute_request", {"ranking": ranking})
        elif action == "drop_order":
            order = list(data.get("display_order") or [])
            self._ws.write(agent_id, "display_order", order)
        elif action == "rank_all":
            await self._bus.publish(agent_id, "rank_all.request", {})


# ── Seed ──────────────────────────────────────────────────────────────────────

def _seed(room: Room, params: dict) -> None:
    """Load the CSV dataset into the room's WorldState and seed the keys the
    dashboard and the SVM ranker expect."""
    infra_cfg = _config.get("infrastructure", {})
    dataset_path = BASE / infra_cfg.get("dataset", "data/cars.csv")
    df = pd.read_csv(dataset_path)
    numeric_cols = [c for c in df.columns if c != "name"]

    ws = room.world_state
    ws.system_write("dataset", df.to_dict(orient="records"))
    ws.system_write("numeric_cols", numeric_cols)
    ws.system_write("session_nudges", {})
    ws.system_write("user_preference_ranking", {})
    ws.system_write("ranked_items", [])
    ws.system_write("display_order", [])
    ws.system_write("weights", {})
    ws.system_write("svm_status", {"status": "initialised"})

    print(f"[room {room.room_id}] dataset loaded: {len(df)} rows, cols={numeric_cols}")


def _on_config_reload(raw: dict) -> None:
    """Refresh the raw config in place so new rooms pick up e.g. a changed
    ``infrastructure.dataset`` path (agent + user configs are handled
    generically by the library watcher)."""
    _config.clear()
    _config.update(raw)


# ── App ───────────────────────────────────────────────────────────────────────

va = create_room_app(
    title="PODIUM - Multi-Agent Visual Analytics",
    version="2.0.0",
    base_dir=BASE,
    gateway_cls=PodiumGateway,
    agent_classes=_AGENT_CLASSES,
    seed=_seed,
    env_prefix="PODIUM",
    cors=True,
    watch_config=True,
    on_config_reload=_on_config_reload,
)
app, rooms = va.app, va.rooms
DEFAULT_ROOM = va.default_room

_FRONTEND_DIST = BASE.parent / "frontend" / "dist"


# ── PODIUM-specific REST ──────────────────────────────────────────────────────

@app.get("/state")
async def get_state(room: str = DEFAULT_ROOM):
    """Full WorldState snapshot for a room, excluding the raw dataset.

    """
    r = rooms.peek(room)
    if r is None:
        return {"status": "ok", "room": room, "active": False}
    snapshot = r.world_state.snapshot()
    return {k: v for k, v in snapshot.items() if k != "dataset"}


@app.get("/topology", response_class=HTMLResponse)
async def serve_topology():
    """Serve the live infrastructure topology visualizer (frontend/dist/topology.html)."""
    html_path = _FRONTEND_DIST / "topology.html"
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))


@app.get("/replay", response_class=HTMLResponse)
async def serve_replay():
    """Serve the session replay viewer (frontend/dist/replay.html)."""
    html_path = _FRONTEND_DIST / "replay.html"
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))
