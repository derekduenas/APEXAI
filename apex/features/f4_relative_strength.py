"""F4 -- Relative Strength (protocol section 5).

  * 63-day return minus the equal-weighted 63-day return of the security's sector
  * 63-day return minus the 63-day return of the S&P 500

Conventions applied:
  B3 -- F4 uses the SAME 5-trading-day skip as F1.
  C2 -- the sector benchmark EXCLUDES the security itself and requires at least
        10 eligible names in the sector; otherwise the security is excluded at
        that date (section 9 missing-input rule).
  C3 -- sector taxonomy is the vendor's own field. Not point-in-time; section 4
        accepts this as minor contamination and requires it be disclosed.
  C4 -- the market benchmark is S&P 500 TOTAL return, matching the total-return
        basis of the security's own leg.

-----------------------------------------------------------------------------
FINDING, reported not fixed -- see the fuller note in `f1_momentum.py`
-----------------------------------------------------------------------------
`f4_vs_market` subtracts a single cross-sectional constant per date. Winsorising
and z-scoring are both equivariant under a constant shift, so after step 2 of
section 5 this component is EXACTLY IDENTICAL to `f1_mom_63`, not merely
correlated with it.

Consequence for the effective weighting, which section 5 does not intend but does
imply: the 63-day skip-5 momentum z-score enters the composite twice, once via
F1 and once via F4, for a total weight of 0.25, while the genuinely distinct
sector-relative signal carries 0.125. Implemented as specified.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from apex.config import Config
from apex.contracts import Panel
from apex.features.f1_momentum import skip_adjusted_return


def sector_relative(
    values: pd.DataFrame,
    eligible: pd.DataFrame,
    sectors: pd.Series,
    min_names: int,
    exclude_self: bool,
) -> pd.DataFrame:
    """Return minus the equal-weighted return of the security's own sector.

    The leave-one-out mean is computed in closed form rather than by looping
    securities: with the sector total S and count n, excluding security i gives
    (S - x_i) / (n - 1). Including the security in its own benchmark would pull
    every value toward zero, and hardest in the smallest sectors.

    The benchmark is built from ELIGIBLE members only, but the feature is
    returned for every member. Eligibility is a separate gate applied later; if
    this function masked its own output to the eligible set, every ineligible
    security would register as "missing a required input" and section 9's
    missing-data count would be dominated by securities that were never
    candidates.

    Leave-one-out therefore subtracts a security's own value only when that
    security is itself in the benchmark. For an ineligible security the
    benchmark is the plain eligible-member mean, with nothing to leave out.
    """
    out = pd.DataFrame(np.nan, index=values.index, columns=values.columns)

    for _sector, members in sectors.groupby(sectors).groups.items():
        members = pd.Index(members)
        block = values[members]
        in_benchmark = eligible[members] & block.notna()
        contributing = block.where(in_benchmark)

        count = contributing.count(axis=1)
        total = contributing.sum(axis=1, min_count=1)

        if exclude_self:
            own_value = contributing.fillna(0.0)
            own_count = in_benchmark.astype("float64")
            denominator = own_count.rsub(count, axis=0)
            numerator = own_value.rsub(total, axis=0)
            benchmark = numerator.div(denominator.where(denominator > 0))
        else:
            benchmark = pd.DataFrame(
                np.repeat(
                    (total / count.where(count > 0)).to_numpy()[:, None], len(members), axis=1
                ),
                index=values.index,
                columns=members,
            )

        relative = block - benchmark
        out.loc[:, members] = relative.where(count >= min_names, axis=0)

    return out


def market_relative(values: pd.DataFrame, benchmark_return: pd.Series) -> pd.DataFrame:
    return values.sub(benchmark_return, axis=0)


def compute(panel: Panel, eligible: pd.DataFrame, config: Config) -> dict[str, pd.DataFrame]:
    window = int(config.get("features.f4.window"))
    skip = int(config.get("features.f4.skip_days"))
    min_names = int(config.get("features.f4.min_sector_names"))
    exclude_self = bool(config.get("features.f4.exclude_self"))

    raw = skip_adjusted_return(panel.close_adj, window, skip)

    benchmark = panel.benchmark_tr.shift(skip)
    benchmark_return = benchmark / benchmark.shift(window) - 1.0

    return {
        "f4_vs_sector": sector_relative(
            raw, eligible, panel.meta["sector"], min_names, exclude_self
        ),
        "f4_vs_market": market_relative(raw, benchmark_return),
    }
