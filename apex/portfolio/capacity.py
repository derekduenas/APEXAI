"""Capacity engine v1: implementation reality FLOWS INTO the economics.

A strategy that makes 10% before implementation and 0.3% after is not a
profitable opportunity; this module is where that subtraction happens, with
declared constants and a square-root impact model, so the opportunity engine
ranks NET-OF-EVERYTHING numbers and nothing else.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import math

EVIDENCE_CLASS = "engineering_measurement"

MAX_PARTICIPATION = 0.05            # of ADV per day, declared
IMPACT_COEFF_BPS = 25.0             # sqrt-model coefficient, conservative
MIN_VIABLE_NOTIONAL = 5_000.0       # below this, fixed frictions dominate


@dataclass(frozen=True)
class CapacityAssessment:
    tradeable: bool
    reasons: tuple
    capacity_usd: float             # max deployable at MAX_PARTICIPATION
    days_to_build: float
    impact_bps: float
    spread_bps: float
    total_implementation_bps_roundtrip: float
    expected_gross_annual: float
    expected_net_annual: float      # gross minus EVERYTHING, annualised
    evidence_class: str = field(default=EVIDENCE_CLASS)


def assess_capacity(*, target_notional: float, addv_usd: float,
                    relative_spread: float, annual_turnover: float,
                    expected_gross_annual: float,
                    build_days: int = 5) -> CapacityAssessment:
    """Deterministic implementation economics for ONE candidate position."""
    reasons = []
    capacity = MAX_PARTICIPATION * addv_usd * build_days
    if target_notional < MIN_VIABLE_NOTIONAL:
        reasons.append(f"notional {target_notional:.0f} below the "
                       f"{MIN_VIABLE_NOTIONAL:.0f} viability floor")
    if target_notional > capacity:
        reasons.append(f"notional {target_notional:,.0f} exceeds capacity "
                       f"{capacity:,.0f} at {MAX_PARTICIPATION:.0%} "
                       f"participation over {build_days}d")

    participation = target_notional / max(addv_usd * build_days, 1.0)
    impact_bps = IMPACT_COEFF_BPS * math.sqrt(min(participation, 1.0))
    spread_bps = relative_spread / 2 * 1e4          # half-spread per side
    per_side_bps = impact_bps + spread_bps
    roundtrip_bps = 2 * per_side_bps
    annual_cost = annual_turnover * roundtrip_bps / 1e4
    net = expected_gross_annual - annual_cost
    if net <= 0 and not reasons:
        reasons.append(f"implementation consumes the edge: gross "
                       f"{expected_gross_annual:+.2%} - costs "
                       f"{annual_cost:.2%} <= 0")

    return CapacityAssessment(
        tradeable=not reasons, reasons=tuple(reasons),
        capacity_usd=round(capacity, 0), days_to_build=float(build_days),
        impact_bps=round(impact_bps, 1), spread_bps=round(spread_bps, 1),
        total_implementation_bps_roundtrip=round(roundtrip_bps, 1),
        expected_gross_annual=float(expected_gross_annual),
        expected_net_annual=round(net, 5))
