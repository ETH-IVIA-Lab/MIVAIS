"""Example custom metric: share of time spent idle (no event for > threshold).

Use from a study YAML::

    metrics:
      - id: idle_share
        label: "Share of time idle"
        kind: python
        module: studio.metrics.custom.example_idle_share:compute
        params: { threshold_s: 5 }
"""
from __future__ import annotations

from typing import Any


def compute(events: list[dict[str, Any]], params: dict[str, Any]) -> tuple[float | None, dict]:
    threshold_ms = float(params.get("threshold_s", 5)) * 1000
    times = sorted(int(ev.get("t_ms") or 0) for ev in events)
    if len(times) < 2:
        return None, {"reason": "not enough events"}
    total = times[-1] - times[0]
    if total <= 0:
        return None, {"reason": "zero duration"}
    idle = sum(
        gap for a, b in zip(times, times[1:])
        if (gap := b - a) > threshold_ms
    )
    return round(idle / total, 3), {"idle_ms": idle, "total_ms": total}
