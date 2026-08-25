"""DECISION BOUNDARY ARCHAEOLOGY — how close was this to flipping?

A verdict of GOOD tells you almost nothing on its own. A state one
hundredth of an ATR inside the boundary and a state deep in the
interior both print GOOD, and they are entirely different animals:

    BARELY INSIDE   the verdict is a coin balanced on its edge, and the
                    incumbent's threshold is doing the deciding.
    DEEP INSIDE     the verdict is robust, so if the outcome was wrong
                    the fault is not the threshold -- it is a MISSING
                    STATE VARIABLE the representation never saw.

That distinction decides what kind of research problem we have, and it
is invisible to any funnel that records only labels. Monday's SPY needs
exactly this question asked of it, next to the six geometry near-misses
that printed a different verdict.

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

PROXIMITY = ("KNIFE_EDGE", "NEAR_BOUNDARY", "INTERIOR", NOT_ESTIMABLE)

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
        return NOT_ESTIMABLE
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
            band_fraction_used=NOT_ESTIMABLE, proximity=NOT_ESTIMABLE,
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
    law: str = ("distances are per dimension and never collapsed; "
                "thresholds are imported from the incumbent, never "
                "restated")
    proximity_rule: str = PROXIMITY_RULE_CLASSIFICATION
    decision_power: str = "NONE_RESEARCH"

    def as_record(self) -> dict:
        return {"kind": "decision_boundary_map", **asdict(self),
                "dimensions": [d.as_record() for d in self.dimensions]}


def map_equity_decision(*, subject: str, T: str, verdict: str,
                        cohort: str, extension_atr, invalidation_atr,
                        extras: dict | None = None
                        ) -> DecisionBoundaryMap:
    """Reconstruct how close an equity-geometry verdict was to flipping.

    `extras` accepts additional pre-declared banded dimensions as
    {name: (value, edges, source, note)} so the map can widen as the
    faculty does -- without this module inventing bands of its own."""
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

    proxes = [d.proximity for d in dims if d.proximity != NOT_ESTIMABLE]
    if not proxes:
        overall = NOT_ESTIMABLE
        interp = "no estimable dimension; proximity unknown"
    elif "KNIFE_EDGE" in proxes:
        overall = "KNIFE_EDGE"
        interp = (
            "at least one dimension sits on its boundary: this verdict "
            "was decided BY THE THRESHOLD. If the outcome was wrong, "
            "the threshold is the suspect.")
    elif "NEAR_BOUNDARY" in proxes:
        overall = "NEAR_BOUNDARY"
        interp = ("close enough that small state changes would flip it")
    else:
        overall = "INTERIOR"
        interp = (
            "deep inside the verdict on every measured dimension: the "
            "threshold is NOT the suspect. If the outcome was wrong, "
            "the representation is MISSING A STATE VARIABLE it never "
            "saw.")
    return DecisionBoundaryMap(
        subject=subject, T=T, verdict=verdict, cohort=cohort,
        dimensions=tuple(dims), overall_proximity=overall,
        interpretation=interp)


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
