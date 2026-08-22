"""ResearchScientist — F12: hypothesis generation, not self-modifying
trading. It studies prospective errors, abstentions, missed
opportunities, false positives and component disagreement, and may only
ever write ONE status: RESEARCH_PROPOSAL_ONLY.

THE LAW: this module cannot modify production, change weights or
thresholds, promote components, spend experiment credits, open holdout,
or authorize Capital -- not by convention, but because nothing in this
file imports apex.governance.ledger (experiment credits, Holm
multiplicity), apex.governance.holdout_capacity, or any apex.hunter/
captain/execution module (test_frontier2_firewall.py already proves
the package-wide version of this; this module additionally never even
NAMES those two governance modules).

`status` is not a caller-settable field on ResearchProposal -- there is
no parameter for it, so a proposal can never be minted as anything but
RESEARCH_PROPOSAL_ONLY.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from apex.frontier2 import FRONTIER2_POWER

LEDGER = Path("results/frontier2/research_scientist_ledger.jsonl")

STATUS = "RESEARCH_PROPOSAL_ONLY"

# named, documented triggers for the two automatic generators below
MODEL_CONFLICT_MIN_EACH_SIDE = 2
FALSE_POSITIVE_TRIGGER = 1


class ResearchScientistError(RuntimeError):
    pass


@dataclass(frozen=True)
class ResearchProposal:
    proposal_id: str
    subject_component: str
    observation: str
    hypothesis: str
    mechanism: str
    falsification: str
    required_data: tuple
    primary_metric: str
    secondary_metric: str | None
    sample_requirement: str
    regime_requirement: str
    prospective_test: str
    expected_failure_mode: str
    provenance: tuple
    known_from: str
    as_of: str
    status: str = STATUS
    decision_power: str = FRONTIER2_POWER

    def __post_init__(self):
        if self.status != STATUS:
            raise ResearchScientistError(
                f"a ResearchProposal may only ever carry status "
                f"{STATUS!r}; got {self.status!r}")

    def as_record(self) -> dict:
        return {"kind": "research_proposal", **asdict(self)}


def propose(*, proposal_id: str, subject_component: str, observation: str,
           hypothesis: str, mechanism: str, falsification: str,
           required_data: tuple, primary_metric: str,
           sample_requirement: str, regime_requirement: str,
           prospective_test: str, expected_failure_mode: str,
           provenance: tuple = (), secondary_metric: str | None = None,
           known_from, now) -> ResearchProposal:
    import pandas as pd
    now = pd.Timestamp(now)
    return ResearchProposal(
        proposal_id=proposal_id, subject_component=subject_component,
        observation=observation, hypothesis=hypothesis, mechanism=mechanism,
        falsification=falsification, required_data=tuple(required_data),
        primary_metric=primary_metric, secondary_metric=secondary_metric,
        sample_requirement=sample_requirement,
        regime_requirement=regime_requirement, prospective_test=prospective_test,
        expected_failure_mode=expected_failure_mode,
        provenance=tuple(provenance), known_from=str(pd.Timestamp(known_from)),
        as_of=str(now))


def from_model_market_conflict(snapshot: dict, *, now) -> ResearchProposal | None:
    """Auto-generates a proposal FROM a genuine engine disagreement --
    studying component disagreement is the module's explicit mandate.
    Returns None when there is nothing material to study."""
    t = snapshot["tally"]
    if not (t.get("SUPPORT", 0) >= MODEL_CONFLICT_MIN_EACH_SIDE
           and t.get("OPPOSE", 0) >= MODEL_CONFLICT_MIN_EACH_SIDE):
        return None
    prop = snapshot["proposition"]
    return propose(
        proposal_id=f"RS-CONFLICT-{prop}",
        subject_component="InternalModelMarket", observation=(
            f"on {prop!r}, {t['SUPPORT']} engines SUPPORT and {t['OPPOSE']} "
            f"engines OPPOSE -- a material, resolved-to-be-studied split"),
        hypothesis=(
            "the disagreeing engines are conditioning on different, "
            "possibly complementary information rather than one side "
            "simply being wrong"),
        mechanism="different seats read different upstream organs; "
        "disagreement may correlate with regime or data-quality state",
        falsification="the disagreement rate does not correlate with "
        "any measurable regime or quality variable across many "
        "prospective observations",
        required_data=("engine-level resolved outcomes", "regime tag per observation"),
        primary_metric="post-hoc accuracy split by which side an engine took",
        secondary_metric="calibration of the losing side specifically",
        sample_requirement=">=20 resolved propositions with this same "
        "conflict shape, per F16's minimum-N convention",
        regime_requirement="at least two distinct regimes represented",
        prospective_test="track resolved outcomes for this proposition "
        "class going forward; do NOT touch weights in the meantime",
        expected_failure_mode="the split turns out to be noise with no "
        "regime or quality correlate, in which case no action is warranted",
        provenance=(f"model_market_snapshot:{prop}",), now=now, known_from=now)


def from_false_positive(scorecard, *, now) -> ResearchProposal | None:
    """`scorecard`: an apex.frontier2.model_market.Scorecard."""
    if scorecard.false_positive < FALSE_POSITIVE_TRIGGER:
        return None
    return propose(
        proposal_id=f"RS-FP-{scorecard.engine}-{scorecard.proposition_class}",
        subject_component=scorecard.engine, observation=(
            f"{scorecard.engine} has {scorecard.false_positive} false "
            f"positive(s) on {scorecard.proposition_class!r} "
            f"(n={scorecard.resolved} resolved)"),
        hypothesis=f"{scorecard.engine} may be systematically over-eager "
        f"under some identifiable condition",
        mechanism="unknown -- this proposal exists to trigger a look, "
        "not to assert a mechanism",
        falsification="false positive rate does not exceed the other "
        "engines' rates once enough resolved samples exist",
        required_data=("per-observation false-positive flags for every "
                       "engine on the same proposition class",),
        primary_metric="false_positive / resolved ratio, engine vs peers",
        secondary_metric=None,
        sample_requirement=">=20 resolved, per F16's minimum-N convention",
        regime_requirement="UNSPECIFIED (regime tagging not yet wired "
        "into scorecards)",
        prospective_test="continue scoring this engine prospectively; "
        "do NOT downweight it in the meantime",
        expected_failure_mode="the elevated rate is within normal "
        "variance once more samples accrue",
        provenance=(f"scorecard:{scorecard.engine}:{scorecard.proposition_class}",),
        now=now, known_from=now)


def persist(proposal: ResearchProposal) -> dict:
    import sys
    sys.path.insert(0, "scripts")
    from nightly_pull import _chain_append
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    return _chain_append(LEDGER, proposal.as_record())
