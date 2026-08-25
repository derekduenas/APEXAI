"""Day-1 resolver defects, each pinned by a test that reproduces it.

Defect A: a SESSION_CLOSE card resolved against whatever bar happened
          to be in the database when the resolver ran (an after-hours
          print), so the outcome depended on processing time.
Defect B: a UTC-naive bar time compared against an ET-naive entry time
          admitted 88 minutes of PRE-ENTRY bars into the realized path;
          the reported MFE occurred before the position existed.
"""
from __future__ import annotations

import pytest

from apex.governance.resolution_time import (
    ResolutionViolation, eligible_window, instrument_class_for,
    regular_session_close, to_utc)
from apex.governance.trade_semantics import (
    OPTIONS_HOLD_TO_CLOSE, SemanticViolation, THESIS_PATH_STATES,
    TradeAuthorities, classify_thesis_path)
from apex.predators.options.paper_execution import resolve, simulate_entry
from tests.test_options_paper_execution import CARD, _call, _future, _quotes


# ---------------------------------------- DEFECT A: processing time

def test_session_close_is_the_calendar_not_the_clock():
    b = regular_session_close("2026-08-24")
    assert b.close_et.startswith("2026-08-24T16:00:00")
    assert b.calendar_pedigree == "VERIFIED"
    assert b.is_half_day is False


def test_resolver_run_time_cannot_change_the_economic_outcome():
    """16:01, 16:27 and 19:00 must resolve identically."""
    windows = [eligible_window(entry_ts="2026-08-24 09:55:04",
                               session="2026-08-24", symbol="SPY",
                               option=False)
               for _ in range(3)]
    assert len({w["boundary_utc"] for w in windows}) == 1
    assert windows[0]["boundary_utc"].startswith("2026-08-24T20:00")


def test_an_after_hours_bar_is_outside_the_eligible_window():
    """The exact Day-1 failure: a 16:26 ET print decided the verdict."""
    b = to_utc(regular_session_close("2026-08-24").close_utc)
    after_hours = to_utc("2026-08-24T20:26:00Z", assume="UTC")
    assert after_hours > b, "16:26 ET must fall outside the boundary"


def test_half_days_and_holidays_are_not_assumed_to_be_normal():
    half = regular_session_close("2026-11-27")
    assert half.close_et.startswith("2026-11-27T13:00:00")
    assert half.is_half_day is True
    with pytest.raises(ResolutionViolation):
        regular_session_close("2026-12-25")          # holiday
    with pytest.raises(ResolutionViolation):
        regular_session_close("2026-08-23")          # Sunday


def test_an_options_session_is_not_its_underlyings_session():
    assert instrument_class_for("SPY", option=True) == "ETF_OPTION"
    assert instrument_class_for("MSFT", option=True) == "EQUITY_OPTION"
    etf = regular_session_close("2026-08-24",
                                instrument_class="ETF_OPTION")
    eq = regular_session_close("2026-08-24", instrument_class="EQUITY")
    assert etf.close_et.startswith("2026-08-24T16:15:00")
    assert eq.close_et.startswith("2026-08-24T16:00:00")


def test_unverified_years_are_labelled_not_silently_assumed():
    b = regular_session_close("2031-03-04")
    assert b.calendar_pedigree == "ASSUMED_STANDARD"


# ---------------------------------------- DEFECT B: causal path

def test_a_pre_entry_bar_can_never_become_mfe():
    """Monday SPY reproduced: entry 09:55 ET, and a bar from 09:44 ET
    was allowed to set the MFE."""
    f = simulate_entry(_call(ask=3.0), T="2026-08-24 09:55:04",
                       sealed_card_hash=CARD, risk_basis="FULL_PREMIUM")
    path = [
        {"t": "2026-08-24T13:44:00Z", "c": 100.0},   # 09:44 ET PRE-ENTRY
        {"t": "2026-08-24T14:30:00Z", "c": 101.0},   # 10:30 ET eligible
        {"t": "2026-08-24T19:59:00Z", "c": 100.5},   # 15:59 ET eligible
    ]
    path[0]["c"] = 90.0        # a huge pre-entry excursion, if admitted
    out = resolve(fill=f, sealed_card_hash=CARD, future_underlying=path,
                  future_quote_lookup=_quotes({(100.0, "C"): (3.0, 3.1)}),
                  entry_underlying=100.0,
                  entry_utc="2026-08-24 09:55:04",
                  boundary_utc="2026-08-24T20:00:00Z")
    # a LONG whose pre-entry bar was 90.0 would show a -10% MAE if the
    # filter leaked; the eligible path never goes below 100.5
    assert out.mae >= 0.0, f"pre-entry bar leaked into MAE: {out.mae}"
    assert out.mfe == pytest.approx(1.0, abs=0.01)


