#!/usr/bin/env python
"""LAYER 0 -- HOST SENTINEL (Commissioning, 2026-08-21).

WHY THIS EXISTS. On Friday 2026-08-21 the laptop's lid was closed on
battery at 09:56 ET and macOS duty-cycled maintenance sleep for the rest
of the session, destroying ~26% of the regular-session tape -- while
every downstream organ looked innocent and the fabric's own coverage
axis said 1.0. Layer 0 law: the session may not silently continue
through host sleep. Sleep must be DETECTED within seconds and recorded
as a durable incident, so no downstream layer can ever again be blamed
for a host failure.

MECHANISM. time.monotonic() pauses during macOS sleep; time.time() does
not. Each beat records both; wall_delta - mono_delta > SLEEP_GAP_S
means the host slept between beats, for approximately that difference.
Each beat also samples power source (pmset), disk free, network
reachability, and clock/timezone sanity.

WHAT IT CANNOT DO, honestly: prevent clamshell sleep. Userland cannot
override lid-close sleep; only the operator can (lid open + AC, or
`sudo pmset disablesleep 1`, or moving APEX off a laptop). This
sentinel makes the failure LOUD and attributable, which is Layer 0's
acceptance bar.

Writes: results/host/host_heartbeat.json      (latest state, overwritten)
        results/host/host_incidents.jsonl     (append-only incidents)

decision_power: NONE.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import time
from pathlib import Path

BEAT_INTERVAL_S = 15.0
SLEEP_GAP_S = 45.0                # wall-vs-monotonic divergence => slept
DISK_MIN_GB = 3.0
HEARTBEAT = Path("results/host/host_heartbeat.json")
INCIDENTS = Path("results/host/host_incidents.jsonl")


def _power() -> dict:
    try:
        out = subprocess.run(["pmset", "-g", "batt"], capture_output=True,
                             text=True, timeout=5).stdout
        return {"on_ac": "AC Power" in out,
                "battery_pct": next((tok.rstrip("%;")
                                     for tok in out.split()
                                     if tok.rstrip("%;").isdigit()), None)}
    except Exception:                                       # noqa: BLE001
        return {"on_ac": None, "battery_pct": None}


def _network_ok() -> bool:
    try:
        with socket.create_connection(("1.1.1.1", 53), timeout=3):
            return True
    except OSError:
        return False


def _disk_free_gb() -> float:
    st = os.statvfs("/")
    return st.f_bavail * st.f_frsize / 1e9


def _incident(kind: str, detail: dict) -> None:
    INCIDENTS.parent.mkdir(parents=True, exist_ok=True)
    rec = {"kind": f"host_{kind}", "detected_at": _now_iso(),
           **detail, "decision_power": "NONE"}
    with INCIDENTS.open("a") as fh:
        fh.write(json.dumps(rec) + "\n")
    print(f"HOST INCIDENT {kind}: {detail}", flush=True)


def _now_iso() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S%z", time.localtime())


DATA_STALL_AFTER_S = 180.0
_REFERENCE_BAR_FILE = "data/live/alpaca_fabric/bars/SPY_{day}.json"
_last_stall_report = 0.0


def _data_progression_check() -> dict | None:
    """During ET regular hours: the SPY session file's newest bar must be
    younger than DATA_STALL_AFTER_S. Returns an incident dict when
    stalled (rate-limited to one report per stall window), else None."""
    global _last_stall_report
    try:
        import datetime
        import zoneinfo
        et = datetime.datetime.now(
            zoneinfo.ZoneInfo("America/New_York"))
        if et.weekday() >= 5:
            return None
        mins = et.hour * 60 + et.minute
        if not (9 * 60 + 32 <= mins <= 16 * 60):    # grace past 09:30
            return None
        day = et.strftime("%Y-%m-%d")
        p = Path(_REFERENCE_BAR_FILE.format(day=day))
        if not p.exists():
            age = None
        else:
            bars = json.loads(p.read_text()).get("bars", [])
            if not bars:
                age = None
            else:
                newest = max(b.get("event_time_utc", "") for b in bars)
                newest_dt = datetime.datetime.fromisoformat(
                    newest.replace("Z", "+00:00"))
                age = (datetime.datetime.now(datetime.timezone.utc)
                       - newest_dt).total_seconds()
        stalled = age is None or age > DATA_STALL_AFTER_S
        if stalled and time.time() - _last_stall_report > 300:
            _last_stall_report = time.time()
            return {"newest_bar_age_s": (round(age, 1)
                                         if age is not None else None),
                    "threshold_s": DATA_STALL_AFTER_S,
                    "reference": str(p)}
        return None
    except Exception:                                   # noqa: BLE001
        return None


def main() -> int:
    print(f"HOST SENTINEL start beat={BEAT_INTERVAL_S}s "
          f"sleep_gap={SLEEP_GAP_S}s", flush=True)
    prev_wall, prev_mono = time.time(), time.monotonic()
    incidents_today = 0
    while True:
        time.sleep(BEAT_INTERVAL_S)
        wall, mono = time.time(), time.monotonic()
        wall_d, mono_d = wall - prev_wall, mono - prev_mono
        divergence = wall_d - mono_d
        if divergence > SLEEP_GAP_S:
            incidents_today += 1
            _incident("sleep_detected", {
                "slept_for_s": round(divergence, 1),
                "asleep_from_approx": time.strftime(
                    "%Y-%m-%d %H:%M:%S",
                    time.localtime(prev_wall)),
                "law": "the session may not silently continue through "
                       "host sleep -- Layer 0 commissioning, born of the "
                       "2026-08-21 clamshell incident"})
        prev_wall, prev_mono = wall, mono

        power = _power()
        disk = _disk_free_gb()
        net = _network_ok()
        if power.get("on_ac") is False:
            _incident("on_battery", {"battery_pct": power.get("battery_pct")})
        if disk < DISK_MIN_GB:
            _incident("disk_low", {"free_gb": round(disk, 2)})
        if not net:
            _incident("network_unreachable", {})

        # DATA-PROGRESSION WATCHDOG (operator requirement for L0 PASS):
        # during regular hours, the canonical tape must visibly advance.
        # A host that is awake while its data stands still is just as
        # failed as a sleeping one -- and this catches transport or
        # daemon deaths the sleep detector cannot see.
        stall = _data_progression_check()
        if stall is not None:
            incidents_today += 1
            _incident("data_progression_stalled", stall)

        beat = {"kind": "host_heartbeat", "at": _now_iso(),
                "epoch": wall, "monotonic": mono,
                "on_ac": power.get("on_ac"),
                "battery_pct": power.get("battery_pct"),
                "disk_free_gb": round(disk, 2), "network_ok": net,
                "tz": time.strftime("%Z"),
                "sleep_incidents_since_start": incidents_today,
                "decision_power": "NONE"}
        try:
            HEARTBEAT.parent.mkdir(parents=True, exist_ok=True)
            HEARTBEAT.write_text(json.dumps(beat, indent=1))
        except OSError:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
