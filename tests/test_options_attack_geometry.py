"""OPTIONS ATTACK GEOMETRY + ASSASSIN property tests (fixtures only)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from apex.predators.options.attack_geometry import (  # noqa: E402
    MIN_TOP_SIZE, NOT_ESTIMABLE, VERDICTS, WOUND_FAMILIES, assassinate,
    assess)
from apex.predators.options.expression import (  # noqa: E402
    ExpressionCandidate)


class _UG:               # stand-in for the equity geometry result
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


# ------------------------------------------------ both dimensions

def test_both_dimensions_required_for_attackable():
    good = assess(subject="X", direction="LONG", candidate=_cand(),
                  underlying_geometry=_UG(), dte=35, top_size=50,
                  quote_age_s=5, spot=100.0, expected_move_pct=3.0)
    assert good.attackable is True
    # perfect contract, bad location
    bad_loc = assess(subject="X", direction="LONG", candidate=_cand(),
                     underlying_geometry=_UG(eq="POOR"), dte=35,
                     top_size=50, quote_age_s=5, spot=100.0,
                     expected_move_pct=3.0)
    assert bad_loc.attackable is False
    assert any("regardless of the contract" in r
               for r in bad_loc.reasoning)
    # perfect location, unfillable contract
    bad_con = assess(subject="X", direction="LONG",
                     candidate=_cand(spread=200.0),
                     underlying_geometry=_UG(), dte=35, top_size=50,
                     quote_age_s=5, spot=100.0, expected_move_pct=3.0)
    assert bad_con.attackable is False


def test_breakeven_beyond_expected_move_kills_it():
    """The signature options failure: right direction, wrong weapon."""
    g = assess(subject="X", direction="LONG",
               candidate=_cand(be_pct=4.0),      # needs +4%
               underlying_geometry=_UG(), dte=35, top_size=50,
               quote_age_s=5, spot=100.0,
               expected_move_pct=2.0)            # expect only +2%
    assert g.breakeven_reach_ratio == 2.0
    assert g.contract_quality == "POOR"
    assert g.attackable is False
    a = assassinate(geometry=g, options_state=_OS(),
                    candidate=_cand(be_pct=4.0), stock_candidate=_stock())
    assert a.verdict == "REFUSE"
    assert "BREAKEVEN_UNREALISTIC" in a.wounds
    assert "DIRECTION_RIGHT_OPTION_WRONG" in a.wounds
    assert "EXPRESSION_INFERIOR_TO_STOCK" in a.wounds


def test_unfillable_size_is_not_a_quote():
    g = assess(subject="X", direction="LONG", candidate=_cand(),
               underlying_geometry=_UG(), dte=35,
               top_size=MIN_TOP_SIZE - 1, quote_age_s=5, spot=100.0)
    assert g.contract_quality == "POOR"
    assert any("cannot fill" in r for r in g.reasoning)


def test_stale_quote_yields_unknown_not_optimism():
    g = assess(subject="X", direction="LONG", candidate=_cand(),
               underlying_geometry=_UG(), dte=35, top_size=50,
               quote_age_s=600, spot=100.0)
    assert g.contract_quality == "UNKNOWN"
    assert g.attackable is False


def test_stock_expression_has_no_contract_friction():
    g = assess(subject="X", direction="LONG", candidate=_stock(),
               underlying_geometry=_UG(), spot=100.0)
    assert g.contract_quality == "GOOD"
    assert g.attackable is True


def test_short_dte_flags_theta_burden():
    g = assess(subject="X", direction="LONG", candidate=_cand(),
               underlying_geometry=_UG(), dte=18, top_size=50,
               quote_age_s=5, spot=100.0)
    assert g.theta_burden == "HIGH"
    assert g.contract_quality == "ACCEPTABLE"


# ------------------------------------------------ assassin

def test_iv_crush_wound_only_when_paying_premium():
    g = assess(subject="X", direction="LONG", candidate=_cand(),
               underlying_geometry=_UG(), dte=35, top_size=50,
               quote_age_s=5, spot=100.0)
    hot = assassinate(geometry=g, options_state=_OS(ivr=2.0),
                      candidate=_cand())
    assert "IV_CRUSH_RISK" in hot.wounds
    calm = assassinate(geometry=g, options_state=_OS(ivr=1.0),
                       candidate=_cand())
    assert "IV_CRUSH_RISK" not in calm.wounds
    # buying stock cannot suffer an IV crush
    st = assassinate(geometry=g, options_state=_OS(ivr=2.0),
                     candidate=_stock())
    assert "IV_CRUSH_RISK" not in st.wounds


def test_incomplete_state_refuses_rather_than_assumes():
    g = assess(subject="X", direction="LONG", candidate=_cand(),
               underlying_geometry=_UG(), dte=35, top_size=50,
               quote_age_s=5, spot=100.0)
    a = assassinate(geometry=g, options_state=_OS(dq="PARTIAL"),
                    candidate=_cand())
    assert a.verdict == "REFUSE"
    assert "INSUFFICIENT_EVIDENCE" in a.wounds
    assert any("absence of a reason to refuse is not a reason to "
               "attack" in r for r in a.reasoning)


def test_clean_setup_survives():
    g = assess(subject="X", direction="LONG", candidate=_cand(),
               underlying_geometry=_UG(), dte=45, top_size=100,
               quote_age_s=2, spot=100.0, expected_move_pct=5.0)
    a = assassinate(geometry=g, options_state=_OS(ivr=1.0),
                    candidate=_cand(), stock_candidate=_stock())
    assert a.verdict == "SURVIVED"
    assert a.wounds == ()


def test_assassin_cannot_manufacture_confidence():
    """Its vocabulary contains no promoting verdict."""
    assert set(VERDICTS) == {"SURVIVED", "SURVIVED_WOUNDED", "DEGRADE",
                             "REFUSE"}
    for v in VERDICTS:
        assert "STRONG" not in v and "ATTACK" not in v
    src = Path("apex/predators/options/attack_geometry.py").read_text()
    assert "may NEVER manufacture" in src


def test_wound_vocabulary_covers_the_named_failure_modes():
    for w in ("DIRECTION_RIGHT_OPTION_WRONG", "IV_CRUSH_RISK",
              "THETA_BURDEN", "BAD_DTE", "SPREAD_TOO_EXPENSIVE",
              "BREAKEVEN_UNREALISTIC", "EXPRESSION_INFERIOR_TO_STOCK",
              "INSUFFICIENT_EVIDENCE"):
        assert w in WOUND_FAMILIES


def test_thresholds_are_predeclared_not_fitted():
    src = Path("apex/predators/options/attack_geometry.py").read_text()
    assert "before any outcome was inspected" in src
    assert "structural, not fitted" in src
