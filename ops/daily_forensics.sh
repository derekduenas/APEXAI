#!/bin/zsh
# DAILY_FORENSICS_V2 -- job class POST_CLOSE_ANALYTICS.
#
# Read-only reconstruction of a FINISHED session. Runs after the closing
# job's artifacts exist (com.apex.closing starts 12:00 PT, internally
# waits for the 16:00 ET close, then sleeps 600s for 90m-horizon card
# outcomes -- so its artifacts land ~13:10-13:15 PT). This job is
# scheduled at 13:45 PT with a named-artifact precondition, so it cannot
# write forensics about a session whose close never completed.
set -uo pipefail
export PATH="$HOME/.local/bin:/usr/local/bin:/opt/homebrew/bin:$PATH"
export DISABLE_AUTOUPDATER=1
REPO="$HOME/apex-equities"
cd "$REPO"
exec >> "$REPO/logs/daily_forensics.log" 2>&1

.venv/bin/python scripts/sidecar_gate.py --job daily-forensics || {
  echo "$(date -u +%FT%TZ) forensics refused (recorded in results/governance/sidecar_gate.jsonl)"
  exit 0
}
.venv/bin/python scripts/daily_forensics_v2.py

# The acceptance board is evaluated from the same finished session, with
# no manual checkboxes -- it is the last post-close task, so there are no
# manual post-close tasks.
.venv/bin/python scripts/natural_acceptance_observer.py
