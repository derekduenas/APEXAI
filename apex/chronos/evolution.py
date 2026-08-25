"""HISTORICAL ONLINE LEARNING — the organism lives through time.

Not "train on the whole past simultaneously". The replay begins at T0
knowing only pre-T0 history; January resolves before February may know
it. Edges are BORN at specific moments, accumulate prospective-within-
replay evidence, weaken, get flagged, and retire -- and the record of
that lifeline is the product. The question CHRONOS exists to answer is
not "would this edge have made money" but:

    CAN THE ORGANISM LEARN, ADAPT, AND RETIRE EDGE
    WITHOUT SEEING THE FUTURE?

An EdgeLifeline is append-only. Every event carries the clock time at
which it was written and may only cite evidence knowable then. A
retirement explained by information from after the retirement decision
is a story, not a decision, and the lifeline refuses to record it.

decision_power: NONE_RESEARCH.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from apex.chronos import EVIDENCE_LABEL
from apex.chronos.clock import ChronosViolation, _parse

LIFELINE_EVENTS = ("BIRTH", "EVIDENCE", "STRENGTHENING", "WEAKENING",
                   "DECAY_FLAGGED", "REGIME_SHIFT_NOTED", "RETIRED",
                   "DESCENDANT_CREATED")

TERMINAL = ("RETIRED",)


@dataclass
class EdgeLifeline:
    edge_id: str
    born: str
    frozen_hash: str
    events: list = field(default_factory=list)

    def __post_init__(self):
        self.events.append({"event": "BIRTH", "at": self.born,
                            "frozen_hash": self.frozen_hash})

    @property
    def retired(self) -> bool:
        return any(e["event"] in TERMINAL for e in self.events)

    def record(self, *, event: str, at: str, evidence: str,
               evidence_known_from: str, detail: dict | None = None
               ) -> dict:
        """Append one lifeline event, causally checked.

        evidence_known_from must not postdate `at`: an event may only
        cite what was knowable when it was written."""
        if event not in LIFELINE_EVENTS:
            raise ChronosViolation(f"unknown lifeline event {event!r}")
        if event == "BIRTH":
            raise ChronosViolation("an edge is born once")
        if self.retired:
            raise ChronosViolation(
                f"{self.edge_id} is retired; a retired edge does not "
                f"accumulate events -- create a descendant instead")
        t = _parse(at)
        if t < _parse(self.events[-1]["at"]):
            raise ChronosViolation(
                "lifeline events must move forward in time")
        if _parse(evidence_known_from) > t:
            raise ChronosViolation(
                f"{event} at {at} cites evidence known from "
                f"{evidence_known_from} -- a decision explained by "
                f"information from after the decision is a story")
        rec = {"event": event, "at": at, "evidence": evidence,
               "evidence_known_from": evidence_known_from,
               "detail": detail or {},
               "evidence_label": EVIDENCE_LABEL}
        self.events.append(rec)
        return rec

    def as_record(self) -> dict:
        return {"kind": "edge_lifeline", "edge_id": self.edge_id,
                "born": self.born, "retired": self.retired,
                "n_events": len(self.events), "events": self.events,
                "decision_power": "NONE_RESEARCH"}


def grade_retirement_timing(lifeline: EdgeLifeline,
                            *, post_retirement_outcomes: list,
                            pre_retirement_outcomes: list) -> dict:
    """AFTER the replay: was the retirement decision good?

    This is the one place post-decision information is allowed --
    explicitly, as a grade of a sealed past decision, never as an
    input to one. The categories mirror the live system's law that
    outcome and decision quality are different things."""
    if not lifeline.retired:
        return {"kind": "retirement_grade", "edge_id": lifeline.edge_id,
                "verdict": "NOT_RETIRED"}
    post = [v for v in post_retirement_outcomes
            if isinstance(v, (int, float))]
    pre = [v for v in pre_retirement_outcomes
           if isinstance(v, (int, float))]
    if len(post) < 5 or len(pre) < 5:
        return {"kind": "retirement_grade", "edge_id": lifeline.edge_id,
                "verdict": "INSUFFICIENT_EVIDENCE",
                "n_pre": len(pre), "n_post": len(post)}
    import statistics
    pre_med, post_med = (statistics.median(pre),
                         statistics.median(post))
    flagged_first = any(e["event"] == "DECAY_FLAGGED"
                        for e in lifeline.events[:-1])
    if post_med < 0 and post_med < pre_med:
        verdict = ("TIMELY_RETIREMENT_AFTER_FLAG" if flagged_first
                   else "RIGHT_CALL_WITHOUT_WARNING_SYSTEM")
    elif post_med > 0:
        verdict = "RETIRED_A_LIVING_EDGE"
    else:
        verdict = "AMBIGUOUS"
    return {"kind": "retirement_grade", "edge_id": lifeline.edge_id,
            "verdict": verdict,
            "pre_median": round(pre_med, 4),
            "post_median": round(post_med, 4),
            "decay_was_flagged_first": flagged_first,
            "law": "post-decision information grades sealed decisions; "
                   "it never feeds them. RETIRED_A_LIVING_EDGE is a "
                   "real cost, not prudence -- refusal has a price and "
                   "the organism pays it in full view",
            "decision_power": "NONE_RESEARCH"}
