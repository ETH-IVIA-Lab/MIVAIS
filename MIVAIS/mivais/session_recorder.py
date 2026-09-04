"""
SessionRecorder - Writes a timestamped JSONL recording of every MIVAIS session.

Event types recorded:
  snapshot       Full initial state including any large datasets (written once at startup)
  state_update   WorldState broadcast (lighter-weight, no excluded keys)
  cursor_update  Cursor snapshot, throttled to <= 20 fps
  connect        User connected  - {session_id, role}
  disconnect     User disconnected - {session_id}
  bus_message    Inter-agent bus message - {sender, topic, payload}
  user_action    Any user input action - {actor, action, data}

"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path


class SessionRecorder:
    """Appends timestamped events to a JSONL file for later replay."""

    CURSOR_MIN_INTERVAL_MS: float = 50.0   # cap cursor recording at 20 fps

    def __init__(self, recordings_dir: Path) -> None:
        recordings_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        self._path = recordings_dir / f"session_{ts}.jsonl"
        self._start_ms: float = time.monotonic() * 1000
        self._last_cursor_ms: float = 0.0
        self._f = open(self._path, "w", encoding="utf-8")

    # ── Core write ────────────────────────────────────────────────────────────

    def record(self, event_type: str, data: dict) -> None:
        """Append one event immediately to the file."""
        t = round(time.monotonic() * 1000 - self._start_ms)
        line = json.dumps({"t": t, "type": event_type, **data}, default=str)
        self._f.write(line + "\n")
        self._f.flush()

    # ── Specialised helpers ───────────────────────────────────────────────────

    def record_cursors(self, cursors: dict, connected_users: list) -> None:
        """Throttled cursor snapshot - skipped if called more than 20 times per second."""
        now = time.monotonic() * 1000
        if now - self._last_cursor_ms < self.CURSOR_MIN_INTERVAL_MS:
            return
        self._last_cursor_ms = now
        self.record("cursor_update", {
            "cursors": cursors,
            "connected_users": connected_users,
        })

    def record_state(
        self,
        world_state: dict,
        audit_log: list,
        cursors: dict,
        connected_users: list,
        *,
        full_snapshot: bool = False,
    ) -> None:
        """
        Record a WorldState broadcast.
        full_snapshot=True includes all keys, written once on first user connect.
        """
        event_type = "snapshot" if full_snapshot else "state_update"
        payload: dict = {
            "world_state": world_state,
            "audit_log": audit_log,
            "cursors": cursors,
            "connected_users": connected_users,
        }
        self.record(event_type, payload)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def close(self) -> None:
        """Flush and close the recording file."""
        try:
            self._f.close()
        except Exception:
            pass

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def filename(self) -> str:
        """Base filename of the current recording."""
        return self._path.name

    @property
    def path(self) -> Path:
        """Absolute path to the current recording file."""
        return self._path
