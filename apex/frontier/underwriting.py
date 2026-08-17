"""THE CONTINUOUS RE-UNDERWRITING LAW — the desk never falls in love
with its last opinion.

Every material candidate is a CHANGING HYPOTHESIS with an
OpportunityState. Sensors run continuously; expensive judgment runs on
material change or bounded heartbeat; and every re-underwrite asks the
current-state question:

    "If this opportunity first appeared RIGHT NOW, knowing only what is
     knowable right now, would we still care?"

ANTI-ANCHORING IS STRUCTURAL, NOT REQUESTED: reunderwrite() accepts the
prior STATE LABEL only — the previous judgment's content (its support,
its enthusiasm, its brief) is not a parameter and therefore cannot leak
into the new evaluation. Prior belief is a label to diff against, never
an input fact.

decision_power = NONE_FRONTIER_SHADOW. Rank is attention, never Capital.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from apex.frontier import FRONTIER_POWER

LEDGER = Path("results/frontier/underwriting_ledger.jsonl")

STATES = ("DISCOVERED", "WATCHING", "DEVELOPING", "SERIOUS",
          "WAITING_FOR_ENTRY", "CAPITAL_REVIEW", "DEGRADED",
          "INVALIDATED", "EXPIRED")

# Only these two are permanent: the mechanism itself can no longer exist.
TERMINAL = ("INVALIDATED", "EXPIRED")

# Terminal rejection vs conditional wait — the distinction the operator
# named: TOO_EXTENDED is a reason to WATCH, not a death certificate.
TERMINAL_REASONS = ("THESIS_INVALIDATED", "DATA_BAD", "MECHANISM_BROKEN",
                    "EVIDENCE_CONTRADICTION", "OPPORTUNITY_EXPIRED")
CONDITIONAL_REASONS = ("TOO_EXTENDED", "WAIT_FOR_RETEST", "LIQUIDITY_POOR",
                       "WORLD_MIXED", "AWAITING_CONFIRMATION")

# The material-change classes that trigger event-driven re-underwriting.
# Deterministic field diffs over CANONICAL categorical inputs.
TRIGGER_FIELDS = ("market_regime", "sector_leadership", "rs_state",
                  "vwap_relationship", "or_structure", "price_structure",
                  "participation", "volatility_state", "catalyst_status",
                  "dislocation_state", "visual_structure",
                  "microstructure", "execution_quality",
                  "assassin_verdict", "opportunity_rank")

# heartbeat: seconds before a judgment goes STALE per state. Attention
# scales with seriousness; these are OPERATIONAL routing numbers, not
# alpha thresholds, and changing them is an ops act not a strategy act.
HEARTBEAT_S = {"DISCOVERED": 900, "WATCHING": 300, "DEVELOPING": 180,
               "SERIOUS": 120, "WAITING_FOR_ENTRY": 120,
               "CAPITAL_REVIEW": 60, "DEGRADED": 300}


class UnderwritingViolation(RuntimeError):
    pass


@dataclass(frozen=True)
class OpportunityState:
    candidate_id: str
    symbol: str
    state: str
    direction_quality: str = "UNKNOWN"        # separate axes, always
    entry_quality: str = "UNKNOWN"
    reason: str = ""
    last_underwritten_at: str | None = None
    inputs_snapshot: dict = field(default_factory=dict)
    decision_power: str = FRONTIER_POWER

    def __post_init__(self):
        if self.state not in STATES:
            raise UnderwritingViolation(f"unknown state {self.state!r}")

    def as_record(self) -> dict:
        return {"kind": "opportunity_state", **asdict(self)}


def what_changed(prior_inputs: dict, current_inputs: dict) -> list:
    """Deterministic diff over the trigger fields. The answer to the
    mandatory question WHAT_CHANGED_SINCE_LAST_REVIEW is computed, never
    remembered."""
    changes = []
    for f in TRIGGER_FIELDS:
        a, b = prior_inputs.get(f), current_inputs.get(f)
        if a != b:
            changes.append({"field": f, "was": a, "now": b})
    return changes


def is_material(changes: list) -> bool:
    return bool(changes)


def judgment_status(state: OpportunityState, now, data_age_s=None) -> dict:
    """No judgment lives forever. Past its heartbeat -> STALE, never a
    silently-current favorable opinion."""
    import pandas as pd
    if state.state in TERMINAL:
        return {"status": state.state, "review_age_s": None}
    if state.last_underwritten_at is None:
        return {"status": "STALE", "review_age_s": None,
                "reason": "never underwritten"}
    age = (pd.Timestamp(now)
           - pd.Timestamp(state.last_underwritten_at)).total_seconds()
    limit = HEARTBEAT_S.get(state.state, 300)
    return {"status": "STALE" if age > limit else "ACTIVE",
            "review_age_s": round(age, 1),
            "heartbeat_limit_s": limit,
            "data_age_s": data_age_s}


def reunderwrite(prior: OpportunityState, *, current_inputs: dict,
                 direction_quality: str, entry_quality: str,
                 reason: str = "", now=None) -> OpportunityState:
    """One re-underwrite, from CURRENT canonical inputs only.

    Note what this function cannot see: the prior judgment's support,
    objections, or text. It receives the prior STATE LABEL (to diff and
    to enforce terminality) and the prior INPUT SNAPSHOT (to compute
    what_changed). Conviction has no carry-over channel.
    """
    import pandas as pd
    now = pd.Timestamp(now) if now is not None else pd.Timestamp.now(tz="UTC")

    # terminal states stay dead: resurrection requires a NEW candidate id
    # (a new thesis lineage), never a state transition.
    if prior.state in TERMINAL:
        raise UnderwritingViolation(
            f"{prior.candidate_id} is {prior.state}; a dead thesis does "
            f"not resurrect — a new thesis gets a NEW candidate id")

    changes = what_changed(prior.inputs_snapshot, current_inputs)

    # terminal reasons kill regardless of how good anything else looks
    if reason in TERMINAL_REASONS:
        new_state = ("EXPIRED" if reason == "OPPORTUNITY_EXPIRED"
                     else "INVALIDATED")
    else:
        # the deterministic promotion/demotion lattice over the two axes
        dq, eq = direction_quality, entry_quality
        if dq == "STRONG" and eq in ("STRONG", "GOOD"):
            new_state = "SERIOUS"
        elif dq == "STRONG" and eq == "WEAK":
            new_state = "WAITING_FOR_ENTRY"
        elif dq in ("WEAK",) and prior.state in ("SERIOUS",
                                                 "WAITING_FOR_ENTRY",
                                                 "CAPITAL_REVIEW"):
            new_state = "DEGRADED"
        elif dq == "MODERATE":
            new_state = "DEVELOPING"
        elif prior.state == "DEGRADED" and dq == "STRONG":
            new_state = "DEVELOPING"          # improvement is a real path
        else:
            new_state = "WATCHING"

    out = OpportunityState(
        candidate_id=prior.candidate_id, symbol=prior.symbol,
        state=new_state, direction_quality=direction_quality,
        entry_quality=entry_quality, reason=reason,
        last_underwritten_at=str(now), inputs_snapshot=dict(current_inputs))

    rec = {"kind": "reunderwrite", "candidate_id": prior.candidate_id,
           "symbol": prior.symbol, "review_time": str(now),
           "previous_state": prior.state, "current_state": new_state,
           "what_changed": changes,
           "current_state_question": (
               "would we still care if first seen right now"),
           "direction_quality": direction_quality,
           "entry_quality": entry_quality, "reason": reason,
           "prior_referenced_as": "PRIOR_BELIEF_LABEL_ONLY",
           "decision_power": FRONTIER_POWER}
    import sys
    sys.path.insert(0, "scripts")
    from nightly_pull import _chain_append
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    _chain_append(LEDGER, rec)
    return out
