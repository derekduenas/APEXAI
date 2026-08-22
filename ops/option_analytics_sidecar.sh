#!/bin/zsh
# APEX_OPTION_ANALYTICS_LIVE_RUNTIME -- job class OBSERVATIONAL_SIDECAR.
#
# Reads OPRA quotes, computes APEX's own IV/Greeks, writes ONLY under
# results/option_analytics/. Nothing in CORE reads its output, and it
# cannot block CORE: it is a separate launchd job whose failure is
# invisible to Hunter, Captain, Capital and Execution.
#
# The gate below is the honesty condition. It refuses to start when the
# Alpaca sensor is not healthy (a session of REFUSED states would be
# evidence about our own start time, not about the market), and it sizes
# the run budget from the actual wall clock so the process terminates
# cleanly AT the 16:00 ET close rather than on a hardcoded duration.
set -uo pipefail
export PATH="$HOME/.local/bin:/usr/local/bin:/opt/homebrew/bin:$PATH"
export DISABLE_AUTOUPDATER=1
REPO="$HOME/apex-equities"
cd "$REPO"
exec >> "$REPO/logs/option_analytics_sidecar.log" 2>&1

APCA_API_KEY_ID="$(security find-generic-password -a apex -s ALPACA_API_KEY_ID -w)"
APCA_API_SECRET_KEY="$(security find-generic-password -a apex -s ALPACA_API_SECRET_KEY -w)"
export APCA_API_KEY_ID APCA_API_SECRET_KEY

BUDGET="$(.venv/bin/python scripts/sidecar_gate.py --job options-analytics)" || {
  echo "$(date -u +%FT%TZ) sidecar refused to start (recorded in results/governance/sidecar_gate.jsonl)"
  exit 0
}
echo "$(date -u +%FT%TZ) OPTION_ANALYTICS sidecar admitted, budget=${BUDGET}m"
.venv/bin/python scripts/option_analytics_live_runtime.py --minutes "$BUDGET" --cadence 60
