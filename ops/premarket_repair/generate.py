#!/usr/bin/env python
"""Generate the prepared production artifacts FROM the schedule, so they cannot drift from it.

The stage times are ET. launchd's StartCalendarInterval is LOCAL time. This host is America/Los_Angeles, and US
Eastern and US Pacific change to and from daylight time on the SAME dates, so the offset is a constant three
hours -- which this script verifies at a winter and a summer instant rather than assuming. If the host is ever
moved to a zone that does not track Eastern, these plists become wrong, and `status.sh` checks for exactly that.

    python ops/premarket_repair/generate.py          # write the .NEW artifacts
    python ops/premarket_repair/generate.py --check  # exit 1 if any file differs from what the schedule implies
"""
from __future__ import annotations

import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
REPO_AT_RUNTIME = "/Users/derekduenas/apex-equities"
SCHEDULER_TZ = "America/Los_Angeles"
RECONCILE_ET = (9, 40)

PLIST = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.apex.premarket.{stage}</string>
  <!-- ONE AGENT PER STAGE. The single long-lived agent was the defect: one process started once and slept
       through the whole morning, so an early start ran every stage hours early under the right-looking label,
       and any interruption lost the morning. Each stage is now its own bounded process with its own trigger and
       its own explicit stage argument -- nothing is inferred from the clock. -->
  <key>ProgramArguments</key>
  <array><string>/bin/zsh</string><string>{repo}/ops/premarket.sh</string><string>{stage}</string></array>
  <!-- Without these, ANY failure before the script's own log redirect was invisible. That is the surface that
       made a 19-day gap silent. -->
  <key>StandardOutPath</key><string>{repo}/logs/premarket.{stage}.launchd.out</string>
  <key>StandardErrorPath</key><string>{repo}/logs/premarket.{stage}.launchd.err</string>
  <key>StartCalendarInterval</key>
  <array>
{intervals}
  </array>
</dict></plist>
"""

INTERVAL = ('    <dict><key>Weekday</key><integer>{d}</integer>'
            '<key>Hour</key><integer>{h}</integer><key>Minute</key><integer>{m}</integer></dict>')

SHELL = """#!/bin/zsh
# THE STAGED PRODUCTION WRAPPER. Invoked once per stage by its own LaunchAgent, with the stage as $1.
#
# Two properties this file is responsible for, both about making failure VISIBLE:
#   1. the log redirect happens FIRST. It used to be after the keychain read, so any failure in the secret
#      lookup exited under `set -euo pipefail` with no log line at all.
#   2. the secret read is checked explicitly and reports a named reason instead of a bare non-zero exit.
#
# It exports none of the APEX_PREMARKET_* runtime-substitution variables. A production morning is fully real by
# construction, and `premarket_runtime.substitutions()` records that in every event.
set -uo pipefail
STAGE="${1:?FAILED stage=ARGS reason=no stage argument; expected one of: %(stages)s}"
REPO="$HOME/apex-equities"
mkdir -p "$REPO/logs"
exec >> "$REPO/logs/premarket.log" 2>&1
echo "=== premarket stage=$STAGE start $(date -u +%%Y-%%m-%%dT%%H:%%M:%%SZ) pid=$$ ==="
export PATH="$HOME/.local/bin:/usr/local/bin:/opt/homebrew/bin:$PATH"
export DISABLE_AUTOUPDATER=1
if ! EODHD_API_TOKEN="$(security find-generic-password -a apex -s EODHD_API_TOKEN -w 2>&1)"; then
  echo "FAILED stage=SECRET reason=keychain read failed: $EODHD_API_TOKEN"
  exit 11
fi
export EODHD_API_TOKEN
cd "$REPO" || { echo "FAILED stage=CHDIR reason=$REPO missing"; exit 12; }
.venv/bin/python scripts/premarket_stage.py --stage "$STAGE"
rc=$?
echo "=== premarket stage=$STAGE end rc=$rc $(date -u +%%Y-%%m-%%dT%%H:%%M:%%SZ) ==="
exit $rc
"""


def et_to_local(h, m):
    """Convert an ET wall time to the scheduler's local wall time, and PROVE the offset is stable."""
    import pandas as pd
    for probe in ("2026-01-15", "2026-07-15"):
        a = pd.Timestamp("%s %02d:%02d" % (probe, h, m), tz="America/New_York")
        b = a.tz_convert(SCHEDULER_TZ)
        if (a.hour - b.hour) % 24 != 3:
            raise SystemExit("SCHEDULER_TZ_OFFSET_NOT_CONSTANT at %s: ET %02d:%02d -> %s %02d:%02d"
                             % (probe, h, m, SCHEDULER_TZ, b.hour, b.minute))
    ref = pd.Timestamp("2026-07-15 %02d:%02d" % (h, m), tz="America/New_York").tz_convert(SCHEDULER_TZ)
    return ref.hour, ref.minute


def artifacts() -> dict:
    from apex.frontier import premarket_stages as PS
    schedule = list(PS.STAGE_SCHEDULE) + [("reconcile", RECONCILE_ET[0], RECONCILE_ET[1])]
    out = {}
    for stage, h, m in schedule:
        lh, lm = et_to_local(h, m)
        intervals = "\n".join(INTERVAL.format(d=d, h=lh, m=lm) for d in range(1, 6))
        out["com.apex.premarket.%s.plist.NEW" % stage] = PLIST.format(
            stage=stage, repo=REPO_AT_RUNTIME, intervals=intervals)
    out["premarket.sh.NEW"] = SHELL % {"stages": " ".join(s for s, _h, _m in schedule)}
    return out


def main() -> int:
    check = "--check" in sys.argv
    sys.path.insert(0, str(HERE.parents[1]))
    bad = []
    for name, body in artifacts().items():
        p = HERE / name
        if check:
            if not p.exists() or p.read_text() != body:
                bad.append(name)
        else:
            p.write_text(body)
    if check:
        print("DRIFT: %s" % bad if bad else "all prepared artifacts match the schedule")
        return 1 if bad else 0
    print("wrote %d artifacts" % len(artifacts()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
