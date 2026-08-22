"""SLEEVE RELEVANCE -- three expression venues, one brain.

The Observatory is cross-market FROM BIRTH even though only one sleeve
has live data. A pattern identifies which venues COULD express it; it
never selects one. Selection belongs to an Expression layer that does not
exist, so `BEST_EXPRESSION` is permanently `NOT_EVALUATED` here.

BTC perps has no data. Every accessor says so. There is no synthetic
placeholder, no zero-filled funding rate, and no "typical" open interest
-- a fabricated derivative reading would be worse than no sleeve at all,
because it would look like evidence.

decision_power: NONE_PATTERN_OBSERVATORY.
"""
from __future__ import annotations

from apex.pattern_observatory import OBSERVATORY_POWER

EQUITIES_INTRADAY = "EQUITIES_INTRADAY"
OPTIONS = "OPTIONS"
BTC_PERPS = "BTC_PERPS"
SLEEVES = (EQUITIES_INTRADAY, OPTIONS, BTC_PERPS)

NOT_EVALUATED = "NOT_EVALUATED"
NOT_AVAILABLE = "NOT_AVAILABLE"

SLEEVE_STATUS = {
    EQUITIES_INTRADAY: {
        "input_status": "LIVE",
        # Named by ROLE, not by vendor. The sleeve depends on "whatever
        # is the primary broad sensor", not on a particular data company,
        # and apex/governance keeps the vendor-naming exemption list
        # deliberately short -- a module should only name a vendor when
        # it cannot do its job otherwise.
        "source": "PRIMARY_BROAD_SENSOR canonical 1m bars, 164 symbols",
        "expressions": ("EQUITY_LONG", "EQUITY_SHORT", "NO_TRADE")},
    OPTIONS: {
        "input_status": "LIVE_OBSERVATIONAL",
        "source": "results/option_analytics/live/{states,surfaces}.jsonl",
        "note": "surface read as a WORLD SENSOR; the expression bridge "
                "(expression_engine.run / before_card.seal) has zero live "
                "callers, so options cannot be expressed",
        "expressions": ("CALL", "PUT", "CALL_SPREAD", "PUT_SPREAD",
                        "NO_TRADE")},
    BTC_PERPS: {
        "input_status": NOT_AVAILABLE,
        "source": None,
        "note": "sleeve not built; weekend target",
        "expected_inputs": ("funding", "open_interest", "basis",
                            "liquidations", "spot_perp_divergence", "cvd",
                            "order_book_imbalance", "cross_exchange_state",
                            "crypto_volatility", "btc_eth_leadership"),
        "expressions": ("PERP_LONG", "PERP_SHORT", "NO_TRADE")},
}


def sleeve_input_status(sleeve: str) -> dict:
    s = SLEEVE_STATUS.get(sleeve)
    if s is None:
        return {"sleeve": sleeve, "input_status": "UNKNOWN_SLEEVE",
                "decision_power": OBSERVATORY_POWER}
    return {"sleeve": sleeve, **s, "decision_power": OBSERVATORY_POWER}


def relevance(family) -> dict:
    """Which sleeves COULD express this family, and which of those can
    actually observe anything today."""
    potential = tuple(family.sleeves)
    live = tuple(s for s in potential
                 if SLEEVE_STATUS[s]["input_status"] != NOT_AVAILABLE)
    dark = tuple(s for s in potential if s not in live)
    expressions = []
    for s in live:
        expressions.extend(SLEEVE_STATUS[s]["expressions"])
    return {"kind": "sleeve_relevance", "family_id": family.family_id,
            "potential_sleeves": list(potential),
            "observable_sleeves": list(live),
            "dark_sleeves": list(dark),
            "potential_expressions": sorted(set(expressions)),
            "best_expression": NOT_EVALUATED,
            "why_not_evaluated": "expression selection belongs to a layer "
                                 "that has no live caller; identifying a "
                                 "venue is not choosing one",
            "decision_power": OBSERVATORY_POWER}
