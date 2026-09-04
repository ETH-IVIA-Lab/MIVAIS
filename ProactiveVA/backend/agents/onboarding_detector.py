"""
OnboardingDetector — perception agent for the *onboarding* help category.

Watches `interaction.event` and fires when the user appears unfamiliar with
the system's data transformations, visual mapping, or interaction methods.
"""
from __future__ import annotations

from agents._detector_base import DetectorBase


class OnboardingDetector(DetectorBase):
    CATEGORY = "onboarding"
    ENABLE_KEY = "onboarding_enabled"
    PATTERN_KEYS = (
        "hover_messages_scrolling_fast",
        "long_pause_on_graph_node",
        "select_keyword_no_timeline_followup",
    )
