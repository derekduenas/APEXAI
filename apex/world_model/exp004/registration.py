"""EXP-004 registration: OHLCV pressure proxy. Frozen before any fit, any
feature computation on historical data, or any admission request. The
registration hash covers this module's bytes. Prose contract:
docs/EXP004_REGISTRATION.md (R1-R13); this module is the machine-readable form
and is authoritative where the two could differ."""
from __future__ import annotations

import hashlib
from pathlib import Path

EXPERIMENT_ID = "ALPHA-EXP-004"
TITLE = "OHLCV pressure proxy: does clipped signed body-volume add forecast value beyond the product comparator?"
STATUS_AT_FREEZE = "DESIGN ONLY: nothing fitted, scored, implemented, or read from historical data"

# ---- lineage (records, not reinterpreted)
PARENTS = {
    "ALPHA-EXP-001B": {"registration_hash": "b3930727334f24379f72df3919c98d689448b2f3f265b2fa6013559ee1bef5c9",
                       "fit_window": ("2016-01-04", "2019-12-31"), "validation": ("2020-01-01", "2021-12-31"),
                       "verdict": "M1 - M0 = NO_SIGNAL, t=0.7525, n=165958"},
    "ALPHA-EXP-002":  {"registration_hash": "fe15f818129acfb09702cad70401b80f2bdd35af625c44a64800ffa197a3d3f2",
                       "fit_window": ("2016-01-04", "2018-12-31"), "development": ("2019-01-01", "2019-12-31"),
                       "observed": ("2020-01-01", "2021-12-31"),
                       "verdict": "INVALID_NULL_CONTROL; no model selected; development C-L t=-2.312 disclosed"},
    "ALPHA-EXP-003":  {"status": "WITHDRAWN before registration: orthogonalised increment is the same predictor as EXP-002 C (FWL)"},
}

# ---- periods and exposure
PERIODS = {
    "fit":         ("2016-01-04", "2018-12-31"),
    "development": ("2019-01-01", "2021-12-31"),   # EXPOSED by EXP-002 (2019 development; 2020-2021 observed)
    "evaluation":  ("2022-01-01", "2024-12-31"),   # SEALED; one disclosed 60-byte metadata read (EVALUATION_READ_INCIDENT_001)
    "reserve":     ("2025-01-01", "2026-08-28"),   # SEALED
}
DEVELOPMENT_STATUS = "EXPOSED_CANDIDATE_SCREEN: results are screens, grant no sealed access"
SEALED_NEVER_REQUESTED = ("evaluation", "reserve")
ADMISSION = "EXP-004 requires its own signed admission; no prior admission extends to it"
INSTRUMENT, SOURCE_FAMILY = "SPY", "alpaca_sip_raw_1m"
FIELDS = ("open", "high", "low", "close", "volume", "event_time_utc")

# ---- inherited definitions, PINNED by source and value (recording chosen behaviour, not changing it)
INHERITED = {
    "target": {"source": "apex.world_model.exp001b.registration.TARGET",
               "value": "log(close[bar at event_time t+15min] / close[bar at t]); the t+15min bar must exist; nothing forward-filled"},
    "horizon": {"source": "exp001b.registration.HORIZON/HORIZON_MINUTES", "value": ("H_15M", 15)},
    "bar_seconds": {"source": "exp001b.registration.BAR_SECONDS", "value": 60},
    "availability_clock": {"source": "exp001b.registration.AVAILABILITY_BASIS + bars.session_from_doc",
                           "value": "ASSUMED_BAR_CLOSE: bar_complete = assumed_available = event_time + 60 s; known_from = assumed_available of the feature bar; no publication timestamp exists in the corpus"},
    "warmup_minutes": {"source": "exp001b.registration.WARMUP_MINUTES", "value": 30},
    "embargo_minutes": {"source": "exp001b.registration.EMBARGO_MINUTES", "value": 15,
                        "meaning": "rows whose t+15min+15min reaches the session close are excluded"},
    "calendar": {"source": "exp001b.registration.CALENDAR_VERSION + exchange_calendar.session_bounds(require_verified=True)",
                 "value": "NYSE_REGULAR_SESSION_CALENDAR_V0_2016_2026"},
    "legacy_features": {"source": "exp001b.bars.observable_rows / FEATURE_SET_VERSION",
                        "value": ("ret_1", "ret_5", "rv_30"), "version": "EXP001B_OBSERVABLE_FEATURES_V0"},
    "rv_floor": {"source": "exp002.registration.RV_FLOOR", "value": 1e-9,
                 "policy": "rows with rv_30 < RV_FLOOR refused for ALL arms, pairing preserved"},
    "hac": {"source": "apex.world_model.inference (HAC_KERNEL, HAC_LAG = H-1)", "value": ("BARTLETT", 14),
            "note": "fixed inference choice motivated by the 15-bar target overlap; not a claim that dependence ends after 14 rows"},
    "bootstrap": {"source": "exp002.bootstrap.session_stationary_bootstrap + exp002.registration BOOT_*",
                  "value": {"expected_block_sessions": 5, "sensitivities": (1, 10), "resamples": 10000,
                            "seed": 20260909, "p_threshold": 0.0228, "p_estimator": "(k+1)/(B+1)"}},
    "dm_threshold": {"source": "exp002.registration.DM_THRESHOLD", "value": 2.0},
}

