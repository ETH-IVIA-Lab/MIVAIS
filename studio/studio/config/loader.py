"""Load a study directory into a validated StudyConfig.

Layout convention:

    studies/<slug>/
        study.yaml              # top-level study config (id, mode, va, ui, blocks, ...)
        tasks/
            <task-id>.yaml      # one file per task; filename stem must match `id:`

`study.yaml` references tasks in `blocks[].tasks` by id (a bare string).
The loader substitutes each id with the parsed `tasks/<id>.yaml` body
before handing the merged dict to Pydantic for validation.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import yaml

from studio.config.schemas import StudyConfig


class StudyLoadError(ValueError):
    """Raised when a study directory is malformed or a task ref is unresolvable."""


def load_study_dir(study_dir: str | Path) -> tuple[StudyConfig, dict[str, str], str]:
    """Load and validate a study directory.

    Returns ``(config, manifest, digest)`` where:
      - ``config`` is the validated StudyConfig.
      - ``manifest`` is a mapping ``{relative_path: file_sha256}`` covering
        every YAML file the loader consumed (including ``$ref``-resolved files),
        sorted for determinism.
      - ``digest`` is the sha256 of the manifest itself — a stable hash of
        the full study definition that changes iff any file's content changes.
    """
    base = Path(study_dir).resolve()
    if not base.is_dir():
        raise StudyLoadError(f"not a directory: {base}")

    study_file = base / "study.yaml"
    if not study_file.is_file():
        raise StudyLoadError(f"missing study.yaml in {base}")

    studies_root = base.parent.resolve()

    manifest: dict[str, str] = {}
    raw_study, study_hash = _read_yaml(study_file)
    manifest["study.yaml"] = study_hash

    data: dict[str, Any] = yaml.safe_load(raw_study) or {}
    if not isinstance(data, dict):
        raise StudyLoadError("study.yaml must be a mapping at the top level")

    tasks_dir = base / "tasks"

    blocks = data.get("blocks") or []
    if not isinstance(blocks, list):
        raise StudyLoadError("study.yaml: `blocks` must be a list")

    for b_idx, block in enumerate(blocks):
        if not isinstance(block, dict):
            raise StudyLoadError(f"study.yaml: blocks[{b_idx}] must be a mapping")
        refs = block.get("tasks") or []
        if not isinstance(refs, list):
            raise StudyLoadError(f"study.yaml: blocks[{b_idx}].tasks must be a list")

        resolved: list[dict[str, Any]] = []
        for t_idx, ref in enumerate(refs):
            if isinstance(ref, str):
                task_id = ref
                task_file = tasks_dir / f"{task_id}.yaml"
                if not task_file.is_file():
                    raise StudyLoadError(
                        f"blocks[{b_idx}].tasks[{t_idx}] references unknown task "
                        f"'{task_id}' (expected file: tasks/{task_id}.yaml)"
                    )
                raw_task, task_hash = _read_yaml(task_file)
                manifest[f"tasks/{task_id}.yaml"] = task_hash

                task_data = yaml.safe_load(raw_task) or {}
                if not isinstance(task_data, dict):
                    raise StudyLoadError(f"tasks/{task_id}.yaml must be a mapping")
                if task_data.get("id") and task_data["id"] != task_id:
                    raise StudyLoadError(
                        f"tasks/{task_id}.yaml declares id '{task_data['id']}', "
                        f"which does not match its filename"
                    )
                task_data.setdefault("id", task_id)
                resolved.append(task_data)
            elif isinstance(ref, dict) and "$ref" in ref:
                ref_path = str(ref["$ref"])
                ref_file = _resolve_ref(ref_path, study_base=base, studies_root=studies_root)
                if not ref_file.is_file():
                    raise StudyLoadError(
                        f"blocks[{b_idx}].tasks[{t_idx}]: $ref '{ref_path}' "
                        f"does not point to a file ({ref_file})"
                    )
                raw_task, task_hash = _read_yaml(ref_file)
                manifest_key = _manifest_key(ref_file, base, studies_root)
                manifest[manifest_key] = task_hash

                task_data = yaml.safe_load(raw_task) or {}
                if not isinstance(task_data, dict):
                    raise StudyLoadError(f"$ref target {ref_path} must be a mapping")
                overrides = {k: v for k, v in ref.items() if k != "$ref"}
                if overrides:
                    task_data = {**task_data, **overrides}
                resolved.append(task_data)
            elif isinstance(ref, dict):
                # Inline tasks are allowed for one-off cases (e.g. tests).
                resolved.append(ref)
            else:
                raise StudyLoadError(
                    f"blocks[{b_idx}].tasks[{t_idx}] must be a task id (string), "
                    f"a $ref mapping, or an inline task mapping; got {type(ref).__name__}"
                )
        block["tasks"] = resolved

    try:
        config = StudyConfig.model_validate(data)
    except Exception as exc:
        # Re-raise with a small prefix so admin error messages can identify the source.
        raise StudyLoadError(f"validation failed: {exc}") from exc

    sorted_manifest = dict(sorted(manifest.items()))
    digest = _hash_manifest(sorted_manifest)
    return config, sorted_manifest, digest


def _resolve_ref(ref_path: str, study_base: Path, studies_root: Path) -> Path:
    """Resolve a ``$ref`` path under the studies root, refusing escapes.

    Three shapes supported:
      - relative to the study dir:  "../_lib/tasks/nasa-tlx.yaml"
      - rooted in studies dir:      "_lib/tasks/nasa-tlx.yaml"
      - absolute path:              "/full/path/to/file.yaml"  (still re-checked
        against studies_root to keep the safety boundary)
    """
    if ref_path.startswith(("/", "\\")) or (len(ref_path) > 1 and ref_path[1] == ":"):
        candidate = Path(ref_path).resolve()
    else:
        # Try relative to the study dir first, then relative to studies_root.
        c1 = (study_base / ref_path).resolve()
        c2 = (studies_root / ref_path).resolve()
        candidate = c1 if c1.exists() else c2
    try:
        candidate.relative_to(studies_root)
    except ValueError:
        raise StudyLoadError(
            f"$ref '{ref_path}' resolves outside studies_dir ({studies_root}) — refused"
        )
    return candidate


def _manifest_key(target: Path, study_base: Path, studies_root: Path) -> str:
    """Best-effort stable key for the manifest. Prefer paths relative to the
    study dir; fall back to paths relative to the studies root."""
    try:
        return str(target.relative_to(study_base)).replace("\\", "/")
    except ValueError:
        return "$ref:" + str(target.relative_to(studies_root)).replace("\\", "/")


def _read_yaml(path: Path) -> tuple[str, str]:
    """Read a YAML file and return ``(raw_text, sha256_hex)``."""
    raw = path.read_text(encoding="utf-8")
    sha = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return raw, sha


def _hash_manifest(manifest: dict[str, str]) -> str:
    """Stable sha256 over ``path\\tfile_hash`` lines in sorted order."""
    payload = "\n".join(f"{p}\t{h}" for p, h in manifest.items())
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
