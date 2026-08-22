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


# ---------------------------------------------------------------------
# FORENSIC_CORRUPTED_INTERVAL (operator mandate, 2026-08-22): the WS
# ledgers' dual-writer window compromised LEDGER PROVENANCE -- not
# necessarily the market data, but a chain whose integrity is uncertain
# may not feed World Lab or any eligible corpus. The boundary marker is
# the append-only `commissioning_perturbation` record itself (appended
# after both writers were killed and before the locked daemon started):
# every row at or before it is forensic; every row after it must chain
# cleanly.
FORENSIC_REASON = "FORENSIC_CORRUPTED_INTERVAL_DUAL_WRITER"
_PERTURBATION_CAUSE = "BUILDER_CAUSED_DUAL_WRITER"


def ws_chain_closure_report(ledger_path: Path) -> dict:
    """Hard closure of the dual-writer incident for one WS ledger:
    bounds the forensic interval, proves the post-fix chain is clean,
    and reports lock-contention observability."""
    rows = [json.loads(x) for x in
            Path(ledger_path).read_text().splitlines() if x.strip()]
    boundary = None
    for i, r in enumerate(rows):
        if r.get("kind") == "commissioning_perturbation" and \
                r.get("cause") == _PERTURBATION_CAUSE:
            boundary = i
    if boundary is None:
        return {"kind": "ws_chain_closure", "ledger": str(ledger_path),
                "status": "NO_PERTURBATION_MARKER",
                "rows_total": len(rows)}
    post = rows[boundary:]
    post_breaks = sum(
        1 for i in range(1, len(post))
        if post[i].get("prev_hash") != post[i - 1].get("entry_hash"))
    pre_breaks = sum(
        1 for i in range(1, boundary + 1)
        if rows[i].get("prev_hash") != rows[i - 1].get("entry_hash"))
    contention = Path("results/btc/ws_lock_contention.jsonl")
    contention_events = (len(contention.read_text().splitlines())
                        if contention.exists() else 0)
    return {"kind": "ws_chain_closure", "ledger": str(ledger_path),
            "rows_total": len(rows),
            "forensic_interval_rows": boundary + 1,
            "forensic_interval_bounds": {
                "first_known_from": rows[0].get("known_from"),
                "boundary_known_from": rows[boundary].get("known_from")},
            "forensic_eligibility": {
                "canonical_eligible": False,
                "research_eligible": False,
                "forecast_eligible": False,
                "reason": FORENSIC_REASON,
                "note": "ledger provenance compromised; underlying "
                        "market data not necessarily bad -- excluded "
                        "anyway"},
            "pre_fix_chain_breaks_preserved": pre_breaks,
            "post_fix_rows": len(post) - 1,
            "POST_FIX_HASH_CHAIN_BREAKS": post_breaks,
            "DUAL_WRITER_EVENTS_POST_FIX": 0 if post_breaks == 0 else
            "UNKNOWN -- breaks present, investigate",
            "LOCK_CONTENTION_EVENTS": contention_events,
            "lock_contention_observable": True}


def ws_eligible_rows(ledger_path: Path):
    """WS-ledger analog of eligible_rows: yields only rows AFTER the
    dual-writer perturbation marker (forensic interval excluded)."""
    rows = [json.loads(x) for x in
            Path(ledger_path).read_text().splitlines() if x.strip()]
    boundary = -1
    for i, r in enumerate(rows):
        if r.get("kind") == "commissioning_perturbation" and \
                r.get("cause") == _PERTURBATION_CAUSE:
            boundary = i
    for r in rows[boundary + 1:]:
        yield r


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
