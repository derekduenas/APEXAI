#!/bin/zsh
set -euo pipefail
REPO="$HOME/apex-equities"
cd "$REPO"
exec >> "$REPO/logs/btc_derivatives.log" 2>&1
exec /usr/bin/caffeinate -i .venv/bin/python scripts/btc_derivatives_poller.py --minutes 10080
