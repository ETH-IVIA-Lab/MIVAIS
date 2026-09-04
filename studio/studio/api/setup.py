"""/api/setup — the public, step-by-step tutorial.

A single piece of static documentation content that walks a developer from an
empty folder to a working mixed-initiative VA on MIVAIS (the Starter VA in
``Starter_VA/``), and from there to running a controlled study on it in
Studio. No auth: it's documentation and contains no deployment-specific data.

The prose is pure static HTML with zero dynamic data (no template syntax),
so it's just read off disk and served as a JSON string the React SetupPage
drops in with dangerouslySetInnerHTML — no templating engine needed.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["setup"])

_CONTENT_PATH = Path(__file__).resolve().parent.parent / "static" / "setup_content.html"


@router.get("/setup")
async def setup_tutorial() -> dict[str, str]:
    return {"html": _CONTENT_PATH.read_text(encoding="utf-8")}
