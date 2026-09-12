"""Pricing adapter and PATH_ACCOUNTING_V1 (contract §2.5, §3.1, §3.2).

Pricing is ANCHORED at the frozen strike, so `iv` at `K_atm` reproduces `exp(x_iv)` exactly for every state.
Time to expiry is recomputed at EVERY evaluation instant. Every path receives a defined number under two named
accounting SCENARIOS (not bounds: they are not ordered), the selection value is their MINIMUM and the spread is an
absolute difference, so the rule-4 gate cannot pass through an inverted ordering."""
from __future__ import annotations

import math

import numpy as np

from apex.multiverse_wb.pricing import bsm_price_vec

CALENDAR_YEAR_S = 365.0 * 86400.0
H_S = 900.0
W_END_S = 120.0
LOG_IV_MIN, LOG_IV_MAX = math.log(1e-4), math.log(50.0)
MULT = 100.0
SIZE_POLICIES = ("ASSUME_AVAILABLE", "MODELLED_SIZE")
EXTENSION_SCALING = ("EXTENSION_SCALING_V1: linear-in-time drift and square-root-of-time innovation scaling over "
                     "2/15 of the horizon; an ASSUMPTION, not an estimate")


class PricingGuard(ValueError):
    pass


def slice_iv(*, x_iv, x_sk, K: float, K_atm: float) -> np.ndarray:
    """log iv_K = x_iv + x_sk * log(K / K_atm) — ANCHORED at the frozen strike (§2.5)."""
    return np.asarray(x_iv, dtype=float) + np.asarray(x_sk, dtype=float) * math.log(K / K_atm)


def T_at(expiry_epoch: float, t_eval: float) -> float:
    return (expiry_epoch - t_eval) / CALENDAR_YEAR_S


def price_paths(*, S, x_iv, x_sk, x_sp, x_sz, K: float, K_atm: float, right: str, expiry_epoch: float, t_eval: float) -> dict:
    """Vectorized state -> (mid, bid, size) with the declared RANGE guards; `log iv_K` may be negative."""
    T = T_at(expiry_epoch, t_eval)
    S = np.asarray(S, dtype=float)
    log_iv = slice_iv(x_iv=x_iv, x_sk=x_sk, K=K, K_atm=K_atm)
    bad = ~np.isfinite(log_iv) | (log_iv < LOG_IV_MIN) | (log_iv > LOG_IV_MAX) | ~np.isfinite(S) | (S <= 0)
    if T <= 0:
        return {"unpriceable": np.ones(len(S), dtype=bool), "why": "T_NOT_POSITIVE", "T": T}
    if bad.any():
        return {"unpriceable": bad, "why": "LOG_IV_OUT_OF_RANGE_OR_S_INVALID", "T": T,
                "first_bad": int(np.where(bad)[0][0]), "first_value": float(log_iv[np.where(bad)[0][0]])}
    iv = np.exp(log_iv)
    mid = bsm_price_vec(S, K, T, iv, r=0.0, q=0.0, right=right)
    sp = np.exp(np.asarray(x_sp, dtype=float))
    sz = np.maximum(0.0, np.exp(np.asarray(x_sz, dtype=float)) - 1.0)
    if not (np.all(np.isfinite(mid)) and np.all(np.isfinite(sp)) and np.all(np.isfinite(sz))):
        return {"unpriceable": ~(np.isfinite(mid) & np.isfinite(sp) & np.isfinite(sz)), "why": "NONFINITE_PRICE_STATE", "T": T}
    return {"unpriceable": np.zeros(len(S), dtype=bool), "mid": mid, "bid": mid * (1.0 - sp / 2.0), "size": sz,
            "iv": iv, "spread_rel": sp, "T": T}


