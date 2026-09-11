"""Finite expression comparison under COMMON paths and documented costs at the ACTUAL exit horizon (M4).

For a long option exited at horizon H (15 minutes):
    Pi_H = q M (B_exit - A_entry) - F_entry - F_exit
Entry ask and exit bid already include spread crossing; latency/slippage enter through the execution
model exactly once. Exit bid on a path = model price at (S_H, IV_H, T - H) minus half the spread
scenario. Candidates: WAIT (zero), the deterministic pilot baseline (nearest >= 21 DTE, nearest-ATM,
one contract) and any declared alternative contract. Selection authority is NONE: the first pilot's
selection stays the deterministic rule; this comparison is RECORDED with the candidate set and the
rejection reasons. Expected economic value is marked UNESTABLISHED whenever future IV is not credibly
modeled (IV_FIXED): a sensitivity surface over IV shifts is reported instead of a point claim."""
from __future__ import annotations

import math

import numpy as np

from .pricing import bsm_price, bsm_price_vec, sanitize_quote, PricingRefused

SELECTION_AUTHORITY = "NONE: the pilot's deterministic rule selects; this comparison is recorded, not applied"


def _pnl_paths(*, paths: dict, inst: dict, entry_ask: float, T_years: float, horizon_years: float, r: float, fees_entry: float,
               fees_exit: float, spread_bps_exit=None, iv_override=None) -> np.ndarray:
    S_H = paths["S"][:, -1]
    IV_H = paths["iv"][:, -1] if iv_override is None else np.full(len(S_H), iv_override)
    sp = paths["spread_bps"][:, -1] if spread_bps_exit is None else np.full(len(S_H), spread_bps_exit)
    T_exit = max(T_years - horizon_years, 1e-6)
    model_mid = bsm_price_vec(S_H, inst["strike"], T_exit, IV_H, r=r, q=inst.get("dividend_yield", 0.0), right=inst["right"])
    exit_bid = np.maximum(model_mid * (1 - sp / 2e4), 0.0)
    return 100.0 * (exit_bid - entry_ask) - fees_entry - fees_exit


