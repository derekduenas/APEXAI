"""SCIENTIST EXAM — planted ground truth, to measure POWER.

Campaigns 000-003 proved the scientist can reject nonsense. That is
half a scientist. A system that answers NO EDGE forever has a perfect
false-positive rate and is worth nothing.

    EXP 000  noise can fool me
    #001     I rediscover the same noise endlessly
    #002     I remember what I already tried
    #003     I survive an expanding roster, and I spot beta in costume
    #004     ...can I recognize real signal when it is there?

THE CONTROL UNIVERSE IS SEPARATE. Real causally-aligned features are
reused where practical, but OUTCOMES are semisynthetic and generated
from a known ground truth. Nothing discovered here may ever become
EdgeDNA authority: every artifact is labelled POSITIVE_CONTROL_ONLY,
a label with no upgrade path.

Seven predeclared families, each with ground truth fixed BEFORE the
scientist runs, spanning the shapes that actually matter in markets:

    SIMPLE_STRONG        one variable, large, persistent
    SIMPLE_MODERATE      one variable, smaller
    SIMPLE_WEAK          near the noise floor; INSUFFICIENT_EVIDENCE
                         is the CORRECT answer here, not a failure
    INTERACTION_ONLY     neither marginal carries anything; only A x B
    REGIME_CONDITIONAL   real inside one regime, absent elsewhere
    SEQUENCE_EDGE        depends on an A -> B -> C transition, not a
                         state
    DECAYING_EDGE        genuine in 2020, gone by 2023
    NULL_FAMILY          nothing at all

decision_power: NONE_RESEARCH.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from apex.chronos.clock import ChronosViolation
from apex.edgeforge.world_foundry import _Rng

CONTROL_LABEL = "POSITIVE_CONTROL_ONLY"

FAMILIES = ("SIMPLE_STRONG", "SIMPLE_MODERATE", "SIMPLE_WEAK",
            "INTERACTION_ONLY", "REGIME_CONDITIONAL", "SEQUENCE_EDGE",
            "DECAYING_EDGE", "NULL_FAMILY")

# Effect sizes in units of outcome sd. Declared here, before any run.
EFFECT = {"SIMPLE_STRONG": 0.80, "SIMPLE_MODERATE": 0.35,
          "SIMPLE_WEAK": 0.12, "INTERACTION_ONLY": 0.50,
          "REGIME_CONDITIONAL": 0.55, "SEQUENCE_EDGE": 0.50,
          "DECAYING_EDGE": 0.60, "NULL_FAMILY": 0.0}

# Where the truth lives. The discovery process is NEVER given this.
TRUTH_FEATURE = {
    "SIMPLE_STRONG": ("f0",), "SIMPLE_MODERATE": ("f1",),
    "SIMPLE_WEAK": ("f2",), "INTERACTION_ONLY": ("f3", "f4"),
    "REGIME_CONDITIONAL": ("f5",), "SEQUENCE_EDGE": ("f6",),
    "DECAYING_EDGE": ("f7",), "NULL_FAMILY": (),
}

N_FEATURES = 10          # 8 truth-bearing slots + decoys
NOISE_SD = 1.0


class ExamViolation(RuntimeError):
    pass


def _h(*parts) -> float:
    d = hashlib.sha256("|".join(str(p) for p in parts).encode())
    return int(d.hexdigest()[:12], 16) / float(1 << 48) - 0.5


@dataclass
class ControlUniverse:
    """Semisynthetic sessions with known ground truth.

    Features are deterministic from (seed, session, index) so any
    apparent discovery is exactly reproducible and can be dissected."""
    family: str
    n_sessions: int = 900
    seed: int = 4004
    sessions: list = field(default_factory=list)
    features: dict = field(default_factory=dict)
    outcomes: dict = field(default_factory=dict)
    regimes: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.family not in FAMILIES:
            raise ExamViolation(f"unknown exam family {self.family!r}")
        self._build()

    def _build(self):
        rng = _Rng(self.seed)
        eff = EFFECT[self.family]
        prev_hi = False
        prev2_hi = False
        for i in range(self.n_sessions):
            s = f"S{i:04d}"
            self.sessions.append(s)
            f = {f"f{j}": _h(self.seed, s, j) for j in range(N_FEATURES)}
            self.features[s] = f
            # regime defined WITHOUT the outcome, from a feature the
            # truth for other families never uses
            reg = "REGIME_A" if f["f9"] > 0 else "REGIME_B"
            self.regimes[s] = reg
            noise = rng.normal() * NOISE_SD
            signal = 0.0
            if self.family == "SIMPLE_STRONG":
                signal = eff * f["f0"] * 2
            elif self.family == "SIMPLE_MODERATE":
                signal = eff * f["f1"] * 2
            elif self.family == "SIMPLE_WEAK":
                signal = eff * f["f2"] * 2
            elif self.family == "INTERACTION_ONLY":
                # each marginal is symmetric around zero => no marginal
                # edge; only the product carries the effect
                signal = eff * (f["f3"] * f["f4"]) * 4
            elif self.family == "REGIME_CONDITIONAL":
                signal = (eff * f["f5"] * 2) if reg == "REGIME_A" else 0.0
            elif self.family == "SEQUENCE_EDGE":
                # the TRANSITION carries it, never the current state
                signal = (eff * 1.0 if (prev2_hi and not prev_hi
                                        and f["f6"] > 0) else 0.0)
            elif self.family == "DECAYING_EDGE":
                frac = i / max(self.n_sessions - 1, 1)
                signal = eff * f["f7"] * 2 * max(0.0, 1.0 - 1.35 * frac)
            self.outcomes[s] = signal + noise
            prev2_hi, prev_hi = prev_hi, f["f6"] > 0

    def ground_truth(self) -> dict:
        return {"kind": "exam_ground_truth", "family": self.family,
                "truth_features": list(TRUTH_FEATURE[self.family]),
                "effect_size_sd": EFFECT[self.family],
                "has_real_signal": self.family != "NULL_FAMILY",
                "n_sessions": self.n_sessions,
                "label": CONTROL_LABEL,
                "decision_power": "NONE_RESEARCH"}


def grade(*, family: str, detected: bool, detected_features: tuple,
          verdict: str) -> dict:
    """Score one exam family against its ground truth.

    SIMPLE_WEAK is deliberately near the noise floor: the CORRECT
    answer there is INSUFFICIENT_EVIDENCE, and calling it a discovery
    would be a false positive, not a triumph. A scientist is graded on
    knowing which questions its data cannot answer."""
    if family not in FAMILIES:
        raise ExamViolation(f"unknown family {family!r}")
    truth = TRUTH_FEATURE[family]
    real = family != "NULL_FAMILY"
    correct_feature = (not truth or
                       any(f in truth for f in detected_features))
    if family == "NULL_FAMILY":
        outcome = "TRUE_NEGATIVE" if not detected else "FALSE_POSITIVE"
    elif family == "SIMPLE_WEAK":
        outcome = ("APPROPRIATE_ABSTENTION" if not detected else
                   "DETECTED_AT_NOISE_FLOOR" if correct_feature
                   else "FALSE_POSITIVE")
    elif detected and correct_feature:
        outcome = "TRUE_POSITIVE"
    elif detected and not correct_feature:
        outcome = "DETECTED_WRONG_FEATURE"
    else:
        outcome = "FALSE_NEGATIVE"
    return {"kind": "exam_grade", "family": family,
            "has_real_signal": real,
            "effect_size_sd": EFFECT[family],
            "truth_features": list(truth),
            "detected": detected,
            "detected_features": list(detected_features),
            "verdict": verdict, "outcome": outcome,
            "label": CONTROL_LABEL,
            "decision_power": "NONE_RESEARCH"}


def power_report(grades: list) -> dict:
    """The detection curve, plus the specificity that must survive it.

    No single score: a true-positive rate is meaningless without the
    false-positive rate beside it, and both are meaningless without
    the effect size that produced them."""
    rows = {g["family"]: g for g in grades}
    real = [g for g in grades if g["has_real_signal"]
            and g["family"] != "SIMPLE_WEAK"]
    tp = sum(1 for g in real if g["outcome"] == "TRUE_POSITIVE")
    fn = sum(1 for g in real if g["outcome"] == "FALSE_NEGATIVE")
    wrong = sum(1 for g in real
                if g["outcome"] == "DETECTED_WRONG_FEATURE")
    nulls = [g for g in grades if not g["has_real_signal"]]
    fp = sum(1 for g in nulls if g["outcome"] == "FALSE_POSITIVE")

    curve = sorted(
        ({"family": g["family"], "effect_sd": g["effect_size_sd"],
          "outcome": g["outcome"]} for g in grades),
        key=lambda r: -r["effect_sd"])

    # A false positive on a KNOWN-EMPTY family is direct evidence of
    # permissiveness and dominates every other reading, including the
    # "we did not test enough real families" excuse.
    if fp:
        verdict = "OVER_PERMISSIVE"
    elif not real:
        verdict = "INSUFFICIENT_CONTROL_POWER"
    elif tp == 0:
        verdict = "OVER_CONSERVATIVE"
    elif fn == 0 and wrong == 0:
        verdict = "WELL_CALIBRATED_SCIENTIST"
    else:
        verdict = "FAMILY_DEPENDENT"

    return {"kind": "research_power_report",
            "label": CONTROL_LABEL,
            "detection_curve": curve,
            "true_positives": tp, "false_negatives": fn,
            "detected_wrong_feature": wrong,
            "false_positives_on_nulls": fp,
            "weak_family_outcome": rows.get(
                "SIMPLE_WEAK", {}).get("outcome"),
            "by_family": {f: rows[f]["outcome"] for f in rows},
            "verdict": verdict,
            "law": "a true-positive rate is meaningless without the "
                   "false-positive rate beside it, and both are "
                   "meaningless without the effect size that produced "
                   "them",
            "no_edge_authority": "POSITIVE_CONTROL_ONLY findings can "
                                 "never become EdgeDNA",
            "decision_power": "NONE_RESEARCH"}
