"""Minimal monetisation EVALUATOR: does a factor survive basic implementation?

WHAT THIS IS
------------
The smallest possible answer to one question: "IF this factor's gross
decile-spread were real, would it survive conservative costs and turnover?" It
takes an ABSTRACT gross spread (and breadth) as input and returns net-of-cost
metrics. It is a pure evaluator with FIXED, DECLARED assumptions.

WHAT THIS IS NOT
----------------
Not a portfolio optimiser. Not a backtester. It has no parameter to tune, no
policy to search, no ML, no regime conditioning, and no selection logic. Every
assumption (top/bottom decile, equal weight, monthly rebalance, cost bps,
turnover) is a fixed constant declared here, not fitted to anything. There is no
`optimise`, `best_policy`, or `select` -- a test asserts their absence.

WHY IT NEVER TOUCHES A CANDIDATE'S DATA
---------------------------------------
Running this on H1/H3's real signal would require their forward returns, which
is validation-adjacent and would pre-empt the one paid look. So this consumes an
already-computed gross spread as a NUMBER. It is exercised on synthetic controls;
it is fed a real factor's spread only AFTER that factor is a VALIDATED_ALPHA.

The `portfolio` firewall contract forbids this module from importing screening,
discovery, registration, or the ledger -- verified by the firewall test.
"""

from __future__ import annotations

from dataclasses import dataclass


class ProjectionError(ValueError):
    """A monetisation projection input was malformed."""


# FIXED policy. Declared, never tuned. A quintile/weekly variant would be a
# DIFFERENT declared policy, not a search over this one.
POLICY = {
    "construction": "long_top_decile_short_bottom_decile",
    "weighting": "equal_weight",
    "rebalance": "monthly",
    "n_deciles": 10,
}

# FIXED, CONSERVATIVE cost assumptions. Declared before any use, never fitted.
# One-way cost per name per rebalance, in basis points. 20 bps is deliberately
# pessimistic for large-cap US equities (commission + half-spread + slippage).
DEFAULT_COST_BPS_ONE_WAY = 20.0
# Fraction of the long+short book turned over each monthly rebalance. A
# conservative default; a factor's realised turnover replaces it once known.
DEFAULT_MONTHLY_TURNOVER = 0.30


@dataclass(frozen=True)
class ProjectionResult:
    """Gross -> net, with every assumption recorded. No optimisation."""

    gross_spread_annualised: float
    cost_bps_one_way: float
    monthly_turnover: float
    annual_cost_drag: float
    net_spread_annualised: float
    degradation_fraction: float          # 1 - net/gross, when gross > 0
    breadth_median_names: int
    capacity_proxy: str                  # qualitative, breadth-driven
    policy: dict

    def as_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


def project(
    *,
    gross_spread_annualised: float,
    breadth_median_names: int,
    cost_bps_one_way: float = DEFAULT_COST_BPS_ONE_WAY,
    monthly_turnover: float = DEFAULT_MONTHLY_TURNOVER,
) -> ProjectionResult:
    """Net-of-cost projection under the FIXED policy. Pure function.

    `gross_spread_annualised` is an already-computed decile-spread annualised
    return (a NUMBER, not a signal). This function applies conservative,
    declared costs; it does not compute the spread, choose the policy, or search
    anything.
    """
    if breadth_median_names <= 0:
        raise ProjectionError("breadth must be positive")
    if not (0.0 <= monthly_turnover <= 2.0):
        raise ProjectionError("monthly_turnover out of plausible range")

    # 12 monthly rebalances; each turns over `monthly_turnover` of a two-sided
    # (long+short) book, and each turned-over name pays a round-trip (2x one-way).
    annual_cost_drag = (
        12 * monthly_turnover * 2.0 * (cost_bps_one_way / 1e4) * 2.0
    )
    net = gross_spread_annualised - annual_cost_drag
    degradation = (
        (gross_spread_annualised - net) / gross_spread_annualised
        if gross_spread_annualised > 0 else float("nan")
    )

    # Capacity is a QUALITATIVE proxy from breadth only -- no dollar figure is
    # claimed. More names => a top/bottom decile holds more distinct positions.
    if breadth_median_names >= 1000:
        cap = "wide (>=100 names per leg at decile width)"
    elif breadth_median_names >= 400:
        cap = "moderate (40-100 names per leg)"
    else:
        cap = "narrow (<40 names per leg) -- capacity-constrained"

    return ProjectionResult(
        gross_spread_annualised=float(gross_spread_annualised),
        cost_bps_one_way=float(cost_bps_one_way),
        monthly_turnover=float(monthly_turnover),
        annual_cost_drag=float(annual_cost_drag),
        net_spread_annualised=float(net),
        degradation_fraction=float(degradation),
        breadth_median_names=int(breadth_median_names),
        capacity_proxy=cap,
        policy=dict(POLICY),
    )
