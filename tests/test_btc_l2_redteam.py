"""BTC-L2 RED TEAM (operator directive, final L2 commissioning).

Every attack must end in REFUSAL / DEGRADED / INVALID / NOT_ESTIMABLE.
Never silent correction.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from apex.btc_sleeve.book_engine import (  # noqa: E402
    BOOK_CLOSED, BOOK_INVALID, BOOK_VALID, BookState)
from apex.btc_sleeve.lineage_eligibility import (  # noqa: E402
    PRE_LINEAGE_REASON, classify_row, eligible_rows, exclusion_report)
from apex.btc_sleeve.semantics import (  # noqa: E402
    LAST_TRADE_MAX_AGE_S, SemanticsViolation,
    convert_bitnomial_product_data_price,
    last_trade_realtime_eligibility, normalize_funding,
    normalize_open_interest)

LEDGER = Path("results/btc/derivatives_ledger.jsonl")


def _snapshot(ack=100, bids=((15650, 50), (15645, 30)),
              asks=((15660, 50), (15665, 40))):
    return {"type": "book", "ack_id": ack, "bids": list(bids),
            "asks": list(asks), "symbol": "PBTCUCZ50",
            "timestamp": "2026-08-22T00:00:00Z"}


def _level(ack, price, qty, side="Bid"):
    return {"type": "level", "ack_id": ack, "price": price,
            "quantity": qty, "side": side, "symbol": "PBTCUCZ50",
            "timestamp": "2026-08-22T00:00:01Z"}


# ------------------------------------------------ price units / metadata

def test_wrong_units_attack_conversion_refuses_without_increment():
    with pytest.raises(SemanticsViolation):
        convert_bitnomial_product_data_price(15650, product_spec={})


def test_expired_metadata_attack_spec_without_increment_refused():
    """An old/expired product spec that lacks price_increment must
    refuse conversion, never fall back to a hardcoded 5."""
    with pytest.raises(SemanticsViolation):
        convert_bitnomial_product_data_price(
            15650, product_spec={"symbol": "PBUCZ22_EXPIRED"})


def test_ws_unit_unresolved_refuses_usd():
    """WS price unit starts UNKNOWN; USD conversion is REFUSED until
    the empirical resolution against REST succeeds."""
    import btc_ws_stream as ws
    s = object.__new__(ws.BitnomialStream)
    s.unit = None
    s.spec = {"price_increment": 5, "product_id": 5614}
    out = s._usd(15650.0)
    assert out["canonical_value"] is None
    assert out["conversion"] == "REFUSED_UNIT_UNRESOLVED"


# ------------------------------------------------ stale trade / frozen mark

def test_stale_last_trade_is_ineligible():
    g = last_trade_realtime_eligibility(LAST_TRADE_MAX_AGE_S + 1)
    assert not g["eligible"]
    assert g["reason"] == "LAST_TRADE_REALTIME_COMPARISON_INELIGIBLE"


def test_unknown_trade_age_is_ineligible():
    assert not last_trade_realtime_eligibility(None)["eligible"]


def test_fresh_trade_is_eligible():
    assert last_trade_realtime_eligibility(5.0)["eligible"]


def test_staleness_policy_is_predeclared_not_tuned():
    src = Path("apex/btc_sleeve/semantics.py").read_text()
    assert "never tuned from favorable results" in src
    assert LAST_TRADE_MAX_AGE_S == 60.0


def test_frozen_mark_law_survives_in_source():
    from apex.btc_sleeve.semantics import (
        BITNOMIAL_PRODUCT_DATA_PRICE_SEMANTICS as SEM)
    assert SEM["mark_price"]["semantic_type"] == "FUNDING_MARK"
    assert "NEVER" in SEM["mark_price"]["law"]


# ------------------------------------------------ OI cadence attacks

def test_daily_oi_polled_rapidly_stays_daily():
    """Polling Bitnomial OI at 15s must not make it real-time."""
    from apex.btc_sleeve.semantics import VENUE_OI_SEMANTICS
    b = VENUE_OI_SEMANTICS["BITNOMIAL"]
    assert b["oi_class"] == "OI_DAILY_PUBLISHED"
    assert b["real_time_capable"] is False


def test_oi_normalization_preserves_provenance_and_refuses():
    out = normalize_open_interest("BITNOMIAL", 1000)
    assert out["oi_class"] == "OI_DAILY_PUBLISHED"     # provenance kept
    assert out["oi_btc_equivalent"] is None            # no contract size
    assert "derivation_refused" in out
    ok = normalize_open_interest("BITNOMIAL", 1000, contract_btc=0.01,
                                 btc_usd=78000)
    assert ok["oi_btc_equivalent"] == 10.0
    assert ok["oi_usd_notional"] == 780000.0
    with pytest.raises(SemanticsViolation):
        normalize_open_interest("MYSTERY_VENUE", 5)


# ------------------------------------------------ funding cadence attacks

def test_funding_cadence_mismatch_refuses_annualization():
    """Kraken's native interval semantics are unverified -- annualizing
    would be a fabricated comparison: NOT_ESTIMABLE."""
    out = normalize_funding("KRAKEN_FUTURES", 0.0001)
    assert out["annualized_rate"] is None
    assert "NOT_ESTIMABLE" in out["annualization_refused"]


def test_funding_native_preserved_first():
    out = normalize_funding("BITNOMIAL", 0.0001)
    assert out["native_rate"] == 0.0001
    assert out["native_form"] == "PER_INTERVAL_ACTUAL_SETTLED"
    assert abs(out["annualized_rate"] - 0.0001 * 1095) < 1e-9


# ------------------------------------------------ book integrity attacks

def test_missing_snapshot_level_first_is_invalid():
    b = BookState()
    b.apply_level(_level(5, 15650, 10))
    assert b.quality == BOOK_INVALID
    assert b.invalid_reason == "LEVEL_BEFORE_SNAPSHOT"
    assert "book_quality" in b.top() and "best_bid_raw" not in b.top()


def test_sequence_gap_ack_regression_invalidates_no_silent_continue():
    b = BookState()
    b.apply_snapshot(_snapshot(ack=100))
    b.apply_level(_level(110, 15650, 20))
    b.apply_level(_level(105, 15645, 5))          # regression
    assert b.quality == BOOK_INVALID
    assert b.invalid_reason == "ACK_REGRESSION"
    frozen = dict(b.bids)
    b.apply_level(_level(120, 15650, 99))         # must NOT apply
    assert b.bids == frozen, "invalid book silently accepted a delta"


def test_resync_after_invalid_requires_fresh_snapshot():
    b = BookState()
    b.apply_snapshot(_snapshot(ack=100))
    b.apply_level(_level(90, 15650, 1, side="Ask"))   # stale: skipped
    assert b.levels_stale_skipped == 1
    b.on_disconnect()
    assert b.quality == BOOK_INVALID
    b.apply_snapshot(_snapshot(ack=200))
    assert b.quality == BOOK_VALID and b.resyncs == 1


def test_duplicate_same_ack_delta_is_applied_idempotently():
    """LIVE FINDING 2026-08-21: ~47% of level traffic shares an ack_id
    (atomic multi-level events). Skipping them corrupted the book; the
    law is apply-idempotent + count."""
    b = BookState()
    b.apply_snapshot(_snapshot(ack=100))
    b.apply_level(_level(110, 15650, 20))
    b.apply_level(_level(110, 15645, 0))          # same-ack member
    b.apply_level(_level(110, 15645, 0))          # true duplicate: no-op
    assert b.same_ack_repeats == 2
    assert b.bids == {15650.0: 20.0}
    assert b.quality == BOOK_VALID


def test_crossed_book_is_invalid():
    b = BookState()
    b.apply_snapshot(_snapshot(ack=100))
    b.apply_level(_level(110, 15661, 10, side="Bid"))  # bid > best ask
    assert b.quality == BOOK_INVALID
    assert b.invalid_reason == "CROSSED_OR_LOCKED_BOOK"
    assert b.crossed_events == 1


def test_locked_book_is_invalid():
    b = BookState()
    b.apply_snapshot(_snapshot(ack=100, bids=((15660, 5),),
                               asks=((15660, 5),)))
    assert b.quality == BOOK_INVALID


def test_negative_size_is_invalid():
    b = BookState()
    b.apply_snapshot(_snapshot(ack=100))
    b.apply_level(_level(110, 15650, -3))
    assert b.quality == BOOK_INVALID
    assert b.invalid_reason == "NEGATIVE_SIZE_DELTA"


def test_markets_closed_ack_zero_refuses_prices():
    b = BookState()
    b.apply_snapshot({"type": "book", "ack_id": 0, "bids": [],
                      "asks": [], "symbol": "PBTCUCZ50",
                      "timestamp": "t"})
    assert b.quality == BOOK_CLOSED
    assert "best_bid_raw" not in b.top()


def test_restart_during_reconstruction_book_invalid_until_snapshot():
    b = BookState()
    b.apply_snapshot(_snapshot(ack=100))
    b.apply_level(_level(110, 15650, 20))
    b.on_disconnect()
    assert b.quality == BOOK_INVALID
    b.apply_level(_level(120, 15650, 30))         # post-reconnect delta
    assert b.quality == BOOK_INVALID, "delta must not resurrect book"
    b.apply_snapshot(_snapshot(ack=300))
    assert b.quality == BOOK_VALID


def test_snapshot_divergence_probe_counts_reconstruction_errors():
    b = BookState()
    b.apply_snapshot(_snapshot(ack=100))
    div = _snapshot(ack=150, bids=((15650, 77), (15645, 30)))
    b.apply_snapshot(div)
    assert b.snapshot_divergence_events == 1
    assert b.last_divergence["mismatched_levels"]


def test_timestamp_inversion_counted_on_trades(monkeypatch, tmp_path):
    import btc_ws_stream as ws
    from collections import deque
    monkeypatch.setattr(ws, "TRADES_LEDGER", tmp_path / "t.jsonl")
    s = object.__new__(ws.BitnomialStream)
    s.unit = "TICKS"
    s.spec = {"price_increment": 5, "product_id": 5614,
              "symbol": "PBTCUCZ50"}
    s.seen_trade_acks = deque(maxlen=10)
    s.counts = {"trades": 0, "trade_duplicates": 0,
                "trade_ts_regressions": 0}
    s.prev_trade_ts = None
    s.last_trade = None
    t1 = {"ack_id": "1", "price": 15650, "quantity": 1,
          "taker_side": "Bid", "timestamp": "2026-08-22T00:00:05Z",
          "symbol": "PBTCUCZ50"}
    t2 = dict(t1, ack_id="2", timestamp="2026-08-22T00:00:03Z")
    s._on_trade(t1, 0.0)
    s._on_trade(t2, 0.0)
    s._on_trade(dict(t2), 0.0)                     # duplicate ack
    assert s.counts["trade_ts_regressions"] == 1
    assert s.counts["trade_duplicates"] == 1
    assert s.counts["trades"] == 2


# ------------------------------------------------ pre-lineage exclusion

_PRE_FIX_ROW = {"venues": {"BITNOMIAL": {
    "status": "OK", "mark_price": 15467, "mark_price_usd": 77335,
    "last_price": 15672}}}
_POST_FIX_ROW = {"venues": {"BITNOMIAL": {
    "status": "OK",
    "last_trade": {"semantic_type": "LAST_TRADE", "raw_value": 15672},
    "funding_mark": {"semantic_type": "FUNDING_MARK",
                     "raw_value": 15467},
    "settlement": {"semantic_type": "SETTLEMENT", "raw_value": 15422}}}}
_OUTAGE_ROW = {"venues": {"BITNOMIAL": {"status": "FETCH_FAILED"}}}


def test_pre_lineage_rows_excluded_for_all_purposes():
    v = classify_row(_PRE_FIX_ROW)
    assert v == {"canonical_eligible": False, "research_eligible": False,
                 "forecast_eligible": False,
                 "reason": PRE_LINEAGE_REASON,
                 "disposition": "FORENSIC_EVIDENCE_ONLY"}


def test_post_lineage_and_outage_rows_are_eligible():
    assert classify_row(_POST_FIX_ROW)["canonical_eligible"]
    assert classify_row(_OUTAGE_ROW)["canonical_eligible"]
    assert classify_row(_OUTAGE_ROW)["disposition"] == \
        "NO_BITNOMIAL_PRICES_IN_ROW"


def test_exclusion_survives_restart_and_replay(tmp_path):
    """The classifier is a pure function of the row: replaying the same
    ledger from disk in a fresh 'process' re-derives identical verdicts
    -- no in-memory state to lose on restart."""
    lp = tmp_path / "ledger.jsonl"
    lp.write_text("\n".join(json.dumps(r) for r in
                            [_PRE_FIX_ROW, _POST_FIX_ROW, _OUTAGE_ROW]))
    first = exclusion_report(lp)
    second = exclusion_report(lp)                  # the 'replay'
    assert first == second
    assert first["rows_excluded_pre_lineage"] == 1
    kept = [r for r, _ in eligible_rows(lp, purpose="forecast")]
    assert len(kept) == 2
    assert all("last_trade" in r["venues"]["BITNOMIAL"] or
               r["venues"]["BITNOMIAL"]["status"] == "FETCH_FAILED"
               for r in kept)


def test_real_ledger_pre_lineage_rows_are_excluded_and_preserved():
    """Against the REAL derivatives ledger: the pre-fix rows exist
    (preserved, append-only) and are all excluded."""
    if not LEDGER.exists():
        pytest.skip("no real ledger in this environment")
    rep = exclusion_report(LEDGER)
    assert rep["rows_excluded_pre_lineage"] >= 100, \
        "the forensic pre-fix rows must still be present, not deleted"
    assert rep["rows_eligible"] >= 1
    for row, verdict in eligible_rows(LEDGER, purpose="canonical"):
        b = (row.get("venues") or {}).get("BITNOMIAL") or {}
        if b.get("status") == "OK" and "last_trade" in b:
            assert b["last_trade"]["semantic_type"] == "LAST_TRADE"


# ------------------------------------------------ dual-writer closure

def _chain(rows):
    """Hash-chain a list of dicts the way chain_append does."""
    import hashlib
    out, prev = [], "GENESIS"
    for r in rows:
        r = dict(r, prev_hash=prev)
        prev = hashlib.sha256(
            json.dumps(r, sort_keys=True).encode()).hexdigest()
        r["entry_hash"] = prev
        out.append(r)
    return out


_MARKER = {"kind": "commissioning_perturbation",
           "cause": "BUILDER_CAUSED_DUAL_WRITER", "known_from": "t2"}


def test_chain_closure_bounds_forensic_interval_and_proves_post_fix(
        tmp_path, monkeypatch):
    from apex.btc_sleeve.lineage_eligibility import (
        FORENSIC_REASON, ws_chain_closure_report, ws_eligible_rows)
    monkeypatch.chdir(tmp_path)          # sidecar path is relative
    # pre-boundary rows with a deliberate break, then marker, then
    # a clean post-fix chain
    pre = _chain([{"kind": "ws_trade", "known_from": "t0"},
                  {"kind": "ws_trade", "known_from": "t1"}])
    pre[1]["prev_hash"] = "BROKEN_BY_SECOND_WRITER"
    tail = _chain([_MARKER,
                   {"kind": "ws_trade", "known_from": "t3"},
                   {"kind": "ws_trade", "known_from": "t4"}])
    lp = tmp_path / "ws.jsonl"
    lp.write_text("\n".join(json.dumps(r) for r in pre + tail))
    rep = ws_chain_closure_report(lp)
    assert rep["POST_FIX_HASH_CHAIN_BREAKS"] == 0
    assert rep["DUAL_WRITER_EVENTS_POST_FIX"] == 0
    assert rep["forensic_interval_rows"] == 3
    fe = rep["forensic_eligibility"]
    assert not fe["canonical_eligible"] and \
        not fe["research_eligible"] and not fe["forecast_eligible"]
    assert fe["reason"] == FORENSIC_REASON
    assert rep["lock_contention_observable"] is True
    kept = list(ws_eligible_rows(lp))
    assert [r["known_from"] for r in kept] == ["t3", "t4"]


def test_chain_closure_detects_post_fix_breaks(tmp_path, monkeypatch):
    from apex.btc_sleeve.lineage_eligibility import (
        ws_chain_closure_report)
    monkeypatch.chdir(tmp_path)
    rows = _chain([_MARKER, {"kind": "ws_trade", "known_from": "t3"}])
    rows[1]["prev_hash"] = "TAMPERED"
    lp = tmp_path / "ws.jsonl"
    lp.write_text("\n".join(json.dumps(r) for r in rows))
    rep = ws_chain_closure_report(lp)
    assert rep["POST_FIX_HASH_CHAIN_BREAKS"] == 1
    assert rep["DUAL_WRITER_EVENTS_POST_FIX"] != 0


def test_real_ws_ledgers_post_fix_chains_are_clean():
    from apex.btc_sleeve.lineage_eligibility import (
        ws_chain_closure_report)
    for lp in (Path("results/btc/ws_trades_ledger.jsonl"),
               Path("results/btc/ws_book_ledger.jsonl")):
        if not lp.exists():
            pytest.skip("no real WS ledgers in this environment")
        rep = ws_chain_closure_report(lp)
        assert rep["POST_FIX_HASH_CHAIN_BREAKS"] == 0, rep
        assert rep["pre_fix_chain_breaks_preserved"] >= 1


def test_lock_contention_is_observable(tmp_path, monkeypatch):
    import os
    import btc_ws_stream as ws
    monkeypatch.chdir(tmp_path)
    (tmp_path / "results/btc").mkdir(parents=True)
    monkeypatch.setattr(ws, "LOCK",
                        tmp_path / "results/btc/ws_stream.pid")
    ws.LOCK.write_text(str(os.getpid()))       # a provably live holder
    with pytest.raises(SystemExit):
        ws._acquire_single_writer_lock()
    side = tmp_path / "results/btc/ws_lock_contention.jsonl"
    ev = json.loads(side.read_text().splitlines()[0])
    assert ev["outcome"] == "REFUSED_SINGLE_WRITER_LAW"
    assert ev["holder_pid"] == os.getpid()


# ------------------------------------------------ snapshot reconciliation

def test_transient_divergence_classified_as_race():
    """A mismatch that self-heals by the next snapshot is a confirmed
    in-flight race, not a reconstruction error."""
    b = BookState()
    b.apply_snapshot(_snapshot(ack=100), arrival=1.0)
    b.apply_level(_level(110, 15650, 20), arrival=1.5)
    diverged = _snapshot(ack=150, bids=((15650, 77), (15645, 30)))
    b.apply_snapshot(diverged, arrival=2.0)
    assert b.snapshot_divergence_events == 1
    healed = _snapshot(ack=200, bids=((15650, 77), (15645, 30)))
    b.apply_snapshot(healed, arrival=3.0)
    assert b.races_confirmed == 1
    assert b.persistent_divergences == 0
    assert b.last_reconciliation[
        "prior_divergence_classification"] == \
        "RECONCILIATION_RACE_CONFIRMED"


def test_repeated_divergence_is_reconstruction_error():
    """The SAME level wrong at two consecutive reconciliations is
    BOOK_RECONSTRUCTION_DIVERGENCE -- L2 stays provisional."""
    b = BookState()
    b.apply_snapshot(_snapshot(ack=100), arrival=1.0)
    for ack in (150, 200):
        # venue keeps saying 15650 -> 77; we never saw that delta
        b.apply_snapshot(_snapshot(
            ack=ack, bids=((15650, 77 + ack), (15645, 30))),
            arrival=float(ack))
    assert b.persistent_divergences == 1
    assert b.last_reconciliation["classification"] == \
        "BOOK_RECONSTRUCTION_DIVERGENCE"
    assert b.last_reconciliation["repeated_levels"]


def test_reconciliation_record_carries_the_mandated_fields():
    b = BookState()
    b.apply_snapshot(_snapshot(ack=100), arrival=1.0)
    b.apply_level(_level(110, 15650, 20), arrival=1.5)
    b.apply_snapshot(_snapshot(ack=150, bids=((15650, 20),
                                              (15645, 30))),
                     arrival=2.0)
    rec = b.last_reconciliation
    for f in ("snapshot_ack", "snapshot_event_time",
              "local_last_applied_ack", "time_delta_ms",
              "levels_compared", "levels_matching",
              "quantity_mismatch", "price_mismatch",
              "top_of_book_match",
              "events_between_local_capture_and_snapshot"):
        assert f in rec, f
    assert rec["time_delta_ms"] == 500.0
    assert rec["events_between_local_capture_and_snapshot"] == 1
    assert rec["top_of_book_match"] is True
    assert rec["levels_matching"] == rec["levels_compared"]


def test_schema_change_attack_unknown_shape_is_excluded():
    """A future upstream schema change that drops lineage fields must
    fail CLOSED (excluded), not open."""
    mutated = {"venues": {"BITNOMIAL": {
        "status": "OK", "last_price": 15672,
        "some_new_field": {"semantic_type": "LAST_TRADE"}}}}
    assert not classify_row(mutated)["canonical_eligible"]
