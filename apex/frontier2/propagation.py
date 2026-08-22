"""MarketPropagationGraph — F4: empirical, observational lead-lag edges
between instruments, and LeadingEdgeState: given a source's state just
changed, has the target caught up yet?

THE LAW THIS MODULE ENFORCES: edges are estimated from actual observed
return series via lagged cross-correlation -- a completely standard,
zero-fitting-parameter technique (there is nothing to overfit; it is
arithmetic over the data you hand it) -- and are labeled
OBSERVATIONAL_RELATIONSHIP or (with enough support) SUPPORTED_LEAD_LAG,
NEVER a causal claim. No edge is ever hard-coded ("QQQ leads semis"):
`estimate_edge()` only ever reports what it measured in the series it
was given. Nothing here touches the sealed holdout -- these are
same-session intraday return series, an entirely different data surface
from the daily-frequency Sharadar lake the holdout gate governs.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from apex.frontier2 import FRONTIER2_POWER

LEDGER = Path("results/frontier2/propagation_ledger.jsonl")

EDGE_STATUSES = ("OBSERVATIONAL_RELATIONSHIP", "SUPPORTED_LEAD_LAG",
                 "INSUFFICIENT_DATA", "UNSTABLE", "UNKNOWN")
PROPAGATION_STATES = ("NOT_YET_PROPAGATED", "PROPAGATING", "PROPAGATED",
                      "STALLED", "UNKNOWN")

# named, documented, un-fitted thresholds
MIN_SAMPLES_FOR_ANY_EDGE = 20
MIN_SAMPLES_FOR_SUPPORTED = 60
MATERIAL_CORR = 0.30                 # |corr| below this is noise, not a lead-lag
STRONG_CORR = 0.55
MAX_LAG_MINUTES = 5                  # candidate lags searched, -5..+5


class PropagationError(RuntimeError):
    pass


@dataclass(frozen=True)
class PropagationEdge:
    source: str
    target: str
    relationship_type: str            # always "LAGGED_RETURN_CORRELATION" today
    lead_lag_direction: str           # SOURCE_LEADS | TARGET_LEADS | SIMULTANEOUS | UNKNOWN
    estimated_delay_minutes: int | None
    correlation_at_lag: float | None
    support: int
    sample_count: int
    stability: str                    # STABLE | UNSTABLE | UNKNOWN
    regime: str
    quality: str
    status: str
    birth: str | None
    known_from: str
    as_of: str
    decision_power: str = FRONTIER2_POWER

    def __post_init__(self):
        if self.status not in EDGE_STATUSES:
            raise PropagationError(f"unknown edge status {self.status!r}")

    def as_record(self) -> dict:
        return {"kind": "propagation_edge", **asdict(self)}


@dataclass(frozen=True)
class LeadingEdgeState:
    source_change: dict               # the triggering typed event, verbatim
    target_candidate: str
    propagation_state: str
    observed_delay_minutes: float | None
    expected_delay_if_supported: int | None
    support: tuple
    contradictions: tuple
    falsification: str
    quality: str
    known_from: str
    as_of: str
    decision_power: str = FRONTIER2_POWER

    def __post_init__(self):
        if self.propagation_state not in PROPAGATION_STATES:
            raise PropagationError(
                f"unknown propagation_state {self.propagation_state!r}")

    def as_record(self) -> dict:
        return {"kind": "leading_edge_state", **asdict(self)}


def _lagged_corr(source_rets, target_rets, lag: int):
    """corr(source[t], target[t+lag]) -- positive lag means TARGET is
    shifted FORWARD, i.e. target reacts `lag` bars AFTER source. Uses
    only the two series handed in; no external state, no future beyond
    what the caller already sliced."""
    import numpy as np
    s, t = np.asarray(source_rets, dtype=float), np.asarray(target_rets, dtype=float)
    if lag > 0:
        s2, t2 = s[:-lag], t[lag:]
    elif lag < 0:
        s2, t2 = s[-lag:], t[:lag]
    else:
        s2, t2 = s, t
    n = min(len(s2), len(t2))
    if n < 3:
        return None, 0
    s2, t2 = s2[:n], t2[:n]
    if np.std(s2) < 1e-12 or np.std(t2) < 1e-12:
        return 0.0, n
    return float(np.corrcoef(s2, t2)[0, 1]), n


def estimate_edge(source: str, target: str, source_returns: list,
                  target_returns: list, *, known_from, now,
                  regime: str = "UNSPECIFIED", quality: str = "UNKNOWN",
                  birth: str | None = None,
                  max_lag: int = MAX_LAG_MINUTES) -> PropagationEdge:
    """`source_returns`/`target_returns`: same-length, same-cadence,
    already time-aligned per-bar return series (the caller's job, not
    this function's -- keeping this a pure numerical estimator).
    Searches lags -max_lag..+max_lag (in bars) and reports the lag with
    the strongest |correlation|. A negative estimated_delay means the
    TARGET actually led the SOURCE in this sample -- reported honestly,
    not silently flipped."""
    import pandas as pd

    n = min(len(source_returns), len(target_returns))
    if n < MIN_SAMPLES_FOR_ANY_EDGE:
        return PropagationEdge(
            source=source, target=target,
            relationship_type="LAGGED_RETURN_CORRELATION",
            lead_lag_direction="UNKNOWN", estimated_delay_minutes=None,
            correlation_at_lag=None, support=0, sample_count=n,
            stability="UNKNOWN", regime=regime, quality=quality,
            status="INSUFFICIENT_DATA", birth=birth,
            known_from=str(pd.Timestamp(known_from)), as_of=str(pd.Timestamp(now)))

    best_lag, best_corr, best_support = 0, 0.0, 0
    for lag in range(-max_lag, max_lag + 1):
        corr, support = _lagged_corr(source_returns, target_returns, lag)
        if corr is not None and abs(corr) > abs(best_corr):
            best_lag, best_corr, best_support = lag, corr, support

    if abs(best_corr) < MATERIAL_CORR:
        status = "OBSERVATIONAL_RELATIONSHIP"
        direction = "SIMULTANEOUS" if best_lag == 0 else "UNKNOWN"
    else:
        # stability check: does the SAME-SIGN lead-lag hold on the first
        # vs second half of the sample independently?
        half = n // 2
        c1, _ = _lagged_corr(source_returns[:half], target_returns[:half], best_lag)
        c2, _ = _lagged_corr(source_returns[half:], target_returns[half:], best_lag)
        stable = (c1 is not None and c2 is not None
                 and (c1 > 0) == (best_corr > 0) and (c2 > 0) == (best_corr > 0))
        if not stable:
            status = "UNSTABLE"
        elif best_support >= MIN_SAMPLES_FOR_SUPPORTED and abs(best_corr) >= STRONG_CORR:
            status = "SUPPORTED_LEAD_LAG"
        else:
            status = "OBSERVATIONAL_RELATIONSHIP"
        direction = ("SIMULTANEOUS" if best_lag == 0 else
                    "SOURCE_LEADS" if best_lag > 0 else "TARGET_LEADS")

    return PropagationEdge(
        source=source, target=target,
        relationship_type="LAGGED_RETURN_CORRELATION",
        lead_lag_direction=direction,
        estimated_delay_minutes=best_lag if abs(best_corr) >= MATERIAL_CORR else None,
        correlation_at_lag=round(best_corr, 4), support=best_support,
        sample_count=n,
        stability=("STABLE" if status == "SUPPORTED_LEAD_LAG" else
                  "UNSTABLE" if status == "UNSTABLE" else "UNKNOWN"),
        regime=regime, quality=quality, status=status, birth=birth,
        known_from=str(pd.Timestamp(known_from)), as_of=str(pd.Timestamp(now)))


def infer_leading_edge(edge: PropagationEdge, source_change: dict, *,
                       target_change_event_time=None, now,
                       ) -> LeadingEdgeState:
    """`source_change`: the triggering typed event (e.g. a
    CURVATURE_CHANGE record) verbatim -- used only for its subject/
    event_time, never mutated. `target_change_event_time`: if the
    caller has since observed the target's own matching change, pass
    its event_time; None means 'not observed yet', which is the whole
    point of a LEADING edge check."""
    import pandas as pd
    now = pd.Timestamp(now)
    source_t = pd.Timestamp(source_change["event_time"])

    if edge.status not in ("SUPPORTED_LEAD_LAG", "OBSERVATIONAL_RELATIONSHIP"):
        return LeadingEdgeState(
            source_change=source_change, target_candidate=edge.target,
            propagation_state="UNKNOWN", observed_delay_minutes=None,
            expected_delay_if_supported=None, support=(),
            contradictions=("edge_status_" + edge.status,),
            falsification="a supported or observational edge is estimated",
            quality=edge.quality, known_from=edge.known_from, as_of=str(now))

    expected_delay = (edge.estimated_delay_minutes
                      if edge.status == "SUPPORTED_LEAD_LAG" else None)

    if target_change_event_time is not None:
        observed_delay = (pd.Timestamp(target_change_event_time)
                          - source_t).total_seconds() / 60.0
        state = "PROPAGATED"
        support = ("target_change_observed",)
        contradictions = ()
        if expected_delay is not None and observed_delay < 0:
            contradictions = ("target_changed_before_source",)
            state = "UNKNOWN"
    else:
        observed_delay = (now - source_t).total_seconds() / 60.0
        support = ()
        contradictions = ()
        if expected_delay is None:
            state = "UNKNOWN"
        elif observed_delay <= 0:
            state = "NOT_YET_PROPAGATED"
        elif observed_delay <= expected_delay * 2:
            state = "PROPAGATING"
        else:
            state = "STALLED"
            contradictions = ("observed_delay_exceeds_2x_expected",)

    return LeadingEdgeState(
        source_change=source_change, target_candidate=edge.target,
        propagation_state=state, observed_delay_minutes=round(observed_delay, 2),
        expected_delay_if_supported=expected_delay, support=support,
        contradictions=contradictions,
        falsification=(f"{edge.target} shows the matching change within "
                       f"2x the estimated delay" if expected_delay is not None
                       else "an edge with a supported delay estimate exists"),
        quality=edge.quality, known_from=edge.known_from, as_of=str(now))


def persist_edge(edge: PropagationEdge) -> dict:
    import sys
    sys.path.insert(0, "scripts")
    from nightly_pull import _chain_append
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    return _chain_append(LEDGER, edge.as_record())
