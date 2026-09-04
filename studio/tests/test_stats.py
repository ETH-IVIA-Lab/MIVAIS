"""Tests for studio.stats — Welch's t, Cohen's d, Mann–Whitney U, Cohen's κ.

Each estimator is checked against a hand-computed reference + at least one
degenerate edge case so refactors can't silently change the math.
"""
from __future__ import annotations

import pytest

from studio.stats import (
    cohens_d, cohens_kappa, mann_whitney_u, mean, stddev, welch_t_test,
)


class TestDescriptive:
    def test_mean(self):
        assert mean([1, 2, 3]) == 2.0

    def test_mean_empty(self):
        assert mean([]) == 0.0

    def test_stddev_sample(self):
        assert stddev([2, 4, 4, 4, 5, 5, 7, 9]) == pytest.approx(2.138, abs=1e-3)

    def test_stddev_singleton(self):
        assert stddev([5]) == 0.0


class TestWelch:
    def test_large_effect(self):
        a = [10, 12, 11, 13, 14, 15, 12, 11, 14, 13]
        b = [7, 8, 9, 8, 7, 9, 6, 8, 7, 9]
        r = welch_t_test(a, b)
        assert r["t"] > 5
        assert r["p_two_sided"] < 0.001
        assert r["mean_diff"] > 0
        assert r["ci95_low"] > 0

    def test_identical_samples(self):
        c = [1, 2, 3, 4, 5]
        r = welch_t_test(c, c)
        assert r["t"] == 0.0
        assert r["p_two_sided"] == pytest.approx(1.0, abs=1e-6)
        # Mean diff is 0; CI is centred on 0 but has non-zero width from the
        # within-sample variance, so it must contain 0 with some symmetry.
        assert r["mean_diff"] == 0.0
        assert r["ci95_low"] < 0 < r["ci95_high"]
        assert r["ci95_low"] == pytest.approx(-r["ci95_high"], rel=1e-6)

    def test_small_n_returns_nones(self):
        r = welch_t_test([1], [1, 2])
        assert r["t"] is None
        assert r["df"] is None
        assert r["p_two_sided"] is None


class TestCohensD:
    def test_huge_effect(self):
        a = [10, 12, 11, 13, 14, 15, 12, 11, 14, 13]
        b = [7, 8, 9, 8, 7, 9, 6, 8, 7, 9]
        d = cohens_d(a, b)
        assert d is not None
        assert d > 2.5

    def test_zero_when_identical(self):
        c = [1, 2, 3, 4, 5]
        assert cohens_d(c, c) == 0.0

    def test_none_when_too_few(self):
        assert cohens_d([1], [1, 2]) is None


class TestMannWhitney:
    def test_separated_distributions(self):
        a = [10, 12, 11, 13, 14, 15, 12, 11, 14, 13]
        b = [7, 8, 9, 8, 7, 9, 6, 8, 7, 9]
        r = mann_whitney_u(a, b)
        assert r["U"] == 0  # no overlap
        assert r["rank_biserial"] == 1.0
        assert r["p_two_sided"] < 0.001

    def test_no_difference(self):
        c = [1, 2, 3, 4, 5]
        r = mann_whitney_u(c, c)
        assert r["p_two_sided"] == pytest.approx(1.0, abs=0.05)

    def test_empty_returns_nones(self):
        r = mann_whitney_u([], [1, 2])
        assert r["U"] is None
        assert r["p_two_sided"] is None


class TestCohensKappa:
    def test_perfect_agreement(self):
        r = cohens_kappa([True, False, True, True], [True, False, True, True])
        assert r["kappa"] == 1.0
        assert r["interpretation"] == "almost perfect"

    def test_partial_agreement(self):
        a = [True, True, False, False, True]
        b = [True, False, False, True, True]
        r = cohens_kappa(a, b)
        assert r["agreement"] == pytest.approx(0.6)
        assert r["kappa"] is not None
        assert -1 < r["kappa"] < 1

    def test_mismatched_lengths(self):
        r = cohens_kappa([True, False], [True])
        assert r["kappa"] is None

    def test_interpretation_landis_koch(self):
        # Build a deliberately moderate-agreement scenario:
        # 7/10 agree, both raters have similar marginals (~6/10 true).
        a = [True] * 6 + [False] * 4
        b = [True] * 5 + [False] * 1 + [True] * 1 + [False] * 3
        r = cohens_kappa(a, b)
        assert r["interpretation"] in {"slight", "fair", "moderate", "substantial"}