# ---- feature construction (R3)
WINDOW_BARS = 10
BODY = "B_i = (close_i - open_i)/(high_i - low_i) if high_i > low_i else 0; SIGNED BODY-TO-RANGE, not close-location"
BASELINE = {"definition": "Vbar(m) = fit-split MEDIAN volume at exchange-local session minute m",
            "min_support_sessions": 100, "estimated_on": "fit split only; frozen"}
FEATURES = {
    "Bbar": "(1/W) sum_i B_i",
    "P":    "sum_i V_i / sum_i Vbar(m_i)",
    "F":    "sum_i B_i V_i / sum_i Vbar(m_i)",
    "identity_raw": "F = Bbar*P + W*Cov_W(B,V)/sum_i Vbar(m_i), Cov_W with divisor W",
}
CLIPPING = {"rule": "per-feature clip at the fit-split 0.99 quantile of |x| (P one-sided, [0, q_P])",
            "quantile_convention": "the ceil(0.99*n)-th order statistic, 1-indexed, no interpolation",
            "constants": ("q_B", "q_P", "q_F"), "estimated_on": "fit split only; frozen",
            "consequence": "breaks the raw identity in the clipped tail; no covariance-only attribution is claimed"}

# ---- arms (R4)
ARMS = ("L", "A", "AX", "C")
ARM_BASIS = {
    "L":  ("ret_1", "ret_5"),
    "A":  ("ret_1", "ret_5", "Bbar~", "P~"),
    "AX": ("ret_1", "ret_5", "Bbar~", "P~", "Bbar~*P~"),
    "C":  ("ret_1", "ret_5", "Bbar~", "P~", "Bbar~*P~", "F~"),
}
LOCATION_FIT = {"method": "OLS via SVD lstsq", "rcond": 1e-12, "basis": "intercept + fit-split standardised columns",
                "coefficients": "every arm re-estimates all of its own coefficients",
                "nesting": "design spaces nested L<=A<=AX<=C; strictness NOT guaranteed; RANK_DEFICIENT and ZERO_VARIANCE_FEATURE are refused, never repaired",
                "theta_note": "theta on F~ is a partial association holding other regressors fixed; mu_C - mu_AX != theta*F~ in general"}

# ---- common row population and preprocessing order (R7 + finalisation item 1)
COMMON_ROWS = {
    "rule": "a row is eligible iff it satisfies the requirements of EVERY arm; eligibility computed once per row; all comparisons scored on the identical (session_date, event_time) key set",
    "applies_to": ("fit", "development"),
    "fit_population": "all four location fits, the clipping constants and both dispersion fits use the SAME eligible fit-row population; no arm-specific filtering",
    "requirements": ("legacy warm-up 30 min", "target bar exists", "embargo 15 min", "rv_30 >= RV_FLOOR",
                     "10 completed bars in the same session, none missing (MISSING_PRESSURE_BARS)",
                     "valid OHLC: high>=low, open&close in [low,high], finite, volume>=0 (INVALID_OHLC)",
                     "baseline support at every window minute", "sum Vbar > 0"),
    "zero_volume_present_bar": "VALID, contributes 0", "missing_bar": "row refused",
    "zero_range_bar": "B=0, counted and reported",
}
PREPROCESSING_ORDER = (
    "1 valid fit bars (calendar-verified sessions; malformed/impossible bars refused by name)",
    "2 minute-of-session volume baselines Vbar(m) from step-1 fit bars (median; support >= 100 sessions)",
    "3 eligible raw feature rows on the fit split under COMMON_ROWS (legacy + pressure requirements)",
    "4 clipping constants q_B, q_P, q_F from step-3 rows",
    "5 standardised design matrices per arm (fit-split column mean/sd) from step-3 rows with step-4 clipping",
    "6 location fits L, A, AX, C on the identical step-3 rows",
    "7 dispersion fits D0 then D1 on AX residuals over the identical step-3 rows",
    "development: steps 2,4,5-statistics are FROZEN from fit; development rows pass COMMON_ROWS once; features use only completed bars available by each forecast time",
)
FIT_PREPROCESSING_NOTE = "fit-window baselines and constants are training material, not forecasts available at earlier fit timestamps"

