"""TRUE_LATENCY_V1 + external cadence accounting.

THE LAW THIS ENCODES
--------------------
A SERVICE THAT COMPLETES ITS INTERNAL WORK IN 30 SECONDS BUT OCCUPIES
ITS SLOT FOR 75 SECONDS IS NOT A 30-SECOND SERVICE.

A TIMER FIRE THAT NEVER BECAME AN OBSERVATION IS LOST EVIDENCE.

WHY
---
PULSE_V0's latency.total_s began timing AFTER interpreter start,
imports and the journal restores. It reported within_budget=True on
100% of cycles while TRUE slot occupancy (scheduled -> persisted)
reached p95 72.4s and max 86.1s, and systemd silently discarded 24
timer fires because the oneshot was still active. The metric measured
the wrong quantity, so the system was blind to its own decay.

Only FULL SLOT OCCUPANCY may decide whether cadence survived.
The expected denominator comes from SCHEDULE SEMANTICS, never from the
records that happen to exist -- deriving it from survivors is how a
13.9% miss rate reads as 100%.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

CADENCE_VERSION = "TRUE_LATENCY_V1"


class SlotState(Enum):
    COMPLETED_ON_TIME = "COMPLETED_ON_TIME"
    COMPLETED_LATE = "COMPLETED_LATE"
    OVERRUN_COLLISION = "OVERRUN_COLLISION"
    START_FAILED = "START_FAILED"
    OOM_KILLED = "OOM_KILLED"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    PERSIST_FAILED = "PERSIST_FAILED"
    MISSED_NO_INVOCATION = "MISSED_NO_INVOCATION"
    HOST_UNAVAILABLE = "HOST_UNAVAILABLE"
    UNKNOWN = "UNKNOWN"


@dataclass
class Lifecycle:
    """Lifecycle points for ONE cycle. Any may be missing -- a cycle
    that died before persisting has no persistence_complete, and that
    absence is itself the evidence."""
    scheduled_time: datetime
    service_start: datetime | None = None
    state_restore_complete: datetime | None = None
    capture_start: datetime | None = None
    capture_complete: datetime | None = None
    composition_complete: datetime | None = None
    persistence_complete: datetime | None = None
    service_exit: datetime | None = None

    # -- the ONLY authority on cadence survival -----------------------
    @property
    def true_slot_occupancy_s(self) -> float | None:
        """scheduled_time -> authoritative persistence complete."""
        if self.persistence_complete is None:
            return None
        return (self.persistence_complete
                - self.scheduled_time).total_seconds()

    @property
    def startup_s(self) -> float | None:
        """The region PULSE_V0's metric could not see."""
        if self.capture_start is None:
            return None
        return (self.capture_start - self.scheduled_time).total_seconds()

    @property
    def internal_work_s(self) -> float | None:
        """What total_s measured. Diagnostic ONLY -- never the cadence
        authority."""
        if self.capture_start is None or self.persistence_complete is None:
            return None
        return (self.persistence_complete
                - self.capture_start).total_seconds()

    def occupies_next_slot(self, period_s: float = 60.0) -> bool:
        occ = self.true_slot_occupancy_s
        return occ is not None and occ >= period_s


def expected_slots(start: datetime, end: datetime,
                   period_s: float = 60.0) -> list[datetime]:
    """The denominator, derived from SCHEDULE, never from survivors."""
    out, cur = [], start
    step = timedelta(seconds=period_s)
    while cur <= end:
        out.append(cur)
        cur += step
    return out


def classify_slot(slot: datetime, *,
                  lifecycle: Lifecycle | None,
                  oom_kills: set[datetime] | None = None,
                  start_events: set[datetime] | None = None,
                  failed_events: set[datetime] | None = None,
                  prior_occupied: bool = False,
                  host_down: bool = False,
                  period_s: float = 60.0,
                  late_threshold_s: float = 60.0) -> SlotState:
    """Classify ONE expected slot into exactly one state.

    Substrate evidence (systemd/kernel) outranks application records:
    a cycle killed before writing leaves NO application trace, which is
    exactly how 77 OOM kills looked like 'nothing happened' from inside
    PULSE.
    """
    oom_kills = oom_kills or set()
    start_events = start_events or set()
    failed_events = failed_events or set()

    if host_down:
        return SlotState.HOST_UNAVAILABLE

    def _near(s: set[datetime]) -> bool:
        return any(timedelta(seconds=-2) <= (e - slot)
                   <= timedelta(seconds=period_s + 60) for e in s)

    # a persisted cycle is the only thing that counts as observed
    if lifecycle is not None and lifecycle.persistence_complete is not None:
        occ = lifecycle.true_slot_occupancy_s
        if occ is not None and occ > late_threshold_s:
            return SlotState.COMPLETED_LATE
        return SlotState.COMPLETED_ON_TIME

    if _near(oom_kills):
        return SlotState.OOM_KILLED

    if lifecycle is not None and lifecycle.service_start is not None:
        if lifecycle.composition_complete is not None:
            return SlotState.PERSIST_FAILED
        if lifecycle.capture_start is not None:
            return SlotState.EXECUTION_FAILED
        return SlotState.START_FAILED

    if _near(failed_events):
        return SlotState.EXECUTION_FAILED

    if prior_occupied and not _near(start_events):
        return SlotState.OVERRUN_COLLISION

    if not _near(start_events):
        return SlotState.MISSED_NO_INVOCATION

    return SlotState.UNKNOWN


def reconcile(states: dict[datetime, SlotState]) -> dict:
    """Full-session accounting. Everything must add up."""
    from collections import Counter
    c = Counter(s.value for s in states.values())
    total = len(states)
    observed = (c.get(SlotState.COMPLETED_ON_TIME.value, 0)
                + c.get(SlotState.COMPLETED_LATE.value, 0))
    lost = total - observed
    return {
        "version": CADENCE_VERSION,
        "expected_slots": total,
        "observed": observed,
        "LOST_PROSPECTIVE_OBSERVATIONS": lost,
        "miss_rate_pct": round(100.0 * lost / total, 3) if total else 0.0,
        "by_state": dict(c),
        "reconciles": observed + lost == total,
        "LAW": "the denominator comes from schedule semantics, never "
               "from surviving records; lost minutes are never "
               "backfilled as prospective observation",
    }


def latency_distribution(lifecycles: list[Lifecycle]) -> dict:
    """Report BOTH quantities side by side, so the misleading one can
    never again be mistaken for the authoritative one."""
    def pct(a, p):
        if not a:
            return None
        a = sorted(a)
        return round(a[min(len(a) - 1, int(len(a) * p))], 2)

    true_occ = [x for x in (lc.true_slot_occupancy_s for lc in lifecycles)
                if x is not None]
    internal = [x for x in (lc.internal_work_s for lc in lifecycles)
                if x is not None]
    startup = [x for x in (lc.startup_s for lc in lifecycles)
               if x is not None]
    return {
        "AUTHORITATIVE_true_slot_occupancy": {
            "p50": pct(true_occ, .50), "p95": pct(true_occ, .95),
            "p99": pct(true_occ, .99),
            "max": round(max(true_occ), 2) if true_occ else None,
            "n": len(true_occ)},
        "DIAGNOSTIC_internal_work": {
            "p50": pct(internal, .50), "p95": pct(internal, .95),
            "max": round(max(internal), 2) if internal else None},
        "DIAGNOSTIC_startup": {
            "p50": pct(startup, .50), "p95": pct(startup, .95),
            "max": round(max(startup), 2) if startup else None},
        "note": "internal_work is the quantity PULSE_V0 called "
                "within_budget. It is diagnostic only.",
    }
