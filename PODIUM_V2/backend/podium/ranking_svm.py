"""
Ranking SVM implementation for Podium.


"""

import numpy as np
from sklearn.svm import LinearSVC
from sklearn.preprocessing import MinMaxScaler
from typing import Optional


class RankingSVM:
    """
    Fits a linear SVM on pairwise difference vectors derived from a user ranking.
    The SVM coefficient vector becomes the attribute weight vector.
    """

    def __init__(self, C: float = 1.0):
        self.C = C
        self.svm = LinearSVC(fit_intercept=False, C=C, max_iter=5000)
        self.scaler = MinMaxScaler()
        self.weights: Optional[np.ndarray] = None
        self.feature_names: list[str] = []

    def fit(self, X: np.ndarray, ranking: list[int], feature_names: list[str]) -> dict:
        """
        Train the Ranking SVM.

        Parameters
        ----------
        X : shape (n_items, n_features) – raw feature matrix for ALL items
        ranking : list of item indices in user-defined order, best first
                  e.g. [4, 1, 0, 7] means item 4 is best, then 1, then 0, then 7
        feature_names : column names matching X

        Returns
        -------
        dict mapping feature_name -> weight (normalised to [-1, 1])
        """
        self.feature_names = feature_names
        X_scaled = self.scaler.fit_transform(X)

        pairs_X, pairs_y = self._build_pairs(X_scaled, ranking)

        if len(pairs_X) == 0:
            # No pairs yet – return uniform weights
            self.weights = np.ones(X.shape[1]) / X.shape[1]
            return self._weights_as_dict()

        self.svm.fit(pairs_X, pairs_y)
        raw_weights = self.svm.coef_[0]

        # Normalise to [-1, 1] so the UI can display them symmetrically
        max_abs = np.abs(raw_weights).max()
        self.weights = raw_weights / max_abs if max_abs > 0 else raw_weights

        return self._weights_as_dict()

    def apply_nudges(self, nudges: dict[str, int]) -> dict:
        """
        Adjust weights based on user attribute nudges.

        Parameters
        ----------
        nudges : {feature_name: direction}  

        Returns
        -------
        Updated weight dict
        """
        if self.weights is None:
            raise RuntimeError("Call fit() before apply_nudges()")

        weights = self.weights.copy()
        for name, direction in nudges.items():
            if name not in self.feature_names:
                continue
            idx = self.feature_names.index(name)
            if direction == 1:
                weights[idx] = np.sign(weights[idx]) * min(abs(weights[idx]) * 1.5, 1.0)
            elif direction == -1:
                weights[idx] = weights[idx] * 0.5

        max_abs = np.abs(weights).max()
        self.weights = weights / max_abs if max_abs > 0 else weights
        return self._weights_as_dict()

    def rank_all(self, X: np.ndarray) -> tuple[list[int], list[float]]:
        """
        Produce a full ranking of all items using Simple Additive Weighting.

        Returns
        -------
        (ranked_indices, scores) – ranked_indices[0] is the top-ranked item
        """
        if self.weights is None:
            raise RuntimeError("Call fit() before rank_all()")

        X_scaled = self.scaler.transform(X)
        scores = X_scaled @ self.weights
        ranked_indices = np.argsort(-scores).tolist()
        return ranked_indices, scores.tolist()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_pairs(self, X_scaled: np.ndarray, ranking: list[int]):
        """
        For every ordered pair (i, j) in the ranking where i is preferred over j,
        add the difference vector x_i - x_j as a positive training example
        and x_j - x_i as a negative one.
        """
        pairs_X = []
        pairs_y = []

        for pos_i in range(len(ranking)):
            for pos_j in range(pos_i + 1, len(ranking)):
                idx_i = ranking[pos_i]  # higher ranked
                idx_j = ranking[pos_j]  # lower ranked
                diff = X_scaled[idx_i] - X_scaled[idx_j]
                pairs_X.append(diff)
                pairs_y.append(1)
                pairs_X.append(-diff)
                pairs_y.append(-1)

        return np.array(pairs_X), np.array(pairs_y)

    def _weights_as_dict(self) -> dict:
        return {
            name: float(self.weights[i])
            for i, name in enumerate(self.feature_names)
        }
