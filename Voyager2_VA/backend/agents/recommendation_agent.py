"""
RecommendationAgent 
"""

from __future__ import annotations
import asyncio
from typing import Any

from mivais.base_agent import BaseAgent
from spec_utils import (
    generate_univariate_summaries,
    generate_summaries,
    generate_field_suggestions,
    generate_alt_encodings,
)


class RecommendationAgent(BaseAgent):
    """Generates related view recommendations based on the focus view."""

    async def run(self) -> None:
        self._ws.watch("focus_view", self._on_focus_changed)
        self._subscribe("recommendation.instruction")
        await asyncio.Event().wait()  # run forever

    async def on_message(self, message: dict) -> None:
        if message.get("topic") == "recommendation.instruction":
            await self._on_focus_changed("focus_view", self._read("focus_view"))

    async def _on_focus_changed(self, key: str, value: Any) -> None:
        focus = value
        data_fields = self._read("data_fields") or []
        if not data_fields:
            return

        try:
            if not focus or not focus.get("encoding"):
                # No focus — show univariate summaries of all fields
                summaries = generate_univariate_summaries(data_fields)
                self._write("related_summaries", summaries)
                self._write("field_suggestions", [])
                self._write("alt_encodings", [])
            else:
                summaries = generate_summaries(focus, data_fields)
                field_sugg = generate_field_suggestions(focus, data_fields)
                alt_enc = generate_alt_encodings(focus)

                self._write("related_summaries", summaries)
                self._write("field_suggestions", field_sugg)
                self._write("alt_encodings", alt_enc)
        except Exception as exc:
            print(f"[{self.agent_id}] error: {exc}")
