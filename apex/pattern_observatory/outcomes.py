"""FORWARD OUTCOME RESOLVER + BASELINES.

Every prospective pattern eventually gets asked: what happened next?
NO_EVENT is a first-class answer and negative results are retained
forever -- a family that never precedes anything is exactly as valuable a
finding as one that does, and considerably more likely.

THE RESOLVER CANNOT SEE THE FUTURE. It resolves a horizon only when bars
covering that horizon already exist, and it stamps the bar range it used.
A horizon that has not elapsed returns PENDING, never an extrapolation.

BASELINES ARE THE POINT. The question is never "did the pattern go up".
It is "did the CONJUNCTION add anything its components did not". Five
baselines are computed for exactly that comparison.

decision_power: NONE_PATTERN_OBSERVATORY.
"""
from __future__ import annotations

from dataclasses import dataclass

from apex.pattern_observatory import OBSERVATORY_POWER

HORIZONS_MIN = (5, 15, 30, 60, 90)
PENDING = "PENDING"
NO_EVENT = "NO_EVENT"
UNRESOLVABLE = "UNRESOLVABLE"

BASELINES = ("RANDOM_STATE", "MARKET_UNCONDITIONAL", "SAME_REGIME",
             "SAME_SUBJECT", "SAME_TIME_OF_DAY", "SINGLE_COMPONENT")

# A move must clear this to count as an EVENT rather than drift.
EVENT_THRESHOLD = 0.0025


@dataclass(frozen=True)
class PatternOutcome:
    pattern_id: str
    family_id: str
    subject: str
    horizon_minutes: int
    observed_at: str
    resolved_at: str | None
    status: str
    ret: float | None
    mfe: float | None
    mae: float | None
    realized_vol: float | None
    range_expansion: float | None
    direction: str | None
    tail_event: bool | None
    time_to_break_s: float | None
    bars_used: int
    bar_range: tuple
    input_quality_at_observation: str
    baselines: dict

    def as_dict(self) -> dict:
        return {"kind": "pattern_outcome", **self.__dict__,
                "bar_range": list(self.bar_range),
                "baselines": dict(self.baselines),
                "negative_results_retained": True,
                "decision_power": OBSERVATORY_POWER}


def resolve(*, pattern_id: str, family_id: str, subject: str,
            observed_at, horizon_minutes: int, bars,
            input_quality: str, baselines: dict | None = None,
            now=None) -> PatternOutcome:
    """`bars`: canonical bars for `subject`. Only bars at or after
    `observed_at` are consulted, and only up to the horizon."""
    import pandas as pd
    t0 = pd.Timestamp(observed_at)
    t1 = t0 + pd.Timedelta(minutes=horizon_minutes)

    def _mk(status, **kw):
        base = dict(ret=None, mfe=None, mae=None, realized_vol=None,
                    range_expansion=None, direction=None, tail_event=None,
                    time_to_break_s=None, bars_used=0, bar_range=("", ""))
        base.update(kw)
        return PatternOutcome(
            pattern_id=pattern_id, family_id=family_id, subject=subject,
            horizon_minutes=horizon_minutes, observed_at=str(t0),
            resolved_at=(str(now) if now is not None else None),
            status=status, input_quality_at_observation=input_quality,
            baselines=dict(baselines or {}), **base)

    if bars is None or not len(bars):
        return _mk(UNRESOLVABLE)

    window = bars[(bars["event_time_utc"] >= t0)
                  & (bars["event_time_utc"] <= t1)]
    if len(window) < 2:
        return _mk(UNRESOLVABLE if now is not None
                   and pd.Timestamp(now) > t1 else PENDING)
    # THE NO-LOOKAHEAD GUARD: the horizon must have actually elapsed in
    # observed data, not merely in wall-clock time.
    if window["event_time_utc"].max() < t1 - pd.Timedelta(minutes=1):
        return _mk(PENDING, bars_used=len(window))

    p0 = float(window["close"].iloc[0])
    if p0 == 0:
        return _mk(UNRESOLVABLE)
    closes = window["close"].astype(float)
    ret = float(closes.iloc[-1]) / p0 - 1.0
    mfe = float(window["high"].max()) / p0 - 1.0
    mae = float(window["low"].min()) / p0 - 1.0
    rets = closes.pct_change().dropna()
    rv = float(rets.std()) if len(rets) > 1 else None
    rng = (float(window["high"].max()) - float(window["low"].min())) / p0

    status = NO_EVENT if abs(ret) < EVENT_THRESHOLD else "RESOLVED"
    direction = "UP" if ret > 0 else "DOWN" if ret < 0 else "FLAT"
    return _mk(status, ret=ret, mfe=mfe, mae=mae, realized_vol=rv,
               range_expansion=rng, direction=direction,
               tail_event=(abs(ret) >= 4 * EVENT_THRESHOLD),
               bars_used=len(window),
               bar_range=(str(window["event_time_utc"].min()),
                          str(window["event_time_utc"].max())))


def compare_to_baselines(pattern_returns: list, baseline_returns: dict) -> dict:
    """Does the conjunction add anything beyond its components?

    Reports differences and sample sizes. It does NOT report a p-value:
    with n in the tens, a p-value would be a decoration that invites
    exactly the overclaiming this system exists to prevent.
    """
    import statistics
    n = len(pattern_returns)
    out = {"kind": "pattern_baseline_comparison", "pattern_n": n,
           "decision_power": OBSERVATORY_POWER}
    if n < 2:
        out["status"] = "INSUFFICIENT_SUPPORT"
        return out
    pm = statistics.fmean(pattern_returns)
    out["pattern_mean"] = pm
    out["pattern_median"] = statistics.median(pattern_returns)
    out["comparisons"] = {}
    for name, vals in baseline_returns.items():
        if len(vals) < 2:
            out["comparisons"][name] = {"status": "INSUFFICIENT_SUPPORT",
                                        "n": len(vals)}
            continue
        bm = statistics.fmean(vals)
        out["comparisons"][name] = {
            "n": len(vals), "baseline_mean": bm, "difference": pm - bm,
            "pattern_better": pm > bm}
    out["status"] = "COMPUTED"
    out["caveat"] = ("differences at this sample size are descriptive, not "
                     "inferential; no p-value is reported by design")
    return out
