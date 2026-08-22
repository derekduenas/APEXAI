#!/usr/bin/env python
"""INDEPENDENT PROGRESS WATCHDOG — reasons from the persisted state
alone, exactly as an external observer would; never trusts the
monitored process's self-reported status string without re-deriving it.

    python scripts/frontier_watchdog.py

The distinction this exists to enforce: a service cannot mark itself
healthy merely by writing a heartbeat. On 2026-08-17, frontier_loop.py's
heartbeat-equivalent (loop_state.json, the cycle-start log line) kept
advancing for ~3 hours while cycle_number effectively never reached a
successful completion -- "the PID is alive and printing" is not
"progress is being made." This script checks the SECOND thing.

decision_power: NONE. This can only OBSERVE and CLASSIFY.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_S = Path(__file__).resolve().parent
sys.path.insert(0, str(_S.parent))

from apex.governance.service_progress import (  # noqa: E402
    is_pid_alive, watchdog_classify,
)

STATE_PATH = Path("results/frontier/service_progress.json")


def check() -> dict:
    if not STATE_PATH.exists():
        return {"service": "frontier_loop", "progress_status": "STOPPED",
               "reason": "no service_progress.json has ever been written"}
    try:
        record = json.loads(STATE_PATH.read_text())
    except json.JSONDecodeError:
        return {"service": "frontier_loop", "progress_status": "STOPPED",
               "reason": "service_progress.json is corrupt/unreadable"}
    pid = record.get("pid")
    alive = is_pid_alive(pid) if isinstance(pid, int) else False
    verdict = watchdog_classify(record, current_pid=pid, pid_alive=alive)
    return {
        "service": record.get("service_name", "frontier_loop"),
        "pid": pid, "pid_alive": alive,
        "cycle_number": record.get("cycle_number"),
        "last_successful_cycle": record.get("last_successful_cycle"),
        "consecutive_failures": record.get("consecutive_failures"),
        "total_failures": record.get("total_failures"),
        "self_reported_status": record.get("progress_status"),
        "watchdog_status": verdict["progress_status"],
        "watchdog_reason": verdict["reason"],
        "agrees_with_self_report": (
            verdict["progress_status"] == record.get("progress_status")),
    }


def main() -> int:
    result = check()
    print(json.dumps(result, indent=1, default=str))
    if result["watchdog_status"] in ("STALLED", "FAILED", "STOPPED"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
