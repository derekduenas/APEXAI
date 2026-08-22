"""SystemCognitionState — F13 (full assembly): whether APEX itself is
healthy enough to trust its own intelligence output.

THE LAW, enforced mechanically, not by convention: `can_claim_high_
quality()` returns False whenever ANY tracked component -- starting
with ObservationIntegrityState itself -- is not at its best status.
Every Frontier-2 organ that emits a `quality` field is expected to
call this rather than invent its own rollup, so "no module may claim
HIGH_QUALITY while critical observation integrity is degraded" is one
function, not thirteen re-implementations that could drift apart.

A component the caller does not supply contributes UNKNOWN severity
(2 of 0-3), never HEALTHY-by-default -- absence must never read as
healthy, the same law this repo has enforced since Phase 0.1.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from apex.frontier2 import FRONTIER2_POWER

LEDGER = Path("results/frontier2/system_cognition_ledger.jsonl")

COMPONENTS = ("observation_integrity", "provider_health", "trade_coverage",
             "quote_coverage", "service_progress", "bar_completeness",
             "latency", "runtime_drift", "disk", "quota", "model_freshness",
             "event_backlog")

OVERALL_QUALITIES = ("HEALTHY", "DEGRADED", "LIMITED", "CRITICAL", "UNKNOWN")

# a shared severity map spanning every status vocabulary already in use
# across this repo tonight (Health Law states, SessionCoverage's
# FULL/PARTIAL/DEGRADED/INVALID, service_progress's PROGRESS_STATUS,
# ObservationIntegrityState's FULL/PARTIAL/LIMITED/INVALID) -- 0 best,
# 3 worst. Anything not recognized is treated as UNKNOWN (severity 2),
# never assumed benign.
_SEVERITY = {
    "HEALTHY": 0, "FULL": 0, "OK": 0,
    "PARTIAL": 1, "DEGRADED": 1, "STARTING": 1, "CONNECTING": 1,
    "AUTHENTICATED": 1, "PARTIAL_COVERAGE": 1,
    "LIMITED": 2, "STALE": 2, "SUBSCRIBED_NO_DATA": 2, "UNKNOWN": 2,
    "STALLED": 3, "INVALID": 3, "FAILED": 3, "CRITICAL": 3,
}


class SystemCognitionError(RuntimeError):
    pass


@dataclass(frozen=True)
class SystemCognitionState:
    subject: str
    as_of: str
    known_from: str
    component_statuses: dict
    overall_quality: str
    quality_reasons: tuple
    worst_component: str | None
    decision_power: str = FRONTIER2_POWER

    def __post_init__(self):
        if self.overall_quality not in OVERALL_QUALITIES:
            raise SystemCognitionError(
                f"unknown overall_quality {self.overall_quality!r}")

    def as_record(self) -> dict:
        return asdict(self)

    def can_claim_high_quality(self) -> bool:
        return self.overall_quality == "HEALTHY"


def _severity(status: str | None) -> int:
    if status is None:
        return _SEVERITY["UNKNOWN"]
    return _SEVERITY.get(status, _SEVERITY["UNKNOWN"])


def assess(*, observation_integrity, subject: str = "SYSTEM", known_from, now,
          provider_health: str | None = None, trade_coverage: str | None = None,
          quote_coverage: str | None = None, service_progress: str | None = None,
          bar_completeness: str | None = None, latency: str | None = None,
          runtime_drift: str | None = None, disk: str | None = None,
          quota: str | None = None, model_freshness: str | None = None,
          event_backlog: str | None = None) -> SystemCognitionState:
    """`observation_integrity`: an ObservationIntegrityState -- REQUIRED,
    not optional, because system cognition without it is exactly the
    blind spot this module exists to close."""
    import pandas as pd
    now = pd.Timestamp(now)

    statuses = {
        "observation_integrity": observation_integrity.quality,
        "provider_health": provider_health, "trade_coverage": trade_coverage,
        "quote_coverage": quote_coverage, "service_progress": service_progress,
        "bar_completeness": bar_completeness, "latency": latency,
        "runtime_drift": runtime_drift, "disk": disk, "quota": quota,
        "model_freshness": model_freshness, "event_backlog": event_backlog,
    }

    worst_name, worst_sev = None, -1
    for name, status in statuses.items():
        sev = _severity(status)
        if sev > worst_sev:
            worst_sev, worst_name = sev, name

    overall = {0: "HEALTHY", 1: "DEGRADED", 2: "LIMITED", 3: "CRITICAL"}[worst_sev]
    reasons = []
    if worst_sev > 0:
        reasons.append(f"{worst_name}={statuses[worst_name]!r} is the "
                       f"worst-tracked component (severity {worst_sev})")
    absent = [n for n, s in statuses.items() if s is None and n != "observation_integrity"]
    if absent:
        reasons.append(f"not supplied (read as UNKNOWN, not healthy): {absent}")
    if not reasons:
        reasons.append("every tracked component reads at its best status")

    return SystemCognitionState(
        subject=subject, as_of=str(now), known_from=str(pd.Timestamp(known_from)),
        component_statuses=statuses, overall_quality=overall,
        quality_reasons=tuple(reasons), worst_component=worst_name)


def persist(state: SystemCognitionState) -> dict:
    import sys
    sys.path.insert(0, "scripts")
    from nightly_pull import _chain_append
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    return _chain_append(LEDGER, state.as_record())
