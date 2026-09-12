"""SYNTHETIC_GRADER_V0 -- compare a SEALED forecast to a sealed outcome.

THE ONE RULE OF GRADING
The grader takes a forecast and an outcome as two separate immutable
objects and never merges them. It records the forecast hash it was
given, grades, and records the forecast hash again. If they differ, the
grading is void: something touched the forecast after the answer was
known, and no score computed in that state means anything.

THE PREREGISTERED NULL RULE (frozen BEFORE any world was run)
For each evaluation sample i:
    d_i = logL_model(i) - logL_null(i)
Let m = mean(d), s = std(d) / sqrt(n).

    SIGNAL_DETECTED   iff   m > 0   and   m / s > Z_RULE
    NO_SIGNAL         otherwise

Z_RULE = 2.0. It is a constant in this file, chosen before S0 or S1
were run, and it is not adjusted if a control fails. Under a true null
this rule mis-fires roughly 2.3% of the time per test; that rate is
accepted and STATED, not hidden by re-seeding until it passes.

METRICS ARE DIAGNOSTICS, NOT OBJECTIVES
Nothing here is optimised. NLL, pinball, coverage and residual moments
describe how well a distribution matched a synthetic truth. They say
nothing about money and are not permitted to.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from apex.world_model.canonical import content_hash, strict_float
from apex.world_model.forecast import WorldModelForecast
from apex.world_model.targets import OutcomeRecord

GRADER_VERSION = "SYNTHETIC_GRADER_V0"
Z_RULE = 2.0                      # PREREGISTERED. Do not touch after S0.
NULL_RULE = ("SIGNAL_DETECTED iff mean(d) > 0 and mean(d)/stderr(d) > %.1f, "
             "d_i = logL_model - logL_null per evaluation sample" % Z_RULE)


class GradingViolation(Exception):
    pass


def _gauss_logpdf(y: float, mu: float, sigma: float) -> float:
    z = (y - mu) / sigma
    return -0.5 * z * z - math.log(sigma) - 0.5 * math.log(2 * math.pi)


def _pinball(y: float, q: float, level: float) -> float:
    return max(level * (y - q), (level - 1) * (y - q))


@dataclass(frozen=True)
class Grade:
    forecast_id: str
    forecast_hash_before: str
    forecast_hash_after: str
    outcome_hash: str
    outcome_known_time: float
    forecast_known_from: float
    grading_time: float
    target_value: float
    metrics: dict
    grader_version: str = GRADER_VERSION

    @property
    def grade_hash(self) -> str:
        return content_hash({
            "forecast_id": self.forecast_id,
            "forecast_hash": self.forecast_hash_before,
            "outcome_hash": self.outcome_hash, "metrics": self.metrics,
            "grader_version": self.grader_version})


def grade(forecast: WorldModelForecast, outcome: OutcomeRecord, *,
          grading_time: float) -> Grade:
    h_before = forecast.forecast_hash
    if outcome.outcome_known_time <= forecast.known_from:
        raise GradingViolation(
            "outcome became known at %r, forecast known_from is %r: this "
            "forecast could have seen its own answer"
            % (outcome.outcome_known_time, forecast.known_from))
    d = forecast.distribution.canonical()
    mu = strict_float(d["expected_return"], field="expected_return")
    sigma = strict_float(d["total_uncertainty"], field="total_uncertainty")
    y = strict_float(outcome.target_value, field="target_value")

    metrics = {
        "residual": y - mu,
        "abs_error": abs(y - mu),
        "squared_error": (y - mu) ** 2,
        "log_likelihood": _gauss_logpdf(y, mu, sigma),
        "standardised_residual": (y - mu) / sigma,
    }
    if d.get("quantiles"):
        metrics["pinball"] = {k: _pinball(y, v, float(k))
                              for k, v in d["quantiles"].items()}
    if d.get("predictive_intervals"):
        cov = {}
        for k, (lo, hi) in d["predictive_intervals"].items():
            cov[k] = 1.0 if lo <= y <= hi else 0.0
        metrics["interval_covered"] = cov
    if d.get("prob_return_gt_zero") is not None:
        p = d["prob_return_gt_zero"]
        o = 1.0 if y > 0 else 0.0
        eps = 1e-12
        metrics["brier"] = (p - o) ** 2
        metrics["log_loss"] = -(o * math.log(max(p, eps))
                                + (1 - o) * math.log(max(1 - p, eps)))

    h_after = forecast.forecast_hash
    if h_after != h_before:
        raise GradingViolation(
            "forecast hash changed during grading (%s -> %s): the "
            "forecast was mutated after its outcome was known. This "
            "grade is VOID." % (h_before[:16], h_after[:16]))
    return Grade(forecast_id=forecast.forecast_id,
                 forecast_hash_before=h_before, forecast_hash_after=h_after,
                 outcome_hash=outcome.outcome_hash,
                 outcome_known_time=outcome.outcome_known_time,
                 forecast_known_from=forecast.known_from,
                 grading_time=grading_time, target_value=y, metrics=metrics)


def aggregate(grades: list) -> dict:
    n = len(grades)
    if n == 0:
        raise GradingViolation("nothing to aggregate")
    ll = [g.metrics["log_likelihood"] for g in grades]
    res = [g.metrics["residual"] for g in grades]
    out = {"n": n, "nll": -sum(ll) / n,
           "mean_residual": sum(res) / n,
           "rmse": math.sqrt(sum(r * r for r in res) / n),
           "mae": sum(abs(r) for r in res) / n}
    if "interval_covered" in grades[0].metrics:
        for k in grades[0].metrics["interval_covered"]:
            out["coverage_%s" % k] = sum(
                g.metrics["interval_covered"][k] for g in grades) / n
    if "pinball" in grades[0].metrics:
        out["pinball"] = {k: sum(g.metrics["pinball"][k] for g in grades) / n
                          for k in grades[0].metrics["pinball"]}
    if "brier" in grades[0].metrics:
        out["brier"] = sum(g.metrics["brier"] for g in grades) / n
        out["log_loss"] = sum(g.metrics["log_loss"] for g in grades) / n
    return out


def null_rule(model_grades: list, null_grades: list) -> dict:
    """Apply the PREREGISTERED rule. Returns the verdict and the
    numbers behind it so nobody has to trust the label."""
    if len(model_grades) != len(null_grades) or not model_grades:
        raise GradingViolation("paired grades required")
    for a, b in zip(model_grades, null_grades):
        if a.outcome_hash != b.outcome_hash:
            raise GradingViolation(
                "paired comparison on DIFFERENT outcomes is meaningless")
    d = [a.metrics["log_likelihood"] - b.metrics["log_likelihood"]
         for a, b in zip(model_grades, null_grades)]
    n = len(d)
    m = sum(d) / n
    if n < 3:
        raise GradingViolation("rule needs >= 3 paired samples")
    var = sum((x - m) ** 2 for x in d) / (n - 1)
    se = math.sqrt(var / n) if var > 0 else 0.0
    z = (m / se) if se > 0 else (float("inf") if m > 0 else 0.0)
    verdict = "SIGNAL_DETECTED" if (m > 0 and z > Z_RULE) else "NO_SIGNAL"
    return {"rule": NULL_RULE, "z_rule": Z_RULE, "n": n,
            "mean_loglik_gain": m, "stderr": se, "z": z, "verdict": verdict,
            "false_positive_rate_under_null": "~0.023 per test at Z=2.0 "
                                              "(stated, not hidden)"}
