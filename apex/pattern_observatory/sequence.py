"""SEQUENCE ENGINE -- markets unfold in order.

A conjunction says five things are true at once. A SEQUENCE says they
became true in an order, and that the order itself is the information:

    T-90  positioning reaches an extreme
    T-45  sector leadership deteriorates
    T-25  breadth weakens
    T-15  curve rolls
    T-10  options skew reprices
    T-5   liquidity thins
    T0    break

DELIBERATELY PERMISSIVE IN V1. The engine does NOT require exact
timestamps or a strict order, because requiring either before we have
observed a single real sequence would encode a guess as a law. It records
the order it actually saw, tracks which declared steps have completed,
and learns the observed timing distribution. Strictness can be earned
later from evidence; it cannot be assumed now.

A sequence that BREAKS or REVERSES is retained, not deleted. Failed
sequences are the control group.

decision_power: NONE_PATTERN_OBSERVATORY.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from apex.pattern_observatory import OBSERVATORY_POWER

FORMING, ADVANCING, STALLED, COMPLETED, BROKEN, REVERSED = (
    "FORMING", "ADVANCING", "STALLED", "COMPLETED", "BROKEN", "REVERSED")
STATES = (FORMING, ADVANCING, STALLED, COMPLETED, BROKEN, REVERSED)

STALL_AFTER_S = 1800.0


@dataclass(frozen=True)
class SequenceStep:
    name: str
    observed_at: str | None
    seconds_from_start: float | None
    order_observed: int | None


@dataclass(frozen=True)
class PatternSequenceState:
    sequence_id: str
    family_id: str
    subject: str
    market: str
    declared_steps: tuple
    steps: tuple
    current_step: str | None
    completion_fraction: float
    expected_next_step: str | None
    observed_order: tuple
    order_matches_declared: bool | None
    time_between_steps: dict
    time_to_completion_s: float | None
    state: str
    started_at: str
    last_updated: str
    known_from: str
    reasoning: tuple = ()

    def as_dict(self) -> dict:
        return {"kind": "pattern_sequence_state", **self.__dict__,
                "declared_steps": list(self.declared_steps),
                "steps": [s.__dict__ for s in self.steps],
                "observed_order": list(self.observed_order),
                "time_between_steps": dict(self.time_between_steps),
                "reasoning": list(self.reasoning),
                "order_is_learned_not_required": True,
                "decision_power": OBSERVATORY_POWER}


class SequenceEngine:
    def __init__(self):
        self._seq: dict = {}

    def observe(self, *, sequence_id: str, family_id: str, subject: str,
                market: str, declared_steps: tuple, active_steps: set,
                now, known_from) -> PatternSequenceState:
        import pandas as pd
        ts = pd.Timestamp(now)
        rec = self._seq.get(sequence_id)
        if rec is None:
            rec = {"started_at": ts, "seen": {}, "order": [],
                   "state": FORMING, "reversals": 0}
            self._seq[sequence_id] = rec

        for step in declared_steps:
            if step in active_steps and step not in rec["seen"]:
                rec["seen"][step] = ts
                rec["order"].append(step)

        # a step that had fired and is no longer true = a reversal, kept
        regressed = [s for s in list(rec["seen"])
                     if s not in active_steps and s == (rec["order"][-1]
                                                        if rec["order"] else None)]
        if regressed:
            rec["reversals"] += 1

        steps = tuple(
            SequenceStep(
                name=s,
                observed_at=(str(rec["seen"][s]) if s in rec["seen"] else None),
                seconds_from_start=((rec["seen"][s] - rec["started_at"]).total_seconds()
                                    if s in rec["seen"] else None),
                order_observed=(rec["order"].index(s) + 1 if s in rec["order"]
                                else None))
            for s in declared_steps)

        done = [s for s in declared_steps if s in rec["seen"]]
        frac = len(done) / len(declared_steps) if declared_steps else 0.0
        remaining = [s for s in declared_steps if s not in rec["seen"]]
        current = rec["order"][-1] if rec["order"] else None
        # "expected next" must not point BACKWARDS. Steps declared before
        # the furthest one already observed were skipped, not pending --
        # report the first unseen step AFTER the high-water mark, and fall
        # back to any unseen step only if the sequence ran past the end.
        if current is not None:
            hw = max(declared_steps.index(s) for s in rec["seen"])
            ahead = [s for s in declared_steps[hw + 1:] if s not in rec["seen"]]
            skipped = [s for s in declared_steps[:hw] if s not in rec["seen"]]
        else:
            ahead, skipped = remaining, []

        gaps = {}
        for i in range(1, len(rec["order"])):
            a, b = rec["order"][i - 1], rec["order"][i]
            gaps[f"{a}->{b}"] = (rec["seen"][b] - rec["seen"][a]).total_seconds()

        order_match = None
        if len(rec["order"]) >= 2:
            declared_pos = {s: i for i, s in enumerate(declared_steps)}
            order_match = all(
                declared_pos[rec["order"][i - 1]] < declared_pos[rec["order"][i]]
                for i in range(1, len(rec["order"])))

        reasoning = []
        if frac >= 1.0:
            state = COMPLETED
        elif rec["reversals"] >= 2:
            state = REVERSED
            reasoning.append(f"{rec['reversals']} step reversals observed")
        elif rec["order"]:
            idle = (ts - rec["seen"][rec["order"][-1]]).total_seconds()
            state = STALLED if idle > STALL_AFTER_S else ADVANCING
            if state == STALLED:
                reasoning.append(f"no new step for {idle:.0f}s")
        else:
            state = FORMING
        if skipped:
            reasoning.append(f"steps skipped, not pending: {skipped}")
        if order_match is False:
            reasoning.append("observed order differs from the declared "
                             "order -- recorded, not penalised")
        rec["state"] = state

        return PatternSequenceState(
            sequence_id=sequence_id, family_id=family_id, subject=subject,
            market=market, declared_steps=declared_steps, steps=steps,
            current_step=current, completion_fraction=frac,
            expected_next_step=(ahead[0] if ahead else None),
            observed_order=tuple(rec["order"]),
            order_matches_declared=order_match, time_between_steps=gaps,
            time_to_completion_s=((ts - rec["started_at"]).total_seconds()
                                  if state == COMPLETED else None),
            state=state, started_at=str(rec["started_at"]),
            last_updated=str(ts), known_from=str(known_from),
            reasoning=tuple(reasoning))
