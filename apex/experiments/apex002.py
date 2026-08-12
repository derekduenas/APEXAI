"""The APEX-002 execution path: universe -> NSI -> rank -> deciles -> returns.

This module is the #002 counterpart to `apex.pipeline.build_panel_pipeline`.
It exists as a SEPARATE module, rather than a branch inside the #001 builder,
so that the two experiments have disjoint static import closures. That is not
cosmetic: `apex.audit.execution_path` certifies each experiment by walking the
imports reachable from its entry point, and a shared entry module would make
"does #002 reach #001's scorer" unanswerable.

What it must NOT reach: `apex.features.composite`, `apex.features.f1_momentum`,
`f2_trend`, `f3_volatility`, `f4_relative_strength`, or `apex.features`'s
`compute_features`. `test_execution_path.py` fails if any of them appears here.

APEX-001's path is untouched. It still runs `build_panel_pipeline` exactly as
it did when it produced the recorded INCONCLUSIVE result, and nothing in this
module can change that.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from apex.calendar import FormationCalendar, build_calendar
from apex.config import Config
from apex.contracts import ForwardReturns, Panel, ScorePanel, UniverseSnapshot
from apex.features.nsi import (
    NSIReport,
    build_nsi_panel,
    load_as_filed,
    load_exclusions,
)
from apex.features.nsi_scores import build_nsi_scores
from apex.returns import compute_forward_returns
from apex.universe import build_universe


@dataclass(frozen=True)
class NSIOutput:
    """The #002 analogue of PipelineOutput.

    Deliberately NOT `PipelineOutput`. That container requires a `FeaturePanel`,
    whose contract hard-codes #001's four feature components and rejects any
    others -- #002 has one signal, and satisfying that contract would mean
    inventing three empty companions to impersonate an experiment that is
    closed. A separate container states the shape honestly.

    The field NAMES match `PipelineOutput` where the shared evaluation layer
    reads them (`calendar`, `universe`, `scores`, `forward_returns`), so
    `apex.pipeline.evaluate` consumes this object unchanged.
    """

    panel: Panel
    calendar: FormationCalendar
    universe: UniverseSnapshot
    nsi: pd.DataFrame
    scores: ScorePanel
    forward_returns: ForwardReturns
    daily_dates: pd.DatetimeIndex
    grid_dates: pd.DatetimeIndex

    def per_date_log(self) -> pd.DataFrame:
        """Section 9's per-rebalance log, with #002's decile orientation.

        DECILE 1 IS THE TOP DECILE (section 9, ruled 2026-08-11) -- the largest
        net repurchasers. This is the OPPOSITE of #001's `PipelineOutput`,
        where `top_decile` counts decile `n_deciles`. The two logs share column
        names and mean opposite things, which is why #002 has its own method
        rather than inheriting one.
        """
        counts = self.universe.counts()
        deciles = self.scores.decile
        n = int(deciles.max().max()) if deciles.notna().any().any() else 0
        counts["top_decile"] = (deciles == 1).sum(axis=1)
        counts["bottom_decile"] = (deciles == n).sum(axis=1)
        counts["ranked"] = deciles.notna().sum(axis=1)
        return counts


@dataclass(frozen=True)
class NSISignal:
    """Everything #002 computes BEFORE forward returns enter the picture.

    Split out so certification can exercise the real production code without
    calculating a single forward return. `build_nsi_output` calls this and adds
    returns; nothing else computes the signal, so a certification run against
    `build_nsi_signal` is a certification of the production path, not of a
    parallel reimplementation that happens to resemble it.
    """

    calendar: FormationCalendar
    universe: UniverseSnapshot
    nsi: pd.DataFrame
    scores: ScorePanel
    report: NSIReport


def build_nsi_signal(
    panel: Panel,
    config: Config,
    snapshot_root: Path,
    known_from_out: pd.DataFrame | None = None,
) -> NSISignal:
    """Universe -> as-filed shares -> NSI -> score + deciles. No returns."""
    calendar = build_calendar(panel.dates, config)
    universe = build_universe(panel, config)

    report = NSIReport()
    as_filed = load_as_filed(snapshot_root, report)
    exclusions = load_exclusions(snapshot_root)
    ticker_to_security = dict(zip(panel.meta["ticker"], panel.meta.index))

    nsi = build_nsi_panel(
        as_filed, exclusions, ticker_to_security,
        panel.dates, panel.securities, report,
        known_from_out=known_from_out,
    )

    # Section 10: NSI never redefines the universe. A security with no
    # computable NSI is absent from the RANKING at that date and remains
    # eligible at later dates -- the existing `missing_feature` path. The
    # eligibility frame is therefore NOT narrowed here.
    scores = build_nsi_scores(nsi, universe.eligible, config)

    return NSISignal(
        calendar=calendar, universe=universe, nsi=nsi, scores=scores, report=report
    )


def build_nsi_output(
    panel: Panel,
    config: Config,
    snapshot_root: Path,
    known_from_out: pd.DataFrame | None = None,
):
    """Run the #002 computational core over a loaded panel.

    `known_from_out` is passed straight through to the signal builder so the
    dry run can measure PIT compliance while calling THIS function -- the real
    production entry point -- rather than assembling its two halves itself.
    """
    signal = build_nsi_signal(panel, config, snapshot_root,
                              known_from_out=known_from_out)
    forward_returns = compute_forward_returns(panel, signal.universe.eligible, config)

    output = NSIOutput(
        panel=panel,
        calendar=signal.calendar,
        universe=signal.universe,
        nsi=signal.nsi,
        scores=signal.scores,
        forward_returns=forward_returns,
        daily_dates=signal.calendar.computable_days(),
        grid_dates=signal.calendar.grid(),
    )
    return output, signal.report