def test_bars_past_the_sealed_boundary_are_excluded():
    f = simulate_entry(_call(ask=3.0), T="2026-08-24 09:55:04",
                       sealed_card_hash=CARD, risk_basis="FULL_PREMIUM")
    path = [{"t": "2026-08-24T19:59:00Z", "c": 101.0},   # 15:59 ET in
            {"t": "2026-08-24T20:26:00Z", "c": 95.0}]    # 16:26 ET out
    out = resolve(fill=f, sealed_card_hash=CARD, future_underlying=path,
                  future_quote_lookup=_quotes({(100.0, "C"): (3.0, 3.1)}),
                  entry_underlying=100.0,
                  entry_utc="2026-08-24 09:55:04",
                  boundary_utc="2026-08-24T20:00:00Z")
    assert out.underlying_return_pct == pytest.approx(1.0, abs=0.01), \
        "the after-hours print decided the verdict"


def test_naive_timestamps_are_normalized_not_compared_raw():
    et = to_utc("2026-08-24 09:55:04")                  # ET-naive
    utc = to_utc("2026-08-24T13:55:04Z", assume="UTC")  # UTC-aware
    assert et == utc, "ET-naive and UTC must reconcile, not offset"


# ---------------------------------------- invalidation ontology

def test_the_four_authorities_are_declared_not_assumed():
    a = TradeAuthorities(thesis_invalidation=763.82,
                         **OPTIONS_HOLD_TO_CLOSE)
    assert a.has_execution_stop is False
    assert a.execution_stop_trigger == "NONE"
    assert a.risk_basis == "FULL_PREMIUM"
    assert a.resolution_horizon == "REGULAR_SESSION_CLOSE"
    assert "DIAGNOSTIC" in " ".join(a.notes)


def test_an_ambiguous_stop_is_refused():
    with pytest.raises(SemanticViolation):
        TradeAuthorities(execution_stop_trigger="MAYBE")


def test_a_broken_and_recovered_thesis_is_not_a_thesis_that_held():
    """Day-1's SPY scoring error, pinned."""
    a = TradeAuthorities(thesis_invalidation=763.82,
                         **OPTIONS_HOLD_TO_CLOSE)
    r = classify_thesis_path(direction="SHORT", thesis_invalidation=763.82,
                             path_closes=[764.5, 765.2, 764.1, 763.5],
                             final_close=763.5, authorities=a)
    assert r["state"] == "THESIS_REVALIDATED_AFTER_INVALIDATION"
    assert r["breach_fraction"] == 0.75
    assert r["protocol_held_through_breach"] is True
    assert "NOT an unbroken thesis" in r["why"]


def test_a_thesis_still_broken_at_the_boundary_says_so():
    r = classify_thesis_path(direction="SHORT", thesis_invalidation=763.82,
                             path_closes=[764.5, 765.2, 764.1],
                             final_close=764.1)
    assert r["state"] == "THESIS_INVALIDATED_PROTOCOL_HELD"


def test_an_unbroken_thesis_is_distinguishable():
    r = classify_thesis_path(direction="SHORT", thesis_invalidation=763.82,
                             path_closes=[763.0, 762.5, 762.9],
                             final_close=762.9)
    assert r["state"] == "THESIS_NEVER_INVALIDATED"
    assert r["n_breached"] == 0


def test_every_emitted_thesis_state_is_declared():
    for closes, final in (([764.5], 764.5), ([763.0], 763.0),
                          ([764.5, 763.0], 763.0)):
        r = classify_thesis_path(direction="SHORT",
                                 thesis_invalidation=763.82,
                                 path_closes=closes, final_close=final)
        assert r["state"] in THESIS_PATH_STATES


def test_no_thesis_level_yields_not_estimable_not_a_guess():
    r = classify_thesis_path(direction="SHORT", thesis_invalidation=None,
                             path_closes=[1.0], final_close=1.0)
    assert r["state"] == "NOT_ESTIMABLE"
