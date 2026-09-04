from __future__ import annotations

from datetime import datetime, timezone

from beanie import Document, PydanticObjectId
from pydantic import Field
from pymongo import ASCENDING, IndexModel


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Code(Document):
    code: str                           # short alphanumeric, e.g. "PILOT01"
    study_id: PydanticObjectId

    # Optional role pre-binding. When set, every participant who joins via this
    # code is automatically assigned this role (typical: WoZ wizard code).
    # When None, the participant picks from the study's selectable roles on join.
    role: str | None = None

    # Multiplayer cohort: for studies with mode=multiplayer, all participants
    # joining the same code share one session. The first join creates it; later
    # joins attach to the existing session until participants_required is filled.
    multiplayer_session_id: PydanticObjectId | None = None

    expires_at: datetime | None = None
    max_uses: int | None = None
    uses: int = 0
    active: bool = True
    created_at: datetime = Field(default_factory=_utcnow)

    class Settings:
        name = "codes"
        indexes = [
            IndexModel([("code", ASCENDING)], unique=True),
            IndexModel([("study_id", ASCENDING)]),
        ]

    def is_usable(self) -> bool:
        if not self.active:
            return False
        if self.expires_at and self.expires_at < _utcnow():
            return False
        if self.max_uses is not None and self.uses >= self.max_uses:
            return False
        return True
