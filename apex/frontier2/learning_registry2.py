"""learning_registry2 — F16: the preregistered hypotheses Frontier-2
will eventually be judged against, frozen BEFORE any prospective
observation exists. Same discipline as apex.frontier.learning.py
(reimplemented independently, per the firewall): a conservative
minimum-N rule frozen now so no result can be peeked at into
significance, and `estimate()` is the ONLY door -- gated at the moment
of computation, not by a docstring.

Every one of the ten hypotheses below starts, and will remain for a
long time, at 0 valid prospective observations. That is not a
placeholder to be filled in tonight; it is the honest state of a build
that went live minutes ago.
"""
from __future__ import annotations

import json
from pathlib import Path

from apex.frontier2 import FRONTIER2_POWER

REGISTRY = Path("results/frontier2/learning_registry2.json")

PREREGISTRATION = {
    "registered_utc": "2026-08-18T04:13:42+00:00",
    "min_n_rule": ("each compared group needs >= 20 resolved prospective "
                   "observations across >= 10 distinct session dates "
                   "before ANY estimate is computed"),
    "min_n_per_group": 20,
    "min_distinct_dates": 10,
    "hypotheses": {
        "H_CURVE_TRANSITION": {
            "question": ("does an elevated MarketCurvatureState "
                         "transition_likelihood correspond to a real "
                         "subsequent state change, more often than a "
                         "matched control?"),
            "groups": ("LIKELIHOOD_HIGH", "LIKELIHOOD_MODERATE",
                      "LIKELIHOOD_LOW", "LIKELIHOOD_UNKNOWN"),
            "measures": ("ret_15m", "ret_30m", "ret_60m", "mfe", "mae")},
        "H_CURVE_DIRECTION": {
            "question": ("when transition_direction is UP or DOWN (not "
                         "MIXED/UNKNOWN), does subsequent price move in "
                         "that direction more often than chance?"),
            "groups": ("DIRECTION_UP", "DIRECTION_DOWN", "DIRECTION_MIXED",
                      "DIRECTION_UNKNOWN"),
            "measures": ("ret_15m", "ret_30m", "ret_60m")},
        "H_CURVE_EXPRESSION": {
            "question": ("does EARLY_EXPRESSION (RS/other dims bending "
                         "before price) precede CONFIRMED_EXPRESSION with "
                         "measurable lead time, more often than not?"),
            "groups": ("EARLY_EXPRESSION", "CONFIRMED_EXPRESSION",
                      "NO_EXPRESSION"),
            "measures": ("lead_time_minutes", "ret_60m")},
        "H_EXPECTATION_VIOLATION": {
            "question": ("does an OBSERVABLE_VIOLATION with STRONG "
                         "residual_strength predict a different forward "
                         "outcome than NO_VIOLATION?"),
            "groups": ("OBSERVABLE_VIOLATION_STRONG",
                      "OBSERVABLE_VIOLATION_WEAK", "NO_VIOLATION"),
            "measures": ("ret_15m", "ret_30m", "ret_60m")},
        "H_PARTICIPANT_PRESSURE": {
            "question": ("does a CONFIRMED_BY_PRICE_ACTION trap state "
                         "predict the trap's implied direction better "
                         "than a POSSIBLE_* trap alone?"),
            "groups": ("CONFIRMED_TRAP", "POSSIBLE_TRAP", "NO_TRAP"),
            "measures": ("ret_15m", "ret_30m", "ret_60m")},
        "H_PROPAGATION": {
            "question": ("for a SUPPORTED_LEAD_LAG edge, does the target "
                         "actually change within 2x the estimated delay "
                         "more often than a matched control pair?"),
            "groups": ("SUPPORTED_LEAD_LAG", "OBSERVATIONAL_RELATIONSHIP",
                      "UNSTABLE"),
            "measures": ("propagated_within_2x_delay", "observed_delay_minutes")},
        "H_LEADING_EDGE": {
            "question": ("does rank=1 in a LeadingEdgeMap outperform "
                         "rank>1 candidates for the same transition?"),
            "groups": ("RANK_1", "RANK_2_TO_5", "RANK_6_PLUS"),
            "measures": ("ret_15m", "ret_30m", "ret_60m")},
        "H_MODEL_MARKET": {
            "question": ("does unanimous or near-unanimous engine SUPPORT "
                         "predict outcomes better than a split vote?"),
            "groups": ("UNANIMOUS", "MAJORITY", "SPLIT"),
            "measures": ("resolved_correct_frac",)},
        "H_ASSASSIN2": {
            "question": ("does a non-FAMILIAR ModelBreakerState verdict "
                         "correspond to worse subsequent CaptainShadow "
                         "thesis outcomes than FAMILIAR?"),
            "groups": ("FAMILIAR", "LOW_FAMILIARITY", "STRUCTURAL_RISK",
                      "DATA_CONFLICT", "MODEL_CONFLICT"),
            "measures": ("thesis_survived_to_target", "thesis_invalidated")},
        "H_CAPTAIN_FRONTIER": {
            "question": ("does a SERIOUS CaptainFrontierShadow state "
                         "correspond to better forward outcomes than "
                         "DEVELOP or WATCH?"),
            "groups": ("SERIOUS", "WAIT_FOR_ENTRY", "DEVELOP", "WATCH"),
            "measures": ("ret_15m", "ret_30m", "ret_60m", "mfe", "mae")},
    },
    "rule_17": "prospective observations only; no historical LLM replay",
    "decision_power": FRONTIER2_POWER,
}


class LearningRegistry2Violation(RuntimeError):
    pass


def preregister() -> Path:
    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    # Compare through a JSON round-trip on BOTH sides: PREREGISTRATION
    # holds tuples (groups/measures), which JSON has no native type for
    # and always deserializes back as lists -- comparing the raw dict
    # against a freshly-loaded one would treat every unmodified registry
    # as tampered. Round-tripping the in-code copy too makes the
    # comparison type-consistent without weakening what it checks.
    canonical = json.loads(json.dumps(PREREGISTRATION))
    if REGISTRY.exists():
        prior = json.loads(REGISTRY.read_text())
        if prior["preregistration"] != canonical:
            raise LearningRegistry2Violation(
                "the preregistration on disk differs from the code: "
                "amending hypotheses after registration is a lineage break")
        return REGISTRY
    REGISTRY.write_text(json.dumps(
        {"preregistration": PREREGISTRATION, "observations": []}, indent=2))
    return REGISTRY


def estimate(hypothesis: str, observations: tuple = ()) -> dict:
    """The ONLY estimation door. `observations`: whatever prospective
    records a caller has accrued -- always empty tonight."""
    if hypothesis not in PREREGISTRATION["hypotheses"]:
        raise LearningRegistry2Violation(
            f"{hypothesis!r} was not preregistered; post-hoc hypotheses "
            f"are refused")
    n_rule = PREREGISTRATION["min_n_per_group"]
    d_rule = PREREGISTRATION["min_distinct_dates"]
    dates = {o.get("session_date") for o in observations if "session_date" in o}
    if len(observations) < n_rule or len(dates) < d_rule:
        return {"hypothesis": hypothesis, "status": "NOT_YET_ESTIMABLE",
               "resolved_observations": len(observations),
               "distinct_dates": len(dates), "rule": PREREGISTRATION["min_n_rule"],
               "decision_power": FRONTIER2_POWER}
    raise LearningRegistry2Violation(
        "sample rule met but the estimator is deliberately NOT implemented "
        "in this lineage: computing it is a versioned governance act, not "
        "a quiet code path")
