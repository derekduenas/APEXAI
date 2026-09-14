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
        assert all(any(k.arg == "model_history_by_symbol" for k in n.keywords)
                   for n in calls), "%s must pass the model's own history, not only today's frame" % path


def test_real_decision_pass_hands_original_frames_to_enrichment(monkeypatch):
    from apex.hunter import forward_pass as F
    from tests.test_hunter_p1b import failed_spike_frame, bars, ctx
    f, t = failed_spike_frame(date="2026-08-17")
    inputs = {"X": f, "SPY.US": bars("SPY", date="2026-08-17", n=120, noise=5e-5)}
    universe = {"symbols": {"X": {"sector": "Technology", "sector_etf": None,
                                    "median_dollar_volume": 500e6}}}
    seen = []
    def capture(t, date, decisions, universe, bars_by_symbol=None,
                model_history_by_symbol=None):
        seen.append((bars_by_symbol, model_history_by_symbol))
        return []
    monkeypatch.setattr(F, "enrichment_pass", capture)
    F.decision_pass(t, universe, inputs,
                   {"X": ctx("X", as_of_date="2026-08-17"),
                    "SPY.US": ctx("SPY", as_of_date="2026-08-17")})
    assert len(seen) == 1
    passed_bars, passed_history = seen[0]
    assert passed_bars is inputs, "today's frames reach enrichment unmodified"
    # THE DIRECT DECISION PATH MUST ALSO SUPPLY THE MODEL'S OWN HISTORY. Today's frame alone starves the
    # variance model until roughly 200 minutes into the session.
    assert passed_history is not None, "the direct decision path must pass model history"
    assert "X" in passed_history, passed_history
    prov = (passed_history["X"] or {}).get("provenance") or {}
    assert prov.get("schema") == "HUNTER_MODEL_HISTORY_V1", prov
    assert "prior_sessions" in prov, "the history must say which completed sessions it drew on"


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


def _two_session_frame():
    """Prior session (2026-09-11 19:00 UTC) then current session (2026-09-14 13:30 UTC)."""
    a = pd.date_range("2026-09-11 19:00", periods=30, freq="min", tz="UTC")
    b = pd.date_range("2026-09-14 13:30", periods=30, freq="min", tz="UTC")
    times = a.append(b)
    px = 100 * np.exp(np.cumsum(np.random.default_rng(3).normal(0, .001, len(times))))
    return pd.DataFrame(dict(event_time_utc=times, close=px, open=px, high=px, low=px, volume=1000)), a, b


def test_market_date_filtering_excludes_the_prior_session():
    """FILTER, not adjacency. `_visible_simulation_bars` keeps only the cutoff's own market date, so the prior
    session never reaches the return calculation at all."""
    two, a, b = _two_session_frame()
    cutoff = b[-1].timestamp() + 60
    visible = W._visible_simulation_bars(two, cutoff_epoch=cutoff)
    kept = visible["event_time_utc"]
    assert len(kept) == len(b), "only the current session's bars survive the filter"
    assert kept.min() >= b[0] and kept.max() <= b[-1]
    assert not ((kept >= a[0]) & (kept <= a[-1])).any(), "no prior-session bar survives"


def test_adjacency_excludes_a_session_jump_when_both_sessions_reach_the_return_calculation(monkeypatch):
    """ADJACENCY, not the filter. This is a SEPARATE property and it does NOT prove the test above.

    The market-date filter is bypassed on purpose so both sessions are presented to `_return_rows`; what is under
    test is the `times[i] - times[i-1] != 60` rule. This matters because widening the history window (which the
    morning warm-up requires) removes the filter's protection and leaves adjacency as the only thing standing
    between the model and a 3-day 'one-minute return'."""
    two, a, b = _two_session_frame()
    monkeypatch.setattr(W, "_visible_simulation_bars",
                        lambda bars, *, cutoff_epoch, sessions=1:
                        bars.sort_values("event_time_utc", kind="stable"))
    rows = W._return_rows(two, cutoff_epoch=b[-1].timestamp() + 60)
    assert rows, "the within-session returns must survive"
    assert len(rows) == (len(a) - 1) + (len(b) - 1), \
        "every adjacent pair in BOTH sessions is a return; only the junction is refused"
    jump = b[0].timestamp() - a[-1].timestamp()
    assert jump > 60, "the fixture must actually contain a session jump"
    assert all(r["event_time"] - 60 - 60 != a[-1].timestamp() for r in rows), \
        "no return may be built across the session junction"


# ---- the morning window: the whole point of a separate model-history input
def _session(date, start="13:30", n=390, seed=1, s0=100.0):
    t = pd.date_range("%s %s" % (date, start), periods=n, freq="min", tz="UTC")
    px = s0 * np.exp(np.cumsum(np.random.default_rng(seed).normal(0, .001, n)))
    return pd.DataFrame(dict(event_time_utc=t, close=px, open=px, high=px, low=px, volume=1000))


