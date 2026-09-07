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
from apex.ops.host_qualification import qualify_host           # noqa: E402
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


# --------------------------------------------------------------- R2
# ORCHESTRATOR-OOM-001-R2: bounded incident history.
#
# MAX_RECOVERY_ATTEMPTS guarded only the branch that STARTS a service.
# The branch for externally supervised services appended one entry per
# tick with no cap, and state["attempts"] is cleared only on a phase
# change. Over a weekend in phase IDLE that produced 1907 identical
# entries for one service, and the whole list is re-serialised into
# EVERY ledger record, so records grew 135 bytes per tick until one
# exceeded the chain primitive's tail window.
#
# A deferral is an OBSERVATION -- "still missing, and its supervisor
# owns the restart" -- not an attempt. Its information content is a
# count and a duration, not N copies of one sentence. It is now kept as
# a summary plus a bounded sample, and it is held SEPARATELY from real
# recovery attempts so that repeated observations can neither consume
# nor bypass the recovery allowance.
MAX_DEFERRAL_DETAIL = 3


def _service_state(state: dict, name: str, supervised_by: str) -> dict:
    """Per-service incident state: real attempts and deferrals, apart."""
    return state["attempts"].setdefault(name, {
        "recovery": [],
        "deferrals": {"count": 0, "first_utc": None, "last_utc": None,
                      "recent": [], "supervised_by": supervised_by}})


def _record_deferral(st: dict, *, service: str, at: str,
                     supervised_by: str) -> None:
    """Count it, timestamp it, and keep a BOUNDED sample: the first
    observation and the most recent ones. The first says when the
    service went missing; the last say it is still missing now."""
    d = st["deferrals"]
    d["count"] += 1
    d["last_utc"] = at
    if d["first_utc"] is None:
        d["first_utc"] = at
    d["supervised_by"] = supervised_by
    d["recent"].append({"service": service, "attempted_utc": at,
                        "outcome": "DEFERRED_TO_SUPERVISOR",
                        "detail": supervised_by})
    if len(d["recent"]) > MAX_DEFERRAL_DETAIL:
        # keep index 0 and the last MAX_DEFERRAL_DETAIL - 1
        del d["recent"][1:len(d["recent"]) - MAX_DEFERRAL_DETAIL + 1]


def _attempt_history(st: dict, service: str) -> list:
    """What rides with the alarm. Bounded by construction:
    at most MAX_RECOVERY_ATTEMPTS real attempts, then at most one
    summary, then at most MAX_DEFERRAL_DETAIL sampled deferrals.

    RECORD FORMAT CHANGE. Before R2 a supervised service contributed one
    entry per tick here. It now contributes a `deferral_summary` entry
    carrying the total, the first and last observation times, and how
    many detailed entries were kept -- followed by those entries. A
    reader that took len(recovery_attempts) as the number of deferrals
    will now UNDER-COUNT and must read `count` from the summary. Records
    written before this change keep their old shape and stay readable;
    nothing rewrites them.
    """
    history = list(st["recovery"])
    d = st["deferrals"]
    if d["count"]:
        history.append({"kind": "deferral_summary", "service": service,
                        "outcome": "DEFERRED_TO_SUPERVISOR",
                        "detail": d["supervised_by"],
                        "count": d["count"],
                        "first_utc": d["first_utc"],
                        "last_utc": d["last_utc"],
                        "detail_entries_retained": len(d["recent"]),
                        "note": "observations, not recovery attempts; the "
                                "supervisor owns the restart"})
        history.extend(d["recent"])
    return history


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

    # HOST QUALIFICATION gates the equity commissioning day on the
    # Mac only: a battery/network-degraded host produces a number
    # nobody can interpret, and burns a prospective session doing it.
    # The gate follows the FABRIC, not a particular machine: equity
    # now runs on DigitalOcean, so qualifying the Mac would check a
    # host that no longer carries a market day.
    runs_equity = any(sp.name == "equity-fabric" for sp in specs)
    host_q = None
    if runs_equity and phase in ("PREOPEN", "SESSION_ARMED", "RTH"):
        host_q = qualify_host(
            fabric_ready=(observed.get("equity-fabric", False)
                          and first_work_seen("equity-fabric")))

    actions, incidents = [], []
    for s in specs:
        exp = s.expected_lifecycle(phase)
        if exp != "EXPECTED_RUNNING":
            continue
        if observed[s.name] and first_work_seen(s.name):
            continue
        st = _service_state(state, s.name, s.supervised_by)
        if (not observed[s.name] and not s.externally_supervised
                and len(st["recovery"]) < MAX_RECOVERY_ATTEMPTS):
            att = (StartAttempt(service=s.name,
                                attempted_utc=t.isoformat(),
                                outcome="DRY_RUN", detail="--dry-run")
                   if dry_run else start(s.name, s))
            st["recovery"].append(att.__dict__)
            actions.append(att.__dict__)
        elif not observed[s.name] and s.externally_supervised:
            # the supervisor owns the restart; we own noticing that it
            # is not working, and saying so loudly. R2: an OBSERVATION,
            # recorded in bounded form and never counted as an attempt.
            _record_deferral(st, service=s.name, at=t.isoformat(),
                             supervised_by=s.supervised_by)
        v = missed_start_verdict(
            service=s.name, phase=phase, expected_lifecycle=exp,
            first_work_seen=first_work_seen(s.name),
            seconds_since_phase_start=elapsed,
            deadline_s=s.first_work_deadline_s,
            recovery_attempts=_attempt_history(st, s.name),
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
           "host_qualification": ({"verdict": host_q["verdict"],
                                   "blocking": host_q["blocking"]}
                                  if host_q else None),
           "decision_power": "NONE_OPERATIONAL"}
    if (actions or incidents or rec["verdict"] != "OK"
            or (host_q and host_q["verdict"] == "SAFE_BLOCKED")):
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
              f"incidents={len(r['incidents'])} "
              f"host={(r.get('host_qualification') or {}).get('verdict')}")
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
