"""PREMARKET_RUN_RECORD_V1 — every scheduled run leaves a record, including one that failed before the packet.

The 19-day gap was invisible because a run that never produced a packet left NOTHING: no packet, no log line, no
record. "Did it run?" was unanswerable from artifacts, and `launchctl list` reported `LastExitStatus = 0`, which
is the INITIAL value and not evidence of a run -- `runs = 0` was the fact that settled it.

So a record is written at START, updated at each stage, and finalised on every exit path. A provider failure
produces a FAILED record, never silence."""
from __future__ import annotations

import json
import os
import pathlib
import socket
import time

SCHEMA = "PREMARKET_RUN_RECORD_V1"
RUNS = pathlib.Path("results/frontier/premarket/runs")
STAGES = ("STARTED", "SOURCES", "AI", "PACKET", "SEALED", "FINISHED")


class LockHeld(RuntimeError):
    pass


class RunLock:
    """A bounded lock so two invocations cannot overwrite one another. A STALE lock is DIAGNOSED, never silently
    stolen: the holder's pid and age are reported and recovery is a reviewed action."""

    def __init__(self, name="premarket", *, max_age_s: float = 3600.0, now=time.time):
        self.path = RUNS / ("%s.lock" % name)
        self.max_age_s, self.now = max_age_s, now

    def acquire(self, run_id: str) -> dict:
        RUNS.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            try:
                held = json.loads(self.path.read_text())
            except Exception:
                held = {"pid": None, "at": 0, "run_id": "UNREADABLE"}
            age = self.now() - float(held.get("at") or 0)
            alive = _pid_alive(held.get("pid"))
            raise LockHeld("PREMARKET_RUN_LOCKED: held by run %r pid %r for %.0fs (holder alive: %s). %s"
                           % (held.get("run_id"), held.get("pid"), age, alive,
                              "STALE (older than %.0fs) -- recovery is a reviewed action, not automatic"
                              % self.max_age_s if age > self.max_age_s else "ACTIVE"))
        body = {"run_id": run_id, "pid": os.getpid(), "at": self.now(), "host": socket.gethostname()}
        self.path.write_text(json.dumps(body))
        return body

    def release(self):
        if self.path.exists():
            self.path.unlink()


def _pid_alive(pid):
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except Exception:
        return False


class RunRecord:
    def __init__(self, *, run_id: str, scheduled_epoch=None, code_identity=None, now=time.time):
        self.now = now
        RUNS.mkdir(parents=True, exist_ok=True)
        self.path = RUNS / ("%s.json" % run_id)
        if self.path.exists():
            raise FileExistsError("RUN_RECORD_EXISTS: %s -- run records are never overwritten" % self.path)
        self.body = {"schema": SCHEMA, "run_id": run_id, "scheduled_epoch": scheduled_epoch,
                     "started_epoch": now(), "finished_epoch": None, "pid": os.getpid(),
                     "code_identity": code_identity, "stage": "STARTED", "stages": {}, "exit_status": None,
                     "failure_stage": None, "failure_reason": None, "output_identity": None}
        self._write()

    def stage(self, name: str, status: str, **detail):
        if name not in STAGES:
            raise ValueError("UNKNOWN_STAGE: %r" % name)
        self.body["stage"] = name
        self.body["stages"][name] = {"status": status, "at": self.now(), **detail}
        self._write()

    def fail(self, stage: str, reason: str):
        self.body.update(failure_stage=stage, failure_reason=str(reason)[:400], exit_status="FAILED",
                         finished_epoch=self.now())
        self._write()

    def finish(self, *, output_identity=None, exit_status="OK"):
        self.body.update(output_identity=output_identity, exit_status=exit_status, finished_epoch=self.now(),
                         stage="FINISHED")
        self._write()

    def _write(self):
        self.path.write_text(json.dumps(self.body, indent=1, default=str) + "\n")
