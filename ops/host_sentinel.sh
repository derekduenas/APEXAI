#!/bin/zsh
set -euo pipefail
REPO="$HOME/apex-equities"
cd "$REPO"
exec >> "$REPO/logs/host_sentinel.log" 2>&1
# deliberately NOT caffeinated: the sentinel's job is to DETECT sleep,
# and it must never be the thing keeping the box awake.
exec .venv/bin/python scripts/host_sentinel.py
