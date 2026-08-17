#!/bin/zsh
# Forward-clock wrapper: token from Keychain, never on disk or in args.
set -euo pipefail
export DISABLE_AUTOUPDATER=1   # SAC-2: no runtime drift mid-session
REPO="$HOME/apex-equities"
EODHD_API_TOKEN="$(security find-generic-password -a apex -s EODHD_API_TOKEN -w)"
export EODHD_API_TOKEN
cd "$REPO"
exec >> "$REPO/logs/hunter_clock.log" 2>&1
.venv/bin/python scripts/hunter_forward_clock.py
