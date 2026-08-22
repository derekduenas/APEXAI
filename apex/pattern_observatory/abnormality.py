"""ABNORMALITY ENGINE -- how unusual, and is that even answerable.

RARITY IS NOT PROFITABILITY. A 99th-percentile reading is a statement
about the sample, not about the future. This module exists to say "this
configuration is unusual" with a defensible denominator, and to say
NOT_ESTIMABLE loudly the rest of the time.

THE DENOMINATOR IS THE WHOLE PROBLEM. On its first live day the
Observatory has a history of ZERO sessions. Every percentile it could
report would be computed against itself. So the default answer here is
NOT_ESTIMABLE, and it stays NOT_ESTIMABLE until MIN_HISTORY observations
across MIN_DISTINCT_SESSIONS distinct sessions exist. There is no
"provisional" percentile and no shrinkage toward a prior.

decision_power: NONE_PATTERN_OBSERVATORY.
"""
from __future__ import annotations

from dataclasses import dataclass

from apex.pattern_observatory import OBSERVATORY_POWER

NORMAL, ELEVATED, RARE, EXTREME = "NORMAL", "ELEVATED", "RARE", "EXTREME"
NOT_ESTIMABLE = "NOT_ESTIMABLE"
STATES = (NORMAL, ELEVATED, RARE, EXTREME, NOT_ESTIMABLE)

# DECLARED before any observation. A percentile needs a denominator big
# enough that the extremes are not simply the two samples we happen to
# have, and sessions matter more than raw count: 500 observations from
# one session are one session's worth of information.
MIN_HISTORY = 200
MIN_DISTINCT_SESSIONS = 5

P_ELEVATED, P_RARE, P_EXTREME = 0.85, 0.95, 0.99


@dataclass(frozen=True)
class Abnormality:
    metric: str
    subject: str
    value: float | None
    percentile: float | None
    z_score: float | None
    rate_of_change: float | None
    acceleration: float | None
    duration_observations: int | None
    state: str
    n_history: int
    n_distinct_sessions: int
    reason: str
    as_of: str
    known_from: str

    def as_dict(self) -> dict:
        return {"kind": "abnormality", **self.__dict__,
                "rarity_implies_profitability": False,
                "decision_power": OBSERVATORY_POWER}


def assess(metric: str, subject: str, value: float | None, history: list, *,
           session_dates: list | None = None, prior_value: float | None = None,
           prior_rate: float | None = None, duration: int | None = None,
           as_of=None, known_from=None) -> Abnormality:
    """`history`: prior values of the SAME metric for the SAME subject."""
    n = len(history)
    sessions = len(set(session_dates or ()))

    def _mk(pct, z, state, reason):
        roc = (None if (value is None or prior_value is None)
               else value - prior_value)
        acc = (None if (roc is None or prior_rate is None) else roc - prior_rate)
        return Abnormality(
            metric=metric, subject=subject, value=value, percentile=pct,
            z_score=z, rate_of_change=roc, acceleration=acc,
            duration_observations=duration, state=state, n_history=n,
            n_distinct_sessions=sessions, reason=reason,
            as_of=str(as_of) if as_of else "", 
            known_from=str(known_from) if known_from else "")

    if value is None:
        return _mk(None, None, NOT_ESTIMABLE, "no value observed")
    if n < MIN_HISTORY:
        return _mk(None, None, NOT_ESTIMABLE,
                   f"history {n} < required {MIN_HISTORY}")
    if sessions < MIN_DISTINCT_SESSIONS:
        return _mk(None, None, NOT_ESTIMABLE,
                   f"{sessions} distinct sessions < required "
                   f"{MIN_DISTINCT_SESSIONS} -- a percentile from one "
                   f"session describes that session, not the market")

    import statistics
    below = sum(1 for h in history if h < value)
    pct = below / n
    try:
        sd = statistics.pstdev(history)
        z = (value - statistics.fmean(history)) / sd if sd > 0 else None
    except statistics.StatisticsError:
        z = None

    two_sided = max(pct, 1 - pct)
    state = (EXTREME if two_sided >= P_EXTREME else
             RARE if two_sided >= P_RARE else
             ELEVATED if two_sided >= P_ELEVATED else NORMAL)
    return _mk(pct, z, state,
               f"percentile {pct:.3f} over {n} obs / {sessions} sessions")
