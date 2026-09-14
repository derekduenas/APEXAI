#!/bin/zsh
# NOT RUN BY THE AUDIT. Review, then run deliberately.
set -euo pipefail
D="$(cd "$(dirname "$0")" && pwd)"
cp "$D/com.apex.premarket.plist.NEW" "$HOME/Library/LaunchAgents/com.apex.premarket.plist"
cp "$D/premarket.sh.NEW" "$HOME/apex-equities/ops/premarket.sh"
chmod +x "$HOME/apex-equities/ops/premarket.sh"
launchctl bootout "gui/$(id -u)/com.apex.premarket" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.apex.premarket.plist"
echo "installed; verify with ./status.sh"
