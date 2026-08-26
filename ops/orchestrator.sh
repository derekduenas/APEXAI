#!/bin/zsh
# APEX SESSION ORCHESTRATOR — always-on supervisor.
cd /Users/derekduenas/apex-equities || exit 1
exec .venv/bin/python -u scripts/apex_orchestrator.py