def compare(*, paths: dict, candidates: list, T_years_by_contract: dict, horizon_years: float, r: float, fees_entry: float,
            fees_exit: float, now: float, quote_max_age_s: float = 15.0, iv_shifts=(-0.2, -0.1, 0.0, 0.1, 0.2)) -> dict:
    """candidates: [{"label", "instrument", "quote"}] where quote is a raw provider quote. Returns the recorded
    comparison: every candidate with its economics or its rejection reason, WAIT included."""
    iv_fixed = "IV held fixed" in " ".join(paths.get("restrictions", []))
    rows = [{"label": "WAIT", "expected_net_pnl": 0.0, "p_loss": 0.0, "q05": 0.0, "q25": 0.0, "certified_max_loss": 0.0,
             "status": "ELIGIBLE", "note": "no trade is always an eligible action"}]
    for c in candidates:
        inst = c["instrument"]
        try:
            q = sanitize_quote(c["quote"], now=now, max_age_s=quote_max_age_s)
        except PricingRefused as e:
            rows.append({"label": c["label"], "status": "REJECTED", "why": "QUOTE: %s" % e}); continue
        if inst["exercise"] == "AMERICAN":
            note = "AMERICAN instrument priced at exit with the European formula as a DECLARED approximation (long option, no dividend within horizon)"
        else:
            note = "European exit repricing"
        T = T_years_by_contract.get(c["label"])
        if T is None or T <= horizon_years:
            rows.append({"label": c["label"], "status": "REJECTED", "why": "EXPIRY_INSIDE_HORIZON_OR_UNKNOWN"}); continue
        pnl = _pnl_paths(paths=paths, inst=inst, entry_ask=q["ask"], T_years=T, horizon_years=horizon_years, r=r, fees_entry=fees_entry, fees_exit=fees_exit)
        sens = {}
        for sh in iv_shifts:
            p2 = _pnl_paths(paths=paths, inst=inst, entry_ask=q["ask"], T_years=T, horizon_years=horizon_years, r=r, fees_entry=fees_entry,
                            fees_exit=fees_exit, iv_override=float(paths["iv"][:, -1].mean() * (1 + sh)))
            sens[str(sh)] = float(p2.mean())
        rows.append({"label": c["label"], "status": "ELIGIBLE", "expected_net_pnl": float(pnl.mean()), "p_loss": float(np.mean(pnl < 0)),
                     "q05": float(np.quantile(pnl, 0.05)), "q25": float(np.quantile(pnl, 0.25)), "q50": float(np.quantile(pnl, 0.5)),
                     "certified_max_loss": 100.0 * q["ask"] + fees_entry + fees_exit, "entry_ask": q["ask"], "entry_spread_rel": q["spread_rel"],
                     "mc_se_mean": float(pnl.std() / math.sqrt(len(pnl))), "iv_sensitivity_of_expected_pnl": sens,
                     "expected_value_established": (not iv_fixed), "pricing_note": note,
                     "quote_uncertainty": "entry at the sanitized ask; exit bid = model mid - half spread scenario; no queue position assumed"})
    return {"selection_authority": SELECTION_AUTHORITY, "common_paths": {"n_paths": paths["n_paths"], "seed": paths["seed"], "parameter_hash": paths["parameter_hash"],
                                                                         "restrictions": paths.get("restrictions", [])},
            "costs": {"fees_entry": fees_entry, "fees_exit": fees_exit, "spread": "exit bid = model mid minus half the spread scenario; entry at ask",
                      "double_counting": "spread crossing is in the quoted sides only; not subtracted again"},
            "horizon_years": horizon_years, "candidates": rows,
            "expected_value_note": ("UNESTABLISHED: future IV is held fixed; the IV sensitivity table stands in for a point claim" if iv_fixed
                                    else "IV process declared; expected values are model-conditional"),
            "no_arbitrage_label": "a physical-vs-implied discrepancy is a research feature, never an arbitrage label"}


CALENDAR_YEAR_S = 365.0 * 86400.0
HORIZON_15M_CALENDAR_YEARS = 900.0 / CALENDAR_YEAR_S          # expiry decay over the 15-minute hold, in the SAME calendar convention as T


def physical_vs_implied(*, physical_var_15m: float, implied_iv_annual: float, T_years: float | None = None,
                        trading_minutes_to_expiry: float | None = None, minutes_per_year: float = 252 * 390) -> dict:
    """Compare at a COMPATIBLE horizon. Two clocks are kept apart and named:
       - implied vol is annualized on CALENDAR time (T_years = calendar seconds to expiry / 365d);
       - realized variance accrues on MARKET time (one-minute bars during regular hours).
    Convention (declared): the option's total implied variance to expiry, iv^2 * T_years, is allocated uniformly over
    the TRADING minutes remaining to expiry, so implied_var_15m = iv^2 * T_years * 15 / trading_minutes_to_expiry.
    Without T_years the legacy per-trading-minute scaling iv^2 * 15 / (252*390) is used and labelled."""
    if T_years is not None and trading_minutes_to_expiry:
        implied_var_15m = implied_iv_annual ** 2 * T_years * (15.0 / trading_minutes_to_expiry)
        convention = "iv^2 * T_calendar * 15 / trading_minutes_to_expiry (total implied variance allocated over trading minutes)"
    else:
        implied_var_15m = implied_iv_annual ** 2 * (15.0 / minutes_per_year)
        convention = "LEGACY: iv^2 * 15 / (252*390) per trading minute"
    return {"physical_var_15m": physical_var_15m, "implied_var_15m": implied_var_15m, "convention": convention,
            "log_ratio": math.log(physical_var_15m / implied_var_15m) if physical_var_15m > 0 and implied_var_15m > 0 else None,
            "interpretation": ("a difference between predicted realized variance and implied variance is a research FEATURE with a risk premium and model "
                               "uncertainty inside it; it is not a mechanical arbitrage signal"), "risk_premium_disclosed": True}
