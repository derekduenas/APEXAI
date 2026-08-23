"""EXPRESSION COMPETITION -- "which weapon monetizes this thesis?"

THE CORE LAW: GOOD UNDERLYING THESIS != GOOD OPTION TRADE. A correct
directional call expressed through the wrong instrument loses money to
theta, spread and breakeven distance. This module makes STOCK,
LONG_CALL, LONG_PUT, CALL_VERTICAL, PUT_VERTICAL and NO_TRADE compete
on REAL QUOTED ECONOMICS at time T.

FILL LAW: long legs pay ASK, short legs receive BID. No midpoint fill
is ever assumed -- a mid that never traded is a fantasy, and options
spreads are wide enough that mid-fills manufacture edge from nothing.

SELECTION LAW: strikes and expiries are chosen by DETERMINISTIC RULES
declared before outcomes are seen -- never the retrospectively best
strike. The rules live in CANDIDATE_RULES below.

decision_power: NONE -- it compares; Capital decides.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

EXPRESSIONS = ("STOCK", "LONG_CALL", "LONG_PUT", "CALL_VERTICAL",
               "PUT_VERTICAL", "NO_TRADE")

# pre-registered deterministic candidate rules (2026-08-23)
CANDIDATE_RULES = {
    "dte_target_days": 30,      # nearest expiry >= 21d, else nearest
    "dte_min_days": 21,
    "long_strike": "nearest-ATM",
    "vertical_wing": "first strike >= 1.5% OTM beyond the long strike",
    "note": "declared BEFORE any outcome inspection; never re-tuned "
            "against replay P&L",
}


@dataclass(frozen=True)
class ExpressionCandidate:
    expression: str
    direction: str
    legs: tuple                  # ((action, right, strike, price), ...)
    debit: float | None          # net cost per contract (100 mult)
    max_loss: float | None
    max_gain: float | str
    breakeven: float | None
    breakeven_move_pct: float | None
    quoted_spread_cost: float | None
    liquidity: str
    capital_required: float | None
    notes: tuple = ()

    def as_record(self) -> dict:
        return {"kind": "expression_candidate", **asdict(self)}


def _latest_by_contract(quotes: list) -> dict:
    out = {}
    for r in quotes:
        key = (r["expiration"], float(r["strike"]),
               "C" if r["right"].upper().startswith("C") else "P")
        prev = out.get(key)
        if prev is None or r["timestamp"] >= prev["timestamp"]:
            out[key] = r
    return out


def _pick_expiry(contracts: dict, T, rules) -> str | None:
    import pandas as pd
    Tn = pd.Timestamp(T)
    if Tn.tzinfo is not None:
        Tn = Tn.tz_localize(None)
    exps = sorted({k[0] for k in contracts})
    eligible = [e for e in exps
                if (pd.Timestamp(e) - Tn).days >= rules["dte_min_days"]]
    return eligible[0] if eligible else (exps[-1] if exps else None)


def build_candidates(frozen, direction: str, *, shares: int = 100,
                     rules: dict = CANDIDATE_RULES) -> list:
    """Every legitimate expression of one directional thesis at T."""
    spot = frozen.spot_ref
    if spot is None or direction not in ("LONG", "SHORT"):
        return []
    contracts = _latest_by_contract(list(frozen.option_quotes))
    if not contracts:
        return []
    exp = _pick_expiry(contracts, frozen.T, rules)
    if exp is None:
        return []
    right = "C" if direction == "LONG" else "P"
    strikes = sorted({k[1] for k in contracts if k[0] == exp
                      and k[2] == right})
    if not strikes:
        return []

    def q(strike):
        r = contracts.get((exp, strike, right))
        if not r:
            return None
        try:
            b, a = float(r["bid"]), float(r["ask"])
        except (TypeError, ValueError):
            return None
        return (b, a) if (b > 0 and a > 0 and a >= b) else None

    out = []
    # ---------- STOCK (the benchmark every option must beat)
    out.append(ExpressionCandidate(
        expression="STOCK", direction=direction,
        legs=(("BUY" if direction == "LONG" else "SELL", "STOCK",
               spot, spot),),
        debit=round(spot * shares, 2), max_loss=None,
        max_gain="UNBOUNDED" if direction == "LONG" else None,
        breakeven=spot, breakeven_move_pct=0.0,
        quoted_spread_cost=None, liquidity="UNDERLYING",
        capital_required=round(spot * shares, 2),
        notes=("max_loss None: bounded only by the strategy stop, not "
               "by the instrument",)))

    # ---------- LONG single option (nearest-ATM, deterministic)
    atm = min(strikes, key=lambda k: abs(k - spot))
    aq = q(atm)
    if aq:
        b, a = aq
        debit = a * 100
        be = atm + a if right == "C" else atm - a
        out.append(ExpressionCandidate(
            expression="LONG_CALL" if right == "C" else "LONG_PUT",
            direction=direction,
            legs=(("BUY", right, atm, a),),
            debit=round(debit, 2), max_loss=round(debit, 2),
            max_gain="UNBOUNDED" if right == "C" else
            round((atm - a) * 100, 2),
            breakeven=round(be, 4),
            breakeven_move_pct=round((be / spot - 1.0) * 100, 3),
            quoted_spread_cost=round((a - b) * 100, 2),
            liquidity="QUOTED",
            capital_required=round(debit, 2),
            notes=("long leg pays ASK",)))

        # ---------- VERTICAL (long ATM, short first wing >=1.5% OTM)
        target = atm * (1.015 if right == "C" else 0.985)
        wing = ([k for k in strikes if k >= target] if right == "C"
                else [k for k in reversed(strikes) if k <= target])
        if wing:
            wk = wing[0]
            wq = q(wk)
            if wq:
                wb, _wa = wq
                net = (a - wb) * 100          # pay ask, sell at BID
                width = abs(wk - atm) * 100
                bev = atm + (a - wb) if right == "C" else atm - (a - wb)
                out.append(ExpressionCandidate(
                    expression="CALL_VERTICAL" if right == "C"
                    else "PUT_VERTICAL", direction=direction,
                    legs=(("BUY", right, atm, a),
                          ("SELL", right, wk, wb)),
                    debit=round(net, 2), max_loss=round(net, 2),
                    max_gain=round(width - net, 2),
                    breakeven=round(bev, 4),
                    breakeven_move_pct=round((bev / spot - 1.0) * 100, 3),
                    quoted_spread_cost=round((a - b) * 100, 2),
                    liquidity="QUOTED",
                    capital_required=round(net, 2),
                    notes=("short leg receives BID -- never mid",
                           "favorable tail CAPPED at the wing")))
    return out


def compare(candidates: list, *, expected_move_pct: float | str
            ) -> dict:
    """Rank expressions against a thesis. Returns an OBSERVATION, not
    an order: if the expected move is not estimable, the honest answer
    is that no option can be shown superior to stock."""
    if not candidates:
        return {"verdict": "NO_TRADE",
                "reason": "no quotable expression at T"}
    rows = []
    for c in candidates:
        reach = None
        if isinstance(expected_move_pct, (int, float)) and \
                c.breakeven_move_pct is not None:
            # how much of the expected move is consumed getting to
            # breakeven -- <1 means the option can pay before the
            # thesis is fully realized
            denom = abs(expected_move_pct) or None
            reach = (abs(c.breakeven_move_pct) / denom
                     if denom else None)
        rows.append({"expression": c.expression,
                     "debit": c.debit, "max_loss": c.max_loss,
                     "max_gain": c.max_gain,
                     "breakeven_move_pct": c.breakeven_move_pct,
                     "breakeven_reach_ratio": (round(reach, 3)
                                               if reach else None),
                     "spread_cost": c.quoted_spread_cost,
                     "capital_required": c.capital_required})
    if not isinstance(expected_move_pct, (int, float)):
        return {"verdict": "NOT_ESTIMABLE",
                "reason": "expected move not estimable -- no option "
                          "may be declared superior to STOCK without "
                          "a forecast",
                "candidates": rows}
    return {"verdict": "COMPARED", "candidates": rows,
            "law": "ranking is an observation; Capital selects and "
                   "sizes. Breakeven reach > 1.0 means the option "
                   "needs MORE than the expected move merely to break "
                   "even."}
