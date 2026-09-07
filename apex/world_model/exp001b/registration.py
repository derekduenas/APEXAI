"""EXP001B REGISTRATION -- frozen BEFORE any real row is read. Do not edit
after the first sealed forecast. Changing any value is a new experiment.

This registration SUPERSEDES ALPHA-EXP-001 (registration 1a3f55a5...),
which is preserved unchanged. No real outcome was consulted in drafting it:
every change below was motivated by a reproduced specification defect, not
by a result.
"""
from __future__ import annotations

import hashlib
import json

EXPERIMENT_ID = "ALPHA-EXP-001B"
REGISTRATION_VERSION = "EXP001B_REGISTRATION_V0"

SUPERSEDES = {
    "experiment": "ALPHA-EXP-001",
    "registration_hash": "1a3f55a522f7595f179033827ad10d87e873b7839f1cc08fb05624067c8f391c",
    "reproduced_defects": [
        "F1 forecast known_from was the bar OPEN, one minute before its inputs finished forming",
        "F2 outcome availability was the target bar's OPEN, not its completion",
        "F3 'regular session' was a fixed 13:30-20:00 UTC window: wrong across DST and early closes",
        "F4 the 15-minute horizon was 15 retained rows; missing minutes silently changed elapsed time",
        "F5 economics were computed on VALIDATION despite an evaluation-only registration",
        "F6 economics used close-to-close target returns, not the registered next-bar-open execution",
        "F7 'certified_1R' named rv_30 + spread, which is not a certified maximum loss",
    ],
    "real_outcomes_consulted": False,
    "evidence": "results/si002_reproductions.json (base 566600dca, disposable fixtures)",
}

# ---- what is being asked (unchanged from EXP-001 in substance)
HYPOTHESIS = ("Conditional on the last 1 and 5 one-minute returns and the "
              "trailing 30-bar realised volatility, the 15-minute forward "
              "log return of SPY during the NYSE regular session has a "
              "distribution that a volatility-scaled Gaussian with a fitted "
              "conditional mean predicts with higher out-of-sample log "
              "likelihood than the same Gaussian with zero mean.")
MECHANISM_IS_NOT_A_FACT = True

# ---- data
SOURCE = "history-b/etf_continuous (alpaca_sip_raw_1m)"
CORPUS_VERSION = "5c0d768b7ee2ea14"
INSTRUMENT = "SPY"

# ---- session: exchange-local, calendar-governed (NOT a UTC window)
SESSION = ("NYSE regular session in America/New_York wall time, 09:30 to 16:00, "
           "early closes 13:00, per apex.world_model.exchange_calendar; converted "
           "to UTC per date; bars outside [open, close) are dropped and counted; a "
           "bar whose exchange-local date differs from the file's session date is "
           "a refusal")
CALENDAR_VERSION = "NYSE_REGULAR_SESSION_CALENDAR_V0_2016_2026"
BAR_SECONDS = 60

# ---- clocks: six of them, kept apart
CLOCKS = {
    "event_time": "bar OPEN instant (vendor event_time_utc)",
    "bar_complete": "event_time + 60 s: the bar's close, when its OHLCV exist",
    "assumed_available": "= bar_complete. ASSUMED historical availability; this corpus carries no publication timestamp",
    "publication_time": "NOT_AVAILABLE for this corpus (recorded as None, never substituted)",
    "decision_time": "the forecast's known_from = assumed_available of the current bar",
    "outcome_available": "bar_complete of the target bar",
}
AVAILABILITY_BASIS = "ASSUMED_BAR_CLOSE"
AVAILABILITY_LIMITATION = ("This corpus does not establish historical publication or revision "
                           "timing. Results are conditional on the bar-close assumption.")

# ---- target and horizon: ELAPSED time, not row count
HORIZON = "H_15M"
HORIZON_MINUTES = 15
TARGET = "log(close[bar at event_time t+15min] / close[bar at t]); the t+15min bar must exist"
MISSING_BARS = ("no imputation. A row's features require the bars at every minute in "
                "[t-30min, t]; otherwise the row is refused (MISSING_FEATURE_BARS). A "
                "target requires the bar at exactly t+15min; otherwise the target is "
                "None (MISSING_TARGET_BAR). Nothing is forward-filled.")
EMBARGO_MINUTES = 15               # rows whose t+15min+15min reaches the close are excluded

# ---- features
FEATURE_SET_VERSION = "EXP001B_OBSERVABLE_FEATURES_V0"
FEATURES = ("ret_1", "ret_5", "rv_30")
WARMUP_MINUTES = 30
NOT_AVAILABLE_IN_CORPUS = ("spread_bps", "trade_count", "bid", "ask", "publication_time")

# ---- models: one baseline, one challenger. No search. (EXP-001's, reused)
M0 = {"id": "M0_VOL_SCALED_GAUSSIAN", "mean": "zero",
      "sigma": "rv_30 * k, k fit on TRAIN as mean(|y|)/mean(rv_30)"}
M1 = {"id": "M1_CONDITIONAL_GAUSSIAN", "mean": "a + b1*ret_1 + b5*ret_5, OLS on TRAIN",
      "sigma": "same as M0"}
SEARCH_BUDGET = {"model_families": 2, "feature_sets": 1, "hyperparameters_tuned": 0, "horizons": 1}

# ---- chronology (unchanged)
PERIODS = {
    "train":      ("2016-01-04", "2019-12-31"),
    "validation": ("2020-01-01", "2021-12-31"),
    "evaluation": ("2022-01-01", "2024-12-31"),   # SEALED; opened only by a separate decision
    "reserve":    ("2025-01-01", "2026-08-28"),   # SEALED; untouched
}

# ---- statistic and null
STATISTIC = "DEPENDENCE_AWARE_DM_HAC_V0"
DM_THRESHOLD = 2.0
HAC_LAG = HORIZON_MINUTES - 1
MIN_SAMPLES = 4 * (HAC_LAG + 1)
NULL_CONTROL = "N0_BLOCK_PERMUTATION: outcomes permuted across 20-row blocks; state kept"
PRIMARY_METRIC = "out-of-sample log likelihood differential, M1 minus M0"
VALIDATION_IS_DISTRIBUTIONAL_ONLY = True

# ---- economics: EVALUATION ONLY, registered execution convention
EXECUTION_MODEL = "NEXT_BAR_OPEN_PLUS_MODELLED_SPREAD"
EXECUTION_LEGS = ("entry at the OPEN of the bar at t+1min (the first bar after decision_time); "
                  "exit at the OPEN of the bar at t+16min (the first bar after the target bar); "
                  "each leg crosses half the modelled spread; a missing leg bar makes the row "
                  "NOT_EXECUTABLE (counted, not imputed)")
MODELLED_SPREAD_BPS = 2.0
EXPRESSIONS = ("CASH", "LONG_15M", "SHORT_15M")
ECONOMIC_STAGE = "EVALUATION only, after the statistical stage; never on validation"
RISK_CERTIFICATION = ("NONE in this experiment. No field named certified_1R is produced. "
                      "stop_distance_rv30_diagnostic = 1.0 * rv_30 is a DIAGNOSTIC "
                      "normalisation and is ineligible as certified 1R; certification is "
                      "only ever produced by apex.organism.risk_certificate.certify.")


def registration() -> dict:
    return {k: v for k, v in globals().items()
            if k.isupper() and not k.startswith("_")}


def registration_hash() -> str:
    return hashlib.sha256(json.dumps(registration(), sort_keys=True, default=str).encode()).hexdigest()
