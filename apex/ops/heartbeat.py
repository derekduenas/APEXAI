"""HEARTBEAT — liveness that is not fooled by a live process.

The Phase A daemon taught the distinction this module is built around:
a process can be alive and doing nothing, and a process can be dead
with nobody noticing for seven hours. So:

    PROCESS EXISTENCE IS NOT HEALTH.

A heartbeat therefore records PROGRESS, not merely presence. The states
below separate the failures that look identical from the outside:

    HEALTHY    beating, and work is completing
    STARTING   beating, recently started, work not finished yet
    STALLED    beating, but no unit of work has completed
    STALE      not beating recently enough
    DEAD       the recorded pid is gone
    WRONG_RELEASE  running code that is not the approved release
    NEVER_STARTED  no heartbeat has ever been written

STALLED is the state most systems omit, and it is the one that hides
the longest: a daemon looping on a failing API forever looks perfectly
alive to anything that only checks the pid.

Thresholds are per-service and declared by the caller, because "slow"
means different things to a 15-minute options scanner and a continuous
tick recorder. There is no global default that is honest for both.

decision_power: NONE -- an operational primitive.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

HEARTBEAT_DIR = Path(os.environ.get("APEX_HEARTBEAT_DIR",
                                    "/apex-data/core/heartbeats"))

HEALTH_STATES = ("HEALTHY", "STARTING", "STALLED", "STALE", "DEAD",
                 "WRONG_RELEASE", "NEVER_STARTED")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse(ts) -> datetime | None:
    if not ts:
        return None
    try:
        d = datetime.fromisoformat(str(ts))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


@dataclass
class Heartbeat:
    service: str
    pid: int = field(default_factory=os.getpid)
    release_commit: str | None = None
    release_path: str | None = None
    authority: str = "OBSERVE"
    started_utc: str = field(default_factory=lambda: _now().isoformat())
    beat_utc: str = field(default_factory=lambda: _now().isoformat())
    last_work_utc: str | None = None
    last_work_item: str | None = None
    work_completed: int = 0
    last_error: str | None = None
    last_error_utc: str | None = None
    backlog_remaining: int | str = "NOT_ESTIMABLE"
    notes: dict = field(default_factory=dict)

    # ---------------------------------------------------------- write
    def path(self, root: Path | None = None) -> Path:
        return Path(root or HEARTBEAT_DIR) / f"{self.service}.json"

    def beat(self, root: Path | None = None) -> Path:
        """Record presence. Does NOT claim progress."""
        self.beat_utc = _now().isoformat()
        return self._write(root)

    def work(self, item: str, *, backlog=None,
             root: Path | None = None) -> Path:
        """Record a COMPLETED unit of work -- the thing that
        distinguishes healthy from stalled."""
        self.work_completed += 1
        self.last_work_item = item
        self.last_work_utc = _now().isoformat()
        if backlog is not None:
            self.backlog_remaining = backlog
        return self.beat(root)

    def error(self, message: str, root: Path | None = None) -> Path:
        # never persist a secret value; callers pass types, not payloads
        self.last_error = str(message)[:500]
        self.last_error_utc = _now().isoformat()
        return self.beat(root)

    def _write(self, root: Path | None = None) -> Path:
        p = self.path(root)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(
            {"kind": "apex_heartbeat", **asdict(self)}, indent=1))
        os.replace(tmp, p)          # atomic: a reader never sees a tear
        return p


def _pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except (ProcessLookupError, ValueError):
        return False
    except PermissionError:
        return True                 # exists, owned by someone else


def read(service: str, root: Path | None = None) -> dict | None:
    p = Path(root or HEARTBEAT_DIR) / f"{service}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        return None


def health(service: str, *, beat_stale_s: float,
           work_stale_s: float | None = None,
           expected_commit: str | None = None,
           root: Path | None = None, now: datetime | None = None
           ) -> dict:
    """Classify one service. Thresholds are the caller's to declare."""
    now = now or _now()
    hb = read(service, root)
    if hb is None:
        return {"kind": "service_health", "service": service,
                "state": "NEVER_STARTED",
                "why": "no heartbeat has ever been written -- the "
                       "service has not run, or cannot write its "
                       "heartbeat"}

    pid, beat = hb.get("pid"), _parse(hb.get("beat_utc"))
    beat_age = (now - beat).total_seconds() if beat else None
    work = _parse(hb.get("last_work_utc"))
    work_age = (now - work).total_seconds() if work else None

    base = {"kind": "service_health", "service": service, "pid": pid,
            "release_commit": hb.get("release_commit"),
            "beat_age_s": round(beat_age, 1) if beat_age else None,
            "work_age_s": round(work_age, 1) if work_age else None,
            "work_completed": hb.get("work_completed"),
            "backlog_remaining": hb.get("backlog_remaining"),
            "last_error": hb.get("last_error"),
            "authority": hb.get("authority")}

    if not _pid_alive(pid):
        return {**base, "state": "DEAD",
                "why": f"pid {pid} is gone; last beat "
                       f"{round(beat_age or 0)}s ago"}

    if expected_commit and hb.get("release_commit") and \
            hb["release_commit"] != expected_commit:
        return {**base, "state": "WRONG_RELEASE",
                "why": f"running {hb['release_commit'][:8]} but the "
                       f"approved release is {expected_commit[:8]}"}

    if beat_age is None or beat_age > beat_stale_s:
        return {**base, "state": "STALE",
                "why": f"last beat {round(beat_age or 0)}s ago exceeds "
                       f"{round(beat_stale_s)}s -- the process exists "
                       f"but is not reporting"}

    # STARTUP GRACE. A freshly restarted daemon has legitimately not
    # finished a unit of work yet. Calling that STALLED would fire an
    # alert on every restart, and an alert that cries wolf gets ignored
    # -- the same way a buffered empty log got ignored.
    started = _parse(hb.get("started_utc"))
    start_age = (now - started).total_seconds() if started else None
    if work_stale_s is not None and start_age is not None \
            and start_age < work_stale_s and hb.get("work_completed", 0) == 0:
        return {**base, "state": "STARTING",
                "why": f"started {round(start_age)}s ago and has not "
                       f"completed a unit of work yet; within the "
                       f"{round(work_stale_s)}s startup grace"}

    if work_stale_s is not None:
        if work_age is None:
            return {**base, "state": "STALLED",
                    "why": "alive and beating, but no unit of work has "
                           "EVER completed"}
        if work_age > work_stale_s:
            return {**base, "state": "STALLED",
                    "why": f"alive and beating, but no work completed "
                           f"for {round(work_age)}s (limit "
                           f"{round(work_stale_s)}s) -- presence is not "
                           f"progress"}

    return {**base, "state": "HEALTHY",
            "why": f"beating and completing work "
                   f"({hb.get('work_completed')} units)"}


def summarize(reports: list) -> dict:
    # STARTING is not a problem; it is a daemon doing exactly what a
    # daemon does after a restart.
    bad = [r for r in reports if r["state"] not in ("HEALTHY", "STARTING")]
    return {"kind": "apex_health_summary",
            "services": len(reports),
            "healthy": len(reports) - len(bad),
            "unhealthy": len(bad),
            "states": {r["service"]: r["state"] for r in reports},
            "attention": [{"service": r["service"], "state": r["state"],
                           "why": r["why"]} for r in bad],
            "verdict": "ALL_HEALTHY" if not bad else "ATTENTION_REQUIRED",
            "law": "process existence is not health; a daemon looping "
                   "on a failing call is alive and useless"}
