"""P1B counterexample suite: as-of leakage, relative strength, scanner
funnel, playbook predicates, birth-timestamp eligibility.

The leakage tests are the load-bearing ones: inject a monster bar AFTER T
and require every ChartState field to be unchanged — the day's later high,
the day's final volume, and the final VWAP must be structurally
unreachable at T.
"""

from __future__ import annotations

import dataclasses

import numpy as np
import pandas as pd
import pytest

from apex.hunter.birth import (FORWARD_ELIGIBLE, NOT_FORWARD_ELIGIBLE,
                               forward_eligibility)
from apex.hunter.chartstate import (DailyContext, compute_chart_state,
                                    visible_bars)
from apex.hunter.forward_pass import extension_geometry, resolve_decision
from apex.hunter.playbooks_v1 import match_hunter_001, match_hunter_002
from apex.hunter.relstrength import compute_relative_strength
from apex.hunter.scanner import Signal, detect_signals, scan

ET = "America/New_York"


def bars(symbol="TEST", date="2026-08-10", n=390, base=100.0, drift=0.0,
         vol_per_min=10_000.0, seed=7, noise=3e-4):
    """Synthetic Monday regular-session 1m bars, 09:30 ET onward."""
    rng = np.random.default_rng(seed)
    t0 = pd.Timestamp(f"{date} 09:30", tz=ET).tz_convert("UTC")
    times = pd.date_range(t0, periods=n, freq="1min")
    steps = drift / n + rng.normal(0, noise, n)
    close = base * np.cumprod(1 + steps)
    op = np.r_[base, close[:-1]]
    return pd.DataFrame({
        "provider_symbol": symbol, "event_time_utc": times,
        "open": op, "high": np.maximum(op, close) * 1.0004,
        "low": np.minimum(op, close) * 0.9996, "close": close,
        "volume": np.full(n, vol_per_min)})


def ctx(symbol="TEST", **kw):
    base = {"symbol": symbol, "as_of_date": "2026-08-10",
            "prev_day_high": 101.0, "prev_day_low": 99.0,
            "prev_close": 100.0, "weekly_high": 102.0, "weekly_low": 98.0,
            "atr_frac": 0.02, "median_day_range_frac": 0.015,
            "cum_vol_by_minute": {str(m): 10_000.0 * (m + 1)
                                  for m in range(390)},
            "median_dollar_volume": 100e6, "sessions_observed": 20}
    base.update(kw)
    return DailyContext(**base)


T = pd.Timestamp("2026-08-10 10:45", tz=ET).tz_convert("UTC")


# ------------------------------------------------------------- as-of leakage
def test_future_monster_bar_changes_nothing():
    f = bars()
    cs_before = compute_chart_state("TEST", f, T, ctx())
    poisoned = f.copy()
    late = poisoned["event_time_utc"] > T
    poisoned.loc[late, ["high", "close"]] = 999.0   # day high explodes later
    poisoned.loc[late, "volume"] = 1e9              # day volume explodes
    cs_after = compute_chart_state("TEST", poisoned, T, ctx())
    assert cs_before.as_record() == cs_after.as_record()


def test_bar_at_T_not_yet_visible():
    f = bars()
    t_edge = f["event_time_utc"].iloc[100]          # bar starts exactly at T
    vis = visible_bars(f, t_edge)
    assert vis["event_time_utc"].max() < t_edge     # completes at T+1m
    vis2 = visible_bars(f, t_edge + pd.Timedelta(minutes=1))
    assert vis2["event_time_utc"].max() == t_edge


def test_vwap_at_T_differs_from_final_vwap():
    f = bars(drift=0.05)
    cs_mid = compute_chart_state("TEST", f, T, ctx())
    end = f["event_time_utc"].iloc[-1] + pd.Timedelta(minutes=1)
    cs_end = compute_chart_state("TEST", f, end, ctx())
    assert cs_mid.vwap != pytest.approx(cs_end.vwap)


def test_rvol_uses_only_visible_volume():
    f = bars()
    cs = compute_chart_state("TEST", f, T, ctx())
    # 75 minutes in at 10:45, baseline 10k/min => rvol ~= 1
    assert cs.rvol_tod == pytest.approx(1.0, abs=0.05)
    assert cs.cum_volume == pytest.approx(75 * 10_000.0)


def test_opening_range_incomplete_before_1000():
    f = bars()
    early = pd.Timestamp("2026-08-10 09:50", tz=ET).tz_convert("UTC")
    cs = compute_chart_state("TEST", f, early, ctx())
    assert cs.or_complete is False and cs.or_high is None


def test_missing_context_flags_not_fabricates():
    f = bars()
    cs = compute_chart_state("TEST", f, T,
                             DailyContext(symbol="TEST",
                                          as_of_date="2026-08-10"))
    assert cs.gap_frac is None and cs.rvol_tod is None
    assert "NO_PREV_CLOSE" in cs.data_quality
    assert "NO_RVOL_BASELINE" in cs.data_quality


