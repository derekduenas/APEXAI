"""Hunter service progress + independent watchdog.

WHY THIS EXISTS (measured 2026-08-18): a repo-wide search for
Hunter-specific progress/watchdog artifacts returned nothing. Frontier,
Frontier-2 and Options Analytics each had a service_progress.json and a
watchdog; Hunter -- the OFFICIAL decision path -- had neither.

RECURRING_ONESHOT, NOT A DAEMON. hunter_forward_clock.py runs ONE tick
and exits; launchd re-invokes it every 900 s (com.apex.hunter-clock
StartInterval). This distinction is load-bearing and was got wrong in
the Phase 1.0 draft of this module, which reused the daemon watchdog's
`pid_alive` test: between ticks there is deliberately NO process, so a
daemon-shaped watchdog would report STOPPED on a perfectly healthy
Hunter every single time.

Therefore:
  - cycle_number PERSISTS and increments ACROSS invocations (a fresh
    process is a continuing cycle sequence, not a reset)
  - health is judged by the AGE OF THE LAST SUCCESSFUL CYCLE against the
    expected cadence -- never by whether a process is currently alive
  - pid liveness is still recorded, but only as informational context

PID_ALIVE IS NOT HEALTHY, and for a one-shot PID_DEAD IS NOT UNHEALTHY.

decision_power: NONE_OBSERVABILITY. This computes and classifies; it
touches no scan, playbook, threshold or decision. Hunter's semantics are
unchanged.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from apex.governance.service_progress import (
    DEGRADED, FAILED, HEALTHY, STALLED, STARTING, STOPPED, is_pid_alive,
)

STATE_PATH = Path("results/hunter/runtime/service_progress.json")

RUNTIME_MODEL = "RECURRING_ONESHOT"
# launchd com.apex.hunter-clock StartInterval
DEFAULT_CADENCE_S = 900.0

# missed-run tolerances, expressed in scheduled intervals rather than
# raw seconds so they stay meaningful if the cadence changes.
DEGRADED_AFTER_INTERVALS = 2.0
STALLED_AFTER_INTERVALS = 3.0
FAILED_AFTER_CONSECUTIVE_FAILURES = 8
STALLED_AFTER_CONSECUTIVE_FAILURES = 3


@dataclass
class HunterProgressState:
    service_name: str
    pid: int
    start_time: str
    expected_cadence_s: float

    cycle_number: int = 0
    cycle_start: str | None = None
    cycle_complete: str | None = None
    last_successful_cycle: str | None = None
    cycle_duration_s: float | None = None

    states_computed: int = 0
    watchlist_count: int = 0
    playbook_matches: int = 0
    ledger_writes: int = 0

    consecutive_failures: int = 0
    total_failures: int = 0
    heartbeat: str | None = None
    last_error_ref: str | None = None

    runtime_model: str = RUNTIME_MODEL
    decision_power: str = "NONE_OBSERVABILITY"

    def as_record(self) -> dict:
        return {"kind": "hunter_service_progress", **asdict(self),
               "progress_status": self.progress_status()}

    def progress_status(self) -> str:
        if self.cycle_number == 0 and self.consecutive_failures == 0:
            return STARTING
        if self.consecutive_failures >= FAILED_AFTER_CONSECUTIVE_FAILURES:
            return FAILED
        if self.consecutive_failures >= STALLED_AFTER_CONSECUTIVE_FAILURES:
            return STALLED
        if self.last_successful_cycle is None:
            # ticks attempted, none ever completed -- stalled from birth
            return STALLED if self.cycle_number > 0 else DEGRADED
        import pandas as pd
        age = (pd.Timestamp.now(tz="UTC")
               - pd.Timestamp(self.last_successful_cycle)).total_seconds()
        if age > STALLED_AFTER_INTERVALS * self.expected_cadence_s:
            return STALLED
        if age > DEGRADED_AFTER_INTERVALS * self.expected_cadence_s:
            return DEGRADED
        if self.consecutive_failures >= 1:
            return DEGRADED
        return HEALTHY


def read(path: Path | None = None) -> dict | None:
    p = path or STATE_PATH
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        return None


def load_or_advance(*, expected_cadence_s: float = DEFAULT_CADENCE_S,
                    path: Path | None = None) -> HunterProgressState:
    """Begin a tick. Continues the persisted cycle sequence across
    process boundaries (the one-shot model) rather than resetting."""
    import pandas as pd
    now = pd.Timestamp.now(tz="UTC")
    prior = read(path)
    if prior is None:
        return HunterProgressState(
            service_name="hunter_forward_clock", pid=os.getpid(),
            start_time=str(now), expected_cadence_s=expected_cadence_s,
            cycle_number=1, cycle_start=str(now), heartbeat=str(now))
    keep = {k: v for k, v in prior.items()
            if k in HunterProgressState.__dataclass_fields__}
    s = HunterProgressState(**keep)
    s.pid = os.getpid()                 # this invocation
    s.expected_cadence_s = expected_cadence_s
    s.cycle_number = int(s.cycle_number) + 1
    s.cycle_start = str(now)
    s.heartbeat = str(now)
    s.cycle_complete = None
    return s


def mark_success(state: HunterProgressState) -> HunterProgressState:
    import pandas as pd
    now = pd.Timestamp.now(tz="UTC")
    state.cycle_complete = str(now)
    state.last_successful_cycle = str(now)
    state.consecutive_failures = 0
    state.last_error_ref = None
    if state.cycle_start:
        state.cycle_duration_s = round(
            (now - pd.Timestamp(state.cycle_start)).total_seconds(), 3)
    state.heartbeat = str(now)
    return state


def mark_failure(state: HunterProgressState, error_ref: str) -> HunterProgressState:
    import pandas as pd
    now = pd.Timestamp.now(tz="UTC")
    state.consecutive_failures += 1
    state.total_failures += 1
    state.last_error_ref = error_ref
    state.heartbeat = str(now)
    return state


def write(state: HunterProgressState, path: Path | None = None) -> None:
    p = path or STATE_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(state.as_record(), indent=1, default=str))
    os.replace(tmp, p)


def watchdog_check(path: Path | None = None) -> dict:
    """INDEPENDENT verification: re-derives status from the persisted
    record rather than trusting the self-reported string, and applies
    the ONE-SHOT rule -- a dead PID between scheduled ticks is normal
    and must never be reported as STOPPED."""
    p = path or STATE_PATH
    rec = read(p)
    if rec is None:
        return {"service": "hunter_forward_clock", "runtime_model": RUNTIME_MODEL,
               "watchdog_status": STOPPED,
               "watchdog_reason": "no hunter service_progress.json has ever "
                                  "been written"}

    pid = rec.get("pid")
    alive = is_pid_alive(pid) if isinstance(pid, int) else False

    if (rec.get("cycle_start") is not None
            and rec.get("last_successful_cycle") is None):
        status = STALLED
        reason = ("cycle_start advancing but no cycle has ever completed "
                  "successfully -- heartbeat without progress")
    else:
        derived = HunterProgressState(**{
            k: v for k, v in rec.items()
            if k in HunterProgressState.__dataclass_fields__})
        status, reason = derived.progress_status(), None

    return {
        "service": rec.get("service_name", "hunter_forward_clock"),
        "runtime_model": RUNTIME_MODEL,
        "pid": pid,
        "pid_alive": alive,
        "pid_liveness_is_informational_only": True,
        "cycle_number": rec.get("cycle_number"),
        "cycle_start": rec.get("cycle_start"),
        "last_successful_cycle": rec.get("last_successful_cycle"),
        "cycle_duration_s": rec.get("cycle_duration_s"),
        "states_computed": rec.get("states_computed"),
        "watchlist_count": rec.get("watchlist_count"),
        "playbook_matches": rec.get("playbook_matches"),
        "ledger_writes": rec.get("ledger_writes"),
        "consecutive_failures": rec.get("consecutive_failures"),
        "total_failures": rec.get("total_failures"),
        "last_error_ref": rec.get("last_error_ref"),
        "self_reported_status": rec.get("progress_status"),
        "watchdog_status": status,
        "watchdog_reason": reason,
        "agrees_with_self_report": status == rec.get("progress_status"),
    }
