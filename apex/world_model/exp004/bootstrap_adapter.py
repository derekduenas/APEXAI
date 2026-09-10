"""Reporting extension of exp002.bootstrap.session_stationary_bootstrap (R8).

The statistical calculation is unchanged: identical RNG consumption order,
identical replicate means, identical p-hat and pass. What is ADDED is the
replicate means themselves and the registered percentile interval:

    lower = ceil(0.025*B)-th, upper = ceil(0.975*B)-th order statistic of the
    raw replicate means, 1-indexed, no interpolation.

N8 requires exact equivalence to the original for the same inputs and seed."""
from __future__ import annotations

import math
import random

import numpy as np

from apex.world_model.exp002.bootstrap import P_ESTIMATOR_LABEL

COVERAGE = 0.95          # tails 25/1000 and 975/1000, exact


def order_stat(sorted_vals: np.ndarray, num: int, den: int) -> tuple:
    """The ceil(num/den * B)-th order statistic, 1-indexed, computed with EXACT
    integer arithmetic. (Correction: in Python 0.025*40 == 1.0 exactly; my
    earlier claim that it rounds to 2 was false. The integer form is kept
    because it is exact for every B and every declared tail, not because of
    that example.)"""
    B = len(sorted_vals)
    k = max(1, min(B, (num * B + den - 1) // den))
    return float(sorted_vals[k - 1]), k


def session_stationary_bootstrap_ext(d, session_ids, *, expected_block_sessions: int,
                                     n_resamples: int, seed: int, threshold: float) -> dict:
    d = np.asarray(d, dtype=float)
    sids = list(session_ids)
    if len(d) != len(sids) or len(d) == 0:
        raise ValueError("differentials and session ids must align")
    order, sums, counts = [], [], []
    seen = {}
    for x, s in zip(d, sids):
        if s not in seen:
            seen[s] = len(order); order.append(s); sums.append(0.0); counts.append(0)
        i = seen[s]; sums[i] += float(x); counts[i] += 1
    sums, counts = np.array(sums), np.array(counts, dtype=float)
    S, n = len(order), len(d)
    m_obs = float(d.mean())
    rng = random.Random(seed)                     # identical RNG and consumption order
    p = 1.0 / expected_block_sessions
    means = np.empty(n_resamples)
    for b in range(n_resamples):
        idx = rng.randrange(S)
        tot, cnt = 0.0, 0.0
        for _ in range(S):
            tot += sums[idx]; cnt += counts[idx]
            idx = rng.randrange(S) if rng.random() < p else (idx + 1) % S
        means[b] = tot / cnt
    if not np.all(np.isfinite(means)):
        raise ValueError("NONFINITE_BOOTSTRAP_REPLICATES: %d of %d" % (int(n_resamples - np.isfinite(means).sum()), n_resamples))
    centred = means - m_obs
    k = int(np.sum(centred >= m_obs))
    B = int(n_resamples)
    p_hat = (k + 1.0) / (B + 1.0)
    srt = np.sort(means)
    lo, klo = order_stat(srt, 25, 1000)                       # 0.025 exactly
    hi, khi = order_stat(srt, 975, 1000)                      # 0.975 exactly
    return {"mean": m_obs, "n_rows": int(n), "n_sessions": int(S),
            "expected_block_sessions": expected_block_sessions, "resamples": B,
            "seed": seed, "boot_se": float(centred.std(ddof=1)),
            "exceedances": k, "p_estimator": P_ESTIMATOR_LABEL, "p_one_sided": p_hat,
            "raw_fraction_k_over_B": k / B, "smallest_reportable_p": 1.0 / (B + 1.0),
            "threshold": threshold,
            "pass": bool(m_obs > 0 and p_hat < threshold),
            # --- extension
            "replicate_means": means,
            "percentile_interval": {"coverage": COVERAGE, "lower": lo, "upper": hi,
                                    "lower_order_index": klo, "upper_order_index": khi,
                                    "convention": "ceil(q*B)-th order statistic, 1-indexed, no interpolation",
                                    "note": "descriptive; p_one_sided decides; boot_se is NOT a bootstrap interval"},
            "session_counts": counts.astype(int).tolist(),
            "estimand": "pooled per-row mean as ratio of resampled session sums to session counts"}


def strip_arrays(rec: dict) -> dict:
    """JSON-safe copy without the replicate array (kept out of sealed records)."""
    return {k: v for k, v in rec.items() if k != "replicate_means"}
