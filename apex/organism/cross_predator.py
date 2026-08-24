"""CROSS-PREDATOR CONTEXT — SHADOW faculty (V2 #4).

MISSION: let the three specialists share information without destroying
their specialization, and without the oldest error in multi-signal
systems: counting the same risk twice and calling it confirmation.

THE REDUNDANCY LAW IS THE WHOLE POINT. Long NVDA equity, long NVDA
calls, long QQQ and risk-on BTC look like four opinions; economically
they can be one concentrated risk-on bet wearing four costumes.
Agreement between correlated observers is not independent confirmation
-- it is the same observer echoing. So every cross-sleeve relation here
carries a redundancy tag, and the tag defaults to UNKNOWN, because
claiming independence we have not measured would be the exact
overcounting this faculty exists to prevent.

SHADOW ONLY. This module ASSEMBLES and OBSERVES. It emits no
confirmation score, no confidence, and nothing an incumbent Predator
reads. Its records accumulate so that, once prospective evidence
exists, we can ask whether cross-sleeve context would have added
information not explained by redundant exposure -- and only then seek
authority.

decision_power: NONE_SHADOW.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

NOT_ESTIMABLE = "NOT_ESTIMABLE"

REDUNDANCY = ("INDEPENDENT", "PARTIALLY_REDUNDANT", "HIGHLY_REDUNDANT",
              "UNKNOWN")

RELATIONS = ("CONFIRMS", "CONTRADICTS", "UNRELATED", NOT_ESTIMABLE)

# Pre-declared structural overlap map: which sleeve-subject pairs are
# KNOWN to share underlying risk by construction (an option on X and X
# itself are the same underlying by definition -- that much needs no
# statistics). Everything not listed stays UNKNOWN until measured.
STRUCTURAL_OVERLAP = {
    ("equity", "options"): "same underlying when subjects match; "
                           "index/sector beta otherwise unmeasured",
}


@dataclass(frozen=True)
class SleeveObservation:
    """One sleeve's view, quoted verbatim -- never reinterpreted."""
    sleeve: str                     # equity | options | btc
    subject: str
    T: str
    direction_view: str = NOT_ESTIMABLE     # LONG/SHORT/NONE/NOT_ESTIMABLE
    state_summary: dict = field(default_factory=dict)
    evidence_class: str = NOT_ESTIMABLE
    pedigree: str = NOT_ESTIMABLE


@dataclass(frozen=True)
class CrossRelation:
    a: str                          # "sleeve:subject"
    b: str
    relation: str
    redundancy: str
    why: tuple = ()
    law: str = ("agreement between correlated observers is not "
                "independent confirmation")


@dataclass(frozen=True)
class CrossPredatorContext:
    T: str
    observations: tuple = ()
    relations: tuple = ()
    shared_underlying_risks: tuple = ()
    confirmation_claims_permitted: bool = False
    calibration: str = "NONE_FITTED"
    evidence_class: str = "SHADOW_OBSERVATION"
    decision_power: str = "NONE_SHADOW"
    law: str = ("this context is assembled for later study; no "
                "incumbent Predator reads it, and no confidence "
                "adjustment is derived from it")

    def as_record(self) -> dict:
        return {"kind": "cross_predator_context", **asdict(self)}


def _same_underlying(x: SleeveObservation, y: SleeveObservation) -> bool:
    return x.subject.upper() == y.subject.upper()


def _relation(x: SleeveObservation, y: SleeveObservation
              ) -> CrossRelation:
    key_a, key_b = f"{x.sleeve}:{x.subject}", f"{y.sleeve}:{y.subject}"
    dx, dy = x.direction_view, y.direction_view

    if NOT_ESTIMABLE in (dx, dy) or "NONE" in (dx, dy):
        return CrossRelation(key_a, key_b, NOT_ESTIMABLE, "UNKNOWN",
                             ("at least one sleeve holds no directional "
                              "view; silence relates to nothing",))

    if _same_underlying(x, y):
        red = "HIGHLY_REDUNDANT"
        why = ("same underlying by construction -- these are one risk "
               "in two costumes, and their agreement is an echo, not "
               "evidence",)
    elif STRUCTURAL_OVERLAP.get(tuple(sorted((x.sleeve, y.sleeve)))):
        red = "PARTIALLY_REDUNDANT"
        why = (STRUCTURAL_OVERLAP[tuple(sorted((x.sleeve, y.sleeve)))],)
    else:
        red = "UNKNOWN"
        why = ("no measured correlation exists between these subjects; "
               "independence may not be assumed in either direction",)

    rel = "CONFIRMS" if dx == dy else "CONTRADICTS"
    return CrossRelation(key_a, key_b, rel, red, why)


def assemble(observations: list, *, T: str | None = None
             ) -> CrossPredatorContext:
    """Assemble one shadow context. Observes; never scores."""
    T = T or datetime.now(timezone.utc).isoformat()
    obs = tuple(observations)
    relations = []
    shared = []
    for i in range(len(obs)):
        for j in range(i + 1, len(obs)):
            r = _relation(obs[i], obs[j])
            relations.append(r)
            if r.redundancy == "HIGHLY_REDUNDANT":
                shared.append((r.a, r.b))
    return CrossPredatorContext(
        T=T, observations=obs, relations=tuple(relations),
        shared_underlying_risks=tuple(shared))
