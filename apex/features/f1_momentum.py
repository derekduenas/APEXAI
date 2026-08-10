"""F1 -- Momentum (protocol section 5).

  * 126-day total return, excluding the most recent 5 trading days
  * 63-day total return, excluding the most recent 5 trading days
  * Both expressed as excess over the equal-weighted universe return for the
    same window (C1: the cross-sectional MEAN over the eligible universe at T)

Computed on the ADJUSTED (total-return) series: these are ratios, so the
vintage of the cumulative adjustment factor cancels (CONVENTIONS section 4.4).

-----------------------------------------------------------------------------
FINDING, reported not fixed
-----------------------------------------------------------------------------
The universe-excess step is INERT. It subtracts one cross-sectional constant
from every security on a given date, and both downstream operations are
equivariant under a constant shift:

    winsorise(x - c) = winsorise(x) - c        (percentiles shift by c)
    zscore(x - c)    = zscore(x)               (mean shifts by c, sd unchanged)

So F1's z-scores -- and therefore the APEX Score -- are numerically identical
whether or not the benchmark is subtracted. The same argument applies to F4b
(minus the S&P 500), which is also a single cross-sectional constant.

The protocol's own section 2 technical note makes exactly this argument for the
RETURN side ("subtracting a constant does not change the rank ordering"). It
was not carried over to the feature side, where it has a sharper consequence:
after z-scoring, F4b is not merely a near-duplicate of F1b (as CONVENTIONS B3
records) but is EXACTLY IDENTICAL to it -- both reduce to the z-score of the
same 63-day skip-5 adjusted return.

The subtraction is implemented anyway, faithfully to section 5, and
`test_features_f1.py::test_universe_excess_is_inert_after_zscoring` asserts the
invariance mechanically so this stays a documented property rather than
becoming a suspected bug later.
"""

from __future__ import annotations

import pandas as pd

from apex.config import Config
from apex.contracts import Panel


def skip_adjusted_return(close_adj: pd.DataFrame, window: int, skip: int) -> pd.DataFrame:
    """Total return over `window` trading days ending `skip` days before T.

    Uses the two endpoint prices only. A missing bar strictly between the
    endpoints does not make the return uncomputable, so section 9's exclusion
    rule fires on genuinely absent inputs rather than on any gap in the window.
    """
    end = close_adj.shift(skip)
    start = end.shift(window)
    return end / start - 1.0


def universe_mean(values: pd.DataFrame, eligible: pd.DataFrame) -> pd.Series:
    """C1: cross-sectional mean over the eligible universe as constituted at T."""
    return values.where(eligible).mean(axis=1)


def compute(panel: Panel, eligible: pd.DataFrame, config: Config) -> dict[str, pd.DataFrame]:
    windows = config.get("features.f1.windows")
    skip = int(config.get("features.f1.skip_days"))

    long_window, short_window = int(windows[0]), int(windows[1])
    out: dict[str, pd.DataFrame] = {}

    for name, window in (("f1_mom_126", long_window), ("f1_mom_63", short_window)):
        raw = skip_adjusted_return(panel.close_adj, window, skip)
        benchmark = universe_mean(raw, eligible)
        out[name] = raw.sub(benchmark, axis=0)

    return out
