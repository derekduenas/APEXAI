"""INFORMATION LEAD -- is this organ EARLY, or merely correct?

The distinction that separates an indicator from an edge. An organ that
reports "breadth is deteriorating" ten minutes after the index has
already fallen is accurate and worthless. APEX has never measured this
for anything.

For every observation the Observatory records:

    first_known_at              when APEX could first have known
    move_became_obvious_at      when the move crossed the obviousness bar
    lead_seconds                the difference

A NEGATIVE lead is the important case and it is retained, not discarded:
it means the organ is a lagging description of something already priced.
Most organs will score negative. That is the finding.

OBVIOUSNESS IS DEFINED, NOT ASSUMED. "The move became obvious" means the
cumulative absolute return from the observation crossed a declared
threshold in units of the subject's own recent volatility -- scale-free,
so a $30 stock and a $770 index are judged the same way. A fixed
percentage would systematically flatter low-vol names.

decision_power: NONE_PATTERN_OBSERVATORY.
"""
from __future__ import annotations

from dataclasses import dataclass

from apex.pattern_observatory import OBSERVATORY_POWER

# DECLARED. A move is "obvious" once it exceeds this many multiples of
# the trailing per-minute volatility, measured over the same window.
OBVIOUSNESS_SIGMA = 2.0
MIN_VOL_BARS = 20
MAX_HORIZON_MIN = 120

NO_MOVE = "NO_OBVIOUS_MOVE"
NOT_ESTIMABLE = "NOT_ESTIMABLE"

ORGANS = ("sector_rotation", "breadth", "options_surface", "fastwatch",
          "expectation_violation", "propagation", "positioning",
          "pattern_observatory", "curve")


@dataclass(frozen=True)
class InformationLead:
    organ: str
    subject: str
    observation: str
    first_known_at: str
    move_became_obvious_at: str | None
    lead_seconds: float | None
    obviousness_threshold: float | None
    realized_move: float | None
    status: str
    is_early: bool | None
    bars_used: int
    known_from: str

    def as_dict(self) -> dict:
        return {"kind": "information_lead", **self.__dict__,
                "negative_lead_means_lagging": True,
                "law": "an organ that is correct but late is not an edge",
                "decision_power": OBSERVATORY_POWER}


def measure(*, organ: str, subject: str, observation: str, first_known_at,
            bars, known_from, horizon_minutes: int = MAX_HORIZON_MIN
            ) -> InformationLead:
    """`bars`: canonical bars for `subject` covering first_known_at onward."""
    import pandas as pd

    t0 = pd.Timestamp(first_known_at)

    def _mk(status, **kw):
        base = dict(move_became_obvious_at=None, lead_seconds=None,
                    obviousness_threshold=None, realized_move=None,
                    is_early=None, bars_used=0)
        base.update(kw)
        return InformationLead(
            organ=organ, subject=subject, observation=observation,
            first_known_at=str(t0), status=status,
            known_from=str(known_from), **base)

    if bars is None or not len(bars):
        return _mk(NOT_ESTIMABLE)

    # trailing volatility BEFORE the observation -- using bars after it
    # would let the outcome define its own threshold
    prior = bars[bars["event_time_utc"] < t0]
    if len(prior) < MIN_VOL_BARS:
        return _mk(NOT_ESTIMABLE, bars_used=len(prior))
    rets = prior["close"].astype(float).pct_change().dropna()
    sigma = float(rets.std())
    if not sigma or sigma <= 0:
        return _mk(NOT_ESTIMABLE, bars_used=len(prior))
    threshold = OBVIOUSNESS_SIGMA * sigma

    fwd = bars[(bars["event_time_utc"] >= t0)
               & (bars["event_time_utc"] <= t0 + pd.Timedelta(
                   minutes=horizon_minutes))]
    if len(fwd) < 2:
        return _mk(NOT_ESTIMABLE, obviousness_threshold=threshold,
                   bars_used=len(fwd))

    p0 = float(fwd["close"].iloc[0])
    if p0 == 0:
        return _mk(NOT_ESTIMABLE)

    obvious_at, realized = None, 0.0
    for _, row in fwd.iterrows():
        move = abs(float(row["close"]) / p0 - 1.0)
        if move > abs(realized):
            realized = float(row["close"]) / p0 - 1.0
        if move >= threshold:
            obvious_at = row["event_time_utc"]
            break

    if obvious_at is None:
        return _mk(NO_MOVE, obviousness_threshold=threshold,
                   realized_move=realized, bars_used=len(fwd))

    lead = (pd.Timestamp(obvious_at) - t0).total_seconds()
    return _mk("MEASURED", move_became_obvious_at=str(obvious_at),
               lead_seconds=lead, obviousness_threshold=threshold,
               realized_move=realized, is_early=lead > 0, bars_used=len(fwd))


def summarize(leads: list) -> dict:
    """Which organs are systematically early? The question that decides
    what is worth listening to."""
    import statistics
    by_organ: dict = {}
    for l in leads:
        if l.status != "MEASURED" or l.lead_seconds is None:
            continue
        by_organ.setdefault(l.organ, []).append(l.lead_seconds)
    rows = {}
    for organ, vals in sorted(by_organ.items()):
        rows[organ] = {
            "n": len(vals),
            "median_lead_s": statistics.median(vals),
            "mean_lead_s": statistics.fmean(vals),
            "pct_early": sum(1 for v in vals if v > 0) / len(vals),
            "verdict": ("INSUFFICIENT_SUPPORT" if len(vals) < 30 else
                        "SYSTEMATICALLY_EARLY"
                        if statistics.median(vals) > 0
                        and sum(1 for v in vals if v > 0) / len(vals) > 0.6
                        else "LAGGING_OR_COINCIDENT")}
    return {"kind": "information_lead_summary", "organs": rows,
            "n_measured": sum(r["n"] for r in rows.values()),
            "caveat": "a positive median lead is necessary for an edge and "
                      "nowhere near sufficient -- it says nothing about "
                      "direction, magnitude or cost",
            "decision_power": OBSERVATORY_POWER}
