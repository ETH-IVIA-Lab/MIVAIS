"""Heart-rate batch ingest endpoint."""
from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from datetime import datetime

from beanie import PydanticObjectId
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from studio.api.participant import PARTICIPANT_COOKIE
from studio.biometric.recorder import ingest_chunk
from studio.models import Participant

log = logging.getLogger("studio.biometric.api")

router = APIRouter(tags=["biometric"])

# Per-participant sliding-window rate limit, same shape as audio/video ingest.
_RATE_MAX_CHUNKS = 60           # one ~5s batch/s sustained is already generous
_RATE_WINDOW_SECONDS = 60.0
_ingest_times: dict[str, deque] = defaultdict(deque)


def _rate_ok(participant_id: str) -> bool:
    now = time.monotonic()
    dq = _ingest_times[participant_id]
    while dq and now - dq[0] > _RATE_WINDOW_SECONDS:
        dq.popleft()
    if len(dq) >= _RATE_MAX_CHUNKS:
        return False
    dq.append(now)
    return True


class HRSampleIn(BaseModel):
    t_wall: str
    bpm: int


class BiometricChunkIn(BaseModel):
    seq: int
    batch_started_wall: str
    samples: list[HRSampleIn]


def _parse_iso(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        raise HTTPException(400, "Invalid wall-clock timestamp")


@router.post("/ingest/biometric-chunk")
async def ingest_biometric_chunk(request: Request, body: BiometricChunkIn) -> dict:
    """Accept one batch of BLE heart-rate samples + timing metadata.

    The participant is identified by the same cookie the rest of the
    participant flow uses; we never trust an explicit participant_id from the
    body. Returns the persisted BiometricChunk's metadata for the client to log.
    """
    pid = request.cookies.get(PARTICIPANT_COOKIE)
    if not pid:
        raise HTTPException(401, "No active participant")
    try:
        participant_oid = PydanticObjectId(pid)
    except Exception:
        raise HTTPException(401, "Bad participant cookie")

    participant = await Participant.get(participant_oid)
    if participant is None:
        raise HTTPException(401, "Participant not found")

    if participant.status not in ("in_session", "ready", "lobby", "consented"):
        raise HTTPException(400, f"Participant is not in an active session (status={participant.status})")

    if not _rate_ok(str(participant.id)):
        raise HTTPException(429, "Too many biometric batches; slow down")

    if not body.samples:
        raise HTTPException(400, "Empty batch")

    batch_started_wall = _parse_iso(body.batch_started_wall)
    samples = [(_parse_iso(s.t_wall), s.bpm) for s in body.samples]

    try:
        saved = await ingest_chunk(
            session_id=participant.session_id,
            participant_id=participant.id,
            chunk_seq=body.seq,
            batch_started_wall=batch_started_wall,
            samples=samples,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))

    return {
        "chunk_id": str(saved.id),
        "seq": saved.chunk_seq,
        "n_samples": len(saved.samples),
        "t_ms_start": saved.t_ms_start,
    }
