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


VALIDITY_COMPONENTS = (
    "CAUSAL_INTEGRITY", "POISON_CONTROL",
    "WITHIN_EPOCH_FALSE_DISCOVERY_CONTROL",
    "CROSS_EPOCH_MULTIPLICITY_CONTROL", "SURVIVORSHIP_CONTROL",
    "VALIDATION_DISCIPLINE", "LOCKBOX_INTEGRITY")


def scientific_validity_decomposition(*, components: dict) -> dict:
    """Scientific validity is DECOMPOSABLE, because Campaign #001
    proved a single verdict misleads: PASSED_FALSE_DISCOVERY_CONTROL
    was true and still sounded like the whole process passed, when it
    had passed ONE defense and exposed failure in another.

    Every component must be present with PASS / FAIL /
    NOT_EXERCISED and evidence. Overall authority is NONE unless
    every component PASSES -- a chain of defenses is as strong as its
    weakest named link, and an unnamed link is weaker still."""
    missing = [c for c in VALIDITY_COMPONENTS if c not in components]
    if missing:
        raise ChronosViolation(
            f"validity decomposition refuses with unassessed "
            f"components {missing}: an unnamed defense cannot pass")
    rows = {}
    for c in VALIDITY_COMPONENTS:
        e = components[c]
        if e.get("verdict") not in ("PASS", "FAIL", "NOT_EXERCISED"):
            raise ChronosViolation(
                f"component {c}: verdict must be PASS, FAIL or "
                f"NOT_EXERCISED, got {e.get('verdict')!r}")
        if not e.get("evidence"):
            raise ChronosViolation(
                f"component {c}: a verdict without evidence is an "
                f"opinion wearing a lab coat")
        rows[c] = {"verdict": e["verdict"], "evidence": e["evidence"]}
    failed = [c for c, r in rows.items() if r["verdict"] == "FAIL"]
    unexercised = [c for c, r in rows.items()
                   if r["verdict"] == "NOT_EXERCISED"]
    overall = ("NONE" if failed or unexercised else "QUALIFIED")
    return {"kind": "scientific_validity_decomposition",
            "components": rows, "failed": failed,
            "not_exercised": unexercised,
            "OVERALL_SCIENTIFIC_AUTHORITY": overall,
            "evidence_label": EVIDENCE_LABEL,
            "law": "passing one defense is not passing the process; "
                   "authority is NONE until every named component "
                   "qualifies",
            "decision_power": "NONE_RESEARCH"}


def campaign_status(*, process_qualified: bool,
                    economic_edge_proven: bool) -> dict:
    """Three statuses that must never collapse into one word.

    'QUALIFIED' alone let process quality imply edge quality. The
    hierarchy: a QUALIFIED process with one replay path, one family,
    one dominant run and no prospective confirmation has an UNPROVEN
    edge — and trading authority is a third thing entirely, granted
    by nobody in this module."""
    if economic_edge_proven:
        raise ChronosViolation(
            "no historical replay can set economic_edge_proven=True: "
            "proof requires prospective sessions, which CHRONOS is "
            "structurally incapable of producing")
    return {"kind": "campaign_status",
            "SCIENTIFIC_PROCESS_AUTHORITY": (
                "QUALIFIED_REPLAY_ONLY" if process_qualified
                else "NONE"),
            "ECONOMIC_EDGE_STATUS": "UNPROVEN",
            "TRADING_AUTHORITY": "NONE",
            "evidence_label": EVIDENCE_LABEL,
            "law": "process quality and edge quality are different "
                   "things; QUALIFIED must never imply proven edge, "
                   "and neither grants a cent of trading authority",
            "decision_power": "NONE_RESEARCH"}


def classify_experiment(*, economic_positive: bool | None,
                        false_discovery_restraint: str,
                        survived_unseen_time: bool | None) -> dict:
    """Top-level research qualification. Three lines, so nobody six
    months from now reads 'challenger dominated!' without noticing the
    nonsense controls.

    THE TWO ASYMMETRIC LAWS:
      economic success cannot rescue scientific invalidity -- a
      pipeline that fails its false-discovery controls confers ZERO
      edge authority on anything it produced, however pretty;
      one bad economic realization does not automatically kill a
      scientifically valid candidate -- outcomes have variance, and a
      sound process with a losing draw is reported as exactly that."""
    if false_discovery_restraint not in ("DEMONSTRATED", "FAILED",
                                         "INSUFFICIENT_EVIDENCE"):
        raise ChronosViolation(
            f"unknown restraint verdict {false_discovery_restraint!r}")
    econ = ("POSITIVE" if economic_positive else
            "NEGATIVE" if economic_positive is not None else
            "NOT_RUN")
    if false_discovery_restraint == "FAILED":
        sci = "FAILED_FALSE_DISCOVERY_CONTROL"
        authority = "NONE"
        note = ("the process that produced this result could not "
                "distinguish real structure from deliberate nonsense; "
                "the economic outcome is preserved as a sealed fact "
                "and earns zero edge authority")
    elif false_discovery_restraint == "INSUFFICIENT_EVIDENCE":
        sci = "UNCALIBRATED"
        authority = "NONE"
        note = ("no measured hallucination rate; unmeasured is not "
                "low")
    else:
        sci = "PASSED_FALSE_DISCOVERY_CONTROL"
        if survived_unseen_time:
            authority = "RESEARCH_CANDIDATE"
            note = ("scientifically valid and survived unseen time; "
                    "still HISTORICAL_REPLAY -- prospective sessions "
                    "remain the judge")
        elif survived_unseen_time is False and econ == "NEGATIVE":
            authority = "NONE"
            note = ("scientifically valid process, losing realization: "
                    "outcomes have variance, and this is reported as a "
                    "sound process with a bad draw, not as proof the "
                    "process is broken")
        else:
            authority = "NONE"
            note = "not yet tested on unseen time"
    return {"kind": "experiment_classification",
            "ECONOMIC_TEST_RESULT": econ,
            "SCIENTIFIC_VALIDITY": sci,
            "EDGE_AUTHORITY": authority,
            "note": note,
            "evidence_label": EVIDENCE_LABEL,
            "law": "economic success cannot rescue scientific "
                   "invalidity; one bad realization does not "
                   "automatically kill a valid process",
            "decision_power": "NONE_RESEARCH"}


def blend(*_args, **_kwargs):
    """Deliberately unimplementable. The temptation gets a named
    grave instead of a quiet implementation."""
    raise ChronosViolation(
        "there is no combined economic+scientific number. A composite "
        "is a dial someone will optimize, and the first thing it "
        "optimizes away is the honest zero")
