"""EXP001 REGISTRATION -- frozen BEFORE any evaluation. Do not edit after
the first sealed forecast is written. Changing any value below is a new
experiment with a new id."""
from __future__ import annotations

import hashlib
import json

EXPERIMENT_ID = "ALPHA-EXP-001"
REGISTRATION_VERSION = "EXP001_REGISTRATION_V0"

# ---- what is being asked
HYPOTHESIS = ("Conditional on the last 1 and 5 one-minute returns and the "
              "trailing 30-bar realised volatility, the 15-minute forward "
              "log return of SPY during the regular session has a "
              "distribution that a volatility-scaled Gaussian with a fitted "
              "conditional mean predicts with higher out-of-sample log "
              "likelihood than the same Gaussian with zero mean.")
MECHANISM_PLAUSIBLE = ("Short-horizon serial dependence in index returns is "
                       "weak and widely known; where it exists it is small "
                       "relative to the spread. The plausible reason it is not "
                       "fully priced is that it is not worth anyone's spread "
                       "to price it -- which is also why it may not be worth "
                       "ours. That is the point of the economic stage.")
MECHANISM_IS_NOT_A_FACT = True

# ---- data
SOURCE = "history-b/etf_continuous (alpaca_sip_raw_1m)"
CORPUS_VERSION = "5c0d768b7ee2ea14"
INSTRUMENT = "SPY"
SESSION_UTC = ("13:30", "20:00")           # regular session only
CUTOFF_CONVENTION = "bar CLOSE at time t; the forecast may use bars with event_time <= t"

# ---- target and horizon (the laboratory's frozen horizon, reused)
HORIZON = "H_15M"
HORIZON_STEPS = 15
TARGET = "log(close[t+15] / close[t])"

# ---- features: observable-only. The laboratory's frozen set includes
# spread and trade_count, which this corpus does not carry, and its own law
# forbids zero-filling a missing column. So EXP001 declares its own set.
FEATURE_SET_VERSION = "EXP001_OBSERVABLE_FEATURES_V0"
FEATURES = ("ret_1", "ret_5", "rv_30")
WARMUP_BARS = 30
NOT_AVAILABLE_IN_CORPUS = ("spread_bps", "trade_count", "bid", "ask")

# ---- models: one baseline, one challenger. No search.
M0 = {"id": "M0_VOL_SCALED_GAUSSIAN", "mean": "zero",
      "sigma": "rv_30 * k, k fit on TRAIN as mean(|y|)/mean(rv_30)"}
M1 = {"id": "M1_CONDITIONAL_GAUSSIAN", "mean": "a + b1*ret_1 + b5*ret_5, OLS on TRAIN",
      "sigma": "same as M0"}
SEARCH_BUDGET = {"model_families": 2, "feature_sets": 1, "hyperparameters_tuned": 0}

# ---- chronology. Sealed periods are never read by fitting.
PERIODS = {
    "train":      ("2016-01-04", "2019-12-31"),
    "validation": ("2020-01-01", "2021-12-31"),
    "evaluation": ("2022-01-01", "2024-12-31"),   # SEALED until registration is frozen
    "reserve":    ("2025-01-01", "2026-08-28"),   # SEALED; untouched by EXP001
}
EMBARGO_BARS = HORIZON_STEPS                       # purge across every boundary
OVERLAP = "adjacent targets share 14 of 15 increments; dependence-aware statistic"

# ---- statistic and null (the laboratory's, unchanged)
STATISTIC = "DEPENDENCE_AWARE_DM_HAC_V0"
DM_THRESHOLD = 2.0
HAC_LAG = HORIZON_STEPS - 1
MIN_SAMPLES = 4 * (HAC_LAG + 1)
NULL_CONTROL = "N0_BLOCK_PERMUTATION: outcomes permuted across 20-bar blocks; state kept"
PRIMARY_METRIC = "out-of-sample log likelihood differential, M1 minus M0"
SECONDARY_METRICS = ("pinball loss at 0.05/0.5/0.95", "PIT calibration")

# ---- economics
EXECUTION_MODEL = "NEXT_BAR_OPEN_PLUS_MODELLED_SPREAD"
MODELLED_SPREAD_BPS = 2.0            # crossed on entry AND exit; cited from day_trader.py
EXPRESSIONS = ("CASH", "LONG_15M", "SHORT_15M")
STOP = "1.0 * rv_30 below/above entry; certified 1R = stop distance + full round-trip spread"
ECONOMIC_TEST = ("On EVALUATION only, after the statistical stage: mean after-cost "
                 "return of the selected expression, with a dependence-aware "
                 "standard error, versus CASH = 0.")
MARKET_BENCHMARK = ("Executable price range = last close +/- modelled half-spread. "
                    "Option-implied distribution at 15 minutes: NOT_ESTIMABLE from "
                    "the sources on box; not claimed.")

# ---- criteria, frozen
FAIL_STATISTICAL = "DM-HAC z <= 2.0 on VALIDATION -> NO_SIGNAL. Evaluation is not opened."
FAIL_ECONOMIC = "mean after-cost return of the best non-cash expression <= 0 -> NO_OPPORTUNITY"
PASS = ("z > 2.0 on validation AND z > 2.0 on evaluation AND after-cost mean > 0 with "
        "z_econ > 2.0 on evaluation. Even then: 'historically evaluated', not 'validated'.")
NULL_MUST = "N0 must produce NO_SIGNAL. If it does not, the harness is broken and nothing counts."

# ---- compute
COMPUTE = {"bars_train": "~390k", "runtime": "minutes, single process", "memory": "< 1 GiB"}


def registration() -> dict:
    return {k: v for k, v in globals().items()
            if k.isupper() and not k.startswith("_")}


def registration_hash() -> str:
    return hashlib.sha256(json.dumps(registration(), sort_keys=True,
                                     default=str).encode()).hexdigest()
