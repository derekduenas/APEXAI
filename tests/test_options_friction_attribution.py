"""Friction attribution: does the diagnosis distinguish the four
failures that demand different repairs?"""
from __future__ import annotations

from dataclasses import dataclass

from apex.predators.options.friction_attribution import (
    CLASSES, attribute, summarize)

NE = "NOT_ESTIMABLE"


@dataclass
class FakeOutcome:
    expression: str = "LONG_CALL"
    pnl: float | str = 0.0
    mid_change: float | str = 0.0
    exit_friction: float | str = 0.0
    underlying_return_pct: float | str = 0.0
    r_multiple: float | str = 0.0
    mfe: float | str = 0.0
    mae: float | str = 0.0
    iv_change: float | str = NE
    friction_identity_holds: bool | str = True


@dataclass
class FakeCandidate:
    quoted_spread_cost: float | None = None
    debit: float | None = None


# ------------------------------------------------ the four diagnoses

def test_thesis_right_friction_killed_is_named_explicitly():
    """The headline finding of the replay: right on mid, lost anyway."""
    a = attribute(outcome=FakeOutcome(
        pnl=-212.0, mid_change=251.0, exit_friction=300.0,
        underlying_return_pct=-1.4, expression="PUT_VERTICAL"))
    assert a.primary_class == "THESIS_RIGHT_FRICTION_KILLED"
    assert a.total_friction == 463.0        # 251 - (-212)
    assert a.entry_friction == 163.0        # 251 - 300 - (-212)
    assert a.friction_verdict == "FRICTION_DOMINANT"
    assert "the spread took all of it" in " ".join(a.reasoning)


def test_thesis_right_friction_survived_is_the_only_proof_of_edge():
    a = attribute(outcome=FakeOutcome(
        pnl=180.0, mid_change=260.0, exit_friction=40.0,
        underlying_return_pct=2.0))
    assert a.primary_class == "THESIS_RIGHT_FRICTION_SURVIVED"
    assert a.friction_verdict == "FRICTION_MINOR"
    assert "cleared its own execution cost" in " ".join(a.reasoning)


def test_thesis_wrong_is_not_blamed_on_the_spread():
    a = attribute(outcome=FakeOutcome(
        pnl=-300.0, mid_change=-280.0, exit_friction=20.0,
        underlying_return_pct=-2.5, expression="LONG_CALL"))
    assert a.primary_class == "THESIS_WRONG"
    assert "no execution improvement would have saved this" in \
        " ".join(a.reasoning)


def test_right_underlying_wrong_instrument_is_its_own_diagnosis():
    """Underlying went the right way; the option still lost on mid."""
    a = attribute(outcome=FakeOutcome(
        pnl=-90.0, mid_change=-70.0, exit_friction=20.0,
        underlying_return_pct=1.2, expression="LONG_CALL"))
    assert a.primary_class == "THESIS_RIGHT_OPTION_LOST"
    assert "BAD_EXPRESSION" in a.contributing
    assert "the instrument was wrong" in " ".join(a.reasoning)


def test_no_executable_round_trip_is_execution_failure_not_zero_pnl():
    a = attribute(outcome=FakeOutcome(pnl=NE, mid_change=NE,
                                      exit_friction=NE))
    assert a.primary_class == "EXECUTION_FAILURE"
    assert "absence of a tradeable market" in " ".join(a.notes)
    assert a.executable_pnl == NE


# ------------------------------------------------ contributing causes

def test_iv_crush_is_contributing_never_the_headline():
    a = attribute(outcome=FakeOutcome(
        pnl=-150.0, mid_change=-140.0, exit_friction=10.0,
        underlying_return_pct=-1.0, iv_change=-0.05))
    assert "IV_CRUSH" in a.contributing
    assert a.primary_class == "THESIS_WRONG"


def test_theta_burden_is_contributing_and_not_treated_as_fatal():
    a = attribute(outcome=FakeOutcome(
        pnl=120.0, mid_change=160.0, exit_friction=40.0,
        underlying_return_pct=1.5), dte_at_entry=5.0)
    assert "THETA_BURDEN" in a.contributing
    assert a.primary_class == "THESIS_RIGHT_FRICTION_SURVIVED", \
        "a short-dated winner must still be allowed to be a winner"


def test_bad_entry_flags_a_spread_that_started_underwater():
    a = attribute(
        outcome=FakeOutcome(pnl=-100.0, mid_change=-80.0,
                            exit_friction=20.0,
                            underlying_return_pct=-1.0),
        candidate=FakeCandidate(quoted_spread_cost=60.0, debit=200.0))
    assert "BAD_ENTRY" in a.contributing


def test_a_tight_entry_is_not_flagged():
    a = attribute(
        outcome=FakeOutcome(pnl=-100.0, mid_change=-80.0,
                            exit_friction=20.0,
                            underlying_return_pct=-1.0),
        candidate=FakeCandidate(quoted_spread_cost=10.0, debit=200.0))
    assert "BAD_ENTRY" not in a.contributing


def test_every_emitted_class_is_declared():
    outs = [
        FakeOutcome(pnl=-212.0, mid_change=251.0, exit_friction=300.0),
        FakeOutcome(pnl=180.0, mid_change=260.0, exit_friction=40.0),
        FakeOutcome(pnl=-300.0, mid_change=-280.0, exit_friction=20.0,
                    underlying_return_pct=-2.5),
        FakeOutcome(pnl=NE, mid_change=NE, exit_friction=NE),
    ]
    for o in outs:
        assert attribute(outcome=o).primary_class in CLASSES


# ------------------------------------------------ the session roll-up

def test_summary_headline_points_at_execution_when_friction_dominates():
    atts = [attribute(outcome=FakeOutcome(
        pnl=-50.0, mid_change=120.0, exit_friction=90.0,
        underlying_return_pct=1.0)) for _ in range(7)]
    atts += [attribute(outcome=FakeOutcome(
        pnl=90.0, mid_change=140.0, exit_friction=25.0,
        underlying_return_pct=1.0)) for _ in range(3)]
    s = summarize(atts)
    assert s["right_on_mid"] == 10
    assert s["friction_killed"] == 7
    assert s["friction_survived"] == 3
    assert s["friction_kill_rate"] == 0.7
    assert "right on mid and lost to the round trip" in s["headline"]
    assert "the repair is EXECUTION" in s["law"]


def test_summary_is_honest_when_nothing_gained_on_mid():
    atts = [attribute(outcome=FakeOutcome(
        pnl=-40.0, mid_change=-30.0, exit_friction=10.0,
        underlying_return_pct=-1.0)) for _ in range(4)]
    s = summarize(atts)
    assert s["right_on_mid"] == 0
    assert s["friction_kill_rate"] == NE
    assert "no attack gained on mid" in s["headline"]


def test_summary_only_totals_what_it_could_decompose():
    atts = [attribute(outcome=FakeOutcome(pnl=NE, mid_change=NE,
                                          exit_friction=NE)),
            attribute(outcome=FakeOutcome(pnl=100.0, mid_change=150.0,
                                          exit_friction=30.0,
                                          underlying_return_pct=1.0))]
    s = summarize(atts)
    assert s["n"] == 2 and s["n_decomposed"] == 1
    assert s["mid_pnl"] == 150.0
