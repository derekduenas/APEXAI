"""DECISION BOUNDARY ARCHAEOLOGY — how close was this to flipping?

A verdict of GOOD tells you almost nothing on its own. A state one
hundredth of an ATR inside the boundary and a state deep in the
interior both print GOOD, and they are entirely different animals:

    BARELY INSIDE   the verdict is a coin balanced on its edge, so
                    threshold placement and measurement noise become
                    priority hypotheses.
    DEEP INSIDE     the verdict was not marginal, so simple threshold
                    placement is unlikely to explain it -- which does
                    NOT identify the cause. A non-marginal decision
                    that ended badly still admits a noisy feature, a
                    wrong threshold family, a misspecified interaction,
                    rapid state drift, regime conditionality, a missing
                    variable, or ordinary stochastic loss.

The map narrows the search; it never closes it. Diagnosing causality
from proximity alone would be precisely the premature certainty this
engine exists to refuse. That said, the distinction is invisible to any
funnel recording only labels, and it is what separates "we placed the
line wrong" from "we are looking at the market through an incomplete
representation" -- two problems with completely different remedies.

NEVER A SCALAR. Distances are reported PER DIMENSION. Collapsing
"distance to the WAIT boundary" into one number would average an ATR of
chase headroom against a fraction of invalidation slack and produce a
figure describing nothing.

THRESHOLDS ARE IMPORTED, NEVER RESTATED. Every boundary here is read
from the incumbent faculty's own pre-declared constants. A copy would
drift, and then the archaeology would be measuring a boundary the
Predator does not actually use.

decision_power: NONE_RESEARCH -- measures the incumbent, never moves it.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

# THE incumbent's own constants. Imported so a threshold change over
# there can never silently invalidate the measurements over here.
from apex.predators.equities.attack_geometry import (
    CHASE_HIGH_ATR, CHASE_LOW_ATR, CHASE_MODERATE_ATR,
    INVALIDATION_GOOD_ATR, INVALIDATION_POOR_ATR)

NOT_ESTIMABLE = "NOT_ESTIMABLE"

PROXIMITY = ("KNIFE_EDGE", "NEAR_BOUNDARY", "INTERIOR", "UNKNOWN")

# THE ONTOLOGY GENERATES HYPOTHESES; IT DOES NOT DIAGNOSE CAUSALITY.
# An earlier draft read INTERIOR as "therefore a missing state
# variable", which is too strong: a non-marginal decision that ended
# badly has at least six live explanations, and naming one of them the
# answer would be exactly the premature causal claim this engine exists
# to refuse.
PROXIMITY_MEANING = {
    "KNIFE_EDGE": {
        "statement": "the decision is highly sensitive to the incumbent "
                     "threshold",
        "priority_hypotheses": (
            "threshold placement",
            "measurement noise in the boundary dimension")},
    "NEAR_BOUNDARY": {
        "statement": "the decision is moderately sensitive to the "
                     "incumbent threshold",
        "priority_hypotheses": (
            "threshold placement",
            "measurement noise",
            "state drift between observation and action")},
    "INTERIOR": {
        "statement": "the decision was NOT marginal under the incumbent "
                     "rule, so simple threshold placement alone is "
                     "unlikely to explain it",
        "priority_hypotheses": (
            "the incumbent feature is itself noisy or poorly measured",
            "the threshold FAMILY is wrong even far from this boundary",
            "the interaction/function between dimensions is misspecified",
            "the state changed rapidly after the frozen observation",
            "the rule is valid only conditionally on another regime",
            "a missing state variable the representation never saw",
            "ordinary stochastic loss despite a genuinely favorable "
            "state")},
    "UNKNOWN": {
        "statement": "required boundary inputs were not prospectively "
                     "recorded, or are insufficiently reliable",
        "priority_hypotheses": (
            "nothing may be inferred; this is a measurement gap",)},
}

# Inputs may only found a proximity classification if they were
# RECORDED AT DECISION TIME. Reconstructing them after the outcome is
# known is where discovery quietly becomes hindsight.
ACCEPTABLE_INPUT_PEDIGREE = ("PROSPECTIVELY_RECORDED",)
UNRECORDED_REASON = "REQUIRED_PROSPECTIVE_INPUTS_NOT_RECORDED"

# REPORTING_PRIOR (declared, not learned): fraction of the band's own
# width within which a state counts as sitting on its edge.
KNIFE_EDGE_FRACTION = 0.10
NEAR_BOUNDARY_FRACTION = 0.30
PROXIMITY_RULE_CLASSIFICATION = "REPORTING_PRIOR"


class BoundaryViolation(RuntimeError):
    pass


@dataclass(frozen=True)
class DimensionDistance:
    """One dimension's headroom to the verdict flipping."""
    dimension: str
    value: float | str
    band: tuple                      # (lower, upper) of the current band
    distance_to_worse: float | str   # toward a weaker verdict
    distance_to_better: float | str  # toward a stronger verdict
    band_fraction_used: float | str
    proximity: str
    boundary_source: str
    note: str = ""

    def as_record(self) -> dict:
        return asdict(self)


