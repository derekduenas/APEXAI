#!/bin/zsh
set -euo pipefail
export PATH="$HOME/.local/bin:/usr/local/bin:/opt/homebrew/bin:$PATH"
export DISABLE_AUTOUPDATER=1
REPO="$HOME/apex-equities"
cd "$REPO"
export APCA_API_KEY_ID="$(security find-generic-password -a apex -s ALPACA_API_KEY_ID -w)"
export APCA_API_SECRET_KEY="$(security find-generic-password -a apex -s ALPACA_API_SECRET_KEY -w)"
exec >> "$REPO/logs/alpaca_fabric.log" 2>&1
# 660 min from 05:14 PT (08:14 ET premarket) covers premarket + the full
# 09:30-16:00 ET regular session + ~3h past close (19:14 ET) for the
# bounded reconnect rehearsal (directive §10) -- 400 min undershot close
# by over an hour and was never armed against the true schedule.
# LAYER 0 (commissioning, 2026-08-21): caffeinate -i prevents IDLE
# sleep while the sensor runs. It CANNOT prevent clamshell (lid-close)
# sleep -- that killed 26% of Friday's tape and only the operator can
# prevent it (lid open + AC, `sudo pmset disablesleep 1`, or a real
# server). The host sentinel detects and records any sleep regardless.
/usr/bin/caffeinate -i .venv/bin/python scripts/alpaca_fabric_daemon.py --minutes 660