# ---- dispersion (R5, R6)
DISPERSION = {
    "reference_residuals": "z_i = (y_i - mu_AX(x_i)) / rv_30_i on the common eligible fit rows",
    "D0": {"objective": "J0(log s0, log nu) = sum_i [ log s0 - log t_nu(z_i/s0) ]", "free": ("log s0", "log nu"),
           "init": {"nu0": 6.0, "s0": "sd(z)*sqrt((nu0-2)/nu0)"}, "bounds": {"nu": (2.1, 50.0), "s": "> 0"}},
    "D1": {"objective": "a_i = log s1 + lambda*P~_i; J1(log s1, lambda) = sum_i [ a_i - log t_nu0(z_i*exp(-a_i)) ]",
           "free": ("log s1", "lambda"), "nu": "FROZEN at D0's nu0", "init": {"s1": "s0 from D0", "lambda": 0.0},
           "bounds": {"lambda": (-2.0, 2.0), "s": "> 0"}},
    "full_scoring_scale": "D0: rv_30*s0; D1: rv_30*s1*exp(lambda*P~); scored log-density includes -log(scale)",
    "identity_check": "J1(log s0, 0) at nu0 == J0(log s0, log nu0) to 1e-9 relative on the same residual vector; required before any fit is accepted",
    "optimizer": {"method": "Nelder-Mead as in exp002.studentt.fit_scale_nu", "alpha": 1.0, "gamma": 2.0, "rho": 0.5, "sigma": 0.5,
                  "simplex_step": 0.1, "max_iter": 500, "tol": 1e-8, "convergence": "objective spread < tol AND simplex diameter < tol"},
    "sharing": "(s0,nu0) identical across L,A,AX,C under D0; (s1,lambda,nu0) identical under D1; OLS locations reused across specs",
}
REFUSALS = {
    "residuals": "NO filtering: any non-finite residual -> NONFINITE_RESIDUALS; count < 100 -> INSUFFICIENT_RESIDUALS",
    "bound_contact_tolerance": 1e-3,
    "nu_lower_bound": "REFUSED (model-domain policy)", "nu_upper_bound": "accepted and recorded",
    "lambda_bounds": "REFUSED at either bound: a constrained estimate, refused as declared model-domain policy",
    "enforced_by": "apex/world_model/exp004/dispersion.py (fit_d0, fit_d1); the fitter reports contact, this module enforces",
    "finiteness": "accepted params must give finite objective and finite positive scale on every fit row and every eligible development row; violation refuses the run; no overflow-driven dropping, no fallback",
    "optimizer": "OPTIMIZER_NO_CONVERGENCE -> refused",
    "design": ("RANK_DEFICIENT", "ZERO_VARIANCE_FEATURE"),
}

# ---- inference and classification (R8-R10)
PRIMARY = {"comparison": ("C", "AX"), "estimand": "mean per-row log-density difference C - AX over common eligible development rows",
           "orientation": "positive = challenger scored better", "null": "E[d] <= 0"}
SECONDARY = {"S1": ("AX", "A"), "S2": ("A", "L"), "S3": ("C", "A")}
CONTEXTUAL = {"C_vs_L": ("C", "L"), "dispersion_improvement": "AX under D1 vs AX under D0",
              "bootstrap_sensitivities": (1, 10), "per_year": (2019, 2020, 2021)}
