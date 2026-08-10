"""Decile returns and the top-minus-bottom spread.

SCOPE: this module computes GROSS decile returns on the non-overlapping
20-trading-day grid, which is what Stage 2's null rig needs in order to assert
the spread is indistinguishable from zero.

The cost and turnover simulation of protocol section 8 and the section 9 portfolio rule
(hold the top decile, close names that leave the universe at their last valid
price, hold proceeds in cash to the rebalance) is STAGE 6 and is deliberately
not implemented here. Reporting a net figure before that machinery exists would
mean inventing a turnover number, and the cost hurdle is too close to the pass
threshold for an invented number to be harmless.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from apex.config import Config
from apex.evaluate.ic import simple_tstat


@dataclass(frozen=True)
class DecileResult:
    per_period: pd.DataFrame
    spread: pd.Series
    mean_by_decile: pd.Series
    spread_mean_per_period: float
    spread_annualised_gross: float
    spread_t_stat: float
    hit_rate: float
    monotonic_top_over_bottom: bool
    n_periods: int

    def as_dict(self) -> dict:
        return {
            "spread_mean_per_period": self.spread_mean_per_period,
            "spread_annualised_gross": self.spread_annualised_gross,
            "spread_t_stat": self.spread_t_stat,
            "hit_rate": self.hit_rate,
            "monotonic_top_over_bottom": self.monotonic_top_over_bottom,
            "n_periods": self.n_periods,
            "mean_by_decile": {int(k): float(v) for k, v in self.mean_by_decile.items()},
        }


def annualise(per_period_return: float, periods_per_year: float, method: str) -> float:
    if not np.isfinite(per_period_return):
        return float("nan")
    if method == "geometric":
        base = 1.0 + per_period_return
        if base <= 0:
            return float("nan")
        return float(base**periods_per_year - 1.0)
    if method == "arithmetic":
        return float(per_period_return * periods_per_year)
    raise ValueError(f"unknown annualisation method '{method}'")


def decile_returns(
    decile: pd.DataFrame,
    returns: pd.DataFrame,
    eligible: pd.DataFrame,
    dates: pd.DatetimeIndex,
    n_deciles: int,
) -> pd.DataFrame:
    """Equal-weighted mean forward return per decile, per formation date."""
    mask = eligible.loc[dates] & decile.loc[dates].notna() & returns.loc[dates].notna()
    bucket = decile.loc[dates].where(mask)
    values = returns.loc[dates].where(mask)

    out = {}
    for d in range(1, n_deciles + 1):
        selected = values.where(bucket == d)
        out[d] = selected.mean(axis=1)
    return pd.DataFrame(out, index=dates)


def evaluate_deciles(
    decile: pd.DataFrame,
    returns: pd.DataFrame,
    eligible: pd.DataFrame,
    config: Config,
    dates: pd.DatetimeIndex,
) -> DecileResult:
    n_deciles = int(config.get("evaluation.n_deciles"))
    periods_per_year = float(config.get("evaluation.periods_per_year"))
    method = config.get("evaluation.annualization")

    per_period = decile_returns(decile, returns, eligible, dates, n_deciles)
    spread = per_period[n_deciles] - per_period[1]
    clean = spread.dropna()

    mean_by_decile = per_period.mean()
    top = mean_by_decile.loc[n_deciles - 2 : n_deciles].mean()
    bottom = mean_by_decile.loc[1:3].mean()

    spread_mean = float(clean.mean()) if len(clean) else float("nan")
    spread_t, _ = simple_tstat(spread)

    return DecileResult(
        per_period=per_period,
        spread=spread,
        mean_by_decile=mean_by_decile,
        spread_mean_per_period=spread_mean,
        spread_annualised_gross=annualise(spread_mean, periods_per_year, method),
        spread_t_stat=spread_t,
        hit_rate=float((clean > 0).mean()) if len(clean) else float("nan"),
        monotonic_top_over_bottom=bool(top > bottom),
        n_periods=int(len(clean)),
    )
