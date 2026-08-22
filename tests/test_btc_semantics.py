"""BTC VENUE SEMANTICS -- units and cadences as law (2026-08-21).

Pins the operator's L2 semantic corrections: ticks-vs-USD per endpoint,
current-spec settlement, and OI publication cadence vs poll cadence.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from apex.btc_sleeve import semantics as sem  # noqa: E402


def test_ticks_convert_via_the_specific_products_spec_never_hardcoded():
    out = sem.convert_bitnomial_product_data_price(
        15467, product_spec={"price_increment": 5, "product_id": 5614,
                             "symbol": "PBTCUCZ50"})
    assert out["canonical_value"] == 77335
    assert out["canonical_unit"] == "USD_PER_BTC"
    assert out["raw_unit"] == "TICKS"
    assert "5614" in out["spec_source"]
    # a DIFFERENT product's increment gives a different answer -- the
    # spec is the authority, not a constant
    other = sem.convert_bitnomial_product_data_price(
        15467, product_spec={"price_increment": 10, "product_id": 9999})
    assert other["canonical_value"] == 154670


def test_conversion_refuses_without_an_increment():
    with pytest.raises(sem.SemanticsViolation):
        sem.convert_bitnomial_product_data_price(100, product_spec={})


def test_none_price_stays_none_never_zero():
    out = sem.convert_bitnomial_product_data_price(None, product_spec={})
    assert out["canonical_value"] is None


def test_charts_usd_is_never_multiplied_by_the_increment():
    """THE DOUBLE-CONVERSION TRAP: Charts OHLC is already USD;
    multiplying by the increment would fabricate a 5x price."""
    out = sem.charts_price_passthrough(77335.0)
    assert out["canonical_value"] == 77335.0
    assert out["conversion"] == "NONE"
    reg = sem.BITNOMIAL_ENDPOINT_SEMANTICS_REGISTRY
    assert reg["/web/charts/price/"]["price_conversion"] == "NONE"
    assert reg["/product/data/"]["price_conversion"] == \
        "MULTIPLY_BY_PRODUCT_SPEC_PRICE_INCREMENT"


def test_oi_cadence_law_unknown_is_never_realtime():
    v = sem.VENUE_OI_SEMANTICS
    assert v["BITNOMIAL"]["oi_class"] == sem.OI_DAILY_PUBLISHED
    assert v["BITNOMIAL"]["real_time_capable"] is False
    assert v["DERIBIT"]["oi_class"] == sem.OI_REALTIME
    assert v["KRAKEN_FUTURES"]["oi_class"] == sem.OI_DELAYED
    # every class declaration carries measured/documented evidence
    for venue, s in v.items():
        assert s.get("evidence"), f"{venue} OI class asserted without evidence"
    assert sem.OI_UNKNOWN_CADENCE != sem.OI_REALTIME


def test_poller_uses_live_spec_settlement_not_the_expired_products():
    src = Path("scripts/btc_derivatives_poller.py").read_text()
    assert "CASH SETTLED" in src
    # strip string-literal quote breaks before checking the phrase --
    # adjacent Python string constants split words across quotes
    normalized = " ".join(src.lower().replace('"', "").split())
    assert "deliverable" not in normalized.replace(
        "series was deliverable", ""), (
        "'deliverable' appears outside the historical PBUC note")
    assert "spec_provenance" in src
    assert "product/spec/5614" in src


def test_poller_carries_full_conversion_metadata():
    import json
    p = Path("results/btc/derivatives_ledger.jsonl")
    if not p.exists():
        pytest.skip("no live ledger in this environment")
    rows = [json.loads(l) for l in p.read_text().splitlines()[-5:]]
    latest = rows[-1]
    b = latest["venues"].get("BITNOMIAL", {})
    if b.get("status") != "OK":
        pytest.skip("bitnomial not OK in latest poll")
    lt = b.get("last_trade")
    if not isinstance(lt, dict):
        pytest.skip("pre-lineage ledger rows")
    for field in ("raw_value", "raw_unit", "conversion",
                  "canonical_value", "canonical_unit", "semantic_type",
                  "field_name", "endpoint", "last_update_time"):
        assert field in lt
    assert lt["semantic_type"] == "LAST_TRADE"
    fm = b.get("funding_mark", {})
    assert fm.get("semantic_type") == "FUNDING_MARK"
    oi = b.get("open_interest", {})
    assert oi.get("oi_class") == "OI_DAILY_PUBLISHED"
    assert oi.get("real_time_capable") is False



def test_funding_mark_is_never_in_realtime_reconciliation():
    """THE LINEAGE LAW: the un-timestamped funding-interval value
    (0 changes/153 polls) manufactured a fake -1.48% discount when
    compared against real-time references -- the fresh LAST_TRADE was
    only ~-0.2% off. FUNDING_MARK may be stored, never compared."""
    import json
    p = Path("results/btc/derivatives_ledger.jsonl")
    if not p.exists():
        pytest.skip("no live ledger")
    rows = [json.loads(l) for l in p.read_text().splitlines()]
    checked = 0
    for r in rows:
        recon = r.get("cross_venue_reconciliation_same_poll")
        if not recon:
            continue
        # the ledger is append-only: rows from BEFORE the lineage fix
        # retain the defective key as historical evidence. The law
        # applies to every row written under the post-fix schema
        # (identified by the last_trade lineage object).
        if not isinstance((r["venues"].get("BITNOMIAL") or {}
                           ).get("last_trade"), dict):
            continue
        checked += 1
        for key in recon:
            assert "funding_mark" not in key.lower()
            assert "bitnomial_mark" not in key.lower(), (
                f"un-lineaged 'mark' comparison present: {key}")
    if checked == 0:
        pytest.skip("no reconciliation rows yet")


def test_price_semantic_types_registry():
    from apex.btc_sleeve.semantics import (
        BITNOMIAL_PRODUCT_DATA_PRICE_SEMANTICS, PRICE_SEMANTIC_TYPES)
    assert "FUNDING_MARK" in PRICE_SEMANTIC_TYPES
    assert "BOOK_MID" in PRICE_SEMANTIC_TYPES
    s = BITNOMIAL_PRODUCT_DATA_PRICE_SEMANTICS
    assert s["mark_price"]["semantic_type"] == "FUNDING_MARK"
    assert s["last_price"]["semantic_type"] == "LAST_TRADE"
    assert s["last_price"]["timestamp_field"] == "last_price_time"
    assert "NEVER compared" in s["mark_price"]["law"]
