"""COMPETING HYPOTHESIS ENGINE + DISAGREEMENT RECORD.

A market state is not a story. Collapsing observation into one
narrative is how systems become confidently wrong, so EdgeForge holds
several explanations of the same state simultaneously and PRESERVES the
disagreement -- disagreement is itself researchable, and the future
Frontier Discovery engine may find that specific disagreement
structures carry predictive content.

Two refusals define the contract:

    A hypothesis without falsifiers is not a hypothesis. It cannot be
    wrong, so it cannot be knowledge.

    No calibrated probabilities. Statuses are ordinal (SUPPORTED /
    PLAUSIBLE / WEAK / CONTRADICTED / NOT_ESTIMABLE) because no outcome
    data links these statuses to anything yet, and a number would be
    invented -- the same law the participant-state and calibration
    faculties already live under.

The tournament refuses to average. "60% accumulation, 40% covering" is
a single narrative wearing arithmetic; the honest object is BOTH
hypotheses, each with its own falsifiers, racing forward evidence.

decision_power: NONE_RESEARCH.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

NOT_ESTIMABLE = "NOT_ESTIMABLE"

HYPOTHESIS_STATUSES = ("SUPPORTED", "PLAUSIBLE", "WEAK", "CONTRADICTED",
                       NOT_ESTIMABLE)

REDUNDANCY = ("INDEPENDENT", "PARTIALLY_REDUNDANT", "HIGHLY_REDUNDANT",
              "UNKNOWN")


class HypothesisViolation(RuntimeError):
    pass


@dataclass(frozen=True)
class MarketHypothesis:
    hypothesis_id: str
    birth_time: str
    mechanism: str
    participants: tuple = ()
    supporting_evidence: tuple = ()
    contradicting_evidence: tuple = ()
    competing_explanations: tuple = ()
    falsifiers: tuple = ()
    expected_path_characteristics: tuple = ()
    expected_liquidity_behavior: str = NOT_ESTIMABLE
    expected_volatility_behavior: str = NOT_ESTIMABLE
    expected_cross_market_behavior: str = NOT_ESTIMABLE
    pedigree: str = "AUTHORED_UNVALIDATED"
    status: str = "PLAUSIBLE"
    calibration: str = "NONE_FITTED"
    decision_power: str = "NONE_RESEARCH"

    def __post_init__(self):
        if self.status not in HYPOTHESIS_STATUSES:
            raise HypothesisViolation(
                f"unknown status {self.status!r}")
        if not self.falsifiers:
            raise HypothesisViolation(
                f"{self.hypothesis_id}: a hypothesis without falsifiers "
                f"cannot be wrong, and therefore cannot be knowledge")
        for banned in ("probability", "confidence", "p="):
            for f_ in (self.supporting_evidence
                       + self.contradicting_evidence):
                if banned in str(f_).lower() and any(
                        ch.isdigit() for ch in str(f_)):
                    raise HypothesisViolation(
                        f"{self.hypothesis_id}: evidence may not smuggle "
                        f"a numeric {banned!r} -- statuses are ordinal "
                        f"until calibration exists")

    def as_record(self) -> dict:
        return {"kind": "market_hypothesis", **asdict(self)}


@dataclass
class HypothesisTournament:
    """Several explanations of ONE state, held apart on purpose."""
    state_hash: str
    hypotheses: list = field(default_factory=list)
    law: str = ("disagreement is preserved, never averaged into one "
                "narrative; its existence is itself researchable")

    def enter(self, h: MarketHypothesis) -> None:
        if any(x.hypothesis_id == h.hypothesis_id for x in self.hypotheses):
            raise HypothesisViolation(
                f"{h.hypothesis_id} already entered")
        self.hypotheses.append(h)

    def standings(self) -> dict:
        if len(self.hypotheses) < 2:
            note = ("SINGLE_NARRATIVE_WARNING: one hypothesis is a "
                    "story, not a tournament")
        else:
            note = "OK"
        return {"kind": "hypothesis_tournament",
                "state_hash": self.state_hash,
                "n_hypotheses": len(self.hypotheses),
                "statuses": {h.hypothesis_id: h.status
                             for h in self.hypotheses},
                "live_disagreement": len({h.mechanism
                                          for h in self.hypotheses}) > 1,
                "note": note, "law": self.law,
                "decision_power": "NONE_RESEARCH"}

    def average(self, *_a, **_k):
        raise HypothesisViolation(
            "averaging hypotheses into one narrative is refused by "
            "construction -- hold the disagreement")


@dataclass(frozen=True)
class DisagreementState:
    """Two faculties, one market, different readings -- recorded as a
    first-class object with its redundancy named, because agreement
    between correlated observers is an echo and disagreement between
    them may be information."""
    state_hash: str
    faculty_a: str
    reading_a: str
    faculty_b: str
    reading_b: str
    inputs_redundancy: str = "UNKNOWN"
    why: tuple = ()
    conclusion: str = "NONE_RECORDED"
    law: str = ("no conclusion is drawn here; whether this disagreement "
                "structure carries edge is a future Frontier Discovery "
                "question")
    decision_power: str = "NONE_RESEARCH"

    def __post_init__(self):
        if self.inputs_redundancy not in REDUNDANCY:
            raise HypothesisViolation(
                f"redundancy {self.inputs_redundancy!r} is not declared")
        if self.conclusion != "NONE_RECORDED":
            raise HypothesisViolation(
                "a DisagreementState records disagreement; it may not "
                "carry a conclusion")

    def as_record(self) -> dict:
        return {"kind": "disagreement_state", **asdict(self)}
