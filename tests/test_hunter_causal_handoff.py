"""Regression coverage for the scheduled simulation handoff and its causal input set."""
import ast
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from apex.hunter import intelligence_wiring as W


def frame(n=90):
    times = pd.date_range("2026-09-14 13:30", periods=n, freq="min", tz="UTC")
    prices = 100 * np.exp(np.cumsum(np.random.default_rng(7).normal(0, .001, n)))
    return pd.DataFrame(dict(event_time_utc=times, close=prices, open=prices,
                             high=prices, low=prices, volume=1000))


def test_unclosed_and_future_prices_cannot_change_simulation():
    # 420 bars, not the fixture default of 90: the variance contract requires MIN_OBS=200 ADJACENT one-minute
    # returns, so a 90-bar frame cut in half could never reach SIMULATED_UNCALIBRATED. The original assertion was
    # unreachable, and CI stopped at the synthetic smoke before this file ever ran.
    f = frame(420)
    cutoff = f.event_time_utc.iloc[300].timestamp()
    a = W.simulation_view({}, f, as_of_epoch=cutoff, prefer_garch=False, n_paths=100)
    changed = f.copy()
    changed.loc[300:, "close"] = 100000
    b = W.simulation_view({}, changed, as_of_epoch=cutoff, prefer_garch=False, n_paths=100)
    assert a.calibration_status == "SIMULATED_UNCALIBRATED", a.reasons
    assert a == b
    assert a.provenance["spot"] == f.close.iloc[299]


def test_receipt_exclusion_also_applies_to_spot():
    f = frame()
    cutoff = f.event_time_utc.iloc[-1].timestamp() + 60
    f["available_epoch"] = f.event_time_utc.map(lambda t: t.timestamp() + 60)
    f.loc[len(f)-1, "available_epoch"] = cutoff + 10
    visible = W._visible_simulation_bars(f, cutoff_epoch=cutoff)
    assert visible.close.iloc[-1] == f.close.iloc[-2]
    assert all(r["available"] <= cutoff for r in W._return_rows(f, cutoff_epoch=cutoff))


def test_completion_boundary_and_missing_minutes():
    f = frame(5)
    cutoff = f.event_time_utc.iloc[3].timestamp()
    rows = W._return_rows(f, cutoff_epoch=cutoff)
    assert len(rows) == 2
    assert rows[-1]["event_time"] == cutoff
    gapped = f.drop(index=1)
    assert len(W._return_rows(gapped, cutoff_epoch=cutoff)) == 0


def test_duplicate_visible_bars_refuse():
    f = frame()
    cutoff = f.event_time_utc.iloc[-1].timestamp() + 60
    v = W.simulation_view({}, pd.concat([f, f.tail(1)]),
                          as_of_epoch=cutoff, prefer_garch=False, n_paths=100)
    assert v.calibration_status == "REFUSED"
    assert "DUPLICATE_SIMULATION_BAR" in str(v.reasons)


def test_prior_session_excluded():
    f = frame()
    prior = f.copy()
    prior["event_time_utc"] -= pd.Timedelta(days=3)
    cutoff = f.event_time_utc.iloc[-1].timestamp() + 60
    visible = W._visible_simulation_bars(pd.concat([prior, f]), cutoff_epoch=cutoff)
    assert len(visible) == len(f)


def test_both_production_call_sites_pass_bars():
    # Structural wiring check, not a claim that the scheduled host executed.
    root = Path(__file__).resolve().parents[1]
    for path in ("apex/hunter/forward_pass.py", "scripts/hunter_forward_clock.py"):
        tree = ast.parse((root / path).read_text())
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Name) and n.func.id == "enrichment_pass"]
        assert calls, path
        assert all(any(k.arg == "bars_by_symbol" for k in n.keywords) for n in calls), path


def test_real_decision_pass_hands_original_frames_to_enrichment(monkeypatch):
    from apex.hunter import forward_pass as F
    from tests.test_hunter_p1b import failed_spike_frame, bars, ctx
    f, t = failed_spike_frame(date="2026-08-17")
    inputs = {"X": f, "SPY.US": bars("SPY", date="2026-08-17", n=120, noise=5e-5)}
    universe = {"symbols": {"X": {"sector": "Technology", "sector_etf": None,
                                    "median_dollar_volume": 500e6}}}
    seen = []
    def capture(t, date, decisions, universe, bars_by_symbol=None):
        seen.append(bars_by_symbol)
        return []
    monkeypatch.setattr(F, "enrichment_pass", capture)
    F.decision_pass(t, universe, inputs,
                   {"X": ctx("X", as_of_date="2026-08-17"),
                    "SPY.US": ctx("SPY", as_of_date="2026-08-17")})
    assert len(seen) == 1 and seen[0] is inputs


def test_the_same_session_window_blinds_the_simulation_until_midday():
    """A MEASURED property of this repair, pinned so it cannot be discovered in production.

    `_visible_simulation_bars` restricts the fit to the cutoff's own market date, and the variance contract needs
    MIN_OBS=200 adjacent one-minute returns. On real SPY live bars for 2026-09-14 the layer therefore REFUSES from
    the open until roughly 13:05 ET:

        09:35 ET   4 returns   REFUSED   10:30 ET  59 returns  REFUSED
        11:30 ET 119 returns   REFUSED   12:50 ET 194 returns  REFUSED
        14:00 ET 264 returns   SIMULATED_UNCALIBRATED

    The open -- the most decision-relevant part of the session -- has no multiverse view at all. This test states
    the behaviour rather than asserting it is correct; widening the window to prior completed sessions is a data
    decision for the operator, and the adjacent-minute rule below already prevents an overnight gap from ever
    being treated as a one-minute return."""
    f = frame(420)
    early = f.event_time_utc.iloc[60].timestamp()
    v = W.simulation_view({}, f, as_of_epoch=early, prefer_garch=False, n_paths=50)
    assert v.calibration_status == "REFUSED"
    assert "TOO_FEW_OBSERVATIONS" in v.reasons[0], v.reasons
    late = f.event_time_utc.iloc[300].timestamp()
    assert W.simulation_view({}, f, as_of_epoch=late, prefer_garch=False,
                             n_paths=50).calibration_status == "SIMULATED_UNCALIBRATED"


def test_an_overnight_gap_is_never_a_one_minute_return():
    """The session boundary is excluded by the ADJACENCY rule, not only by the market-date filter -- which is why
    widening the history window would not admit a cross-session return."""
    a = pd.date_range("2026-09-11 19:00", periods=30, freq="min", tz="UTC")
    b = pd.date_range("2026-09-14 13:30", periods=30, freq="min", tz="UTC")
    times = a.append(b)
    px = 100 * np.exp(np.cumsum(np.random.default_rng(3).normal(0, .001, len(times))))
    two = pd.DataFrame(dict(event_time_utc=times, close=px, open=px, high=px, low=px, volume=1000))
    rows = W._return_rows(two, cutoff_epoch=times[-1].timestamp() + 60)
    assert rows, "the same-session returns must survive"
    spans = [r["event_time"] for r in rows]
    assert all(s >= b[0].timestamp() for s in spans), "no return may span the overnight boundary"
