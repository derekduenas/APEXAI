"""SERVICE PROGRESS STATE — the canonical answer to "is this service
actually doing anything," proven on 2026-08-17 to be a DIFFERENT
question from "is the PID alive."

Root cause of that day's Frontier stall (evidence, not inference): the
buffered stdout log, flushed only when the process finally exited after
its full 400-minute budget, showed

    tick failed (loop continues): KeyError: 0

repeated ~150+ times, one per ~120s cycle, from the first real watchlist
(14:52 UTC) to process exit. Every cycle raised, was caught by a bare
`except Exception: print(...)`, and the print sat in a block-buffered
pipe invisible until the process died on its own budget almost three
hours later. The PID was alive the entire time; zero cycles ever
completed; `_save()` was never reached once.

This module makes that distinction structural: PID_ALIVE is not
PROGRESS_STATUS. A service can only be marked HEALTHY by demonstrating
an ADVANCING cycle counter and a recent successful cycle -- never by a
heartbeat write alone (a stalled loop can still "heartbeat" on every
failed attempt).

decision_power: NONE. This module classifies; it authorizes nothing.
"""
from __future__ import annotations

import json
import os
import traceback
from dataclasses import asdict, dataclass, field
from pathlib import Path

STARTING, HEALTHY, DEGRADED, STALLED, FAILED, STOPPED = (
    "STARTING", "HEALTHY", "DEGRADED", "STALLED", "FAILED", "STOPPED")

# consecutive-failure thresholds: 1-2 is DEGRADED (transient), 3+ without
# a single success in between is STALLED, 8+ is FAILED (give up quietly
# retrying the same broken thing forever)
DEGRADED_AFTER_FAILURES = 1
STALLED_AFTER_FAILURES = 3
FAILED_AFTER_FAILURES = 8


class ServiceProgressViolation(RuntimeError):
    pass


@dataclass
class ServiceProgressState:
    service_name: str
    pid: int
    start_time: str
    expected_cadence_s: float

    cycle_number: int = 0
    last_cycle_start: str | None = None
    last_cycle_complete: str | None = None
    last_successful_cycle: str | None = None
    cycle_duration_s: float | None = None

    last_event_consumed: str | None = None
    last_event_produced: str | None = None
    last_state_read: str | None = None
    last_state_write: str | None = None

    consecutive_failures: int = 0
    total_failures: int = 0
    backlog_count: int = 0
    blocking_operation: str | None = None
    error_reference: str | None = None

    heartbeat_time: str | None = None

    def as_record(self) -> dict:
        return {"kind": "service_progress_state", **asdict(self),
               "progress_status": self.progress_status()}

    def progress_status(self) -> str:
        """PID existence is not health. A cycle must have completed
        SUCCESSFULLY, and recently, or this is not HEALTHY -- regardless
        of how recently a heartbeat was written."""
        if self.cycle_number == 0 and self.consecutive_failures == 0:
            return STARTING
        if self.consecutive_failures >= FAILED_AFTER_FAILURES:
            return FAILED
        if self.consecutive_failures >= STALLED_AFTER_FAILURES:
            return STALLED
        if self.last_successful_cycle is None:
            # cycles have been attempted (cycle_number>0 or failures>0)
            # but NONE has ever succeeded -- this is stalled from birth,
            # exactly the 2026-08-17 shape, never "starting"
            return STALLED if self.cycle_number > 0 else DEGRADED
        import pandas as pd
        age = (pd.Timestamp.now(tz="UTC")
              - pd.Timestamp(self.last_successful_cycle)).total_seconds()
        stall_bound = max(3 * self.expected_cadence_s, 180)
        if age > stall_bound:
            return STALLED
        if self.consecutive_failures >= DEGRADED_AFTER_FAILURES:
            return DEGRADED
        return HEALTHY


def start(service_name: str, *, expected_cadence_s: float) -> ServiceProgressState:
    import pandas as pd
    return ServiceProgressState(
        service_name=service_name, pid=os.getpid(),
        start_time=str(pd.Timestamp.now(tz="UTC")),
        expected_cadence_s=expected_cadence_s)


def write(state: ServiceProgressState, path: Path) -> None:
    """Atomic (os.replace): a reader never observes a half-written
    state file, and a canonical artifact never depends on a print
    surviving a crash to be legible."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state.as_record(), indent=1, default=str))
    os.replace(tmp, path)


def read(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return None


def is_pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True          # exists, just not ours to signal
    return True


def check_pid_matches_state(state_record: dict | None,
                            current_pid: int) -> tuple:
    """(matches, reason). RESTART SEMANTICS: a new process must never
    inherit a previous instance's last_successful_cycle as evidence of
    ITS OWN health -- the exact ambiguity that made 2026-08-17's stall
    hard to see at a glance ('is that state fresh, or from the process
    before this one?') until the raw log was read by hand and its PID
    cross-checked. A caller whose actual PID differs from the persisted
    record's PID must call start() (cycle_number resets to 0, a fresh
    ServiceProgressState) rather than mutate an inherited one."""
    if state_record is None:
        return False, "NO_PERSISTED_STATE"
    recorded_pid = state_record.get("pid")
    if recorded_pid != current_pid:
        return False, (f"PID_MISMATCH: state belongs to pid={recorded_pid}, "
                       f"this process is pid={current_pid} -- treat as a "
                       f"fresh instance, not continuity")
    return True, "SAME_PROCESS"


def watchdog_classify(state_record: dict | None, *, current_pid: int,
                      pid_alive: bool) -> dict:
    """INDEPENDENT verification: the monitored service cannot mark
    itself healthy merely by writing a heartbeat. This function reasons
    from the PERSISTED record alone (as an external watchdog would),
    never trusting a self-reported progress_status string without
    re-deriving it, and explicitly flags the case that hid the 2026-08-17
    stall: heartbeat/cycle_start advancing while cycle completion does
    not."""
    if state_record is None:
        return {"progress_status": STOPPED if not pid_alive else STARTING,
               "reason": "no persisted state"}
    matches, why = check_pid_matches_state(state_record, current_pid)
    if not matches:
        return {"progress_status": STOPPED,
               "reason": f"stale state from a different process: {why}"}
    if not pid_alive:
        return {"progress_status": STOPPED, "reason": "pid not alive"}

    started_but_never_completed = (
        state_record.get("last_cycle_start") is not None
        and state_record.get("last_successful_cycle") is None)
    if started_but_never_completed:
        return {"progress_status": STALLED,
               "reason": "cycle_start is advancing but no cycle has ever "
                        "completed successfully -- heartbeat without "
                        "progress, the exact 2026-08-17 shape"}

    derived = ServiceProgressState(**{
        k: v for k, v in state_record.items()
        if k in ServiceProgressState.__dataclass_fields__})
    return {"progress_status": derived.progress_status(), "reason": None}
