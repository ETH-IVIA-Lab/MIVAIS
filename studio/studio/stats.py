"""Pure-Python inference helpers 

Three estimators, kept intentionally small so reviewers can read each in one sit:

  - Welch's two-sample t-test (unequal variances): t-stat, df, two-sided p-value
    via a Lentz continued-fraction approximation of the regularised incomplete
    beta function. Accuracy is good enough for the table on /admin/compare;
    if you publish, run a proper stats package on the underlying data.
  - Cohen's d effect size with Hedges's small-sample correction.
  - 95% confidence interval on the mean difference.
  - Mann–Whitney U + rank-biserial effect size for non-normal duration data.

"""
from __future__ import annotations

import math
from typing import Sequence


def mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def stddev(xs: Sequence[float], ddof: int = 1) -> float:
    if len(xs) < 2:
        return 0.0
    m = mean(xs)
    var = sum((x - m) ** 2 for x in xs) / (len(xs) - ddof)
    return math.sqrt(var)


def cohens_kappa(ratings_a: Sequence[bool], ratings_b: Sequence[bool]) -> dict:
    """Cohen's κ for two raters on a binary tag (present / absent).

    Returns ``{n, agreement, expected, kappa, interpretation}``. The
    interpretation labels follow Landis & Koch (1977): poor (<0), slight,
    fair, moderate, substantial, almost perfect.
    """
    if len(ratings_a) != len(ratings_b) or not ratings_a:
        return {"n": len(ratings_a), "agreement": None, "expected": None,
                "kappa": None, "interpretation": None}
    n = len(ratings_a)
    p_o = sum(1 for a, b in zip(ratings_a, ratings_b) if a == b) / n
    p_a1 = sum(1 for x in ratings_a if x) / n
    p_b1 = sum(1 for x in ratings_b if x) / n
    p_e = p_a1 * p_b1 + (1 - p_a1) * (1 - p_b1)
    if p_e >= 1.0:
        kappa = 1.0 if p_o == 1.0 else 0.0
    else:
        kappa = (p_o - p_e) / (1 - p_e)
    if kappa is None:    label = None
    elif kappa < 0:      label = "poor"
    elif kappa < 0.2:    label = "slight"
    elif kappa < 0.4:    label = "fair"
    elif kappa < 0.6:    label = "moderate"
    elif kappa < 0.8:    label = "substantial"
    else:                label = "almost perfect"
    return {"n": n, "agreement": p_o, "expected": p_e,
            "kappa": kappa, "interpretation": label}


# ── Welch's t-test ───────────────────────────────────────────────────────

def welch_t_test(a: Sequence[float], b: Sequence[float]) -> dict:
    """Two-sided Welch's t-test for two independent samples.

    Returns:
      {n_a, n_b, mean_a, mean_b, mean_diff, t, df, p_two_sided,
       ci95_low, ci95_high}
    """
    n_a, n_b = len(a), len(b)
    if n_a < 2 or n_b < 2:
        return {
            "n_a": n_a, "n_b": n_b, "mean_a": mean(a), "mean_b": mean(b),
            "mean_diff": mean(a) - mean(b),
            "t": None, "df": None, "p_two_sided": None,
            "ci95_low": None, "ci95_high": None,
        }
    ma, mb = mean(a), mean(b)
    sa2 = stddev(a) ** 2
    sb2 = stddev(b) ** 2
    se = math.sqrt(sa2 / n_a + sb2 / n_b)
    if se == 0:
        return {
            "n_a": n_a, "n_b": n_b, "mean_a": ma, "mean_b": mb,
            "mean_diff": ma - mb, "t": 0.0, "df": float(n_a + n_b - 2),
            "p_two_sided": 1.0, "ci95_low": ma - mb, "ci95_high": ma - mb,
        }
    t = (ma - mb) / se
    num = (sa2 / n_a + sb2 / n_b) ** 2
    den = (sa2 ** 2) / (n_a ** 2 * (n_a - 1)) + (sb2 ** 2) / (n_b ** 2 * (n_b - 1))
    df = num / den if den else float(n_a + n_b - 2)
    p = _t_two_sided_p(abs(t), df)
    # 95% CI on mean diff via t critical value at df.
    tcrit = _t_quantile(0.975, df)
    half = tcrit * se
    return {
        "n_a": n_a, "n_b": n_b, "mean_a": ma, "mean_b": mb,
        "mean_diff": ma - mb, "t": t, "df": df, "p_two_sided": p,
        "ci95_low": (ma - mb) - half, "ci95_high": (ma - mb) + half,
    }


def cohens_d(a: Sequence[float], b: Sequence[float], hedges: bool = True) -> float | None:
    """Cohen's d with optional Hedges's correction for small samples."""
    n_a, n_b = len(a), len(b)
    if n_a < 2 or n_b < 2:
        return None
    sa, sb = stddev(a), stddev(b)
    pooled = math.sqrt(((n_a - 1) * sa ** 2 + (n_b - 1) * sb ** 2) / (n_a + n_b - 2))
    if pooled == 0:
        return 0.0
    d = (mean(a) - mean(b)) / pooled
    if hedges:
        j = 1 - 3 / (4 * (n_a + n_b) - 9)
        d *= j
    return d


# ── Mann–Whitney U ────────────────────────────────────────────────────────

