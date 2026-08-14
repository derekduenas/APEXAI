"""APEX-003-H1 execution path: gross profitability. A HIGHER-is-better signal.

The mirror of apex002, with one deliberate difference that is the whole risk of
this experiment: gross profitability is HIGHER-is-better, the OPPOSITE of NSI.
The APEX-002 erratum documented what happens when a decile orientation is wrong;
this module states the orientation explicitly and pins it with tests:

    highest gross profitability  ->  score 100  ->  decile 1 (TOP)
    lowest  gross profitability  ->  score ~0   ->  decile 10 (BOTTOM)

Score 100 for the highest profitability is what makes the pre-registered IC
POSITIVE under "higher profitability predicts higher return". Decile 1 = top
follows the registered packet. The two derive from ONE descending rank, so they
cannot drift apart (the erratum's lesson).

ISOLATION: this path does not import apex.features.composite (#001) or
apex.features.nsi_scores (#002). It has its own scorer, so "which experiment's
scoring ran" is unambiguous. The feature itself comes from the certified
factory, PIT-safe with knowability dates.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from apex.calendar import FormationCalendar, build_calendar
from apex.config import Config
from apex.contracts import ForwardReturns, Panel, ScorePanel, UniverseSnapshot
from apex.features.factory import FactoryReport, build_features
from apex.features.registry import built_specs
from apex.returns import compute_forward_returns
from apex.universe import build_universe

FEATURE_ID = "prof_gross_profitability"
SCORE_MAX = 100.0


def _descending_rank(
    signal: pd.DataFrame, eligible: pd.DataFrame, tie_method: str
) -> tuple[pd.DataFrame, pd.Series]:
    """THE ranking. Rank 1 = HIGHEST gross profitability = best.

    One definition shared by score and decile so they cannot disagree about
    which security is best. Eligibility applied BEFORE ranking; missing stays
    missing; ties broken on a security_id-sorted view (C10), independent of the
    caller's column order.
    """
    restricted = signal.where(eligible)
    ordered = restricted.reindex(columns=restricted.columns.sort_values())
    # DESCENDING: the highest profitability gets rank 1.
    ranks = ordered.rank(axis=1, method=tie_method, ascending=False)
    counts = ordered.notna().sum(axis=1)
    return ranks.reindex(columns=signal.columns), counts


def gp_percentile_score(
    signal: pd.DataFrame, eligible: pd.DataFrame, tie_method: str = "first"
) -> pd.DataFrame:
    """0-100 score. HIGHEST profitability scores 100 (the IC variable).

    rank 1 (highest) -> 100, rank n (lowest) -> ~0. This orientation makes the
    pre-registered IC positive under 'higher profitability predicts higher
    return'.
    """
    ranks, counts = _descending_rank(signal, eligible, tie_method)
    n = counts.to_numpy()[:, None]
    pct_best = (n - ranks.to_numpy() + 1.0) / n
    return pd.DataFrame(pct_best * SCORE_MAX, index=signal.index, columns=signal.columns)


def gp_deciles(
    signal: pd.DataFrame, eligible: pd.DataFrame, n_deciles: int,
    tie_method: str = "first",
) -> pd.DataFrame:
    """Equal-count deciles. DECILE 1 = HIGHEST profitability = TOP.

    Derived from the same descending rank as the score, so decile 1 is the
    highest-scoring names -- no sign flip between the two.
    """
    ranks, counts = _descending_rank(signal, eligible, tie_method)
    n = counts.to_numpy()[:, None]
    with np.errstate(invalid="ignore"):
        scaled = np.ceil(ranks.to_numpy() / n * n_deciles)
    bounded = np.clip(scaled, 1, n_deciles)
    out = pd.DataFrame(bounded, index=signal.index, columns=signal.columns)
    return out.where(ranks.notna())


def build_gp_scores(signal: pd.DataFrame, eligible: pd.DataFrame, config: Config) -> ScorePanel:
    """The APEX-003 ScorePanel. No winsorisation, no z-scoring, no smoothing."""
    tie_method = config.get("evaluation.rank_tie_method")
    n_deciles = int(config.get("evaluation.n_deciles"))
    score = gp_percentile_score(signal, eligible, tie_method)
    decile = gp_deciles(signal, eligible, n_deciles, tie_method)
    return ScorePanel(
        dates=signal.index, securities=signal.columns,
        category_scores={"gross_profitability": signal.where(eligible)},
        apex_score=score, decile=decile,
        top_decile_label=1,     # decile 1 = highest profitability = top
    )


@dataclass(frozen=True)
class GPSignal:
    calendar: FormationCalendar
    universe: UniverseSnapshot
    signal: pd.DataFrame
    scores: ScorePanel
    report: FactoryReport


@dataclass(frozen=True)
class GPOutput:
    panel: Panel
    calendar: FormationCalendar
    universe: UniverseSnapshot
    signal: pd.DataFrame
    scores: ScorePanel
    forward_returns: ForwardReturns
    daily_dates: pd.DatetimeIndex
    grid_dates: pd.DatetimeIndex

    def rescore(self, eligible: pd.DataFrame, config: Config) -> ScorePanel:
        """Re-rank on a narrowed universe (section-9 B6). #003 rescores itself."""
        return build_gp_scores(self.signal, eligible, config)

    def per_date_log(self) -> pd.DataFrame:
        counts = self.universe.counts()
        deciles = self.scores.decile
        n = int(deciles.max().max()) if deciles.notna().any().any() else 0
        counts["top_decile"] = (deciles == 1).sum(axis=1)      # decile 1 = top
        counts["bottom_decile"] = (deciles == n).sum(axis=1)
        counts["ranked"] = deciles.notna().sum(axis=1)
        return counts


def build_gp_signal(
    panel: Panel, config: Config, snapshot_root: Path,
    known_from_out: pd.DataFrame | None = None,
) -> GPSignal:
    """Universe -> gross-profitability feature (PIT) -> score + deciles."""
    calendar = build_calendar(panel.dates, config)
    universe = build_universe(panel, config)

    spec = next(x for x in built_specs() if x.feature_id == FEATURE_ID)
    values, known, report = build_features(snapshot_root, panel, (spec,))
    signal = values[FEATURE_ID]
    if known_from_out is not None:
        kf = known[FEATURE_ID].reindex(index=known_from_out.index,
                                       columns=known_from_out.columns)
        known_from_out.loc[:, :] = kf

    scores = build_gp_scores(signal, universe.eligible, config)
    return GPSignal(calendar=calendar, universe=universe, signal=signal,
                    scores=scores, report=report)


def build_gp_output(
    panel: Panel, config: Config, snapshot_root: Path,
    known_from_out: pd.DataFrame | None = None,
):
    signal = build_gp_signal(panel, config, snapshot_root, known_from_out=known_from_out)
    forward_returns = compute_forward_returns(panel, signal.universe.eligible, config)
    output = GPOutput(
        panel=panel, calendar=signal.calendar, universe=signal.universe,
        signal=signal.signal, scores=signal.scores, forward_returns=forward_returns,
        daily_dates=signal.calendar.computable_days(), grid_dates=signal.calendar.grid(),
    )
    return output, signal.report
