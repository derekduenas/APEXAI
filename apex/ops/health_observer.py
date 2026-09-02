"""APEX_HEALTH_OBSERVER_V0 -- observes from OUTSIDE the process.

THE LAW THIS ENCODES
--------------------
A SYSTEM CANNOT SELF-REPORT ITS OWN ABSENCE.

WHY
---
All 77 PULSE OOM kills were invisible from inside PULSE: the process
was SIGKILLed before it could write anything, so its own ledgers and
heartbeats recorded nothing at all. An hour of blindness was discovered
by end-of-day forensics, not by monitoring. Any observer that reads
only the monitored service's own output inherits exactly that
blindness.

So this observer's authoritative inputs are SUBSTRATE inputs --
systemd lifecycle, the timer schedule, kernel OOM records -- reconciled
against canonical output. Heartbeats are corroboration, never proof.

It also reconciles heartbeat artifacts against a REGISTRY, so that an
orphaned heartbeat (capital-arena-shadow, whose unit is NOT-FOUND)
cannot masquerade as an active monitored organ, and a service that
should exist cannot vanish merely by leaving no file behind.
"""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path

OBSERVER_VERSION = "APEX_HEALTH_OBSERVER_V0"


class Registration(Enum):
    REGISTERED_ACTIVE = "REGISTERED_ACTIVE"
    REGISTERED_SCHEDULED = "REGISTERED_SCHEDULED"
    INTENTIONALLY_DISABLED = "INTENTIONALLY_DISABLED"
    DECOMMISSIONED = "DECOMMISSIONED"
    ORPHAN_ARTIFACT = "ORPHAN_ARTIFACT"      # heartbeat with no unit
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class Registered:
    """A service the observer is responsible for knowing about."""
    unit: str
    registration: Registration
    heartbeat: str | None = None
    note: str = ""


# ---------------------------------------------------------------- probes
def _sh(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True,
                              timeout=30).stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return ""


def systemd_state(unit: str) -> dict:
    """Lifecycle facts from systemd -- authoritative over app logs."""
    out = _sh(["systemctl", "show", unit,
               "-p", "ActiveState", "-p", "SubState", "-p", "Result",
               "-p", "NRestarts", "-p", "UnitFileState",
               "-p", "ExecMainStatus", "-p", "MainPID",
               "-p", "MemoryCurrent", "-p", "MemoryPeak",
               "-p", "MemoryMax", "-p", "Slice"])
    d: dict = {}
    for ln in out.splitlines():
        if "=" in ln:
            k, v = ln.split("=", 1)
            d[k] = v
    return d


def kernel_oom_events(unit: str, since: str = "-24h") -> list[dict]:
    """OOM kills naming this unit. THIS is how a service that died
    before writing anything still leaves a trace."""
    out = _sh(["sudo", "journalctl", "-k", "--since", since,
               "--no-pager", "-o", "short-iso"])
    ev = []
    for ln in out.splitlines():
        if "oom-kill:" not in ln or unit not in ln:
            continue
        ts = ln.split()[0]
        ev.append({
            "at": ts,
            "global": "CONSTRAINT_NONE" in ln,
            "cgroup_limit": "CONSTRAINT_MEMCG" in ln,
        })
    return ev


def systemd_lifecycle_events(unit: str, since: str) -> dict:
    """Start / finish / failure events for cadence classification."""
    out = _sh(["sudo", "journalctl", "-u", unit, "--since", since,
               "--no-pager", "-o", "short-iso"])
    starts, finished, failed, oom = [], [], [], []
    for ln in out.splitlines():
        m = re.match(r"^(\S+) \S+ systemd\[1\]: (.*)$", ln)
        if not m:
            continue
        try:
            t = datetime.fromisoformat(m.group(1))
        except ValueError:
            continue
        msg = m.group(2)
        if msg.startswith("Starting "):
            starts.append(t)
        elif "Finished " in msg:
            finished.append(t)
        elif "Failed to start" in msg or "Failed with result" in msg:
            failed.append(t)
        if "killed by the OOM killer" in msg:
            oom.append(t)
    return {"starts": starts, "finished": finished,
            "failed": failed, "oom": oom}