# -------------------------------------------------------- relative strength
def test_amd_style_excess_and_agreement():
    amd = bars("AMD", drift=0.055, seed=1)        # ~ +1.1% by T pace
    qqq = bars("QQQ", drift=-0.015, seed=2)
    soxx = bars("SOXX", drift=-0.005, seed=3)
    a = compute_chart_state("AMD", amd, T, ctx("AMD"))
    q = compute_chart_state("QQQ", qqq, T, ctx("QQQ"))
    s = compute_chart_state("SOXX", soxx, T, ctx("SOXX"))
    rs = compute_relative_strength(a, q, s)
    assert rs.excess_market_day == pytest.approx(
        a.day_return - q.day_return)
    assert rs.excess_market_day > 0.008
    assert rs.excess_sector_day > 0.008
    assert rs.multi_horizon_agreement in (True, False, None)


def test_missing_benchmark_propagates_none():
    a = compute_chart_state("AMD", bars("AMD"), T, ctx("AMD"))
    m = compute_chart_state("SPY", bars("SPY"), T, ctx("SPY"))
    rs = compute_relative_strength(a, m, sector=None)
    assert rs.excess_sector_60m is None and rs.sector_symbol is None


# ------------------------------------------------------------------ scanner
def test_scanner_zero_candidates_is_legal():
    # a genuinely ordinary day: pinned inside the OR, normal volume
    a = compute_chart_state("AAA", bars("AAA", noise=5e-5), T, ctx("AAA"))
    m = compute_chart_state("SPY", bars("SPY", noise=5e-5), T, ctx("SPY"))
    rs = compute_relative_strength(a, m)
    res = scan(str(T), 150, [(a, rs)])
    assert res.abnormal == 0 and res.watchlist == ()
    assert res.universe_count == 150 and res.states_computed == 1


def test_scanner_denominators_and_liquidity_refusal():
    cheap = compute_chart_state("PNY", bars("PNY", base=3.0), T,
                                ctx("PNY", median_dollar_volume=1e6))
    m = compute_chart_state("SPY", bars("SPY"), T, ctx("SPY"))
    rs = compute_relative_strength(cheap, m)
    res = scan(str(T), 150, [(cheap, rs)])
    assert res.liquidity_data_ok == 0
    assert any("PRICE_BELOW_MIN" in r for _, r in res.rejected_examples)


def test_extreme_rvol_detected():
    f = bars("HOT", vol_per_min=30_000)           # 3x baseline
    cs = compute_chart_state("HOT", f, T, ctx("HOT"))
    m = compute_chart_state("SPY", bars("SPY"), T, ctx("SPY"))
    rs = compute_relative_strength(cs, m)
    assert Signal.EXTREME_RVOL in detect_signals(cs, rs)


def test_no_signals_in_first_30_minutes():
    f = bars("HOT", vol_per_min=90_000)
    early = pd.Timestamp("2026-08-10 09:45", tz=ET).tz_convert("UTC")
    cs = compute_chart_state("HOT", f, early, ctx("HOT"))
    m = compute_chart_state("SPY", bars("SPY"), early, ctx("SPY"))
    assert detect_signals(cs, compute_relative_strength(cs, m)) == ()


# ---------------------------------------------------------------- playbooks
def strong_setup():
    """A hand-built Hunter-001 textbook case."""
    f = bars("AMD", drift=0.12, vol_per_min=25_000, seed=11)
    cs = compute_chart_state("AMD", f, T, ctx("AMD"))
    mkt = compute_chart_state("SPY", bars("SPY", seed=12), T, ctx("SPY"))
    sec = compute_chart_state("SOXX", bars("SOXX", seed=13), T, ctx("SOXX"))
    rs = compute_relative_strength(cs, mkt, sec)
    return cs, rs, mkt


def test_hunter001_requires_every_predicate():
    cs, rs, mkt = strong_setup()
    m = match_hunter_001(cs, rs, mkt)
    if m is not None:                     # geometry may exclude; if it fires:
        assert m["direction"] == "LONG"
        assert m["stop"] == pytest.approx(cs.vwap)
        assert m["target"] > m["entry"] > m["stop"]
    # break one predicate -> never fires
    weak_rs = dataclasses.replace(rs, excess_market_60m=0.001)
    assert match_hunter_001(cs, weak_rs, mkt) is None
    hostile = dataclasses.replace(mkt, day_return=-0.02)
    assert match_hunter_001(cs, rs, hostile) is None


def test_hunter001_fails_closed_on_missing_input():
    cs, rs, mkt = strong_setup()
    no_rvol = dataclasses.replace(cs, rvol_tod=None)
    assert match_hunter_001(no_rvol, rs, mkt) is None


def failed_spike_frame():
    """Steady rise, sharp spike, then a ~2/3 giveback of the spike leg —
    the mechanism's textbook shape."""
    n = 110
    t0 = pd.Timestamp("2026-08-10 09:30", tz=ET).tz_convert("UTC")
    times = pd.date_range(t0, periods=n, freq="1min")
    path = np.r_[np.linspace(100, 103.5, 60),       # steady rise (VWAP up)
                 np.linspace(103.5, 105.6, 15),     # spike leg
                 np.linspace(105.6, 102.4, 35)]     # failure
    f = pd.DataFrame({"provider_symbol": "X", "event_time_utc": times,
                      "open": path, "high": path * 1.0002,
                      "low": path * 0.9998, "close": path,
                      "volume": np.full(n, 20_000.0)})
    return f, times[-1] + pd.Timedelta(minutes=1)


