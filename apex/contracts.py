"""Data contracts between pipeline stages.

Every frame that crosses a stage boundary is validated here, on construction.
Two invariants are enforced structurally rather than by convention, because they
are the two things that silently invalidate an equity cross-sectional study:

1. `security_id` is a stable surrogate key, NEVER a ticker. Tickers are recycled
   across companies; a ticker join reintroduces survivorship contamination
   through the back door.

2. Time-series features are computed on each security's own full history
   regardless of universe membership -- a stock's 200-day SMA does not care
   whether it was eligible 200 days ago -- while every cross-sectional
   operation (winsorise, z-score, sector and universe benchmarks, ranking) sees
   ONLY the eligible set at T. `Panel` therefore carries full history and
   `UniverseSnapshot` carries eligibility; nothing merges them implicitly.

Fail loudly. No silent coercion, no fillna, no default that papers over a gap.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

import numpy as np
import pandas as pd


class ContractViolation(ValueError):
    """A frame crossing a stage boundary did not satisfy its contract."""


# --------------------------------------------------------------------------
# validation helpers
# --------------------------------------------------------------------------


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractViolation(message)


def _require_columns(frame: pd.DataFrame, columns: Iterable[str], name: str) -> None:
    missing = [c for c in columns if c not in frame.columns]
    _require(not missing, f"{name}: missing required columns {missing}")


def _require_no_nan(frame: pd.DataFrame, columns: Iterable[str], name: str) -> None:
    for column in columns:
        n_nan = int(frame[column].isna().sum())
        _require(
            n_nan == 0,
            f"{name}: column '{column}' contains {n_nan} NaN values; "
            f"required columns may not be null (protocol section 9: no imputation)",
        )


def _require_aligned(
    frame: pd.DataFrame,
    dates: pd.DatetimeIndex,
    securities: pd.Index,
    name: str,
) -> None:
    _require(
        frame.index.equals(dates),
        f"{name}: index is not aligned to the panel trading calendar",
    )
    _require(
        frame.columns.equals(securities),
        f"{name}: columns are not aligned to the panel security_id axis",
    )


# --------------------------------------------------------------------------
# Contract 1 -- Panel (raw market data, full history)
# --------------------------------------------------------------------------

SECURITY_META_COLUMNS = (
    "security_id",
    "ticker",
    "exchange",
    "security_type",
    "sector",
    "first_date",
    "last_date",
    "delist_date",
    "delist_reason",
)


@dataclass(frozen=True)
class Panel:
    """Wide market-data panel: rows are trading dates, columns are security_id.

    Adjusted series are total-return adjusted (splits and dividends). Unadjusted
    series are as printed on the day.

    Which one to use is not a style choice -- it follows from CONVENTIONS section 4.4:

      * RATIO quantities (returns, SMA ratios, vol ratios, ATR/Close) are
        invariant to the vintage of the cumulative adjustment factor, because
        the factor cancels. These use the ADJUSTED series.

      * LEVEL quantities (the $5 close filter, the $1B market cap filter) are
        NOT invariant. Using a modern adjustment factor on a historical level
        test is lookahead. These use the UNADJUSTED as-of-date series.
    """

    dates: pd.DatetimeIndex
    securities: pd.Index

    close_adj: pd.DataFrame
    high_adj: pd.DataFrame
    low_adj: pd.DataFrame

    close_unadj: pd.DataFrame
    volume: pd.DataFrame
    shares_out: pd.DataFrame

    meta: pd.DataFrame
    benchmark_tr: pd.Series
    vol_index: pd.Series

    def __post_init__(self) -> None:
        _require(
            isinstance(self.dates, pd.DatetimeIndex),
            "Panel: dates must be a DatetimeIndex",
        )
        _require(self.dates.is_monotonic_increasing, "Panel: dates must be sorted")
        _require(self.dates.is_unique, "Panel: dates must be unique")
        _require(self.securities.is_unique, "Panel: security_id axis must be unique")

        for name in (
            "close_adj",
            "high_adj",
            "low_adj",
            "close_unadj",
            "volume",
            "shares_out",
        ):
            _require_aligned(getattr(self, name), self.dates, self.securities, f"Panel.{name}")

        _require_columns(self.meta, SECURITY_META_COLUMNS, "Panel.meta")
        _require(
            self.meta.index.equals(self.securities),
            "Panel.meta: index must be the security_id axis",
        )
        _require(
            self.meta["security_id"].is_unique,
            "Panel.meta: security_id must be unique (it is a surrogate key)",
        )
        _require(
            not self.meta["ticker"].equals(self.meta["security_id"]),
            "Panel.meta: security_id must not be the ticker -- tickers are "
            "recycled across companies and joining on them reintroduces "
            "survivorship contamination",
        )

        for name in ("benchmark_tr", "vol_index"):
            series = getattr(self, name)
            _require(
                series.index.equals(self.dates),
                f"Panel.{name}: index must be the panel trading calendar",
            )
            _require_no_nan(series.to_frame(name), [name], f"Panel.{name}")

        positive = self.close_adj.to_numpy()
        finite = np.isfinite(positive)
        _require(
            bool(np.all(positive[finite] > 0)),
            "Panel.close_adj: non-positive prices present",
        )

    @property
    def market_cap(self) -> pd.DataFrame:
        """As-of-date market cap: unadjusted close x shares outstanding.

        Unadjusted by construction -- see the class docstring. Using an adjusted
        close here would be a lookahead violation on a level quantity.
        """
        return self.close_unadj * self.shares_out

    @property
    def dollar_volume(self) -> pd.DataFrame:
        """Unadjusted dollar volume.

        Invariant to splits (price / r x volume * r), so no adjustment choice
        is needed, but it is computed from the unadjusted series for clarity.
        """
        return self.close_unadj * self.volume


# --------------------------------------------------------------------------
# Contract 2 -- UniverseSnapshot
# --------------------------------------------------------------------------

FILTER_NAMES = (
    "security_type",
    "exchange",
    "history",
    "bars_in_prior_252",
    "close",
    # PIT establishment is a SEPARATE filter from the size test (user ruling,
    # 2026-08-09). "We know it was a $400m company" and "we do not know what it
    # was worth" are different facts, and collapsing them hides how much of the
    # universe is lost to missing point-in-time data -- the number that says
    # whether the dual-vendor join is actually working.
    "pit_market_cap",
    "market_cap",
    "addv",
)


@dataclass(frozen=True)
class UniverseSnapshot:
    """Point-in-time eligibility, emitted for EVERY date, not only rebalances.

    `pass_flags` holds one wide boolean frame per filter, so protocol section 9's
    "count excluded by each filter" falls out of the same object that decides
    eligibility. A separate counting path could drift from the decision path;
    this one cannot.
    """

    dates: pd.DatetimeIndex
    securities: pd.Index
    eligible: pd.DataFrame
    pass_flags: dict[str, pd.DataFrame]
    exclusion_reason: pd.DataFrame
    tradable: pd.DataFrame

    def __post_init__(self) -> None:
        _require_aligned(self.eligible, self.dates, self.securities, "UniverseSnapshot.eligible")
        _require_aligned(self.tradable, self.dates, self.securities, "UniverseSnapshot.tradable")
        _require(
            self.eligible.dtypes.eq(bool).all(),
            "UniverseSnapshot.eligible: must be boolean",
        )
        missing = [f for f in FILTER_NAMES if f not in self.pass_flags]
        _require(not missing, f"UniverseSnapshot: missing pass_flags for {missing}")
        for name, frame in self.pass_flags.items():
            _require_aligned(
                frame, self.dates, self.securities, f"UniverseSnapshot.pass_flags[{name}]"
            )

    def counts(self) -> pd.DataFrame:
        """Protocol section 9 per-date log: eligible count and per-filter exclusions.

        Iterates every registered filter, including `missing_feature` once
        feature completeness has been folded in, so the log cannot silently omit
        a filter that was actually applied.
        """
        out = {"eligible": self.eligible.sum(axis=1)}
        for name in self.pass_flags:
            out[f"excluded_{name}"] = (~self.pass_flags[name] & self.tradable).sum(axis=1)
        out["tradable"] = self.tradable.sum(axis=1)
        return pd.DataFrame(out, index=self.dates)


# --------------------------------------------------------------------------
# Contract 3 -- FeaturePanel
# --------------------------------------------------------------------------

FEATURE_COMPONENTS = (
    "f1_mom_126",
    "f1_mom_63",
    "f2_close_over_sma200",
    "f2_frac_above_sma50",
    "f3_vol_ratio",
    "f3_atr_over_close",
    "f4_vs_sector",
    "f4_vs_market",
)

CATEGORY_COMPONENTS = {
    "f1": ("f1_mom_126", "f1_mom_63"),
    "f2": ("f2_close_over_sma200", "f2_frac_above_sma50"),
    "f3": ("f3_vol_ratio", "f3_atr_over_close"),
    "f4": ("f4_vs_sector", "f4_vs_market"),
}


@dataclass(frozen=True)
class FeaturePanel:
    """Raw (pre-winsorisation) feature values, one wide frame per component.

    `max_input_date` is the provenance frame the Stage 3 lookahead auditor
    checks: for each (date, security) it records the latest timestamp of any
    input that entered that row's feature computation. The audit is a mechanical
    comparison against T, not a code review.
    """

    dates: pd.DatetimeIndex
    securities: pd.Index
    components: dict[str, pd.DataFrame]
    max_input_date: pd.DataFrame

    def __post_init__(self) -> None:
        missing = [c for c in FEATURE_COMPONENTS if c not in self.components]
        _require(not missing, f"FeaturePanel: missing components {missing}")
        extra = [c for c in self.components if c not in FEATURE_COMPONENTS]
        _require(not extra, f"FeaturePanel: unexpected components {extra} (section 5: no additions)")
        for name, frame in self.components.items():
            _require_aligned(frame, self.dates, self.securities, f"FeaturePanel[{name}]")
        _require_aligned(
            self.max_input_date, self.dates, self.securities, "FeaturePanel.max_input_date"
        )

    def complete(self) -> pd.DataFrame:
        """True where every one of the eight components is present.

        Protocol section 9: a security missing a required input for ANY of the four
        features is excluded at that formation date only, and stays eligible
        later. There is no partial-category averaging.
        """
        mask = pd.DataFrame(True, index=self.dates, columns=self.securities)
        for frame in self.components.values():
            mask &= frame.notna()
        return mask


# --------------------------------------------------------------------------
# Contract 4 -- ScorePanel
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ScorePanel:
    dates: pd.DatetimeIndex
    securities: pd.Index
    category_scores: dict[str, pd.DataFrame]
    apex_score: pd.DataFrame
    decile: pd.DataFrame
    # WHICH LABEL IS THE LONG LEG. Carried by the panel because the SCORER
    # assigns the labels, so only the scorer knows which end is best.
    # Previously the decile evaluator assumed APEX-001's 10-is-best, which
    # sign-inverted every decile figure in APEX-002's recorded validation
    # artifact (APEX-002-ERRATUM-001). Putting it in configuration was tried
    # and rejected: that is a second source of truth, and the null rig -- which
    # scores with #001's composite -- immediately disagreed with it.
    top_decile_label: int = 0

    def __post_init__(self) -> None:
        for name, frame in self.category_scores.items():
            _require_aligned(frame, self.dates, self.securities, f"ScorePanel.category[{name}]")
        _require_aligned(self.apex_score, self.dates, self.securities, "ScorePanel.apex_score")
        _require_aligned(self.decile, self.dates, self.securities, "ScorePanel.decile")

        # The panel can only check the convention was STATED. Which end is
        # valid depends on n_deciles, which the panel does not carry, and a
        # sparse cross-section legitimately leaves some labels unpopulated --
        # 5 eligible names over 10 buckets yields {2,4,6,8,10} and no decile 1.
        # `evaluate_deciles` makes the strict 1-or-n check, where n is known.
        _require(
            int(self.top_decile_label) >= 1,
            f"ScorePanel.top_decile_label={self.top_decile_label} is unset. The "
            f"scorer assigns the labels, so it must state which end is the long "
            f"leg; there is no default.",
        )

        scored = self.apex_score.to_numpy()
        present = np.isfinite(scored)
        if present.any():
            _require(
                bool(scored[present].min() >= 0.0 and scored[present].max() <= 100.0),
                "ScorePanel.apex_score: values outside the 0-100 percentile range",
            )


# --------------------------------------------------------------------------
# Contract 5 -- ForwardReturns
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ForwardReturns:
    """Forward returns measured close T+1 -> close T+21 (protocol section 4).

    Indexed by SIGNAL date T, not by formation date T+1, so it joins directly
    against the score panel without an off-by-one.
    """

    dates: pd.DatetimeIndex
    securities: pd.Index
    raw: pd.DataFrame
    excess: pd.DataFrame
    exit_reason: pd.DataFrame

    def __post_init__(self) -> None:
        _require_aligned(self.raw, self.dates, self.securities, "ForwardReturns.raw")
        _require_aligned(self.excess, self.dates, self.securities, "ForwardReturns.excess")
        _require_aligned(
            self.exit_reason, self.dates, self.securities, "ForwardReturns.exit_reason"
        )
        finite = np.isfinite(self.raw.to_numpy())
        values = self.raw.to_numpy()[finite]
        if values.size:
            _require(
                bool(values.min() >= -1.0),
                "ForwardReturns.raw: a return below -100% is impossible for a "
                "long position and indicates a price or corporate-action bug",
            )


# --------------------------------------------------------------------------
# Contract 6 -- RunResult
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class RunResult:
    experiment_id: str
    period: str
    config_hash: str
    protocol_hash: str
    conventions_hash: str
    git_sha: str
    data_hash: str
    metrics: dict
    per_date_log: pd.DataFrame
    provenance: dict = field(default_factory=dict)

    def header(self) -> dict:
        return {
            "experiment_id": self.experiment_id,
            "period": self.period,
            "config_hash": self.config_hash,
            "protocol_hash": self.protocol_hash,
            "conventions_hash": self.conventions_hash,
            "git_sha": self.git_sha,
            "data_hash": self.data_hash,
        }
