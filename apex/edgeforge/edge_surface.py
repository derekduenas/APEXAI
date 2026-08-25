"""EDGE SURFACE — where the opportunity survives, and where it dies.

A point estimate ("this trade was +EV") is nearly worthless; the
research object is the NEIGHBOURHOOD: how far can entry worsen before
the edge disappears, how much spread expansion destroys it, what state
transition flips the answer from ATTACK to WAIT. A robust edge has room
around it; a fragile one is a knife's edge that only looked like an
edge because we happened to stand exactly on it.

Axes come from the candidate's MECHANISM, never from a brute-force
sweep of every recorded dimension -- indiscriminate surfaces are
multiple-testing machines wearing lab coats.

REGION LABELS use a declared REPORTING_PRIOR (favorable world-fraction
cutoffs), classified exactly like the calibration floor: a human-chosen
convenience for describing a surface, not a learned threshold, and
carried in the output so nobody later mistakes the vocabulary for a
discovery.

decision_power: NONE_RESEARCH.
"""
from __future__ import annotations

from dataclasses import dataclass

NOT_ESTIMABLE = "NOT_ESTIMABLE"

REGIONS = ("ROBUST_REGION", "FRAGILE_REGION", "FAILURE_REGION",
           "UNKNOWN_REGION")

# REPORTING_PRIOR (declared, not learned): a grid cell whose favorable
# world-fraction is >= ROBUST_CUT reads ROBUST, <= FAIL_CUT reads
# FAILURE, in between FRAGILE. Descriptive vocabulary only.
ROBUST_CUT = 0.60
FAIL_CUT = 0.40
REGION_RULE_CLASSIFICATION = "REPORTING_PRIOR"


class EdgeSurfaceViolation(RuntimeError):
    pass


@dataclass(frozen=True)
class AxisSpec:
    """One mechanism-derived axis: a named parameter and its sweep."""
    name: str
    values: tuple
    mechanism_reason: str

    def __post_init__(self):
        if not self.mechanism_reason:
            raise EdgeSurfaceViolation(
                f"axis {self.name!r} has no mechanism reason -- an axis "
                f"without a mechanism is a fishing rod")


def sweep(*, base_params: dict, axes: list, worlds: list,
          make_attack, evaluate_common, summarize_attack) -> dict:
    """Evaluate the candidate across a mechanism-derived grid, every
    cell fighting the SAME worlds."""
    if not axes:
        raise EdgeSurfaceViolation("no axes: a surface needs dimensions")
    if len(axes) > 3:
        raise EdgeSurfaceViolation(
            "more than 3 axes at once is a brute-force sweep, not a "
            "mechanism study -- decompose it")

    # cartesian grid
    grids = [{}]
    for ax in axes:
        grids = [{**g, ax.name: v} for g in grids for v in ax.values]

    cells = []
    for g in grids:
        params = {**base_params, **g}
        attack = make_attack(params)
        run = evaluate_common(attacks=[attack], worlds=worlds)
        s = summarize_attack(run, attack)
        frac = s.get("favorable_world_fraction")
        if not isinstance(frac, (int, float)):
            region = "UNKNOWN_REGION"
        elif frac >= ROBUST_CUT:
            region = "ROBUST_REGION"
        elif frac <= FAIL_CUT:
            region = "FAILURE_REGION"
        else:
            region = "FRAGILE_REGION"
        cells.append({"cell": g, "region": region,
                      "favorable_world_fraction": frac,
                      "median_pnl": s.get("median_pnl"),
                      "lower_tail_p10": s.get("lower_tail_p10")})

    # decision boundaries: adjacent cells along one axis whose region
    # label changes -- the places where the answer flips
    boundaries = []
    for ax in axes:
        vals = list(ax.values)
        for i in range(len(vals) - 1):
            for c1 in cells:
                if c1["cell"][ax.name] != vals[i]:
                    continue
                match = {k: v for k, v in c1["cell"].items()
                         if k != ax.name}
                for c2 in cells:
                    if c2["cell"][ax.name] != vals[i + 1]:
                        continue
                    if {k: v for k, v in c2["cell"].items()
                            if k != ax.name} != match:
                        continue
                    if c1["region"] != c2["region"]:
                        boundaries.append({
                            "axis": ax.name,
                            "between": (vals[i], vals[i + 1]),
                            "from": c1["region"], "to": c2["region"],
                            "holding": match})

    regions = {}
    for c in cells:
        regions[c["region"]] = regions.get(c["region"], 0) + 1
    return {"kind": "edge_surface",
            "axes": [{"name": a.name, "values": list(a.values),
                      "mechanism_reason": a.mechanism_reason}
                     for a in axes],
            "n_cells": len(cells), "cells": cells,
            "region_counts": regions,
            "decision_boundaries": boundaries,
            "region_rule": {"robust_cut": ROBUST_CUT,
                            "fail_cut": FAIL_CUT,
                            "classification":
                            REGION_RULE_CLASSIFICATION},
            "law": "regions are descriptive vocabulary under a declared "
                   "reporting prior; nothing here is a learned "
                   "threshold, and no gate may be moved from a surface "
                   "built on one session's worlds",
            "decision_power": "NONE_RESEARCH"}
