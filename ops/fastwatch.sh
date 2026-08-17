#!/bin/zsh
# FastWatch wrapper: token from Keychain, never on disk or in args.
set -euo pipefail
export DISABLE_AUTOUPDATER=1   # SAC-2: no runtime drift mid-session
REPO="$HOME/apex-equities"
EODHD_API_TOKEN="$(security find-generic-password -a apex -s EODHD_API_TOKEN -w)"
export EODHD_API_TOKEN
cd "$REPO"
exec >> "$REPO/logs/fastwatch.log" 2>&1
.venv/bin/python scripts/fastwatch.py --minutes 395 --cadence 60
