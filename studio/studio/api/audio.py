"""Audio chunk ingest endpoint."""
from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from datetime import datetime

from beanie import PydanticObjectId
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile

from studio.api.participant import PARTICIPANT_COOKIE
from studio.audio.recorder import ingest_chunk
from studio.models import Participant
from studio.settings import get_settings

log = logging.getLogger("studio.audio.api")

router = APIRouter(tags=["audio"])


_RATE_MAX_CHUNKS = 120          # generous: ~1 chunk/s for 2 min before throttling
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


@router.post("/ingest/audio-chunk")
async def ingest_audio_chunk(
    request: Request,
    chunk: UploadFile = File(...),
    seq: int = Form(...),
    recorder_started_wall: str = Form(...),
    chunk_started_wall: str = Form(...),
) -> dict:
    """Accept one MediaRecorder chunk + its timing metadata.

    The participant is identified by the same cookie that the rest of the
    participant flow uses; we never trust an explicit participant_id from the
    body. Returns the persisted AudioChunk's metadata for the client to log.
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
        raise HTTPException(429, "Too many audio chunks; slow down")

    max_bytes = get_settings().audio_max_chunk_bytes

    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            if int(content_length) > max_bytes + 65536:
                raise HTTPException(413, "Audio chunk too large")
        except ValueError:
            pass

    try:
        rs_wall = datetime.fromisoformat(recorder_started_wall.replace("Z", "+00:00"))
        cs_wall = datetime.fromisoformat(chunk_started_wall.replace("Z", "+00:00"))
    except Exception:
        raise HTTPException(400, "Invalid wall-clock timestamp")


    blob = await chunk.read(max_bytes + 1)
    if not blob:
        raise HTTPException(400, "Empty chunk")
    if len(blob) > max_bytes:
        raise HTTPException(413, "Audio chunk too large")

    try:
        saved = await ingest_chunk(
            session_id=participant.session_id,
            participant_id=participant.id,
            chunk_seq=int(seq),
            recorder_started_wall=rs_wall,
            chunk_started_wall=cs_wall,
            blob=blob,
            mime=chunk.content_type or "audio/webm;codecs=opus",
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))

    return {
        "chunk_id": str(saved.id),
        "seq": saved.chunk_seq,
        "t_ms_start": saved.t_ms_start,
        "size_bytes": saved.size_bytes,
        "queued_for_transcribe": True,
    }
