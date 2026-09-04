"""Staging of an uploaded study.yaml onto the studies directory.

Pure file/parse logic — no HTTP types, no database. The admin endpoint stays
a thin shell: auth + "is this slug already registered?" (a DB concern) live
there; everything about the *file* lives here, where it can be unit-tested
without an app or event loop.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

# A study.yaml is prose + structure, not data.
MAX_STUDY_YAML_BYTES = 512 * 1024

_DIR_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class StudyUploadError(ValueError):
    """Invalid uploaded study.yaml. `status` suggests the HTTP status code."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


def parse_uploaded_study_yaml(raw: bytes) -> tuple[str, str]:
    """Validate the uploaded bytes and return ``(yaml_text, slug)``.

    Checks: size cap, UTF-8, parseable YAML, top-level mapping with an `id:`.
    """
    if len(raw) > MAX_STUDY_YAML_BYTES:
        raise StudyUploadError(
            "study.yaml larger than 512 KB — that is not a study definition", status=413
        )
    try:
        text = raw.decode("utf-8")
        parsed = yaml.safe_load(text)
    except Exception as exc:
        raise StudyUploadError(f"Not parseable as YAML: {exc}")
    if not isinstance(parsed, dict) or not parsed.get("id"):
        raise StudyUploadError("The YAML must be a mapping with at least an `id:` field")
    return text, str(parsed["id"])


def stage_study_yaml(text: str, slug: str, studies_dir: Path, dir_name: str = "") -> str:
    """Write the YAML as ``studies/<dir>/study.yaml`` and return the dir name.

    ``dir_name`` defaults to the study's slug. The name is validated against a
    conservative pattern and resolved-path-checked, so an upload can never
    escape the studies directory. The tasks/ folder is NOT touched — tasks are
    always read from disk, which is the contract of the upload flow.
    """
    target_name = (dir_name or slug).strip()
    if not _DIR_NAME_RE.match(target_name):
        raise StudyUploadError(f"Invalid directory name '{target_name}'")

    target = (studies_dir / target_name).resolve()
    if not str(target).startswith(str(studies_dir.resolve())):
        raise StudyUploadError(f"Invalid directory name '{target_name}'")

    target.mkdir(parents=True, exist_ok=True)
    (target / "study.yaml").write_text(text, encoding="utf-8")
    return target_name
