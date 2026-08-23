"""The prospective scoreboard: does it keep the Predator honest about
what it refused and how big its sample really is?"""
from __future__ import annotations

import pytest

from apex.predators.options.friction_attribution import attribute
from apex.predators.options.scoreboard import (
    PIPELINE_STAGES, SessionScoreboard, combine)
from tests.test_options_friction_attribution import FakeOutcome


def _sb():
    return SessionScoreboard(session="2026-08-24")


def test_refusals_are_counted_as_evidence_not_discarded():
    sb = _sb()
    for _ in range(12):
        sb.stage("CANDIDATE")
    sb.stop("NO_DIRECTIONAL_THESIS")
    sb.stop("NO_DIRECTIONAL_THESIS")
    sb.stop("GEOMETRY_REFUSED")
    sb.stop("NO_TRADE")
    r = sb.report()
    assert r["refusals_total"] == 4
    assert r["stops"]["NO_DIRECTIONAL_THESIS"] == 2
    assert "refusals are evidence" in r["refusal_law"]


def test_no_trade_is_a_legitimate_recorded_outcome():
    sb = _sb()
    sb.stop("NO_TRADE")
    assert sb.report()["stops"]["NO_TRADE"] == 1


def test_unknown_stage_or_stop_is_refused_not_silently_absorbed():
    sb = _sb()
    with pytest.raises(ValueError):
        sb.stage("PROBABLY_GOOD")
    with pytest.raises(ValueError):
        sb.stop("FELT_WRONG")


def test_many_attacks_in_one_session_are_not_many_samples():
    sb = _sb()
    for i in range(6):
        sb.attack(symbol="SPY", T=f"2026-08-24T1{i}:00",
                  expression="LONG_CALL")
    r = sb.report()
    assert r["attacks_raw"] == 6
    assert r["attacks_effective_lower_bound"] == 1, \
        "six attacks on one symbol-day is one symbol-day"
    assert "is NOT the sample size" in r["sample_law"]


def test_effective_count_grows_with_distinct_symbols():
    sb = _sb()
    for sym in ("SPY", "QQQ", "NVDA"):
        sb.attack(symbol=sym, T="2026-08-24T10:00", expression="LONG_PUT")
    assert sb.report()["attacks_effective_lower_bound"] == 3


def test_near_misses_isolate_the_single_blocking_gate():
    sb = _sb()
    sb.near_miss(symbol="AAPL", T="2026-08-24T10:00",
                 missing="EXECUTION_DEGRADED")
    r = sb.report()
    assert r["near_misses"] == 1
    assert r["near_miss_detail"][0]["blocked_by"] == "EXECUTION_DEGRADED"


def test_thesis_right_versus_profitable_is_surfaced():
    """The comparison that decides whether to fix forecasting or
    execution."""
    sb = _sb()
    killed = attribute(outcome=FakeOutcome(
        pnl=-40.0, mid_change=120.0, exit_friction=90.0,
        underlying_return_pct=1.0))
    won = attribute(outcome=FakeOutcome(
        pnl=95.0, mid_change=140.0, exit_friction=25.0,
        underlying_return_pct=1.0))
    sb.attack(symbol="SPY", T="t1", expression="LONG_CALL",
              attribution=killed)
    sb.attack(symbol="QQQ", T="t2", expression="LONG_CALL",
              attribution=won)
    r = sb.report()
    assert r["thesis_right"] == 2
    assert r["profitable"] == 1
    assert r["right_but_unprofitable"] == 1
    assert r["friction"]["friction_killed"] == 1


def test_a_session_with_no_attacks_reports_honestly():
    r = _sb().report()
    assert r["attacks_raw"] == 0
    assert r["friction"]["headline"] == "no attacks resolved"


def test_every_pipeline_stage_appears_even_at_zero():
    r = _sb().report()
    for s in PIPELINE_STAGES:
        assert s in r["pipeline"]


def test_campaign_rollup_preserves_the_effective_count():
    a, b = _sb(), SessionScoreboard(session="2026-08-25")
    for i in range(4):
        a.attack(symbol="SPY", T=f"t{i}", expression="LONG_CALL")
    b.attack(symbol="SPY", T="t0", expression="LONG_PUT")
    b.stop("NO_TRADE")
    c = combine([a.report(), b.report()])
    assert c["sessions"] == 2
    assert c["attacks_raw"] == 5
    assert c["attacks_effective_lower_bound"] == 2
    assert c["stops"]["NO_TRADE"] == 1
    assert "does not become PAPER_AUTHORIZED by growing" in c["law"]


def test_scoreboard_is_stamped_prospective_and_powerless():
    r = _sb().report()
    assert r["evidence_class"] == "PROSPECTIVE_PAPER"
    assert r["decision_power"] == "NONE"
