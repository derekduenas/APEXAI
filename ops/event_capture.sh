#!/bin/zsh
# Event-capture wrapper: no secrets needed (public SEC feed).
set -euo pipefail
REPO="$HOME/apex-equities"
cd "$REPO"
exec >> "$REPO/logs/event_capture.log" 2>&1
.venv/bin/python scripts/event_capture.py