DECISION_RULE = {
    "hac_pass": "mean > 0 and t > 2.0", "boot_pass": "mean > 0 and p_hat < 0.0228",
    "required": ("HAC_D0", "BOOT_D0", "HAC_D1", "BOOT_D1"),
    "SELECTED": "all four pass", "NOT_SELECTED": "otherwise",
    "flags_independent": {"INFERENCE_DISAGREEMENT_D0": "HAC_D0 != BOOT_D0", "INFERENCE_DISAGREEMENT_D1": "HAC_D1 != BOOT_D1",
                          "SPECIFICATION_SENSITIVE": "(HAC_D0 and BOOT_D0) != (HAC_D1 and BOOT_D1)"},
    "integrity_precedence": "any integrity control failure or R6 refusal -> INTEGRITY_FAILURE (or the specific refusal); no statistical classification; artifact preserved",
}
INTERVALS = {"hac": "mean +/- 1.96*se_HAC",
             "bootstrap": "two-sided 95% PERCENTILE interval of raw replicate means; bounds = ceil(0.025*B)-th and ceil(0.975*B)-th order statistics, 1-indexed, no interpolation; boot_se reported but never presented as the bootstrap interval; p_hat decides"}
BOOTSTRAP_ESTIMAND = ("m* = sum_j D_{I_j} / sum_j N_{I_j}: pooled per-row mean as a ratio of session sums to session counts; "
                      "justification concerns the JOINT sequence of per-session (sum, count) pairs being approximately stationary "
                      "with dependence covered by geometric run lengths; NOT session exchangeability")
BOOTSTRAP_INTERFACE = ("the existing session_stationary_bootstrap returns mean, boot_se, exceedances, p_hat and pass but NOT the "
                       "replicate means; EXP-004 requires a reporting extension or adapter that exposes the replicate means for the "
                       "percentile interval. Equivalence checks must show the extension preserves the existing resampling sequence "
                       "(same seed -> same draws), p_hat and pass decision exactly. 'Unchanged' describes the statistical calculation, "
                       "not the current return object")
MULTIPLICITY = {"primary": "no adjustment; decides selection",
                "secondary_family": "six hypotheses: S1,S2,S3 x {D0,D1}; Holm SEPARATELY per inference method (six HAC p-values; six bootstrap p_hat); all twelve adjusted values reported; none affects selection",
                "contextual": "reported always; unadjusted; no authority"}

# ---- budget (R11)
BUDGET = {"baseline_estimations": 1, "clipping_constants": 3, "location_fits": 4, "dispersion_fits": 2,
          "total_fit_split_estimations": 10, "refits": 0,
          "development_evaluations": "1 pooled primary + 3 fixed per-year summaries",
          "design_variants_in_reserve": 0, "sealed_openings": 0, "economics": "NONE"}

# ---- implementation checks required before any admission request (R12)
IMPLEMENTATION_CHECKS = ("N1 identical close paths -> identical legacy inputs, different F",
                         "N2 identical Bbar,P -> different F", "N3 identical F: one dominant bar vs ten uniform bars",
                         "N4 availability: features recomputed from prior completed bars only",
                         "N5 FWL distinctness of C from AX out of sample", "N6 dispersion identity check (R5)",
                         "N7 common-row-key identity across all comparisons under induced pressure refusals",
                         "N8 bootstrap adapter equivalence: same seed -> same replicate sequence, p_hat, pass")
CHECK_AUTHORITY = "fixtures establish representation and computation only; not predictive value, size or power; a later-discovered defect CAN invalidate the scientific use of an artifact already produced"

# ---- what a pass means (R13)
PASS_MEANING = ("on the EXPOSED development pool, adding F~ to a location forecast already containing the legacy features, "
                "both ingredients and their product produced a better distributional score by changing the location forecast "
                "while holding scale and tail shape fixed, under both dispersion specifications and both inference methods. "
                "Exposed-data candidate screen. Not: covariance-only attribution, better conditional mean under misspecification, "
                "metaorder detection, temporary impact, causation, generalisation beyond 2021, tradability")
OPTIONS_CONTRIBUTION = ("evidence that a defined OHLCV state changes the distributional score of the 15-minute location forecast, "
                        "and separately whether a pressure-conditioned scale improves the score; NOT direction/magnitude evidence. "
                        "Missing before options use: option prices/quotes, IV changes, spreads, contract selection, fees, exercise "
                        "mechanics, capacity, portfolio risk. No profit computed; no broker path")
ECONOMICS = "NONE. Distributional only."


def registration_hash() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
