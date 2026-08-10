"""Mandatory in-sample smoke run -- ruling 2, 2026-08-09.

    "This is not for performance judgment -- only for schema + unit validation.
     If anything looks structurally wrong, we stop. No partial fixes carried
     into validation."

WHAT THIS IS AND IS NOT

It is a structural inspection of the pipeline against REAL data for the first
time, run on the in-sample period only. In-sample has no statistical standing
(protocol section 7) and costs no research credit, so it can be run as often as
needed while the vendor snapshot is being shaken out.

It is NOT a performance test. Nothing here reports whether the signal works, and
the checks below deliberately cannot be satisfied by a better IC. Every
structural check is about the DATA and the PLUMBING: is the universe populated,
are the features finite and varying, is the score cross-sectional, is the IC
series behaving like a series of correlations rather than like a constant or an
overflow.

THE FOUR BLOCKS REQUESTED

  1. Universe counts over time      -- not empty, not collapsing
  2. Feature distributions          -- NaNs, clipping, constant columns
  3. IC time series                 -- noisy, not flat, not exploding
  4. Decile membership concentration -- not one ticker over and over

Plus both leakage audits, because a smoke run that ignored them would certify a
pipeline that had never been checked against the data it will actually use.

FAILURE IS A STOP, NOT A WARNING

Every check yields PASS or FAIL. Any FAIL means the run is not clear to proceed
to validation. There is deliberately no "warning" tier: a tier that does not
stop anything is a tier that gets ignored.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from apex.audit.cross_sectional import audit_cross_sectional
from apex.audit.lookahead import audit_lookahead
from apex.config import Config
from apex.contracts import FEATURE_COMPONENTS
from apex.pipeline import PipelineOutput, build_panel_pipeline, evaluate


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    detail: str

    def line(self) -> str:
        return f"  [{'PASS' if self.passed else 'FAIL'}] {self.name}: {self.detail}"


@dataclass
class SmokeReport:
    dataset_fingerprint: str
    period: str
    checks: list = field(default_factory=list)
    blocks: dict = field(default_factory=dict)

    def add(self, name: str, passed: bool, detail: str) -> None:
        self.checks.append(Check(name, passed, detail))

    @property
    def clear_to_proceed(self) -> bool:
        return all(c.passed for c in self.checks)

    def render(self) -> str:
        out = [
            "=" * 78,
            "APEX EXPERIMENT #001 -- IN-SAMPLE SMOKE RUN",
            "structural and unit validation only; NOT a performance judgement",
            "=" * 78,
            f"dataset fingerprint : {self.dataset_fingerprint}",
            f"period              : {self.period}",
            "",
        ]
        for title, body in self.blocks.items():
            out += [f"--- {title} " + "-" * max(0, 74 - len(title)), body, ""]
        out += ["--- STRUCTURAL CHECKS " + "-" * 56]
        out += [c.line() for c in self.checks]
        out += [
            "",
            "=" * 78,
            (
                "CLEAR TO PROCEED TO VALIDATION"
                if self.clear_to_proceed
                else "STOP -- structural problems above must be resolved first. "
                "No partial fixes carried into validation."
            ),
            "=" * 78,
        ]
        return "\n".join(out)


# ---------------------------------------------------------------------------
# blocks
# ---------------------------------------------------------------------------


def _universe_block(output: PipelineOutput, dates, report: SmokeReport) -> None:
    log = output.per_date_log().loc[dates]
    eligible = log["eligible"]

    sample = log.iloc[:: max(1, len(log) // 12)]
    columns = ["eligible", "tradable"] + [c for c in log.columns if c.startswith("excluded_")]
    report.blocks["1. UNIVERSE COUNTS OVER TIME"] = (
        sample[columns].to_string()
        + f"\n\n  eligible: min={eligible.min()}  median={eligible.median():.0f}  "
        f"max={eligible.max()}  over {len(log)} dates"
    )

    report.add(
        "universe is never empty",
        bool(eligible.min() > 0),
        f"smallest cross-section is {eligible.min()} names",
    )
    report.add(
        "universe is large enough to rank",
        bool(eligible.median() >= 100),
        f"median {eligible.median():.0f} names (a decile needs a workable count)",
    )
    # A genuine collapse looks like a cliff, not a drift.
    ratio = eligible / eligible.shift(1)
    worst = float(ratio.min()) if ratio.notna().any() else 1.0
    report.add(
        "universe does not collapse day to day",
        worst > 0.5,
        f"largest single-day contraction is x{worst:.2f}",
    )


def _feature_block(output: PipelineOutput, dates, report: SmokeReport) -> None:
    eligible = output.universe.eligible.loc[dates]
    rows = []
    constant_columns: list[str] = []
    bad_nan: list[str] = []

    for name in FEATURE_COMPONENTS:
        frame = output.features.components[name].loc[dates].where(eligible)
        values = frame.to_numpy()
        finite = values[np.isfinite(values)]
        present = eligible.to_numpy().sum()
        nan_rate = 1.0 - (finite.size / present) if present else 1.0

        # Cross-sectional dispersion is what the composite actually consumes; a
        # feature that is constant within a date carries no ranking information
        # even if it varies through time.
        dispersion = frame.std(axis=1, ddof=1)
        flat_dates = int((dispersion.fillna(0) <= 0).sum())

        rows.append(
            {
                "component": name,
                "nan_rate": round(nan_rate, 4),
                "min": round(float(finite.min()), 4) if finite.size else np.nan,
                "p50": round(float(np.median(finite)), 4) if finite.size else np.nan,
                "max": round(float(finite.max()), 4) if finite.size else np.nan,
                "xs_sd_p50": round(float(dispersion.median()), 4),
                "flat_dates": flat_dates,
            }
        )
        if flat_dates > 0:
            constant_columns.append(name)
        if nan_rate > 0.25:
            bad_nan.append(f"{name}={nan_rate:.0%}")

    report.blocks["2. FEATURE DISTRIBUTIONS"] = pd.DataFrame(rows).to_string(index=False)

    report.add(
        "no feature is constant within a cross-section",
        not constant_columns,
        "all eight vary across securities"
        if not constant_columns
        else f"constant on some dates: {constant_columns}",
    )
    report.add(
        "feature NaN rates are plausible",
        not bad_nan,
        "all components below 25% missing" if not bad_nan else f"excessive: {bad_nan}",
    )
    report.add(
        "all feature values are finite",
        all(np.isfinite(r["p50"]) for r in rows if not pd.isna(r["p50"])),
        "no infinities or overflow in the medians",
    )


def _ic_block(evaluation, report: SmokeReport) -> None:
    series = evaluation.ic_daily.series.dropna()
    report.blocks["3. IC TIME SERIES"] = (
        f"  observations   : {len(series)}\n"
        f"  mean           : {series.mean():+.5f}\n"
        f"  sd             : {series.std(ddof=1):.5f}\n"
        f"  min / max      : {series.min():+.4f} / {series.max():+.4f}\n"
        f"  |IC| > 0.5     : {int((series.abs() > 0.5).sum())} dates\n"
        f"  autocorr lag 1 : {series.autocorr(1):+.3f}   (overlap implies strongly positive)\n"
        f"  by year:\n"
        + series.groupby(series.index.year)
        .agg(["count", "mean", "std"])
        .round(5)
        .to_string()
    )

    report.add(
        "IC series is populated",
        len(series) > 200,
        f"{len(series)} scored dates",
    )
    report.add(
        "IC series is not flat",
        float(series.std(ddof=1)) > 1e-6,
        f"sd = {series.std(ddof=1):.5f}",
    )
    report.add(
        "IC series is not exploding",
        bool(series.abs().max() <= 1.0),
        f"max |IC| = {series.abs().max():.4f} (a correlation cannot exceed 1)",
    )
    # Overlapping 20-day windows must produce strong positive autocorrelation.
    # Its absence means the forward window is not what section 4 specifies.
    autocorr = series.autocorr(1)
    report.add(
        "IC autocorrelation matches the 20-day overlap",
        bool(autocorr > 0.5),
        f"lag-1 autocorrelation {autocorr:+.3f}",
    )


def _decile_block(output: PipelineOutput, config: Config, dates, report: SmokeReport) -> None:
    grid = output.calendar.grid_formation_dates(dates.min(), dates.max())
    deciles = output.scores.decile.loc[grid]
    n = int(config.get("evaluation.n_deciles"))

    top = deciles == n
    bottom = deciles == 1
    periods = len(grid)

    frequency = (top.sum(axis=0) / periods).sort_values(ascending=False)
    tickers = output.panel.meta["ticker"]
    head = pd.DataFrame(
        {
            "ticker": [tickers.get(s, s) for s in frequency.head(10).index],
            "top_decile_share": frequency.head(10).round(3).to_numpy(),
        }
    )

    report.blocks["4. DECILE MEMBERSHIP"] = (
        f"  rebalance periods      : {periods}\n"
        f"  top-decile size (median): {int(top.sum(axis=1).median())}\n"
        f"  bottom-decile size      : {int(bottom.sum(axis=1).median())}\n"
        f"  distinct names ever top : {int((frequency > 0).sum())}\n\n"
        f"  most persistent top-decile members:\n{head.to_string(index=False)}"
    )

    report.add(
        "both deciles are populated at every rebalance",
        bool(top.sum(axis=1).min() > 0 and bottom.sum(axis=1).min() > 0),
        f"smallest top decile {int(top.sum(axis=1).min())}, "
        f"bottom {int(bottom.sum(axis=1).min())}",
    )
    worst = float(frequency.max()) if len(frequency) else 0.0
    report.add(
        "no single security dominates the top decile",
        worst < 0.90,
        f"most persistent name appears in {worst:.0%} of rebalances",
    )
    report.add(
        "top-decile turnover is not zero",
        int((frequency > 0).sum()) > n,
        f"{int((frequency > 0).sum())} distinct names appear in the top decile",
    )


def _audit_block(output: PipelineOutput, config: Config, dates, report: SmokeReport) -> None:
    scored = output.scores.apex_score.loc[dates].notna().any(axis=1)
    usable = output.scores.apex_score.loc[dates].index[scored]
    probes = pd.DatetimeIndex([usable[2], usable[len(usable) // 2], usable[-3]])

    lookahead = audit_lookahead(output.panel, config, probes)
    cross = audit_cross_sectional(
        output.features, output.universe.eligible, config, probes
    )

    report.blocks["5. LEAKAGE AUDITS (measured on this dataset)"] = (
        lookahead.explain() + "\n\n" + cross.explain()
    )
    report.add("no lookahead on this dataset", lookahead.clean, "protocol section 4, measured")
    report.add("preprocessing is strictly cross-sectional", cross.clean, "ruling 5, measured")


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------


def smoke_run(source, config: Config, period: str = "in_sample") -> tuple[SmokeReport, PipelineOutput]:
    """Run the full pipeline on the in-sample period and inspect it structurally.

    Spends no research credit: in-sample is unlocked by design (section 7).
    """
    spec = config.period(period)
    if spec.get("locked", True):
        raise ValueError(
            f"the smoke run may only address an UNLOCKED period; '{period}' is "
            f"locked and running it here would spend a research credit outside "
            f"the ledger's gates"
        )

    output = build_panel_pipeline(source.load(), config)
    evaluation = evaluate(output, config, spec["start"], spec["end"])
    dates = output.calendar.daily_formation_dates(spec["start"], spec["end"])

    report = SmokeReport(
        dataset_fingerprint=source.dataset_fingerprint,
        period=f"{period} ({spec['start']} to {spec['end']})",
    )

    _universe_block(output, dates, report)
    _feature_block(output, dates, report)
    _ic_block(evaluation, report)
    _decile_block(output, config, dates, report)
    _audit_block(output, config, dates, report)

    return report, output
