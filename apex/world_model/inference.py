"""DEPENDENCE_AWARE_DM_HAC_V0 -- the repaired decision statistic.

WHY THIS FILE EXISTS: WM-STAT-001
NULL_COURT_V0 (WM-0E) convicted the WM-0D decision rule. That rule
divided mean(d) by an iid standard error, where

    d_t = logL_M0(y_t) - logL_null(y_t)

is the per-sample log-likelihood differential and y_t is a 15-step
forward return. Adjacent targets share 14 of their 15 price increments,
so adjacent d_t are strongly serially dependent wherever the temporal
structure of the data survives. Measured on the failed N1 cells: lag-1
autocorrelation 0.76-0.92, effective sample size ~6% of nominal. The
iid stderr was ~4x too small, the threshold of 2.0 was ~0.5 in true
units, and N1 produced 6/25 false detections against 0.58 expected.

N1 did its job. It is not a bad null because it failed the old
detector; it is the one null that kept BOTH sides' path dependence
while carrying zero information, which is exactly the shape a real
market null takes. N2/N3 looked healthier only because they destroyed
the dependence (rho_1 ~ 0.02-0.06); that does not validate iid
inference.

THE REPAIR
A Diebold-Mariano-style test on the loss differential with a
Newey-West / HAC long-run variance (Bartlett kernel). This is the
estimator matched to the problem: comparing forecast losses whose
multi-step errors overlap.

    t = mean(d) / sqrt(LRV / n)
    LRV = gamma_0 + 2 * sum_{k=1}^{L} (1 - k/(L+1)) * gamma_k

THE LAG IS DERIVED, NOT CHOSEN
    L = H - 1
because H-step outcomes at adjacent steps share up to H-1 future
increments. For the registered H_15M target, L = 14. It comes from the
target definition (TARGET_HORIZON_STEPS), not from N1's numbers, and
this module refuses to run with any other lag.

WHAT L = H-1 DOES NOT DO (read this before generalising)
It addresses the DETERMINISTIC dependence created by label overlap.
Model forecasts, latent synthetic state (S1's regime z_t has its own
0.96 persistence) and path structure can create dependence beyond H-1.
A synthetic H=15 job passing under this statistic says the estimator
handles the overlap it was built for. It does NOT establish the
real-market inference contract: real A0 evaluation will still need
symbol clustering, session clustering, purging and its own
dependence-aware inference, derived for that job.

THRESHOLD
The DM/HAC statistic is asymptotically N(0,1) under the null, so the
pre-existing one-sided decision concept is retained unchanged:
threshold 2.0, nominal alpha = 1 - Phi(2.0) = 0.02275. No threshold
search was performed; a test asserts DM_THRESHOLD == grader.Z_RULE.

ORIENTATION
Positive means M0 improves on the null. This is the existing WM-0D
orientation (d = logL_M0 - logL_null; higher log-likelihood = lower
loss), documented here so nobody has to re-derive the sign.
"""
from __future__ import annotations

import hashlib
import math
from pathlib import Path
from statistics import NormalDist

from apex.world_model.canonical import content_hash
from apex.world_model.grader import GradingViolation, Z_RULE
from apex.world_model.targets import TARGET_HORIZON, TARGET_HORIZON_STEPS

INFERENCE_VERSION = "DEPENDENCE_AWARE_DM_HAC_V0"

# ---- the defect this repairs; permanent identity ---------------------
WM_STAT_001 = {
    "defect_id": "WM-STAT-001",
    "name": "IID_INFERENCE_INVALID_FOR_OVERLAPPING_FORECAST_LOSS",
    "discovered_by": "NULL_COURT_V0, control N1 (FORWARD_TIME_DISPLACEMENT)",
    "sittings": ["COURT-a4c366b64b0d", "COURT-0d4063653ce6",
                 "COURT-bad6d1f1cff0"],
    "mechanism": [
        "forecast horizon = 15 steps",
        "adjacent targets overlap by 14 increments",
        "loss differential d_t is serially dependent (rho_1 0.76-0.92 on N1)",
        "iid stderr understates uncertainty (~4x; n_eff/n ~ 0.06)",
        "N1 preserved temporal structure on both sides and exposed it",
        "N2/N3 looked healthier because they DESTROYED the dependence; "
        "that does not validate iid inference"],
    "observed": "N1 6/25 false detections vs 0.58 expected, in all three "
                "sittings; N0/N3 fluctuated 1-5 of 25 across re-keyings",
    "status_synthetic_h15": "OPEN until NULL_COURT_V1_DEPENDENCE_AWARE "
                            "passes on fresh seeds",
    "status_real_market": "OPEN -- WORLD_MODEL_PHASE3_BLOCKER_NEGATIVE_"
                          "CONTROL is not touched by this repair",
}

