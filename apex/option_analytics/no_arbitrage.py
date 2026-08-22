"""Price sanity / no-arbitrage gates — checked BEFORE any price ever
reaches an IV solver. A bad quote fed to a solver produces a garbage
IV that looks exactly as precise as a good one; refusing here is
cheaper and more honest than debugging it downstream.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass

from apex.option_analytics import OPTION_ANALYTICS_POWER

VIOLATIONS = (
    "NEGATIVE_PRICE",
    "LOCKED_CROSSED_MARKET",
    "BELOW_INTRINSIC",
    "ABOVE_UPPER_BOUND",
)


class NoArbitrageError(RuntimeError):
    pass


@dataclass(frozen=True)
class PriceSanityVerdict:
    passed: bool
    violations: tuple
    intrinsic_value: float | None
    upper_bound: float | None
    known_from: str
    decision_power: str = OPTION_ANALYTICS_POWER

    def __post_init__(self):
        bad = set(self.violations) - set(VIOLATIONS)
        if bad:
            raise NoArbitrageError(f"unknown violation(s) {bad}")
        if self.passed and self.violations:
            raise NoArbitrageError("passed=True cannot carry violations")
        if not self.passed and not self.violations:
            raise NoArbitrageError("passed=False must name at least one violation")

    def as_record(self) -> dict:
        return {"kind": "price_sanity_verdict", **asdict(self)}


def check_price_sanity(*, option_type: str, spot: float, strike: float,
                       time_to_expiry_years: float, rate: float,
                       bid: float | None, ask: float | None,
                       known_from) -> PriceSanityVerdict:
    """`option_type`: "call" or "put". Checks the NBBO (bid/ask), not a
    single last-trade price -- callers must supply the real quote, this
    function never assumes bid==ask nor invents one from the other."""
    import pandas as pd
    violations = []

    if (bid is not None and bid < 0) or (ask is not None and ask < 0):
        violations.append("NEGATIVE_PRICE")
    if bid is not None and ask is not None and bid > ask:
        violations.append("LOCKED_CROSSED_MARKET")

    discounted_strike = strike * math.exp(-rate * time_to_expiry_years)
    if option_type == "call":
        intrinsic = max(0.0, spot - discounted_strike)
        upper_bound = spot
    elif option_type == "put":
        intrinsic = max(0.0, discounted_strike - spot)
        upper_bound = discounted_strike
    else:
        raise NoArbitrageError(f"unknown option_type {option_type!r}")

    # a locked/crossed market already failed; below-intrinsic / above-
    # upper-bound are judged off the ASK (cheapest way to acquire the
    # option) and BID (cheapest way to be paid to sell it) respectively.
    if ask is not None and ask < intrinsic - 1e-9:
        violations.append("BELOW_INTRINSIC")
    if bid is not None and bid > upper_bound + 1e-9:
        violations.append("ABOVE_UPPER_BOUND")

    return PriceSanityVerdict(
        passed=(not violations), violations=tuple(violations),
        intrinsic_value=intrinsic, upper_bound=upper_bound,
        known_from=str(pd.Timestamp(known_from)))
