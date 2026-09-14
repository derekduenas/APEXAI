#!/usr/bin/env python
"""STAGED PREMARKET PRODUCER -- the production entry point. One bounded invocation per stage, no sleeping.

WHY THIS REPLACED THE LOOP IN premarket_run.py. That runner started once and slept through every refresh to the
09:25 ET seal, so an interruption lost the whole morning. Worse, its wait was `time.sleep(min(wait, 3600))` with
no re-check of the target, so a process that started sufficiently early returned from the sleep an hour later and
absorbed immediately -- hours before the stage whose label it was writing. Reproduced on a controlled early-start
fixture: a 02:00 ET start fires the 08:15 absorption at 03:00 ET. (Whether launchd actually produces such an
early start on this host is a separate question, and only the disposable operating-system test can answer it.)

Here each stage is its own process. It claims its own identity, writes its record before anything can fail, takes
a durable lock, verifies its predecessors' hash chain, and REFUSES to run outside its window rather than running
early under a correct-looking label. State survives between processes in an append-only journal, so the finalizer
rebuilds the morning from evidence instead of from a variable that only existed inside one long-lived process.

    python scripts/premarket_stage.py --stage 0815_ET_initial
    python scripts/premarket_stage.py --stage seal
    python scripts/premarket_stage.py --stage reconcile
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_S = Path(__file__).resolve().parent
sys.path.insert(0, str(_S.parent)); sys.path.insert(0, str(_S))

from apex.frontier import premarket_stages as PS  # noqa: E402

STAGES = PS.STAGES
WINDOW_S = PS.WINDOW_S


def et_now():
    from apex.frontier import premarket_runtime as RT
    return RT.now_et()


def target_for(stage, now_et):
    return PS.target_for(stage, now_et)


def disposition(stage, now_et):
    return PS.disposition(stage, now_et)


EXIT = {"COMPLETED": 0, "TOO_EARLY": 0, "MISSED_WINDOW": 0, "RECONCILED_DUPLICATE": 0,
        "REFUSED_INPUT": 0, "SOURCE_UNAVAILABLE": 3, "FAILED": 4}


def main() -> int:
    from apex.frontier import premarket_journal as PJ
    from apex.frontier import premarket_runtime as RT
    from apex.frontier import run_record as RR

    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", required=True, choices=sorted(STAGES) + ["reconcile", "verify"])
    ap.add_argument("--dry-run", action="store_true",
                    help="exercise startup accounting, stage claiming and window logic without providers")
    a = ap.parse_args()

    now = et_now()
    day = str(now.date())
    journal = PJ.open_journal(day)
    subs = RT.substitutions()
    if subs:
        print("SUBSTITUTIONS ACTIVE (this run is NOT fully real): %s" % sorted(subs))

    if a.stage == "verify":
        print(journal.verify())
        return 0
    if a.stage == "reconcile":
        return reconcile(day, now, journal, RR)

    # session-opening record, written once per trading date
    if not journal.events():
        journal.append(stage="session", state="STARTED", trading_date=day, opened_at_et=str(now),
                       schedule={n: "%02d:%02d ET" % (h, m) for n, h, m in PS.STAGE_SCHEDULE},
                       code_identity=code_identity(), realism=RT.realism())

    # A run record is per INVOCATION. Exactly-once absorption is enforced by the journal's O_EXCL claim, not by
    # this filename -- conflating the two made a crashed stage permanently unresumable, which the failure
    # flights caught before this was ever scheduled.
    run_id = RR.next_run_id(day, a.stage)
    try:
        rec = RR.RunRecord(run_id=run_id, scheduled_epoch=target_for(a.stage, now).timestamp(),
                           code_identity=code_identity())
    except FileExistsError:
        journal.append(stage=a.stage, state="RECONCILED_DUPLICATE",
                       note="two invocations raced for run id %s; nothing was absorbed again" % run_id)
        print("RACED stage=%s day=%s run_id=%s" % (a.stage, day, run_id))
        return 0

    lock = RR.RunLock()
    try:
        held = lock.acquire(run_id)
        if held.get("took_over_from"):
            journal.append(stage=a.stage, state="STARTED", lock_takeover=held["took_over_from"],
                           note="the previous lock holder's process no longer exists; recovering")
            print("LOCK_TAKEOVER stage=%s from dead pid %s"
                  % (a.stage, held["took_over_from"].get("pid")))
    except RR.LockHeld as e:
        rec.stage("STARTED", "LOCKED", why=str(e)[:200]); rec.fail("STARTED", str(e)[:200])
        journal.append(stage=a.stage, state="RECONCILED_DUPLICATE", reason="LOCK_HELD", detail=str(e)[:200])
        print("LOCKED stage=%s: %s" % (a.stage, e))
        return 0
    try:
        if a.dry_run:
            disp, delta = disposition(a.stage, now)
            rec.stage("STARTED", disp, target_et=str(target_for(a.stage, now)), actual_et=str(now),
                      delta_s=round(delta, 1))
            journal.append(stage=a.stage, state="STARTED", disposition=disp, delta_s=round(delta, 1),
                           dry_run=True)
            terminal = disp if disp in ("TOO_EARLY", "MISSED_WINDOW") else "REFUSED_INPUT"
            journal.append(stage=a.stage, state=terminal, dry_run=True,
                           note="dry run: window logic and claiming exercised; no provider was called")
            rec.stage("SOURCES", "SKIPPED_DRY_RUN"); rec.finish(exit_status="DRY_RUN_%s" % disp)
            print("stage=%s disposition=%s delta=%.0fs (dry run)" % (a.stage, disp, delta))
            return 0

        if a.stage == "seal":
            out = PS.finalize(journal=journal, now_et=now)
        else:
            out = PS.run_stage(a.stage, journal=journal, now_et=now)

        state = out["state"]
        rec.stage("SOURCES", state)
        rec.finish(output_identity=out.get("packet_sha256") or out.get("packet_blob"), exit_status=state)
        return EXIT.get(state, 0)
    finally:
        lock.release()


def code_identity() -> dict:
    """What code produced this morning. Recorded per run so a packet can be tied to an executable."""
    import hashlib
    import subprocess
    files = ["scripts/premarket_stage.py", "apex/frontier/premarket_stages.py",
             "apex/frontier/premarket_journal.py", "apex/frontier/premarket_runtime.py",
             "apex/frontier/premarket.py", "apex/frontier/run_record.py"]
    h = hashlib.sha256()
    per = {}
    for f in files:
        p = Path(f)
        b = p.read_bytes() if p.exists() else b""
        d = hashlib.sha256(b).hexdigest()
        per[f] = d[:16]
        h.update(f.encode()); h.update(d.encode())
    try:
        sha = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                             timeout=10).stdout.strip() or "UNAVAILABLE"
    except Exception:                                                   # noqa: BLE001
        sha = "UNAVAILABLE"
    return {"producer_digest": h.hexdigest(), "files": per, "git_head": sha}


def reconcile(day, now, journal, RR) -> int:
    """Compare the expected stages with the durable record. Never backdates, never fetches retrospective data."""
    from apex.frontier import premarket_journal as PJ
    try:
        chain = journal.verify()
    except PJ.ChainBroken as e:
        print("RECONCILE REFUSED: %s" % e)
        journal_state = {"chain": "BROKEN", "detail": str(e)[:300]}
        journal.append(stage="reconcile", state="FAILED", **journal_state)
        return 4
    missing = []
    for stage, _h, _m in PS.STAGE_SCHEDULE:
        st = journal.stage_state(stage)
        if st in ("PENDING",):
            disp, delta = disposition(stage, now)
            missing.append((stage, disp, delta))
    print("reconcile %s: chain=%s events=%d; %d stage(s) without a record"
          % (day, chain["verdict"], chain["events"], len(missing)))
    for stage, disp, delta in missing:
        state = "MISSED_WINDOW" if disp in ("MISSED_WINDOW", "LATE_START", "ON_TIME") else disp
        journal.append(stage=stage, state=state, observed_at_et=str(now), delta_s=round(delta, 1),
                       reconciled=True,
                       note="reconciliation: no retrospective data was fetched for a stage that never ran")
        rid = "%s_%s_reconciled" % (day, stage)
        try:
            r = RR.RunRecord(run_id=rid, scheduled_epoch=target_for(stage, now).timestamp())
        except FileExistsError:
            continue
        r.stage("STARTED", state, observed_at_et=str(now), delta_s=round(delta, 1),
                note="reconciliation: no retrospective data was fetched for a missed window")
        r.finish(exit_status=state)
        print("   %-20s %s (delta %.0fs)" % (stage, state, delta))
    return 0


if __name__ == "__main__":
    sys.exit(main())
