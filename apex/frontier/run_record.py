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


def runs_dir() -> pathlib.Path:
    """Honours the same declared output root as the packet writer, so run accounting and packets can never end up
    in two different places during one morning. When no root is declared the module constant stands, which keeps
    the existing `monkeypatch.setattr(RR, "RUNS", ...)` seam working exactly as before."""
    import os

    from apex.frontier import premarket_runtime as RT
    return (RT.root() / "runs") if os.environ.get(RT.ENV_ROOT) else RUNS
STAGES = ("STARTED", "SOURCES", "AI", "PACKET", "SEALED", "FINISHED")


class LockHeld(RuntimeError):
    pass


class RunLock:
    """A bounded lock so two invocations cannot overwrite one another.

    R4 REFINEMENT, and why it is not a retreat from R3's rule. R3 said a stale lock is DIAGNOSED, never silently
    stolen, and keyed staleness on AGE. The failure flights showed what that costs once the morning is many
    processes: a stage killed mid-run leaves its lock behind, every retry is refused, and the morning is lost
    permanently by the very mechanism meant to protect it.

    So the test is no longer age, which is a proxy, but LIVENESS, which is the fact:
      * holder process ALIVE            -> refused, at any age. A living holder is never displaced.
      * holder pid unknown/unreadable   -> refused. A lock being written right now looks like an abandoned one.
      * holder process GONE             -> taken over, and the dead holder is RECORDED in the new lock body and
                                           returned to the caller. Diagnosed, not silent -- which was always the
                                           actual requirement.
    `takeover_dead=False` restores the strict R3 behaviour for callers that want it."""

    def __init__(self, name="premarket", *, max_age_s: float = 3600.0, now=time.time, takeover_dead=True):
        self.path = runs_dir() / ("%s.lock" % name)
        self.max_age_s, self.now, self.takeover_dead = max_age_s, now, takeover_dead

    def acquire(self, run_id: str) -> dict:
        runs_dir().mkdir(parents=True, exist_ok=True)
        took_over = None
        if self.path.exists():
            try:
                held = json.loads(self.path.read_text())
            except Exception:
                held = {"pid": None, "at": 0, "run_id": "UNREADABLE"}
            age = self.now() - float(held.get("at") or 0)
            alive = _pid_alive(held.get("pid"))
            if alive or not self.takeover_dead or not held.get("pid"):
                raise LockHeld("PREMARKET_RUN_LOCKED: held by run %r pid %r for %.0fs (holder alive: %s). %s"
                               % (held.get("run_id"), held.get("pid"), age, alive,
                                  "STALE (older than %.0fs) -- recovery is a reviewed action, not automatic"
                                  % self.max_age_s if age > self.max_age_s else "ACTIVE"))
            took_over = held
        body = {"run_id": run_id, "pid": os.getpid(), "at": self.now(), "host": socket.gethostname()}
        if took_over is not None:
            body["took_over_from"] = took_over
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


def next_run_id(day: str, stage: str) -> str:
    """A run record is PER INVOCATION, not per stage.

    This was wrong in the first cut of the staged CLI and the failure flights caught it: the record was named
    `<day>_<stage>`, so after a crash the retry found the file, reported DUPLICATE and exited -- a crashed stage
    could never resume. Exactly-once absorption is the JOURNAL CLAIM's job (an O_EXCL create), not a filename's.
    One mechanism, one job."""
    runs_dir().mkdir(parents=True, exist_ok=True)
    base = "%s_%s" % (day, stage)
    if not (runs_dir() / ("%s.json" % base)).exists():
        return base
    n = 2
    while (runs_dir() / ("%s_attempt%02d.json" % (base, n))).exists():
        n += 1
    return "%s_attempt%02d" % (base, n)


class RunRecord:
    def __init__(self, *, run_id: str, scheduled_epoch=None, code_identity=None, now=time.time):
        self.now = now
        runs_dir().mkdir(parents=True, exist_ok=True)
        self.path = runs_dir() / ("%s.json" % run_id)
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
