#!/bin/zsh
# SessionAnchorEvidence arming wrapper. Must run AT the open so the
# anchor facts are captured before 400-bar rolling retention erases
# them (the 2026-08-18 failure mode).
set -euo pipefail
export PATH="$HOME/.local/bin:/usr/local/bin:/opt/homebrew/bin:$PATH"
export DISABLE_AUTOUPDATER=1
REPO="$HOME/apex-equities"
cd "$REPO"
exec >> "$REPO/logs/session_anchor.log" 2>&1
.venv/bin/python scripts/arm_session_anchor_evidence.py --minutes 45 --cadence 60
