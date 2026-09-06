"""PULSE-007 -- an unrelated LIVE incident found while attributing an OOM.

NOT part of the anchor repair. Recorded because it was discovered and must
not be lost, and NOT acted on: this brick may not change services.

WHAT HAPPENED. The first attempt at this brick's regression ran the whole
suite in one contained process. It was OOM-killed inside wmresearch.slice at
about 52% -- contained exactly as intended, slice oom_kill 4 -> 5, and the
work was re-run as one fresh contained process per test module instead. The
slice ceiling was NOT raised.

While attributing that kill I checked whether anything outside the research
slice had also died, and found that apex-orchestrator.service is in a
permanent OOM crash-loop that long predates this brick.

decision_power: NONE_REPORTING.
"""
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

OUT = "/opt/apex-repo/results/pulse007_orchestrator_incident.json"


def sh(cmd):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout.strip()


def main():
    per_hour = sh("sudo -n journalctl -u apex-orchestrator.service --since '-7 days' -o short-iso "
                  "2>/dev/null | grep -E 'oom-kill' | awk '{print $1}' | cut -c1-13 | sort | uniq -c "
                  "| tail -24")
    by_unit = sh("sudo -n journalctl --since '-7 days' 2>/dev/null | grep -oE 'oom_memcg=[^ ,]+' "
                 "| sort | uniq -c | sort -rn | head -8")
    show = sh("systemctl show apex-orchestrator.service -p NRestarts -p MemoryMax -p ActiveState "
              "-p SubState -p Slice -p ExecMainStartTimestamp")
    slice_ev = sh("cat /sys/fs/cgroup/wmresearch.slice/memory.events | tr '\\n' ' '")
    doc = {
        "kind": "pulse007_incidental_finding",
        "id": "ORCHESTRATOR-OOM-LOOP-001",
        "found_while": "attributing the OOM kill of this brick's own first regression attempt",
        "status": "REPORTED, NOT ACTED ON -- this brick may not change services",
        "utc": datetime.now(timezone.utc).isoformat(),

        "finding": "apex-orchestrator.service is OOM-killed at its own 512M cgroup limit roughly "
                   "every 31 seconds and restarted, continuously, for at least seven days. "
                   "systemctl reports it 'active/running' between kills, so a liveness check "
                   "that samples the unit state sees a healthy service.",
        "constraint": "CONSTRAINT_MEMCG on /apex.slice/apex-market.slice/apex-orchestrator.service "
                      "-- the service exceeds its OWN limit. This is not global host pressure and "
                      "is not caused by research load.",
        "not_caused_by_this_brick": {
            "evidence": "the kill rate is ~114/hour for every hour of every day in the window, "
                        "including hours before this brick began at 14:43Z",
            "this_bricks_own_kill": "one kill inside wmresearch.slice (the first regression "
                                    "attempt), contained by design; slice oom_kill 4 -> 5"},
        "why_it_matters": "the orchestrator is the always-on calendar-aware trigger and WORK "
                          "VERIFIER. A verifier that dies every 31 seconds cannot verify, and "
                          "the standing law is that heartbeats must measure WORK, not presence. "
                          "Any Phase-2 commissioning window scheduled through it is unreliable "
                          "until this is understood.",
        "kills_per_hour_last_24h": per_hour,
        "oom_kills_by_cgroup_last_7d": by_unit,
        "unit_state": show,
        "wmresearch_slice_memory_events": slice_ev,
        "recommended_disposition": "a separate bounded brick: measure the orchestrator's working "
                                   "set before proposing any limit, per RESOURCE_PROFILE_V1 -- a "
                                   "current MemoryPeak after a restart is not evidence of "
                                   "required capacity. Do not raise the cap on a guess.",
    }
    json.dump(doc, open(OUT, "w"), indent=1)
    print("ORCHESTRATOR-OOM-LOOP-001 recorded ->", OUT)
    print(per_hour)
    print(by_unit)


if __name__ == "__main__":
    main()
