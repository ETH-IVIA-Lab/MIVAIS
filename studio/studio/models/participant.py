from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from beanie import Document, PydanticObjectId
from pydantic import BaseModel, Field
from pymongo import ASCENDING, IndexModel


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


PARTICIPANT_STATUSES = {
    "joined", "consented", "lobby", "ready", "in_session", "finished", "dropped",
}


class TaskRun(BaseModel):
    task_id: str
    task_index: int
    started_at: datetime
    ended_at: datetime | None = None
    answer: Any = None
    duration_ms: int | None = None
    timed_out: bool = False
    skipped: bool = False

    # Scoring (populated only when the task declares ground_truth)
    score: float | None = None
    correct: bool | None = None
    score_details: dict[str, Any] | None = None

    # task_step ids the participant (or Studio's auto-check engine) has marked
    # done while this task is active. Order preserved by insertion.
    checked_steps: list[str] = Field(default_factory=list)


class Participant(Document):
    session_id: PydanticObjectId
    study_id: PydanticObjectId

    anon_id: str                              # short, e.g. "p_8f3a"
    role: str | None = None                   # study-declared role id (not the MIVAIS agent_id)
    code_id: PydanticObjectId | None = None   # which Code the participant entered
    # External participant identifier (e.g. Prolific PID, MTurk worker id).
    # Captured from `?PROLIFIC_PID=`/`?pid=` on `/s/<CODE>`. Never displayed to
    # other participants; used by the researcher to link Studio anon_id ↔ pool id.
    external_id: str | None = None
    # Raw recruitment-platform query params kept verbatim for reconciliation
    # (e.g. {"PROLIFIC_PID": ..., "STUDY_ID": ..., "SESSION_ID": ...}).
    recruitment: dict = Field(default_factory=dict)

    status: str = "joined"

    # Outcome of the /p/biometric pairing step (only asked when the study
    # enables recording.biometric): "not_asked" | "connected" | "skipped" | "unsupported".
    biometric_status: str = "not_asked"

    # Outcome of the /p/run recording-consent gate (only asked when the study
    # enables recording.video): "not_asked" | "recording" | "declined_continue".
    recording_status: str = "not_asked"

    joined_at: datetime = Field(default_factory=_utcnow)
    consented_at: datetime | None = None
    ready_at: datetime | None = None
    finished_at: datetime | None = None

    # Per-task local task_index for sync'd advance: each participant has their
    # own pointer, but session.current_task_index gates which task they can see.
    last_seen_task_index: int = 0

    # Counterbalanced task path. Populated on participant registration from
    # study.block_order; mutated by conditional flow as the participant moves.
    # Each entry is a task id; the participant advances through this list.
    applied_task_order: list[str] = Field(default_factory=list)

    # Random seed used to shuffle this participant's task order (when
    # block_order=random). Recorded so a replay can reconstruct what they saw.
    shuffle_seed: int | None = None

    # Singleplayer cursor into applied_task_order. Linear advancement is
    # flow_pointer += 1; conditional flow can leap to any valid position.
    flow_pointer: int = 0

    task_runs: list[TaskRun] = Field(default_factory=list)

    user_agent: str | None = None
    ip_hash: str | None = None

    class Settings:
        name = "participants"
        indexes = [
            IndexModel([("session_id", ASCENDING)]),
            IndexModel([("anon_id", ASCENDING)], unique=True),
        ]
