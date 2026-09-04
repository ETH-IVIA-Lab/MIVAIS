"""
Simple Additive Weighting model.

Computes a composite score for each item as the weighted sum of its
normalised attribute values, then ranks items by descending score.
This is how Podium re-ranks the full dataset after the SVM infers weights.
"""

import numpy as np
import pandas as pd
from sklearn.preprocessing import MinMaxScaler


def rank_with_saw(
    df: pd.DataFrame,
    numeric_cols: list[str],
    weights: dict[str, float],
) -> pd.DataFrame:
    """
    Rank all rows of *df* using Simple Additive Weighting.

    Parameters
    ----------
    df          : full dataset (may contain non-numeric columns like 'name')
    numeric_cols: columns used for scoring
    weights     : {column_name: weight_value}  – must cover all numeric_cols

    Returns
    -------
    df with two extra columns: 'score' and 'rank' (1-based), sorted by rank.
    """
    X = df[numeric_cols].values.astype(float)

    scaler = MinMaxScaler()
    X_norm = scaler.fit_transform(X)

    w = np.array([weights.get(col, 0.0) for col in numeric_cols])

    scores = X_norm @ w

    result = df.copy()
    result["score"] = scores
    result["rank"] = scores.argsort()[::-1].argsort() + 1  # 1-based
    result = result.sort_values("score", ascending=False).reset_index(drop=True)
    return result