def host_pressure() -> dict:
    """Host-level memory facts. Zero swap means pressure produces a
    kill rather than a slowdown, so it is reported explicitly."""
    mem = {}
    try:
        for ln in Path("/proc/meminfo").read_text().splitlines():
            k, _, v = ln.partition(":")
            mem[k] = int(v.strip().split()[0]) * 1024
    except OSError:
        return {"available": None}
    total = mem.get("MemTotal", 0)
    avail = mem.get("MemAvailable", 0)
    swap = mem.get("SwapTotal", 0)
    return {
        "ram_bytes": total,
        "available_bytes": avail,
        "swap_bytes": swap,
        "available_fraction": round(avail / total, 4) if total else None,
        "has_swap_buffer": swap > 0,
        "PRESSURE": bool(total) and avail < 0.15 * total,
    }


# ------------------------------------------------------------- registry
def reconcile_registry(registry: list[Registered],
                       heartbeat_dir: Path,
                       now: datetime | None = None) -> dict:
    """Every heartbeat file must map to a registered unit, and every
    registered unit's absence must be explainable."""
    now = now or datetime.now(timezone.utc)
    by_hb = {r.heartbeat: r for r in registry if r.heartbeat}
    found, orphans, missing = [], [], []

    if heartbeat_dir.exists():
        for p in sorted(heartbeat_dir.glob("*.json")):
            age_s = (now - datetime.fromtimestamp(
                p.stat().st_mtime, timezone.utc)).total_seconds()
            reg = by_hb.get(p.name)
            row = {"file": p.name, "age_s": round(age_s, 1)}
            if reg is None:
                row["registration"] = Registration.ORPHAN_ARTIFACT.value
                row["verdict"] = (
                    "ORPHAN -- no registered unit owns this heartbeat; "
                    "it must NOT be read as an active monitored organ")
                orphans.append(row)
            else:
                row["unit"] = reg.unit
                row["registration"] = reg.registration.value
                found.append(row)

    seen = {r["file"] for r in found}
    for r in registry:
        if r.heartbeat and r.heartbeat not in seen:
            missing.append({
                "unit": r.unit, "heartbeat": r.heartbeat,
                "registration": r.registration.value,
                "verdict": ("expected heartbeat absent -- absence of a "
                            "file is NOT absence of a service")})
    return {"registered_found": found, "orphans": orphans,
            "expected_but_missing": missing,
            "LAW": "an orphaned heartbeat must never appear to "
                   "represent an active monitored organ"}


def observe(unit: str, *, since: str = "-24h") -> dict:
    """One service, observed entirely from outside itself."""
    sd = systemd_state(unit)
    ooms = kernel_oom_events(unit, since=since)
    return {
        "version": OBSERVER_VERSION,
        "unit": unit,
        "observed_utc": datetime.now(timezone.utc).isoformat(),
        "systemd": {
            "ActiveState": sd.get("ActiveState"),
            "SubState": sd.get("SubState"),
            "Result": sd.get("Result"),
            "NRestarts": int(sd.get("NRestarts") or 0),
            "UnitFileState": sd.get("UnitFileState"),
            "Slice": sd.get("Slice"),
            "MemoryCurrent": sd.get("MemoryCurrent"),
            "MemoryPeak": sd.get("MemoryPeak"),
            "MemoryMax": sd.get("MemoryMax")},
        "oom": {
            "count": len(ooms),
            "global": sum(1 for e in ooms if e["global"]),
            "cgroup": sum(1 for e in ooms if e["cgroup_limit"]),
            "events": ooms[:10]},
        "host": host_pressure(),
        "LAW": "substrate evidence (systemd + kernel) outranks any "
               "self-written heartbeat; a process killed before it "
               "could write leaves no application trace at all",
    }
