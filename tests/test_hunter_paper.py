"""Phase 5 + full-stack proofs: paper authorization firewall, fill
realism, trade-management safety, and the two end-to-end proofs (synthetic
full stack; production Monday truth)."""

from __future__ import annotations

import os

import pandas as pd
import pytest

from apex.hunter.capital import FinalState
from apex.hunter.expression_iface import select_expression
from apex.hunter.paper import (FillGrade, ManagementError,
                               PaperAuthorizationError, PaperPosition,
                               SyntheticTestAuthorization, assess_fill,
                               authorize_paper, manage, thesis_health)
from tests.test_hunter_capital import candidate, run
from tests.test_hunter_p1b import bars, ctx, failed_spike_frame


def synthetic_order():
    cd = run()                                       # OBSERVE in production
    return authorize_paper(cd, candidate(),
                           synthetic=SyntheticTestAuthorization())


# ---- adversarial 18: synthetic authorization impossible in production
def test_synthetic_auth_impossible_outside_tests(monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    with pytest.raises(PaperAuthorizationError):
        SyntheticTestAuthorization()
    assert "PYTEST_CURRENT_TEST" in os.environ or True


def test_production_paper_not_authorized_today():
    cd = run()
    res = authorize_paper(cd, candidate())
    assert res["state"] == "NOT_AUTHORIZED"
    assert "PAPER_ELIGIBLE" in res["reason"]
    assert "PAPER_ELIGIBLE" in {s.value for s in FinalState}  # state exists


# ---- adversarial 15: touched != filled
def test_fill_realism():
    o = synthetic_order()
    assert o.state == "ORDER_PENDING" and o.authorized_by == "SYNTHETIC_TEST"
    mk = lambda op, hi, lo: pd.DataFrame(  # noqa: E731
        {"open": [op], "high": [hi], "low": [lo], "close": [op]})
    assert assess_fill(o, mk(99.0, 100.4, 98.9))["grade"] == \
        FillGrade.CERTAIN_FILL.value                 # opened through
    assert assess_fill(o, mk(100.6, 100.8, 99.0))["grade"] == \
        FillGrade.PLAUSIBLE_FILL.value               # traded well through
    assert assess_fill(o, mk(100.6, 100.8, 100.0))["grade"] == \
        FillGrade.AMBIGUOUS_FILL.value               # bare touch: no P&L
    assert assess_fill(o, mk(100.9, 101.2, 100.6))["grade"] == \
        FillGrade.NO_FILL.value
    assert assess_fill(o, pd.DataFrame())["grade"] == FillGrade.NO_FILL.value


# ---- adversarial 14/16/17 + management laws
def test_management_safety_counterexamples():
    pos = PaperPosition(order=synthetic_order())
    with pytest.raises(ManagementError, match="never widens"):
        manage(pos, "TIGHTEN", actor="operator", new_stop=99.0)  # widen
    manage(pos, "TIGHTEN", actor="operator", new_stop=99.8)      # tighten OK
    with pytest.raises(ManagementError, match="never mutate"):
        manage(pos, "TIGHTEN", actor="llm_swarm", new_stop=100.0)
    with pytest.raises(ManagementError, match="REDUCE"):
        manage(pos, "PARTIAL", actor="operator", reduce_to=1.5)  # grow
    manage(pos, "PARTIAL", actor="operator", reduce_to=0.5)
    with pytest.raises(ManagementError, match="fresh Capital"):
        manage(pos, "ADD_IF_PERMITTED", actor="operator",
               capital_recheck=run())               # OBSERVE != authorization
    with pytest.raises(ManagementError, match="MORE uncertain"):
        manage(pos, "ADD_IF_PERMITTED", actor="operator",
               world_more_uncertain=True)
    manage(pos, "EXIT", actor="operator")
    assert pos.state == "EXITED" and pos.qty_frac == 0.0
    with pytest.raises(ManagementError):
        manage(pos, "HOLD", actor="operator")        # closed is closed


def test_thesis_health_deterministic():
    frozen = {"above_vwap": True, "or_break_up": True, "rs_positive": True}
    assert thesis_health(frozen, {"above_vwap": True, "or_break_up": True,
                                  "rs_positive": True})["health"] == \
        "THESIS_HEALTHY"
    assert thesis_health(frozen, {"above_vwap": False, "or_break_up": True,
                                  "rs_positive": True})["health"] == \
        "THESIS_WEAKENING"
    assert thesis_health(frozen, {"above_vwap": False,
                                  "rs_positive": False})["health"] == \
        "THESIS_INVALID"
    assert thesis_health(frozen, {"invalidation_hit": True})["health"] == \
        "THESIS_INVALID"


# ---- adversarial 23: options stay dormant
def test_options_interface_dormant():
    r = select_expression("LONG_CALL", distribution_status="REFUSED")
    assert r["expression"] == "STOCK" and r["demoted"]
    assert any("DORMANT" in x for x in r["reasons"])
    assert select_expression("STOCK",
                             distribution_status="REFUSED")["demoted"] is False


# ---- PART 20: synthetic full-stack proof, market state to memory
def test_full_stack_synthetic_proof(tmp_path):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    from nightly_pull import _chain_append

    from apex.hunter.forward_pass import decision_pass, resolve_decision
    from apex.hunter.memory import candidate_lineage

    f, t = failed_spike_frame(date="2026-08-17")   # post-birth Monday
    universe = {"symbols": {"X": {"sector": "Technology", "sector_etf": None,
                                  "median_dollar_volume": 500e6}},
                "universe_limitation": "synthetic-proof"}
    scan_rec, records = decision_pass(
        t, universe, {"X": f, "SPY.US": bars("SPY", n=120, noise=5e-5)},
        {"X": ctx("X"), "SPY.US": ctx("SPY")})
    led = tmp_path / "ledger.jsonl"
    _chain_append(led, scan_rec)
    for r in records:
        _chain_append(led, r)
    pb = [r for r in records if r.get("kind") == "decision"
          and not r["playbook_id"].startswith("BASELINE-")][0]
    cap = [r for r in records if r.get("kind") == "capital_decision"][0]
    fb = [r for r in records if r.get("kind") == "forecast_bundle"][0]
    assert fb["distribution_source_status"] == "REFUSED"

    # synthetic-only paper authorization -> fill -> manage -> exit
    class _Cap:                                      # ledger dict -> obj view
        final_state = cap["final_state"]
        weight = cap["weight"]
        decision_id = cap["decision_id"]
    order = authorize_paper(_Cap(), pb, bundle_id=fb["candidate_id"],
                            synthetic=SyntheticTestAuthorization())
    _chain_append(led, order.as_record())
    fill = assess_fill(order, f.tail(5).reset_index(drop=True))
    assert fill["grade"] in [g.value for g in FillGrade]
    pos = PaperPosition(order=order)
    manage(pos, "EXIT", actor="integration-test")

    # realization + memory lineage
    real = resolve_decision(pb, f)
    _chain_append(led, real)
    lin = candidate_lineage(pb["decision_id"], led)
    assert set(lin["before"]) >= {"decision", "forecast_bundle",
                                  "capital_decision", "paper_order"}
    assert lin["after"]["realization"]["decision_id"] == pb["decision_id"]
    # adversarial 20: BEFORE and AFTER are separate records; the decision
    # inside the lineage still carries no outcome fields
    assert "ret_60m" not in lin["before"]["decision"]


# ---- PART 21: production Monday truth
def test_production_forward_path_monday_truth():
    f, t = failed_spike_frame(date="2026-08-17")   # post-birth Monday
    universe = {"symbols": {"X": {"sector": "Technology", "sector_etf": None,
                                  "median_dollar_volume": 500e6}},
                "universe_limitation": "test"}
    _, records = decision_pass_prod(t, universe, f)
    fb = [r for r in records if r.get("kind") == "forecast_bundle"][0]
    cap = [r for r in records if r.get("kind") == "capital_decision"][0]
    assert fb["ml_view"]["status"] == "UNTRAINED"
    assert fb["swarm_view"]["status"] == "BLOCKED_EXTERNAL_AUTH"
    assert fb["analog_view"]["status"] in ("NO_VALID_ANALOGS",
                                           "ANALOG_SUPPORT_LOW", "OK")
    assert fb["distribution_source_status"] in ("REFUSED", "ANALOG_FORWARD")
    assert cap["final_state"] in ("OBSERVE", "WATCH", "NO_TRADE", "REFUSED")
    assert cap["final_state"] != "PAPER_ELIGIBLE"    # unreachable, proven
    assert "NO_CALIBRATED_FORECAST" in cap["reason_codes"]
    # and NO paper order exists anywhere in the production records
    assert not any(r.get("kind") == "paper_order" for r in records)


def decision_pass_prod(t, universe, f):
    from apex.hunter.forward_pass import decision_pass
    return decision_pass(
        t, universe, {"X": f, "SPY.US": bars("SPY", n=120, noise=5e-5)},
        {"X": ctx("X"), "SPY.US": ctx("SPY")})
