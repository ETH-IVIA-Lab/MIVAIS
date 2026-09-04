"""Study document — the resolved YAML for one study."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from beanie import Document
from pydantic import Field
from pymongo import ASCENDING, DESCENDING, IndexModel


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Study(Document):
    slug: str
    name: str
    version: int = 1
    mode: str = "singleplayer"            # singleplayer | multiplayer
    participants_required: int | None = None

    consent_text_md: str = ""
    consent_text_md_by_lang: dict[str, str] = Field(default_factory=dict)

    # Verbatim resolved YAML pieces (validated by config/schemas.py before storage).
    # va_systems is a map id → VAConfig dict; primary_va_system names the default.
    va_systems: dict[str, dict[str, Any]] = Field(default_factory=dict)
    primary_va_system: str | None = None
    roles: list[dict[str, Any]] = Field(default_factory=list)
    advance_policy: str = "all"
    recording: dict[str, Any] = Field(default_factory=dict)
    ui: dict[str, Any] = Field(default_factory=dict)
    blocks: list[dict[str, Any]] = Field(default_factory=list)
    # Declarative behavioral metrics (see studio.metrics + MetricConfig).
    metrics: list[dict[str, Any]] = Field(default_factory=list)
    # Researcher-defined replay-timeline event taxonomy (see config.schemas.ReplayConfig).
    replay: dict[str, Any] = Field(default_factory=dict)
    # Counterbalancing + parameters added in the flow/expressiveness phase.
    block_order: str = "declared"
    block_orders: list[list[str]] = Field(default_factory=list)
    parameters: dict[str, Any] = Field(default_factory=dict)
    completion_redirect_url: str | None = None
    completion_code: str | None = None

    # Path of the source study directory, relative to settings.studies_dir.
    # Empty when the study was loaded inline (e.g. from a test).
    study_dir: str = ""
    yaml_hash: str = ""

    created_at: datetime = Field(default_factory=_utcnow)
    archived: bool = False

    class Settings:
        name = "studies"
        indexes = [
            IndexModel([("slug", ASCENDING)], unique=True),
            IndexModel([("archived", ASCENDING), ("created_at", DESCENDING)]),
        ]

    def all_tasks(self) -> list[dict[str, Any]]:
        """Flatten blocks into an ordered task list."""
        return [task for block in self.blocks for task in block.get("tasks", [])]
