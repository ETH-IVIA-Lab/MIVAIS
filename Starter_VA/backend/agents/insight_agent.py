"""InsightAgent — the one software agent in the Starter VA.

This is deliberately the smallest useful mixed-initiative agent:

  * it WATCHES one World State key   (``selected_attributes``)
  * it WRITES one World State key    (``insight``)
  * it PUBLISHES on one bus topic    (``chat.message``)

Whenever the analyst picks a new x/y attribute pair in the scatterplot, the
agent wakes up (nobody calls it!), computes the Pearson correlation between
the two attributes over the whole dataset, writes a structured insight back
into the shared state, and drops a one-line observation into the chat.

Everything below is plain Python — no ML libraries, no network calls. The
infrastructure supplies the identity, the permissions, the audit trail and
the delivery of the result to every connected client.
"""
from __future__ import annotations

import asyncio
import math
from datetime import datetime, timezone
from typing import Any

from mivais.base_agent import BaseAgent


def pearson(xs: list[float], ys: list[float]) -> float | None:
    """Pearson correlation coefficient, pure Python. None if undefined."""
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    dx = [x - mx for x in xs]
    dy = [y - my for y in ys]
    num = sum(a * b for a, b in zip(dx, dy))
    den = math.sqrt(sum(a * a for a in dx)) * math.sqrt(sum(b * b for b in dy))
    if den == 0:
        return None
    return num / den


class InsightAgent(BaseAgent):
    """Watches the analyst's attribute selection and comments on it."""

    async def run(self) -> None:
        # 1. Register the watch. From now on, every accepted write to
        #    `selected_attributes` (by anyone) invokes _on_selection.
        self._ws.watch("selected_attributes", self._on_selection)

        # 2. The dataset and a default selection may have been written before
        #    this coroutine started, so compute one insight straight away.
        selection = self._read("selected_attributes")
        if selection:
            await self._analyze(selection)

        # 3. Sleep forever — all further work is watch-driven.
        await asyncio.Event().wait()

    async def _on_selection(self, key: str, value: Any) -> None:
        try:
            await self._analyze(value)
        except Exception as exc:  # never let a bad payload kill the watcher
            print(f"[insight_agent] analysis failed: {exc}")

    async def _analyze(self, selection: dict) -> None:
        x_attr = (selection or {}).get("x")
        y_attr = (selection or {}).get("y")
        dataset = self._read("dataset", [])
        if not x_attr or not y_attr or not dataset:
            return

        xs, ys = [], []
        for row in dataset:
            x, y = row.get(x_attr), row.get(y_attr)
            if isinstance(x, (int, float)) and isinstance(y, (int, float)):
                xs.append(float(x))
                ys.append(float(y))

        r = pearson(xs, ys)
        if r is None:
            return

        strong = float(self.params.get("strong_threshold", 0.7))
        moderate = float(self.params.get("moderate_threshold", 0.4))
        direction = "positive" if r >= 0 else "negative"
        if abs(r) >= strong:
            strength, hint = "strong", "these two attributes move almost in lockstep"
        elif abs(r) >= moderate:
            strength, hint = "moderate", "there is a visible trend, with real spread around it"
        else:
            strength, hint = "weak", "knowing one tells you little about the other"

        # Write the structured result into the shared state. The write goes
        # through the Permission Guard under this agent's identity, lands in
        # the Audit Log, and is broadcast to every connected client.
        self._write("insight", {
            "x": x_attr,
            "y": y_attr,
            "r": round(r, 3),
            "n": len(xs),
            "strength": strength,
            "direction": direction,
            "text": (
                f"{x_attr} and {y_attr} show a {strength} {direction} "
                f"correlation (r = {r:+.2f} over {len(xs)} cars) — {hint}."
            ),
        })

        # And say it out loud: one line in the shared chat, unprompted
        await self._publish("chat.message", {
            "from": self.agent_id,
            "to": "broadcast",
            "text": f"Looking at {x_attr} vs {y_attr}: {strength} {direction} correlation (r = {r:+.2f}).",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
