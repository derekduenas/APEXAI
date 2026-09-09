"""Stationary bootstrap over whole trading sessions (Politis-Romano).

Sessions are resampled whole and their row-level differentials concatenated,
so a session contributes in proportion to its row count. The block length is
geometric with a DECLARED expected length in sessions. Centred, one-sided."""
from __future__ import annotations

import random

import numpy as np

from .registration import BOOT_P_ESTIMATOR

P_ESTIMATOR_LABEL = BOOT_P_ESTIMATOR.split(",")[0].strip()


def session_stationary_bootstrap(d, session_ids, *, expected_block_sessions: int,
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
    rng = random.Random(seed)
    p = 1.0 / expected_block_sessions
    means = np.empty(n_resamples)
    for b in range(n_resamples):
        idx = rng.randrange(S)
        tot, cnt = 0.0, 0.0
        for _ in range(S):                      # draw S sessions, whole
            tot += sums[idx]; cnt += counts[idx]
            idx = rng.randrange(S) if rng.random() < p else (idx + 1) % S
        means[b] = tot / cnt
    centred = means - m_obs
    k = int(np.sum(centred >= m_obs))                 # exceedances
    B = int(n_resamples)
    p_hat = (k + 1.0) / (B + 1.0)                     # declared estimator; never zero
    return {"mean": m_obs, "n_rows": int(n), "n_sessions": int(S),
            "expected_block_sessions": expected_block_sessions, "resamples": B,
            "seed": seed, "boot_se": float(centred.std(ddof=1)),
            "exceedances": k, "p_estimator": P_ESTIMATOR_LABEL, "p_one_sided": p_hat,
            "raw_fraction_k_over_B": k / B, "smallest_reportable_p": 1.0 / (B + 1.0),
            "threshold": threshold,
            "pass": bool(m_obs > 0 and p_hat < threshold)}
