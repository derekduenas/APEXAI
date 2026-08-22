"""PAPER EXECUTION PLUMBING COMMISSIONING (2026-08-21, off-market).

Operator authorization: build and commission the paper-order pipe NOW,
tagged COMMISSIONING_TEST, with APEX intelligence explicitly NOT
connected. Strategy later plugs into a proven pipe.

Proves: full lifecycle, idempotency, duplicate prevention, restart
recovery, authority-ladder gating, and -- load-bearing, because the
stored data keys were PROVEN to authenticate against the LIVE trading
API -- that no route to a real account exists structurally.
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from apex.execution_paper import harness as hz  # noqa: E402
from apex.governance import authority_ladder as ladder  # noqa: E402

T0 = pd.Timestamp("2026-08-21 21:00:00", tz="UTC")


def _h(tmp_path):
    return hz.PaperHarness(blotter=tmp_path / "blotter.jsonl")


# ------------------------------------------------------------ lifecycle

def test_full_lifecycle_submit_fill_position_exit_pnl(tmp_path):
    h = _h(tmp_path)
    o = h.submit(mode="COMMISSIONING_TEST", symbol="TESTSYM", side="BUY",
                 qty=100, stop_price=99.0, now=T0,
                 tags={"purpose": "plumbing commissioning"})
    assert o.state == "SUBMITTED"
    h.fill_simulated(o.client_order_id, reference_price=100.0,
                     spread=0.02, now=T0 + pd.Timedelta(seconds=1))
    o = h._get(o.client_order_id)
    assert o.state == "FILLED"
    assert o.fill_price == 100.01            # adverse half-spread, never generous
    assert len(h.positions()) == 1
    h.close_position(o.client_order_id, exit_price=102.01,
                     mfe=2.5, mae=-0.4, now=T0 + pd.Timedelta(minutes=30))
    o = h._get(o.client_order_id)
    assert o.state == "CLOSED"
    assert o.realized_pnl == pytest.approx(200.0)
    assert o.r_multiple == pytest.approx(200.0 / (1.01 * 100), abs=0.01)
    assert h.positions() == []


def test_sell_side_fill_is_adverse_too(tmp_path):
    h = _h(tmp_path)
    o = h.submit(mode="COMMISSIONING_TEST", symbol="T", side="SELL",
                 qty=10, now=T0)
    h.fill_simulated(o.client_order_id, reference_price=50.0, spread=0.10,
                     now=T0)
    assert h._get(o.client_order_id).fill_price == 49.95


def test_limit_order_refuses_to_fill_through_its_limit(tmp_path):
    h = _h(tmp_path)
    o = h.submit(mode="COMMISSIONING_TEST", symbol="T", side="BUY", qty=10,
                 order_type="LIMIT", limit_price=99.50, now=T0)
    h.fill_simulated(o.client_order_id, reference_price=100.0, spread=0.02,
                     now=T0)
    assert h._get(o.client_order_id).state == "SUBMITTED"   # no fill
    h.modify(o.client_order_id, limit_price=100.05, now=T0)
    h.fill_simulated(o.client_order_id, reference_price=100.0, spread=0.02,
                     now=T0)
    assert h._get(o.client_order_id).state == "FILLED"


def test_cancel_only_from_submitted(tmp_path):
    h = _h(tmp_path)
    o = h.submit(mode="COMMISSIONING_TEST", symbol="T", side="BUY", qty=1,
                 now=T0)
    h.cancel(o.client_order_id, now=T0)
    assert h._get(o.client_order_id).state == "CANCELLED"
    with pytest.raises(hz.PaperExecutionViolation):
        h.fill_simulated(o.client_order_id, reference_price=1.0, now=T0)


# ------------------------------------- idempotency / duplicate prevention

def test_resubmitting_same_client_order_id_is_idempotent(tmp_path):
    h = _h(tmp_path)
    o1 = h.submit(mode="COMMISSIONING_TEST", symbol="T", side="BUY", qty=5,
                  client_order_id="FIXED-1", now=T0)
    o2 = h.submit(mode="COMMISSIONING_TEST", symbol="T", side="BUY", qty=5,
                  client_order_id="FIXED-1", now=T0 + pd.Timedelta(seconds=9))
    assert o1 is o2
    assert len(h.blotter_view()) == 1        # ONE order, not two


def test_duplicate_prevention_survives_restart(tmp_path):
    h = _h(tmp_path)
    h.submit(mode="COMMISSIONING_TEST", symbol="T", side="BUY", qty=5,
             client_order_id="FIXED-2", now=T0)
    h2 = _h(tmp_path)                        # fresh process, same blotter
    o = h2.submit(mode="COMMISSIONING_TEST", symbol="T", side="BUY", qty=5,
                  client_order_id="FIXED-2", now=T0)
    assert o.state == "SUBMITTED"
    assert len(h2.blotter_view()) == 1


# ------------------------------------------------------ restart recovery

def test_restart_recovery_replays_exact_state(tmp_path):
    h = _h(tmp_path)
    a = h.submit(mode="COMMISSIONING_TEST", symbol="A", side="BUY", qty=10,
                 stop_price=9.0, now=T0)
    h.fill_simulated(a.client_order_id, reference_price=10.0, now=T0)
    b = h.submit(mode="COMMISSIONING_TEST", symbol="B", side="SELL", qty=5,
                 now=T0)
    h.cancel(b.client_order_id, now=T0)

    h2 = _h(tmp_path)
    assert h2._get(a.client_order_id).state == "FILLED"
    assert h2._get(b.client_order_id).state == "CANCELLED"
    assert len(h2.positions()) == 1
    h2.close_position(a.client_order_id, exit_price=11.0, now=T0)
    assert h2._get(a.client_order_id).realized_pnl == pytest.approx(10.0)


# ------------------------------------------------- authority-ladder gate

def test_default_level_is_observe_and_paper_modes_are_refused(tmp_path,
                                                              monkeypatch):
    monkeypatch.setattr(ladder, "LEDGER", tmp_path / "none.jsonl")
    assert ladder.current_level() == "OBSERVE"
    h = _h(tmp_path)
    with pytest.raises(hz.PaperExecutionViolation):
        h.submit(mode="PAPER_EXPLORATORY", symbol="T", side="BUY", qty=1,
                 now=T0)
    # COMMISSIONING_TEST is infrastructure, allowed at OBSERVE
    h.submit(mode="COMMISSIONING_TEST", symbol="T", side="BUY", qty=1,
             now=T0)


def test_no_live_mode_exists_to_request(tmp_path):
    h = _h(tmp_path)
    for bad in ("LIVE", "TINY_LIVE", "REAL", "PRODUCTION"):
        with pytest.raises(hz.PaperExecutionViolation):
            h.submit(mode=bad, symbol="T", side="BUY", qty=1, now=T0)


def test_ladder_promotions_are_one_step_and_operator_authorized(
        tmp_path, monkeypatch):
    monkeypatch.setattr(ladder, "LEDGER", tmp_path / "l.jsonl")
    with pytest.raises(ladder.AuthorityViolation):
        ladder.record_transition(to="PAPER_AUTHORIZED",
                                 operator_authorization="x" * 20,
                                 evidence="skip attempt", now=T0)
    with pytest.raises(ladder.AuthorityViolation):
        ladder.record_transition(to="PAPER_EXPLORATORY",
                                 operator_authorization="",
                                 evidence="no authorization", now=T0)
    ladder.record_transition(
        to="PAPER_EXPLORATORY",
        operator_authorization="operator: enable exploratory paper "
                               "(test fixture)",
        evidence="commissioning test", now=T0)
    assert ladder.current_level() == "PAPER_EXPLORATORY"


# ------------------------------------------------- no-route-to-live proof

def test_live_trading_host_is_refused_by_the_url_law():
    with pytest.raises(hz.PaperExecutionViolation):
        hz._check_host("https://api.alpaca.markets/v2/orders")
    hz._check_host("https://paper-api.alpaca.markets/v2/orders")  # allowed


def test_alpaca_paper_adapter_refuses_without_dedicated_paper_keys(
        monkeypatch):
    monkeypatch.delenv("ALPACA_PAPER_KEY_ID", raising=False)
    monkeypatch.delenv("ALPACA_PAPER_SECRET_KEY", raising=False)
    out = hz.alpaca_paper_account()
    assert out["status"] == "REFUSED"
    assert "PAPER keys absent" in out["reason"]


def test_package_import_closure_cannot_reach_live_execution():
    from apex.audit.execution_path import module_closure
    from apex.execution_paper import FORBIDDEN_IMPORTS
    root = Path(__file__).resolve().parent.parent
    closure = (module_closure(root, "apex.execution_paper")
               | module_closure(root, "apex.execution_paper.harness"))
    for mod in closure:
        for f in FORBIDDEN_IMPORTS:
            # module-BOUNDARY match: apex.execution_paper is NOT
            # apex.execution -- a naive substring check flags the
            # package's own name
            assert not (mod == f or mod.startswith(f + ".")), (
                f"paper harness reaches {mod} -- a route to live "
                f"execution exists")


def test_live_api_host_never_appears_in_package_source():
    for p in Path("apex/execution_paper").glob("*.py"):
        src = p.read_text()
        assert "https://api.alpaca.markets" not in src, (
            f"{p}: the live trading URL must not exist in this package")


def test_every_blotter_event_is_hash_chained(tmp_path):
    h = _h(tmp_path)
    o = h.submit(mode="COMMISSIONING_TEST", symbol="T", side="BUY", qty=1,
                 now=T0)
    h.fill_simulated(o.client_order_id, reference_price=1.0, now=T0)
    rows = [json.loads(l) for l in
            (tmp_path / "blotter.jsonl").read_text().splitlines()]
    assert rows[0]["prev_hash"] == "GENESIS"
    assert rows[1]["prev_hash"] == rows[0]["entry_hash"]
    assert all(r["mode"] == "COMMISSIONING_TEST" for r in rows)
