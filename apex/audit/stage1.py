"""STAGE 1 — data intake -> PULSE -> Twin, inspected value by value.

THE FIXTURE IS FROZEN BEFORE EXECUTION and uses values whose expected results can be computed by hand:
1-minute bars rising by exactly $0.10 from $600.00, availability exactly event_time + 60s.

    last_bar_close  = the close of the newest bar whose availability <= as_of
    ret_15          = LOG return, ln(close(t) / close(t-15min)), over COMPLETED, AVAILABLE bars only

CORRECTION MADE DURING THE AUDIT: the first expected formula here was the SIMPLE return, which disagreed with the
Twin at the 6th decimal (0.00249004 vs 0.00248694). The Twin was right and the audit's expectation was wrong --
ret_15 is a log return. Recorded rather than quietly amended, because an audit that silently adopts the system's
answer has stopped being an audit.

Both are recomputed here from the raw fixture, independently of the Twin, and compared."""
from __future__ import annotations

FIXTURE = "SEQUENTIAL_AUDIT_STAGE1_V1"
START_PX = 600.00
STEP_PX = 0.10
BAR_S = 60.0
T0 = 1_789_000_020.0          # the declared scan instant
N = 40


def frozen_bars(n: int = N, *, t0: float = T0) -> list:
    """Bar i closes at START_PX + i*STEP_PX. Bar i is available at its event_time + 60s.
    The NEWEST bar is event_time = t0 - 60 and available exactly at t0."""
    out = []
    for i in range(n):
        t = t0 - (n - i) * BAR_S
        px = round(START_PX + i * STEP_PX, 2)
        out.append({"event_time": t, "available": t + BAR_S, "bar_complete": t + BAR_S, "receipt_time": t + BAR_S,
                    "start": t, "open": px, "high": round(px + 0.05, 2), "low": round(px - 0.05, 2),
                    "close": px, "volume": 1000.0, "vwap": px, "source": "audit-frozen"})
    return out


def expected_last_bar_close(bars: list, as_of: float):
    avail = [b for b in bars if b["available"] <= as_of]
    return max(avail, key=lambda b: b["event_time"])["close"] if avail else None


def expected_ret_15(bars: list, as_of: float):
    """close(t)/close(t-15min) - 1 over available, completed bars. Returns None when the window is not covered."""
    avail = sorted([b for b in bars if b["available"] <= as_of], key=lambda b: b["event_time"])
    if not avail:
        return None
    last = avail[-1]
    want = last["event_time"] - 15 * BAR_S
    base = next((b for b in avail if b["event_time"] == want), None)
    if base is None:
        return None
    import math
    return math.log(last["close"] / base["close"])


# ------------------------------------------------------------------ adversarial ingestion inputs
def adversarial(bars: list, *, t0: float = T0) -> list:
    """Each case is fed to the REAL adapter. The audit harness does NOT pre-filter them."""
    good = bars[-1]
    return [
        ("FUTURE_AVAILABILITY", {**good, "event_time": t0 + 600.0, "available": t0 + 660.0},
         "available after the scan instant"),
        ("MALFORMED_PRICE", {**good, "close": float("nan")}, "close is NaN"),
        ("NEGATIVE_PRICE", {**good, "close": -5.0}, "close is negative"),
        ("MISSING_TIMESTAMP", {k: v for k, v in good.items() if k != "event_time"}, "no event_time"),
        ("DUPLICATE_CONFLICTING", {**good, "close": good["close"] + 5.0}, "same event_time, different close"),
        ("OUT_OF_ORDER", bars[0], "an older bar delivered after a newer one"),
        ("STALE", {**bars[0], "available": t0 - 1.0}, "very old event, available in time"),
    ]
