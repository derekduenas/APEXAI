"""APEX HEALTH — is what should be running actually running, and working?

Answers the question nobody asked for seven hours on 2026-08-23.

Exit codes are meant for a timer or a watchdog:
    0  everything healthy (including services idle by design)
    1  degraded -- something is late but present
    2  the release itself cannot be accounted for
    3  critical -- something expected is gone, looping, or running
       when it should not be
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apex.ops import heartbeat as hb                      # noqa: E402
from apex.ops import release as rel                       # noqa: E402

# Per-service thresholds. Declared, not global: "slow" means something
# different for a 15-minute scanner than for a bulk downloader.
SERVICES = {
    "options-acquire": {"beat_stale_s": 900, "work_stale_s": 3600},
    "options-paper": {"beat_stale_s": 1800, "work_stale_s": None},
    "btc-stream": {"beat_stale_s": 300, "work_stale_s": 900},
}

# EXPECTED LIFECYCLE, declared per service via
#   APEX_SERVICE_LIFECYCLE="options-acquire=EXPECTED_ON_DEMAND,..."
#
# THE DEFAULT IS DELIBERATELY STRICT. Anything not declared is assumed
# EXPECTED_RUNNING, so a service nobody thought about can still alarm.
# The two failure directions are not symmetric: a false alarm at
# midnight is annoying, while a session daemon dying at 10:09 and
# reporting EXPECTED_IDLE is the seven-hour silence all of this exists
# to prevent. Silence is the expensive error, so absence of a
# declaration buys noise, never quiet.
DEFAULT_LIFECYCLE = "EXPECTED_RUNNING"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--heartbeat-dir", default=None)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--service", action="append", default=None)
    a = ap.parse_args()
    # EACH HOST DECLARES WHAT IT SHOULD BE RUNNING. Reporting
    # NEVER_STARTED for a service that legitimately lives on another
    # machine is a false alarm, and false alarms train an operator to
    # ignore the alarm -- the same way a buffered empty log trained us
    # to ignore a dead daemon.
    # SET-BUT-EMPTY is not the same intention as UNSET. An empty list
    # means "this host should be running nothing right now" (between
    # sessions, with acquisition deliberately disabled); an absent
    # variable means "no declaration, fall back to the roster". Treating
    # them alike made a quiet host report its finished session as DEAD.
    expected = os.environ.get("APEX_EXPECTED_SERVICES")
    root = Path(a.heartbeat_dir) if a.heartbeat_dir else None

    relrep = rel.verify_running_release()
    if a.service:
        names = a.service
    elif expected is not None:
        names = [n.strip() for n in expected.split(",") if n.strip()]
    else:
        names = list(SERVICES)
    lifecycles = {}
    for item in (os.environ.get("APEX_SERVICE_LIFECYCLE") or "").split(","):
        if "=" in item:
            k, _, v = item.partition("=")
            lifecycles[k.strip()] = v.strip()
    reports = [hb.health(n, root=root,
                         expected_lifecycle=lifecycles.get(
                             n, DEFAULT_LIFECYCLE),
                         **SERVICES.get(n, {"beat_stale_s": 900}))
               for n in names]
    summary = hb.summarize(reports)
    if not names:
        summary["note"] = ("no services are expected on this host right "
                           "now; a quiet host is not an unhealthy one")
    out = {"release": relrep, "health": summary, "detail": reports}

    if a.json:
        print(json.dumps(out, indent=1, default=str))
    else:
        print(f"release: {relrep['verdict']}"
              f"{' -- ' + '; '.join(relrep['findings']) if relrep.get('findings') else ''}")
        for r in reports:
            print(f"  {r['service']:20} {r['state']:18} "
                  f"[{r.get('severity', '?')}] {r['why']}")
        print(f"verdict: {summary['verdict']}")

    if relrep["verdict"] not in ("RELEASE_HEALTHY",):
        return 2
    # 0 healthy · 1 degraded · 3 critical. A watchdog that cannot tell
    # "a scanner is late" from "the daemon is gone" pages the same way
    # for both, and then stops being read.
    return {"ALL_HEALTHY": 0, "DEGRADED": 1, "CRITICAL": 3}.get(
        summary["verdict"], 1)


if __name__ == "__main__":
    raise SystemExit(main())
