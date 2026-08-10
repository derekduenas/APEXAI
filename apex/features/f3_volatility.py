"""F3 -- Volatility Structure (protocol section 5).

  * Ratio of 20-day realised volatility to 100-day realised volatility
  * ATR(14) / Close

SIGN CONVENTION (protocol section 5 requires this be fixed in advance and stated in
code comments; CONVENTIONS B1 fixes it):

    BOTH components are NEGATED at the composite stage.

    Compression -- a LOW 20d/100d ratio -- is hypothesised favourable, and a LOW
    ATR/Close is likewise hypothesised favourable. F3 is therefore a
    low-volatility category. Leaving ATR un-negated would set the two components
    partially against each other and contribute noise.

The negation itself lives in `composite.py`, driven by
`composite.negate_components` in config, so the sign is a declared parameter
rather than a buried minus sign. This module returns the raw quantities as
section 5 defines them.

Conventions: realised volatility is the standard deviation of daily LOG returns
with ddof=1, not annualised (C5) -- annualisation cancels in the ratio. ATR uses
Wilder's smoothing (C6).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from apex.config import Config
from apex.contracts import Panel


def realised_volatility(close_adj: pd.DataFrame, window: int, ddof: int) -> pd.DataFrame:
    log_returns = np.log(close_adj).diff()
    return log_returns.rolling(window, min_periods=window).std(ddof=ddof)


def true_range(
    high: pd.DataFrame, low: pd.DataFrame, close: pd.DataFrame
) -> pd.DataFrame:
    previous_close = close.shift(1)
    return pd.concat(
        [
            (high - low).stack(future_stack=True),
            (high - previous_close).abs().stack(future_stack=True),
            (low - previous_close).abs().stack(future_stack=True),
        ],
        axis=1,
    ).max(axis=1).unstack()


def wilder_atr(tr: pd.DataFrame, period: int) -> pd.DataFrame:
    """Wilder's ATR, exactly as originally defined.

        ATR[period-1] = mean(TR[0 : period])
        ATR[t]        = (ATR[t-1] * (period - 1) + TR[t]) / period

    Written as an explicit recursion rather than an EWM so it is hand-checkable
    in a unit test. `ewm(alpha=1/period)` seeds from the first observation
    instead of the first SMA and is therefore a different series early on.

    A missing bar yields NaN for that date -- the security is excluded there
    under section 9 -- but the recursion STATE carries across the gap rather than
    being poisoned by it, so the series resumes correctly afterwards.
    """
    values = tr.to_numpy(dtype="float64")
    n_days, n_sec = values.shape
    out = np.full((n_days, n_sec), np.nan)

    state = np.full(n_sec, np.nan)
    seen = np.zeros(n_sec, dtype=int)
    seed_sum = np.zeros(n_sec)

    for t in range(n_days):
        row = values[t]
        valid = np.isfinite(row)

        seeding = valid & (seen < period)
        seed_sum[seeding] += row[seeding]
        seen[seeding] += 1
        just_seeded = seeding & (seen == period)
        state[just_seeded] = seed_sum[just_seeded] / period

        updating = valid & (seen >= period) & ~just_seeded & np.isfinite(state)
        state[updating] = (state[updating] * (period - 1) + row[updating]) / period

        out[t] = np.where(valid, state, np.nan)

    return pd.DataFrame(out, index=tr.index, columns=tr.columns)


def compute(panel: Panel, eligible: pd.DataFrame, config: Config) -> dict[str, pd.DataFrame]:
    short_window = int(config.get("features.f3.vol_short"))
    long_window = int(config.get("features.f3.vol_long"))
    period = int(config.get("features.f3.atr_period"))
    ddof = int(config.get("features.f3.ddof"))

    vol_short = realised_volatility(panel.close_adj, short_window, ddof)
    vol_long = realised_volatility(panel.close_adj, long_window, ddof)
    vol_ratio = vol_short / vol_long.where(vol_long > 0)

    tr = true_range(panel.high_adj, panel.low_adj, panel.close_adj)
    atr = wilder_atr(tr, period)
    atr_over_close = atr / panel.close_adj

    return {
        "f3_vol_ratio": vol_ratio,
        "f3_atr_over_close": atr_over_close,
    }
