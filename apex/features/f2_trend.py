"""F2 -- Trend Strength (protocol section 5).

  * (Close / 200-day SMA) - 1
  * Fraction of the prior 63 trading days on which Close > 50-day SMA

Both on the ADJUSTED series (ratios; adjustment vintage cancels). Both moving
averages require a COMPLETE window: unlike F1's two-endpoint returns, an SMA
genuinely needs every bar in its window, so a gap makes it uncomputable and the
security is excluded at that date under section 9.

The above/below comparison preserves NaN deliberately. `close > sma` evaluates
to False when either side is NaN, which would silently record a halted day as
"below the 50-day SMA" and bias the fraction downward for exactly the securities
with the messiest data. The comparison is masked back to NaN first.
"""

from __future__ import annotations

import pandas as pd

from apex.config import Config
from apex.contracts import Panel


def simple_moving_average(close_adj: pd.DataFrame, window: int) -> pd.DataFrame:
    return close_adj.rolling(window, min_periods=window).mean()


def compute(panel: Panel, eligible: pd.DataFrame, config: Config) -> dict[str, pd.DataFrame]:
    long_window = int(config.get("features.f2.sma_long"))
    short_window = int(config.get("features.f2.sma_short"))
    lookback = int(config.get("features.f2.lookback_days"))

    close = panel.close_adj

    sma_long = simple_moving_average(close, long_window)
    close_over_sma = close / sma_long - 1.0

    sma_short = simple_moving_average(close, short_window)
    above = (close > sma_short).where(close.notna() & sma_short.notna())
    fraction_above = above.rolling(lookback, min_periods=lookback).mean()

    return {
        "f2_close_over_sma200": close_over_sma,
        "f2_frac_above_sma50": fraction_above,
    }
