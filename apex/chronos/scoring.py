"""TWO SCORES THAT MAY NEVER BE BLENDED.

ECONOMIC: did the decisions make money, out of sample, after friction?
SCIENTIFIC: did the intelligence behave like an intelligence --
reject false edges, identify decay, calibrate, refuse well, beat
simple baselines, recognize what it did not know?

They are computed separately, reported separately, and there is no
combined number, because a combined number is a dial someone will
optimize. Early CHRONOS may be economically mediocre and
scientifically valuable; that is a legitimate state. What is NOT
legitimate is scientific virtue that never translates -- so the
scientific score carries a standing question, not a free pass:
"has this translated into better economic decisions yet, and if not,
what is the concrete mechanism by which it eventually will?"
Research theater is the failure mode this file exists to name.

decision_power: NONE_RESEARCH.
"""
from __future__ import annotations

import statistics

from apex.chronos import EVIDENCE_LABEL
from apex.chronos.clock import ChronosViolation

NOT_ESTIMABLE = "NOT_ESTIMABLE"

SCIENTIFIC_DIMENSIONS = (
    "false_edge_rejection",       # killed candidates that later failed
    "decay_detection",            # flagged deterioration before collapse
    "path_distribution_fidelity", # analog/world sets resembled the future
    "calibration",                # stated uncertainty matched outcomes
    "cohort_separation",          # ATTACK > WAIT > REFUSE, or not
    "false_discovery_restraint",  # behavior on nonsense and shuffles
    "hypothesis_information",     # hypotheses carried usable signal
    "uncertainty_recognition",    # said NOT_ESTIMABLE when it was
    "baseline_superiority",       # beat NO_TRADE and simple rules
    "missing_state_detection",    # surfaced representation gaps
)


def economic_score(*, oos_r_multiples: list, friction_total: float,
                   n_sessions: int) -> dict:
    """Out-of-sample decisions only. In-sample trades are not evidence
    of anything except the fit."""
    if not oos_r_multiples:
        return {"kind": "chronos_economic_score",
                "evidence_label": EVIDENCE_LABEL,
                "verdict": "NO_OOS_DECISIONS",
                "decision_power": "NONE_RESEARCH"}
    vals = [r for r in oos_r_multiples if isinstance(r, (int, float))]
    return {"kind": "chronos_economic_score",
            "evidence_label": EVIDENCE_LABEL,
            "n_decisions": len(vals),
            "n_sessions": n_sessions,
            "total_R": round(sum(vals), 4),
            "median_R": round(statistics.median(vals), 4),
            "favorable_fraction": round(
                sum(1 for v in vals if v > 0) / len(vals), 4),
            "friction_total": round(friction_total, 2),
            "law": "historical replay economics never upgrade to "
                   "prospective evidence; real sessions are the judge",
            "decision_power": "NONE_RESEARCH"}


def scientific_score(*, dimension_evidence: dict) -> dict:
    """Grade the intelligence, dimension by dimension, no composite.

    dimension_evidence maps each SCIENTIFIC_DIMENSION to
      {"verdict": "DEMONSTRATED"|"FAILED"|"INSUFFICIENT_EVIDENCE",
       "evidence": str}
    Every dimension must be present -- an absent dimension is a
    question nobody asked, which is worse than a failed one."""
    missing = [d for d in SCIENTIFIC_DIMENSIONS
               if d not in dimension_evidence]
    if missing:
        raise ChronosViolation(
            f"scientific score refused: unassessed dimensions "
            f"{missing}. An unasked question is not a passed one")
    rows = {}
    for d in SCIENTIFIC_DIMENSIONS:
        e = dimension_evidence[d]
        if e.get("verdict") not in ("DEMONSTRATED", "FAILED",
                                    "INSUFFICIENT_EVIDENCE"):
            raise ChronosViolation(
                f"dimension {d}: verdict must be DEMONSTRATED, FAILED "
                f"or INSUFFICIENT_EVIDENCE, got {e.get('verdict')!r}")
        if not e.get("evidence"):
            raise ChronosViolation(
                f"dimension {d}: a verdict without evidence is an "
                f"opinion wearing a lab coat")
        rows[d] = {"verdict": e["verdict"], "evidence": e["evidence"]}
    demonstrated = sum(1 for r in rows.values()
                       if r["verdict"] == "DEMONSTRATED")
    failed = sum(1 for r in rows.values() if r["verdict"] == "FAILED")
    return {"kind": "chronos_scientific_score",
            "evidence_label": EVIDENCE_LABEL,
            "dimensions": rows,
            "demonstrated": demonstrated, "failed": failed,
            "insufficient": len(rows) - demonstrated - failed,
            "no_composite_number": True,
            "standing_question": (
                "has scientific capability translated into better "
                "economic decisions yet, and if not, what is the "
                "concrete mechanism by which it eventually will? "
                "Scientific virtue that never translates is research "
                "theater"),
            "decision_power": "NONE_RESEARCH"}


def blend(*_args, **_kwargs):
    """Deliberately unimplementable. The temptation gets a named
    grave instead of a quiet implementation."""
    raise ChronosViolation(
        "there is no combined economic+scientific number. A composite "
        "is a dial someone will optimize, and the first thing it "
        "optimizes away is the honest zero")
