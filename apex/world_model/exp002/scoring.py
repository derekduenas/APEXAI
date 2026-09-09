"""Scoring for every arm. Gaussian arms go through the UNTOUCHED grader; the
Student-t arms are scored here in the same Grade shape, so inference code is
shared and the protected grader is never modified."""
from __future__ import annotations

import math

from apex.world_model import grader
from apex.world_model.canonical import strict_float
from apex.world_model.grader import Grade, GradingViolation
from . import studentt as T


def grade_any(forecast, outcome, *, grading_time: float) -> Grade:
    if forecast.model_family == "GAUSSIAN":
        return grader.grade(forecast, outcome, grading_time=grading_time)
    if forecast.model_family != "STUDENT_T":
        raise GradingViolation("UNKNOWN_FAMILY: %s" % forecast.model_family)
    h_before = forecast.forecast_hash
    if outcome.outcome_known_time <= forecast.known_from:
        raise GradingViolation("outcome known at %r, forecast known_from %r"
                               % (outcome.outcome_known_time, forecast.known_from))
    d = forecast.distribution.canonical()
    meta = forecast.calibration_metadata
    mu = strict_float(d["expected_return"], field="expected_return")
    scale, nu = float(meta["scale"]), float(meta["nu"])
    sd = T.implied_sd(scale, nu)
    y = strict_float(outcome.target_value, field="target_value")
    metrics = {"residual": y - mu, "abs_error": abs(y - mu), "squared_error": (y - mu) ** 2,
               "log_likelihood": T.logpdf(y, mu, scale, nu),
               "standardised_residual": (y - mu) / sd,
               "pit": T.cdf(y, mu, scale, nu)}
    if d.get("quantiles"):
        metrics["pinball"] = {k: grader._pinball(y, v, float(k)) for k, v in d["quantiles"].items()}
    if d.get("predictive_intervals"):
        metrics["interval_covered"] = {k: 1.0 if lo <= y <= hi else 0.0
                                       for k, (lo, hi) in d["predictive_intervals"].items()}
    if d.get("prob_return_gt_zero") is not None:
        p, o, eps = d["prob_return_gt_zero"], 1.0 if y > 0 else 0.0, 1e-12
        metrics["brier"] = (p - o) ** 2
        metrics["log_loss"] = -(o * math.log(max(p, eps)) + (1 - o) * math.log(max(1 - p, eps)))
    if forecast.forecast_hash != h_before:
        raise GradingViolation("forecast mutated during grading")
    return Grade(forecast_id=forecast.forecast_id, forecast_hash_before=h_before,
                 forecast_hash_after=h_before, outcome_hash=outcome.outcome_hash,
                 outcome_known_time=outcome.outcome_known_time, forecast_known_from=forecast.known_from,
                 grading_time=grading_time, target_value=y, metrics=metrics)


def pit(forecast, y: float) -> float:
    """Probability integral transform of y under the forecast, any family."""
    d = forecast.distribution.canonical()
    mu = float(d["expected_return"])
    if forecast.model_family == "GAUSSIAN":
        sd = float(d["total_uncertainty"])
        return 0.5 * (1.0 + math.erf((y - mu) / (sd * math.sqrt(2.0))))
    meta = forecast.calibration_metadata
    return T.cdf(y, mu, float(meta["scale"]), float(meta["nu"]))


def coverage_hits(forecast, y: float) -> dict:
    """Whether y falls below the 0.05, 0.50 and 0.95 quantiles."""
    q = forecast.distribution.canonical()["quantiles"]
    return {lv: (1.0 if y <= q[lv] else 0.0) for lv in ("0.05", "0.5", "0.95")}
