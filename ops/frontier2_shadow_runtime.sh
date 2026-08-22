#!/bin/zsh
set -euo pipefail
export PATH="$HOME/.local/bin:/usr/local/bin:/opt/homebrew/bin:$PATH"
export DISABLE_AUTOUPDATER=1
REPO="$HOME/apex-equities"
cd "$REPO"
exec >> "$REPO/logs/frontier2_shadow_runtime.log" 2>&1
# 450 min from 06:00 PT (09:00 ET) covers a PREMARKET start through the
# 16:00 ET close plus 30 min. On 2026-08-18 this runtime was started by
# hand at 09:43 ET -- 13 minutes AFTER the open -- so no Frontier-2
# observation existed for the opening transition. A premarket start is
# the fix; 390 min from 09:00 ET would have ended at 15:30 ET, before
# the close.
.venv/bin/python scripts/frontier2_shadow_runtime.py --minutes 450 --cadence 20
