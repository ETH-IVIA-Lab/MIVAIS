"""/api/i18n/<lang>.json — serves the flat-dict locale files used by the
useT() seam on the frontend. Public, no auth (translation strings aren't
sensitive); reuses studio.i18n's loader so this stays the one source of
truth for locale data.
"""
from __future__ import annotations

from fastapi import APIRouter

from studio.i18n import _load_locale

router = APIRouter(prefix="/api", tags=["i18n"])


@router.get("/i18n/{lang}.json")
async def get_locale(lang: str) -> dict[str, str]:
    if lang.lower() == "en":
        return {}
    return _load_locale(lang.lower())
