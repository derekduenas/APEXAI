#!/usr/bin/env python
"""FINAL SCHEDULER / TIMEZONE CERTIFICATION.

Every Monday job, one table, machine-derived from the LOADED plists and
the code's own time math — never from report prose. Exits nonzero on any
incoherence. launchd StartCalendarInterval fires in HOST LOCAL time, so
the host being US/Pacific is itself an asserted precondition.
"""
from __future__ import annotations

import glob
import plistlib
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pandas as pd  # noqa: E402

FAIL = []


def check(name, ok, detail):
    print(f"{'PASS' if ok else 'FAIL':<6}{name:<38}{detail}")
    if not ok:
        FAIL.append(name)


def main() -> int:
    # 0. the anchor identities, computed not asserted
    open_et = pd.Timestamp("2026-08-17 09:30", tz="America/New_York")
    close_et = pd.Timestamp("2026-08-17 16:00", tz="America/New_York")
    check("REGULAR_OPEN 09:30 ET == 06:30 PT",
          str(open_et.tz_convert("America/Los_Angeles"))[11:16] == "06:30",
          f"{open_et} == {open_et.tz_convert('America/Los_Angeles')}")
    check("REGULAR_CLOSE 16:00 ET == 13:00 PT",
          str(close_et.tz_convert("America/Los_Angeles"))[11:16] == "13:00",
          f"{close_et} == {close_et.tz_convert('America/Los_Angeles')}")

    # 1. host timezone: plists fire in host-local, so this is load-bearing
    host_tz = time.strftime("%Z")
    check("host timezone is Pacific", host_tz in ("PDT", "PST"),
          f"host={host_tz} (launchd calendar times are host-local)")

    # 2. every loaded com.apex job: local schedule -> ET meaning
    rows = []
    for p in sorted(glob.glob(str(Path("ops") / "com.apex.*.plist"))):
        d = plistlib.loads(Path(p).read_bytes())
        label = d["Label"]
        loaded = label in subprocess.run(
            ["launchctl", "list"], capture_output=True, text=True).stdout
        cal = d.get("StartCalendarInterval")
        interval = d.get("StartInterval")
        keep = d.get("KeepAlive")
        if cal:
            first = cal[0] if isinstance(cal, list) else cal
            h, m = first.get("Hour"), first.get("Minute", 0)
            pt = pd.Timestamp(f"2026-08-17 {h:02d}:{m:02d}",
                              tz="America/Los_Angeles")
            et = pt.tz_convert("America/New_York")
            sched = f"{h:02d}:{m:02d} PT = {str(et)[11:16]} ET"
        elif interval:
            sched = f"every {interval}s (self-gated on session)"
        elif keep:
            sched = "KeepAlive resident"
        else:
            sched = "RunAtLoad/other"
        rows.append((label, loaded, sched))
        print(f"  {label:<28}{'LOADED' if loaded else 'NOT_LOADED':<12}"
              f"{sched}")

    expect = {  # label -> required PT firing time
        "com.apex.premarket": "05:14", "com.apex.preopen-gate": "06:20",
        "com.apex.fastwatch": "06:27", "com.apex.sensory-loop": "06:28",
        "com.apex.closing": "12:00"}
    for label, want_pt in expect.items():
        row = next((r for r in rows if r[0] == label), None)
        ok = row is not None and row[1] and want_pt in row[2]
        check(f"{label} fires {want_pt} PT", ok,
              row[2] if row else "MISSING")

    # the operator's named P0: a closing job firing at 15:00/16:02 PT
    # (i.e. hours after the close). Assert on the PT FIRING HOUR itself —
    # the first draft substring-matched "15:0" and hit the ET translation
    # of a CORRECT 12:00 PT schedule: the checker's own tz-prose bug.
    closing = next((r for r in rows if r[0] == "com.apex.closing"), None)
    check("closing job fires before 13:00 PT",
          closing is not None and closing[2].startswith("12:00 PT"),
          closing[2] if closing else "MISSING")

    # 3. in-code market-time math is ET-anchored (the runners)
    for f, token in (("scripts/closing_run.py", '"1500_ET", 15, 0'),
                     ("scripts/closing_run.py", '("close_capture", 16, 2)'),
                     ("scripts/premarket_run.py", '("0920_ET_final", 9, 20)')):
        src = open(f).read()
        check(f"{f.split('/')[-1]} anchors {token[:18]}..", token in src
              and 'tz="America/New_York"' in src, "ET-labeled schedule")

    # 4. DST awareness: the same wall times in January differ from UTC by
    # a different offset — computed, not assumed
    aug = pd.Timestamp("2026-08-17 09:30", tz="America/New_York")
    jan = pd.Timestamp("2026-01-16 09:30", tz="America/New_York")
    check("DST-aware ET anchor", aug.utcoffset() != jan.utcoffset(),
          f"Aug offset {aug.utcoffset()} vs Jan {jan.utcoffset()}")

    # 5. naive-datetime refusal at the seals and PIT gates
    import pytest  # noqa: F401
    from apex.events.catalyst import catalyst_state
    try:
        catalyst_state("X", "2026-08-17 14:00")
        naive_ok = False
    except ValueError:
        naive_ok = True
    check("catalyst refuses naive datetimes", naive_ok, "raises ValueError")
    from apex.hunter.birth import forward_eligibility
    try:
        forward_eligibility(pd.Timestamp("2026-08-17 14:00"), {})
        birth_ok = False
    except ValueError:
        birth_ok = True
    check("birth law refuses naive datetimes", birth_ok, "raises ValueError")

    # 6. the Monday timeline, PT + ET, one authority
    print("\nMONDAY 2026-08-17 TIMELINE (PT | ET)")
    for pt_s, what in (("05:14", "premarket wake (refreshes 05:15/05:32/"
                        "06:05/06:20, SEAL 06:25)"),
                       ("06:20", "preopen gate"),
                       ("06:27", "FastWatch warm"),
                       ("06:28", "frontier loop warm (2m cadence, "
                        "re-underwriting heartbeats 60-900s)"),
                       ("06:30", "REGULAR OPEN — Epoch-1 first tick "
                        "(900s cadence, session-gated)"),
                       ("12:00", "final-hour watcher (checkpoints "
                        "12:00/12:30/12:50/12:58 PT)"),
                       ("13:00", "REGULAR CLOSE"),
                       ("13:02", "close capture -> seal -> brief -> "
                        "card outcomes -> daily memory")):
        pt = pd.Timestamp(f"2026-08-17 {pt_s}", tz="America/Los_Angeles")
        print(f"  {pt_s} PT | {str(pt.tz_convert('America/New_York'))[11:16]}"
              f" ET  {what}")

    print(f"\n{'CERTIFIED' if not FAIL else 'FAILED: ' + str(FAIL)}")
    return 0 if not FAIL else 1


if __name__ == "__main__":
    raise SystemExit(main())
