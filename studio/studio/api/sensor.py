"""
External, non-browser sensor batch ingest endpoint.

The pusher here is typically a separate device (a lab PC running a vendor SDK, a companion app). 
Auth is a per-participant ``SensorIngestToken`` (see
``studio.models.sensor_token``), minted by an admin in
``POST /api/admin/sessions/{sid}/participants/{pid}/sensor-tokens``.
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from studio.models import SensorIngestToken, Session, Study
from studio.models.api_key import hash_token
from studio.sensors.recorder import ingest_sensor_chunk

log = logging.getLogger("studio.sensors.api")

router = APIRouter(tags=["sensor"])


_RATE_MAX_CHUNKS = 60           # one ~5s batch/s sustained is already generous
_RATE_WINDOW_SECONDS = 60.0
_ingest_times: dict[str, deque] = defaultdict(deque)


async def _session_accepts_ingest(session: Session) -> bool:
    """Ingestion stays open for the life of the study, not the session:
    researchers may add offline-sensor data at any point until the study
    itself is archived."""
    study = await Study.get(session.study_id)
    return study is not None and not study.archived


def _rate_ok(token_id: str) -> bool:
    now = time.monotonic()
    dq = _ingest_times[token_id]
    while dq and now - dq[0] > _RATE_WINDOW_SECONDS:
        dq.popleft()
    if len(dq) >= _RATE_MAX_CHUNKS:
        return False
    dq.append(now)
    return True


async def _require_sensor_token(request: Request) -> SensorIngestToken:
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        raise HTTPException(401, "Missing bearer token (Authorization: Bearer <token>)")
    token = auth[7:].strip()
    sensor_token = await SensorIngestToken.find_one(SensorIngestToken.token_hash == hash_token(token))
    if sensor_token is None or sensor_token.revoked:
        raise HTTPException(401, "Invalid or revoked sensor ingest token")

    session = await Session.get(sensor_token.session_id)
    if session is None or not await _session_accepts_ingest(session):
        raise HTTPException(400, "Study is archived; sensor ingest is closed")

    sensor_token.last_used_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await sensor_token.save()
    return sensor_token


class SensorSampleIn(BaseModel):
    t_wall: str
    value: float


class SensorChunkIn(BaseModel):
    channel: str
    unit: str | None = None
    seq: int
    batch_started_wall: str
    samples: list[SensorSampleIn]


def _parse_iso(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        raise HTTPException(400, "Invalid wall-clock timestamp")


@router.post("/ingest/sensor-chunk")
async def ingest_sensor_chunk_route(request: Request, body: SensorChunkIn) -> dict:
    """Accept one batch of external sensor samples for a single named channel.

    The session + participant are identified by the sensor ingest token; we
    never trust an explicit session/participant id from the body. Returns
    the persisted SensorChunk's metadata for the client to log.
    """
    sensor_token = await _require_sensor_token(request)

    if not _rate_ok(str(sensor_token.id)):
        raise HTTPException(429, "Too many sensor batches; slow down")

    if not body.channel.strip():
        raise HTTPException(400, "channel is required")
    if not body.samples:
        raise HTTPException(400, "Empty batch")

    batch_started_wall = _parse_iso(body.batch_started_wall)
    samples = [(_parse_iso(s.t_wall), s.value) for s in body.samples]

    try:
        saved = await ingest_sensor_chunk(
            session_id=sensor_token.session_id,
            participant_id=sensor_token.participant_id,
            channel=body.channel.strip(),
            unit=body.unit,
            chunk_seq=body.seq,
            batch_started_wall=batch_started_wall,
            samples=samples,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))

    return {
        "chunk_id": str(saved.id),
        "channel": saved.channel,
        "seq": saved.chunk_seq,
        "n_samples": len(saved.samples),
        "t_ms_start": saved.t_ms_start,
    }
