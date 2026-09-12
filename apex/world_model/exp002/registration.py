"""EXP-002 registration: frozen before any fit. Hash covers this module."""
from __future__ import annotations

import hashlib
from pathlib import Path

EXPERIMENT_ID = "ALPHA-EXP-002"
QUALIFICATION_REVISION = 2
QUALIFICATION_REVISION_NOTE = (
    "Revision 2 of the synthetic qualification was DESIGNED AFTER OBSERVING the failed "
    "revision-1 battery (results/exp002_synthetic_qualification.json, NOT QUALIFIED: the "
    "weak linear world was declared blocking and M1-M0 sat at the HAC threshold with an "
    "inference disagreement). Revision 1 is preserved as failed; its failure is not "
    "retroactively removed. Changes: a strong linear world is added as the blocking "
    "linear-detection check with the weak one kept unchanged as a diagnostic; the "
    "baseline-replacement verdict is removed and selection concerns the matched C-L "
    "comparison only; the bootstrap p-value estimator is declared as (k+1)/(B+1).")
PARENT = "ALPHA-EXP-001B"
PARENT_REGISTRATION_HASH = "b3930727334f24379f72df3919c98d689448b2f3f265b2fa6013559ee1bef5c9"
PARENT_RESULT = "NO_SIGNAL, t=0.7525, n=165958, run 20260909T003427Z-exp001b-914a30d3"

# ---- held constant from the parent: information set and target
FEATURES = ("ret_1", "ret_5", "rv_30")
HORIZON = "H_15M"
HORIZON_MINUTES = 15
TARGET = "log(close[t+15min] / close[t])"

# ---- arms
ARMS = ("M0", "M1", "S", "L", "C")
ARM_SPEC = {
    "M0": {"mean": "zero", "family": "GAUSSIAN", "dispersion": "registered k (EXP-001B, untouched)"},
    "M1": {"mean": "linear ret_1, ret_5 (registered _ols2)", "family": "GAUSSIAN",
           "dispersion": "registered k (untouched)"},
    "S":  {"mean": "zero", "family": "STUDENT_T", "dispersion": "shared (s*, nu*)"},
    "L":  {"mean": "linear ret_1, ret_5 (SVD, train-only centred/scaled basis)",
           "family": "STUDENT_T", "dispersion": "shared (s*, nu*)"},
    "C":  {"mean": "quadratic: 1, r1, r5, r1^2, r5^2, r1*r5 (SVD, train-only centred/scaled)",
           "family": "STUDENT_T", "dispersion": "shared (s*, nu*)"},
}
SHARED_REFERENCE = ("(s*, nu*) by two-parameter ML on fit-split LINEAR-mean residuals "
                    "standardised by rv_30; identical values used by S, L and C")
T_SCALE_LAW = "scale = rv_30 * s*; implied sd = scale * sqrt(nu/(nu-2)); variance is NOT matched across families"

# ---- estimation
NU_BOUNDS = (2.1, 50.0)
NU_LOWER_BOUND_POLICY = ("REFUSE. Declared model-domain policy: variance is finite at nu=2.1 "
                         "but the dispersion comparison is degenerate that close to 2.")
NU_UPPER_BOUND_POLICY = "LEGITIMATE near-Gaussian outcome; recorded as nu_at_upper_bound=True; run proceeds"
OPTIMIZER = "Nelder-Mead on (log s, log nu); init nu0=6, s0=std(z)*sqrt((nu0-2)/nu0); simplex step 0.1"
OPTIMIZER_STOP = "max |f_i - f_best| < 1e-8 and simplex diameter < 1e-8, or 500 iterations -> non-convergence REFUSED"
LSTSQ = "numpy.linalg.lstsq (SVD), rcond=1e-12; rank < p -> REFUSED (RANK_DEFICIENT); no regularisation"
RV_FLOOR = 1e-9
RV_FLOOR_POLICY = "rows with rv_30 < RV_FLOOR are refused at admission for ALL arms (pairing preserved)"
ZERO_VARIANCE_FEATURE_POLICY = "a basis column with zero fit-split variance -> REFUSED (scaling undefined)"

