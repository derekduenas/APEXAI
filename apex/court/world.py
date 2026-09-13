"""The declared synthetic world. FROZEN BEFORE ANY FLIGHT RUNS.

A control flight is only worth something if its fixture was declared in advance. A world tuned until it trades is
a search for parameters that produce green, not a test. The recipe, seeds and budget below are fixed here; any
revision is recorded in the run directory as a FIXTURE_REVISION with its reason."""
from __future__ import annotations

import math

RECIPE = "ORGANISM_COURT_WORLD_V1"
SEED = 20260913
FIT_BUDGET = 400                 # the FunnelEngine's own budget; not raised for this court
MIN_TRAIN_BARS = 400             # the engine's gate; not lowered for this court

DECLARED = {
    "recipe": RECIPE, "seed": SEED,
    "bars": "1-minute bars, deterministic LCG, drift and volatility declared per world",
    "law": ("SYNTHETIC. Proves ORCHESTRATION and CONNECTION only. It is not market data, not a backtest, and no "
            "number produced from it is evidence of edge, calibration or profitability."),
    "no_tuning": ("min_train_bars and fit_budget are the engine's own values, NOT lowered or raised to make a "
                  "flight pass. A flight that cannot reach a layer reports where it stopped."),
}


def _lcg(seed: int):
    s = seed & 0xFFFFFFFF
    while True:
        s = (1103515245 * s + 12345) & 0x7FFFFFFF
        yield s / 0x7FFFFFFF


def bars(*, n: int, end_epoch: float, start_px: float = 646.0, drift_bp_per_bar: float = 0.0,
         vol_bp_per_bar: float = 4.0, seed: int = SEED) -> list:
    """Deterministic 1-minute bars ending at `end_epoch`. Availability is always event_time + 60s, so the
    causality firewall sees a real availability clock rather than a convenient one."""
    g = _lcg(seed)
    out, px = [], float(start_px)
    for i in range(n):
        t = end_epoch - (n - i) * 60.0
        shock = (next(g) - 0.5) * 2.0 * vol_bp_per_bar / 10000.0
        px = px * (1.0 + drift_bp_per_bar / 10000.0 + shock)
        hi, lo = px * 1.0002, px * 0.9998
        out.append({"event_time": t, "available": t + 60.0, "bar_complete": t + 60.0, "receipt_time": t + 60.0,
                    "start": t, "open": round(px, 4), "high": round(hi, 4), "low": round(lo, 4),
                    "close": round(px, 4), "volume": 1000.0 + i, "vwap": round(px, 4), "source": "court-synthetic"})
    return out


WORLDS = {
    # A: a trending world with an affordable, liquid candidate
    "ELIGIBLE_TRADE": {"drift_bp_per_bar": 0.8, "vol_bp_per_bar": 4.0, "chain_ask": 2.45, "quote": (2.40, 2.50),
                       "exit_quote": (2.70, 2.80),
                       "why": "declared BEFORE running: a persistent upward drift with an affordable near-money ask"},
    # B: a world where nothing clears the declared rules -- the ask is far above any affordable envelope
    "MANDATORY_WAIT": {"drift_bp_per_bar": 0.8, "vol_bp_per_bar": 4.0, "chain_ask": 90.0, "quote": (89.0, 90.0),
                       "exit_quote": (89.0, 90.0),
                       "why": "declared BEFORE running: every contract is priced above the risk envelope's cap"},
}
