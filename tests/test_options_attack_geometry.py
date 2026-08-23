"""OPTIONS ATTACK GEOMETRY + ASSASSIN property tests (fixtures only).

Hardened 2026-08-23 after the operator caught retail folklore encoded
as structural law (DTE<14 penalty) and a hard veto resting on an
uncalibrated forecast.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from apex.predators.options.attack_geometry import (  # noqa: E402
    NOT_ESTIMABLE, RULE_CLASSIFICATION, VERDICTS, WOUND_FAMILIES,
    assassinate, assess)
from apex.predators.options.expression import (  # noqa: E402
    ExpressionCandidate)


class _UG:
    def __init__(self, eq="GOOD", chase="LOW", inval=98.0):
        self.entry_quality, self.chase_risk, self.invalidation = \
            eq, chase, inval


class _OS:
    def __init__(self, ivr=1.0, dq="FULL"):
        self.iv_over_rv, self.data_quality = ivr, dq


def _cand(expr="LONG_CALL", debit=300.0, spread=20.0, be_pct=1.5):
    return ExpressionCandidate(
        expression=expr, direction="LONG",
        legs=(("BUY", "C", 100.0, 3.0),), debit=debit, max_loss=debit,
        max_gain="UNBOUNDED", breakeven=103.0,
        breakeven_move_pct=be_pct, quoted_spread_cost=spread,
        liquidity="QUOTED", capital_required=debit)


def _stock():
    return ExpressionCandidate(
        expression="STOCK", direction="LONG",
        legs=(("BUY", "STOCK", 100.0, 100.0),), debit=10000.0,
        max_loss=None, max_gain="UNBOUNDED", breakeven=100.0,
        breakeven_move_pct=0.0, quoted_spread_cost=None,
        liquidity="UNDERLYING", capital_required=10000.0)


def _g(**kw):
    base = dict(subject="X", direction="LONG", candidate=_cand(),
                underlying_geometry=_UG(), dte=35, bid_size=50,
                ask_size=50, quote_age_s=5, spot=100.0)
    base.update(kw)
    return assess(**base)


# ------------------------------------------- RULE CLASSIFICATION LAW

def test_every_rule_is_explicitly_classified():
    for k, v in RULE_CLASSIFICATION.items():
        if k.startswith("_"):
            continue
        assert v in ("STRUCTURAL_INVALIDITY", "EXPLORATORY_QUALITY_PRIOR",
                     "LEARNED_ECONOMIC_THRESHOLD"), (k, v)


def test_no_learned_economic_threshold_is_authorized_yet():
    """Nothing may claim outcome-derived authority before evidence."""
    assert "LEARNED_ECONOMIC_THRESHOLD" not in \
        set(v for k, v in RULE_CLASSIFICATION.items()
            if not k.startswith("_"))
    assert "no LEARNED_ECONOMIC_THRESHOLD is authorized" in \
        RULE_CLASSIFICATION["_note"]


def test_numeric_quality_rules_are_priors_not_structural():
    for k in ("spread_pct_wide", "top_size_below_intended_order",
              "quote_staleness", "theta_burden_short_dte",
              "breakeven_reach_ratio"):
        assert RULE_CLASSIFICATION[k] == "EXPLORATORY_QUALITY_PRIOR"


# ------------------------------------------- DTE IS NOT BANNED

def test_short_dte_is_not_structurally_penalized():
    """THE CORRECTION: a 7-DTE contract with a clean market must remain
    attackable -- gamma/capital-efficiency battlefields are not banned
    before being studied."""
    g = _g(dte=7)
    assert g.theta_burden == "HIGH"
    assert g.execution_state == "EXECUTION_ACCEPTABLE"
    assert g.contract_quality == "GOOD"
    assert g.attackable is True, "short DTE was banned by folklore"
    assert any("NOT a ban" in r for r in g.reasoning)


def test_short_dte_wound_is_provisional_not_refusal():
    g = _g(dte=5)
    a = assassinate(geometry=g, options_state=_OS(), candidate=_cand())
    assert "THETA_BURDEN" in a.wounds
    assert WOUND_FAMILIES["THETA_BURDEN"] == "PROVISIONAL"
    assert a.verdict in ("SURVIVED_WOUNDED", "DEGRADE")
    assert a.verdict != "REFUSE"


def test_expired_contract_is_structural():
    g = _g(dte=0)
    assert g.execution_state == "EXECUTION_IMPOSSIBLE"
    a = assassinate(geometry=g, options_state=_OS(), candidate=_cand())
    assert a.verdict == "REFUSE"
    assert "EXPIRED_CONTRACT" in a.structural_wounds


# ------------------------------------------- LIQUIDITY IS RELATIVE

def test_size_is_judged_against_the_order_we_intend():
    """One contract in a liquid name is a real order for a small
    account -- no universal size floor."""
    ok = _g(bid_size=2, ask_size=2, intended_contracts=1)
    assert ok.execution_state == "EXECUTION_ACCEPTABLE"
    assert ok.attackable is True
    too_big = _g(bid_size=2, ask_size=2, intended_contracts=10)
    assert too_big.execution_state == "EXECUTION_DEGRADED"


def test_zero_size_is_structurally_unexecutable():
    g = _g(bid_size=0, ask_size=0)
    assert g.execution_state == "EXECUTION_IMPOSSIBLE"
    a = assassinate(geometry=g, options_state=_OS(), candidate=_cand())
    assert a.verdict == "REFUSE"
    assert "EXECUTION_IMPOSSIBLE" in a.structural_wounds


def test_continuous_measurements_are_preserved():
    g = _g(bid_size=7, ask_size=9, open_interest=1234, quote_age_s=3.5)
    for f in ("spread_abs", "spread_pct", "bid_size", "ask_size",
              "quote_age_s", "open_interest", "dte", "moneyness"):
        assert getattr(g, f) is not None, f
    assert g.bid_size == 7 and g.ask_size == 9
    assert g.open_interest == 1234


# ------------------------------------------- FORECAST PEDIGREE

def test_uncalibrated_breakeven_degrades_it_does_not_veto():
    g = _g(candidate=_cand(be_pct=4.0), expected_move_pct=2.0,
           forecast_pedigree="ESTIMABLE_UNCALIBRATED")
    assert g.breakeven_reach_ratio == 2.0
    assert g.contract_quality == "ACCEPTABLE"       # not POOR
    a = assassinate(geometry=g, options_state=_OS(),
                    candidate=_cand(be_pct=4.0), stock_candidate=_stock())
    assert "BREAKEVEN_CONCERN" in a.wounds
    assert "BREAKEVEN_UNREALISTIC" not in a.wounds
    assert a.verdict != "REFUSE", "immature forecast produced a hard veto"


def test_calibrated_breakeven_may_refuse():
    g = _g(candidate=_cand(be_pct=4.0), expected_move_pct=2.0,
           forecast_pedigree="CALIBRATED")
    assert g.contract_quality == "POOR" and g.attackable is False
    a = assassinate(geometry=g, options_state=_OS(),
                    candidate=_cand(be_pct=4.0), stock_candidate=_stock())
    assert a.verdict == "REFUSE"
    assert "BREAKEVEN_UNREALISTIC" in a.wounds
    assert "EXPRESSION_INFERIOR_TO_STOCK" in a.wounds


def test_not_estimable_forecast_yields_not_estimable_ratio():
    g = _g(candidate=_cand(be_pct=4.0), expected_move_pct=2.0,
           forecast_pedigree="NOT_ESTIMABLE")
    assert g.breakeven_reach_ratio == NOT_ESTIMABLE
    assert g.attackable is True        # no manufactured precision
    a = assassinate(geometry=g, options_state=_OS(), candidate=_cand())
    assert "BREAKEVEN_UNREALISTIC" not in a.wounds


def test_unknown_pedigree_is_rejected_loudly():
    with pytest.raises(ValueError):
        _g(forecast_pedigree="VIBES")


# ------------------------------------------- unchanged core laws

def test_both_dimensions_still_required():
    assert _g().attackable is True
    assert _g(underlying_geometry=_UG(eq="POOR")).attackable is False


def test_wounds_are_tagged_structural_or_provisional():
    for w, kind in WOUND_FAMILIES.items():
        assert kind in ("STRUCTURAL", "PROVISIONAL"), w


def test_assassin_still_cannot_manufacture_confidence():
    assert set(VERDICTS) == {"SURVIVED", "SURVIVED_WOUNDED", "DEGRADE",
                             "REFUSE"}
    src = Path("apex/predators/options/attack_geometry.py").read_text()
    assert "may NEVER manufacture" in src


def test_incomplete_state_still_refuses():
    a = assassinate(geometry=_g(), options_state=_OS(dq="PARTIAL"),
                    candidate=_cand())
    assert a.verdict == "REFUSE"
    assert "INSUFFICIENT_EVIDENCE" in a.structural_wounds


def test_clean_setup_survives():
    g = _g(dte=45, bid_size=100, ask_size=100, quote_age_s=2,
           expected_move_pct=5.0, forecast_pedigree="CALIBRATED")
    a = assassinate(geometry=g, options_state=_OS(),
                    candidate=_cand(), stock_candidate=_stock())
    assert a.verdict == "SURVIVED" and a.wounds == ()
