"""CANONICAL_WRITER_HEALTH_V0 -- job-specific health, not liveness.

THE LAWS THIS ENCODES
---------------------
    PROCESS ALIVE          != SERVICE HEALTHY
    FILE MTIME CHANGING    != CANONICAL WORK PRODUCED
    HASH CHAIN VALID       != EXPECTED EVIDENCE CONTINUOUS

WHY
---
apex-btc-paper presented, simultaneously:
    systemctl        active (running)
    file mtime       seconds old
    hash chain       640 rows, 0 prev_mismatch, VALID
    restart          recovering successfully
...while it had produced ZERO decisions for 35 hours. Each restart
appended one preregistration row, so the ledger GREW while the
economic job was dead. Every superficial signal said healthy.

CONTAINMENT SUCCESS IS NOT ORGAN SUCCESS. A health model must be able
to say, at the same time:
    HOST_CONTAINMENT     PASS
    EQUITY_FABRIC        FAIL
    EVIDENCE_CONTINUITY  DEGRADED
A model that cannot express all three at once is lying by omission.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum

HEALTH_VERSION = "CANONICAL_WRITER_HEALTH_V0"


class Health(Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    EVIDENCE_GAP = "EVIDENCE_GAP"
    FAILED = "FAILED"
    SCHEDULED_INACTIVE = "SCHEDULED_INACTIVE"
    DISABLED = "DISABLED"
    UNKNOWN = "UNKNOWN"


@dataclass
class Schedule:
    """A service's INTENDED operating window.

    equity-fabric runs --minutes 660 then exits cleanly; it is then
    legitimately absent until the orchestrator's next daily start.
    apex-options-paper completes its session at the close. Neither is
    stale, dead, or unhealthy -- they are SCHEDULED_INACTIVE. Health
    that ignores schedule manufactures false alarms, and false alarms
    train operators to ignore real ones.
    """
    windows: list[tuple[str, str]] = field(default_factory=list)  # UTC HH:MM
    always_on: bool = False

    def is_expected_active(self, now: datetime) -> bool:
        if self.always_on:
            return True
        hm = now.strftime("%H:%M")
        return any(a <= hm < b for a, b in self.windows)


@dataclass
class WriterObservation:
    """Everything the observer gathered from OUTSIDE the process."""
    unit: str
    now: datetime
    process_alive: bool
    unit_enabled: bool
    schedule: Schedule
    # the economic job -- what actually matters
    last_valid_output_at: datetime | None = None
    expected_output_period_s: float | None = None
    expected_denominator: int | None = None
    actual_denominator: int | None = None
    missing_intervals: int = 0
    # substrate signals -- necessary but NEVER sufficient
    file_mtime_at: datetime | None = None
    chain_valid: bool | None = None
    restart_count: int = 0
    oom_count: int = 0
    source_healthy: bool | None = None

    @property
    def output_age_s(self) -> float | None:
        if self.last_valid_output_at is None:
            return None
        return (self.now - self.last_valid_output_at).total_seconds()


def evaluate(obs: WriterObservation) -> dict:
    """Resolve one canonical writer's health.

    Order matters: schedule first (absence may be correct), then
    lifecycle, then -- crucially -- the ECONOMIC JOB. Substrate signals
    can only downgrade, never promote.
    """
    reasons: list[str] = []
    expected_active = obs.schedule.is_expected_active(obs.now)

    if not expected_active:
        return _result(Health.SCHEDULED_INACTIVE, obs,
                       ["outside its intended operating window; "
                        "absence here is CORRECT, not stale"])

    if not obs.unit_enabled and not obs.process_alive:
        return _result(Health.DISABLED, obs,
                       ["unit disabled and not running"])

    if not obs.process_alive:
        return _result(Health.FAILED, obs,
                       ["expected active but process is not running"])

    # ---- the economic job -------------------------------------------
    # A running process that is not producing its product is FAILED,
    # regardless of how healthy its substrate looks.
    if obs.last_valid_output_at is None:
        reasons.append("no valid canonical output has EVER been "
                       "observed in the evaluated window")
        return _result(Health.FAILED, obs, reasons)

    age = obs.output_age_s
    period = obs.expected_output_period_s
    if period is not None and age is not None:
        if age > period * 10:
            reasons.append(
                f"last valid output {age:.0f}s old vs expected period "
                f"{period:.0f}s (>10x) -- the process is alive but the "
                f"economic job has stopped")
            return _result(Health.FAILED, obs, reasons)
        if age > period * 3:
            reasons.append(
                f"last valid output {age:.0f}s old vs expected period "
                f"{period:.0f}s (>3x)")

    # ---- evidence continuity ----------------------------------------
    if obs.missing_intervals > 0:
        reasons.append(f"{obs.missing_intervals} missing interval(s) -- "
                       "evidence is not continuous")
        return _result(Health.EVIDENCE_GAP, obs, reasons)

    if (obs.expected_denominator is not None
            and obs.actual_denominator is not None
            and obs.actual_denominator < obs.expected_denominator):
        reasons.append(
            f"actual {obs.actual_denominator} < expected "
            f"{obs.expected_denominator} observations")
        return _result(Health.EVIDENCE_GAP, obs, reasons)

    # ---- substrate: may only DOWNGRADE ------------------------------
    if obs.chain_valid is False:
        reasons.append("hash chain INVALID")
        return _result(Health.FAILED, obs, reasons)
    if obs.oom_count > 0:
        reasons.append(f"{obs.oom_count} OOM kill(s) in window -- "
                       "restart does not restore evidence health")
    if obs.restart_count > 0:
        reasons.append(f"{obs.restart_count} restart(s) in window")
    if obs.source_healthy is False:
        reasons.append("upstream source unhealthy")

    if reasons:
        return _result(Health.DEGRADED, obs, reasons)
    return _result(Health.HEALTHY, obs, ["expected work observed on "
                                         "cadence, evidence continuous"])


def _result(state: Health, obs: WriterObservation,
            reasons: list[str]) -> dict:
    return {
        "version": HEALTH_VERSION,
        "unit": obs.unit,
        "state": state.value,
        "evaluated_utc": obs.now.isoformat(),
        "output_age_s": obs.output_age_s,
        "expected_denominator": obs.expected_denominator,
        "actual_denominator": obs.actual_denominator,
        "missing_intervals": obs.missing_intervals,
        "restart_count": obs.restart_count,
        "oom_count": obs.oom_count,
        "chain_valid": obs.chain_valid,
        "reasons": reasons,
        "LAW": "process alive, changing mtime and a valid chain can "
               "ALL be true while the economic job is dead; none of "
               "them can produce HEALTHY on their own",
    }


def substrate_only_is_never_healthy(*, process_alive: bool,
                                    mtime_changing: bool,
                                    chain_valid: bool,
                                    now: datetime | None = None) -> dict:
    """The btc-paper counterexample, executable.

    Given ONLY the three substrate signals -- all true -- and no
    evidence of economic work, health must not be HEALTHY.
    """
    now = now or datetime.now(timezone.utc)
    obs = WriterObservation(
        unit="<substrate-only>", now=now,
        process_alive=process_alive, unit_enabled=True,
        schedule=Schedule(always_on=True),
        last_valid_output_at=None,
        file_mtime_at=now if mtime_changing else None,
        chain_valid=chain_valid)
    return evaluate(obs)
