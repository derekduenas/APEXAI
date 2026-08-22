"""Re-underwrite ledger — the durable record that makes
"Captain looked and nothing had changed" distinguishable from
"Captain was never called."

Before 2026-08-18 only the second case was observable, and only by
noticing an ABSENCE of rows -- which is exactly why the session-long
Captain freeze went unnoticed until end-of-day forensics. Every review
now writes a row whether or not the state changed:

  CAPTAIN_REVIEW        -- Captain was asked; state may or may not have moved
  CAPTAIN_STATE_CHANGE  -- Captain was asked AND the state actually moved

decision_power = NONE_FRONTIER_SHADOW. This records; it authorizes
nothing.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from apex.frontier2 import FRONTIER2_POWER

LEDGER = Path("results/frontier2/reunderwrite_ledger.jsonl")

RECORD_KINDS = ("CAPTAIN_REVIEW", "CAPTAIN_STATE_CHANGE")


class ReunderwriteLedgerError(RuntimeError):
    pass


@dataclass(frozen=True)
class ReunderwriteRecord:
    record_kind: str
    candidate_id: str
    subject: str
    review_number: int
    review_time: str
    trigger: tuple

    previous_captain_state: str | None
    current_captain_state: str

    changed_inputs: tuple
    unchanged_inputs: tuple

    current_curve: str | None
    current_ev: str | None
    current_pressure: str | None
    current_propagation: str | None
    current_assassin: str | None
    current_system_cognition: str | None

    support: tuple
    objections: tuple

    direction_quality: str
    transition_quality: str
    entry_quality: str
    data_quality: str

    assassin_refreshed: bool
    known_from: str
    artifact_refs: tuple

    # ---- DECISION ADAPTATION LATENCY (Phase 1.1, operator request) ----
    # The chain from "upstream state materially changed" to "Captain's
    # state actually moved". Recorded as explicit timestamps rather than
    # left to a cross-ledger join, so tomorrow's forensics can measure
    # adaptation latency directly. None where a leg did not occur (e.g.
    # no Assassin refresh, or a review that changed nothing).
    upstream_event_time: str | None = None
    assassin_review_time: str | None = None
    state_change_time: str | None = None
    decision_power: str = FRONTIER2_POWER

    def adaptation_latency_s(self) -> dict:
        """Derived, never stored: seconds from the upstream material
        event to each downstream step. A leg with a missing timestamp
        reports None rather than a guessed zero."""
        import pandas as pd

        def _d(a, b):
            if a is None or b is None:
                return None
            return round((pd.Timestamp(b) - pd.Timestamp(a)).total_seconds(), 3)

        out = {
            "upstream_to_assassin_s": _d(self.upstream_event_time,
                                         self.assassin_review_time),
            "upstream_to_captain_review_s": _d(self.upstream_event_time,
                                               self.review_time),
            "upstream_to_state_change_s": _d(self.upstream_event_time,
                                             self.state_change_time),
            "assassin_to_captain_s": _d(self.assassin_review_time,
                                        self.review_time),
        }
        # A NEGATIVE latency is not a fast system -- it means the runtime
        # reasoned over a bar stamped AHEAD of its own clock (clock skew,
        # a future-stamped feed, or a replay whose `now` precedes the
        # data). Flag it rather than let a nonsense number be averaged
        # into a "decision adaptation latency" statistic tomorrow.
        negatives = [k for k, v in out.items() if v is not None and v < 0]
        out["integrity"] = ("NEGATIVE_LATENCY_UPSTREAM_AHEAD_OF_CLOCK"
                            if negatives else "OK")
        out["negative_legs"] = negatives
        return out

    def __post_init__(self):
        if self.record_kind not in RECORD_KINDS:
            raise ReunderwriteLedgerError(f"unknown record_kind {self.record_kind!r}")
        if self.review_number < 1:
            raise ReunderwriteLedgerError("review_number starts at 1")
        state_moved = self.previous_captain_state != self.current_captain_state
        if self.record_kind == "CAPTAIN_STATE_CHANGE" and not state_moved:
            raise ReunderwriteLedgerError(
                "CAPTAIN_STATE_CHANGE requires the state to have actually moved")
        if self.record_kind == "CAPTAIN_REVIEW" and state_moved:
            raise ReunderwriteLedgerError(
                "a state that moved must be recorded as CAPTAIN_STATE_CHANGE")

    def as_record(self) -> dict:
        return {"kind": "frontier2_reunderwrite_record", **asdict(self),
               "adaptation_latency_s": self.adaptation_latency_s()}


def record(*, candidate_id: str, subject: str, review_number: int,
           review_time, trigger: tuple, previous_captain_state: str | None,
           current_captain_state: str, changed_inputs: tuple,
           unchanged_inputs: tuple, current_curve: str | None = None,
           current_ev: str | None = None, current_pressure: str | None = None,
           current_propagation: str | None = None,
           current_assassin: str | None = None,
           current_system_cognition: str | None = None,
           support: tuple = (), objections: tuple = (),
           direction_quality: str = "UNKNOWN",
           transition_quality: str = "UNKNOWN",
           entry_quality: str = "UNKNOWN", data_quality: str = "UNKNOWN",
           assassin_refreshed: bool = False, known_from,
           artifact_refs: tuple = (), upstream_event_time=None,
           assassin_review_time=None) -> ReunderwriteRecord:
    import pandas as pd
    moved = previous_captain_state != current_captain_state
    rec = ReunderwriteRecord(
        record_kind=("CAPTAIN_STATE_CHANGE" if moved else "CAPTAIN_REVIEW"),
        candidate_id=candidate_id, subject=subject, review_number=review_number,
        review_time=str(pd.Timestamp(review_time)), trigger=tuple(trigger),
        previous_captain_state=previous_captain_state,
        current_captain_state=current_captain_state,
        changed_inputs=tuple(changed_inputs), unchanged_inputs=tuple(unchanged_inputs),
        current_curve=current_curve, current_ev=current_ev,
        current_pressure=current_pressure, current_propagation=current_propagation,
        current_assassin=current_assassin,
        current_system_cognition=current_system_cognition,
        support=tuple(support), objections=tuple(objections),
        direction_quality=direction_quality, transition_quality=transition_quality,
        entry_quality=entry_quality, data_quality=data_quality,
        assassin_refreshed=assassin_refreshed,
        known_from=str(pd.Timestamp(known_from)), artifact_refs=tuple(artifact_refs),
        upstream_event_time=(str(pd.Timestamp(upstream_event_time))
                             if upstream_event_time is not None else None),
        assassin_review_time=(str(pd.Timestamp(assassin_review_time))
                              if assassin_review_time is not None else None),
        # the state-change instant IS the review instant when the state
        # moved; None when this review changed nothing.
        state_change_time=(str(pd.Timestamp(review_time)) if moved else None))
    return rec


def persist(rec: ReunderwriteRecord) -> dict:
    import sys
    sys.path.insert(0, "scripts")
    from nightly_pull import _chain_append
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    return _chain_append(LEDGER, rec.as_record())


def review_counts_by_subject(path: Path | None = None) -> dict:
    """Forensics helper: {subject: {"reviews": n, "state_changes": m}}."""
    import json
    p = path or LEDGER
    if not p.exists():
        return {}
    out: dict = {}
    for line in p.read_text().splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        s = out.setdefault(r.get("subject"), {"reviews": 0, "state_changes": 0})
        s["reviews"] += 1
        if r.get("record_kind") == "CAPTAIN_STATE_CHANGE":
            s["state_changes"] += 1
    return out
