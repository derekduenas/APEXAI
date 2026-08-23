"""EXPRESSION COMPETITION -- "which weapon monetizes this thesis?"

THE CORE LAW: GOOD UNDERLYING THESIS != GOOD OPTION TRADE. A correct
directional call expressed through the wrong instrument loses money to
theta, spread and breakeven distance. This module makes STOCK,
LONG_CALL, LONG_PUT, CALL_VERTICAL, PUT_VERTICAL and NO_TRADE compete
on REAL QUOTED ECONOMICS at time T.

FILL LAW (quoted-side semantics, per-contract):

    LONG  leg entry = THAT EXACT CONTRACT's ASK
    SHORT leg entry = THAT EXACT CONTRACT's BID
    debit vertical  = long_ask - short_bid

No midpoint fill, no theoretical/model fill, and NO cross-contract
price assumption: we do not assert that one strike's premium must sit
below another's ask. That ordering usually holds for conventional debit
spreads, but a surface anomaly or unusual structure must never be able
to falsify a law -- the law is about WHICH SIDE OF ITS OWN QUOTE each
leg crosses, nothing more. Economic validity (e.g. a debit structure
costing more than its width) is checked separately, on its own terms.

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
    # NORMALIZATION INPUTS (2026-08-23): one contract is NOT universally
    # 100 shares of exposure -- a 0.50-delta call is ~50 share-
    # equivalents, a vertical often 20-30. Delta is carried so
    # comparisons can be made on equal INITIAL DELTA, not a fiction.
    net_delta: float | str = "NOT_ESTIMABLE"
    stock_equivalent_shares: float | str = "NOT_ESTIMABLE"
    max_theoretical_loss: float | None = None
    execution_pedigree: str = "OBSERVED_QUOTE"
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


def _delta(option_type, spot, strike, dte_years, rate, sigma):
    """Causal delta from the commissioned stack; NOT_ESTIMABLE if the
    inputs do not support it -- never a guessed 0.5."""
    if not all((spot, strike, dte_years, sigma)) or dte_years <= 0 \
            or sigma <= 0:
        return None
    try:
        from apex.option_analytics.bsm import greeks
        g = greeks(option_type=option_type, spot=spot, strike=strike,
                   time_to_expiry_years=dte_years, rate=rate,
                   sigma=sigma)
        return getattr(g, "delta", None) if not isinstance(g, dict) \
            else g.get("delta")
    except Exception:                                      # noqa: BLE001
        return None


def build_candidates(frozen, direction: str, *, shares: int = 100,
                     rules: dict = CANDIDATE_RULES,
                     iv: float | None = None, rate: float = 0.04,
                     stock_execution_pedigree: str = "MODELLED_EXECUTION"
                     ) -> list:
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
        net_delta=1.0 if direction == "LONG" else -1.0,
        stock_equivalent_shares=float(shares),
        max_theoretical_loss=round(spot * shares, 2),
        execution_pedigree=stock_execution_pedigree,
        notes=("max_loss shown is the instrument's theoretical bound, "
               "NOT the planned loss -- the strategy stop defines that",
               f"stock fill basis: {stock_execution_pedigree}")))

    # ---------- LONG single option (nearest-ATM, deterministic)
    import pandas as pd
    _Tn = pd.Timestamp(frozen.T)
    if _Tn.tzinfo is not None:
        _Tn = _Tn.tz_localize(None)
    _dte_y = max((pd.Timestamp(exp) - _Tn).days, 0) / 365.0
    _opt = "call" if right == "C" else "put"

    atm = min(strikes, key=lambda k: abs(k - spot))
    aq = q(atm)
    d_atm = _delta(_opt, spot, atm, _dte_y, rate, iv) if iv else None
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
            net_delta=(round(d_atm, 4) if d_atm is not None
                       else "NOT_ESTIMABLE"),
            stock_equivalent_shares=(round(abs(d_atm) * 100, 1)
                                     if d_atm is not None
                                     else "NOT_ESTIMABLE"),
            max_theoretical_loss=round(debit, 2),
            execution_pedigree="OBSERVED_QUOTE",
            notes=("long leg pays ASK",
                   "one contract is NOT 100 shares of exposure -- see "
                   "stock_equivalent_shares")))

        # ---------- VERTICAL (long ATM, short first wing >=1.5% OTM)
        target = atm * (1.015 if right == "C" else 0.985)
        wing = ([k for k in strikes if k >= target] if right == "C"
                else [k for k in reversed(strikes) if k <= target])
        if wing:
            wk = wing[0]
            wq = q(wk)
            if wq:
                wb, _wa = wq
                d_wing = (_delta(_opt, spot, wk, _dte_y, rate, iv)
                          if iv else None)
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
                    net_delta=(round(d_atm - d_wing, 4)
                               if (d_atm is not None
                                   and d_wing is not None)
                               else "NOT_ESTIMABLE"),
                    stock_equivalent_shares=(
                        round(abs(d_atm - d_wing) * 100, 1)
                        if (d_atm is not None and d_wing is not None)
                        else "NOT_ESTIMABLE"),
                    max_theoretical_loss=round(net, 2),
                    execution_pedigree="OBSERVED_QUOTE",
                    notes=("short leg receives BID -- never mid",
                           "favorable tail CAPPED at the wing",
                           "NET delta is long minus short -- a vertical "
                           "often carries only 20-30 share-equivalents")))
    return out


# ---------------------------------------------------------------------
# COMPARISON BASES (operator law, 2026-08-23). There is NO single
# correct normalization, so we never pick one and hide the rest.
COMPARISON_BASES = ("RAW_UNIT_ECONOMICS", "EQUAL_INITIAL_DELTA",
                    "EQUAL_RISK_BUDGET", "EQUAL_CAPITAL_DEPLOYED")

RISK_BASES = ("PLANNED_INVALIDATION", "MAX_LOSS", "FULL_PREMIUM",
              "OTHER_EXPLICIT")


def declared_risk(candidate, *, risk_basis: str,
                  planned_invalidation_loss: float | None = None
                  ) -> dict:
    """R MUST come from the risk DECLARED BEFORE the trade.

    Never automatically equate premium / max debit / stock notional
    with 1R. A long call held to zero really does risk the premium --
    but a call the strategy intends to abandon when the UNDERLYING
    invalidates risks far less, and treating the full premium as 1R
    would make that trade look artificially efficient (or artificially
    reckless) against stock."""
    if risk_basis not in RISK_BASES:
        raise ValueError(f"unknown risk_basis {risk_basis!r}")
    max_loss = candidate.max_theoretical_loss
    if risk_basis == "PLANNED_INVALIDATION":
        if planned_invalidation_loss is None:
            return {"declared_1R_dollars": "NOT_ESTIMABLE",
                    "risk_basis": risk_basis,
                    "reason": "planned invalidation loss not supplied "
                              "-- R may not be inferred"}
        r = min(planned_invalidation_loss, max_loss) if max_loss \
            else planned_invalidation_loss
    elif risk_basis in ("MAX_LOSS", "FULL_PREMIUM"):
        r = max_loss
    else:
        r = planned_invalidation_loss
    return {"declared_1R_dollars": (round(r, 2) if r else
                                    "NOT_ESTIMABLE"),
            "risk_basis": risk_basis,
            "capital_deployed": candidate.capital_required,
            "maximum_theoretical_loss": max_loss,
            "planned_invalidation_loss": planned_invalidation_loss,
            "law": "R is the loss the sealed plan intends, not an "
                   "instrument default"}


def normalize(candidates: list, *, risk_budget_dollars: float | None
              = None, risk_basis: str = "MAX_LOSS",
              planned_losses: dict | None = None) -> dict:
    """Every honest comparison basis, side by side. No winner is
    declared here."""
    planned_losses = planned_losses or {}
    out = {b: {} for b in COMPARISON_BASES}
    ref_delta = None
    for c in candidates:
        if c.expression == "STOCK":
            continue
        if isinstance(c.stock_equivalent_shares, (int, float)):
            ref_delta = c.stock_equivalent_shares
            break
    for c in candidates:
        risk = declared_risk(
            c, risk_basis=risk_basis,
            planned_invalidation_loss=planned_losses.get(c.expression))
        out["RAW_UNIT_ECONOMICS"][c.expression] = {
            "unit": "1 contract" if c.expression != "STOCK"
            else "stated share block",
            "debit": c.debit, "capital": c.capital_required,
            "max_theoretical_loss": c.max_theoretical_loss,
            **risk}
        out["EQUAL_INITIAL_DELTA"][c.expression] = (
            {"stock_equivalent_shares": c.stock_equivalent_shares,
             "net_delta": c.net_delta,
             "note": "stock sized to THIS many shares matches the "
                     "option's initial directional exposure"}
            if isinstance(c.stock_equivalent_shares, (int, float))
            else {"status": "NOT_ESTIMABLE",
                  "reason": "delta unavailable at decision time"})
        r1 = risk["declared_1R_dollars"]
        out["EQUAL_RISK_BUDGET"][c.expression] = (
            {"units_for_budget": round(risk_budget_dollars / r1, 3),
             "budget": risk_budget_dollars, "one_R": r1}
            if (risk_budget_dollars and isinstance(r1, (int, float))
                and r1 > 0)
            else {"status": "NOT_ESTIMABLE",
                  "reason": "no predeclared risk budget or 1R"})
        out["EQUAL_CAPITAL_DEPLOYED"][c.expression] = {
            "capital": c.capital_required,
            "caveat": "DIAGNOSTIC ONLY -- capital efficiency is not a "
                      "winner criterion"}
    out["_law"] = ("multiple bases preserved deliberately; one option "
                   "contract is NOT universally 100 shares of exposure, "
                   "and no single normalization may crown a winner")
    out["_reference_delta_shares"] = ref_delta
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
            "comparison_basis_required": True,
            "law": "ranking is an observation; Capital selects and "
                   "sizes. Breakeven reach > 1.0 means the option "
                   "needs MORE than the expected move merely to break "
                   "even. No OPTION_BETTER / STOCK_BETTER verdict may "
                   "be drawn from one normalization -- call normalize() "
                   "and report the basis explicitly."}
