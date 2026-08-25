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
                 "WRONG_RELEASE", "NEVER_STARTED", "RESTART_LOOPING",
                 "EXPECTED_IDLE", "UNEXPECTEDLY_RUNNING")

# EXPECTED LIFECYCLE. Health is only meaningful relative to what the
# service is SUPPOSED to be doing right now. A paper daemon that is
# down at midnight because the market is closed is not a fault, and
# reporting it as one trains the operator to ignore the health check --
# which is precisely how a real daemon died unnoticed for seven hours.
#
# The inverse matters just as much: a service that is running when it
# should be stopped is a genuine finding, not a happy accident.
LIFECYCLE_STATES = ("EXPECTED_RUNNING", "EXPECTED_STOPPED",
                    "EXPECTED_DISABLED", "EXPECTED_ON_DEMAND")

# Idle-tolerant lifecycles: absence is the correct observation.
_IDLE_OK = ("EXPECTED_STOPPED", "EXPECTED_DISABLED", "EXPECTED_ON_DEMAND")
_ABSENT = ("DEAD", "NEVER_STARTED", "STALE", "STALLED")

SEVERITY = {
    "HEALTHY": "OK", "STARTING": "OK", "EXPECTED_IDLE": "OK",
    "STALE": "DEGRADED", "STALLED": "DEGRADED",
    "DEAD": "CRITICAL", "WRONG_RELEASE": "CRITICAL",
    "NEVER_STARTED": "CRITICAL", "RESTART_LOOPING": "CRITICAL",
    "UNEXPECTEDLY_RUNNING": "CRITICAL",
}

# A process that dies and is restarted every few minutes completes a
# little work each life, so heartbeats alone read HEALTHY. Only the
# supervisor's restart counter reveals it -- the 2026-08-24 OOM loop
# ran 69 restarts while health said fine.
RESTART_LOOP_THRESHOLD = 3


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


def _classify(service: str, *, beat_stale_s: float,
              work_stale_s: float | None = None,
              expected_commit: str | None = None,
              restarts_since_last_check: int | None = None,
              root: Path | None = None, now: datetime | None = None
              ) -> dict:
    """Classify one service from its heartbeat alone. Thresholds are
    the caller's to declare."""
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

    if isinstance(restarts_since_last_check, int) and \
            restarts_since_last_check >= RESTART_LOOP_THRESHOLD:
        return {**base, "state": "RESTART_LOOPING",
                "why": f"{restarts_since_last_check} supervisor restarts "
                       f"since the last check -- the process is dying and "
                       f"being revived, which heartbeats alone cannot see"}

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


def _reconcile(report: dict, expected: str) -> dict:
    """Reconcile an observed state against the expected lifecycle.

    The observation is NEVER destroyed. When absence is expected the
    state becomes EXPECTED_IDLE, but the state that was actually
    observed is retained as `observed_state` -- otherwise tonight's
    legitimate idleness would erase the record of a daemon that died
    mid-session this morning when it was supposed to be working."""
    st = report["state"]
    out = {**report, "expected_lifecycle": expected}
    if expected in _IDLE_OK and st in _ABSENT:
        out.update({
            "state": "EXPECTED_IDLE", "observed_state": st,
            "why": f"expected {expected}; observed {st} "
                   f"({report.get('why', '')}). Absence is the correct "
                   f"state right now -- this is not a fault, and the "
                   f"observation is retained, not erased"})
    elif expected in ("EXPECTED_STOPPED", "EXPECTED_DISABLED") and \
            st in ("HEALTHY", "STARTING", "RESTART_LOOPING"):
        out.update({
            "state": "UNEXPECTEDLY_RUNNING", "observed_state": st,
            "why": f"expected {expected} but the service is {st}. "
                   f"Something started that should not be running"})
    out["severity"] = SEVERITY.get(out["state"], "CRITICAL")
    return out


def health(service: str, *, beat_stale_s: float,
           work_stale_s: float | None = None,
           expected_commit: str | None = None,
           restarts_since_last_check: int | None = None,
           expected_lifecycle: str = "EXPECTED_RUNNING",
           root: Path | None = None, now: datetime | None = None
           ) -> dict:
    """Classify one service AGAINST ITS EXPECTED LIFECYCLE.

    Only the caller knows whether this service is supposed to be up
    right now, so the expectation is an argument, never a guess. The
    default is EXPECTED_RUNNING, which preserves the strict behaviour
    for anything that has not declared otherwise -- a service nobody
    thought about should still be able to alarm."""
    if expected_lifecycle not in LIFECYCLE_STATES:
        raise ValueError(
            f"unknown expected lifecycle {expected_lifecycle!r}; health "
            f"is meaningless without knowing what was expected")
    report = _classify(
        service, beat_stale_s=beat_stale_s, work_stale_s=work_stale_s,
        expected_commit=expected_commit,
        restarts_since_last_check=restarts_since_last_check,
        root=root, now=now)
    return _reconcile(report, expected_lifecycle)


def summarize(reports: list) -> dict:
    # STARTING is not a problem; it is a daemon doing exactly what a
    # daemon does after a restart. EXPECTED_IDLE is not a problem
    # either -- it is a service correctly doing nothing.
    bad = [r for r in reports
           if SEVERITY.get(r["state"], "CRITICAL") != "OK"]
    crit = [r for r in bad
            if SEVERITY.get(r["state"]) == "CRITICAL"]
    return {"kind": "apex_health_summary",
            "services": len(reports),
            "healthy": len(reports) - len(bad),
            "unhealthy": len(bad),
            "critical": len(crit),
            "states": {r["service"]: r["state"] for r in reports},
            "severities": {r["service"]: SEVERITY.get(r["state"],
                                                      "CRITICAL")
                           for r in reports},
            "idle_by_design": [r["service"] for r in reports
                               if r["state"] == "EXPECTED_IDLE"],
            "attention": [{"service": r["service"], "state": r["state"],
                           "severity": SEVERITY.get(r["state"],
                                                    "CRITICAL"),
                           "observed_state": r.get("observed_state"),
                           "why": r["why"]} for r in bad],
            "verdict": ("ALL_HEALTHY" if not bad else
                        "CRITICAL" if crit else "DEGRADED"),
            "law": "process existence is not health, and neither is "
                   "process absence a fault -- health is measured "
                   "against the EXPECTED lifecycle state"}
