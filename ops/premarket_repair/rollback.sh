#!/bin/zsh
# Restores the EXACT prior bytes captured at audit time.
set -euo pipefail
D="$(cd "$(dirname "$0")" && pwd)"
cp "$D/com.apex.premarket.plist.PRIOR" "$HOME/Library/LaunchAgents/com.apex.premarket.plist"
cp "$D/premarket.sh.PRIOR" "$HOME/apex-equities/ops/premarket.sh"
chmod +x "$HOME/apex-equities/ops/premarket.sh"
launchctl bootout "gui/$(id -u)/com.apex.premarket" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.apex.premarket.plist"
echo "rolled back to the prior state"