def test_a_0935_decision_reaches_the_variance_layer_when_history_is_supplied():
    """The defect this input exists for. Today at 09:35 ET has ~4 completed returns; the contract needs 200."""
    today = _session("2026-09-14", n=6, seed=2)
    cutoff = today.event_time_utc.iloc[-1].timestamp() + 60
    starved = W.simulation_view({}, today, as_of_epoch=cutoff, prefer_garch=False, n_paths=50)
    assert starved.calibration_status == "REFUSED"
    assert "TOO_FEW_OBSERVATIONS" in starved.reasons[0]

    prior = _session("2026-09-11", n=390, seed=3)
    history = pd.concat([prior, today], ignore_index=True)
    ok = W.simulation_view({}, today, as_of_epoch=cutoff, history=history, history_sessions=2,
                           prefer_garch=False, n_paths=50)
    assert ok.calibration_status == "SIMULATED_UNCALIBRATED", ok.reasons
    assert ok.provenance["sessions_used"] == ["2026-09-11", "2026-09-14"]
    # spot is still TODAY's last completed bar, never the prior session's close
    assert ok.provenance["spot"] == float(today.close.iloc[-1])


def test_a_0935_decision_still_refuses_when_history_is_genuinely_insufficient():
    today = _session("2026-09-14", n=6, seed=2)
    thin = _session("2026-09-11", n=40, seed=3)
    cutoff = today.event_time_utc.iloc[-1].timestamp() + 60
    v = W.simulation_view({}, today, as_of_epoch=cutoff,
                          history=pd.concat([thin, today], ignore_index=True),
                          history_sessions=2, prefer_garch=False, n_paths=50)
    assert v.calibration_status == "REFUSED", v.provenance
    assert "TOO_FEW_OBSERVATIONS" in v.reasons[0], "MIN_OBS is not relaxed to obtain a simulation"


def test_history_cannot_carry_the_spot_out_of_the_decision_session():
    """With history admitted the newest completed bar could be a PRIOR session's close. A simulation started
    from yesterday's price is not a simulation of today's decision."""
    prior = _session("2026-09-11", n=390, seed=3)
    cutoff = pd.Timestamp("2026-09-14 13:35", tz="UTC").timestamp()
    v = W.simulation_view({}, prior, as_of_epoch=cutoff, history=prior, history_sessions=2,
                          prefer_garch=False, n_paths=50)
    assert v.calibration_status == "REFUSED"
    assert v.source == "SPOT_NOT_FROM_DECISION_SESSION", v.reasons


def test_post_cutoff_history_bars_cannot_change_the_simulation():
    prior = _session("2026-09-11", n=390, seed=3)
    today = _session("2026-09-14", n=30, seed=2)
    cutoff = today.event_time_utc.iloc[10].timestamp()
    hist = pd.concat([prior, today], ignore_index=True)
    a = W.simulation_view({}, today, as_of_epoch=cutoff, history=hist, history_sessions=2,
                          prefer_garch=False, n_paths=50)
    tampered = hist.copy()
    tampered.loc[tampered.event_time_utc >= pd.Timestamp(cutoff, unit="s", tz="UTC"), "close"] = 99999.0
    b = W.simulation_view({}, today, as_of_epoch=cutoff, history=tampered, history_sessions=2,
                          prefer_garch=False, n_paths=50)
    assert a.calibration_status == "SIMULATED_UNCALIBRATED", a.reasons
    assert a.branch_scenario_frequencies == b.branch_scenario_frequencies
    assert a.provenance["spot"] == b.provenance["spot"]


def test_a_garch_refusal_a_fallback_and_a_missing_call_are_three_different_records():
    prior = _session("2026-09-11", n=390, seed=3)
    today = _session("2026-09-14", n=30, seed=2)
    cutoff = today.event_time_utc.iloc[-1].timestamp() + 60
    hist = pd.concat([prior, today], ignore_index=True)

    asked = W.simulation_view({}, today, as_of_epoch=cutoff, history=hist, history_sessions=2,
                              prefer_garch=True, n_paths=50)
    p = asked.provenance
    assert ("garch_refused" in p or "garch_error" in p
            or str(p.get("variance_model", "")).startswith("GARCH")), p
    assert p.get("variance_model"), "the model actually used is always named"

    not_attempted = W.simulation_view({}, today, as_of_epoch=cutoff, history=hist, history_sessions=2,
                                      prefer_garch=False, n_paths=50)
    assert "garch_not_attempted" in not_attempted.provenance

    from apex.hunter.forecast import assemble_bundle
    missing = assemble_bundle({"decision_id": "x", "direction": "LONG"}).as_record()
    assert missing["simulation_view"]["status"] == "NOT_REQUESTED", \
        "a layer nobody called must never read as a refusal"
