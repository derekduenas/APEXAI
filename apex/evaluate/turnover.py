"""Stage 6 -- realised turnover and net returns. Protocol section 8, ruling C8.

    "Costs = 10 bps per side applied to REALISED one-way turnover, on BOTH legs
     of the spread."

This closes the standing GROSS-ONLY gap. `deciles.py` has always refused to
report a net figure on the grounds that "a net figure computed without realised
turnover is an invented number"; turnover here is derived from the actual
holdings path, so the net number finally has something real underneath it.

WHY DRIFT IS THE WHOLE PROBLEM

Section 9 forbids intra-period trading, so between rebalances the book drifts
with returns. A name that doubled is a larger share of the portfolio and must be
SOLD at the next rebalance even though it is still in the top decile. Measuring
turnover as "how much of the membership changed" ignores that and understates
cost. Turnover is measured against the DRIFTED book, not against the previous
target.

WHAT IS DELIBERATELY ABSENT

No function here accepts a turnover figure. There is no `assumed_turnover`
parameter, and a test asserts there never will be -- the one way to get a net
number is to have actually simulated the holdings.

WHAT THIS STILL DOES NOT MODEL, and must be disclosed with any net figure:
  * market impact as a function of order size versus ADV
  * partial fills, and the liquidity constraint on a large book
  * borrow cost and availability for the short leg
  * the short leg's implementability at all (section 9: "the bottom decile is
    computed for the spread but never traded")
  * taxes (section 8 keeps pre-tax primary)

The cost model is the pre-registered section 8 one: a flat per-side charge. It
is not a microstructure simulation and must not be described as one.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


def drift_weights(weights: pd.Series, returns: pd.Series) -> pd.Series:
    """Weights after one holding period of untraded drift.

    A name returning -100% leaves the book entirely; the rest re-normalise.
    """
    grown = weights * (1.0 + returns.reindex(weights.index).fillna(0.0))
    total = grown.sum()
    if total <= 0:
        return grown * 0.0
    return grown / total


def one_way_turnover(held: pd.Series, target: pd.Series) -> float:
    """Fraction of the book that changes hands in one direction.

    sum|dw| counts buys AND sells; one-way turnover is half of it.
    """
    axis = held.index.union(target.index)
    delta = target.reindex(axis).fillna(0.0) - held.reindex(axis).fillna(0.0)
    return float(delta.abs().sum() / 2.0)


def leg_costs(held: pd.Series, target: pd.Series, bps_per_side: float) -> float:
    """Cost of moving one leg from `held` to `target`, as a fraction of the leg.

    Every unit traded pays the per-side charge, in both directions, so the cost
    is bps x sum|dw| -- equivalently 2 x bps x one-way turnover.
    """
    return float(bps_per_side / 1e4) * 2.0 * one_way_turnover(held, target)


def annualise_turnover(per_period: float, periods_per_year: float) -> float:
    """C9: 12.6 rebalances per year."""
    return float(per_period) * float(periods_per_year)


@dataclass(frozen=True)
class NetResult:
    """Gross and net, with the realised turnover that produced the difference."""

    gross_spread_per_period: float
    net_spread_per_period: float
    cost_per_period: float
    long_cost_per_period: float
    short_cost_per_period: float
    long_turnover_per_period: float
    short_turnover_per_period: float
    annualised_turnover: float
    bps_per_side: float
    n_periods: int

    def as_dict(self) -> dict:
        return {
            "gross_spread_per_period": self.gross_spread_per_period,
            "net_spread_per_period": self.net_spread_per_period,
            "cost_per_period": self.cost_per_period,
            "long_cost_per_period": self.long_cost_per_period,
            "short_cost_per_period": self.short_cost_per_period,
            "long_turnover_per_period": self.long_turnover_per_period,
            "short_turnover_per_period": self.short_turnover_per_period,
            "annualised_turnover": self.annualised_turnover,
            "bps_per_side": self.bps_per_side,
            "n_periods": self.n_periods,
            "basis": (
                "costs charged on REALISED one-way turnover derived from the "
                "simulated holdings path, on both legs (C8). No turnover was "
                "assumed."
            ),
            "not_modelled": [
                "market impact vs order size / ADV",
                "partial fills and capacity",
                "short borrow cost and availability",
                "whether the short leg is implementable at all",
                "taxes (section 8 keeps pre-tax primary)",
            ],
        }


def _equal_weights(mask_row: pd.Series) -> pd.Series:
    members = mask_row[mask_row.fillna(False)].index
    if len(members) == 0:
        return pd.Series(dtype="float64")
    return pd.Series(1.0 / len(members), index=members)


def net_decile_result(
    top: pd.DataFrame,
    bottom: pd.DataFrame,
    period_returns: pd.DataFrame,
    bps_per_side: float,
    periods_per_year: float,
) -> NetResult:
    """Simulate both legs across the rebalance grid and net the costs off.

    `top` / `bottom` are boolean membership at each REBALANCE date.
    `period_returns` are the holding-period returns realised from that date.
    """
    dates = top.index
    held = {"long": pd.Series(dtype="float64"), "short": pd.Series(dtype="float64")}
    costs = {"long": [], "short": []}
    turnovers = {"long": [], "short": []}
    gross: list = []

    for date in dates:
        row_returns = period_returns.loc[date]
        legs = {"long": _equal_weights(top.loc[date]), "short": _equal_weights(bottom.loc[date])}

        leg_gross = {}
        for side, target in legs.items():
            # Trade from the drifted book into this period's target.
            cost = leg_costs(held[side], target, bps_per_side)
            costs[side].append(cost)
            turnovers[side].append(one_way_turnover(held[side], target))

            realised = float((target * row_returns.reindex(target.index).fillna(0.0)).sum())
            leg_gross[side] = realised
            held[side] = drift_weights(target, row_returns)

        gross.append(leg_gross["long"] - leg_gross["short"])

    mean_gross = float(np.mean(gross)) if gross else float("nan")
    long_cost = float(np.mean(costs["long"])) if costs["long"] else 0.0
    short_cost = float(np.mean(costs["short"])) if costs["short"] else 0.0
    long_turnover = float(np.mean(turnovers["long"])) if turnovers["long"] else 0.0
    short_turnover = float(np.mean(turnovers["short"])) if turnovers["short"] else 0.0

    return NetResult(
        gross_spread_per_period=mean_gross,
        net_spread_per_period=mean_gross - (long_cost + short_cost),
        cost_per_period=long_cost + short_cost,
        long_cost_per_period=long_cost,
        short_cost_per_period=short_cost,
        long_turnover_per_period=long_turnover,
        short_turnover_per_period=short_turnover,
        annualised_turnover=annualise_turnover(long_turnover, periods_per_year),
        bps_per_side=float(bps_per_side),
        n_periods=len(dates),
    )
