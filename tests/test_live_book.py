"""Live book commissioning — no order surface, eligibility is not a
trigger, broker truth, two books never merged.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from apex.organism import live_book as LB


PREVIEW = {"est_price": 1.25, "est_cost": 125.0, "venue": "robinhood"}


def intent_kwargs(**over):
    kw = dict(candidate_id="2026-08-31:001:SPY", sleeve="OPTIONS",
              symbol="SPY", expression="LONG_PUT", direction="SHORT",
              source_stream="options_evaluation",
              known_from="2026-08-31T14:00:00Z",
              declared_risk=125.0, max_loss_dollars=125.0,
              broker_preview=PREVIEW, operator_approved=True,
              card_hash="abc123")
    kw.update(over)
    return kw


# ================================================ NO ORDER SURFACE

def test_the_live_book_cannot_place_orders():
    """No broker client, no MCP, no network -- structurally."""
    src = Path(LB.__file__).read_text()
    for banned in ("place_order(", "requests.", "urllib",
                   "http://", "https://", "websocket", "socket."):
        assert banned not in src.lower(), f"live_book contains {banned}"
    assert LB.REAL_ORDER_AUTHORITY == "NONE"
    for n in ast.walk(ast.parse(src)):
        mods = ([a.name for a in n.names] if isinstance(n, ast.Import)
                else [n.module or ""] if isinstance(n, ast.ImportFrom)
                else [])
        for m in mods:
            assert m in ("__future__", "annotations", "json", "datetime", "pathlib",
                         "apex.governance.chain_ledger"), \
                f"unexpected import {m}"


# ======================================== ELIGIBILITY IS NOT A TRIGGER

def test_synthetic_intents_are_refused(tmp_path):
    with pytest.raises(LB.LiveBookViolation, match="synthetic"):
        LB.seal_intent(**intent_kwargs(
            source_stream="manual_test_trade"),
            ledger=tmp_path / "i.jsonl")


def test_unapproved_intents_are_refused(tmp_path):
    with pytest.raises(LB.LiveBookViolation, match="approve"):
        LB.seal_intent(**intent_kwargs(operator_approved=False),
                       ledger=tmp_path / "i.jsonl")


def test_unbounded_loss_is_refused(tmp_path):
    with pytest.raises(LB.LiveBookViolation, match="bounded"):
        LB.seal_intent(**intent_kwargs(max_loss_dollars=0),
                       ledger=tmp_path / "i.jsonl")


def test_unpreviewed_orders_are_refused(tmp_path):
    with pytest.raises(LB.LiveBookViolation, match="preview"):
        LB.seal_intent(**intent_kwargs(broker_preview={}),
                       ledger=tmp_path / "i.jsonl")


def test_a_valid_intent_seals_once_and_only_once(tmp_path):
    led = tmp_path / "i.jsonl"
    r1 = LB.seal_intent(**intent_kwargs(), ledger=led)
    r2 = LB.seal_intent(**intent_kwargs(), ledger=led)
    assert not r1.get("duplicate") and r2.get("duplicate")
    row = json.loads(led.read_text().splitlines()[0])
    assert row["status"] == "APPROVED_AWAITING_EXECUTION"
    assert row["checklist"] == list(LB.FIRST_TRADE_CHECKLIST)
    assert "broker fills > sealed intents > models" in \
        row["truth_hierarchy"]


# ================================================== BROKER TRUTH

def _fill(ref="RH1", sym="SPY", pnl=None):
    f = {"broker_ref": ref, "symbol": sym, "expression": "LONG_PUT",
         "side": "buy", "quantity": 1, "price": 1.27,
         "time": "2026-08-31T14:31:00Z"}
    if pnl is not None:
        f["realized_pnl"] = pnl
    return f


def test_fills_reconcile_one_to_one_and_never_guess(tmp_path):
    il, fl = tmp_path / "i.jsonl", tmp_path / "f.jsonl"
    LB.seal_intent(**intent_kwargs(), ledger=il)
    r = LB.reconcile(broker_fills=[_fill()], session="2026-08-31",
                     intents_ledger=il, fills_ledger=fl)
    assert r["matched"] == 1 and r["unreconciled"] == 0
    row = json.loads(fl.read_text().splitlines()[0])
    assert row["kind"] == "live_fill"
    assert "BROKER" in row["truth"]
    # replay is idempotent on broker_ref
    r2 = LB.reconcile(broker_fills=[_fill()], session="2026-08-31",
                      intents_ledger=il, fills_ledger=fl)
    assert r2["duplicates_skipped"] == 1 and r2["matched"] == 0


def test_an_orphan_fill_is_sealed_unreconciled_not_dropped(tmp_path):
    il, fl = tmp_path / "i.jsonl", tmp_path / "f.jsonl"
    r = LB.reconcile(broker_fills=[_fill(sym="TSLA")],
                     session="2026-08-31",
                     intents_ledger=il, fills_ledger=fl)
    assert r["unreconciled"] == 1
    row = json.loads(fl.read_text().splitlines()[0])
    assert row["kind"] == "live_fill_unreconciled"
    assert "will not guess" in row["why"]


def test_state_reports_broker_truth_and_the_never_merge_law(tmp_path):
    il, fl = tmp_path / "i.jsonl", tmp_path / "f.jsonl"
    LB.seal_intent(**intent_kwargs(), ledger=il)
    LB.reconcile(broker_fills=[_fill(pnl=-12.5)],
                 session="2026-08-31",
                 intents_ledger=il, fills_ledger=fl)
    st = LB.state(intents_ledger=il, fills_ledger=fl)
    assert st["broker_realized_pnl"] == -12.5
    assert "never merged" in st["law"]
    assert st["real_order_authority"] == "NONE"


def test_nothing_on_a_trading_path_imports_the_live_book():
    for mod in list(Path("apex/predators").rglob("*.py")) + [
            Path("apex/organism/allocator.py"),
            Path("apex/organism/book.py"),
            Path("apex/capital/arena.py"),
            Path("scripts/options_paper_session.py"),
            Path("scripts/equity_shadow_session.py"),
            Path("scripts/organism_service.py")]:
        for n in ast.walk(ast.parse(mod.read_text())):
            mods = ([a.name for a in n.names]
                    if isinstance(n, ast.Import)
                    else [n.module or ""]
                    if isinstance(n, ast.ImportFrom) else [])
            assert not any("live_book" in m for m in mods), \
                f"{mod} consumes the live book"
