from __future__ import annotations

from datetime import datetime, timezone

from beanie import Document, PydanticObjectId
from pydantic import BaseModel, Field
from pymongo import ASCENDING, DESCENDING, IndexModel


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class VAProcessInfo(BaseModel):
    pid: int | None = None
    port: int | None = None
    recording_dir: str | None = None
    jsonl_path: str | None = None
    iframe_url: str | None = None    # so we can reattach after restart
    internal_url: str | None = None  # Docker-network URL for server-side connections
    variant: str | None = None       # which VA variant this process is


# Status values: pending → spawning → running → completed | failed | abandoned
SESSION_STATUSES = {
    "pending", "lobby", "spawning", "running",
    "completed", "failed", "abandoned",
    # Studio went down while this session was active; the participant cookies
    # are still valid but the VA process is gone. Surfaces in the admin UI so
    # researchers know to either resume manually or write the session off.
    "interrupted",
}


class Session(Document):
    study_id: PydanticObjectId
    mode: str = "singleplayer"
    status: str = "pending"

    created_at: datetime = Field(default_factory=_utcnow)
    # va_started_at = wall-clock the *first* VA in this session was spawned.
    # All `t_ms` values across the session are measured from this anchor, so
    # the multiple-VA case still produces a single coherent timeline.
    va_started_at: datetime | None = None
    va_jsonl_offset_ms: int = 0
    ended_at: datetime | None = None
    # Set when Studio restarts while this session was active.
    interrupted_at: datetime | None = None

    # One VAProcessInfo per declared va_system, keyed by va_system_id.
    # Studies with only one system end up with a single entry here.
    vas: dict[str, VAProcessInfo] = Field(default_factory=dict)
    current_task_index: int = 0
    failure_reason: str | None = None

    # Researcher annotations on this session (admin-only). Each entry:
    # { author, t_ms, wall_clock, text } — used for qualitative context in analytics.
    notes: list[dict] = Field(default_factory=list)
    # Per-instant markers placed on the replay timeline by admins. Each entry:
    # { author, t_ms, kind, label, wall_clock } — rendered as flags above the
    # replay scrubber. ``kind`` is a short free-form tag (e.g. "stuck", "aha").
    markers: list[dict] = Field(default_factory=list)

    # Free-form tags admins attach for filtering / cohorting in analytics
    # (e.g. ["woz", "pilot-batch-1"]). Kept short — sorting and grouping helper.
    tags: list[str] = Field(default_factory=list)

    # Unguessable token that makes this session's replay publicly viewable at
    # /admin/shared/<token> (read-only: timeline + video + markers, no admin
    # actions). None = not shared. Minted/revoked from the admin replay page.
    share_token: str | None = None
    # Per-admin tagging for inter-rater reliability. Map of
    # ``{admin_username: [tag, ...]}`` — `tags` above remains the merged view
    # so analytics filters keep working. Kappa is computed across the rater
    # axis of this map (see studio.stats.cohens_kappa).
    tags_by_author: dict[str, list[str]] = Field(default_factory=dict)

    # Counterbalancing in multiplayer: the cohort shares one applied task path
    # so session.current_task_index references a position here. Singleplayer
    # sessions don't use this — each participant carries their own order.
    applied_task_order: list[str] = Field(default_factory=list)
    shuffle_seed: int | None = None

    # Frozen study definition this session ran against. Captured at create
    # time so a session remains reproducible even if the study YAML is later
    # edited or archived. ``study_yaml_hash`` mirrors Study.yaml_hash at the
    # moment of capture.
    study_snapshot: dict = Field(default_factory=dict)
    study_yaml_hash: str = ""

    class Settings:
        name = "sessions"
        indexes = [
            IndexModel([("study_id", ASCENDING), ("created_at", DESCENDING)]),
            IndexModel([("status", ASCENDING)]),
        ]

    def t_ms_now(self) -> int:
        """Session-relative time in ms (0 if VA has not started yet)."""
        if self.va_started_at is None:
            return 0
        started = self.va_started_at.replace(tzinfo=None) if self.va_started_at.tzinfo else self.va_started_at
        delta = _utcnow() - started
        return int(delta.total_seconds() * 1000)
