"""Corporate actions as a DERIVED layer over immutable raw prices.

Three price meanings, never interchangeable:
  RAW_PRICE                  as printed, forever
  ANALYTICAL_NORMALIZED      retrospectively split-adjusted, clearly marked,
                             for ANALYSIS only -- and only legal when the
                             consumer explicitly declares retrospective use
  TRADABLE_PRICE_AT_T        what an agent at T saw: raw, with only actions
                             whose EXECUTION DATE <= T applied

A split executed after T may never alter what the agent knew at T. A raw 2:1
split boundary looks like a -50% crash; the tradable series at T just before
the boundary must still show the raw price, and the analytical series must
show continuity -- both directions counterexampled.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


def _utc(ts) -> pd.Timestamp:
    t = pd.Timestamp(ts)
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


@dataclass(frozen=True)
class SplitAction:
    apex_security_id: str
    execution_date: str          # prices/shares switch basis ON this date
    ratio: float                 # 2.0 = 2-for-1 forward split


def tradable_price_at(raw: pd.Series, actions, security_id: str, at) -> float:
    """What the agent could TRADE at `at`: the raw print. Actions with
    execution_date <= at are already reflected in raw prints by the
    exchange; later actions must not touch this value."""
    t = _utc(at)
    s = raw.loc[:t]
    if s.empty:
        raise ValueError("no raw observation at or before the requested time")
    return float(s.iloc[-1])


def analytical_normalized(raw: pd.Series, actions, security_id: str,
                          *, retrospective_use_declared: bool) -> pd.Series:
    """Back-adjusted continuity series. REFUSES to exist unless the caller
    declares retrospective use -- the flag is how 'clearly marked as such'
    is enforced structurally rather than by comment."""
    if not retrospective_use_declared:
        raise ValueError(
            "analytical_normalized is retrospective by construction; the "
            "caller must declare retrospective_use_declared=True. A PIT "
            "consumer that cannot declare it must use tradable_price_at.")
    out = raw.astype(float).copy()
    for a in sorted(actions, key=lambda a: a.execution_date):
        if a.apex_security_id != security_id:
            continue
        ex = _utc(a.execution_date)
        out.loc[out.index < ex] = out.loc[out.index < ex] / a.ratio
    return out.rename("ANALYTICAL_NORMALIZED")
