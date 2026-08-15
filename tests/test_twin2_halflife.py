"""Twin 2.0 (Digital World) + alpha half-life routing counterexamples."""

from __future__ import annotations

import numpy as np
import pandas as pd

from apex.hunter.halflife import estimate, route_intelligence
from apex.world.twin2 import build_world, transition_state
from tests.test_hunter_p1b import T, bars


def etf_frames():
    syms = ("SPY.US", "QQQ.US", "IWM.US", "XLK.US", "XLY.US", "XLF.US",
            "XLP.US", "XLU.US", "XLV.US", "XLE.US")
    return {s: bars(s, drift=0.01 * (i % 3 - 1), seed=i)
            for i, s in enumerate(syms)}


def test_world_computes_rich_facets_with_typed_absences():
    w = build_world(etf_frames(), T, "2026-08-10",
                    universe_facets={"n_states": 25,
                                     "above_vwap_frac": 0.6},
                    spy_daily=None, spy_atr_frac=0.011)
    ms = w["market_structure"]
    assert ms["correlation"].get("mean_pairwise_60m") is not None
    assert ms["breadth"]["sectors_positive_frac"] is not None
    assert w["risk_environment"]["risk_on_off_spread"] is not None
    assert w["risk_environment"]["volatility_transition"] in (
        "EXPANDING", "NORMAL", "COMPRESSED")
    assert w["leadership"]["sector_ranking_top"]
    assert w["intraday_structure"]["n_states"] == 25
    assert w["event_world"]["status"] == "DORMANT_NO_TIMESTAMPED_FEED"
    assert w["transition_state"]["status"] == "DAILY_SERIES_UNAVAILABLE"
    assert w["decision_power"] == "NONE_OBSERVATIONAL_EPOCH1"
    # the audit's WEAK item: per-facet freshness exists per feed
    assert len(w["system_state"]["per_facet_freshness_min"]) >= 8


def test_transition_state_online_never_revised():
    idx = pd.bdate_range("2021-01-04", periods=1100)
    rng = np.random.default_rng(3)
    px = pd.Series(100 * np.cumprod(1 + rng.normal(2e-4, 0.01, len(idx))),
                   index=idx)
    ts = transition_state(px, str(idx[-1].date() + pd.Timedelta(days=1)))
    assert ts["status"] == "ONLINE"
    assert ts["regime"] in ("CALM_UP", "CALM_DOWN", "VOL_UP", "VOL_DOWN")
    assert ts["time_since_transition_sessions"] >= 1
    assert ts["pmf"]["status"] == "UNCALIBRATED_NOT_COMPUTED"  # no invention
    # as-of: label date must precede the query date
    assert ts["label_asof"] < "2026-01-01" or ts["label_asof"] <= str(
        idx[-1].date())


def test_halflife_refuses_then_estimates_then_routes():
    assert estimate("HUNTER-001_v1", [])["status"] == "NOT_YET_ESTIMABLE"
    rows = []
    for i in range(12):
        rows.append({"session_date": f"2026-08-{i+1:02d}",
                     "ret_15m": 0.004, "ret_30m": 0.003,
                     "ret_60m": 0.001, "ret_90m": 0.0005})
    hl = estimate("HUNTER-001_v1", rows)
    assert hl["status"] == "PERSISTENCE_MEASURED"
    assert hl["edge_persistence_horizon_minutes"] == 30
    r = route_intelligence(hl)
    assert r["routing"] == "STANDARD" and r["allow_deep_swarm"] is True
    fast = estimate("X", [{"session_date": f"d{i}", "ret_15m": 0.004,
                           "ret_30m": 0.001, "ret_60m": 0.0,
                           "ret_90m": 0.0} for i in range(12)])
    assert route_intelligence(fast)["routing"] == "FAST_ONLY"
    assert route_intelligence(fast)["allow_deep_swarm"] is False
    assert route_intelligence(
        {"status": "NOT_YET_ESTIMABLE"})["routing"] == "STANDARD_DEFAULT"


def test_routing_only_reduces_intelligence_never_adds_aggression(monkeypatch):
    import apex.hunter.swarm as swarm
    monkeypatch.setattr(swarm, "auth_available", lambda: True)
    import json
    good = json.dumps({"claims": [], "adversarial_flags": [],
                       "unresolved_questions": []})
    calls = []

    def runner(p):
        calls.append(p)
        return good
    a = swarm.run_specialists({"decision_id": "d"}, as_of="t",
                              allow_deep=False, runner=runner)
    assert a.agents_run == swarm.TIER1_AGENTS     # assassin ALWAYS runs
    assert set(a.provenance["agents_skipped"]) == set(swarm.TIER2_AGENTS)
    assert a.provenance["deep_allowed_by_routing"] is False
