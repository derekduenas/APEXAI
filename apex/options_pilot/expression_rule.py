"""ONE deterministic expression rule for OPTIONS-PILOT-001.

No "best option", no mispricing claim, no breakeven ranking. Expiration
breakevens cannot say which 21+ DTE option best monetises a move before
today's close, so the pilot does not pretend to know. The rule exists so the
recording boundary has something deterministic to record.

    direction_signal LONG  -> BUY one CALL
    direction_signal SHORT -> BUY one PUT
    expiration: nearest available with DTE >= 21 (CANDIDATE_RULES.dte_min_days)
    strike:     nearest to spot (ties -> lower strike)
    quantity:   1, filled or unfilled

The forecast distribution is recorded but does NOT drive expression choice in
this brick: horizon-consistent option valuation is a separate capability."""
from __future__ import annotations

from datetime import date

DTE_MIN_DAYS = 21
RULE_ID = "PILOT_RULE_V1: signal->right, nearest expiry >= 21 DTE, nearest-ATM strike, 1 contract"


class RuleRefused(ValueError):
    pass


def choose(*, symbol: str, direction_signal: str | None, spot: float, as_of: str,
           available: list) -> dict:
    """`available` is a list of contract dicts {expiration, strike, right}.
    Returns the intent shape (expression, action, contract) or refuses."""
    if direction_signal not in ("LONG", "SHORT"):
        raise RuleRefused("NO_DIRECTION_SIGNAL: the heuristic label is %r; the rule needs LONG or SHORT" % direction_signal)
    if not isinstance(spot, (int, float)) or not spot > 0:
        raise RuleRefused("NO_SPOT: %r" % spot)
    right = "CALL" if direction_signal == "LONG" else "PUT"
    today = date.fromisoformat(as_of[:10])
    exps = sorted({c["expiration"] for c in available if c.get("right") == right})
    eligible = [e for e in exps if (date.fromisoformat(e) - today).days >= DTE_MIN_DAYS]
    if not eligible:
        raise RuleRefused("NO_ELIGIBLE_EXPIRY: none with DTE >= %d among %s" % (DTE_MIN_DAYS, exps[:4]))
    exp = eligible[0]
    strikes = sorted({float(c["strike"]) for c in available if c.get("right") == right and c["expiration"] == exp})
    if not strikes:
        raise RuleRefused("NO_STRIKES for %s %s" % (exp, right))
    strike = min(strikes, key=lambda k: (abs(k - spot), k))
    ref = [c.get("ask") for c in available if c.get("right") == right and c["expiration"] == exp and float(c["strike"]) == strike]
    reference_ask = ref[0] if ref and isinstance(ref[0], (int, float)) and not isinstance(ref[0], bool) else None
    return {"expression": "LONG_CALL" if right == "CALL" else "LONG_PUT", "action": "BUY",
            "contract": {"symbol": symbol, "expiration": exp, "strike": strike, "right": right},
            "quantity": 1, "expression_rule": RULE_ID,
            "reference_ask": reference_ask,          # INDICATIVE only (chain snapshot); never a fill price
            }
