"""LeadingEdgeMap — F5: conditional on an emerging transition, which
instruments appear to be expressing it earliest or most cleanly?

NOT another Opportunity Board (that is F10's job, later, over the whole
candidate lifecycle). This is a narrow, single-purpose competition: rank
a set of candidates ALREADY believed relevant to one named transition,
using a deterministic lexicographic key over categorical states from
Curve, Propagation, RS, sector alignment, trend, participant pressure,
expectation violation, liquidity and entry geometry -- exactly the same
"no fitted weights, UNKNOWN always sorts worst" discipline
apex.frontier.senses.rank_opportunities() uses, reimplemented here
independently (this package may not import apex.frontier).

RANKING CONVENTION (a choice, not a law -- documented because the
operator's directive left it open): CONFIRMED_EXPRESSION ranks above
EARLY_EXPRESSION for "cleanest" current expression of the transition;
`first_elevated_at` is an OPTIONAL secondary tie-break so that, among
equally-clean candidates, the one that started expressing the
transition earliest still wins the "earliest" half of the question.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from apex.frontier2 import FRONTIER2_POWER

LEDGER = Path("results/frontier2/leading_edge_map_ledger.jsonl")

RANK_ORDER = ("data_quality", "curve_expression", "propagation_position",
             "rs_velocity_quality", "sector_alignment", "trend_quality",
             "participant_pressure_potential", "expectation_violation",
             "liquidity", "entry_geometry")

# lexicographic value maps: LOWER sorts FIRST (better). UNKNOWN is
# always the worst value in its dimension so missingness can never
# outrank knowledge -- same law as rank_opportunities().
_VAL = {
    "data_quality": {"FULL": 0, "PARTIAL": 1, "LIMITED": 2, "UNKNOWN": 9},
    "curve_expression": {"CONFIRMED_EXPRESSION": 0, "EARLY_EXPRESSION": 1,
                         "NO_EXPRESSION": 2, "UNKNOWN": 9},
    "propagation_position": {"PROPAGATED": 0, "PROPAGATING": 1,
                             "NOT_YET_PROPAGATED": 2, "STALLED": 3, "UNKNOWN": 9},
    "rs_velocity_quality": {"STRONG": 0, "MODERATE": 1, "WEAK": 2, "UNKNOWN": 9},
    "sector_alignment": {"ALIGNED": 0, "MIXED": 1, "CONFLICTED": 2, "UNKNOWN": 9},
    "trend_quality": {"STRONG": 0, "MODERATE": 1, "WEAK": 2, "UNKNOWN": 9},
    "participant_pressure_potential": {"HIGH": 0, "MODERATE": 1, "LOW": 2,
                                       "NONE": 3, "UNKNOWN": 9},
    "expectation_violation": {"OBSERVABLE_VIOLATION": 0, "NO_VIOLATION": 1,
                              "INSUFFICIENT_CONTEXT": 2,
                              "NO_EXPECTATION_MODEL": 2, "UNKNOWN": 9},
    "liquidity": {"HEALTHY": 0, "THIN": 1, "UNKNOWN": 9},
    "entry_geometry": {"GOOD": 0, "ACCEPTABLE": 1, "POOR": 2, "UNKNOWN": 9},
}

_BEST_VALUE = {d: min(m, key=m.get) for d, m in _VAL.items()}


class LeadingEdgeMapError(RuntimeError):
    pass


@dataclass(frozen=True)
class LeadingEdgeRow:
    rank: int
    symbol: str
    transition: str
    supporting_dimensions: tuple
    contradictions: tuple
    leading_edge_reason: str
    direction_quality: str
    entry_quality: str
    data_quality: str
    coverage: str
    dimensions: dict
    known_from: str
    decision_power: str = FRONTIER2_POWER

    def as_record(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class LeadingEdgeMap:
    transition: str
    as_of: str
    known_from: str
    rows: tuple
    n_candidates: int
    rank_order: tuple = RANK_ORDER
    decision_power: str = FRONTIER2_POWER

    def as_record(self) -> dict:
        return {"kind": "leading_edge_map",
               "transition": self.transition, "as_of": self.as_of,
               "known_from": self.known_from,
               "rows": [r for r in self.rows], "n_candidates": self.n_candidates,
               "rank_order": list(self.rank_order),
               "decision_power": self.decision_power}


def _direction_quality(c: dict) -> str:
    strong, total = 0, 0
    for dim, best in (("curve_expression", "CONFIRMED_EXPRESSION"),
                      ("trend_quality", "STRONG"),
                      ("propagation_position", "PROPAGATED")):
        v = c.get(dim, "UNKNOWN")
        if v == "UNKNOWN":
            continue
        total += 1
        if v == best:
            strong += 1
    if total == 0:
        return "UNKNOWN"
    frac = strong / total
    return "STRONG" if frac >= 0.66 else "MODERATE" if frac >= 0.33 else "WEAK"


def _reason(c: dict, supporting: tuple) -> str:
    if not supporting:
        return "no supporting dimension currently confirmed"
    return "confirmed: " + ", ".join(supporting)


def rank(transition: str, candidates: list, *, known_from, now
        ) -> LeadingEdgeMap:
    """`candidates`: [{"symbol", + any RANK_ORDER dims, "entry_geometry",
    "first_elevated_at" (ISO str, optional), "contradictions" (tuple,
    optional)}, ...]. Missing dims read UNKNOWN, never a fabricated
    default value."""
    import pandas as pd
    now = pd.Timestamp(now)

    def sort_key(c):
        primary = tuple(_VAL[d].get(str(c.get(d, "UNKNOWN")), 9)
                        for d in RANK_ORDER)
        fe = c.get("first_elevated_at")
        tie = pd.Timestamp(fe).value if fe else float("inf")
        return primary + (tie, str(c.get("symbol", "")))

    ordered = sorted(candidates, key=sort_key)
    rows = []
    for i, c in enumerate(ordered):
        supporting = tuple(d for d in RANK_ORDER
                           if str(c.get(d, "UNKNOWN")) == _BEST_VALUE[d])
        dims = {d: str(c.get(d, "UNKNOWN")) for d in RANK_ORDER}
        n_known = sum(1 for d in RANK_ORDER if c.get(d, "UNKNOWN") != "UNKNOWN")
        row = LeadingEdgeRow(
            rank=i + 1, symbol=c.get("symbol", "?"), transition=transition,
            supporting_dimensions=supporting,
            contradictions=tuple(c.get("contradictions", ())),
            leading_edge_reason=_reason(c, supporting),
            direction_quality=_direction_quality(c),
            entry_quality=str(c.get("entry_geometry", "UNKNOWN")),
            data_quality=str(c.get("data_quality", "UNKNOWN")),
            coverage=f"{n_known}/{len(RANK_ORDER)} dimensions known",
            dimensions=dims, known_from=str(pd.Timestamp(known_from)))
        rows.append(row.as_record())

    return LeadingEdgeMap(transition=transition, as_of=str(now),
                          known_from=str(pd.Timestamp(known_from)),
                          rows=tuple(rows), n_candidates=len(rows))


def persist(lem: LeadingEdgeMap) -> dict:
    from apex.governance.chain_ledger import chain_append as _chain_append
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    return _chain_append(LEDGER, lem.as_record())