# ---- inference
DM_THRESHOLD = 2.0
HAC_LAG = HORIZON_MINUTES - 1
BOOT_BLOCK_SESSIONS = 5
BOOT_SENSITIVITY_SESSIONS = (1, 10)
BOOT_RESAMPLES = 10000
BOOT_SEED = 20260909
BOOT_P_THRESHOLD = 0.0228          # one-sided normal-theory equivalent of t > 2.0
BOOT_P_ESTIMATOR = "(k + 1) / (B + 1), k = centred exceedances of the observed mean, B = replicates"
BOOT_P_ESTIMATOR_NOTE = ("declared BEFORE the revision-2 run. Zero observed exceedances is not zero "
                         "probability: with B=10000 the smallest reportable p is 1/10001 ~ 1e-4. "
                         "Revision 1 reported the raw fraction k/B, which printed 0.0000; its records "
                         "are kept as they were and re-read under this estimator where cited.")
INFERENCE_RULE = ("HAC and the 5-session bootstrap must BOTH pass; disagreement is "
                  "NOT_SELECTED_INFERENCE_DISAGREEMENT, never a switch to the friendlier one")

# ---- gates
# Selection authority rests on ONE matched comparison. Comparisons against the
# registered Gaussian models are reported context: revision 1 showed they pass
# in every world, including the null, because the registered scale law is a
# mean-absolute-deviation ratio used as a standard deviation, so they add little
# discrimination here. A later baseline-replacement study may specify stronger
# dispersion comparators explicitly. No comparator family is added now.
GATES = {"G1": ("C", "L")}
REPORTED = {"R1": ("L", "S"), "R2": ("L", "M1"), "R3": ("S", "M0"), "R4": ("M1", "M0"),
            "R5": ("C", "M1"), "R6": ("C", "M0")}
OUTCOMES = {
    "MATCHED_IMPROVEMENT": "G1 (C-L) passes BOTH predeclared inferences: a candidate for later "
                           "confirmation of incremental predictive information. Not validated alpha.",
    "NOT_SELECTED": "G1 fails under both inferences: this quadratic specification did not "
                    "demonstrate improvement over the matched linear Student-t",
    "NOT_SELECTED_INFERENCE_DISAGREEMENT": "the two inferences disagree on G1; unresolved",
    "INVALID_NULL_CONTROL": "a required matched null assertion failed; the tournament is void",
}
REMOVED_IN_REVISION_2 = ("BASELINE_REPLACEMENT_CANDIDATE and MATCHED_IMPROVEMENT_ONLY: the compound "
                         "gates carried no selection authority worth having in this battery")

# ---- null control, stated precisely
N0 = {"name": "N0_BLOCK_PERMUTATION",
      "what_is_permuted": "the OUTCOME sequence y, in blocks of 20 consecutive evaluation rows, block order shuffled",
      "what_is_fixed": "every forecast (models are NOT refitted, forecasts are NOT recomputed); the state sequence including rv_30",
      "what_is_destroyed": "the row-level pairing of outcome with state, hence conditional mean AND conditional variance structure",
      "what_survives": "the marginal outcome distribution; the state sequence",
      "assertions": {"C-L": "NO_SIGNAL", "L-S": "NO_SIGNAL", "M1-M0": "NO_SIGNAL"},
      "not_asserted": "C-M1, C-M0, S-M0 (compound: mixed channels)",
      "block": 20,
      "framing": "a stress/control transformation evaluated on matched comparisons"}

# ---- splits (historical; not used by the synthetic qualification)
PERIODS = {"fit": ("2016-01-04", "2018-12-31"),
           "development": ("2019-01-01", "2019-12-31"),
           "observed": ("2020-01-01", "2021-12-31"),
           "evaluation": ("2022-01-01", "2024-12-31"),
           "reserve": ("2025-01-01", "2026-08-28")}
DEVELOPMENT_STATUS = "development data with prior exposure (inside EXP-001B's fitting window); never pristine"
OBSERVED_STATUS = "2020-2021 has been observed; secondary reporting only; no authority"

# ---- budget
FIT_BUDGET = {"market_data_fits": 5, "tuned_hyperparameters": 0, "refits_after_results": 0,
              "information_sets": 1, "horizons": 1,
              "synthetic_control_fits": 30,            # revision 2: 6 worlds x 5 arms
              "synthetic_control_fits_revision_1": 25, # retained in the cumulative record
              "synthetic_control_fits_cumulative": 55}

CALIBRATION_LAW = ("a log-likelihood gain is a DISTRIBUTIONAL-SCORE improvement. Calibration is a "
                   "separate claim requiring PIT and coverage at 0.05/0.50/0.95, reported for every arm.")
ECONOMICS = "NONE. Distributional only."


def registration_hash() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
