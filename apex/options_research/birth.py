"""Options Research V1 — five separate birth chains, minted once each,
sharing one hash-chained ledger distinguished by `birth_version`. Every
birth is stamped decision_power=NONE_OPTIONS_RESEARCH /
capital_authority=NONE / broker_authority=NONE, and none of them
retroactively validate anything -- a birth records that a component
came into existence at this instant, nothing about its track record.
"""
from __future__ import annotations

from pathlib import Path

from apex.options_research import OPTIONS_RESEARCH_POWER

LEDGER = Path("results/options_research/options_research_births.jsonl")

BIRTH_VERSIONS = (
    "APEX_OPTIONS_RESEARCH_V1",
    "OPTION_MARKET_SCHEMA_V1",
    "OPTION_SURFACE_SCHEMA_V1",
    "OPTION_EXECUTION_MODEL_V1",
    "OPTION_EXPRESSION_ENGINE_V1",
    "ASYMMETRIC_GROWTH_DOCTRINE_V1",
)

DEFAULT_LINEAGE = {
    "APEX_OPTIONS_RESEARCH_V1":
        "apex/options_research/* built 2026-08-18 -- the shadow options "
        "expression research framework as a whole",
    "OPTION_MARKET_SCHEMA_V1":
        "apex/options_research/market_state.py -- OptionMarketState, OCC parsing",
    "OPTION_SURFACE_SCHEMA_V1":
        "apex/options_research/surface_state.py -- OptionSurfaceState, per-feature honesty",
    "OPTION_EXECUTION_MODEL_V1":
        "apex/options_research/execution_model.py -- CONSERVATIVE_TAKER canonical fills",
    "OPTION_EXPRESSION_ENGINE_V1":
        "apex/options_research/expression_engine.py -- OptionExpressionEngine orchestrator",
    "ASYMMETRIC_GROWTH_DOCTRINE_V1":
        "apex/options_research/asymmetric_growth_doctrine.py + asymmetry_profile.py "
        "+ scaling_potential.py + edge_maturity.py + growth_panel.py + "
        "rare_opportunity.py -- operator directive embedded 2026-08-18, "
        "same-day as the base framework build",
}


class BirthError(RuntimeError):
    pass


def mint(birth_version: str, *, now, code_lineage: str | None = None) -> dict:
    if birth_version not in BIRTH_VERSIONS:
        raise BirthError(f"unknown birth_version {birth_version!r}")
    import sys
    sys.path.insert(0, "scripts")
    from nightly_pull import _chain_append
    import pandas as pd
    now = pd.Timestamp(now)
    entry = {
        "kind": "options_research_birth",
        "birth_version": birth_version,
        "birth_time": str(now),
        "code_lineage": code_lineage or DEFAULT_LINEAGE[birth_version],
        "decision_power": OPTIONS_RESEARCH_POWER,
        "capital_authority": "NONE", "broker_authority": "NONE",
    }
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    return _chain_append(LEDGER, entry)


def already_minted(birth_version: str) -> bool:
    if not LEDGER.exists():
        return False
    import json
    for line in LEDGER.read_text().splitlines():
        if not line.strip():
            continue
        try:
            if json.loads(line).get("birth_version") == birth_version:
                return True
        except json.JSONDecodeError:
            continue
    return False


def mint_all(*, now) -> tuple:
    """Mints every birth version not already minted, in a fixed order.
    Idempotent: re-running after a partial mint only mints what's missing."""
    return tuple(mint(v, now=now) for v in BIRTH_VERSIONS if not already_minted(v))
