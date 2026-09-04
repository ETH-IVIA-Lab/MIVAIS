"""
ExplorationDetector — perception agent for the *exploration* help category.

Watches `interaction.event` and fires when the user appears confused about
data meaning, overwhelmed by data volume, or struggling to compare across
views.
"""
from __future__ import annotations

from agents._detector_base import DetectorBase


class ExplorationDetector(DetectorBase):
    CATEGORY = "exploration"
    ENABLE_KEY = "exploration_enabled"
    PATTERN_KEYS = (
        "hesitant_keyword_selection",
        "browse_messages_no_action",
        "compare_time_ranges_slowly",
    )
