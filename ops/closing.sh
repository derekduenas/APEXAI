#!/bin/zsh
set -euo pipefail
export PATH="$HOME/.local/bin:/usr/local/bin:/opt/homebrew/bin:$PATH"
export DISABLE_AUTOUPDATER=1
REPO="$HOME/apex-equities"
EODHD_API_TOKEN="$(security find-generic-password -a apex -s EODHD_API_TOKEN -w)"
export EODHD_API_TOKEN
cd "$REPO"
exec >> "$REPO/logs/closing.log" 2>&1
.venv/bin/python scripts/closing_run.py
