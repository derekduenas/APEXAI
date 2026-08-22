#!/bin/zsh
set -euo pipefail
export PATH="$HOME/.local/bin:/usr/local/bin:/opt/homebrew/bin:$PATH"
export DISABLE_AUTOUPDATER=1
REPO="$HOME/apex-equities"
cd "$REPO"
export EODHD_API_TOKEN="$(security find-generic-password -a apex -s EODHD_API_TOKEN -w)"
exec >> "$REPO/logs/equity_fabric.log" 2>&1
.venv/bin/python scripts/equity_fabric_daemon.py --minutes 400
