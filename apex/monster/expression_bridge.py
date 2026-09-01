"""MONSTER V_NEXT — the expression-engine bridge.

Fixes the wind-tunnel-confirmed IMPLEMENTATION DEFECT
(FLIGHT-SIMULATOR-V1-FIVE-SESSION-WINDTUNNEL, finding 1): option
expressions previously carried quotes but never an economic score, so
CASH won by forfeit. This bridge invokes the EXISTING
apex/expression/engine.py against an EMPIRICAL cohort distribution so
stock / long put / put spread / CASH compete on expected after-cost
value.

HONESTY LAWS
  * The pmf is the raw empirical distribution of PRIOR cohort
    outcomes supplied by the caller (expanding, as-of the event:
    causality is the caller's declared responsibility). It is
    labeled UNCALIBRATED_MODEL -- the engine's as_recommendation()
    correctly refuses it; we use SCORES, never recommendations.
  * Distribution horizon is the deepest sealed cohort checkpoint;
    structures are repriced with one day elapsed (declared
    approximation for a session hold).
  * IV is implied from each leg's own quote MID by bisection on the
    engine's own bs_price -- no vendor IV is invented.
  * Anything missing -> NOT_ESTIMABLE, and CASH can still win, but
    only for a stated economic reason.

STATIC POSITION MANAGEMENT IS UNCHANGED. decision_power: SHADOW.
"""
from __future__ import annotations

import numpy as np

from apex.expression.engine import (DistributionSource,
                                    ExpressionInput, OptionQuote,
                                    bs_price, evaluate)

VERSION = "MONSTER_VNEXT_EXPRESSION_WIRED_V1"
RISK_AVERSION = 2.0            # declared, not tuned
OBJECTIVE = "exponential_utility"


class _Config:
    def get(self, key):
        return {"expression.risk_aversion": RISK_AVERSION,
                "expression.objective": OBJECTIVE}[key]


def implied_vol(kind: str, spot: float, strike: float,
                dte_days: int, price: float) -> float | None:
    """Bisection on the engine's own bs_price. None if the quote is
    outside no-arbitrage bounds for any vol in [1%, 500%]."""
    t = dte_days / 365.0
    lo, hi = 0.01, 5.0
    if not (bs_price(kind, spot, strike, t, lo) <= price
            <= bs_price(kind, spot, strike, t, hi)):
        return None
    for _ in range(60):
        mid = (lo + hi) / 2
        if bs_price(kind, spot, strike, t, mid) < price:
            lo = mid
        else:
            hi = mid
    return round((lo + hi) / 2, 4)


def score_expressions(*, spot: float, dte_days: int,
                      atm_put: dict, otm_put: dict | None,
                      cohort_returns_bps: list,
                      rt_cost_bps: float) -> dict:
    """Score stock / options / CASH against the empirical pmf.
    atm_put/otm_put: {"strike","bid","ask"} real NBBO.
    cohort_returns_bps: UNDERLYING returns (bps) of prior cohort
    events at the sealed horizon -- expanding, supplied causally."""
    if len(cohort_returns_bps) < 60:
        return {"status": "NOT_ESTIMABLE", "version": VERSION,
                "why": f"cohort n={len(cohort_returns_bps)} < 60: "
                       f"no distribution, no engine, CASH stands"}
    r = np.asarray(cohort_returns_bps, dtype=float) / 1e4
    # discretize to a pmf on quantile-spaced grid
    qs = np.linspace(0.01, 0.99, 33)
    grid = np.quantile(r, qs)
    probs = np.full(len(grid), 1.0 / len(grid))

    chain = []
    for q, name in ((atm_put, "atm_put"), (otm_put, "otm_put")):
        if not q or not (q.get("ask", 0) > q.get("bid", 0) > 0):
            continue
        mid = (q["bid"] + q["ask"]) / 2
        iv = implied_vol("put", spot, q["strike"], dte_days, mid)
        if iv is None:
            continue
        chain.append(OptionQuote(kind="put", strike=q["strike"],
                                 expiry_days=dte_days,
                                 bid=q["bid"], ask=q["ask"], iv=iv,
                                 open_interest=q.get("oi", 0),
                                 volume=q.get("volume", 0)))
    try:
        inp = ExpressionInput(
            horizon_days=1, returns=grid, probs=probs,
            distribution_source=DistributionSource
            .UNCALIBRATED_MODEL,
            chain=tuple(chain), spot=spot, borrow_ok=False)
        rep = evaluate(inp, _Config())
    except Exception as e:                              # noqa: BLE001
        return {"status": "NOT_ESTIMABLE", "version": VERSION,
                "why": f"engine refused: {type(e).__name__}: {e}"}

    rows = {}
    for c in rep.candidates:
        # per-share P&L -> bps of spot; stock rows also pay the
        # observed equity round trip
        ev_bps = c.expected_pnl / spot * 1e4
        if c.name == "common_stock":
            ev_bps -= rt_cost_bps
        rows[c.name] = {
            "expected_net_bps_of_spot": round(ev_bps, 1),
            "max_loss_bps_of_spot": round(
                c.max_loss / spot * 1e4, 1),
            "p5_bps": round(c.pnl_p5 / spot * 1e4, 1),
            "p95_bps": round(c.pnl_p95 / spot * 1e4, 1),
            "spread_cost_bps": round(
                c.spread_cost / spot * 1e4, 1),
            "liquidity_score": c.liquidity_score}
    rows["CASH"] = {"expected_net_bps_of_spot": 0.0,
                    "max_loss_bps_of_spot": 0.0}
    best = max(rows, key=lambda k:
               rows[k]["expected_net_bps_of_spot"])
    return {"status": "SCORED", "version": VERSION,
            "distribution_source": "UNCALIBRATED_MODEL "
            "(empirical prior cohort; engine refuses "
            "recommendation status by law)",
            "cohort_n": len(cohort_returns_bps),
            "structures": rows, "best_expression": best,
            "cash_verdict_reason": (
                "CASH_WINS_ECONOMICALLY" if best == "CASH"
                else f"{best} beats CASH by "
                f"{rows[best]['expected_net_bps_of_spot']} bps"),
            "law": "CASH may win, but never again by forfeit"}