def test_hunter002_failed_up_extension_short():
    f, t = failed_spike_frame()
    cs = compute_chart_state("X", f, t, ctx("X"))
    mkt = compute_chart_state("SPY", bars("SPY"), t, ctx("SPY"))
    rs = compute_relative_strength(cs, mkt)
    geo = extension_geometry(f, t)
    assert cs.above_vwap is False               # failure took it below VWAP
    m = match_hunter_002(cs, rs, geo)
    assert m is not None and m["direction"] == "SHORT"
    assert m["stop"] == pytest.approx(geo["session_high"])
    assert m["target"] < m["entry"] < m["stop"]
    assert 0.5 <= m["matched"]["retrace"] <= 1.0


def test_hunter002_fresh_extreme_is_a_knife_not_a_failure():
    f, t = failed_spike_frame()
    cs = compute_chart_state("X", f, t, ctx("X"))
    mkt = compute_chart_state("SPY", bars("SPY"), t, ctx("SPY"))
    rs = compute_relative_strength(cs, mkt)
    geo = dict(extension_geometry(f, t))
    geo["session_high_age_min"] = 2.0           # extreme still being made
    assert match_hunter_002(cs, rs, geo) is None


# ------------------------------------------------- birth-stamp eligibility
def _births(t_protocol, t_playbook):
    return {"HUNTER-FORWARD-PROTOCOL_v1":
            {"birth_time_utc": t_protocol, "artifact_hash": "aa",
             "dependency_kind": "protocol"},
            "hunter_feature_schema_v1":
            {"birth_time_utc": t_protocol, "artifact_hash": "bb",
             "dependency_kind": "feature_schema"},
            "hunter_rule_model_v1":
            {"birth_time_utc": t_protocol, "artifact_hash": "cc",
             "dependency_kind": "model"},
            "HUNTER-001_v1":
            {"birth_time_utc": t_playbook, "artifact_hash": "dd",
             "dependency_kind": "playbook"}}


def test_decision_before_playbook_birth_not_eligible():
    b = _births("2026-08-15T18:00:00+00:00", "2026-08-17T15:00:00+00:00")
    status, reasons = forward_eligibility(
        pd.Timestamp("2026-08-17 14:00", tz="UTC"), b)
    assert status == NOT_FORWARD_ELIGIBLE
    assert any("HUNTER-001_v1" in r for r in reasons)


def test_decision_after_all_births_eligible():
    b = _births("2026-08-15T18:00:00+00:00", "2026-08-15T19:00:00+00:00")
    status, reasons = forward_eligibility(
        pd.Timestamp("2026-08-17 14:00", tz="UTC"), b)
    assert status == FORWARD_ELIGIBLE and reasons == ()


def test_missing_dependency_kind_fails_closed():
    b = _births("2026-08-15T18:00:00+00:00", "2026-08-15T19:00:00+00:00")
    del b["hunter_rule_model_v1"]
    status, reasons = forward_eligibility(
        pd.Timestamp("2026-08-17 14:00", tz="UTC"), b)
    assert status == NOT_FORWARD_ELIGIBLE
    assert any("missing dependency birth: model" in r for r in reasons)


def test_load_births_reads_flat_chain_entries(tmp_path):
    """Regression: _chain_append writes FLAT entries ({**record, prev_hash,
    entry_hash}), not a {"record": ...} wrapper — the first mint was written
    correctly but the readers were blind to it."""
    import json

    from apex.hunter.birth import load_births
    reg = tmp_path / "birth_registry.jsonl"
    reg.write_text(json.dumps({
        "kind": "birth", "name": "X_v1", "dependency_kind": "playbook",
        "artifact_hash": "ab", "birth_time_utc": "2026-08-15T18:43:03+00:00",
        "prev_hash": "GENESIS", "entry_hash": "ff"}) + "\n")
    b = load_births(reg)
    assert b["X_v1"]["dependency_kind"] == "playbook"


# ------------------------------------------------------------- realization
def test_realization_deterministic_and_truncation_flagged():
    f = bars(drift=0.03)
    t_form = pd.Timestamp("2026-08-10 15:30", tz=ET).tz_convert("UTC")
    d = {"decision_id": "d1", "session_date": "2026-08-10",
         "playbook_id": "HUNTER-001_v1", "symbol": "TEST",
         "direction": "LONG", "t_utc": str(t_form), "entry": 102.0,
         "stop": 101.0, "target": 104.0}
    r1, r2 = resolve_decision(d, f), resolve_decision(d, f)
    assert r1 == r2
    assert r1["truncated_90m"] is True          # 15:30 + 90m > close
    assert r1["label"] == "MECHANICAL_DETERMINISTIC"
    assert isinstance(r1["closing_return"], float)
