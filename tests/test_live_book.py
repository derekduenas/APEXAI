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


def policy(tmp_path, cap=300.0, budget=600.0):
    pp = tmp_path / "policy.json"
    if not pp.exists():
        LB.seal_risk_policy(max_loss_per_intent_dollars=cap,
                            experiment_budget_dollars=budget,
                            sealed_by_operator=True, policy_path=pp)
    return pp


def intent_kwargs(tmp_path, **over):
    kw = dict(candidate_id="2026-08-31:001:SPY", sleeve="OPTIONS",
              symbol="SPY", expression="LONG_PUT", direction="SHORT",
              source_stream="options_evaluation",
              known_from="2026-08-31T14:00:00Z",
              declared_risk=125.0, max_loss_dollars=125.0,
              account_equity_at_approval=4000.0,
              broker_preview=PREVIEW, operator_approved=True,
              card_hash="abc123",
              policy_path=policy(tmp_path))
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
        LB.seal_intent(**intent_kwargs(tmp_path, 
            source_stream="manual_test_trade"),
            ledger=tmp_path / "i.jsonl")


def test_unapproved_intents_are_refused(tmp_path):
    with pytest.raises(LB.LiveBookViolation, match="approve"):
        LB.seal_intent(**intent_kwargs(tmp_path, operator_approved=False),
                       ledger=tmp_path / "i.jsonl")


def test_unbounded_loss_is_refused(tmp_path):
    with pytest.raises(LB.LiveBookViolation, match="bounded"):
        LB.seal_intent(**intent_kwargs(tmp_path, max_loss_dollars=0),
                       ledger=tmp_path / "i.jsonl")


def test_unpreviewed_orders_are_refused(tmp_path):
    with pytest.raises(LB.LiveBookViolation, match="preview"):
        LB.seal_intent(**intent_kwargs(tmp_path, broker_preview={}),
                       ledger=tmp_path / "i.jsonl")


def test_a_valid_intent_seals_once_and_only_once(tmp_path):
    led = tmp_path / "i.jsonl"
    r1 = LB.seal_intent(**intent_kwargs(tmp_path, ), ledger=led)
    r2 = LB.seal_intent(**intent_kwargs(tmp_path, ), ledger=led)
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
    LB.seal_intent(**intent_kwargs(tmp_path, ), ledger=il)
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
    LB.seal_intent(**intent_kwargs(tmp_path, ), ledger=il)
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


# ================================================ LIVE FITNESS GATE

def test_live_can_never_increase_canonical_risk(tmp_path):
    with pytest.raises(LB.LiveBookViolation, match="REDUCE-ONLY"):
        LB.seal_intent(**intent_kwargs(tmp_path,
                                       max_loss_dollars=200.0),
                       ledger=tmp_path / "i.jsonl")


def test_no_sealed_policy_fails_closed(tmp_path):
    kw = intent_kwargs(tmp_path)
    kw["policy_path"] = tmp_path / "absent.json"
    with pytest.raises(LB.LiveBookViolation, match="FAILS *CLOSED"):
        LB.seal_intent(**kw, ledger=tmp_path / "i.jsonl")


def test_over_ceiling_structures_are_refused_first_class(tmp_path):
    """$350 structure vs the $300 ceiling: live yields, paper
    continues, and the refusal is sealed evidence."""
    led = tmp_path / "i.jsonl"
    r = LB.seal_intent(**intent_kwargs(
        tmp_path, declared_risk=350.0, max_loss_dollars=350.0),
        ledger=led)
    assert r["kind"] == "live_intent_refused"
    assert r["refusal"] == "REFUSED_LIVE_MIN_SIZE"
    assert r["per_intent_ceiling"] == 300.0
    assert "paper continues" in r["why"]


def test_the_279_structure_fits_the_operator_ceiling(tmp_path):
    r = LB.seal_intent(**intent_kwargs(
        tmp_path, declared_risk=279.0, max_loss_dollars=279.0),
        ledger=tmp_path / "i.jsonl")
    assert r["kind"] == "live_intent"


def test_open_intents_commit_against_the_experiment_budget(tmp_path):
    """Two $279 open intents on a $600 budget: the second fits
    (558 <= 600) and the THIRD is REFUSED_LIVE_BUDGET -- open
    worst-case counts as committed until resolved."""
    led = tmp_path / "i.jsonl"
    pp = policy(tmp_path)
    for n, cid in enumerate(("A", "B", "C")):
        r = LB.seal_intent(**{**intent_kwargs(tmp_path),
                              "candidate_id": f"2026-08-31:00{n}:SPY",
                              "declared_risk": 279.0,
                              "max_loss_dollars": 279.0,
                              "policy_path": pp}, ledger=led)
        if cid in ("A", "B"):
            assert r["kind"] == "live_intent"
        else:
            assert r["refusal"] == "REFUSED_LIVE_BUDGET"
            assert r["exposure_before_intent"][
                "committed_open_worst_case"] == 558.0


def test_funding_the_account_more_changes_nothing(tmp_path):
    """The crucial improvement: ceilings are absolute -- a fat
    account raises no limit."""
    r = LB.seal_intent(**intent_kwargs(
        tmp_path, declared_risk=350.0, max_loss_dollars=350.0,
        account_equity_at_approval=1_000_000.0),
        ledger=tmp_path / "i.jsonl")
    assert r["refusal"] == "REFUSED_LIVE_MIN_SIZE"


def test_policy_is_an_operator_decision_with_sane_ceilings(tmp_path):
    with pytest.raises(LB.LiveBookViolation, match="operator"):
        LB.seal_risk_policy(max_loss_per_intent_dollars=300,
                            experiment_budget_dollars=600,
                            sealed_by_operator=False,
                            policy_path=tmp_path / "p.json")
    with pytest.raises(LB.LiveBookViolation, match="afford"):
        LB.seal_risk_policy(max_loss_per_intent_dollars=300,
                            experiment_budget_dollars=100,
                            sealed_by_operator=True,
                            policy_path=tmp_path / "p.json")
    pol = LB.seal_risk_policy(max_loss_per_intent_dollars=300,
                              experiment_budget_dollars=600,
                              sealed_by_operator=True,
                              policy_path=tmp_path / "p.json")
    assert pol["experiment_budget_dollars"] == 600.0
    assert "never" in pol["meaning"]
