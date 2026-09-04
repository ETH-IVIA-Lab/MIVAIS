"""
Behaviour-feature extraction over an interaction event window

"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Features:
    """Behaviour features computed over a recent window of interactions."""
    actor: str
    window_size: int
    latest: dict[str, Any] | None
    latest_think_time: float
    long_pause: bool                        # latest thinkTime >= threshold
    pause_streak: int                       # consecutive recent events with high thinkTime
    action_counts: dict[str, int]           # actionType - count
    view_counts: dict[str, int]             # view - count
    repeated_elements: list[tuple[str, int]]  # (element, count) for elements clicked >= 2x
    view_switches: int                      # number of times the focused view changed
    toggle_back_and_forth: bool             # flipped same filter on/off >= 2x
    scroll_runs: int                        # consecutive scroll events
    hover_runs: int                         # consecutive hover events
    no_progress: bool                       # only hover/scroll, no selects/filters/notes
    last_progress_action: str | None        # most recent select/filter/note actionType
    pattern_hints: list[str] = field(default_factory=list)  

    def summary(self) -> str:
        """Compact natural-language summary used in LLM prompts."""
        parts: list[str] = []
        if self.latest:
            parts.append(
                f"Latest action: {self.latest.get('actionType')} on {self.latest.get('view')}"
                f" (element={self.latest.get('element')}, thinkTime={self.latest_think_time:.1f}s)."
            )
        parts.append(f"Window of {self.window_size} events. Action counts: {dict(self.action_counts)}.")
        parts.append(f"View counts: {dict(self.view_counts)}.")
        if self.repeated_elements:
            parts.append(f"Repeated elements: {self.repeated_elements}.")
        if self.view_switches:
            parts.append(f"View switches: {self.view_switches}.")
        if self.toggle_back_and_forth:
            parts.append("Toggled same filter on/off repeatedly.")
        if self.scroll_runs:
            parts.append(f"Long scroll runs: {self.scroll_runs}.")
        if self.hover_runs:
            parts.append(f"Long hover runs: {self.hover_runs}.")
        if self.no_progress:
            parts.append("No selects/filters/notes during this window.")
        if self.pattern_hints:
            parts.append(f"Heuristic pattern matches: {self.pattern_hints}.")
        return " ".join(parts)


def extract_features(
    events: list[dict],
    *,
    actor: str,
    threshold_s: float,
    window: int = 30,
) -> Features:
    """
    Extract behaviour features from `events` for a single `actor`.

    `threshold_s` is the user-controlled prolonged-pause threshold
    """
    own = [e for e in events if e.get("actor") == actor]
    win = own[-window:]

    if not win:
        return Features(
            actor=actor, window_size=0, latest=None,
            latest_think_time=0.0, long_pause=False, pause_streak=0,
            action_counts={}, view_counts={}, repeated_elements=[],
            view_switches=0, toggle_back_and_forth=False,
            scroll_runs=0, hover_runs=0, no_progress=True,
            last_progress_action=None,
        )

    latest = win[-1]
    latest_think_time = float(latest.get("thinkTime", 0.0) or 0.0)
    long_pause = latest_think_time >= threshold_s

    pause_streak = 0
    for ev in reversed(win):
        if float(ev.get("thinkTime", 0.0) or 0.0) >= threshold_s:
            pause_streak += 1
        else:
            break

    action_counts = Counter(e.get("actionType", "?") for e in win)
    view_counts   = Counter(e.get("view", "?") for e in win)

    elements = Counter()
    for e in win:
        el = e.get("element")
        if el:
            elements[(e.get("view", "?"), el)] += 1
    repeated_elements = [(f"{v}:{el}", n) for (v, el), n in elements.most_common() if n >= 2]

    # View switches — every time the focused view changes from previous event
    view_switches = 0
    for prev, curr in zip(win, win[1:]):
        if prev.get("view") != curr.get("view"):
            view_switches += 1

    # Toggle back-and-forth — same select/filter applied with `deselected=True` flips ≥ 2x
    toggle_back_and_forth = False
    flips = 0
    for e in win:
        if e.get("actionType") in {"select", "filter"} and e.get("data", {}).get("deselected"):
            flips += 1
    if flips >= 2:
        toggle_back_and_forth = True

    # Scroll / hover runs — longest consecutive run within the window
    def _longest_run(predicate) -> int:
        run = best = 0
        for e in win:
            if predicate(e):
                run += 1
                best = max(best, run)
            else:
                run = 0
        return best
    scroll_runs = _longest_run(lambda e: e.get("actionType") == "scroll")
    hover_runs  = _longest_run(lambda e: e.get("actionType") == "hover")

    progress_actions = {"select", "filter", "brush", "note"}
    progress_events = [e for e in win if e.get("actionType") in progress_actions]
    no_progress = len(progress_events) == 0
    last_progress_action = progress_events[-1].get("actionType") if progress_events else None

    pattern_hints: list[str] = []
    if hover_runs >= 5 and view_counts.get("messages", 0) >= 5:
        pattern_hints.append("hover_messages_scrolling_fast")
    if long_pause and latest.get("view") == "graph":
        pattern_hints.append("long_pause_on_graph_node")
    if (
        action_counts.get("select", 0) >= 1
        and view_counts.get("messages", 0) >= 1
        and view_counts.get("timeline", 0) == 0
    ):
        pattern_hints.append("select_keyword_no_timeline_followup")
    if toggle_back_and_forth and pause_streak >= 1:
        pattern_hints.append("hesitant_keyword_selection")
    if scroll_runs >= 4 and no_progress:
        pattern_hints.append("browse_messages_no_action")
    brush_count = action_counts.get("brush", 0)
    if brush_count >= 2 and pause_streak >= 1:
        pattern_hints.append("compare_time_ranges_slowly")
    if view_counts.get("timeline", 0) >= 3 and view_switches >= 2:
        pattern_hints.append("review_timeline_repeatedly")
    if view_switches >= 4:
        pattern_hints.append("explore_previous_path_repeatedly")
    if view_switches >= 3 and pause_streak >= 1:
        pattern_hints.append("switch_views_slowly")

    return Features(
        actor=actor,
        window_size=len(win),
        latest=latest,
        latest_think_time=latest_think_time,
        long_pause=long_pause,
        pause_streak=pause_streak,
        action_counts=dict(action_counts),
        view_counts=dict(view_counts),
        repeated_elements=repeated_elements,
        view_switches=view_switches,
        toggle_back_and_forth=toggle_back_and_forth,
        scroll_runs=scroll_runs,
        hover_runs=hover_runs,
        no_progress=no_progress,
        last_progress_action=last_progress_action,
        pattern_hints=pattern_hints,
    )
