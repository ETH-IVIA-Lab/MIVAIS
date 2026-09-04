"""
Server-side external sensor batch ingest.

A non-browser client (a lab PC running a vendor SDK, a companion app, ...)
holds a per-participant ``SensorIngestToken`` (see ``studio.api.sensor``) and
POSTs small JSON batches of named-channel samples to
``/ingest/sensor-chunk``. This module:
  1. Validates the batch + computes each sample's session-relative t_ms
  2. Inserts a SensorChunk doc
  3. Inserts a Studio Event row (source=studio, type=sensor_chunk_received)

"""
from __future__ import annotations

import logging
from datetime import datetime

from beanie import PydanticObjectId

from studio.models import Event, Participant, SensorChunk, Session, Study
from studio.models.event import SOURCE_STUDIO
from studio.models.sensor_chunk import SensorSample
from studio.timing import to_naive, utcnow_naive, wall_to_session_ms

log = logging.getLogger("studio.sensors")

# Generous over-provision for a batch at any plausible sampling rate.
MAX_SAMPLES_PER_BATCH = 600


async def ingest_sensor_chunk(
    session_id: PydanticObjectId,
    participant_id: PydanticObjectId,
    channel: str,
    unit: str | None,
    chunk_seq: int,
    batch_started_wall: datetime,
    samples: list[tuple[datetime, float]],
) -> SensorChunk:
    """Persist one external-sensor batch and return the inserted SensorChunk.

    ``samples`` is a list of (wall-clock timestamp, value) pairs, already
    parsed by the caller (HTTP route), which is also responsible for
    verifying the sensor ingest token and the request body shape
    """
    if not samples:
        raise ValueError("empty batch")
    if len(samples) > MAX_SAMPLES_PER_BATCH:
        raise ValueError(f"batch of {len(samples)} samples exceeds cap {MAX_SAMPLES_PER_BATCH}")

    session = await Session.get(session_id)
    if session is None:
        raise ValueError("session not found")
    participant = await Participant.get(participant_id)
    if participant is None or participant.session_id != session_id:
        raise ValueError("participant not part of this session")
    study = await Study.get(session.study_id)
    if study is None:
        raise ValueError("study gone")
    if not (study.recording or {}).get("external_sensor", False):
        raise ValueError("external sensor capture is disabled for this study")

    # Session-relative timing per DESIGN §6.3, same anchor as audio/biometric.
    sensor_samples: list[SensorSample] = [
        SensorSample(t_ms=wall_to_session_ms(session, wall), value=value) for wall, value in samples
    ]

    chunk = SensorChunk(
        session_id=session.id,
        participant_id=participant.id,
        channel=channel,
        unit=unit,
        chunk_seq=chunk_seq,
        batch_started_wall=to_naive(batch_started_wall) or utcnow_naive(),
        t_ms_start=min(s.t_ms for s in sensor_samples),
        t_ms_end=max(s.t_ms for s in sensor_samples),
        samples=sensor_samples,
    )
    await chunk.insert()

    task_id = None
    if participant.task_runs and participant.task_runs[-1].ended_at is None:
        task_id = participant.task_runs[-1].task_id

    avg_value = round(sum(s.value for s in sensor_samples) / len(sensor_samples), 4)
    await Event(
        study_id=session.study_id,
        session_id=session.id,
        participant_id=participant.id,
        task_id=task_id,
        t_ms=chunk.t_ms_start,
        source=SOURCE_STUDIO,
        type="sensor_chunk_received",
        meta={
            "chunk_id": str(chunk.id),
            "channel": channel,
            "n_samples": len(sensor_samples),
            "avg_value": avg_value,
        },
    ).insert()

    return chunk
