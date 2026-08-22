"""FORWARD DISTRIBUTION / CALIBRATION / OOD / UNCERTAINTY.

THE ARCHITECTURE IS BUILT NOW. THE NUMBERS ARE NOT EARNED YET.

That separation is the entire point of this module. Everything needed to
express a calibrated forward distribution exists here -- the estimator,
the regime conditioner, the OOD detector, the calibration scorer, the
uncertainty accounting -- and every one of them returns
PROBABILITY_NOT_ESTIMABLE until an explicit evidence gate opens.

The gate cannot be opened by an argument, a config flag, or an LLM. It
opens when prospective observations exist:

    prospective_n        >= 30
    distinct_sessions    >= 10
    distinct_regimes     >= 2
    distinct_subjects    >= 5
    OOD                  not OOD
    calibration          measured, Brier better than the base rate

A system that can emit "72%" before that is not a forecasting system,
it is a confidence generator. APEX has exactly zero prospective pattern
outcomes today, so today every answer here is NOT_ESTIMABLE -- and that
is the correct answer, not a limitation to work around.

decision_power: NONE_PATTERN_OBSERVATORY.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from apex.pattern_observatory import OBSERVATORY_POWER

NOT_ESTIMABLE = "PROBABILITY_NOT_ESTIMABLE"
UNCALIBRATED = "UNCALIBRATED"
CALIBRATED = "CALIBRATED"
INSUFFICIENT_SUPPORT = "INSUFFICIENT_SUPPORT"
OOD_BLOCKED = "OOD_BLOCKED"

# THE EVIDENCE GATE. Declared before any observation exists.
MIN_PROSPECTIVE_N = 30
MIN_DISTINCT_SESSIONS = 10
MIN_DISTINCT_REGIMES = 2
MIN_DISTINCT_SUBJECTS = 5
MIN_CALIBRATION_N = 50

QUESTIONS = ("p_up_15m", "p_down_15m", "p_up_60m", "p_down_60m", "p_range",
             "p_vol_expansion", "p_left_tail", "p_right_tail",
             "expected_move", "mae_distribution", "mfe_distribution",
             "time_to_event")


@dataclass(frozen=True)
class SupportProfile:
    prospective_n: int
    distinct_sessions: int
    distinct_regimes: int
    distinct_subjects: int
    historical_n: int = 0

    def gate(self) -> dict:
        checks = {
            "prospective_n": (self.prospective_n, MIN_PROSPECTIVE_N),
            "distinct_sessions": (self.distinct_sessions, MIN_DISTINCT_SESSIONS),
            "distinct_regimes": (self.distinct_regimes, MIN_DISTINCT_REGIMES),
            "distinct_subjects": (self.distinct_subjects, MIN_DISTINCT_SUBJECTS),
        }
        failing = {k: {"have": h, "need": n} for k, (h, n) in checks.items()
                   if h < n}
        return {"open": not failing, "failing": failing,
                "checks": {k: {"have": h, "need": n}
                           for k, (h, n) in checks.items()}}


@dataclass(frozen=True)
class ForwardDistribution:
    pattern_id: str
    family_id: str
    subject: str
    status: str
    answers: dict
    support: dict
    regime: str | None
    ood: str
    calibration: dict
    uncertainty: dict
    as_of: str
    known_from: str

    def as_dict(self) -> dict:
        return {"kind": "forward_distribution", **self.__dict__,
                "answers": dict(self.answers), "support": dict(self.support),
                "calibration": dict(self.calibration),
                "uncertainty": dict(self.uncertainty),
                "narrative_probability_forbidden": True,
                "decision_power": OBSERVATORY_POWER}


# ------------------------------------------------------------------ OOD
def detect_ood(current: dict, history: list, *, min_history: int = 100) -> dict:
    """Is this state inside the distribution we have actually seen?

    A probability computed from analogues that do not resemble the
    present is worse than no probability, because it carries the
    authority of arithmetic.
    """
    if len(history) < min_history:
        return {"status": "NOT_ESTIMABLE", "ood": "NOT_ESTIMABLE",
                "reason": f"history {len(history)} < {min_history}",
                "n_history": len(history)}
    import statistics
    dims, flagged = 0, []
    for k, v in current.items():
        if not isinstance(v, (int, float)):
            continue
        vals = [h[k] for h in history
                if isinstance(h.get(k), (int, float))]
        if len(vals) < min_history // 2:
            continue
        dims += 1
        sd = statistics.pstdev(vals)
        mean = statistics.fmean(vals)
        if sd <= 0:
            # A dimension that has NEVER varied and now differs is the
            # clearest out-of-distribution case there is -- skipping it
            # (the first draft did) makes the detector blindest exactly
            # where it should be loudest.
            if v != mean:
                flagged.append({"dimension": k, "z": None,
                                "reason": "zero-variance history; observed "
                                          f"{v} vs constant {mean}"})
            continue
        z = abs(v - mean) / sd
        if z > 3.0:
            flagged.append({"dimension": k, "z": round(z, 2)})
    if dims == 0:
        return {"status": "NOT_ESTIMABLE", "ood": "NOT_ESTIMABLE",
                "reason": "no comparable numeric dimensions"}
    return {"status": "COMPUTED", "ood": "OOD" if flagged else "IN_DISTRIBUTION",
            "dimensions_compared": dims, "flagged": flagged,
            "n_history": len(history)}


# ---------------------------------------------------------- calibration
def brier(predictions: list, outcomes: list) -> dict:
    """Brier score plus the base-rate reference it must beat.

    A forecaster that always predicts the base rate scores well and knows
    nothing; `skill_vs_base_rate` is the only number here worth reading.
    """
    n = len(predictions)
    if n != len(outcomes):
        raise ValueError("predictions and outcomes differ in length")
    if n < MIN_CALIBRATION_N:
        return {"status": INSUFFICIENT_SUPPORT, "n": n,
                "need": MIN_CALIBRATION_N, "brier": None}
    bs = sum((p - o) ** 2 for p, o in zip(predictions, outcomes)) / n
    base = sum(outcomes) / n
    bs_base = sum((base - o) ** 2 for o in outcomes) / n
    return {"status": "COMPUTED", "n": n, "brier": bs,
            "base_rate": base, "brier_of_base_rate": bs_base,
            "skill_vs_base_rate": bs_base - bs,
            "beats_base_rate": bs < bs_base}


def reliability(predictions: list, outcomes: list, *, bins: int = 10) -> dict:
    """Do the 70% predictions happen 70% of the time?"""
    if len(predictions) < MIN_CALIBRATION_N:
        return {"status": INSUFFICIENT_SUPPORT, "n": len(predictions)}
    buckets: dict = {}
    for p, o in zip(predictions, outcomes):
        b = min(int(p * bins), bins - 1)
        buckets.setdefault(b, []).append((p, o))
    rows, err = [], 0.0
    for b in sorted(buckets):
        vals = buckets[b]
        mp = sum(p for p, _ in vals) / len(vals)
        mo = sum(o for _, o in vals) / len(vals)
        rows.append({"bin": b / bins, "n": len(vals), "mean_predicted": mp,
                     "observed_frequency": mo, "gap": mp - mo})
        err += len(vals) * (mp - mo) ** 2
    return {"status": "COMPUTED", "bins": rows,
            "calibration_error": err / len(predictions)}


# --------------------------------------------------------------- engine
def estimate(*, pattern_id: str, family_id: str, subject: str,
             support: SupportProfile, regime: str | None,
             current_state: dict, history: list,
             prior_outcomes: list | None = None,
             calibration_predictions: list | None = None,
             calibration_outcomes: list | None = None,
             as_of, known_from) -> ForwardDistribution:
    """The only entry point. Refuses in every direction it can."""
    gate = support.gate()
    ood = detect_ood(current_state, history)

    cal = {"status": UNCALIBRATED}
    if calibration_predictions and calibration_outcomes:
        cal = brier(calibration_predictions, calibration_outcomes)
        if cal.get("status") == "COMPUTED":
            cal["reliability"] = reliability(calibration_predictions,
                                             calibration_outcomes)
            cal["calibration_status"] = (
                CALIBRATED if cal.get("beats_base_rate") else UNCALIBRATED)

    blockers = []
    if not gate["open"]:
        blockers.append(f"support gate closed: {list(gate['failing'])}")
    if ood.get("ood") == "OOD":
        blockers.append("state is out of distribution")
    if ood.get("ood") == "NOT_ESTIMABLE":
        blockers.append("OOD not estimable -- insufficient history")
    if cal.get("calibration_status") != CALIBRATED:
        blockers.append("no validated calibration for this family")

    if blockers:
        answers = {q: NOT_ESTIMABLE for q in QUESTIONS}
        status = (OOD_BLOCKED if ood.get("ood") == "OOD"
                  else INSUFFICIENT_SUPPORT)
    else:
        # The gate is open. Even here the estimate is EMPIRICAL -- the
        # observed frequency among prospective analogues -- never a model
        # output, because no model has earned the right to speak yet.
        outs = prior_outcomes or []
        up15 = sum(1 for o in outs if o.get("ret_15m", 0) > 0) / len(outs)
        up60 = sum(1 for o in outs if o.get("ret_60m", 0) > 0) / len(outs)
        answers = {q: NOT_ESTIMABLE for q in QUESTIONS}
        answers["p_up_15m"] = up15
        answers["p_down_15m"] = 1 - up15
        answers["p_up_60m"] = up60
        answers["p_down_60m"] = 1 - up60
        status = "EMPIRICAL_FREQUENCY"

    n = support.prospective_n
    return ForwardDistribution(
        pattern_id=pattern_id, family_id=family_id, subject=subject,
        status=status, answers=answers,
        support={**gate, "profile": support.__dict__}, regime=regime,
        ood=ood.get("ood", "NOT_ESTIMABLE"), calibration=cal,
        uncertainty={
            "sample_width": (None if n < 2 else round(1.0 / (n ** 0.5), 4)),
            "note": "1/sqrt(n) is a FLOOR on uncertainty, not a confidence "
                    "interval; regime and OOD uncertainty are not additive "
                    "with it and are reported separately",
            "regime_support": support.distinct_regimes,
            "blockers": blockers},
        as_of=str(as_of), known_from=str(known_from))
