#!/bin/zsh
# BITNOMIAL WS trades+book daemon (BTC-L2). caffeinate -i keeps the box
# awake while running but CANNOT prevent clamshell sleep (Friday law).
set -euo pipefail
REPO="$HOME/apex-equities"
cd "$REPO"
exec >> "$REPO/logs/btc_ws.log" 2>&1
exec /usr/bin/caffeinate -i .venv/bin/python scripts/btc_ws_stream.py --minutes 10080
