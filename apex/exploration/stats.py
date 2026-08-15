"""Deflated Sharpe and probability of backtest overfitting.

DSR (Bailey & Lopez de Prado): the probability that the observed Sharpe
exceeds the Sharpe one would expect from the BEST of `n_trials` skill-less
tries. Reported WITH its trial count, always -- a DSR quoted without its
denominator is the trick it exists to expose.

PBO via CSCV (combinatorially symmetric cross-validation): split the
per-period score matrix into complementary halves; in each split, find the
in-half best strategy and ask where it ranks out-of-half. PBO is the
fraction of splits where the in-half winner falls in the bottom half
out-of-half. Random selection -> ~0.5; genuine skill -> near 0.
"""

from __future__ import annotations

import math
from itertools import combinations

import numpy as np

_EULER = 0.5772156649015329


def _ncdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _nppf(q: float) -> float:
    # Acklam's rational approximation is overkill; bisection is exact enough
    lo, hi = -8.0, 8.0
    for _ in range(80):
        mid = (lo + hi) / 2
        if _ncdf(mid) < q:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def expected_max_sharpe(n_trials: int, var_sharpe: float) -> float:
    """E[max of n skill-less Sharpes] with estimation variance `var_sharpe`."""
    if n_trials <= 1:
        return 0.0
    n = float(n_trials)
    return math.sqrt(var_sharpe) * (
        (1 - _EULER) * _nppf(1 - 1 / n) + _EULER * _nppf(1 - 1 / (n * math.e)))


def deflated_sharpe(observed_sr: float, n_trials: int, n_periods: int,
                    skew: float = 0.0, kurtosis: float = 3.0) -> dict:
    """P(true SR > 0 | observed SR, best-of-n selection). Non-annualised SR
    on the same period basis as n_periods."""
    if n_periods < 10:
        raise ValueError("too few periods to say anything")
    var_sr = (1 - skew * observed_sr
              + (kurtosis - 1) / 4 * observed_sr ** 2) / (n_periods - 1)
    sr0 = expected_max_sharpe(n_trials, var_sr)
    z = (observed_sr - sr0) * math.sqrt(n_periods - 1) / math.sqrt(
        max(1e-12, 1 - skew * observed_sr + (kurtosis - 1) / 4 * observed_sr ** 2))
    return {"dsr": round(_ncdf(z), 4), "sr0_expected_max": round(sr0, 4),
            "n_trials": int(n_trials), "n_periods": int(n_periods)}


def pbo_cscv(score_matrix: np.ndarray, n_blocks: int = 8) -> dict:
    """Probability of backtest overfitting. `score_matrix` is periods x
    strategies (per-period scores for EVERY trial -- the full denominator,
    not the survivors)."""
    m = np.asarray(score_matrix, dtype=float)
    if m.ndim != 2 or m.shape[1] < 2:
        raise ValueError("need periods x strategies with >= 2 strategies")
    blocks = np.array_split(np.arange(m.shape[0]), n_blocks)
    half = n_blocks // 2
    below_median = 0
    total = 0
    for combo in combinations(range(n_blocks), half):
        ins = np.concatenate([blocks[i] for i in combo])
        outs = np.concatenate([blocks[i] for i in range(n_blocks)
                               if i not in combo])
        best = int(np.argmax(m[ins].mean(axis=0)))
        oos = m[outs].mean(axis=0)
        rank = (oos < oos[best]).mean()          # fraction it beats
        below_median += int(rank < 0.5)
        total += 1
    return {"pbo": round(below_median / total, 4), "splits": total,
            "n_strategies": int(m.shape[1])}
