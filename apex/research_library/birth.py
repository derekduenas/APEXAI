"""APEX_RESEARCH_LIBRARY_V1 — the library's own append-only birth
chain, minted once, read many times."""
from __future__ import annotations

from pathlib import Path

from apex.research_library import RESEARCH_LIBRARY_POWER

LEDGER = Path("results/research_library/library_birth.jsonl")
LIBRARY_VERSION = "APEX_RESEARCH_LIBRARY_V1"
SCHEMA_VERSION = "research_library_schema_v1"


def mint(*, now, code_lineage: str = (
        "apex/research_library/* built 2026-08-18 -- documents.py, "
        "mechanisms.py, hypotheses.py, retrieval.py, programs.py")) -> dict:
    import sys
    sys.path.insert(0, "scripts")
    from nightly_pull import _chain_append
    import pandas as pd
    now = pd.Timestamp(now)
    entry = {
        "kind": "apex_research_library_birth",
        "library_version": LIBRARY_VERSION, "schema": SCHEMA_VERSION,
        "birth_time": str(now), "code_lineage": code_lineage,
        "decision_power": RESEARCH_LIBRARY_POWER,
        "capital_authority": "NONE", "broker_authority": "NONE",
    }
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    return _chain_append(LEDGER, entry)


def already_minted() -> bool:
    return LEDGER.exists() and bool(LEDGER.read_text().strip())
