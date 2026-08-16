#!/bin/zsh
# Crypto arena daemon: resident WebSocket fabric + arena + shadow mgmt.
# Public feed, no secrets, zero capital. KeepAlive restarts on crash.
set -euo pipefail
REPO="$HOME/apex-equities"
cd "$REPO"
exec >> "$REPO/logs/crypto_daemon.log" 2>&1
.venv/bin/python scripts/crypto_daemon.py
