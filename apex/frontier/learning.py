"""Frontier learning registries — the machinery to eventually answer
whether the Eyes, the Assassin and the Catalyst channel EARN their seats.

Preregistered BEFORE the first observation, with a conservative minimum-N
rule frozen now, so no result can be peeked at into significance. Until
the rule is met every registry answers NOT_YET_ESTIMABLE, structurally.

Rule 17 remains absolute: groups accrue from PROSPECTIVE decision cards
only; no historical LLM replay can ever populate them.
"""
from __future__ import annotations

import json
from pathlib import Path

from apex.frontier import FRONTIER_POWER

REGISTRY = Path("results/frontier/learning_registry.json")

# The frozen preregistration. Changing any of this after observations
# exist is a lineage break, and a test pins the hash.
PREREGISTRATION = {
    "registered_utc": "2026-08-17T02:00:00+00:00",
    "amendment_note": ("catalyst absence group relabeled to WITHIN_ACTIVE_"
                       "SOURCES at ZERO observations, before any card "
                       "resolved — absence labels fixed pre-data so "
                       "learning cannot inherit an overclaim"),
    "min_n_rule": ("each compared group needs >= 20 resolved decision "
                   "cards across >= 10 distinct session dates before ANY "
                   "estimate is computed"),
    "min_n_per_group": 20,
    "min_distinct_dates": 10,
    "hypotheses": {
        "H_VISUAL": {
            "question": ("do candidates with MATERIAL visual objections "
                         "have worse prospective outcomes than otherwise "
                         "similar candidates without them?"),
            "groups": ("VISUAL_SUPPORT", "VISUAL_NEUTRAL",
                       "VISUAL_OBJECTION", "VISUAL_UNAVAILABLE"),
            "measures": ("ret_15m", "ret_30m", "ret_60m", "ret_90m",
                         "mfe", "mae")},
        "H_ASSASSIN": {
            "question": ("does Assassin wounding/refusal correspond to "
                         "worse subsequent outcomes?"),
            "groups": ("CLEAN", "WOUNDED", "UNAVAILABLE"),
            "measures": ("ret_15m", "ret_30m", "ret_60m", "ret_90m",
                         "mfe", "mae")},
        "H_CATALYST": {
            "question": ("do candidate outcomes differ across catalyst "
                         "attribution states?"),
            "groups": ("KNOWN_CATALYST",
                       "NO_KNOWN_CATALYST_WITHIN_ACTIVE_SOURCES",
                       "EVENT_UNCERTAIN"),
            "measures": ("ret_15m", "ret_30m", "ret_60m", "ret_90m",
                         "mfe", "mae")},
    },
    "rule_17": "prospective decision cards only; no historical LLM replay",
    "decision_power": FRONTIER_POWER,
}


class LearningViolation(RuntimeError):
    """Someone tried to estimate before the preregistered sample exists."""


def preregister() -> Path:
    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    if REGISTRY.exists():
        prior = json.loads(REGISTRY.read_text())
        if prior["preregistration"] != PREREGISTRATION:
            raise LearningViolation(
                "the preregistration on disk differs from the code: "
                "amending hypotheses after registration is a lineage break")
        return REGISTRY
    REGISTRY.write_text(json.dumps(
        {"preregistration": PREREGISTRATION, "observations": []}, indent=2))
    return REGISTRY


def _resolved_cards() -> list:
    out = []
    root = Path("results/decision_cards")
    if not root.exists():
        return out
    for p in root.rglob("*.json"):
        try:
            payload = json.loads(p.read_text())
        except json.JSONDecodeError:
            continue
        if "after" in payload:
            out.append(payload)
    return out


def estimate(hypothesis: str) -> dict:
    """The ONLY estimation door, and it is gated at the moment of
    computation — not by a docstring (LAB-07's lesson)."""
    if hypothesis not in PREREGISTRATION["hypotheses"]:
        raise LearningViolation(f"{hypothesis!r} was not preregistered; "
                                f"post-hoc hypotheses are refused")
    cards = _resolved_cards()
    dates = {c["before"]["session_date"] for c in cards}
    n_rule = PREREGISTRATION["min_n_per_group"]
    d_rule = PREREGISTRATION["min_distinct_dates"]
    if len(cards) < n_rule or len(dates) < d_rule:
        return {"hypothesis": hypothesis,
                "status": "NOT_YET_ESTIMABLE",
                "resolved_cards": len(cards),
                "distinct_dates": len(dates),
                "rule": PREREGISTRATION["min_n_rule"],
                "decision_power": FRONTIER_POWER}
    raise LearningViolation(
        "sample rule met but the estimator is deliberately NOT implemented "
        "in this lineage: computing it is a versioned governance act, not "
        "a quiet code path")