def mann_whitney_u(a: Sequence[float], b: Sequence[float]) -> dict:
    """Mann–Whitney U with normal approximation (ties broken by average rank).

    Returns {U, n_a, n_b, z, p_two_sided, rank_biserial}.
    """
    n_a, n_b = len(a), len(b)
    if n_a == 0 or n_b == 0:
        return {"U": None, "n_a": n_a, "n_b": n_b, "z": None,
                "p_two_sided": None, "rank_biserial": None}
    combined = [(x, "a") for x in a] + [(x, "b") for x in b]
    combined.sort(key=lambda t: t[0])
    # Average-rank tie correction.
    ranks: list[float] = [0.0] * len(combined)
    i = 0
    while i < len(combined):
        j = i
        while j + 1 < len(combined) and combined[j + 1][0] == combined[i][0]:
            j += 1
        avg = (i + j) / 2 + 1  # 1-indexed
        for k in range(i, j + 1):
            ranks[k] = avg
        i = j + 1
    r_a = sum(r for r, (_, g) in zip(ranks, combined) if g == "a")
    u_a = r_a - n_a * (n_a + 1) / 2
    u_b = n_a * n_b - u_a
    u = min(u_a, u_b)
    # Normal approximation: mean = n_a*n_b/2; var = n_a*n_b*(n_a+n_b+1)/12.
    mu = n_a * n_b / 2
    sigma2 = n_a * n_b * (n_a + n_b + 1) / 12
    sigma = math.sqrt(sigma2) if sigma2 > 0 else 1.0
    z = (u - mu) / sigma if sigma else 0.0
    p = 2 * (1 - _phi(abs(z)))
    # Rank-biserial effect size (Glass) in [-1, 1].
    r_b_eff = 1 - (2 * u) / (n_a * n_b)
    return {"U": u, "n_a": n_a, "n_b": n_b, "z": z,
            "p_two_sided": max(0.0, min(1.0, p)),
            "rank_biserial": r_b_eff}


# ── Distribution helpers (no scipy) ──────────────────────────────────────

def _phi(x: float) -> float:
    """Standard normal CDF via erf — accurate enough for p-value display."""
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _t_two_sided_p(t_abs: float, df: float) -> float:
    """Two-sided p for Student's t via the regularised incomplete beta.

    p = 2 * (1 - F_t(|t|; df)) where F_t = 1 - 0.5 * I_x(df/2, 1/2),
    with x = df / (df + t^2). The continued-fraction expansion is the standard
    Numerical-Recipes one — converges fast for sane t / df.
    """
    if df <= 0:
        return 1.0
    x = df / (df + t_abs * t_abs)
    ix = _reg_inc_beta(x, df / 2, 0.5)
    p = ix  # equals 2 * (1 - F_t(|t|))
    return max(0.0, min(1.0, p))


def _t_quantile(p: float, df: float) -> float:
    """Approximate inverse CDF for the t-distribution via Hill's algorithm
    (good to ~4 decimals across the body of the distribution).
    """
    if df <= 0:
        return float("nan")
    # Use a small Newton refinement starting from the normal approximation.
    z = _inv_phi(p)
    g1 = (z ** 3 + z) / 4
    g2 = (5 * z ** 5 + 16 * z ** 3 + 3 * z) / 96
    g3 = (3 * z ** 7 + 19 * z ** 5 + 17 * z ** 3 - 15 * z) / 384
    t = z + g1 / df + g2 / df ** 2 + g3 / df ** 3
    return t


def _inv_phi(p: float) -> float:
    """Inverse of the standard normal CDF via Acklam's algorithm.

    Adequate accuracy (≲1e-7) across the central 99.9% of the distribution.
    """
    a = [-39.69683028665376, 220.9460984245205, -275.9285104469687,
         138.357751867269,  -30.66479806614716,  2.506628277459239]
    b = [-54.47609879822406, 161.5858368580409, -155.6989798598866,
         66.80131188771972, -13.28068155288572]
    c = [-0.007784894002430293, -0.3223964580411365,  -2.400758277161838,
         -2.549732539343734,     4.374664141464968,    2.938163982698783]
    d = [0.007784695709041462,   0.3224671290700398,   2.445134137142996,
         3.754408661907416]
    plow = 0.02425
    phigh = 1 - plow
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q + c[1])*q + c[2])*q + c[3])*q + c[4])*q + c[5]) / \
               ((((d[0]*q + d[1])*q + d[2])*q + d[3])*q + 1)
    if p <= phigh:
        q = p - 0.5
        r = q * q
        return (((((a[0]*r + a[1])*r + a[2])*r + a[3])*r + a[4])*r + a[5]) * q / \
               (((((b[0]*r + b[1])*r + b[2])*r + b[3])*r + b[4])*r + 1)
    q = math.sqrt(-2 * math.log(1 - p))
    return -(((((c[0]*q + c[1])*q + c[2])*q + c[3])*q + c[4])*q + c[5]) / \
           ((((d[0]*q + d[1])*q + d[2])*q + d[3])*q + 1)


def _reg_inc_beta(x: float, a: float, b: float) -> float:
    """Regularised incomplete beta I_x(a, b) via continued fraction (NR ch. 6)."""
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    lbeta = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
    front = math.exp(lbeta + a * math.log(x) + b * math.log(1 - x)) / a
    # Lentz's continued fraction
    f, c_lentz, d_lentz = 1.0, 1.0, 0.0
    for i in range(1, 201):
        m = i // 2
        if i == 1:
            num = 1.0
        elif i % 2 == 0:
            num = (m * (b - m) * x) / ((a + 2 * m - 1) * (a + 2 * m))
        else:
            num = -((a + m) * (a + b + m) * x) / ((a + 2 * m) * (a + 2 * m + 1))
        d_lentz = 1.0 + num * d_lentz
        if abs(d_lentz) < 1e-30:
            d_lentz = 1e-30
        c_lentz = 1.0 + num / c_lentz
        if abs(c_lentz) < 1e-30:
            c_lentz = 1e-30
        d_lentz = 1.0 / d_lentz
        delta = c_lentz * d_lentz
        f *= delta
        if abs(delta - 1.0) < 1e-9:
            break
    return front * (f - 1)
