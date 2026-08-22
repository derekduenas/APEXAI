"""ModelBreakerState — F8: Assassin 2.0. A sibling to
apex.hunter.assassin.py (Epoch-1's OWN Assassin, untouched by this
build) -- this one hunts for reasons NOT to trust the shadow
intelligence stack itself, rather than reasons not to trade a candidate.

THE MONOTONE CAUTION LAW (same discipline apex.hunter.assassin.py
documents for Epoch-1, reimplemented independently here): novelty may
REDUCE future risk authority, and may NEVER increase it.
`caution_action()` enforces this mechanically -- caution_level can only
go up or stay flat across calls, never down, regardless of how benign a
later reading looks.

Three of the ten named mechanisms have no real signal behind them
tonight (no historical distribution model for OOD, no regime classifier
wired into this build, no liquidity feed) and are declared
UNREACHABLE, matching the same honesty pattern as F3/F6.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from apex.frontier2 import FRONTIER2_POWER

LEDGER = Path("results/frontier2/assassin2_ledger.jsonl")

MECHANISMS = ("OUT_OF_DISTRIBUTION", "MODEL_CONFLICT", "DATA_CONFLICT",
             "REGIME_NOVELTY", "CORRELATION_BREAK", "WEAK_ANALOG_SUPPORT",
             "LIQUIDITY_ANOMALY", "UNEXPLAINED_RESPONSE",
             "PREDICTION_RESIDUAL_BREAK", "SYSTEM_DEGRADATION")

UNREACHABLE_MECHANISMS = {
    "OUT_OF_DISTRIBUTION": "NO_HISTORICAL_DISTRIBUTION_MODEL",
    "REGIME_NOVELTY": "NO_REGIME_CLASSIFIER_WIRED_INTO_THIS_BUILD",
    "LIQUIDITY_ANOMALY": "NO_LIQUIDITY_FEED",
}

FAMILIARITY_STATES = ("FAMILIAR", "LOW_FAMILIARITY", "OUT_OF_DISTRIBUTION",
                      "MODEL_CONFLICT", "DATA_CONFLICT", "STRUCTURAL_RISK",
                      "UNKNOWN")

CAUTION_LABELS = ("NONE", "ELEVATED", "HIGH", "SEVERE")

# named, documented thresholds
MIN_ENGINES_EACH_SIDE_FOR_CONFLICT = 2
WEAK_ANALOG_SUPPORT_MAX = 0.15
RESIDUAL_BREAK_CURVATURE = 5.0


class Assassin2Error(RuntimeError):
    pass


@dataclass(frozen=True)
class ModelBreakerState:
    subject: str
    as_of: str
    known_from: str
    familiarity: str
    mechanisms_checked: tuple
    mechanisms_fired: tuple
    mechanisms_unreachable: tuple
    lethal_defect: bool
    caution_level: int
    caution_label: str
    reasoning: tuple
    quality: str
    decision_power: str = FRONTIER2_POWER

    def __post_init__(self):
        if self.familiarity not in FAMILIARITY_STATES:
            raise Assassin2Error(f"unknown familiarity {self.familiarity!r}")
        if self.caution_label not in CAUTION_LABELS:
            raise Assassin2Error("bad caution_label")
        if not (0 <= self.caution_level <= 3):
            raise Assassin2Error("caution_level out of range")
        fired_unreachable = set(self.mechanisms_fired) & set(UNREACHABLE_MECHANISMS)
        if fired_unreachable:
            raise Assassin2Error(
                f"a caller asserted an UNREACHABLE mechanism fired: "
                f"{fired_unreachable}")

    def as_record(self) -> dict:
        return asdict(self)


def caution_action(familiarity: str, prior_caution_level: int) -> tuple:
    """THE MONOTONE LAW: returns (level, label). `max()` is the entire
    enforcement mechanism -- a benign new reading can never lower the
    level a prior, worse reading already established."""
    mapped = {"FAMILIAR": 0, "LOW_FAMILIARITY": 1, "MODEL_CONFLICT": 1,
             "UNKNOWN": 1, "DATA_CONFLICT": 2, "STRUCTURAL_RISK": 2,
             "OUT_OF_DISTRIBUTION": 3}.get(familiarity, 1)
    level = max(prior_caution_level, mapped)
    level = max(0, min(3, level))
    return level, CAUTION_LABELS[level]


def assess(*, subject: str, observation_integrity=None, curve=None,
          expectation_violation=None, propagation_edge=None,
          world_lab=None, model_market_snapshot=None, system_health=None,
          prior_caution_level: int = 0, quality: str = "UNKNOWN",
          known_from, now) -> ModelBreakerState:
    """Every consumed object is OPTIONAL -- a mechanism whose required
    input is absent is simply not checked (added to
    `mechanisms_checked` only when it WAS checkable), never guessed."""
    import pandas as pd
    now = pd.Timestamp(now)
    checked, fired, reasoning = [], [], []
    lethal = False

    if observation_integrity is not None:
        checked.append("DATA_CONFLICT")
        if observation_integrity.disagreement_material > 0:
            fired.append("DATA_CONFLICT")
            reasoning.append(
                f"{observation_integrity.disagreement_material} material "
                f"provider disagreement(s)")
        if observation_integrity.quality == "INVALID":
            lethal = True
            reasoning.append("observation_integrity quality is INVALID "
                            "-- a lethal deterministic integrity defect")

    if system_health is not None:
        checked.append("SYSTEM_DEGRADATION")
        status = system_health.get("status")
        if status in ("DEGRADED", "STALLED", "FAILED"):
            fired.append("SYSTEM_DEGRADATION")
            reasoning.append(f"system_health status={status}")

    if propagation_edge is not None:
        checked.append("CORRELATION_BREAK")
        if propagation_edge.status == "UNSTABLE":
            fired.append("CORRELATION_BREAK")
            reasoning.append(f"edge {propagation_edge.source}->"
                            f"{propagation_edge.target} is UNSTABLE")

    if world_lab is not None:
        checked.append("WEAK_ANALOG_SUPPORT")
        max_support = max((s["current_support"] for s in world_lab.scenarios),
                          default=0.0)
        if max_support < WEAK_ANALOG_SUPPORT_MAX:
            fired.append("WEAK_ANALOG_SUPPORT")
            reasoning.append(f"no scenario exceeds "
                            f"{WEAK_ANALOG_SUPPORT_MAX} support "
                            f"(max={max_support})")

    if expectation_violation is not None:
        checked.append("UNEXPLAINED_RESPONSE")
        if (expectation_violation.state == "OBSERVABLE_VIOLATION"
                and expectation_violation.residual_strength == "STRONG"):
            fired.append("UNEXPLAINED_RESPONSE")
            reasoning.append("strong, currently-unexplained expectation "
                            "violation")

    if model_market_snapshot is not None:
        checked.append("MODEL_CONFLICT")
        t = model_market_snapshot["tally"]
        if (t.get("SUPPORT", 0) >= MIN_ENGINES_EACH_SIDE_FOR_CONFLICT
                and t.get("OPPOSE", 0) >= MIN_ENGINES_EACH_SIDE_FOR_CONFLICT):
            fired.append("MODEL_CONFLICT")
            reasoning.append(f"{t['SUPPORT']} SUPPORT vs {t['OPPOSE']} "
                            f"OPPOSE -- material engine disagreement")

    if curve is not None:
        checked.append("PREDICTION_RESIDUAL_BREAK")
        price_curv = (curve.dimensions.get("price") or {}).get("curvature")
        if price_curv is not None and abs(price_curv) >= RESIDUAL_BREAK_CURVATURE:
            fired.append("PREDICTION_RESIDUAL_BREAK")
            reasoning.append(f"price curvature {price_curv} exceeds "
                            f"{RESIDUAL_BREAK_CURVATURE}")

    if not reasoning:
        reasoning.append("no mechanism fired on the inputs provided")

    # deterministic priority lookup -- documented order, not a score.
    if lethal:
        familiarity = "DATA_CONFLICT"
    elif "DATA_CONFLICT" in fired:
        familiarity = "DATA_CONFLICT"
    elif "SYSTEM_DEGRADATION" in fired:
        familiarity = "STRUCTURAL_RISK"
    elif "MODEL_CONFLICT" in fired:
        familiarity = "MODEL_CONFLICT"
    elif "CORRELATION_BREAK" in fired or "PREDICTION_RESIDUAL_BREAK" in fired:
        familiarity = "STRUCTURAL_RISK"
    elif "WEAK_ANALOG_SUPPORT" in fired or "UNEXPLAINED_RESPONSE" in fired:
        familiarity = "LOW_FAMILIARITY"
    elif not checked:
        familiarity = "UNKNOWN"
    else:
        familiarity = "FAMILIAR"

    level, label = caution_action(familiarity, prior_caution_level)
    if lethal:
        # a lethal defect is categorically worse than an ordinary
        # DATA_CONFLICT (mere source disagreement) even though both map
        # to the same familiarity label -- force the ceiling directly,
        # still respecting monotonicity (max() against a higher prior).
        level = max(level, 3)
        label = CAUTION_LABELS[level]

    return ModelBreakerState(
        subject=subject, as_of=str(now), known_from=str(pd.Timestamp(known_from)),
        familiarity=familiarity, mechanisms_checked=tuple(checked),
        mechanisms_fired=tuple(fired),
        mechanisms_unreachable=tuple(UNREACHABLE_MECHANISMS),
        lethal_defect=lethal, caution_level=level, caution_label=label,
        reasoning=tuple(reasoning), quality=quality)


def persist(state: ModelBreakerState) -> dict:
    import sys
    sys.path.insert(0, "scripts")
    from nightly_pull import _chain_append
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    return _chain_append(LEDGER, state.as_record())
