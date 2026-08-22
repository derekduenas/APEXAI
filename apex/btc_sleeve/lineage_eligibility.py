"""PERMANENT LINEAGE-EXCLUSION LAW (operator-issued 2026-08-21).

Ledger rows written BEFORE the price-lineage schema (rows whose
Bitnomial block lacks per-field semantic lineage) carried a semantic
defect: an un-timestamped funding-interval mark compared against
real-time references, manufacturing a fake -1.48% "discount".

Those rows are PRESERVED as append-only forensic history and must
NEVER become eligible for canonical state, historical episodes, World
Lab training, analog retrieval, forecast corpus, participant-pressure
inference, Capital, or paper trading.

The classifier is a PURE FUNCTION OF THE ROW ITSELF -- no in-memory
state, no sidecar mutability -- so the exclusion trivially survives
restart and replay: any consumer replaying the ledger from disk
re-derives the identical verdict. Deleting or rewriting the historical
rows is forbidden (the hash chain would scream anyway).
"""
from __future__ import annotations

import json
from pathlib import Path

PRE_LINEAGE_REASON = "PRE_LINEAGE_SEMANTIC_DEFECT"

# The lineage schema's signature: the Bitnomial block carries per-field
# lineage dicts (last_trade with an explicit semantic_type). Rows where
# BITNOMIAL fetch failed entirely carry no Bitnomial prices at all --
# they are lineage-neutral and judged by the schema they do carry.
_LINEAGE_FIELDS = ("last_trade", "funding_mark", "settlement")


def classify_row(row: dict) -> dict:
    """Eligibility verdict for one derivatives-ledger row.

    Returns explicit flags -- consumers must check `canonical_eligible`
    (and friends) rather than inferring from schema shape themselves.
    """
    b = (row.get("venues") or {}).get("BITNOMIAL") or {}
    has_bitnomial_prices = any(
        k in b for k in ("last_trade", "mark_price_usd", "mark_price",
                         "last_price"))
    has_lineage = all(
        isinstance(b.get(f), dict) and "semantic_type" in b.get(f, {})
        for f in _LINEAGE_FIELDS) if has_bitnomial_prices else None

    if has_bitnomial_prices and not has_lineage:
        return {"canonical_eligible": False,
                "research_eligible": False,
                "forecast_eligible": False,
                "reason": PRE_LINEAGE_REASON,
                "disposition": "FORENSIC_EVIDENCE_ONLY"}
    return {"canonical_eligible": True,
            "research_eligible": True,
            "forecast_eligible": True,
            "reason": None,
            "disposition": ("LINEAGE_SCHEMA" if has_bitnomial_prices
                            else "NO_BITNOMIAL_PRICES_IN_ROW")}


def eligible_rows(ledger_path: Path, *, purpose: str = "canonical"):
    """The ONLY sanctioned way to read the derivatives ledger for any
    downstream purpose. Yields (row, verdict) for eligible rows only;
    excluded rows are counted, never yielded."""
    key = {"canonical": "canonical_eligible",
           "research": "research_eligible",
           "forecast": "forecast_eligible"}[purpose]
    for line in Path(ledger_path).read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        verdict = classify_row(row)
        if verdict[key]:
            yield row, verdict


def exclusion_report(ledger_path: Path) -> dict:
    total, excluded = 0, 0
    for line in Path(ledger_path).read_text().splitlines():
        if not line.strip():
            continue
        total += 1
        if not classify_row(json.loads(line))["canonical_eligible"]:
            excluded += 1
    return {"kind": "lineage_exclusion_report",
            "ledger": str(ledger_path), "rows_total": total,
            "rows_excluded_pre_lineage": excluded,
            "rows_eligible": total - excluded,
            "law": PRE_LINEAGE_REASON,
            "historical_rows": "PRESERVED_APPEND_ONLY"}
