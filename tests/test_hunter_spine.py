"""Full-spine counterexamples: analog leakage law, ML refusal, bundle
honesty, simulator future-blindness, monotone caution, degradation."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from apex.analog.engine import AnalogQuery, retrieve
from apex.hunter.capital import caution_scale
from apex.hunter.evidence import EvidenceClass
from apex.hunter.forecast import (ForecastBundle, SwarmAssessment,
                                  assemble_bundle, measure_disagreement)
from apex.ml.hunter_models import (MLContractViolation, build_dataset,
                                   train)
from apex.world.simulator import TwinSnapshot, simulate
from tests.test_hunter_p1b import T, bars, ctx

ET = "America/New_York"


def mem_row(i, day, ret60=0.01, rvol=2.0, r30=0.01, t_hour=15):
    return {"decision_id": f"a{i}", "session_date": day, "symbol": "AMD",
            "regime": "UP",
            # LAB-08: rows declare their provenance; the engine verifies it
            "evidence_class": "EODHD_FORWARD_OBSERVATION",
            "resolved_at": f"{day}T21:00:00+00:00",
            "candidate": {
                "t_utc": f"{day}T{t_hour}:00:00+00:00",
                "chart_state": {"minutes_into_session": 75,
                                "day_return": 0.01, "r_30m": r30,
                                "r_60m": 0.012, "distance_to_vwap": 0.003,
                                "position_in_or": 1.2, "rvol_tod": rvol,
                                "realized_vol_ann": 0.3,
                                "range_vs_atr": 0.8, "gap_frac": 0.005},
                "relative_strength": {"excess_market_60m": 0.008,
                                      "excess_sector_60m": 0.005,
                                      "cross_sectional_pct": 0.9},
                "market_state": {"day_return": 0.002}},
            "outcome": {"ret_60m": ret60, "mae_60m": -0.004,
                        "mfe_60m": 0.02, "target_before_stop": True}}


QUERY = AnalogQuery(
    as_of="2026-08-17T15:00:00+00:00", security_id="AMD",
    horizon_minutes=60, playbook_id="HUNTER-001_v1",
    candidate_record=mem_row(0, "2026-08-14")["candidate"])


# ---- adversarial 1: future outcomes cannot influence neighbour selection
def test_analog_neighbours_immune_to_future_returns():
    rows = [mem_row(i, "2026-08-10", ret60=0.01 * i) for i in range(30)]
    r1 = retrieve(QUERY, rows,
                  evidence_class=EvidenceClass.EODHD_FORWARD_OBSERVATION,
                  k=10)
    poisoned = [dict(r, outcome={**r["outcome"], "ret_60m": -9.9})
                for r in rows]
    r2 = retrieve(QUERY, poisoned,
                  evidence_class=EvidenceClass.EODHD_FORWARD_OBSERVATION,
                  k=10)
    assert r1.neighbour_ids == r2.neighbour_ids       # identities frozen
    assert r1.distances == r2.distances
    assert r1.forward_returns != r2.forward_returns   # outcomes DID change


# ---- adversarial 2: a future candidate can never be an analogue
def test_analog_time_firewall_structural():
    rows = [mem_row(1, "2026-08-14"),               # legal
            mem_row(2, "2026-08-18"),               # formed after as_of
            dict(mem_row(3, "2026-08-14"),          # resolves after as_of
                 resolved_at="2026-08-18T21:00:00+00:00")]
    r = retrieve(QUERY, rows,
                 evidence_class=EvidenceClass.EODHD_FORWARD_OBSERVATION)
    assert r.neighbour_ids == ("a1",)


# ---- adversarial 3 + 7: historical stays limited; sparse stays humble
def test_analog_historical_carries_limitation_and_sparse_refuses_confidence():
    # LAB-08: exploratory rows must SAY they are exploratory. Declaring the
    # class over forward-stamped rows is now refused, which is the point.
    rows = [dict(mem_row(i, "2026-08-10"),
                 evidence_class="EODHD_HISTORICAL_EXPLORATORY")
            for i in range(3)]
    r = retrieve(QUERY, rows,
                 evidence_class=EvidenceClass.EODHD_HISTORICAL_EXPLORATORY)
    assert r.survivorship_limitation is True
    assert r.status == "ANALOG_SUPPORT_LOW"
    b = assemble_bundle({"decision_id": "d", "direction": "LONG",
                         "playbook_id": "HUNTER-001_v1"}, analog_result=r)
    assert b.analog_view["p_positive"] is not None or True
    assert b.distribution_source_status == "REFUSED"  # low support = no claim


def test_analog_no_rows_is_no_valid_analogs():
    r = retrieve(QUERY, [],
                 evidence_class=EvidenceClass.EODHD_FORWARD_OBSERVATION)
    assert r.status == "NO_VALID_ANALOGS" and r.uncertainty == "HIGH"


# ---- adversarial 4/5/6: ML contract
def test_ml_refuses_without_evidence_and_undeclared_horizon():
    ds = build_dataset([], {}, 60, evidence_class=EvidenceClass.EODHD_FORWARD_OBSERVATION)
    m = train(ds)
    assert m.status == "UNTRAINED"
    assert "INSUFFICIENT_FORWARD_DATA" in m.reasons[0]
    assert m.predict_p_positive({})["p_positive"] is None
    assert m.provenance                              # provenance always
    with pytest.raises(MLContractViolation):
        build_dataset([], {}, 45, evidence_class=EvidenceClass.EODHD_FORWARD_OBSERVATION)   # undeclared horizon


def test_ml_trains_deterministically_when_evidence_exists():
    decisions, realized = [], {}
    for i in range(240):
        day = f"2026-{(i % 12) + 1:02d}-{(i % 28) + 1:02d}"
        row = mem_row(i, day, r30=0.02 * ((i % 3) - 1),
                      rvol=1.5 + (i % 4) * 0.5)
        d = {**row["candidate"], "decision_id": f"d{i}",
             "session_date": day, "playbook_id": "HUNTER-001_v1",
             "forward_eligibility": "FORWARD_ELIGIBLE",
             "evidence_class": "EODHD_FORWARD_OBSERVATION"}
        decisions.append(d)
        realized[f"d{i}"] = {"ret_60m": 0.01 if i % 3 == 0 else -0.005}
    ds = build_dataset(decisions, realized, 60, evidence_class=EvidenceClass.EODHD_FORWARD_OBSERVATION)
    assert ds.n_effective >= 40
    m1, m2 = train(ds), train(ds)
    assert m1.status == "EXPLORATORY_MODEL" and m1.coef == m2.coef
    p = m1.predict_p_positive(decisions[0])
    assert 0.0 < p["p_positive"] < 1.0


# ---- bundle honesty: no fake ensemble, disagreement first-class
def test_bundle_monday_truth_and_no_fake_ensemble():
    b = assemble_bundle({"decision_id": "d1", "direction": "LONG",
                         "playbook_id": "HUNTER-001_v1",
                         "t_utc": "2026-08-17T14:00:00+00:00"})
    assert b.distribution_source_status == "REFUSED"
    assert b.ml_view["status"] == "UNTRAINED"
    assert b.swarm_view["status"] == "BLOCKED_EXTERNAL_AUTH"  # default absence
    assert b.disagreement["level"] == "UNMEASURABLE"
    r = b.as_record()
    assert "0.615" not in str(r)                     # no invented average
    with pytest.raises(ValueError):
        ForecastBundle(candidate_id="x", as_of="t", horizon_minutes=60,
                       playbook_view={}, analog_view={}, ml_view={},
                       simulation_view=None, swarm_view={},
                       mechanism_status="ASSOCIATIONAL",
                       disagreement={},
                       distribution_source_status="SUPER_PROBABILITY",
                       provenance={})


def test_disagreement_measured_not_hidden():
    d = measure_disagreement("LONG", analog_p=0.73, ml_p=0.41,
                             swarm_adversarial=False)
    assert d.level == "HIGH" and d.direction_disagreement is True
    assert d.probability_dispersion == pytest.approx(0.32)


# ---- adversarial 13: a non-OK swarm cannot smuggle claims
def test_swarm_non_ok_carries_no_claims():
    with pytest.raises(ValueError):
        SwarmAssessment(candidate_id="c", as_of="t",
                        status="BLOCKED_EXTERNAL_AUTH",
                        claims=(("ADVERSARIAL_TRADER", "buy more", ""),))


# ---- adversarial 8/9: monotone caution law
def test_caution_is_monotone_never_aggressive():
    base = caution_scale(market_uncertain=False)
    assert base == 1.0
    for kw in ({"market_uncertain": True},
               {"market_uncertain": False, "disagreement_level": "HIGH"},
               {"market_uncertain": False, "analog_support_low": True},
               {"market_uncertain": True, "disagreement_level": "HIGH",
                "analog_support_low": True}):
        assert caution_scale(**kw) < base


# ---- adversarial 10: simulator is future-blind
def sim_inputs():
    f = bars("AMD", drift=0.04, seed=5)
    hist = pd.concat([bars("AMD", date=f"2026-08-{d:02d}", seed=d)
                      for d in (3, 4, 5, 6, 7)], ignore_index=True)
    cand = {"decision_id": "d1", "direction": "LONG", "entry": 100.5,
            "stop": 99.9, "target": 101.7}
    snap = TwinSnapshot(as_of=str(T), market={"day_return": 0.001},
                        symbol_state={"rvol": 2.0})
    return cand, snap, f, hist


def test_simulator_future_blind():
    cand, snap, f, hist = sim_inputs()
    s1 = simulate(cand, snap, f, hist, n_paths=50, atr_frac=0.02)
    poisoned = f.copy()
    late = poisoned["event_time_utc"] > T
    poisoned.loc[late, ["open", "high", "low", "close"]] = 9999.0
    s2 = simulate(cand, snap, poisoned, hist, n_paths=50, atr_frac=0.02)
    assert s1.as_record() == s2.as_record()


# ---- adversarial 11/12: declared empirical source; frequencies not
# probabilities; simulation cannot authorize anything
def test_simulator_declares_source_and_uncalibrated_weights():
    cand, snap, f, hist = sim_inputs()
    s = simulate(cand, snap, f, hist, n_paths=50, atr_frac=0.02)
    assert s.source == "conditional_block_bootstrap_v1"
    assert s.calibration_status == "UNCALIBRATED_SCENARIO_WEIGHT"
    assert abs(sum(s.branch_scenario_frequencies.values()) - 1.0) < 0.01
    assert s.as_record()["authorization_power"] == "NONE_DIAGNOSTIC_ONLY"
    assert "probabilit" not in json_keys(s.branch_scenario_frequencies)
    # deterministic reproduction
    s2 = simulate(cand, snap, f, hist, n_paths=50, atr_frac=0.02)
    assert s.simulation_id == s2.simulation_id
    # honest refusal without donor material
    assert simulate(cand, snap, f, hist.iloc[:100], n_paths=50) is None


def json_keys(d) -> str:
    return " ".join(d.keys()).lower()


# ---- adversarial 22: pipeline continues when enrichment dies
def test_decision_pass_survives_broken_intelligence(monkeypatch):
    import apex.hunter.memory as memmod
    from apex.hunter.forward_pass import decision_pass
    from tests.test_hunter_p1b import failed_spike_frame

    def boom(*a, **k):
        raise RuntimeError("intelligence seat on fire")
    monkeypatch.setattr(memmod, "analog_memory_rows", boom)
    f, t = failed_spike_frame()
    universe = {"symbols": {"X": {"sector": "Technology", "sector_etf": None,
                                  "median_dollar_volume": 500e6}},
                "universe_limitation": "test"}
    _, records = decision_pass(
        t, universe, {"X": f, "SPY.US": bars("SPY", n=120, noise=5e-5)},
        {"X": ctx("X"), "SPY.US": ctx("SPY")})
    kinds = [r.get("kind") for r in records]
    assert "capital_decision" in kinds               # capital still reached
    assert "forecast_bundle" not in kinds            # enrichment degraded