# ---- the statistic's frozen parameters ------------------------------
HAC_KERNEL = "BARTLETT"
HAC_LAG = TARGET_HORIZON_STEPS - 1          # L = H - 1, DERIVED
HAC_LAG_DERIVATION = ("L = H - 1 = %d - 1 = %d: adjacent H-step outcomes "
                      "share up to H-1 future increments"
                      % (TARGET_HORIZON_STEPS, HAC_LAG))
DM_THRESHOLD = 2.0                          # RETAINED from Z_RULE, not searched
NOMINAL_ALPHA_ONE_SIDED = 1.0 - NormalDist().cdf(DM_THRESHOLD)   # 0.02275
STATISTIC_ORIENTATION = ("d_t = logL_M0(y_t) - logL_null(y_t); positive "
                         "means M0 improves on the null (higher "
                         "log-likelihood = lower loss)")
VARIANCE_FORMULA = ("LRV = g0 + 2*sum_{k=1..L} (1 - k/(L+1)) g_k, "
                    "g_k = (1/n) sum_{t=k+1..n} (d_t - m)(d_{t-k} - m); "
                    "t = m / sqrt(LRV / n)")
MIN_SAMPLES_FACTOR = 4                      # refuse n < 4*(L+1)

LIMITATION = ("L = H-1 addresses DETERMINISTIC label overlap only. Model "
              "forecasts, latent synthetic state and path structure may "
              "generate dependence beyond H-1. This synthetic repair does "
              "NOT establish the real-market inference contract; real A0 "
              "evaluation needs symbol/session clustering, purging and "
              "its own dependence-aware inference.")

NON_OVERLAP_VERSION = "NON_OVERLAP_ROBUSTNESS_V0"
NON_OVERLAP_ANCHOR = 0                      # first evaluation sample; fixed
NON_OVERLAP_ROLE = ("SECONDARY DIAGNOSTIC ONLY. Cannot rescue a failed "
                    "primary HAC result. Never averaged with the primary.")


class InferenceViolation(ValueError):
    pass


def _source_hash() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def inference_contract() -> dict:
    """Everything the statistic commits to, for the court hash."""
    return {"inference_version": INFERENCE_VERSION,
            "repairs": WM_STAT_001["defect_id"],
            "test": "Diebold-Mariano loss-differential, HAC variance",
            "horizon": TARGET_HORIZON, "horizon_steps": TARGET_HORIZON_STEPS,
            "hac_kernel": HAC_KERNEL, "hac_lag": HAC_LAG,
            "hac_lag_derivation": HAC_LAG_DERIVATION,
            "variance_formula": VARIANCE_FORMULA,
            "orientation": STATISTIC_ORIENTATION,
            "threshold": DM_THRESHOLD,
            "reference_distribution": "N(0,1) asymptotic under H0",
            "nominal_alpha_one_sided": NOMINAL_ALPHA_ONE_SIDED,
            "threshold_search_performed": False,
            "limitation": LIMITATION,
            "implementation_sha256": _source_hash()}


def paired_differentials(model_grades: list, null_grades: list) -> list:
    """d_t in evaluation order. Refuses unpaired or mismatched outcomes."""
    if len(model_grades) != len(null_grades) or not model_grades:
        raise GradingViolation("paired grades required")
    for a, b in zip(model_grades, null_grades):
        if a.outcome_hash != b.outcome_hash:
            raise GradingViolation(
                "paired comparison on DIFFERENT outcomes is meaningless")
    return [a.metrics["log_likelihood"] - b.metrics["log_likelihood"]
            for a, b in zip(model_grades, null_grades)]


