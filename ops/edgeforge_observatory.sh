#!/bin/zsh
# EDGEFORGE OBSERVATORY — always-on research sidecar.
cd /Users/derekduenas/apex-equities || exit 1
exec .venv/bin/python -u scripts/edgeforge_observatory.py --follow
