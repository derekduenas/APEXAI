"""APEX_OPTION_ANALYTICS_V1 — the package's own append-only birth
chain, minted once. Structurally separate from
apex.options_research.birth's ledger (a different decision_power, a
different package, and this one carries the certification's
source_hash at mint time as an audit trail)."""
from __future__ import annotations

from pathlib import Path

from apex.option_analytics import OPTION_ANALYTICS_POWER
from apex.option_analytics.validation_registry import source_hash

LEDGER = Path("results/option_analytics/birth.jsonl")
VERSION = "APEX_OPTION_ANALYTICS_V1"


def mint(*, now, code_lineage: str = (
        "apex/option_analytics/* built 2026-08-18 -- BSM, American binomial, "
        "no-arbitrage gates, rate curve, dividends, time-to-expiry, model "
        "disagreement, IV_BID/MID/ASK triple, canonical state, surface "
        "physics")) -> dict:
    import sys
    sys.path.insert(0, "scripts")
    from nightly_pull import _chain_append
    import pandas as pd
    now = pd.Timestamp(now)
    entry = {
        "kind": "apex_option_analytics_birth",
        "version": VERSION, "birth_time": str(now), "code_lineage": code_lineage,
        "source_hash_at_birth": source_hash(),
        "decision_power": OPTION_ANALYTICS_POWER,
        "capital_authority": "NONE", "broker_authority": "NONE",
    }
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    return _chain_append(LEDGER, entry)


def already_minted() -> bool:
    return LEDGER.exists() and bool(LEDGER.read_text().strip())
