"""
Seeds/updates the persistent studies volume from the image's baked-in copy.

"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path

log = logging.getLogger("studio.sync_studies")


def sync_studies_from_seed(seed_dir: Path, target_dir: Path) -> None:
    if not seed_dir.is_dir():
        log.warning("studies_seed_dir %s does not exist — skipping seed sync", seed_dir)
        return
    target_dir.mkdir(parents=True, exist_ok=True)

    n_files = 0
    for src in seed_dir.rglob("*"):
        rel = src.relative_to(seed_dir)
        dst = target_dir / rel
        if src.is_dir():
            dst.mkdir(parents=True, exist_ok=True)
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            n_files += 1

    log.info("synced %d file(s) from %s into %s", n_files, seed_dir, target_dir)
