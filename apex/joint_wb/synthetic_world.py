"""The declared synthetic generator (contract §6). Known mechanism, deterministic given a seed.

SYNTHETIC-ONLY. The null world for `C_PERM` generates INDEPENDENT AND IDENTICALLY DISTRIBUTED SESSIONS in which
the option-state change block is INDEPENDENT of that session's predictor block; under that generator the joint law
is invariant to permuting SESSION labels between the two blocks, which is what licenses the control. The
permutation unit is the whole session, never the row."""
from __future__ import annotations

import math

import numpy as np

from .permissions import require_read

ROWS_PER_SESSION = 24


def permission():
    return require_read("SYNTHETIC-FIXTURE", "FIT")


def make_rows(*, n_sessions: int, A_true: np.ndarray | None, Sigma_true: np.ndarray, seed: int,
              rows_per_session: int = ROWS_PER_SESSION, v_hat: float = 1e-6, t0: float = 1.788e9) -> list:
    """Training pairs with the contract's three clocks. `A_true = None` means the NULL world (no conditional mean)."""
    rng = np.random.default_rng(seed)
    L = np.linalg.cholesky(Sigma_true)
    rows = []
    for s in range(n_sessions):
        day = "S%04d" % s
        t_session = t0 + s * 86400.0
        for i in range(rows_per_session):
            t_d = t_session + 900.0 * i
            r = float(rng.standard_normal() * math.sqrt(v_hat))
            q = float(v_hat * rng.chisquare(15) / 15.0)
            z = np.array([1.0, r, abs(r) / math.sqrt(v_hat), math.log(q) - math.log(v_hat)])
            eps = L @ rng.standard_normal(4)
            dx = (A_true @ z if A_true is not None else np.zeros(4)) + eps
            start = {"x_iv": math.log(0.18), "x_sk": -0.35, "x_sp": math.log(0.02), "x_sz": math.log(1 + 25)}
            rows.append({"row_id": "%s:%02d" % (day, i), "session": day, "r": r, "q": q, "v_hat": v_hat,
                         "start": start, "end": {k: start[k] + float(dx[j]) for j, k in enumerate(("x_iv", "x_sk", "x_sp", "x_sz"))},
                         "spread_floored": False, "endpoint_missing": False,
                         "available_deadline": t_d + 900.0 + 120.0 + 60.0})
    return rows


def permute_sessions(rows: list, *, seed: int) -> list:
    """The permutation UNIT is the whole session: predictor blocks are permuted against outcome blocks, so the
    within-session time structure is preserved and only the between-block association is destroyed."""
    rng = np.random.default_rng(seed)
    by = {}
    for r in rows:
        by.setdefault(r["session"], []).append(r)
    keys = sorted(by)
    perm = list(rng.permutation(len(keys)))
    out = []
    for i, k in enumerate(keys):
        src = by[keys[perm[i]]]
        dst = by[k]
        n = min(len(src), len(dst))
        for j in range(n):
            a, b = dst[j], src[j]                       # outcomes from this session, predictors from the permuted one
            out.append({**a, "r": b["r"], "q": b["q"], "v_hat": b["v_hat"], "row_id": a["row_id"] + "~perm"})
    return out


def quotes_for_state(*, expiration: str, strikes: list, spot: float, iv: float, skew: float, spread_rel: float,
                     size: int, t: float, T_years: float, available_lag: float = 0.5) -> dict:
    """A coherent quote set consistent with an anchored slice, for fixtures."""
    from apex.multiverse_wb.pricing import bsm_price
    k_atm = min(strikes, key=lambda k: (abs(k - spot), k))
    out = {}
    for K in strikes:
        iv_k = math.exp(math.log(iv) + skew * math.log(K / k_atm))
        for right in ("CALL", "PUT"):
            mid = bsm_price(S=spot, K=float(K), T=T_years, sigma=iv_k, right=right)
            half = mid * spread_rel / 2.0
            out[(expiration, float(K), right)] = {"bid": round(max(0.01, mid - half), 4), "ask": round(mid + half, 4),
                                                  "bid_size": int(size), "ask_size": int(size),
                                                  "timestamp_epoch": t, "available_time": t + available_lag,
                                                  "source": "SYNTHETIC"}
    return out


def bars_and_underlyings(*, t_d: float, spot: float, n: int = 30):
    bars, unders = [], []
    for i in range(n):
        et = t_d - 120.0 - 60.0 * (n - 1 - i)      # the newest bar completes and is AVAILABLE before t_d
        bars.append({"event_time": et, "available_time": et + 60.5, "close": spot, "source": "SYNTHETIC",
                     "revision_policy": "revisions visible only if available <= t_d", "max_age_s": 120.0, "quality": "VALID"})
    for i in range(6):
        et = t_d - 2.0 * (6 - i)
        unders.append({"event_time": et, "available_time": et + 0.2, "value": spot, "kind": "NBBO", "source": "SYNTHETIC",
                       "revision_policy": "superseded by newer", "max_age_s": 15.0, "quality": "VALID"})
    return bars, unders
