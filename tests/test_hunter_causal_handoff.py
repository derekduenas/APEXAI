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
    f = frame()
    cutoff = f.event_time_utc.iloc[65].timestamp()
    a = W.simulation_view({}, f, as_of_epoch=cutoff, prefer_garch=False, n_paths=100)
    changed = f.copy()
    changed.loc[65:, "close"] = 100000
    b = W.simulation_view({}, changed, as_of_epoch=cutoff, prefer_garch=False, n_paths=100)
    assert a.calibration_status == "SIMULATED_UNCALIBRATED", a.reasons
    assert a == b
    assert a.provenance["spot"] == f.close.iloc[64]


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