def account(*, primary: dict, extension: dict | None, entry_ask: float, fees_in: float, fees_out: float,
            size_policy: str = "ASSUME_AVAILABLE") -> dict:
    """One candidate's per-path economics. Returns paired S1/S2 arrays and the counters (§3.1, §3.2)."""
    if size_policy not in SIZE_POLICIES:
        raise ValueError("SIZE_POLICY_UNKNOWN: %r" % (size_policy,))
    if primary.get("unpriceable") is None or primary["unpriceable"].any():
        return {"refused": "UNPRICEABLE_PATH_PRESENT", "stage": "PRIMARY", "count": int(primary["unpriceable"].sum()),
                "why": primary.get("why"), "first_bad": primary.get("first_bad")}
    n = len(primary["bid"])
    achievable = primary["bid"] > 0
    if size_policy == "MODELLED_SIZE":
        achievable &= primary["size"] >= 1.0
    mid_last = primary["mid"].copy()
    from_stage = np.full(n, "PRIMARY", dtype=object)
    achieved_primary = achievable.copy()
    achieved_ext = np.zeros(n, dtype=bool)
    ext_undefined = 0
    bid_used = primary["bid"].copy()
    if (~achievable).any() and extension is not None:
        if extension.get("undefined"):
            ext_undefined = int((~achievable).sum())
        elif extension["unpriceable"].any():
            return {"refused": "UNPRICEABLE_PATH_PRESENT", "stage": "EXTENSION",
                    "count": int(extension["unpriceable"].sum()), "why": extension.get("why")}
        else:
            idx = ~achievable
            ext_ok = extension["bid"] > 0
            if size_policy == "MODELLED_SIZE":
                ext_ok = ext_ok & (extension["size"] >= 1.0)
            mid_last[idx] = extension["mid"][idx]
            from_stage[idx] = "EXTENSION"
            newly = idx & ext_ok
            bid_used[newly] = extension["bid"][newly]
            achieved_ext = newly
            achievable = achievable | newly
    elif (~achievable).any() and extension is None:
        ext_undefined = int((~achievable).sum())
    s1 = np.where(achievable, MULT * (bid_used - entry_ask) - fees_in - fees_out, -MULT * entry_ask - fees_in)
    s2 = np.where(achievable, MULT * (bid_used - entry_ask) - fees_in - fees_out,
                  MULT * (mid_last - entry_ask) - fees_in - fees_out)
    m1, m2 = float(s1.mean()), float(s2.mean())
    return {"refused": None, "S1": s1, "S2": s2, "mean_S1": m1, "mean_S2": m2,
            "E_sel": min(m1, m2), "U": abs(m1 - m2), "selected_scenario": ("S1" if m1 <= m2 else "S2"),
            "availability_failure_rate": float((~achievable).mean()), "size_policy": size_policy,
            "counters": {"achieved_primary_n": int(achieved_primary.sum()), "achieved_extension_n": int(achieved_ext.sum()),
                         "not_achievable_n": int((~achievable).sum()), "extension_undefined_n": ext_undefined,
                         "unpriceable_n": 0},
            "scenarios_from": {"PRIMARY": int((from_stage == "PRIMARY").sum()), "EXTENSION": int((from_stage == "EXTENSION").sum())},
            "labels": {"scenarios": "ACCOUNTING SCENARIOS, not bounds: S2 - S1 = 100*mid_last - fees_out can be negative",
                       "availability": "MODEL_CONDITIONAL_AVAILABILITY, not a fill probability"}}


def extension_state(*, A, z_ext, eps_ext, state0: dict) -> dict:
    """Δx_ext = (2/15) A z_ext + sqrt(2/15) eps_ext, applied to the horizon-end state (§3.2)."""
    f = 2.0 / 15.0
    dx = (f * (np.asarray(A) @ np.asarray(z_ext).T).T) + math.sqrt(f) * np.asarray(eps_ext)
    return {"x_iv": state0["x_iv"] + dx[:, 0], "x_sk": state0["x_sk"] + dx[:, 1],
            "x_sp": state0["x_sp"] + dx[:, 2], "x_sz": state0["x_sz"] + dx[:, 3], "scaling": EXTENSION_SCALING}
