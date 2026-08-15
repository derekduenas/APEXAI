"""Options expression interface — interfaces only; V1 expression is STOCK.

The future options layer consumes a CALIBRATED underlying distribution +
world simulation + real chain data (IV, skew, term structure, Greeks,
spreads, liquidity, event risk). None of that exists for Hunter yet, so
every non-stock request is a typed refusal. The existing expression
engine's law already governs the eventual path (options demand CALIBRATED
distributions; demotion to stock is recorded) — this interface adds the
Hunter-side socket without activating anything. No option-chain history
is fabricated, ever.
"""

from __future__ import annotations

EXPRESSIONS = ("NO_TRADE", "STOCK", "LONG_CALL", "LONG_PUT", "DEBIT_SPREAD")
V1_ALLOWED = ("NO_TRADE", "STOCK")


def select_expression(requested: str, *, distribution_status: str,
                      chain_available: bool = False) -> dict:
    if requested not in EXPRESSIONS:
        raise ValueError(f"undeclared expression {requested!r}")
    if requested in V1_ALLOWED:
        return {"expression": requested, "demoted": False, "reasons": []}
    reasons = ["options expression is DORMANT in Hunter v1"]
    if distribution_status not in ("ML_CALIBRATED", "HYBRID_CALIBRATED"):
        reasons.append(f"distribution status {distribution_status!r} is not "
                       f"calibrated; options demand calibration")
    if not chain_available:
        reasons.append("no real option-chain data; none may be fabricated")
    return {"expression": "STOCK", "demoted": True, "reasons": reasons}
