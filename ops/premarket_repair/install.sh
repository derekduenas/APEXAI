#!/bin/zsh
# NOT RUN BY THE AUDIT. Review, then run deliberately.
#
# Installs ONE LaunchAgent PER STAGE and boots out the single long-lived agent they replace. The old agent must
# go: leaving it loaded would have one process sleeping through the morning alongside five that do not, and both
# would write the same packet.
set -euo pipefail
D="$(cd "$(dirname "$0")" && pwd)"
STAGES=(0815_ET_initial 0832_ET_post_macro 0905_ET_refresh 0920_ET_final seal reconcile)

cp "$D/premarket.sh.NEW" "$HOME/apex-equities/ops/premarket.sh"
chmod +x "$HOME/apex-equities/ops/premarket.sh"
# The timezone the local triggers were generated for. The runner refuses if the live host no longer matches.
cp "$D/timezone_binding.json" "$HOME/apex-equities/ops/timezone_binding.json"

launchctl bootout "gui/$(id -u)/com.apex.premarket" 2>/dev/null || true
rm -f "$HOME/Library/LaunchAgents/com.apex.premarket.plist"

for s in $STAGES; do
  cp "$D/com.apex.premarket.$s.plist.NEW" "$HOME/Library/LaunchAgents/com.apex.premarket.$s.plist"
  launchctl bootout "gui/$(id -u)/com.apex.premarket.$s" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.apex.premarket.$s.plist"
  echo "installed com.apex.premarket.$s"
done
echo "installed; verify with ./status.sh"
