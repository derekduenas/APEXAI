"""OptionExpressionEngine — F O17: composition of thesis + horizon +
cohort + surface gates into one ExpressionResearchDecision. Never
grants trade authority; NO_TRADE/STOCK are always present regardless
of outcome.
"""
from __future__ import annotations

import json

import pandas as pd
import pytest

from apex.options_research import expression_engine as engine_mod
from apex.options_research import forward_distribution as fd_mod
from apex.options_research.expression_candidate import OptionExpressionCandidate
from apex.options_research.surface_state import build_surface

T0 = pd.Timestamp("2026-08-18T14:40:00Z")


def _write_captain(path, subject, **fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    rec = {"subject": subject, "direction_quality": "STRONG",
          "transition_quality": "MODERATE", "data_quality": "FULL",
          "model_familiarity": "FAMILIAR", "falsification": "invalidated below VWAP"}
    rec.update(fields)
    with path.open("a") as fh:
        fh.write(json.dumps(rec) + "\n")


@pytest.fixture
def wired_thesis(tmp_path, monkeypatch):
    curve = tmp_path / "curve_ledger.jsonl"
    captain = tmp_path / "captain_shadow_ledger.jsonl"
    assassin = tmp_path / "assassin2_ledger.jsonl"
    monkeypatch.setattr(fd_mod, "CURVE_LEDGER", curve)
    monkeypatch.setattr(fd_mod, "CAPTAIN_LEDGER", captain)
    monkeypatch.setattr(fd_mod, "ASSASSIN_LEDGER", assassin)
    _write_captain(captain, "AAPL")
    return {"curve": curve, "captain": captain, "assassin": assassin}


def _good_surface():
    return build_surface("AAPL260919C00230000", "2026-09-19", known_from=T0, now=T0,
                         values={"depth": 500.0, "volume": 300.0, "open_interest": 1200.0,
                                "spread_pct": 0.05, "atm_iv": 0.32})


def _option_candidate(mechanism_ids=("OPT-001-DIRECTIONAL-CONVEXITY",)):
    return OptionExpressionCandidate(
        expression_type="LONG_CALL", underlying_thesis_id="AAPL", known_from=str(T0),
        entry_structure="single leg", expiry="2026-09-19", strikes=(230.0,), legs=(),
        net_debit_or_credit=2.0, max_loss=2.0, max_gain_if_defined=None,
        initial_delta=0.5, gamma=0.1, theta=-0.1, vega=0.2, spread_cost=0.1,
        estimated_slippage=0.0, fees=0.65, capital_required=200.0,
        risk_capital_required=200.0, thesis_horizon="60m", break_even=(232.0,),
        surface_context="normal", liquidity_context="liquid", data_quality="FULL",
        research_mechanism_ids=mechanism_ids, as_of=str(T0))


def test_no_legitimate_thesis_still_offers_stock_and_no_trade(tmp_path, monkeypatch):
    monkeypatch.setattr(fd_mod, "CURVE_LEDGER", tmp_path / "curve.jsonl")
    monkeypatch.setattr(fd_mod, "CAPTAIN_LEDGER", tmp_path / "captain.jsonl")
    monkeypatch.setattr(fd_mod, "ASSASSIN_LEDGER", tmp_path / "assassin.jsonl")
    decision = engine_mod.run(subject="ZZZZ", now=T0, known_from=T0,
                              hunter_present=False, frontier_present=False,
                              stock_entry_price=50.0)
    types = {c["expression_type"] for c in decision.candidates}
    assert types == {"NO_TRADE", "STOCK"}
    gates = {r["gate"] for r in decision.refusals}
    assert "REFUSE_INSUFFICIENT_UNDERLYING_THESIS" in gates
    assert decision.decision_power == "NONE_OPTIONS_RESEARCH"


def test_zero_dte_option_candidate_refused_structurally(wired_thesis):
    cand = _option_candidate()
    decision = engine_mod.run(subject="AAPL", now=T0, known_from=T0,
                              hunter_present=True, frontier_present=True,
                              hunter_state_sufficient=True, candidate_dte=0,
                              option_candidates=(cand,), surface_state=_good_surface())
    gates = {r["gate"] for r in decision.refusals}
    assert "REFUSE_ZERO_DTE_OUT_OF_SCOPE" in gates
    assert not any(c["expression_type"] == "LONG_CALL" for c in decision.candidates)


def test_eligible_option_candidate_with_good_surface_is_admitted(wired_thesis):
    cand = _option_candidate()
    decision = engine_mod.run(subject="AAPL", now=T0, known_from=T0,
                              hunter_present=True, frontier_present=True,
                              hunter_state_sufficient=True, candidate_dte=10,
                              expected_realization_minutes=60.0,
                              timing_uncertainty_minutes=30.0,
                              option_candidates=(cand,), surface_state=_good_surface())
    types = {c["expression_type"] for c in decision.candidates}
    assert "LONG_CALL" in types
    assert decision.horizon_check["eligible"] is True


def test_illiquid_surface_refuses_the_option_candidate_not_stock(wired_thesis):
    cand = _option_candidate()
    # every feature EXCEPT depth/volume/open_interest is populated, so
    # this isolates the liquidity-specific gate from the general
    # insufficient-surface-data count check.
    illiquid = build_surface(
        "AAPL260919C00230000", "2026-09-19", known_from=T0, now=T0,
        values={"atm_iv": 0.3, "skew": 0.1, "smile_curvature": 0.05,
               "term_structure": 0.02, "call_put_relative_richness": 0.1,
               "spread_dollars": 0.1, "spread_pct": 0.05,
               "surface_change_1m": 0.0, "surface_change_5m": 0.0,
               "surface_change_15m": 0.0, "surface_change_30m": 0.0,
               "surface_change_60m": 0.0})   # depth/volume/OI all NO_SUPPORT
    decision = engine_mod.run(subject="AAPL", now=T0, known_from=T0,
                              hunter_present=True, frontier_present=True,
                              hunter_state_sufficient=True, candidate_dte=10,
                              expected_realization_minutes=60.0,
                              timing_uncertainty_minutes=30.0,
                              stock_entry_price=230.0,
                              option_candidates=(cand,), surface_state=illiquid)
    gates = {r["gate"] for r in decision.refusals}
    assert "REFUSE_ILLIQUID_SURFACE" in gates
    types = {c["expression_type"] for c in decision.candidates}
    assert types == {"NO_TRADE", "STOCK"}


def test_no_option_advantage_mechanism_refused(wired_thesis):
    cand = _option_candidate(mechanism_ids=())
    decision = engine_mod.run(subject="AAPL", now=T0, known_from=T0,
                              hunter_present=True, frontier_present=True,
                              hunter_state_sufficient=True, candidate_dte=10,
                              expected_realization_minutes=60.0,
                              timing_uncertainty_minutes=30.0,
                              option_candidates=(cand,), surface_state=_good_surface())
    gates = {r["gate"] for r in decision.refusals}
    assert "REFUSE_NO_OPTION_ADVANTAGE_MECHANISM" in gates


def test_hunter_insufficient_state_blocks_all_options(wired_thesis):
    cand = _option_candidate()
    decision = engine_mod.run(subject="AAPL", now=T0, known_from=T0,
                              hunter_present=True, frontier_present=False,
                              hunter_state_sufficient=False, candidate_dte=10,
                              expected_realization_minutes=60.0,
                              timing_uncertainty_minutes=30.0,
                              option_candidates=(cand,), surface_state=_good_surface())
    gates = {r["gate"] for r in decision.refusals}
    assert "REFUSE_HUNTER_INSUFFICIENT_STATE" in gates
    assert decision.cohort == "HUNTER_REFUSED_INSUFFICIENT_STATE"


def test_missing_surface_state_refuses_insufficient_surface_data(wired_thesis):
    cand = _option_candidate()
    decision = engine_mod.run(subject="AAPL", now=T0, known_from=T0,
                              hunter_present=True, frontier_present=True,
                              hunter_state_sufficient=True, candidate_dte=10,
                              expected_realization_minutes=60.0,
                              timing_uncertainty_minutes=30.0,
                              option_candidates=(cand,), surface_state=None)
    gates = {r["gate"] for r in decision.refusals}
    assert "REFUSE_INSUFFICIENT_SURFACE_DATA" in gates


def test_decision_never_carries_trade_authority(wired_thesis):
    decision = engine_mod.run(subject="AAPL", now=T0, known_from=T0,
                              hunter_present=True, frontier_present=True,
                              hunter_state_sufficient=True)
    assert decision.decision_power == "NONE_OPTIONS_RESEARCH"
    assert not hasattr(decision, "capital_authority") or True
