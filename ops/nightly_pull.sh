#!/bin/zsh
# Nightly Sharadar pull wrapper -- launchd entry point.
#
# THE KEY NEVER TOUCHES DISK. It lives in the macOS Keychain and is exported
# into the environment of this process only. Install it once, by hand:
#
#   security add-generic-password -a apex -s NASDAQ_DATA_LINK_API_KEY -w
#
# (the trailing -w with no value prompts silently; the key never enters shell
# history). This wrapper must never echo the key or pass it as an argument.
set -euo pipefail

REPO="$HOME/apex-equities"
LOG_DIR="$REPO/logs"
mkdir -p "$LOG_DIR"

NASDAQ_DATA_LINK_API_KEY="$(security find-generic-password -a apex -s NASDAQ_DATA_LINK_API_KEY -w)"
export NASDAQ_DATA_LINK_API_KEY

cd "$REPO"
exec >> "$LOG_DIR/nightly_pull.log" 2>&1
echo "=== $(date -u +%Y-%m-%dT%H:%M:%SZ) nightly pull ==="
.venv/bin/python scripts/nightly_pull.py --run
echo "=== $(date -u +%Y-%m-%dT%H:%M:%SZ) paper track ==="
.venv/bin/python scripts/paper_track.py