def _classify(frac) -> str:
    if not isinstance(frac, (int, float)):
        return "UNKNOWN"
    edge = min(frac, 1.0 - frac)
    if edge <= KNIFE_EDGE_FRACTION:
        return "KNIFE_EDGE"
    if edge <= NEAR_BOUNDARY_FRACTION:
        return "NEAR_BOUNDARY"
    return "INTERIOR"


def _banded(dimension, value, edges, labels, source, note=""):
    """Locate `value` in a pre-declared banded scale and measure the
    headroom to each side in the value's own units."""
    if not isinstance(value, (int, float)):
        return DimensionDistance(
            dimension=dimension, value=NOT_ESTIMABLE, band=(),
            distance_to_worse=NOT_ESTIMABLE,
            distance_to_better=NOT_ESTIMABLE,
            band_fraction_used=NOT_ESTIMABLE, proximity="UNKNOWN",
            boundary_source=source,
            note="value not estimable; no distance is invented")
    lo = float("-inf")
    for i, e in enumerate(edges):
        if value <= e:
            hi = e
            break
        lo = e
    else:
        hi = float("inf")
    width = (hi - lo) if (hi != float("inf") and lo != float("-inf")) \
        else None
    frac = ((value - lo) / width) if width else NOT_ESTIMABLE
    return DimensionDistance(
        dimension=dimension, value=round(value, 4),
        band=(lo if lo != float("-inf") else "-inf",
              hi if hi != float("inf") else "+inf"),
        distance_to_worse=(round(hi - value, 4)
                           if hi != float("inf") else NOT_ESTIMABLE),
        distance_to_better=(round(value - lo, 4)
                            if lo != float("-inf") else NOT_ESTIMABLE),
        band_fraction_used=(round(frac, 4)
                            if isinstance(frac, float) else frac),
        proximity=_classify(frac), boundary_source=source, note=note)


@dataclass(frozen=True)
class DecisionBoundaryMap:
    subject: str
    T: str
    verdict: str
    cohort: str
    dimensions: tuple
    overall_proximity: str
    interpretation: str
    candidate_hypotheses: tuple = ()
    unknown_reason: str | None = None
    law: str = ("distances are per dimension and never collapsed; "
                "thresholds are imported from the incumbent, never "
                "restated; proximity GENERATES hypotheses and never "
                "diagnoses causality")
    proximity_rule: str = PROXIMITY_RULE_CLASSIFICATION
    decision_power: str = "NONE_RESEARCH"

    def as_record(self) -> dict:
        return {"kind": "decision_boundary_map", **asdict(self),
                "dimensions": [d.as_record() for d in self.dimensions]}


