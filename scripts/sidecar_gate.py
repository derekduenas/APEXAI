#!/usr/bin/env python
"""SIDECAR ADMISSION GATE -- decides whether an OBSERVATIONAL_SIDECAR or
POST_CLOSE_ANALYTICS job may start, and how long it may run.

WHY THIS EXISTS. Two facts about the 2026-08-18 session made an
unattended sidecar unsafe to just cron and forget:

  1. A sidecar that starts before its upstream sensor is healthy
     produces a full session of REFUSED/UNKNOWN states that look like
     evidence but are only evidence of its own start time.
  2. A post-close analytics job that runs before the close artifacts
     exist writes a forensics report about a session it never saw.

So the gate is a PRECONDITION CHECK, not a delay. It answers one
question -- "is the input this job needs actually present right now?" --
and it answers it DURABLY: every admission and every refusal is
appended to results/governance/sidecar_gate.jsonl. A sidecar that never
ran leaves a record saying why, instead of an empty output directory
that reads identically to "ran and found nothing".

THE ISOLATION LAW. This gate can only ever REFUSE a sidecar. It has no
path to CORE: it does not import apex.hunter, apex.captain,
apex.execution, apex.frontier, or apex.frontier2, it writes only under
results/governance/, and a nonzero exit here stops exactly one launchd
job. A sidecar that refuses to start cannot degrade the decision system,
because the decision system never reads a sidecar's output.

USAGE (from a launchd wrapper):
    BUDGET=$(python scripts/sidecar_gate.py --job options-analytics) || exit 0
    python scripts/option_analytics_live_runtime.py --minutes "$BUDGET" ...

On admission it prints the run budget in minutes to stdout and exits 0.
On refusal it prints nothing to stdout, prints the cause to stderr, and
exits nonzero -- so `|| exit 0` in the wrapper turns a refusal into a
clean, recorded no-op rather than a launchd crash loop.

decision_power: NONE_OBSERVABILITY.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_S = Path(__file__).resolve().parent
sys.path.insert(0, str(_S.parent))

import pandas as pd  # noqa: E402

GATE_LEDGER = Path("results/governance/sidecar_gate.jsonl")
ALPACA_HEALTH = Path("results/intraday/alpaca_fabric_health.json")

# A sidecar reading a health artifact older than this is reading about a
# sensor that may already be dead. 10 min is generous relative to the
# fabric's own 45s STALE_AFTER_S -- the gate is not a health monitor,
# it only refuses the obviously-absent case.
HEALTH_MAX_AGE_S = 600.0

# Alpaca fabric states that mean "real market data is arriving". PARTIAL
# counts: partial symbol coverage is a legitimate observation subject,
# and the sidecar stamps coverage on every state it writes anyway.
ADMITTING_HEALTH = ("HEALTHY", "PARTIAL")

# Options analytics observes the REGULAR session only -- an options
# sidecar in premarket would sample a book that is not open.
OPTIONS_SESSION_END_ET = (16, 0)
OPTIONS_MIN_BUDGET_MIN = 5.0

JOBS = ("options-analytics", "daily-forensics")


def _append(rec: dict) -> None:
    try:
        GATE_LEDGER.parent.mkdir(parents=True, exist_ok=True)
        with GATE_LEDGER.open("a") as fh:
            fh.write(json.dumps(rec, default=str) + "\n")
    except Exception as e:                                  # noqa: BLE001
        try:
            from apex.governance.ledger_error import record
            record(service="sidecar_gate", operation="LEDGER_WRITE", exc=e,
                   ledger="sidecar_gate.jsonl",
                   recovery_action="gate decision still returned to caller")
        except Exception:                                   # noqa: BLE001
            pass


def _decide(job: str, now: pd.Timestamp) -> dict:
    et = now.tz_convert("America/New_York")
    base = {"kind": "sidecar_gate_decision", "job": job, "as_of": str(now),
            "as_of_et": str(et), "decision_power": "NONE_OBSERVABILITY"}

    if job == "options-analytics":
        # --- precondition 1: the underlying sensor is actually alive ---
        if not ALPACA_HEALTH.exists():
            return {**base, "admitted": False,
                    "cause": "UPSTREAM_HEALTH_ARTIFACT_ABSENT",
                    "detail": str(ALPACA_HEALTH)}
        try:
            h = json.loads(ALPACA_HEALTH.read_text())
        except Exception as e:                              # noqa: BLE001
            return {**base, "admitted": False,
                    "cause": "UPSTREAM_HEALTH_ARTIFACT_UNREADABLE",
                    "detail": f"{type(e).__name__}: {e}"}
        age_s = now.timestamp() - ALPACA_HEALTH.stat().st_mtime
        status = h.get("status")
        if age_s > HEALTH_MAX_AGE_S:
            return {**base, "admitted": False,
                    "cause": "UPSTREAM_HEALTH_STALE",
                    "upstream_status": status,
                    "health_age_s": round(age_s, 1)}
        if status not in ADMITTING_HEALTH:
            return {**base, "admitted": False,
                    "cause": "UPSTREAM_NOT_HEALTHY",
                    "upstream_status": status,
                    "health_age_s": round(age_s, 1)}

        # --- precondition 2: there is session left to observe ---
        end = et.replace(hour=OPTIONS_SESSION_END_ET[0],
                         minute=OPTIONS_SESSION_END_ET[1],
                         second=0, microsecond=0)
        budget_min = (end - et).total_seconds() / 60.0
        if budget_min < OPTIONS_MIN_BUDGET_MIN:
            return {**base, "admitted": False,
                    "cause": "NO_REGULAR_SESSION_REMAINING",
                    "minutes_to_close": round(budget_min, 1)}
        return {**base, "admitted": True, "budget_minutes": round(budget_min, 1),
                "upstream_status": status, "health_age_s": round(age_s, 1),
                "terminates_at_et": str(end)}

    if job == "daily-forensics":
        # POST_CLOSE_ANALYTICS reads a finished session. Requiring the
        # close artifacts by name is the difference between forensics
        # and fiction.
        date = str(et.date())
        required = {
            "canonical_daily_memory": Path(f"results/frontier/daily_memory/{date}.json"),
        }
        missing = {k: str(p) for k, p in required.items() if not p.exists()}
        if missing:
            return {**base, "admitted": False,
                    "cause": "CLOSE_ARTIFACTS_ABSENT", "session_date": date,
                    "missing": missing}
        return {**base, "admitted": True, "session_date": date,
                "budget_minutes": None,
                "close_artifacts_present": {k: str(p) for k, p in required.items()}}

    return {**base, "admitted": False, "cause": "UNKNOWN_JOB"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", required=True, choices=JOBS)
    ap.add_argument("--now", default=None, help="ISO override, testing only")
    a = ap.parse_args()

    now = (pd.Timestamp(a.now) if a.now else pd.Timestamp.now(tz="UTC"))
    if now.tz is None:
        now = now.tz_localize("UTC")
    rec = _decide(a.job, now)
    _append(rec)

    if not rec.get("admitted"):
        print(f"SIDECAR_GATE REFUSED job={a.job} cause={rec.get('cause')} "
              f"detail={rec.get('detail') or rec.get('missing') or ''}",
              file=sys.stderr)
        return 3
    if rec.get("budget_minutes") is not None:
        print(f"{rec['budget_minutes']:.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
