"""Screen+mic video chunk ingest + admin playback serving.

Ingest mirrors ``studio.api.audio`` (cookie-authed, rate-limited, size-capped).
Serving concatenates one MediaRecorder run's WebM chunks (in seq order) into a
single playable file, streamed only to authenticated admins.
"""
from __future__ import annotations

import logging
import os
import time
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path

from beanie import PydanticObjectId
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from studio.api.participant import PARTICIPANT_COOKIE
from studio.auth.deps import optional_admin
from studio.models import Participant, Session, Study, VideoChunk
from studio.settings import get_settings
from studio.video import transcribe as video_transcribe
from studio.video.recorder import ingest_video_chunk

log = logging.getLogger("studio.video.api")

router = APIRouter(tags=["video"])

# Per-participant sliding-window rate limit (single uvicorn worker by design).
_RATE_MAX_CHUNKS = 120          # ~1 chunk/s for 2 min before throttling
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


@router.post("/ingest/video-chunk")
async def ingest_video_chunk_route(
    request: Request,
    chunk: UploadFile = File(...),
    seq: int = Form(...),
    recorder_started_wall: str = Form(...),
    chunk_started_wall: str = Form(...),
) -> dict:
    """Accept one MediaRecorder video chunk + its timing metadata.

    The participant is identified by the same cookie as the rest of the flow;
    we never trust an explicit participant_id from the body.
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
        raise HTTPException(429, "Too many video chunks; slow down")

    max_bytes = get_settings().video_max_chunk_bytes

    # Cheap up-front rejection: the whole multipart body must not dwarf one chunk.
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            if int(content_length) > max_bytes + 65536:
                raise HTTPException(413, "Video chunk too large")
        except ValueError:
            pass

    try:
        rs_wall = datetime.fromisoformat(recorder_started_wall.replace("Z", "+00:00"))
        cs_wall = datetime.fromisoformat(chunk_started_wall.replace("Z", "+00:00"))
    except Exception:
        raise HTTPException(400, "Invalid wall-clock timestamp")

    # Bounded read so a lying/absent Content-Length can't make us buffer forever.
    blob = await chunk.read(max_bytes + 1)
    if not blob:
        raise HTTPException(400, "Empty chunk")
    if len(blob) > max_bytes:
        raise HTTPException(413, "Video chunk too large")

    try:
        saved = await ingest_video_chunk(
            session_id=participant.session_id,
            participant_id=participant.id,
            chunk_seq=int(seq),
            recorder_started_wall=rs_wall,
            chunk_started_wall=cs_wall,
            blob=blob,
            mime=chunk.content_type or "video/webm",
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))

    return {
        "chunk_id": str(saved.id),
        "seq": saved.chunk_seq,
        "run_id": saved.run_id,
        "t_ms_start": saved.t_ms_start,
        "size_bytes": saved.size_bytes,
    }


# ── admin playback ───────────────────────────────────────────────────────────

async def _primary_run_chunks(session_id: PydanticObjectId) -> list[VideoChunk]:
    """Return the chunks of the recorder run with the most chunks for a session.

    A normal session is one run; a shell refresh creates extra (usually short)
    runs — we serve the dominant one. Chunks are returned ordered by seq.
    """
    chunks = await VideoChunk.find(VideoChunk.session_id == session_id).to_list()
    if not chunks:
        return []
    by_run: dict[str, list[VideoChunk]] = defaultdict(list)
    for c in chunks:
        by_run[c.run_id].append(c)
    primary = max(by_run.values(), key=len)
    primary.sort(key=lambda c: c.chunk_seq)
    return primary


async def _run_chunks(session_id: PydanticObjectId, run_id: str | None = None) -> list[VideoChunk]:
    """Chunks for a specific recorder run — i.e. one participant's POV — or the
    primary run when ``run_id`` is None. Ordered by seq."""
    if not run_id:
        return await _primary_run_chunks(session_id)
    chunks = await VideoChunk.find(
        VideoChunk.session_id == session_id, VideoChunk.run_id == run_id
    ).to_list()
    chunks.sort(key=lambda c: c.chunk_seq)
    return chunks


def _remux_webm(src: Path, dst: Path) -> bool:
    """Rewrite a concatenated live-recorded WebM so it carries a proper Segment
    duration + index.

    MediaRecorder output has ``duration=None``, which leaves the <video> element
    unable to seek or know the total length (it appears "stuck on the first
    part"). PyAV (a faster-whisper dependency, always present) is used as an
    in-process ffmpeg remux. Returns True on success.
    """
    try:
        import av
    except Exception:
        return False
    inp = out = None
    try:
        inp = av.open(str(src))
        out = av.open(str(dst), "w", format="webm")
        smap = {s.index: out.add_stream_from_template(s) for s in inp.streams}
        for pkt in inp.demux():
            if pkt.dts is None:
                continue
            pkt.stream = smap[pkt.stream.index]
            out.mux(pkt)
        return True
    except Exception:
        return False
    finally:
        for c in (out, inp):
            try:
                if c is not None:
                    c.close()
            except Exception:
                pass


def _build_combined(chunks: list[VideoChunk]) -> Path | None:
    """Concatenate a run's chunk files (seq order) into a cached, seekable
    combined.webm.

    Byte-concatenating the timeslice blobs of one MediaRecorder run reproduces
    the original live WebM stream — but with no Segment duration, so the player
    can't seek or show the length. We then remux it so duration + seeking work.
    Cached next to the chunks; rebuilt when a newer chunk appears.
    """
    paths = [Path(c.file_path) for c in chunks if c.file_path and Path(c.file_path).exists()]
    if not paths:
        return None
    parent = paths[0].parent
    combined = parent / "combined.webm"
    newest_chunk_mtime = max(os.path.getmtime(p) for p in paths)
    if combined.exists() and os.path.getmtime(combined) >= newest_chunk_mtime:
        return combined

    raw = parent / "combined.raw.webm"
    with open(raw, "wb") as out:
        for p in paths:
            out.write(p.read_bytes())

    tmp = parent / "combined.tmp.webm"
    if _remux_webm(raw, tmp):
        os.replace(tmp, combined)
        try:
            raw.unlink()
        except Exception:
            pass
    else:
        # Remux unavailable/failed: serve the raw concat (plays, limited seek).
        os.replace(raw, combined)
    return combined


@router.get("/admin/sessions/{session_id}/video", response_model=None)
async def serve_session_video(request: Request, session_id: str, run: str | None = None) -> FileResponse:
    """Stream a session's combined recording to a logged-in admin (Range-capable).

    ``?run=<run_id>`` selects a specific participant's POV; default = primary.
    """
    if optional_admin(request) is None:
        raise HTTPException(401, "Admin login required")
    try:
        sid = PydanticObjectId(session_id)
    except Exception:
        raise HTTPException(400, "Invalid session id")

    chunks = await _run_chunks(sid, run)
    if not chunks:
        raise HTTPException(404, "No recording for this session")
    combined = _build_combined(chunks)
    if combined is None or not combined.exists():
        raise HTTPException(404, "Recording files are missing")
    # FileResponse honours the Range header → the <video> element can seek.
    return FileResponse(str(combined), media_type="video/webm", filename=f"session_{session_id}.webm")


# ── transcription (subtitles + transcript panel) ─────────────────────────────

@router.get("/admin/sessions/{session_id}/transcript", response_model=None)
async def session_transcript(request: Request, session_id: str, run: str | None = None) -> dict:
    """Return the recording's transcript, kicking off background transcription
    on first request. status ∈ {ready, transcribing, disabled, none}.

    ``?run=<run_id>`` selects a specific participant's POV; default = primary.
    """
    if optional_admin(request) is None:
        raise HTTPException(401, "Admin login required")
    try:
        sid = PydanticObjectId(session_id)
    except Exception:
        raise HTTPException(400, "Invalid session id")
    session = await Session.get(sid)
    if session is None:
        raise HTTPException(404, "Session not found")
    study = await Study.get(session.study_id)
    rec = (study.recording or {}) if study is not None else {}
    # No mic in the recording (audio: none) → the video is silent; there is
    # nothing to transcribe.
    if (rec.get("transcribe") is not True or rec.get("video", "none") == "none"
            or rec.get("audio", "none") == "none"):
        return {"status": "disabled", "segments": []}

    chunks = await _run_chunks(sid, run)
    if not chunks:
        return {"status": "none", "segments": []}
    combined = _build_combined(chunks)
    if combined is None or not combined.exists():
        return {"status": "none", "segments": []}

    cdir = combined.parent
    st, segs = video_transcribe.status(cdir)
    if st == "none":
        model = rec.get("whisper_model") or get_settings().whisper_default_model
        lang = rec.get("whisper_language") or get_settings().whisper_default_language
        video_transcribe.ensure_started(cdir, combined, model, lang)
        st = "transcribing"
    sub_src = f"/admin/sessions/{session_id}/subtitles.vtt" + (f"?run={run}" if run else "")
    return {"status": st, "segments": segs, "src": sub_src}


@router.get("/admin/sessions/{session_id}/subtitles.vtt", response_model=None)
async def session_subtitles(request: Request, session_id: str, run: str | None = None) -> FileResponse:
    """Serve the recording's WebVTT subtitles to a logged-in admin.

    ``?run=<run_id>`` selects a specific participant's POV; default = primary.
    """
    if optional_admin(request) is None:
        raise HTTPException(401, "Admin login required")
    try:
        sid = PydanticObjectId(session_id)
    except Exception:
        raise HTTPException(400, "Invalid session id")
    chunks = await _run_chunks(sid, run)
    if not chunks:
        raise HTTPException(404, "No recording for this session")
    combined = _build_combined(chunks)
    if combined is None:
        raise HTTPException(404, "Recording files are missing")
    vtt, _json = video_transcribe.paths_for(combined.parent)
    if not vtt.exists():
        raise HTTPException(404, "Subtitles not ready")
    return FileResponse(str(vtt), media_type="text/vtt", filename=f"session_{session_id}.vtt")