def autocovariances(d: list, max_lag: int) -> list:
    """gamma_0..gamma_L with the 1/n convention (guarantees a PSD
    Bartlett long-run variance)."""
    n = len(d)
    m = sum(d) / n
    c = [x - m for x in d]
    out = []
    for k in range(max_lag + 1):
        s = 0.0
        for t in range(k, n):
            s += c[t] * c[t - k]
        out.append(s / n)
    return out


def hac_long_run_variance(d: list, lag: int) -> float:
    """Newey-West long-run variance with Bartlett weights 1 - k/(L+1)."""
    g = autocovariances(d, lag)
    lrv = g[0]
    for k in range(1, lag + 1):
        lrv += 2.0 * (1.0 - k / (lag + 1.0)) * g[k]
    return lrv


def dm_hac_statistic(d: list, *, lag: int = HAC_LAG) -> dict:
    """The primary statistic on a differential sequence."""
    if lag != HAC_LAG:
        raise InferenceViolation(
            "HAC lag is DERIVED (L = H-1 = %d); %d was passed" % (HAC_LAG, lag))
    n = len(d)
    if n < MIN_SAMPLES_FACTOR * (lag + 1):
        raise InferenceViolation(
            "n=%d too small for lag %d (need >= %d)" % (n, lag,
                                                        MIN_SAMPLES_FACTOR * (lag + 1)))
    m = sum(d) / n
    lrv = hac_long_run_variance(d, lag)
    iid_var = sum((x - m) ** 2 for x in d) / (n - 1)
    if lrv <= 0.0:
        raise InferenceViolation("non-positive long-run variance (%.3e)" % lrv)
    se = math.sqrt(lrv / n)
    t = m / se
    return {"n": n, "mean": m, "hac_lrv": lrv, "hac_se": se, "t": t,
            "iid_se": math.sqrt(iid_var / n) if iid_var > 0 else 0.0,
            "se_inflation_vs_iid": (se / math.sqrt(iid_var / n))
                                   if iid_var > 0 else float("inf"),
            "lag": lag, "kernel": HAC_KERNEL}


def dm_hac_rule(model_grades: list, null_grades: list) -> dict:
    """Apply the PRIMARY decision rule. Same interface as grader.null_rule
    so the court can swap statistics without touching the pipeline."""
    d = paired_differentials(model_grades, null_grades)
    s = dm_hac_statistic(d)
    verdict = ("SIGNAL_DETECTED" if (s["mean"] > 0 and s["t"] > DM_THRESHOLD)
               else "NO_SIGNAL")
    return {"rule": INFERENCE_VERSION, "threshold": DM_THRESHOLD,
            "n": s["n"], "mean_loglik_gain": s["mean"], "t": s["t"],
            "hac_se": s["hac_se"], "iid_se": s["iid_se"],
            "se_inflation_vs_iid": s["se_inflation_vs_iid"],
            "lag": s["lag"], "kernel": s["kernel"], "verdict": verdict}


def non_overlap_rule(model_grades: list, null_grades: list, *,
                     horizon: int = TARGET_HORIZON_STEPS,
                     anchor: int = NON_OVERLAP_ANCHOR) -> dict:
    """SECONDARY: iid rule on d_t at t = anchor, anchor+H, anchor+2H, ...
    where deterministic label overlap is absent by construction. Not
    allowed to rescue the primary; persisted separately; never averaged."""
    if anchor != NON_OVERLAP_ANCHOR:
        raise InferenceViolation("the non-overlap anchor is fixed at %d"
                                 % NON_OVERLAP_ANCHOR)
    d = paired_differentials(model_grades, null_grades)[anchor::horizon]
    n = len(d)
    if n < 3:
        raise InferenceViolation("non-overlap subset too small (%d)" % n)
    m = sum(d) / n
    var = sum((x - m) ** 2 for x in d) / (n - 1)
    se = math.sqrt(var / n) if var > 0 else 0.0
    z = (m / se) if se > 0 else (float("inf") if m > 0 else 0.0)
    verdict = "SIGNAL_DETECTED" if (m > 0 and z > DM_THRESHOLD) else "NO_SIGNAL"
    return {"rule": NON_OVERLAP_VERSION, "role": NON_OVERLAP_ROLE,
            "spacing": horizon, "anchor": anchor, "n": n,
            "mean_loglik_gain": m, "z": z, "verdict": verdict}


def content_identity() -> str:
    return content_hash(inference_contract())
