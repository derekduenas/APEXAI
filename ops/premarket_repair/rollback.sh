#!/bin/zsh
# Restores the EXACT prior bytes captured at audit time, and removes every per-stage agent this repair added.
set -euo pipefail
D="$(cd "$(dirname "$0")" && pwd)"
STAGES=(0815_ET_initial 0832_ET_post_macro 0905_ET_refresh 0920_ET_final seal reconcile)
for s in $STAGES; do
  launchctl bootout "gui/$(id -u)/com.apex.premarket.$s" 2>/dev/null || true
  rm -f "$HOME/Library/LaunchAgents/com.apex.premarket.$s.plist"
done
rm -f "$HOME/apex-equities/ops/timezone_binding.json"
cp "$D/com.apex.premarket.plist.PRIOR" "$HOME/Library/LaunchAgents/com.apex.premarket.plist"
cp "$D/premarket.sh.PRIOR" "$HOME/apex-equities/ops/premarket.sh"
chmod +x "$HOME/apex-equities/ops/premarket.sh"
launchctl bootout "gui/$(id -u)/com.apex.premarket" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.apex.premarket.plist"
echo "rolled back to the prior state"
