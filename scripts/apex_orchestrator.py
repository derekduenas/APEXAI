"""APEX SESSION ORCHESTRATOR DAEMON — always on, so APEX shows up.

Runs continuously. Every tick it asks the exchange calendar what phase
we are in, reconciles what SHOULD be running against what IS, starts
what is missing, verifies FIRST WORK rather than mere liveness, and
escalates SESSION_MISSED_START if a required service never produces a
unit of work.

It never places an order and never touches a trading rule. Its only
opinion is whether the machine turned up for work.

Run with --once for a single reconciliation tick (used by health
checks and by the launchd bootstrap), or bare for the always-on loop.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apex.governance.chain_ledger import chain_append          # noqa: E402
from apex.ops import heartbeat as hb                           # noqa: E402
from apex.ops.orchestrator import (StartAttempt, default_roster,  # noqa: E402
                                   missed_start_verdict, phase_at,
                                   reconcile_expected)


def detect_host() -> str:
    """Which machine am I? Declared by env, else inferred from the
    immutable release root that only the cloud host has."""
    env = os.environ.get("APEX_HOST")
    if env:
        return env
    return "cloud" if Path("/opt/apex/current").exists() else "mac"

TICK_S = 60
LEDGER = Path("results/ops/orchestrator.jsonl")
MAX_RECOVERY_ATTEMPTS = 3


def now() -> datetime:
    return datetime.now(timezone.utc)


def session_of(t: datetime) -> str:
    """The ET calendar date, which is the session's identity.

    Using the UTC date would call 01:00 UTC Wednesday a Wednesday
    session when ET still says Tuesday evening -- and the orchestrator
    would arm the wrong day.
    """
    from zoneinfo import ZoneInfo
    return f"{t.astimezone(ZoneInfo('America/New_York')):%Y-%m-%d}"


def process_running(name: str) -> bool:
    """Observed liveness only. Never confused with working."""
    pats = {
        "equity-fabric": "alpaca_fabric",
        "options-paper": "options_paper_session",
        "edgeforge-observatory": "edgeforge_observatory",
        "btc-paper": "btc_paper_session",
    }
    pat = pats.get(name, name)
    try:
        out = subprocess.run(["pgrep", "-f", pat],
                             capture_output=True, text=True, timeout=10)
        return out.returncode == 0 and bool(out.stdout.strip())
    except Exception:                                    # noqa: BLE001
        return False


def first_work_seen(name: str) -> bool:
    """Work, not presence. Reads the service's own heartbeat."""
    r = hb.read(name)
    return bool(r and (r.get("work_completed") or 0) > 0)


def start(name: str, spec) -> StartAttempt:
    if not spec.start_cmd:
        return StartAttempt(service=name,
                            attempted_utc=now().isoformat(),
                            outcome="FAILED",
                            detail="no start_cmd declared; this "
                                   "service cannot be auto-started "
                                   "yet and must be wired")
    try:
        subprocess.Popen(list(spec.start_cmd),
                         stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL,
                         start_new_session=True)
        return StartAttempt(service=name,
                            attempted_utc=now().isoformat(),
                            outcome="STARTED",
                            detail=" ".join(spec.start_cmd))
    except Exception as e:                               # noqa: BLE001
        return StartAttempt(service=name,
                            attempted_utc=now().isoformat(),
                            outcome="FAILED", detail=repr(e))


def tick(state: dict, *, dry_run: bool) -> dict:
    t = now()
    session = session_of(t)
    ph = phase_at(t, session)
    phase = ph["phase"]
    specs = default_roster(state["host"])
    observed = {s.name: process_running(s.name) for s in specs}
    rec = reconcile_expected(phase=phase, specs=specs,
                             observed_running=observed)

    if state.get("phase") != phase:
        state["phase"] = phase
        state["phase_started"] = time.time()
        state["attempts"] = {}
    elapsed = time.time() - state.get("phase_started", time.time())

    actions, incidents = [], []
    for s in specs:
        exp = s.expected_lifecycle(phase)
        if exp != "EXPECTED_RUNNING":
            continue
        if observed[s.name] and first_work_seen(s.name):
            continue
        tries = state["attempts"].setdefault(s.name, [])
        if (not observed[s.name] and not s.externally_supervised
                and len(tries) < MAX_RECOVERY_ATTEMPTS):
            att = (StartAttempt(service=s.name,
                                attempted_utc=t.isoformat(),
                                outcome="DRY_RUN", detail="--dry-run")
                   if dry_run else start(s.name, s))
            tries.append(att.__dict__)
            actions.append(att.__dict__)
        elif not observed[s.name] and s.externally_supervised:
            # the supervisor owns the restart; we own noticing that it
            # is not working, and saying so loudly
            tries.append({"service": s.name,
                          "attempted_utc": t.isoformat(),
                          "outcome": "DEFERRED_TO_SUPERVISOR",
                          "detail": s.supervised_by})
        v = missed_start_verdict(
            service=s.name, phase=phase, expected_lifecycle=exp,
            first_work_seen=first_work_seen(s.name),
            seconds_since_phase_start=elapsed,
            deadline_s=s.first_work_deadline_s,
            recovery_attempts=tries,
            dependency_states={d: ("RUNNING" if observed.get(d)
                                   else "MISSING")
                               for d in s.dependencies},
            release=os.environ.get("APEX_RELEASE", "UNKNOWN"))
        if v["verdict"] == "SESSION_MISSED_START":
            incidents.append(v)

    out = {"kind": "orchestrator_tick", "at": t.isoformat(),
           "host": state["host"],
           "session": session, "phase": phase, "why": ph["why"],
           "trading_day": ph.get("trading_day"),
           "half_day": ph.get("half_day"),
           "observed": observed,
           "reconciliation": {"verdict": rec["verdict"],
                              "missing": rec["missing"],
                              "unexpectedly_running":
                                  rec["unexpectedly_running"]},
           "actions": actions, "incidents": incidents,
           "decision_power": "NONE_OPERATIONAL"}
    if actions or incidents or rec["verdict"] != "OK":
        LEDGER.parent.mkdir(parents=True, exist_ok=True)
        chain_append(LEDGER, out)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    state: dict = {"attempts": {}, "host": detect_host()}
    beat = hb.Heartbeat(service="orchestrator")
    if a.once:
        r = tick(state, dry_run=a.dry_run)
        print(json.dumps(r, indent=1, default=str) if a.json else
              f"{r['host']:6} {r['phase']:14} "
              f"{r['reconciliation']['verdict']:9} "
              f"missing={r['reconciliation']['missing']} "
              f"incidents={len(r['incidents'])}")
        return 0 if not r["incidents"] else 3
    while True:
        try:
            r = tick(state, dry_run=a.dry_run)
            beat.work(f"tick {r['phase']}")
        except Exception as e:                           # noqa: BLE001
            beat.error(repr(e))
        time.sleep(TICK_S)


if __name__ == "__main__":
    raise SystemExit(main())
