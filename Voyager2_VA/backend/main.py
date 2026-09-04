"""
Voyager 2 - MIVAIS-based visual analytics server

Usage:
    cd backend
    python -m uvicorn main:app --port 8001
"""

from __future__ import annotations
import json, os
from pathlib import Path

from mivais.world_state import WorldState
from mivais.gateway import Gateway
from mivais.rooms import Room, create_room_app

from agents.recommendation_agent import RecommendationAgent
from agents.insight_agent import InsightAgent
from spec_utils import infer_field_types, generate_univariate_summaries, view_to_spec

BASE = Path(__file__).parent
DATA_DIR = BASE / "data"

AGENT_CLASSES = {
    "recommendation_agent": RecommendationAgent,
    "insight_agent": InsightAgent,
}


# ── Gateway subclass ──────────────────────────────────────────────────────────

class VoyagerGateway(Gateway):
    """Handles Voyager 2-specific WebSocket actions."""

    _broadcast_exclude_keys = frozenset({"dataset"})

    async def _handle_action(self, agent_id: str, session_id: str, data: dict) -> None:
        action = data.get("action", "")

        if action == "update_spec":
            spec = data.get("spec")
            if spec:
                self._ws.write(agent_id, "current_spec", spec)

        elif action == "load_dataset":
            
            rows = data.get("dataset")
            name = "".join(c for c in str(data.get("name") or "custom") if c.isalnum() or c in "-_ .")[:40] or "custom"
            if not isinstance(rows, list) or not rows:
                return
            rows = [r for r in rows[:5000] if isinstance(r, dict)]
            if not rows:
                return
            data_fields = infer_field_types(rows)
            self._ws.system_write("dataset", rows)
            self._ws.system_write("dataset_name", name)
            self._ws.system_write("data_fields", data_fields)
            self._ws.system_write("current_spec", {"mark": "?", "encodings": []})
            self._ws.system_write("focus_view", None)
            self._ws.system_write("wildcard_results", [])
            self._ws.system_write("field_suggestions", [])
            self._ws.system_write("alt_encodings", [])
            self._ws.system_write("related_summaries", generate_univariate_summaries(data_fields))
            self._ws.system_write("bookmarks", [])  # they referenced the old fields
            self._ws.system_write("filters", [])
            
            for sid in list(self._connections):
                await self._push_to(sid, msg_type="initial_state")

        elif action == "set_filters":
            filters = data.get("filters")
            if isinstance(filters, list):
                self._ws.write(agent_id, "filters", filters[:12])

        elif action == "specify_view":
            view = data.get("view")
            if view:
                partial = view_to_spec(view)
                self._ws.write(agent_id, "current_spec", partial)

        elif action == "select_insight_action":
            suggestion = data.get("suggestion")
            if suggestion:
                await self._bus.publish(agent_id, "insight.action_selected", {"suggestion": suggestion})

        elif action == "add_bookmark":
            bookmarks = list(self._ws.get("bookmarks") or [])
            bookmark = {
                "view": data.get("view"),
                "note": data.get("note", ""),
                "by": agent_id,
            }
            bookmarks.append(bookmark)
            self._ws.write(agent_id, "bookmarks", bookmarks)

        elif action == "update_bookmark_note":
            idx = data.get("index")
            note = data.get("note", "")
            bookmarks = list(self._ws.get("bookmarks") or [])
            if isinstance(idx, int) and 0 <= idx < len(bookmarks):
                bookmarks[idx]["note"] = note
                self._ws.write(agent_id, "bookmarks", bookmarks)

        elif action == "remove_bookmark":
            idx = data.get("index")
            bookmarks = list(self._ws.get("bookmarks") or [])
            if isinstance(idx, int) and 0 <= idx < len(bookmarks):
                bookmarks.pop(idx)
                self._ws.write(agent_id, "bookmarks", bookmarks)


# ── Dataset loading ───────────────────────────────────────────────────────────
#


DEFAULT_DATASET = os.environ.get("VOYAGER_DEFAULT_DATASET", "cars")


_dataset_cache: dict[str, list] = {}


def available_datasets() -> list[str]:
    return sorted(p.stem for p in DATA_DIR.glob("*.json"))


def resolve_dataset_name(requested: str | None) -> str:
    """Sanitize a client-supplied dataset name; fall back to the default."""
    cleaned = "".join(c for c in (requested or "") if c.isalnum() or c in "-_")[:64]
    if cleaned and (DATA_DIR / f"{cleaned}.json").exists():
        return cleaned
    return DEFAULT_DATASET


def _get_dataset(name: str) -> list:
    dataset = _dataset_cache.get(name)
    if dataset is None:
        path = DATA_DIR / f"{name}.json"
        if not path.exists():
            print(f"[dataset] not found: {path}")
            return []
        with open(path, encoding="utf-8") as f:
            dataset = json.load(f)
        # Clean: remove rows with too many nulls
        cols = list(dataset[0].keys()) if dataset else []
        dataset = [row for row in dataset if sum(1 for c in cols if row.get(c) is not None) >= len(cols) * 0.5]
        _dataset_cache[name] = dataset
    return dataset


def _load_dataset_into(world_state: WorldState, dataset_name: str) -> list:
    """Load ``data/<dataset_name>.json`` into ``world_state`` and seed the
    initial keys. Returns the inferred data fields (used to generate
    univariate summaries).
    """
    dataset = _get_dataset(dataset_name)
    data_fields = infer_field_types(dataset)

    world_state.system_write("dataset", dataset)
    world_state.system_write("dataset_name", dataset_name)
    world_state.system_write("data_fields", data_fields)
    world_state.system_write("current_spec", {"mark": "?", "encodings": []})
    world_state.system_write("focus_view", None)
    world_state.system_write("wildcard_results", [])
    world_state.system_write("related_summaries", [])
    world_state.system_write("field_suggestions", [])
    world_state.system_write("alt_encodings", [])
    world_state.system_write("bookmarks", [])
    world_state.system_write("filters", [])

    return data_fields


def _seed(room: Room, params: dict) -> None:
    """Seed one room's WorldState with its dataset (chosen by the connect that
    created the room via ``?dataset=``)."""
    dataset_name = resolve_dataset_name(params.get("dataset", ""))
    data_fields = _load_dataset_into(room.world_state, dataset_name)
    if data_fields:
        summaries = generate_univariate_summaries(data_fields)
        room.world_state.system_write("related_summaries", summaries)
    print(f"[room {room.room_id}] dataset: {dataset_name}")


# ── App ───────────────────────────────────────────────────────────────────────

va = create_room_app(
    title="Voyager 2 (MIVAIS)",
    base_dir=BASE,
    gateway_cls=VoyagerGateway,
    agent_classes=AGENT_CLASSES,
    seed=_seed,
    env_prefix="VOYAGER",
)
app, rooms = va.app, va.rooms


# ── Voyager-specific REST ─────────────────────────────────────────────────────

@app.get("/datasets")
async def list_datasets():
    """Datasets available for ``?dataset=<name>`` (one per data/<name>.json)."""
    return {"datasets": available_datasets(), "default": DEFAULT_DATASET}
