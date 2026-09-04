"""Shared fixtures + Mongo-availability gate.

Unit tests don't need Mongo and run unconditionally. Integration tests that
hit the database mark themselves with ``@pytest.mark.mongo`` and are skipped
when no Mongo is reachable, so the suite stays green on a fresh laptop.
"""
from __future__ import annotations

import socket

import pytest


def _mongo_reachable(host: str = "127.0.0.1", port: int = 27017, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


MONGO_AVAILABLE = _mongo_reachable()


def pytest_collection_modifyitems(config, items):
    """Auto-skip @pytest.mark.mongo when Mongo isn't reachable."""
    if MONGO_AVAILABLE:
        return
    skip = pytest.mark.skip(reason="Mongo not reachable at 127.0.0.1:27017")
    for item in items:
        if "mongo" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def _isolated_test_db():
    """Point Mongo-backed tests at a separate '<db>_test' database so running
    the suite never writes test studies into a developer's live local DB."""
    from studio.settings import get_settings
    settings = get_settings()
    original = settings.mongo_db
    if not original.endswith("_test"):
        settings.mongo_db = f"{original}_test"
    yield
    settings.mongo_db = original


@pytest.fixture(scope="session")
def studies_root():
    """Absolute path to the test-fixture studies directory.

    Tests used to point at the shipped ``studies/`` catalog, which broke when
    the catalog was reorganized (the podium-* studies became demo-*). The
    fixture studies live under ``tests/fixtures/studies`` so the suite is
    independent of whatever studies currently ship with the app.
    """
    from pathlib import Path
    return (Path(__file__).resolve().parent / "fixtures" / "studies").resolve()


@pytest.fixture
def smoke_study_cfg(studies_root):
    """Loaded StudyConfig for the podium-smoke fixture study."""
    from studio.config.loader import load_study_dir
    cfg, manifest, digest = load_study_dir(studies_root / "podium-smoke")
    return cfg


@pytest.fixture
def multiplayer_study_cfg(studies_root):
    """Loaded StudyConfig for the podium-multiplayer fixture study."""
    from studio.config.loader import load_study_dir
    cfg, manifest, digest = load_study_dir(studies_root / "podium-multiplayer")
    return cfg
