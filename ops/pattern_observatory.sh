#!/bin/zsh
# PATTERN OBSERVATORY SHADOW RUNTIME -- job class OBSERVATIONAL_SIDECAR.
#
# THE THURSDAY FIREWALL. This runs in parallel with the official natural
# acceptance session and must never affect it. It is a separate launchd
# job, writes only under results/pattern_observatory/, imports none of
# the production decision stack, and if it dies the official services do
# not notice.
#
# It starts at 06:35 PT (09:35 ET) -- AFTER the bell and after the
# Alpaca sensor, so its first observation is a real regular-session
# cross-section rather than a premarket one. It needs no credentials:
# every input is an artifact another service already persisted.
set -uo pipefail
export PATH="$HOME/.local/bin:/usr/local/bin:/opt/homebrew/bin:$PATH"
export DISABLE_AUTOUPDATER=1
REPO="$HOME/apex-equities"
cd "$REPO"
exec >> "$REPO/logs/pattern_observatory.log" 2>&1

BUDGET="$(.venv/bin/python scripts/sidecar_gate.py --job options-analytics)" || {
  echo "$(date -u +%FT%TZ) observatory: upstream sensor not healthy; not starting"
  exit 0
}
echo "$(date -u +%FT%TZ) PATTERN_OBSERVATORY shadow runtime, budget=${BUDGET}m"
.venv/bin/python scripts/pattern_observatory_shadow_runtime.py \
    --minutes "$BUDGET" --cadence 60
