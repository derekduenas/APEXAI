"""APEX HEALTH — is what should be running actually running, and working?

Answers the question nobody asked for seven hours on 2026-08-23.

Exit codes are meant for a timer or a watchdog:
    0  everything healthy
    1  something needs attention
    2  the release itself cannot be accounted for
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
    expected = os.environ.get("APEX_EXPECTED_SERVICES")
    root = Path(a.heartbeat_dir) if a.heartbeat_dir else None

    relrep = rel.verify_running_release()
    names = (a.service
             or ([n.strip() for n in expected.split(",") if n.strip()]
                 if expected else list(SERVICES)))
    reports = [hb.health(n, root=root,
                         **SERVICES.get(n, {"beat_stale_s": 900}))
               for n in names]
    summary = hb.summarize(reports)
    out = {"release": relrep, "health": summary, "detail": reports}

    if a.json:
        print(json.dumps(out, indent=1, default=str))
    else:
        print(f"release: {relrep['verdict']}"
              f"{' -- ' + '; '.join(relrep['findings']) if relrep.get('findings') else ''}")
        for r in reports:
            print(f"  {r['service']:20} {r['state']:14} {r['why']}")
        print(f"verdict: {summary['verdict']}")

    if relrep["verdict"] not in ("RELEASE_HEALTHY",):
        return 2
    return 0 if summary["verdict"] == "ALL_HEALTHY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
