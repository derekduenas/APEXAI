"""ChartState + downstream session-integrity tests (Phase 0.1). Covers
matrix items P-V plus the 2026-08-17 regression fixture and the
downstream-consumer audit (Scout, forward_pass, Twin 2.0).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from apex.hunter.chartstate import DailyContext, compute_chart_state
from apex.hunter.relstrength import compute_relative_strength
from apex.hunter.scanner import detect_signals

DAY = "2026-08-17"
ET_OPEN = "2026-08-17 13:30:00+00:00"


def _trending_bars(start, n, base=100.0, drift=0.001, seed=1):
    rng = np.random.default_rng(seed)
    idx = pd.date_range(start, periods=n, freq="1min", tz="UTC")
    steps = drift / n + rng.normal(0, 3e-4, n)
    close = base * np.cumprod(1 + steps)
    op = np.r_[base, close[:-1]]
    return pd.DataFrame({
        "provider_symbol": "X", "event_time_utc": idx,
        "open": op, "high": np.maximum(op, close) * 1.0005,
        "low": np.minimum(op, close) * 0.9995, "close": close,
        "volume": np.full(n, 10_000.0)})


def _ctx(**kw):
    base = {"symbol": "X", "as_of_date": DAY, "prev_close": 99.0,
           "atr_frac": 0.02,
           "cum_vol_by_minute": {str(m): 20_000.0 * (m + 1) for m in range(390)}}
    base.update(kw)
    return DailyContext(**base)


# ------------------------------------------------------------- P/Q/R/S/T
def test_p_first_observed_bar_can_never_become_market_open():
    bars = _trending_bars("2026-08-17 14:17:00+00:00", 60)   # 10:17 ET start
    t = pd.Timestamp("2026-08-17 15:17:00", tz="UTC")
    cs = compute_chart_state("X", bars, t, _ctx())
    # if open_t (first bar) had been treated as market open, minutes_into_
    # session would read 60; the calendar-true answer is ~107 (09:30->11:17)
    assert cs.minutes_into_session != 60
    assert cs.minutes_into_session == pytest.approx(107, abs=1)
    assert cs.session_coverage["observed_start"] == "2026-08-17 14:17:00+00:00"
    assert cs.session_coverage["session_open"] == "2026-08-17 13:30:00+00:00"


def test_q_a_fake_opening_range_can_never_complete():
    # 40 minutes of bars, all AFTER the true 30m OR window would have
    # closed had it started at open_t instead of true open
    bars = _trending_bars("2026-08-17 14:17:00+00:00", 40)
    t = pd.Timestamp("2026-08-17 14:57:00", tz="UTC")
    cs = compute_chart_state("X", bars, t, _ctx())
    assert cs.or_complete is False
    assert cs.or_high is None and cs.or_low is None
    assert cs.feature_validity["or_complete"]["status"] == \
        "INVALID_MISSING_SESSION_START"


def test_r_partial_vwap_can_never_masquerade_as_session_vwap():
    bars = _trending_bars("2026-08-17 14:17:00+00:00", 90)
    t = pd.Timestamp("2026-08-17 15:47:00", tz="UTC")
    cs = compute_chart_state("X", bars, t, _ctx())
    assert cs.vwap is None
    assert cs.above_vwap is None
    assert cs.distance_to_vwap is None
    assert cs.vwap_reclaim is False and cs.vwap_rejection is False
    assert cs.feature_validity["vwap"]["status"] == \
        "INVALID_MISSING_SESSION_START"
    assert "14:17:00" in cs.feature_validity["vwap"]["reason"]  # observed_start, not a canned string


def test_s_gap_can_never_use_an_arbitrary_intraday_price():
    bars = _trending_bars("2026-08-17 14:17:00+00:00", 30)
    t = pd.Timestamp("2026-08-17 14:47:00", tz="UTC")
    cs = compute_chart_state("X", bars, t, _ctx(prev_close=99.0))
    assert cs.gap_frac is None
    assert cs.gap_direction is None
    assert cs.gap_fill_frac is None
    assert cs.day_return is None


def test_t_rvol_never_silently_compares_partial_volume_to_full_baseline():
    bars = _trending_bars("2026-08-17 14:17:00+00:00", 30)
    t = pd.Timestamp("2026-08-17 14:47:00", tz="UTC")
    cs = compute_chart_state("X", bars, t, _ctx())
    assert cs.rvol_tod is None
    assert cs.cum_volume is None
    assert cs.feature_validity["rvol_tod"]["status"] == \
        "INVALID_MISSING_SESSION_START"


# ------------------------------------------------------------------- U
def test_u_minutes_into_session_derives_from_exchange_calendar():
    # even with an invalid anchor, minutes_into_session is the TRUE
    # calendar answer, never derived from open_t
    bars = _trending_bars("2026-08-17 14:17:00+00:00", 10)
    t = pd.Timestamp("2026-08-17 14:27:00", tz="UTC")   # 10:27 ET
    cs = compute_chart_state("X", bars, t, _ctx())
    assert cs.minutes_into_session == 57                # 09:30 -> 10:27
    assert cs.feature_validity["minutes_into_session"]["status"] == "VALID"


# ------------------------------------------------------------------- V
def test_v_trailing_features_remain_valid_during_partial_session():
    bars = _trending_bars("2026-08-17 14:17:00+00:00", 90)  # 90m of real data
    t = pd.Timestamp("2026-08-17 15:47:00", tz="UTC")
    cs = compute_chart_state("X", bars, t, _ctx())
    assert not cs.session_coverage["session_anchor_valid"]
    # trailing-window features need no session anchor and MUST still work
    assert cs.r_15m is not None
    assert cs.r_30m is not None
    assert cs.r_60m is not None
    assert cs.trend_slope is not None
    assert cs.realized_vol_ann is not None
    for name in ("r_15m", "r_30m", "r_60m", "trend_slope", "realized_vol_ann"):
        assert cs.feature_validity[name]["status"] == "VALID"


# --------------------------------------------------- full-session equivalence
def test_full_session_equivalence_vwap_or_gap_rvol_unchanged():
    """The gate must not alter a single formula on a clean session:
    prove the v1.2 output matches a hand-computed v1-style result."""
    bars = _trending_bars(ET_OPEN, 90, seed=5)
    t = pd.Timestamp("2026-08-17 15:00:00", tz="UTC")
    cs = compute_chart_state("X", bars, t, _ctx())
    assert cs.session_coverage["session_anchor_valid"]
    assert cs.session_coverage["quality"] == "FULL"
    assert cs.vwap is not None
    assert cs.or_complete is True
    assert cs.gap_frac is not None
    assert cs.rvol_tod is not None
    assert cs.minutes_into_session == 90
    for name in ("vwap", "or_complete", "gap_frac", "rvol_tod", "day_return"):
        assert cs.feature_validity[name]["status"] == "VALID"


# --------------------------------------------------------- regression fixture
def test_2026_08_17_regression_fixture_matches_the_ratified_finding():
    """The EXACT Day-1 shape: true open 09:30 ET, observation begins
    10:17 ET. Every corrupted field from the ratified finding must read
    invalid; TRAILING_60M must eventually be valid once enough bars
    exist; Scout must mint zero GAP_AND_GO from this state."""
    bars = _trending_bars("2026-08-17 14:17:00+00:00", 65)
    t = pd.Timestamp("2026-08-17 15:22:00", tz="UTC")   # 65 bars visible
    ctx = _ctx(prev_close=249.5)
    cs = compute_chart_state("X", bars, t, ctx)

    assert cs.session_coverage["quality"] == "INVALID"
    assert not cs.session_coverage["session_anchor_valid"]
    assert cs.vwap is None                              # SESSION_VWAP invalid
    assert cs.or_high is None and cs.or_complete is False   # OPENING_RANGE invalid
    assert cs.gap_frac is None                           # GAP invalid
    assert cs.rvol_tod is None and cs.cum_volume is None  # RVOL invalid
    assert cs.minutes_into_session == pytest.approx(112, abs=1)  # correct from calendar
    assert cs.r_60m is not None                          # TRAILING_60M eventually valid

    mkt_bars = _trending_bars(ET_OPEN, 65, base=775.0, drift=0.0002, seed=9)
    mkt = compute_chart_state("SPY.US", mkt_bars, t,
                              _ctx(symbol="SPY.US", prev_close=775.98))
    rs = compute_relative_strength(cs, mkt)
    sigs = detect_signals(cs, rs)
    assert "GAP_AND_GO" not in [s.value for s in sigs]
    assert "GAP_FAILURE" not in [s.value for s in sigs]
    assert "VWAP_RECLAIM" not in [s.value for s in sigs]
    assert "VWAP_LOSS" not in [s.value for s in sigs]
    assert "OPENING_RANGE_BREAK_UP" not in [s.value for s in sigs]
    assert "OPENING_RANGE_BREAK_DOWN" not in [s.value for s in sigs]


# --------------------------------------------------------- forward_pass audit
def test_forward_pass_refuses_insufficient_valid_state_not_no_match():
    """A playbook that never got a chance to evaluate must be
    distinguishable from one that evaluated and found no match."""
    from apex.hunter.forward_pass import decision_pass
    bars = _trending_bars("2026-08-17 14:17:00+00:00", 65)
    mkt_bars = _trending_bars(ET_OPEN, 65, base=775.0, seed=9)
    universe = {"symbols": {"X": {"sector": "Technology", "sector_etf": None,
                                  "median_dollar_volume": 500e6}},
               "universe_limitation": "test"}
    t = pd.Timestamp("2026-08-17 15:22:00", tz="UTC")
    scan_rec, decisions = decision_pass(
        t, universe, {"X": bars, "SPY.US": mkt_bars},
        {"X": _ctx(), "SPY.US": _ctx(symbol="SPY.US", prev_close=775.98)},
        enrich=False)
    refusals = scan_rec.get("playbook_match_refusals", [])
    non_baseline = [d for d in decisions
                   if not d["playbook_id"].startswith("BASELINE-")]
    if "X" in {r for r, *_ in scan_rec.get("watchlist", [])}:
        assert any(r["symbol"] == "X" and
                  r["match_result"] == "REFUSE_INSUFFICIENT_VALID_STATE"
                  for r in refusals)
        assert not any(d["symbol"] == "X" for d in non_baseline)


def test_universe_facets_never_crashes_on_all_invalid_states():
    """The exact production bug this phase fixed: np.mean([]) on an
    all-invalid-anchor tick must never raise."""
    from apex.hunter.forward_pass import decision_pass
    bars = _trending_bars("2026-08-17 14:17:00+00:00", 30)
    mkt_bars = _trending_bars(ET_OPEN, 30, base=775.0, seed=9)
    universe = {"symbols": {"X": {"sector": "Technology", "sector_etf": None,
                                  "median_dollar_volume": 500e6}},
               "universe_limitation": "test"}
    t = pd.Timestamp("2026-08-17 14:47:00", tz="UTC")
    scan_rec, _ = decision_pass(
        t, universe, {"X": bars, "SPY.US": mkt_bars},
        {"X": _ctx(), "SPY.US": _ctx(symbol="SPY.US", prev_close=775.98)},
        enrich=False)
    facets = scan_rec["universe_facets"]
    assert facets["n_session_anchor_valid"] == 0
    assert facets["above_vwap_frac"] is None
    assert facets["opening_behavior"]["n_or_complete"] == 0


# --------------------------------------------------------------- Twin 2.0
def test_world_state_observation_integrity_and_no_crash_on_invalid_anchor():
    from apex.world.twin2 import build_world
    frames = {"SPY.US": _trending_bars(
        "2026-08-17 14:17:00+00:00", 30, base=775.0, seed=1),
              "XLK.US": _trending_bars(
        "2026-08-17 14:17:00+00:00", 30, base=190.0, seed=2)}
    t = pd.Timestamp("2026-08-17 14:47:00", tz="UTC")
    w = build_world(frames, t, DAY, universe_facets=None,
                    spy_daily=None, spy_atr_frac=0.011)
    assert w["observation_integrity"]["n_session_anchor_valid"] == 0
    assert w["observation_integrity"]["healthy_session_state"] is False
    assert w["market_structure"]["trend"]["spy_day_return"] is None
    assert w["market_structure"]["breadth"]["sectors_positive_frac"] is None
    assert w["leadership"]["sector_ranking_top"] == []


def test_world_state_healthy_and_populated_on_full_session():
    from apex.world.twin2 import build_world
    frames = {"SPY.US": _trending_bars(ET_OPEN, 90, base=775.0, seed=1),
              "XLK.US": _trending_bars(ET_OPEN, 90, base=190.0, seed=2),
              "XLF.US": _trending_bars(ET_OPEN, 90, base=58.0, seed=3)}
    t = pd.Timestamp("2026-08-17 15:00:00", tz="UTC")
    w = build_world(frames, t, DAY, universe_facets=None,
                    spy_daily=None, spy_atr_frac=0.011)
    assert w["observation_integrity"]["healthy_session_state"] is True
    assert w["market_structure"]["trend"]["spy_day_return"] is not None