def map_equity_decision(*, subject: str, T: str, verdict: str,
                        cohort: str, extension_atr, invalidation_atr,
                        extras: dict | None = None,
                        input_pedigree: str = "PROSPECTIVELY_RECORDED"
                        ) -> DecisionBoundaryMap:
    """Reconstruct how close an equity-geometry verdict was to flipping.

    `extras` accepts additional pre-declared banded dimensions as
    {name: (value, edges, source, note)} so the map can widen as the
    faculty does -- without this module inventing bands of its own."""
    # THE ANTI-RECONSTRUCTION GUARD. Values derived after the outcome
    # was known cannot found a proximity claim, however technically
    # computable they are -- once the research system reconstructs
    # whatever it needs after seeing results, the line between
    # discovery and hindsight is gone.
    if input_pedigree not in ACCEPTABLE_INPUT_PEDIGREE:
        return DecisionBoundaryMap(
            subject=subject, T=T, verdict=verdict, cohort=cohort,
            dimensions=(), overall_proximity="UNKNOWN",
            unknown_reason=UNRECORDED_REASON,
            interpretation=(
                f"input_pedigree={input_pedigree!r}: "
                + PROXIMITY_MEANING["UNKNOWN"]["statement"]),
            candidate_hypotheses=PROXIMITY_MEANING["UNKNOWN"][
                "priority_hypotheses"])

    dims = [
        _banded("extension_atr (chase)", extension_atr,
                [CHASE_LOW_ATR, CHASE_MODERATE_ATR, CHASE_HIGH_ATR],
                ("LOW", "MODERATE", "HIGH", "EXTREME"),
                "equities.attack_geometry.CHASE_*_ATR",
                "chase forbids attack at HIGH/EXTREME"),
        _banded("invalidation_distance_atr", invalidation_atr,
                [INVALIDATION_GOOD_ATR, INVALIDATION_POOR_ATR],
                ("GOOD", "ACCEPTABLE", "POOR"),
                "equities.attack_geometry.INVALIDATION_*_ATR",
                "beyond POOR, risk cannot be bounded"),
    ]
    for name, spec in (extras or {}).items():
        value, edges, source, note = spec
        dims.append(_banded(name, value, edges, (), source, note))

    proxes = [d.proximity for d in dims if d.proximity != "UNKNOWN"]
    if not proxes:
        overall, reason = "UNKNOWN", UNRECORDED_REASON
    elif "KNIFE_EDGE" in proxes:
        overall, reason = "KNIFE_EDGE", None
    elif "NEAR_BOUNDARY" in proxes:
        overall, reason = "NEAR_BOUNDARY", None
    else:
        overall, reason = "INTERIOR", None
    meaning = PROXIMITY_MEANING[overall]
    return DecisionBoundaryMap(
        subject=subject, T=T, verdict=verdict, cohort=cohort,
        dimensions=tuple(dims), overall_proximity=overall,
        unknown_reason=reason,
        interpretation=meaning["statement"],
        candidate_hypotheses=meaning["priority_hypotheses"])


def compare_cohorts(maps: list) -> dict:
    """Contrast attacked states against refused ones, dimension by
    dimension. The question: did the attacked states actually LOOK
    different, or did they merely land on the other side of a line?"""
    by_cohort = {}
    for m in maps:
        by_cohort.setdefault(m.cohort, []).append(m)

    dims = sorted({d.dimension for m in maps for d in m.dimensions})
    table = {}
    for dim in dims:
        row = {}
        for cohort, ms in by_cohort.items():
            vals = [d.value for m in ms for d in m.dimensions
                    if d.dimension == dim
                    and isinstance(d.value, (int, float))]
            row[cohort] = ({"n": len(vals),
                            "min": round(min(vals), 4),
                            "max": round(max(vals), 4),
                            "mean": round(sum(vals) / len(vals), 4)}
                           if vals else {"n": 0})
        table[dim] = row

    # overlap: do the cohorts' ranges intersect on this dimension?
    overlaps = {}
    for dim, row in table.items():
        ranges = {c: (v["min"], v["max"]) for c, v in row.items()
                  if v.get("n")}
        if len(ranges) < 2:
            overlaps[dim] = NOT_ESTIMABLE
            continue
        lo = max(r[0] for r in ranges.values())
        hi = min(r[1] for r in ranges.values())
        overlaps[dim] = "OVERLAPPING" if lo <= hi else "SEPARATED"

    return {"kind": "cohort_boundary_comparison",
            "cohorts": {c: len(ms) for c, ms in by_cohort.items()},
            "per_dimension": table,
            "separation": overlaps,
            "question": "did the attacked states LOOK different, or did "
                        "they merely land on the other side of a line?",
            "law": "descriptive only; overlap on one session convicts "
                   "nothing and no gate may move from it",
            "decision_power": "NONE_RESEARCH"}
