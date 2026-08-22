"""Alpaca continuity truth: reconnect event ledger, the counter law,
cause-code separation, and per-symbol trade/quote/bar continuity.

These encode the 2026-08-18 findings: reconnects=388 with zero log
evidence, and continuous_coverage_fraction=0.0 on a feed that never
actually stopped delivering.
"""
from __future__ import annotations

import pandas as pd
import pytest

from apex.intraday import reconnect_ledger as rlg
from apex.intraday import symbol_continuity as sc

T0 = pd.Timestamp("2026-08-18T14:00:00Z")


def _ev(reason="NETWORK_RECONNECT", eid="e1"):
    return rlg.make_event(event_id=eid, event_time=T0, known_from=T0,
                          reason=reason, source="alpaca_fabric")


# ---- reconnect ledger ----------------------------------------------------

def test_nine_distinct_reason_codes_exist():
    # 2026-08-20 Phase 11: +UNKNOWN_CAUSE; 2026-08-21 L2 remedy:
    # +MESSAGE_STREAM_STALE (the only staleness allowed to kill a
    # connection under the application-liveness law)
    assert len(rlg.REASON_CODES) == 11
    assert "UNKNOWN_CAUSE" in rlg.REASON_CODES
    assert "MESSAGE_STREAM_STALE" in rlg.REASON_CODES
    for required in ("NETWORK_RECONNECT", "PROVIDER_RECONNECT", "RESUBSCRIBE",
                     "HEARTBEAT_TIMEOUT", "NO_TRADES_OCCURRED",
                     "NO_QUOTES_OCCURRED", "BAR_INCOMPLETE",
                     "PROVIDER_DATA_GAP", "LOCAL_PROCESS_GAP"):
        assert required in rlg.REASON_CODES


def test_unknown_reason_code_refused():
    with pytest.raises(rlg.ReconnectLedgerError):
        _ev(reason="SOMETHING_MADE_UP")


def test_no_trades_occurred_is_not_a_transport_interruption():
    """The no-activity law: a quiet stock must never inflate the
    reconnect counter."""
    assert _ev(reason="NO_TRADES_OCCURRED").is_transport_interruption() is False
    assert _ev(reason="NO_QUOTES_OCCURRED").is_transport_interruption() is False
    assert _ev(reason="BAR_INCOMPLETE").is_transport_interruption() is False


def test_real_transport_faults_are_interruptions():
    for r in ("NETWORK_RECONNECT", "PROVIDER_RECONNECT", "HEARTBEAT_TIMEOUT",
              "LOCAL_PROCESS_GAP"):
        assert _ev(reason=r).is_transport_interruption() is True


def test_counter_matching_ledger_reconciles(tmp_path, monkeypatch):
    monkeypatch.setattr(rlg, "LEDGER", tmp_path / "rc.jsonl")
    rlg.persist(_ev(eid="e1"))
    rlg.persist(_ev(eid="e2", reason="HEARTBEAT_TIMEOUT"))
    r = rlg.reconcile(2, tmp_path / "rc.jsonl")
    assert r["state"] == "RECONCILED"
    assert r["unexplained_increments"] == 0


def test_the_2026_08_18_unexplained_388_is_now_a_health_state(tmp_path):
    """388 reconnects with zero durable events must surface as
    COUNTER_LEDGER_MISMATCH, not as a bare uninterpretable integer."""
    r = rlg.reconcile(388, tmp_path / "empty.jsonl")
    assert r["state"] == "COUNTER_LEDGER_MISMATCH"
    assert r["unexplained_increments"] == 388


def test_non_transport_events_do_not_satisfy_the_counter(tmp_path, monkeypatch):
    monkeypatch.setattr(rlg, "LEDGER", tmp_path / "rc.jsonl")
    rlg.persist(_ev(eid="e1", reason="NO_TRADES_OCCURRED"))
    rlg.persist(_ev(eid="e2", reason="NO_TRADES_OCCURRED"))
    r = rlg.reconcile(2, tmp_path / "rc.jsonl")
    assert r["state"] == "COUNTER_LEDGER_MISMATCH"


