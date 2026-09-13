#!/bin/bash
# EXACT RECONSTRUCTION of apex-pilot-stage1-2026-09-14 as it stood at 2026-09-13T16:54:50Z,
# captured before FEE-AUTHORIZATION-002 held it.
#
# WHY A SCRIPT AND NOT `systemctl enable`: the unit was TRANSIENT
# (/run/user/1000/systemd/transient/). A transient unit has no on-disk definition, so stopping it
# DESTROYS it -- there is nothing to re-enable. It would also not have survived a reboot.
# This script is therefore the only preservation of the prior configuration.
#
# It restores the OLD RELEASE a6e123d, which carries the known-defective risk/accounting and V1 exit
# behaviour. Run it only to deliberately return to that state.
set -euo pipefail
systemd-run --user \
  --unit=apex-pilot-stage1-2026-09-14 \
  --on-calendar='2026-09-14 13:24:00 UTC' \
  --timer-property=AccuracySec=1s \
  --timer-property=RemainAfterElapse=no \
  --property=MemoryMax=1468006400 \
  --working-directory=/opt/apex/current \
  --setenv=APEX_PILOT_LIVE_DATA=ENABLED \
  --setenv=PYTHONUNBUFFERED=1 \
  /opt/apex/shared/venv/bin/python /opt/apex/current/scripts/options_paper_session.py \
    --pilot-boundary --pilot-live-wiring --pilot-selection-policy PILOT_RULE_V2 \
    --symbols SPY --minutes 390 --interval-min 15 \
    --ledger /apex-data/core/options_pilot_ledger.jsonl \
    --out /apex-data/history-a/pilot_2026-09-14.json \
    --pilot-session-id PILOT-2026-09-14 \
    --pilot-release a6e123d36a89ac70ca512243336eb1561a9b9cd3
