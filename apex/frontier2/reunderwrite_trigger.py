"""ReunderwriteTrigger — F: THE DESK NEVER FALLS IN LOVE WITH ITS LAST
OPINION.

Built 2026-08-18 after the live session proved the doctrine was not
actually enforced by the runtime. Root cause (measured, not inferred):
the runtime gated CaptainFrontierShadow behind
`route.tier >= 4 or symbol not in state.captain_state`, and
compute_router2 only grants tier 4 when opportunity_seriousness is
already SERIOUS or WAIT_FOR_ENTRY. A subject that entered at WATCH
(tier 1) or DEVELOP (tier 2/3) therefore could never be re-reviewed:
Captain could only reach SERIOUS by running, running required tier 4,
and tier 4 required already being SERIOUS. A perfect circular deadlock.
Result: 55/55 subjects got exactly ONE evaluation and stayed frozen for
the whole session while Curve/EV/PP/Propagation kept updating beneath
them.

THIS MODULE CHANGES NO JUDGMENT SEMANTICS. It decides only WHETHER to
ASK Captain again. What Captain then concludes is entirely
captain_shadow.review()'s business, unchanged.

SEMANTIC CHANGE, NOT JITTER: triggers fire on categorical/typed state
transitions (POSITIVE_TRANSITION -> NEGATIVE_TRANSITION, quality tier
STRONG -> WEAK). A float that moved from 0.301 to 0.302 is not a
trigger and this module has no numeric-threshold parameter through
which one could become one.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from apex.frontier2 import FRONTIER2_POWER

LEDGER = Path("results/frontier2/reunderwrite_trigger_ledger.jsonl")

TRIGGER_KINDS = (
    "CURVE_STATE_CHANGE",
    "TRANSITION_QUALITY_CHANGE",
    "DIRECTION_QUALITY_CHANGE",
    "EXPECTATION_VIOLATION_CHANGE",
    "PARTICIPANT_PRESSURE_CHANGE",
    "PROPAGATION_CHANGE",
    "LEADING_EDGE_CHANGE",
    "MODEL_MARKET_CHANGE",
    "ASSASSIN_WOUND_CHANGE",
    "OBSERVATION_INTEGRITY_CHANGE",
    "SYSTEM_COGNITION_CHANGE",
    "DATA_DISAGREEMENT_CHANGE",
    "ENTRY_QUALITY_CHANGE",
    "RANK_CHANGE",
    "RUNTIME_STALENESS_SAFETY_INTERVAL",
    "NEVER_REVIEWED",
)

# Which observed-input key maps to which trigger kind. Every one of
# these is a CATEGORICAL field upstream (Curve's high_level_state,
# Assassin2's caution_label, ...) -- never a raw float.
INPUT_TO_TRIGGER = {
    "curve_state": "CURVE_STATE_CHANGE",
    "curve_direction": "DIRECTION_QUALITY_CHANGE",
    "curve_expression": "CURVE_STATE_CHANGE",
    "curve_likelihood": "TRANSITION_QUALITY_CHANGE",
    "expectation_violation_state": "EXPECTATION_VIOLATION_CHANGE",
    "participant_trap": "PARTICIPANT_PRESSURE_CHANGE",
    "participant_direction": "PARTICIPANT_PRESSURE_CHANGE",
    "propagation_state": "PROPAGATION_CHANGE",
    "leading_edge_rank": "RANK_CHANGE",
    "leading_edge_entry_quality": "ENTRY_QUALITY_CHANGE",
    "model_market_tally_agrees": "MODEL_MARKET_CHANGE",
    "assassin2_familiarity": "ASSASSIN_WOUND_CHANGE",
    "assassin2_caution_label": "ASSASSIN_WOUND_CHANGE",
    "observation_quality": "OBSERVATION_INTEGRITY_CHANGE",
    "system_cognition_state": "SYSTEM_COGNITION_CHANGE",
    "data_disagreement": "DATA_DISAGREEMENT_CHANGE",
}

# Deterministic staleness bound. NOT a tuned trading parameter and NOT
# derived from any market outcome -- its only purpose is preventing
# indefinitely stale judgment when no categorical input happens to flip.
RUNTIME_STALENESS_SAFETY_INTERVAL_S = 300.0

# States considered "live enough to keep reconsidering" for the
# heartbeat. DEGRADE is included deliberately: it is NOT terminal (only
# INVALIDATE is, per captain_shadow.TERMINAL), a degrading thesis can
# still recover or die outright, and compute_router2 already treats
# DEGRADE as "still worth a real check on the way down". Leaving it out
# recreated the freeze for degrading subjects in the Phase 1.0 dry run.
# IGNORE is excluded from the HEARTBEAT only -- an IGNORE subject is
# still re-reviewed the instant any material input changes; it just does
# not consume a periodic review slot for a non-opportunity.
HEARTBEAT_STATES = ("WATCH", "DEVELOP", "SERIOUS", "WAIT_FOR_CONFIRMATION",
                    "WAIT_FOR_ENTRY", "DEGRADE")
TERMINAL_STATES = ("INVALIDATE",)


class ReunderwriteTriggerError(RuntimeError):
    pass


@dataclass(frozen=True)
class ReunderwriteDecision:
    subject: str
    candidate_id: str
    should_review: bool
    triggers: tuple                # tuple of TRIGGER_KINDS
    changed_inputs: tuple          # ({field, was, now}, ...)
    unchanged_inputs: tuple
    prior_state: str | None
    seconds_since_last_review: float | None
    is_terminal: bool
    known_from: str
    as_of: str
    decision_power: str = FRONTIER2_POWER

    def __post_init__(self):
        bad = set(self.triggers) - set(TRIGGER_KINDS)
        if bad:
            raise ReunderwriteTriggerError(f"unknown trigger kind(s) {bad}")
        if self.should_review and not self.triggers:
            raise ReunderwriteTriggerError(
                "should_review=True must name at least one trigger")

    def as_record(self) -> dict:
        return {"kind": "frontier2_reunderwrite_decision", **asdict(self)}


def evaluate(*, subject: str, candidate_id: str,
             prior_inputs: dict | None, current_inputs: dict,
             prior_state: str | None,
             seconds_since_last_review: float | None,
             known_from, now) -> ReunderwriteDecision:
    """Pure function: no I/O, no captain invocation, no judgment. Decides
    only whether Captain should be ASKED again."""
    import pandas as pd

    changed, unchanged, triggers = [], [], []

    if prior_state is None or prior_inputs is None:
        triggers.append("NEVER_REVIEWED")
        for f, v in sorted(current_inputs.items()):
            changed.append({"field": f, "was": None, "now": v})
        return ReunderwriteDecision(
            subject=subject, candidate_id=candidate_id, should_review=True,
            triggers=tuple(dict.fromkeys(triggers)), changed_inputs=tuple(changed),
            unchanged_inputs=(), prior_state=prior_state,
            seconds_since_last_review=seconds_since_last_review,
            is_terminal=False, known_from=str(pd.Timestamp(known_from)),
            as_of=str(pd.Timestamp(now)))

    is_terminal = prior_state in TERMINAL_STATES

    for f in sorted(set(prior_inputs) | set(current_inputs)):
        was, nowv = prior_inputs.get(f), current_inputs.get(f)
        if was != nowv:
            changed.append({"field": f, "was": was, "now": nowv})
            kind = INPUT_TO_TRIGGER.get(f)
            if kind:
                triggers.append(kind)
        else:
            unchanged.append(f)

    # heartbeat: only for live (non-terminal) states, and only when no
    # material change already justified a review.
    if (not triggers and not is_terminal and prior_state in HEARTBEAT_STATES
            and seconds_since_last_review is not None
            and seconds_since_last_review >= RUNTIME_STALENESS_SAFETY_INTERVAL_S):
        triggers.append("RUNTIME_STALENESS_SAFETY_INTERVAL")

    # TERMINAL STATE LAW: an INVALIDATE-d thesis is never re-reviewed
    # back to life. New evidence requires a NEW_THESIS_LINEAGE candidate
    # id, minted by the caller -- never a mutation of this one.
    should_review = bool(triggers) and not is_terminal

    return ReunderwriteDecision(
        subject=subject, candidate_id=candidate_id, should_review=should_review,
        triggers=tuple(dict.fromkeys(triggers)), changed_inputs=tuple(changed),
        unchanged_inputs=tuple(unchanged), prior_state=prior_state,
        seconds_since_last_review=seconds_since_last_review,
        is_terminal=is_terminal, known_from=str(pd.Timestamp(known_from)),
        as_of=str(pd.Timestamp(now)))


def requires_fresh_assassin(decision: ReunderwriteDecision) -> bool:
    """Assassin2 must be re-run BEFORE Captain whenever the evidence
    Assassin reasons over changed -- never reuse a hours-old verdict."""
    evidence_triggers = {
        "CURVE_STATE_CHANGE", "EXPECTATION_VIOLATION_CHANGE",
        "PROPAGATION_CHANGE", "OBSERVATION_INTEGRITY_CHANGE",
        "DATA_DISAGREEMENT_CHANGE", "TRANSITION_QUALITY_CHANGE",
        "NEVER_REVIEWED", "RUNTIME_STALENESS_SAFETY_INTERVAL",
    }
    return bool(set(decision.triggers) & evidence_triggers)


def new_thesis_lineage_id(subject: str, *, generation: int) -> str:
    """After a terminal INVALIDATE, a genuinely new thesis gets its own
    lineage id -- the old candidate_id is never resurrected."""
    if generation < 2:
        raise ReunderwriteTriggerError(
            "a NEW_THESIS_LINEAGE id starts at generation 2 (generation 1 is "
            "the original thesis, which stays INVALIDATED)")
    return f"{subject}-LIVE-GEN{generation}"


def persist(decision: ReunderwriteDecision) -> dict:
    import sys
    sys.path.insert(0, "scripts")
    from nightly_pull import _chain_append
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    return _chain_append(LEDGER, decision.as_record())
