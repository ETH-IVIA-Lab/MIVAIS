"""
Tiny gettext-style i18n shim.

Locale files live at ``studio/locales/<lang>.json``. The server-side default
comes from ``STUDIO_DEFAULT_LANG`` (default ``en``); the frontend resolves
its own language independently (``?lang=`` query > browser language > "en").

"""
from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path

log = logging.getLogger("studio.i18n")
LOCALES_DIR = Path(__file__).resolve().parent / "locales"


@lru_cache(maxsize=16)
def _load_locale(lang: str) -> dict[str, str]:
    path = LOCALES_DIR / f"{lang}.json"
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        log.warning("could not load locale %s: %s", lang, exc)
        return {}


def gettext(msg: str, lang: str | None = None) -> str:
    """Return the localised ``msg`` for ``lang``, or ``msg`` itself."""
    if not msg:
        return msg
    code = (lang or _default_lang()).strip().lower()
    if code in ("", "en"):
        return msg
    return _load_locale(code).get(msg, msg)


def _default_lang() -> str:
    # Lazy import to avoid a circular dep at module load.
    from studio.settings import get_settings
    return getattr(get_settings(), "default_lang", None) or "en"
