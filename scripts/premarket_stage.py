#!/usr/bin/env python
"""STAGED PREMARKET PRODUCER — one bounded invocation per stage. No sleeping between stages.

WHY THIS REPLACES THE LOOP IN premarket_run.py. That runner started once at 05:14 PT and slept through every
refresh to the 09:25 ET seal, so an interruption lost the whole morning. Worse, its wait was
`time.sleep(min(wait, 3600))` with no re-check, so a process that started well before the first target -- exactly
what a COALESCED WAKE produces, which is launchd's documented behaviour after sleep -- ran every stage hours
early while still labelling them `0815_ET_initial` and friends. Reproduced: a 02:00 ET start fires the 08:15
absorption at 03:00 ET.

Here each stage is its own invocation, claims its own identity, records its start before anything can fail, and
REFUSES to run outside its window rather than running early and labelling it correctly.

    python scripts/premarket_stage.py --stage 0815_ET_initial
    python scripts/premarket_stage.py --stage seal
    python scripts/premarket_stage.py --stage reconcile
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_S = Path(__file__).resolve().parent
sys.path.insert(0, str(_S.parent)); sys.path.insert(0, str(_S))

STAGES = {"0815_ET_initial": (8, 15), "0832_ET_post_macro": (8, 32),
          "0905_ET_refresh": (9, 5), "0920_ET_final": (9, 20), "seal": (9, 25)}
WINDOW_S = 600.0          # a stage may start up to 10 minutes late; beyond that it is MISSED_WINDOW


def et_now():
    import pandas as pd
    return pd.Timestamp.now(tz="America/New_York")


def target_for(stage, now_et):
    h, m = STAGES[stage]
    return now_et.normalize() + __import__("pandas").Timedelta(hours=h, minutes=m)


def disposition(stage, now_et):
    """ON_TIME / LATE_START / TOO_EARLY / MISSED_WINDOW -- decided, never slept through."""
    t = target_for(stage, now_et)
    delta = (now_et - t).total_seconds()
    if delta < -60.0:
        return "TOO_EARLY", delta
    if delta <= WINDOW_S:
        return ("ON_TIME" if abs(delta) <= 60.0 else "LATE_START"), delta
    return "MISSED_WINDOW", delta


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", required=True, choices=sorted(STAGES) + ["reconcile"])
    ap.add_argument("--dry-run", action="store_true",
                    help="exercise startup accounting, stage claiming and finalisation without providers")
    a = ap.parse_args()
    from apex.frontier import run_record as RR

    now = et_now()
    day = str(now.date())
    if a.stage == "reconcile":
        return reconcile(day, now, RR)

    run_id = "%s_%s" % (day, a.stage)
    try:
        rec = RR.RunRecord(run_id=run_id, scheduled_epoch=target_for(a.stage, now).timestamp())
    except FileExistsError:
        print("DUPLICATE stage=%s day=%s -- a record already exists; not overwritten" % (a.stage, day))
        return 0
    lock = RR.RunLock()
    try:
        lock.acquire(run_id)
    except RR.LockHeld as e:
        rec.stage("STARTED", "LOCKED", why=str(e)[:200]); rec.fail("STARTED", str(e)[:200])
        print("LOCKED stage=%s: %s" % (a.stage, e))
        return 0
    try:
        disp, delta = disposition(a.stage, now)
        rec.stage("STARTED", disp, target_et=str(target_for(a.stage, now)), actual_et=str(now),
                  delta_s=round(delta, 1))
        print("stage=%s disposition=%s delta=%.0fs" % (a.stage, disp, delta))
        if disp in ("TOO_EARLY", "MISSED_WINDOW"):
            rec.finish(exit_status=disp)
            return 0
        if a.dry_run:
            rec.stage("SOURCES", "SKIPPED_DRY_RUN"); rec.finish(exit_status="DRY_RUN_OK")
            print("dry run: startup accounting and stage claiming exercised; no provider called")
            return 0
        rec.stage("SOURCES", "NOT_IMPLEMENTED_IN_THIS_BRICK")
        rec.finish(exit_status="STAGED_SHELL_ONLY")
        return 0
    finally:
        lock.release()


def reconcile(day, now, RR) -> int:
    """Compare expected stages with durable records. Never backdates, never fetches retrospective data."""
    RR.RUNS.mkdir(parents=True, exist_ok=True)
    missing = []
    for stage in sorted(STAGES):
        if not (RR.RUNS / ("%s_%s.json" % (day, stage))).exists():
            disp, delta = disposition(stage, now)
            missing.append((stage, disp, delta))
    print("reconcile %s: %d stage(s) without a record" % (day, len(missing)))
    for stage, disp, delta in missing:
        rid = "%s_%s_reconciled" % (day, stage)
        try:
            r = RR.RunRecord(run_id=rid, scheduled_epoch=target_for(stage, now).timestamp())
        except FileExistsError:
            continue
        state = "LATE_START" if disp == "LATE_START" else "MISSED_WINDOW" if disp == "MISSED_WINDOW" else disp
        r.stage("STARTED", state, observed_at_et=str(now), delta_s=round(delta, 1),
                note="reconciliation: no retrospective data was fetched for a missed window")
        r.finish(exit_status=state)
        print("   %-20s %s (delta %.0fs)" % (stage, state, delta))
    return 0


if __name__ == "__main__":
    sys.exit(main())
