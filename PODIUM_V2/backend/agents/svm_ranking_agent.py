"""
SVMRankingAgent .

Observation strategy: watch (WorldState) + subscribe (MessageBus), both
event-driven via the same asyncio.Queue.

WorldState permissions (from agents_config.yaml):
  can_read:  ["dataset", "numeric_cols", "session_nudges"]
  can_write: ["ranked_items", "weights", "svm_status", "display_order",
              "user_preference_ranking"]
MessageBus subscriptions: ["weights.compute_request", "rank_all.request"]
"""
from __future__ import annotations

import asyncio
from typing import Any

import numpy as np
import pandas as pd

from agents.base_agent import BaseAgent
from podium.ranking_svm import RankingSVM
from podium.saw import rank_with_saw


class SVMRankingAgent(BaseAgent):

    def __init__(
        self,
        agent_id: str,
        world_state: Any,
        message_bus: Any,
        params: dict | None = None,
    ) -> None:
        super().__init__(agent_id, world_state, message_bus, params)
        self._svm = RankingSVM(C=self.params.get("C", 1.0))
        self._fitted = False

    # ── Observation loop ──────────────────────────────────────────────────────

    async def run(self) -> None:
        """
        WorldState watch() callbacks and MessageBus subscriptions both feed
        events into a single asyncio.Queue. The loop processes one event at
        a time — no concurrent SVM calls.
        """
        self._queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()

        async def on_nudges(key: str, value: Any) -> None:
            await self._queue.put(("apply_nudges", value))

        async def on_dataset(key: str, value: Any) -> None:
            await self._queue.put(("init_rank", value))

        self._ws.watch("session_nudges", on_nudges)
        self._ws.watch("dataset",        on_dataset)

        self._subscribe("weights.compute_request")
        self._subscribe("rank_all.request")

        # Produce an initial ranking at startup with uniform weights
        await self._queue.put(("init_rank", None))

        while True:
            try:
                event_type, payload = await self._queue.get()
                await self._handle(event_type, payload)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                print(f"[{self.agent_id}] error: {exc}")
                await asyncio.sleep(1)

    async def on_message(self, message: dict) -> None:
        topic = message.get("topic")
        payload = message.get("payload") or {}
        if topic == "weights.compute_request":
            await self._queue.put(("fit_svm", payload))
        elif topic == "rank_all.request":
            await self._queue.put(("rank_all", payload))

    # ── Event handlers ────────────────────────────────────────────────────────

    async def _handle(self, event_type: str, payload: Any) -> None:
        dataset      = self._read("dataset", [])
        numeric_cols = self._read("numeric_cols", [])
        if not dataset or not numeric_cols:
            return

        df = pd.DataFrame(dataset)
        X  = df[numeric_cols].values.astype(float)

        if event_type == "init_rank":
            await self._init_and_rank(df, X, numeric_cols)

        elif event_type == "fit_svm":
            await self._fit_svm(X, numeric_cols, payload)

        elif event_type == "rank_all":
            await self._rank_all(df, X, numeric_cols)

        elif event_type == "apply_nudges":
            await self._apply_nudges(df, X, numeric_cols, payload)

    async def _init_and_rank(
        self,
        df: pd.DataFrame,
        X: np.ndarray,
        cols: list[str],
    ) -> None:
        """Initialise with uniform weights and rank all items."""
        if not self._fitted:
            self._svm.feature_names = cols
            self._svm.weights = np.ones(len(cols)) / len(cols)
            self._svm.scaler.fit(X)
            self._fitted = True

        self._write("weights", self._svm._weights_as_dict())
        self._write("svm_status", {"status": "initialised", "message": "Uniform weights — drag items to express preferences."})
        ranked_df = rank_with_saw(df, cols, self._svm._weights_as_dict())
        self._write("ranked_items", ranked_df.to_dict(orient="records"))
        self._write("display_order", list(ranked_df["name"] if "name" in ranked_df.columns else ranked_df.iloc[:, 0]))

    # The user expresses preferences by arranging the TOP of the list; the
    # tail is whatever the previous ranking left there. Fitting on the full
    # table drowns an intentional drag under hundreds of stale pairs — one car
    # moved to #1 in a 30-row table loses 29:406 and lands last again after
    # Rank All. Fit on the head of the arrangement only.
    FIT_TOP_K = 10

    async def _fit_svm(
        self,
        X: np.ndarray,
        cols: list[str],
        payload: dict | None,
    ) -> None:
        """Fit RankSVM on the top of the user's drag-to-rank ordering. Does NOT re-rank yet."""
        if not payload:
            return
        ranking = list(payload.get("ranking", []))[: self.FIT_TOP_K]
        if len(ranking) < 2:
            self._write("svm_status", {
                "status": "pending",
                "message": "Need at least 2 items in the preference list.",
            })
            return

        # Ensure SVM scaler is fitted
        if not self._fitted:
            self._svm.feature_names = cols
            self._svm.scaler.fit(X)
            self._fitted = True

        weights_dict = self._svm.fit(X, ranking, cols)

        # Apply any active nudges on top of SVM weights
        nudges = self._read("session_nudges", {})
        if nudges:
            weights_dict = self._svm.apply_nudges(nudges)

        self._write("user_preference_ranking", {"ranking": ranking})
        self._write("weights", weights_dict)
        self._write("svm_status", {
            "status": "fitted",
            "message": f"SVM fitted on your top {len(ranking)} ({len(ranking)*(len(ranking)-1)} pairs). Click Rank All to apply.",
            "n_items": len(ranking),
            "active_nudges": nudges,
        })

    async def _rank_all(
        self,
        df: pd.DataFrame,
        X: np.ndarray,
        cols: list[str],
    ) -> None:
        """Apply SAW with current weights to produce full ranking."""
        if not self._fitted:
            await self._init_and_rank(df, X, cols)
            return

        weights_dict = self._svm._weights_as_dict()
        ranked_df    = rank_with_saw(df, cols, weights_dict)
        self._write("ranked_items", ranked_df.to_dict(orient="records"))
        self._write("display_order", list(ranked_df["name"] if "name" in ranked_df.columns else ranked_df.iloc[:, 0]))
        self._write("svm_status", {
            "status": "ranked",
            "message": f"Ranked {len(ranked_df)} items.",
        })

    async def _apply_nudges(
        self,
        df: pd.DataFrame,
        X: np.ndarray,
        cols: list[str],
        nudges: dict,
    ) -> None:
        """Apply nudge adjustments to current weights and immediately re-rank."""
        if not self._fitted:
            self._svm.feature_names = cols
            self._svm.weights = np.ones(len(cols)) / len(cols)
            self._svm.scaler.fit(X)
            self._fitted = True

        if nudges:
            weights_dict = self._svm.apply_nudges(nudges)
        else:
            weights_dict = self._svm._weights_as_dict()

        self._write("weights", weights_dict)

        ranked_df = rank_with_saw(df, cols, weights_dict)
        self._write("ranked_items", ranked_df.to_dict(orient="records"))
        self._write("display_order", list(ranked_df["name"] if "name" in ranked_df.columns else ranked_df.iloc[:, 0]))
        self._write("svm_status", {
            "status": "nudged",
            "message": f"Nudges applied: {nudges}",
            "active_nudges": nudges,
        })