def test_reason_breakdown_reported(tmp_path, monkeypatch):
    monkeypatch.setattr(rlg, "LEDGER", tmp_path / "rc.jsonl")
    rlg.persist(_ev(eid="a", reason="NETWORK_RECONNECT"))
    rlg.persist(_ev(eid="b", reason="NO_TRADES_OCCURRED"))
    r = rlg.reconcile(1, tmp_path / "rc.jsonl")
    assert r["reason_breakdown"] == {"NETWORK_RECONNECT": 1, "NO_TRADES_OCCURRED": 1}


# ---- symbol continuity ----------------------------------------------------

def test_quiet_symbol_is_no_activity_not_provider_gap():
    """THE CORE 2026-08-18 CONFLATION. A live socket with quotes but no
    prints is a silent instrument, never a data outage."""
    label = sc.classify_interval(had_trade=False, had_quote=True,
                                 socket_open=True, process_listening=True,
                                 partial_coverage=False)
    assert label == "NO_ACTIVITY"
    assert label != "PROVIDER_GAP"


def test_closed_socket_is_provider_gap():
    assert sc.classify_interval(had_trade=False, had_quote=False,
                                socket_open=False, process_listening=True,
                                partial_coverage=False) == "PROVIDER_GAP"


def test_process_not_listening_is_local_gap_even_if_socket_open():
    assert sc.classify_interval(had_trade=False, had_quote=False,
                                socket_open=True, process_listening=False,
                                partial_coverage=False) == "LOCAL_GAP"


def test_no_trade_no_quote_open_socket_is_undetermined_not_blamed():
    assert sc.classify_interval(had_trade=False, had_quote=False,
                                socket_open=True, process_listening=True,
                                partial_coverage=False) == "UNDETERMINED"


def test_partial_coverage_with_trade_is_incomplete():
    assert sc.classify_interval(had_trade=True, had_quote=True,
                                socket_open=True, process_listening=True,
                                partial_coverage=True) == "INCOMPLETE"


def test_three_continuities_computed_separately():
    classes = (["OBSERVED"] * 60 + ["NO_ACTIVITY"] * 20
               + ["INCOMPLETE"] * 10 + ["PROVIDER_GAP"] * 5 + ["LOCAL_GAP"] * 5)
    c = sc.compute(symbol="IWM", session_date="2026-08-18",
                   interval_classes=classes, known_from=T0, now=T0)
    assert c.expected_intervals == 100
    # bar continuity counts only complete bars
    assert c.bar_continuity == pytest.approx(0.60)
    # quote continuity credits every interval the feed proved itself live
    assert c.quote_continuity == pytest.approx(0.90)
    # trade continuity excludes gaps entirely -- 70 prints of 90 possible
    assert c.trade_continuity == pytest.approx(70 / 90)
    assert c.bar_continuity != c.quote_continuity != c.trade_continuity


def test_all_quiet_symbol_does_not_report_zero_continuity():
    """A symbol that never printed but had a live quote stream all
    session must NOT look like a dead feed."""
    c = sc.compute(symbol="QUIET", session_date="2026-08-18",
                   interval_classes=["NO_ACTIVITY"] * 100, known_from=T0, now=T0)
    assert c.quote_continuity == 1.0        # feed was provably alive throughout
    assert c.trade_continuity == 0.0        # instrument genuinely never printed
    assert c.provider_gap_intervals == 0    # and that is NOT the provider's fault


def test_interval_classes_must_partition_exactly():
    with pytest.raises(sc.SymbolContinuityError):
        sc.SymbolContinuity(
            symbol="SPY", session_date="2026-08-18", expected_intervals=100,
            observed_intervals=1, provider_gap_intervals=0, local_gap_intervals=0,
            no_activity_intervals=0, incomplete_intervals=0,
            undetermined_intervals=0, trade_continuity=None, quote_continuity=None,
            bar_continuity=None, known_from=str(T0), as_of=str(T0))


def test_unknown_interval_class_refused():
    with pytest.raises(sc.SymbolContinuityError):
        sc.compute(symbol="SPY", session_date="2026-08-18",
                   interval_classes=["MADE_UP"], known_from=T0, now=T0)
