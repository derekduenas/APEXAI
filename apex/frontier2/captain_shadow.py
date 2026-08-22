"""CaptainFrontierShadow — F9: a parallel, advisory shadow CIO. It
cannot modify or replace apex.captain.kernel.py (imported nowhere in
this module -- not even read-only; the two Captains never touch).

ANTI-ANCHORING IS STRUCTURAL, reusing the exact discipline
apex.frontier.underwriting.reunderwrite() documents (reimplemented
independently here, per the firewall): `review()` accepts the prior
STATE LABEL and its INPUT SNAPSHOT only. The prior judgment's reasoning,
competing explanation, or narrative text is never a parameter, so it
cannot leak into the new evaluation -- every review answers the twelve
questions from CURRENT canonical inputs alone.

Every organ upstream of this one already turned raw signal into a typed
categorical answer (Curve's expression, Assassin2's familiarity,
LeadingEdgeMap's entry_quality, ...). CaptainFrontierShadow does not
re-derive any of those numbers; its only job is to weigh the five
NAMED, SEPARATE quality axes (never a scalar confidence) into one of
eight attention states -- and never TRADE/BUY/SELL/SIZE/OVERRIDE, which
are not even in this module's vocabulary.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

from apex.frontier2 import FRONTIER2_POWER

LEDGER = Path("results/frontier2/captain_shadow_ledger.jsonl")

STATES = ("IGNORE", "WATCH", "DEVELOP", "SERIOUS", "WAIT_FOR_CONFIRMATION",
         "WAIT_FOR_ENTRY", "DEGRADE", "INVALIDATE")
TERMINAL = ("INVALIDATE",)

QUALITY_TIERS = ("STRONG", "MODERATE", "WEAK", "UNKNOWN")

TRIGGER_FIELDS = ("curve_state", "curve_direction", "curve_expression",
                  "curve_likelihood", "participant_trap",
                  "participant_direction", "propagation_state",
                  "leading_edge_rank", "leading_edge_entry_quality",
                  "assassin2_familiarity", "assassin2_caution_label",
                  "observation_quality", "model_market_tally_agrees")

# fields that, when they change, always warrant a fresh review even
# outside a scheduled heartbeat -- same MATERIAL_CHANGE concept as
# underwriting.py's is_material(), reimplemented locally.
MATERIALITY_LAW = ("degrade or invalidate on data/model breakdown; "
                   "promote only on STRONG direction + GOOD/STRONG entry "
                   "+ STRONG transition")

_LIKELIHOOD_TO_TRANSITION_QUALITY = {
    "HIGH": "STRONG", "MODERATE": "MODERATE", "LOW": "WEAK", "NONE": "WEAK",
    "UNKNOWN": "UNKNOWN"}
_ENTRY_QUALITY_STRONG = ("STRONG", "GOOD")
_ENTRY_QUALITY_WEAK = ("WEAK", "POOR", "ACCEPTABLE")
_LETHAL_FAMILIARITY = ("DATA_CONFLICT",)


class CaptainShadowError(RuntimeError):
    pass


@dataclass(frozen=True)
class CaptainFrontierShadowState:
    candidate_id: str
    subject: str
    state: str
    prior_state: str | None
    transition_quality: str
    direction_quality: str
    entry_quality: str
    data_quality: str
    model_familiarity: str
    what_changed: tuple
    competing_explanation: str | None
    falsification: str
    reasoning: tuple
    inputs_snapshot: dict = field(default_factory=dict)
    known_from: str | None = None
    as_of: str | None = None
    decision_power: str = FRONTIER2_POWER

    def __post_init__(self):
        if self.state not in STATES:
            raise CaptainShadowError(f"unknown state {self.state!r}")
        for f in (self.transition_quality, self.direction_quality,
                 self.entry_quality, self.data_quality, self.model_familiarity):
            if f not in QUALITY_TIERS and f not in (
                    "GOOD", "POOR", "ACCEPTABLE", "FULL", "PARTIAL", "LIMITED",
                    "INVALID", "FAMILIAR", "LOW_FAMILIARITY",
                    "OUT_OF_DISTRIBUTION", "MODEL_CONFLICT", "DATA_CONFLICT",
                    "STRUCTURAL_RISK"):
                raise CaptainShadowError(f"unrecognized quality value {f!r}")

    def as_record(self) -> dict:
        return {"kind": "captain_frontier_shadow_state", **asdict(self)}


def what_changed(prior_inputs: dict, current_inputs: dict) -> tuple:
    changes = []
    for f in TRIGGER_FIELDS:
        a, b = prior_inputs.get(f), current_inputs.get(f)
        if a != b:
            changes.append({"field": f, "was": a, "now": b})
    return tuple(changes)


def _answer_the_twelve_questions(*, state, prior_state, changes,
                                  transition_quality, direction_quality,
                                  entry_quality, competing_explanation,
                                  falsification) -> tuple:
    return (
        f"1. WHAT CHANGED: {[c['field'] for c in changes] or 'nothing material'}",
        f"2. BEGINNING TO CHANGE: transition_quality={transition_quality}",
        f"3. WHY: current typed inputs from Curve/Propagation/Participant"
        f"Pressure/Assassin2 (no narrative carried forward from the prior review)",
        f"4. COMPETING EXPLANATION: {competing_explanation or 'none supplied'}",
        f"5. WHO MAY BE PRESSURED: see ParticipantPressureState (this "
        f"module reads its typed output only)",
        f"6. WHERE PROPAGATING: see PropagationEdge/LeadingEdgeState",
        f"7. LEADING EDGE: see LeadingEdgeMap rank (this module reads "
        f"its typed output only)",
        f"8. DIRECTION CLEARER: direction_quality={direction_quality}",
        f"9. ENTRY IMPROVING: entry_quality={entry_quality}",
        f"10. FALSIFIED BY: {falsification}",
        f"11. BETTER OPPORTUNITY: not compared here -- see "
        f"OpportunityIntelligenceGraph (F10)",
        f"12. WOULD I STILL CARE IF FIRST SEEN NOW: "
        f"{'yes' if state not in ('IGNORE', 'INVALIDATE', 'DEGRADE') else 'no'}",
    )


def review(prior: CaptainFrontierShadowState | None, *, candidate_id: str,
          subject: str, current_inputs: dict, now, known_from,
          competing_explanation: str | None = None,
          falsification: str = "canonical inputs reverse the direction "
          "or the transition quality decays to WEAK"
          ) -> CaptainFrontierShadowState:
    import pandas as pd
    now = pd.Timestamp(now)
    prior_state = prior.state if prior is not None else None
    prior_inputs = prior.inputs_snapshot if prior is not None else {}

    if prior_state in TERMINAL:
        raise CaptainShadowError(
            f"{candidate_id} is {prior_state}; a dead thesis does not "
            f"resurrect -- a new thesis gets a NEW candidate_id")

    ci = {f: current_inputs.get(f, "UNKNOWN") for f in TRIGGER_FIELDS}
    changes = what_changed(prior_inputs, ci)

    transition_quality = _LIKELIHOOD_TO_TRANSITION_QUALITY.get(
        ci["curve_likelihood"], "UNKNOWN")
    direction = ci["curve_direction"]
    agrees = current_inputs.get("model_market_tally_agrees")
    if direction in ("UP", "DOWN") and agrees is not False:
        direction_quality = "STRONG"
    elif direction in ("UP", "DOWN") and agrees is False:
        # a clear directional read the model market actively disagrees
        # with is real doubt, not merely unconfirmed -- same bucket as
        # MIXED, not a quiet fallback to MODERATE.
        direction_quality = "WEAK"
    elif direction == "MIXED":
        direction_quality = "WEAK"
    elif direction == "UNKNOWN":
        direction_quality = "UNKNOWN"
    else:
        direction_quality = "MODERATE"
    entry_quality = ci["leading_edge_entry_quality"]
    data_quality = ci["observation_quality"]
    model_familiarity = ci["assassin2_familiarity"]

    lethal = (model_familiarity in _LETHAL_FAMILIARITY
             or data_quality == "INVALID")

    if lethal:
        state = ("INVALIDATE" if prior_state in
                ("SERIOUS", "WAIT_FOR_ENTRY", "WAIT_FOR_CONFIRMATION")
                else "DEGRADE")
    elif (direction_quality == "STRONG" and entry_quality in _ENTRY_QUALITY_STRONG
          and transition_quality == "STRONG"):
        state = "SERIOUS"
    elif direction_quality == "STRONG" and entry_quality in _ENTRY_QUALITY_WEAK:
        state = "WAIT_FOR_ENTRY"
    elif (transition_quality in ("STRONG", "MODERATE")
          and direction_quality in ("UNKNOWN", "WEAK")):
        state = "WAIT_FOR_CONFIRMATION"
    elif transition_quality == "MODERATE":
        state = "DEVELOP"
    elif (transition_quality == "WEAK"
          and prior_state in ("DEVELOP", "SERIOUS", "WAIT_FOR_ENTRY",
                              "WAIT_FOR_CONFIRMATION")):
        state = "DEGRADE"
    elif transition_quality == "WEAK":
        state = "WATCH"
    else:
        state = "IGNORE"

    reasoning = _answer_the_twelve_questions(
        state=state, prior_state=prior_state, changes=changes,
        transition_quality=transition_quality, direction_quality=direction_quality,
        entry_quality=entry_quality, competing_explanation=competing_explanation,
        falsification=falsification)

    return CaptainFrontierShadowState(
        candidate_id=candidate_id, subject=subject, state=state,
        prior_state=prior_state, transition_quality=transition_quality,
        direction_quality=direction_quality, entry_quality=entry_quality,
        data_quality=data_quality, model_familiarity=model_familiarity,
        what_changed=changes, competing_explanation=competing_explanation,
        falsification=falsification, reasoning=reasoning,
        inputs_snapshot=ci, known_from=str(pd.Timestamp(known_from)),
        as_of=str(now))


def persist(state: CaptainFrontierShadowState) -> dict:
    import sys
    sys.path.insert(0, "scripts")
    from nightly_pull import _chain_append
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    return _chain_append(LEDGER, state.as_record())
