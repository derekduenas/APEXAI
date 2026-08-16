#!/bin/zsh
# Crypto shadow arena wrapper: public feed, no secrets, zero capital.
set -euo pipefail
REPO="$HOME/apex-equities"
cd "$REPO"
exec >> "$REPO/logs/crypto_arena.log" 2>&1
.venv/bin/python scripts/crypto_arena.py
