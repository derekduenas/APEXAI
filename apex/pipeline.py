"""End-to-end pipeline: source -> universe -> features -> scores -> returns -> metrics.

This is the single path everything runs through. The null rig, the positive
control, and (from Stage 4) the real experiment all call `run_pipeline`, so a
test that passes on synthetic data is testing the same code that will later see
real prices -- not a parallel implementation that happens to resemble it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from apex.calendar import FormationCalendar, build_calendar
from apex.config import Config
from apex.contracts import FeaturePanel, ForwardReturns, Panel, ScorePanel, UniverseSnapshot
from apex.data.base import PriceSource
from apex.evaluate.deciles import DecileResult, evaluate_deciles
from apex.evaluate.ic import ICResult, evaluate_ic
# The dispatcher below routes to one of two experiments, so this module
# necessarily imports both. `apex.audit.execution_path` therefore certifies
# ISOLATION per experiment from that experiment's OWN entry module, not from
# here: apex.experiments.apex002 must not reach #001's scorer, and it does not.
# Note the closure walk is AST-based and sees imports inside function bodies,
# so moving this import into the branch would not have hidden it.
from apex.experiments.apex002 import build_nsi_output
from apex.features import compute_features
from apex.features.composite import build_scores
from apex.registration import require_protocol_unmodified, require_signed, require_unlocked
from apex.returns import compute_forward_returns
from apex.universe import apply_feature_completeness, build_universe


class UnregisteredExperiment(RuntimeError):
    """The configured experiment has no execution path.

    Raised instead of falling back to a default. Step 3's certification found
    APEX-002 registered in config while APEX-001's composite was what actually
    ran; a silent default is precisely how that survived five commits.
    """


@dataclass(frozen=True)
class PipelineOutput:
    panel: Panel
    calendar: FormationCalendar
    universe: UniverseSnapshot
    features: FeaturePanel
    scores: ScorePanel
    forward_returns: ForwardReturns
    daily_dates: pd.DatetimeIndex
    grid_dates: pd.DatetimeIndex

    def rescore(self, eligible: pd.DataFrame, config: Config) -> ScorePanel:
        """Re-rank on a narrowed universe (section 9 B6 sector-exclusion test).

        INCIDENT-001 D1: `attribute()` used to reach into `output.features` and
        call #001's composite scorer directly, which crashed on APEX-002 and
        put #001 machinery on #002's reporting path. Each experiment now
        rescores itself, so the attribution layer needs no branch and no import
        from either experiment.
        """
        return build_scores(self.features, eligible, config)

    def per_date_log(self) -> pd.DataFrame:
        """Protocol section 9's required per-rebalance log."""
        counts = self.universe.counts()
        deciles = self.scores.decile
        n_deciles = int(deciles.max().max()) if deciles.notna().any().any() else 0
        counts["top_decile"] = (deciles == n_deciles).sum(axis=1)
        counts["bottom_decile"] = (deciles == 1).sum(axis=1)
        return counts


@dataclass(frozen=True)
class Evaluation:
    ic_daily: ICResult
    ic_non_overlapping: ICResult
    deciles: DecileResult

    def as_dict(self) -> dict:
        return {
            "ic_daily_newey_west": self.ic_daily.as_dict(),
            "ic_non_overlapping": self.ic_non_overlapping.as_dict(),
            "deciles_gross": self.deciles.as_dict(),
        }


def build_panel_pipeline(panel: Panel, config: Config) -> PipelineOutput:
    """Run the computational core over a loaded panel. No period gating here."""
    calendar = build_calendar(panel.dates, config)

    universe = build_universe(panel, config)
    features = compute_features(panel, universe.eligible, config)
    universe = apply_feature_completeness(universe, features.complete())

    scores = build_scores(features, universe.eligible, config)
    forward_returns = compute_forward_returns(panel, universe.eligible, config)

    return PipelineOutput(
        panel=panel,
        calendar=calendar,
        universe=universe,
        features=features,
        scores=scores,
        forward_returns=forward_returns,
        daily_dates=calendar.computable_days(),
        grid_dates=calendar.grid(),
    )


def evaluate(output: PipelineOutput, config: Config, start, end) -> Evaluation:
    """Both section 7 tests over one period. B2 keeps their sampling distinct."""
    daily = output.calendar.daily_formation_dates(start, end)
    grid = output.calendar.grid_formation_dates(start, end)

    scores = output.scores.apex_score
    excess = output.forward_returns.excess
    eligible = output.universe.eligible

    return Evaluation(
        ic_daily=evaluate_ic(scores, excess, eligible, config, daily, "daily_newey_west"),
        ic_non_overlapping=evaluate_ic(scores, excess, eligible, config, grid, "non_overlapping"),
        deciles=evaluate_deciles(output.scores.decile, excess, eligible, config, grid),
    )


def run_period(
    source: PriceSource, config: Config, period: str
) -> tuple[PipelineOutput, Evaluation]:
    """The gated entry point: registration and period locks are enforced here.

    Both gates sit in front of the data load, not in front of the report, so a
    locked period cannot be "just looked at" and then discarded.
    """
    if source.requires_signed_registration:
        require_signed(config)
        require_protocol_unmodified(config)
    require_unlocked(config, period, source.dataset_fingerprint)

    spec = config.period(period)
    experiment = config.get("experiment.id")

    # Resolve the execution path BEFORE loading, like the gates above. An
    # unregistered experiment must refuse without touching vendor data, so the
    # message is "no path for APEX-999" rather than a schema error from a load
    # that was never going to be used.
    if experiment not in ("APEX-001", "APEX-002"):
        # The failure this refusal exists to prevent: an unrecognised
        # experiment id silently running whatever path happens to be first.
        # Step 3 found APEX-002 registered while #001's composite executed.
        raise UnregisteredExperiment(
            f"no execution path is registered for {experiment!r}. Refusing to "
            f"run rather than defaulting to another experiment's signal."
        )
    if experiment == "APEX-002" and getattr(source, "root", None) is None:
        raise UnregisteredExperiment(
            f"{type(source).__name__} exposes no `root`; APEX-002 needs the "
            f"snapshot path to read SF1 as-filed shares"
        )

    panel = source.load()

    if experiment == "APEX-001":
        output = build_panel_pipeline(panel, config)
    else:
        output, _ = build_nsi_output(panel, config, Path(source.root))

    return output, evaluate(output, config, spec["start"], spec["end"])
