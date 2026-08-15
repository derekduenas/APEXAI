"""The exploration candidate contract: what a model must carry to exist.

A candidate is a HYPOTHESIS with receipts. Emission is REFUSED unless it
carries: its full trial denominator (cross-checked against the ledger --
claiming fewer trials than were run is the file drawer, mechanised), its
purged-CV and walk-forward results, its deflated Sharpe computed at the TRUE
denominator, its PBO, its correlation to every existing validated signal
(a rediscovery of GP is not a new hypothesis), and -- when any feature is
regime- or state-derived -- the provenance of those labels in the
never-revised online LabelStore (hindsight regimes are refused).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from apex.exploration.accounting import TrialLedger
from apex.exploration.stats import deflated_sharpe

EVIDENCE_CLASS = "exploration_candidate"

STATE_MARKERS = ("regime", "state", "vol_regime", "world")


class CandidateRefused(ValueError):
    """The candidate contract was not met. Nothing is emitted."""


@dataclass(frozen=True)
class ExplorationCandidate:
    hypothesis: str
    family: str
    feature_definitions: dict
    trial_count: int
    purged_cv_score: float
    walk_forward_score: float
    dsr: dict
    pbo: float
    correlation_to_validated: dict     # signal name -> corr, ALL of them
    regime_feature_provenance: str | None
    evidence_class: str = field(default=EVIDENCE_CLASS)


def emit_candidate(*, hypothesis: str, family: str, feature_definitions: dict,
                   claimed_trials: int, ledger: TrialLedger,
                   purged_cv_score: float, walk_forward_score: float,
                   observed_sr: float, n_periods: int, pbo: float,
                   correlation_to_validated: dict,
                   regime_feature_provenance: str | None = None,
                   skew: float = 0.0, kurtosis: float = 3.0
                   ) -> ExplorationCandidate:
    true_n = ledger.denominator(family)
    if true_n == 0:
        raise CandidateRefused(f"family {family!r} has no recorded trials; a "
                               f"candidate cannot precede its own search")
    if claimed_trials < true_n:
        raise CandidateRefused(
            f"claimed {claimed_trials} trials but the ledger records "
            f"{true_n} for {family!r}. The denominator is not negotiable.")
    if not correlation_to_validated:
        raise CandidateRefused(
            "correlation to existing validated signals is REQUIRED -- a "
            "rediscovery is not a new hypothesis, and the machine must ask "
            "'have we already tested this?' before anyone spends anything.")
    uses_state = any(any(m in name.lower() for m in STATE_MARKERS)
                     for name in feature_definitions)
    if uses_state and not regime_feature_provenance:
        raise CandidateRefused(
            "a state/regime-derived feature must cite its provenance in the "
            "never-revised online LabelStore. A regime computed in hindsight "
            "is the leak Track 4 exists to prevent.")

    # The DSR is computed HERE, at the TRUE denominator -- a flattering DSR
    # computed at n=1 cannot be smuggled in because none is accepted.
    dsr = deflated_sharpe(observed_sr, true_n, n_periods, skew, kurtosis)

    return ExplorationCandidate(
        hypothesis=hypothesis, family=family,
        feature_definitions=dict(feature_definitions),
        trial_count=true_n,
        purged_cv_score=float(purged_cv_score),
        walk_forward_score=float(walk_forward_score),
        dsr=dsr, pbo=float(pbo),
        correlation_to_validated=dict(correlation_to_validated),
        regime_feature_provenance=regime_feature_provenance,
    )
