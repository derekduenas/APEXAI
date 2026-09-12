"""Deterministic expression rules for the options pilot.

No "best option", no mispricing claim, no breakeven ranking. Expiration
breakevens cannot say which 21+ DTE option best monetises a move before
today's close, so the pilot does not pretend to know. The rule exists so the
recording boundary has something deterministic to record.

    direction_signal LONG  -> BUY one CALL
    direction_signal SHORT -> BUY one PUT
    expiration: nearest available with DTE >= 21 (CANDIDATE_RULES.dte_min_days)
    quantity:   1, filled or unfilled

Two versioned strike selectors exist. Every intent seals the version it used.

PILOT_RULE_V1 (frozen 2026-09-04): strike nearest to spot (ties -> lower).
    DEFECT recorded 2026-09-11 under PROFIT_TRANSITION_DIRECTIVE hard law one
    ("0 trades because attacks are structurally impossible = DEFECT"): with a
    $500 per-trade cap (max entry 5.00/share) and SPY ATM 21-DTE asks near 9,
    V1's choice is refused by the risk envelope on every scan, and V1 never
    looks at the next strike. V1 is kept for replay of records that sealed it.

PILOT_RULE_V2 (2026-09-11): among strikes on the SIGNAL'S SIDE of spot
    (CALL: K >= spot; PUT: K <= spot) whose INDICATIVE ask is <= max_entry_price,
    the one nearest to spot (ties -> lower). The cap is a fact about the account
    and enters HERE, in expression, downstream of the signal; candidate
    generation upstream stays blind to capital. A strike selected by V2 says what
    V1 could not express: "the nearest feasible strike is N strikes / p% away".

The forecast distribution is recorded but does NOT drive expression choice:
horizon-consistent option valuation is a separate capability."""
from __future__ import annotations

from datetime import date

DTE_MIN_DAYS = 21
RULE_ID_V1 = "PILOT_RULE_V1: signal->right, nearest expiry >= 21 DTE, nearest-ATM strike, 1 contract"
RULE_ID_V2 = ("PILOT_RULE_V2: signal->right, nearest expiry >= 21 DTE, nearest strike on the signal's side with "
              "indicative ask <= max_entry_price, 1 contract")
RULE_ID = RULE_ID_V1            # the frozen V1 id, kept for records that sealed it
RULE_IDS = {"PILOT_RULE_V1": RULE_ID_V1, "PILOT_RULE_V2": RULE_ID_V2}
DEFAULT_RULE = "PILOT_RULE_V2"
V1_DEFECT = ("DEFECT_PTD_HARD_LAW_ONE: PILOT_RULE_V1 selects nearest-to-spot without consulting the entry cap, so under a "
             "$500 cap on SPY every intent is RISK_ENVELOPE_INFEASIBLE by construction (0 trades because attacks are "
             "structurally impossible). Recorded 2026-09-11; V2 is the repair.")


class RuleRefused(ValueError):
    pass


def _num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and x == x


def _side_and_expiry(*, direction_signal, spot, as_of, available):
    if direction_signal not in ("LONG", "SHORT"):
        raise RuleRefused("NO_DIRECTION_SIGNAL: the heuristic label is %r; the rule needs LONG or SHORT" % direction_signal)
    if not _num(spot) or not spot > 0:
        raise RuleRefused("NO_SPOT: %r" % spot)
    right = "CALL" if direction_signal == "LONG" else "PUT"
    today = date.fromisoformat(as_of[:10])
    exps = sorted({c["expiration"] for c in available if c.get("right") == right})
    eligible = [e for e in exps if (date.fromisoformat(e) - today).days >= DTE_MIN_DAYS]
    if not eligible:
        raise RuleRefused("NO_ELIGIBLE_EXPIRY: none with DTE >= %d among %s" % (DTE_MIN_DAYS, exps[:4]))
    exp = eligible[0]
    rows = [c for c in available if c.get("right") == right and c["expiration"] == exp]
    if not rows:
        raise RuleRefused("NO_STRIKES for %s %s" % (exp, right))
    return right, exp, rows


