"""Red-team remediation tests — each reproduces an AUDIT-FINDINGS defect.
Test ids reference results/AUDIT-FINDINGS.json."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from nightly_pull import _chain_append  # noqa: E402


# F-01: a torn write must not kill the archive
def test_f01_chain_survives_torn_tail(tmp_path):
    led = tmp_path / "led.jsonl"
    _chain_append(led, {"kind": "x", "n": 1})
    e2 = _chain_append(led, {"kind": "x", "n": 2})
    with led.open("a") as fh:
        fh.write('{"kind":"x","n":3,"prev_hash":"TRUNC')      # crash artifact
    e4 = _chain_append(led, {"kind": "x", "n": 4})            # must survive
    assert e4["prev_hash"] == e2["entry_hash"]                # links past tear
    assert e4.get("recovered_from_torn_tail") is True         # tear recorded
    from apex.hunter.forward_pass import unrealized_decisions
    assert unrealized_decisions("2026-08-17", led) == []      # readers survive
    from apex.hunter.birth import load_births
    assert load_births(led) == {}                             # tolerant, empty


# F-02: one symbol cannot dominate analogue support
def test_f02_single_symbol_cannot_be_ok_support():
    from apex.analog.engine import retrieve
    from apex.hunter.evidence import EvidenceClass
    from tests.test_hunter_spine import QUERY, mem_row
    rows = [mem_row(i, f"2026-07-{(i % 25) + 1:02d}") for i in range(50)]
    r = retrieve(QUERY, rows,
                 evidence_class=EvidenceClass.EODHD_FORWARD_OBSERVATION)
    assert r.status == "ANALOG_SUPPORT_LOW"      # all-AMD memory is not OK
    assert r.n_symbols == 1
    varied = []
    for i in range(50):
        row = mem_row(i, f"2026-07-{(i % 25) + 1:02d}")
        row["symbol"] = f"S{i % 8}"
        varied.append(row)
    r2 = retrieve(QUERY, varied,
                  evidence_class=EvidenceClass.EODHD_FORWARD_OBSERVATION)
    assert r2.status == "OK" and r2.n_symbols == 8


# F-03: protocol §2 compliance — state records carry a regime field
def test_f03_state_record_carries_regime():
    from hunter_forward_clock import _state_snapshot
    spy = {"symbol": "SPY.US", "day_return": 0.001, "above_vwap": True,
           "realized_vol_ann": 0.1, "cum_volume": 1e6,
           "last_bar_utc": "2026-08-17 14:00:00+00:00",
           "minutes_recorded": 30}
    rec = _state_snapshot(pd.Timestamp("2026-08-17 14:05", tz="UTC"),
                          type("G", (), {"used": 0})(), "2026-08-17",
                          {"SPY.US": _frame_for(spy)})
    assert "regime" in rec
    assert rec["regime"]["daily_classifier"] == "NOT_WIRED_INTRADAY"
    assert rec["regime"]["uncertain_proxy"] in (True, False)


def _frame_for(state):
    import numpy as np
    t0 = pd.Timestamp("2026-08-17 13:30", tz="UTC")
    times = pd.date_range(t0, periods=30, freq="1min")
    px = np.full(30, 100.0) * (1 + state["day_return"])
    return pd.DataFrame({"provider_symbol": "SPY.US",
                         "event_time_utc": times, "open": px, "high": px,
                         "low": px, "close": px, "volume": 1e4})


# F-04: simulator refuses when ATR is unknown (no fabricated scale)
def test_f04_simulator_refuses_unknown_atr():
    from apex.world.simulator import simulate
    from tests.test_hunter_spine import sim_inputs
    cand, snap, f, hist = sim_inputs()
    assert simulate(cand, snap, f, hist, n_paths=10, atr_frac=None) is None


# F-05: ML rows with ANY missing feature are excluded, never zero-filled
def test_f05_ml_excludes_missing_features():
    from apex.ml.hunter_models import build_dataset
    from tests.test_hunter_spine import mem_row
    d = {**mem_row(0, "2026-08-10")["candidate"], "decision_id": "d0",
         "session_date": "2026-08-10", "playbook_id": "HUNTER-001_v1",
         "forward_eligibility": "FORWARD_ELIGIBLE"}
    d["chart_state"] = dict(d["chart_state"], rvol_tod=None)  # one missing
    ds = build_dataset([d], {"d0": {"ret_60m": 0.01}}, 60)
    assert ds.n_raw == 0                          # excluded, not coerced


# F-06: flat market must not yield regime 0.0
def test_f06_memory_regime_flat_market(tmp_path):
    from apex.hunter.memory import analog_memory_rows
    led = tmp_path / "led.jsonl"
    _chain_append(led, {
        "kind": "decision", "decision_id": "d1",
        "session_date": "2026-08-10", "symbol": "X",
        "playbook_id": "HUNTER-001_v1",
        "t_utc": "2026-08-10T15:00:00+00:00",
        "market_state": {"day_return": 0.0},
        "evidence_class": "EODHD_FORWARD_OBSERVATION"})
    _chain_append(led, {"kind": "realization", "decision_id": "d1",
                        "resolvable": True, "ret_60m": 0.01,
                        "evidence_class": "EODHD_FORWARD_OBSERVATION"})
    rows = analog_memory_rows("2026-08-12T00:00:00+00:00", led)
    assert rows[0]["regime"] in ("FLAT", "UP", "DOWN", None)
    assert not isinstance(rows[0]["regime"], float)


# F-07: one sovereign source for the liquidity gates
def test_f07_liquidity_constants_single_source():
    from apex.hunter import contracts, scanner
    from apex.hunter import context_builder as cb
    assert scanner.MIN_PRICE is contracts.LIQUIDITY_MIN_PRICE
    assert cb.MIN_PRICE is contracts.LIQUIDITY_MIN_PRICE
    assert scanner.MIN_MEDIAN_DOLLAR_VOL is \
        contracts.LIQUIDITY_MIN_MEDIAN_DOLLAR_VOL


# F-08: 2026 market holidays populated; holiday is CLOSED
def test_f08_holiday_calendar():
    from apex.intraday.sessions import Session, classify
    labor_day = pd.Timestamp("2026-09-07 14:30", tz="UTC")   # 10:30 ET Mon
    assert classify(labor_day) is Session.CLOSED
    thanksgiving = pd.Timestamp("2026-11-26 15:00", tz="UTC")
    assert classify(thanksgiving) is Session.CLOSED


# F-09: identical inputs -> identical decision ids (content-derived)
def test_f09_decision_ids_deterministic():
    from apex.hunter.forward_pass import decision_pass
    from tests.test_hunter_p1b import bars, ctx, failed_spike_frame
    f, t = failed_spike_frame(date="2026-08-17")
    uni = {"symbols": {"X": {"sector": "Technology", "sector_etf": None,
                             "median_dollar_volume": 500e6}},
           "universe_limitation": "test"}
    args = (t, uni, {"X": f, "SPY.US": bars("SPY", n=120, noise=5e-5)},
            {"X": ctx("X"), "SPY.US": ctx("SPY")})
    _, r1 = decision_pass(*args)
    _, r2 = decision_pass(*args)
    assert json.dumps(r1, sort_keys=True, default=str) == \
        json.dumps(r2, sort_keys=True, default=str)


# F-10: the formed-at firewall is independently load-bearing
def test_f10_formed_after_but_resolved_before_refused():
    from apex.analog.engine import retrieve
    from apex.hunter.evidence import EvidenceClass
    from tests.test_hunter_spine import QUERY, mem_row
    hostile = mem_row(7, "2026-08-18")                 # formed AFTER as_of
    hostile["resolved_at"] = "2026-08-16T21:00:00+00:00"  # claims early res.
    r = retrieve(QUERY, [hostile],
                 evidence_class=EvidenceClass.EODHD_FORWARD_OBSERVATION)
    assert r.status == "NO_VALID_ANALOGS"
