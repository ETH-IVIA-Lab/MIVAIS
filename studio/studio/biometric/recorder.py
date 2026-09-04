"""Server-side heart-rate batch ingest.

The participant's browser pairs a BLE heart-rate strap (Web Bluetooth,
standard GATT Heart Rate Service) and POSTs a small JSON batch of samples to
/ingest/biometric-chunk every ~5 seconds. This module:
  1. Validates the batch + computes each sample's session-relative t_ms
  2. Inserts a BiometricChunk doc
  3. Inserts a Studio Event row (source=studio, type=biometric_chunk_received)
"""
from __future__ import annotations

import logging
from datetime import datetime

from beanie import PydanticObjectId

from studio.models import BiometricChunk, Event, Participant, Session, Study
from studio.models.biometric_chunk import HRSample
from studio.models.event import SOURCE_STUDIO
from studio.timing import to_naive, utcnow_naive, wall_to_session_ms

log = logging.getLogger("studio.biometric")

# Generous over-provision for a 5s batch at any plausible notification rate.
MAX_SAMPLES_PER_BATCH = 600


async def ingest_chunk(
    session_id: PydanticObjectId,
    participant_id: PydanticObjectId,
    chunk_seq: int,
    batch_started_wall: datetime,
    samples: list[tuple[datetime, int]],
) -> BiometricChunk:
    """Persist one heart-rate batch and return the inserted BiometricChunk.

    ``samples`` is a list of (wall-clock timestamp, bpm) pairs, already parsed
    by the caller (HTTP route), which is also responsible for verifying the
    participant token and the request body shape.
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
    if not (study.recording or {}).get("biometric", False):
        raise ValueError("biometric capture is disabled for this study")

    # Session-relative timing per DESIGN §6.3, same anchor as audio/video.
    hr_samples: list[HRSample] = [
        HRSample(t_ms=wall_to_session_ms(session, wall), bpm=bpm) for wall, bpm in samples
    ]

    chunk = BiometricChunk(
        session_id=session.id,
        participant_id=participant.id,
        chunk_seq=chunk_seq,
        batch_started_wall=to_naive(batch_started_wall) or utcnow_naive(),
        t_ms_start=min(s.t_ms for s in hr_samples),
        t_ms_end=max(s.t_ms for s in hr_samples),
        samples=hr_samples,
    )
    await chunk.insert()

    task_id = None
    if participant.task_runs and participant.task_runs[-1].ended_at is None:
        task_id = participant.task_runs[-1].task_id

    avg_bpm = round(sum(s.bpm for s in hr_samples) / len(hr_samples), 1)
    await Event(
        study_id=session.study_id,
        session_id=session.id,
        participant_id=participant.id,
        task_id=task_id,
        t_ms=chunk.t_ms_start,
        source=SOURCE_STUDIO,
        type="biometric_chunk_received",
        meta={"chunk_id": str(chunk.id), "n_samples": len(hr_samples), "avg_bpm": avg_bpm},
    ).insert()

    return chunk
