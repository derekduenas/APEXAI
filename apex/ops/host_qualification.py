"""HOST QUALIFICATION — a degraded host does not get a commissioning day.

2026-08-25: 175 `host_on_battery`, 4 `host_network_unreachable`, 75
`host_data_progression_stalled` (worst bar 1,426s stale), and tape
continuity 0.8103 — beside a PERFECT data-quality record (zero
malformed, duplicate, out-of-order or provider errors). The fabric
did nothing wrong. The laptop did.

An L2 acceptance attempt on a battery-powered host with intermittent
network is not a failed experiment, it is a wasted one: it burns a
prospective session and produces a number nobody can interpret. So
the pre-open gate now refuses.

    AC_POWER        required   a required market-data service may not
                               depend on a battery
    NETWORK_STABLE  required   recent unreachable events disqualify
    DISK_OK         required   evidence must have somewhere to land
    FABRIC_READY    required   the transport is up and progressing

Failure is `SAFE_BLOCKED`, which is a legitimate, recorded outcome —
NOT a failed acceptance. The distinction matters: a blocked day says
nothing about whether the fabric can hold a clean tape, and must
never be counted against it.

decision_power: NONE_OPERATIONAL.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

MIN_FREE_GB = 5.0
NETWORK_LOOKBACK_H = 6
MAX_RECENT_NETWORK_FAILURES = 0
MAX_RECENT_STALLS = 3
HOST_INCIDENTS = Path("results/host/host_incidents.jsonl")


def on_ac_power() -> tuple:
    """macOS: `pmset -g batt` reports the power source in line 1."""
    try:
        out = subprocess.run(["pmset", "-g", "batt"],
                             capture_output=True, text=True,
                             timeout=10).stdout
    except Exception as e:                               # noqa: BLE001
        return None, f"power source unreadable: {e!r}"
    low = out.lower()
    if "ac power" in low:
        return True, "AC Power"
    if "battery power" in low:
        return False, "Battery Power -- a required market-data " \
                      "service may not depend on a battery"
    return None, f"indeterminate power source: {out.splitlines()[:1]}"


def recent_host_incidents(*, kinds: tuple, hours: int,
                          now: datetime | None = None,
                          path: Path | None = None) -> list:
    p = path or HOST_INCIDENTS
    if not p.exists():
        return []
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=hours)
    out = []
    for line in p.read_text().splitlines()[-20000:]:
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except Exception:                                # noqa: BLE001
            continue
        if r.get("kind") not in kinds:
            continue
        ts = r.get("detected_at")
        if not ts:
            continue
        try:
            t = datetime.fromisoformat(ts)
        except ValueError:
            continue
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        if t >= cutoff:
            out.append(r)
    return out


def disk_ok(path: str = ".") -> tuple:
    try:
        u = shutil.disk_usage(path)
    except Exception as e:                               # noqa: BLE001
        return None, f"disk unreadable: {e!r}"
    free_gb = u.free / 1e9
    return (free_gb >= MIN_FREE_GB,
            f"{free_gb:.1f}GB free (need >= {MIN_FREE_GB}GB); "
            f"evidence must have somewhere to land")


def qualify_host(*, now: datetime | None = None,
                 fabric_ready: bool | None = None,
                 incidents_path: Path | None = None) -> dict:
    """Four required checks. Any failure blocks the session SAFELY."""
    checks = []

    ac, ac_detail = on_ac_power()
    checks.append({"check": "AC_POWER", "ok": bool(ac),
                   "detail": ac_detail, "required": True})

    net = recent_host_incidents(kinds=("host_network_unreachable",),
                                hours=NETWORK_LOOKBACK_H, now=now,
                                path=incidents_path)
    checks.append({
        "check": "NETWORK_STABLE",
        "ok": len(net) <= MAX_RECENT_NETWORK_FAILURES,
        "detail": f"{len(net)} unreachable event(s) in the last "
                  f"{NETWORK_LOOKBACK_H}h (max "
                  f"{MAX_RECENT_NETWORK_FAILURES})",
        "required": True})

    stalls = recent_host_incidents(
        kinds=("host_data_progression_stalled",),
        hours=NETWORK_LOOKBACK_H, now=now, path=incidents_path)
    checks.append({
        "check": "NO_RECENT_PROGRESSION_STALLS",
        "ok": len(stalls) <= MAX_RECENT_STALLS,
        "detail": f"{len(stalls)} stall(s) in the last "
                  f"{NETWORK_LOOKBACK_H}h (max {MAX_RECENT_STALLS})",
        "required": True})

    d_ok, d_detail = disk_ok()
    checks.append({"check": "DISK_OK", "ok": bool(d_ok),
                   "detail": d_detail, "required": True})

    checks.append({
        "check": "FABRIC_READY",
        "ok": bool(fabric_ready),
        "detail": ("transport up and progressing" if fabric_ready
                   else "fabric not confirmed ready"),
        "required": True})

    failed = [c["check"] for c in checks if c["required"] and not c["ok"]]
    return {"kind": "host_qualification",
            "evaluated_utc": (now or datetime.now(timezone.utc)
                              ).isoformat(),
            "checks": checks, "blocking": failed,
            "verdict": "HOST_QUALIFIED" if not failed
                       else "SAFE_BLOCKED",
            "commissioning_eligible": not failed,
            "law": "SAFE_BLOCKED is a legitimate recorded outcome, "
                   "NOT a failed acceptance -- a blocked day says "
                   "nothing about whether the fabric can hold a clean "
                   "tape and must never be counted against it",
            "decision_power": "NONE_OPERATIONAL"}