def _ask_at(rows, strike):
    ref = [c.get("ask") for c in rows if float(c["strike"]) == strike]
    return ref[0] if ref and _num(ref[0]) else None


def choose(*, symbol: str, direction_signal: str | None, spot: float, as_of: str, available: list,
           rule: str = DEFAULT_RULE, max_entry_price: float | None = None) -> dict:
    """`available` is a list of contract dicts {expiration, strike, right, [ask]}. `ask` is an INDICATIVE
    chain-snapshot value, never a fill price. Returns the intent shape (expression, action, contract, ...) or
    refuses. V2 requires `max_entry_price`; V1 ignores it."""
    if rule not in RULE_IDS:
        raise RuleRefused("RULE_UNKNOWN: %r" % (rule,))
    right, exp, rows = _side_and_expiry(direction_signal=direction_signal, spot=spot, as_of=as_of, available=available)
    strikes = sorted({float(c["strike"]) for c in rows})
    atm = min(strikes, key=lambda k: (abs(k - spot), k))
    atm_ask = _ask_at(rows, atm)
    base = {"expression": "LONG_CALL" if right == "CALL" else "LONG_PUT", "action": "BUY", "quantity": 1}

    if rule == "PILOT_RULE_V1":
        return {**base, "contract": {"symbol": symbol, "expiration": exp, "strike": atm, "right": right},
                "expression_rule": RULE_ID_V1, "reference_ask": atm_ask,
                "strike_selection": {"rule": "PILOT_RULE_V1", "spot": spot, "strike": atm, "atm_strike": atm,
                                     "distance": round(atm - spot, 4), "distance_pct": round(100.0 * (atm - spot) / spot, 4),
                                     "cap_consulted": False, "defect": V1_DEFECT}}

    if not _num(max_entry_price) or not max_entry_price > 0:
        raise RuleRefused("NO_MAX_ENTRY_PRICE: PILOT_RULE_V2 needs the envelope cap; got %r" % (max_entry_price,))
    on_side = [k for k in strikes if (k >= spot if right == "CALL" else k <= spot)]
    priced = [k for k in on_side if _ask_at(rows, k) is not None]
    feasible = [k for k in priced if _ask_at(rows, k) <= max_entry_price]
    census = {"strikes": len(strikes), "on_signal_side": len(on_side), "with_indicative_ask": len(priced), "feasible": len(feasible),
              "atm_strike": atm, "atm_ask": atm_ask, "max_entry_price": max_entry_price}
    if not priced:
        raise RuleRefused("NO_INDICATIVE_ASKS: V2 cannot judge feasibility without chain asks; census %s" % census)
    if not feasible:
        cheapest = min(priced, key=lambda k: _ask_at(rows, k))
        raise RuleRefused("NO_FEASIBLE_STRIKE: cheapest on-side ask %.2f at K=%s > cap %.2f; census %s"
                          % (_ask_at(rows, cheapest), cheapest, max_entry_price, census))
    strike = min(feasible, key=lambda k: (abs(k - spot), k))
    ask = _ask_at(rows, strike)
    idx_atm, idx_k = strikes.index(atm), strikes.index(strike)
    return {**base, "contract": {"symbol": symbol, "expiration": exp, "strike": strike, "right": right},
            "expression_rule": RULE_ID_V2, "reference_ask": ask,          # INDICATIVE only (chain snapshot); never a fill price
            "strike_selection": {"rule": "PILOT_RULE_V2", "spot": spot, "strike": strike, "reference_ask": ask,
                                 "distance": round(strike - spot, 4), "distance_pct": round(100.0 * (strike - spot) / spot, 4),
                                 "strikes_from_atm": abs(idx_k - idx_atm), "cap_consulted": True, "census": census,
                                 "what_v1_could_not_express": ("V1 would have chosen K=%s (ask %s), which the envelope refuses when ask > "
                                                               "%.2f; V2 states the nearest feasible strike is %d strikes / %.2f%% from spot"
                                                               % (atm, atm_ask, max_entry_price, abs(idx_k - idx_atm),
                                                                  100.0 * (strike - spot) / spot))}}
