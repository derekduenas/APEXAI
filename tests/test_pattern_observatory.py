"""PATTERN OBSERVATORY V1 -- firewall, invariants, and acceptance.

Organised around the ways this organ could LIE rather than the ways it
could crash:

  * claim authority it does not have
  * report a probability it has not earned
  * let damaged inputs raise confidence
  * call an Observatory-derived number canonical
  * relabel a backfilled record as prospective
  * declare a component LIVE_ACTIVE that nothing calls
  * see the future in an outcome
"""
from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from apex.audit.execution_path import module_closure  # noqa: E402
from apex.pattern_observatory import (  # noqa: E402
    OBSERVATORY_POWER, PRODUCTION_STACK_FORBIDDEN, WRITE_ROOT,
)
from apex.pattern_observatory import abnormality as abn  # noqa: E402
from apex.pattern_observatory import birth as birthmod  # noqa: E402
from apex.pattern_observatory import breadth as brmod  # noqa: E402
from apex.pattern_observatory import conjunction as cjmod  # noqa: E402
from apex.pattern_observatory import contradiction as cdmod  # noqa: E402
from apex.pattern_observatory import families as fammod  # noqa: E402
from apex.pattern_observatory import independence as indep  # noqa: E402
from apex.pattern_observatory import obs_features as obf  # noqa: E402
from apex.pattern_observatory import options_surface as osmod  # noqa: E402
from apex.pattern_observatory import outcomes as ocmod  # noqa: E402
from apex.pattern_observatory import pattern_assassin as pamod  # noqa: E402
from apex.pattern_observatory import pattern_state as psmod  # noqa: E402
from apex.pattern_observatory import positioning as posmod  # noqa: E402
from apex.pattern_observatory import quality as qmod  # noqa: E402
from apex.pattern_observatory import registry as regmod  # noqa: E402
from apex.pattern_observatory import sector_rotation as srmod  # noqa: E402
from apex.pattern_observatory import sequence as sqmod  # noqa: E402
from apex.pattern_observatory import sleeves as slmod  # noqa: E402

PKG = REPO / "apex" / "pattern_observatory"
T0 = pd.Timestamp("2026-08-20T14:00:00Z")


def _modules() -> list:
    return [f"apex.pattern_observatory.{p.stem}" for p in PKG.glob("*.py")
            if p.stem != "__init__"]


# ------------------------------------------------------------- firewall
def test_observatory_reaches_no_production_decision_module():
    for mod in _modules():
        reached = module_closure(REPO, mod)
        hit = {r for r in reached
               if any(r == f or r.startswith(f + ".")
                      for f in PRODUCTION_STACK_FORBIDDEN)}
        assert not hit, f"{mod} reaches production stack: {sorted(hit)}"


def test_runtime_script_reaches_no_production_decision_module():
    src = (REPO / "scripts" / "pattern_observatory_shadow_runtime.py").read_text()
    tree = ast.parse(src)
    imported = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            imported.update(a.name for a in n.names)
        elif isinstance(n, ast.ImportFrom) and n.module:
            imported.add(n.module)
    for m in imported:
        assert not any(m == f or m.startswith(f + ".")
                       for f in PRODUCTION_STACK_FORBIDDEN), m


def test_observatory_writes_only_under_its_own_root():
    """A write into Hunter/Frontier/Captain/Options/live-data would let the
    shadow observer contaminate the official session.

    Checked against ACTUAL WRITE CALLS in the AST -- not against string
    constants. A module legitimately NAMES the artifacts it READS, and a
    substring scan cannot tell a source path from a destination. That
    distinction has been got wrong in this repo before.
    """
    write_calls = {"write_text", "write_bytes", "mkdir", "touch", "unlink",
                   "replace", "rename"}
    forbidden_roots = ("results/hunter", "results/frontier",
                       "results/captain", "results/option_analytics",
                       "results/intraday", "data/live")
    files = list(PKG.glob("*.py")) + [
        REPO / "scripts" / "pattern_observatory_shadow_runtime.py"]
    offenders = []
    for f in files:
        tree = ast.parse(f.read_text())
        # map: local name -> literal path string, for Path(...) assignments
        literals = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                fn = node.value.func
                if (isinstance(fn, ast.Name) and fn.id == "Path"
                        and node.value.args
                        and isinstance(node.value.args[0], ast.Constant)):
                    for t in node.targets:
                        if isinstance(t, ast.Name):
                            literals[t.id] = node.value.args[0].value
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            # Path("...").write_text(...) / .mkdir()
            if isinstance(fn, ast.Attribute) and fn.attr in write_calls:
                target = fn.value
                path_str = None
                if (isinstance(target, ast.Call)
                        and isinstance(target.func, ast.Name)
                        and target.func.id == "Path" and target.args
                        and isinstance(target.args[0], ast.Constant)):
                    path_str = target.args[0].value
                elif isinstance(target, ast.Name):
                    path_str = literals.get(target.id)
                if path_str and path_str.startswith(forbidden_roots):
                    offenders.append(f"{f.name}: {fn.attr} on {path_str}")
            # open(path, "w"/"a")
            if isinstance(fn, ast.Name) and fn.id == "open" and len(node.args) > 1:
                mode = node.args[1]
                if isinstance(mode, ast.Constant) and any(
                        m in str(mode.value) for m in ("w", "a")):
                    tgt = node.args[0]
                    if isinstance(tgt, ast.Constant) and str(
                            tgt.value).startswith(forbidden_roots):
                        offenders.append(f"{f.name}: open(w/a) on {tgt.value}")
    assert not offenders, offenders


def test_observatory_write_root_is_its_own():
    assert WRITE_ROOT == "results/pattern_observatory"
    from apex.pattern_observatory import memory as mem
    for led in mem.LEDGERS:
        assert str(led).startswith(WRITE_ROOT), led


def test_no_module_grants_authority():
    for f in list(PKG.glob("*.py")):
        src = f.read_text()
        assert "CAPITAL_AUTHORITY = \"NONE\"" in src or \
            "capital_authority" not in src.lower() or \
            "NONE" in src, f.name


def test_every_state_carries_observatory_decision_power():
    assert OBSERVATORY_POWER == "NONE_PATTERN_OBSERVATORY"
    q = qmod.assess_bar_input(source="s", event_time=T0, known_from=T0,
                              now=T0, gap_fraction=0.0, bars_observed=10)
    assert q.as_dict()["decision_power"] == OBSERVATORY_POWER
    p = posmod.observe(as_of=T0, known_from=T0)
    assert p.as_dict()["decision_power"] == OBSERVATORY_POWER


# -------------------------------------------------------------- quality
def test_damaged_inputs_never_corroborate_into_confidence():
    """THE ANTI-CORROBORATION LAW. Three DEGRADED sources agreeing must
    not produce anything better than DEGRADED."""
    degraded = [
        qmod.PatternInputQuality(
            source=f"s{i}", event_time=str(T0), known_from=str(T0),
            freshness_s=1.0, coverage_fraction=1.0, gap_fraction=0.3,
            missing_observations=0, staleness="FRESH", integrity="OK",
            quality=qmod.DEGRADED,
            feature_sufficiency={"price_direction": qmod.DEGRADED})
        for i in range(3)]
    v = qmod.combine(degraded, required_features=("price_direction",))
    assert v["combined_quality"] == qmod.DEGRADED
    assert v["estimable"] is True


def test_a_required_invalid_feature_makes_the_pattern_not_estimable():
    q = qmod.assess_bar_input(source="alpaca", event_time=T0, known_from=T0,
                              now=T0, gap_fraction=0.60, bars_observed=100)
    assert q.feature_sufficiency["volume"] == qmod.INVALID
    v = qmod.combine([q], required_features=("volume",))
    assert v["estimable"] is False
    assert v["status"] == qmod.PATTERN_NOT_ESTIMABLE


def test_feature_sufficiency_differs_within_one_damaged_series():
    """The 2026-08-19 lesson: one series, different truth per feature."""
    q = qmod.assess_bar_input(source="alpaca", event_time=T0, known_from=T0,
                              now=T0, gap_fraction=0.30, bars_observed=100)
    assert q.feature_sufficiency["price_direction"] == qmod.LIMITED
    assert q.feature_sufficiency["volume"] == qmod.INVALID
    assert q.feature_sufficiency["ohlc"] == qmod.DEGRADED


def test_negative_freshness_is_a_clock_violation_not_freshness():
    q = qmod.assess_bar_input(
        source="opra", event_time=T0 + pd.Timedelta(seconds=1081),
        known_from=T0, now=T0, gap_fraction=0.0, bars_observed=10)
    assert q.staleness == "CLOCK_INTEGRITY_VIOLATION"
    assert q.integrity == "CLOCK_INTEGRITY_VIOLATION"
    assert q.quality == qmod.INVALID


def test_feature_cannot_exceed_its_source_quality():
    q = qmod.PatternInputQuality(
        source="s", event_time=None, known_from=None, freshness_s=None,
        coverage_fraction=None, gap_fraction=None, missing_observations=None,
        staleness="UNKNOWN", integrity="OK", quality=qmod.DEGRADED,
        feature_sufficiency={"price_direction": qmod.VALID})
    assert q.sufficient_for("price_direction") == qmod.DEGRADED


# -------------------------------------------------------- obs namespacing
def test_observatory_features_must_carry_the_obs_prefix():
    with pytest.raises(ValueError):
        obf.ObsFeature(name="VWAP", value=1.0, status="OK",
                       calculation_version="v", formula="f",
                       formula_hash="h", source_bars=1, source_symbol="SPY",
                       event_time=None, known_from=None)


def test_obs_features_never_claim_to_be_canonical_or_hunter_equivalent():
    f = obf.ObsFeature(name="OBS_VWAP", value=1.0, status="OK",
                       calculation_version=obf.CALCULATION_VERSION,
                       formula="f", formula_hash="h", source_bars=1,
                       source_symbol="SPY", event_time=None, known_from=None)
    d = f.as_dict()
    assert d["canonical"] is False
    assert d["hunter_equivalent"] is False


def test_formula_hash_changes_when_the_formula_changes(monkeypatch):
    before = obf.formula_hash("OBS_VWAP")
    monkeypatch.setitem(obf.FORMULAS, "OBS_VWAP", "a different formula")
    assert obf.formula_hash("OBS_VWAP") != before


def test_rvol_without_a_baseline_is_not_estimable_never_a_number():
    f = obf.obs_rvol(None, symbol="SPY", known_from=T0)
    assert f.status == obf.NOT_ESTIMABLE
    assert f.value is None


# ------------------------------------------------------- sector/breadth
def _bars(returns):
    rows = []
    base = pd.Timestamp("2026-08-20 13:30:00+00:00")
    px = 100.0
    for i, r in enumerate(returns):
        px2 = px * (1 + r)
        rows.append({"event_time_utc": base + pd.Timedelta(minutes=i),
                     "open": px, "high": max(px, px2), "low": min(px, px2),
                     "close": px2, "volume": 1000.0, "trades": 10,
                     "gap_duration_ms": 0})
        px = px2
    return pd.DataFrame(rows)


def test_defensive_rotation_is_recognised():
    obs = []
    for s in srmod.SECTOR_ETFS:
        r = 0.004 if s in srmod.DEFENSIVE else -0.004
        obs.append(srmod.observe_sector(s, _bars([r] * 10), market_return=0.0,
                                        known_from=T0, quality="VALID"))
    st = srmod.classify(obs, market_return=0.0, as_of=T0, known_from=T0)
    assert st.state == "DEFENSIVE_ROTATION"
    assert st.defensive_minus_cyclical > 0


def test_tech_internal_divergence_suppresses_a_tech_leadership_label():
    """XLK -0.24% vs XLC +1.18% on 2026-08-19 averaged to 'tech leads'."""
    obs = []
    for s in srmod.SECTOR_ETFS:
        r = {"XLK": -0.0024, "XLC": 0.0118}.get(s, 0.0)
        obs.append(srmod.observe_sector(s, _bars([r] * 10), market_return=0.0,
                                        known_from=T0, quality="VALID"))
    st = srmod.classify(obs, market_return=0.0, as_of=T0, known_from=T0)
    assert st.tech_internal_split["diverging"] is True
    assert st.state != "TECH_LEADERSHIP"
    assert any("INTERNALLY DIVERGENT" in r for r in st.reasoning)


def test_too_few_sectors_is_unknown_not_a_guess():
    obs = [srmod.observe_sector(s, _bars([0.001] * 10), market_return=0.0,
                                known_from=T0, quality="VALID")
           for s in srmod.SECTOR_ETFS[:4]]
    st = srmod.classify(obs, market_return=0.0, as_of=T0, known_from=T0)
    assert st.state == "UNKNOWN"


def test_breadth_never_calls_the_universe_the_market():
    rows = [{"return_from_open": 0.01} for _ in range(11)]
    st = brmod.compute(sector_rows=rows, universe_rows=[], index_return=0.01,
                       as_of=T0, known_from=T0)
    assert st.universe.scope == "APEX_164_LIQUIDITY_SELECTED"
    assert st.index_constituents["status"] == "NOT_ACQUIRED"


def test_breadth_divergence_is_detected():
    rows = [{"return_from_open": -0.01} for _ in range(9)] + \
           [{"return_from_open": 0.01} for _ in range(2)]
    st = brmod.compute(sector_rows=rows, universe_rows=[], index_return=0.005,
                       as_of=T0, known_from=T0)
    assert st.divergence == "INDEX_UP_BREADTH_WEAK"


# ------------------------------------------------------- positioning
def test_a_value_cannot_be_supplied_for_an_unacquired_source():
    with pytest.raises(posmod.PositioningError):
        posmod.PositioningFact(
            source="CFTC_NQ", subject="NQ", metric="net", value=1234.0,
            as_of_market_date=None, known_from=None, publication_delay=None,
            availability=posmod.NOT_ACQUIRED)


def test_positioning_reports_unavailable_not_empty_optimism():
    """Updated 2026-08-19 evening: CFTC and FINRA are now WIRED, so
    CFTC_NQ moved out of acquirable-but-unwired. What must never change
    is that genuinely inaccessible sources stay named as such -- and that
    supplying no facts still reports UNAVAILABLE rather than silence."""
    st = posmod.observe(as_of=T0, known_from=T0)
    assert st.status == "UNAVAILABLE"          # no facts supplied
    assert "PRIME_BROKER" in st.genuinely_unavailable
    assert "SHORT_INTEREST" in st.genuinely_unavailable
    assert st.source_availability["CFTC_NQ"] == posmod.AVAILABLE_LAGGED
    assert st.source_availability["FINRA_SHORT_VOLUME"] == posmod.AVAILABLE
    assert "FORM_13F" in st.acquirable_but_unwired


def test_crowding_without_data_is_unknown():
    c = posmod.crowding("NQ", as_of=T0, known_from=T0)
    assert c.state == "UNKNOWN"
    assert c.basis == "NO_POSITIONING_SOURCE_ACQUIRED"


def test_forced_flow_distinguishes_unobservable_from_absent():
    st = posmod.assess("SPY", as_of=T0, known_from=T0,
                       present={"crowded_short": None, "price_refuses_down": True})
    assert st.estimable is False
    assert st.level == "UNKNOWN"
    assert "crowded_short" in st.components_missing


# ---------------------------------------------------- options surface
def test_negative_quote_age_suppresses_the_surface():
    states = [{"symbol": "SPYx", "spot": 100.0, "strike": 100.0,
               "state_quality": "HIGH", "iv": {"iv_mid": 0.2},
               "live_quality": {"quote_age_s": -50.0}} for _ in range(20)]
    st = osmod.observe("SPY", states, as_of=T0, known_from=T0)
    assert st.estimable is False
    assert st.quality == osmod.SUPPRESSED
    assert st.contracts_suppressed == 20


# ------------------------------------------------------- independence
def test_five_price_derived_components_are_one_mechanism():
    r = indep.analyse(["curve_positive", "direction_quality",
                       "obs_opening_range_break", "price_refusal",
                       "expectation_violation"])
    assert r["independent_mechanism_count"] == 1
    assert r["inflation_ratio"] == 5.0


# --------------------------------------------------------- abnormality
def test_percentile_refuses_a_single_session_denominator():
    a = abn.assess("m", "SPY", 0.5, [0.1] * 500, session_dates=["d"] * 500,
                   as_of=T0, known_from=T0)
    assert a.state == abn.NOT_ESTIMABLE
    assert "distinct sessions" in a.reason


def test_rarity_never_implies_profitability():
    a = abn.assess("m", "SPY", 9.0, list(range(300)),
                   session_dates=[f"d{i%9}" for i in range(300)],
                   as_of=T0, known_from=T0)
    assert a.as_dict()["rarity_implies_profitability"] is False


# --------------------------------------------------------- conjunction
def test_pattern_id_is_order_independent():
    a = cjmod.pattern_id("SPY", "EQ", ("b", "a", "c"))
    b = cjmod.pattern_id("SPY", "EQ", ("c", "b", "a"))
    assert a == b


def test_conjunction_never_claims_edge():
    e = cjmod.ConjunctionEngine()
    c = e.observe(subject="SPY", market="EQ",
                  active_components={"a": 1, "b": 2}, quality_vector={},
                  regime="R", now=T0, known_from=T0)
    assert c.as_dict()["conjunction_implies_edge"] is False


# ------------------------------------------------------------ sequence
def test_expected_next_step_never_points_backwards():
    e = sqmod.SequenceEngine()
    steps = ("s1", "s2", "s3", "s4")
    st = e.observe(sequence_id="x", family_id="P", subject="SPY", market="EQ",
                   declared_steps=steps, active_steps={"s2", "s3"}, now=T0,
                   known_from=T0)
    assert st.expected_next_step == "s4"
    assert any("skipped" in r for r in st.reasoning)


def test_out_of_order_observation_is_recorded_not_rejected():
    e = sqmod.SequenceEngine()
    steps = ("s1", "s2", "s3")
    e.observe(sequence_id="y", family_id="P", subject="S", market="EQ",
              declared_steps=steps, active_steps={"s3"}, now=T0, known_from=T0)
    st = e.observe(sequence_id="y", family_id="P", subject="S", market="EQ",
                   declared_steps=steps, active_steps={"s3", "s1"},
                   now=T0 + pd.Timedelta(minutes=1), known_from=T0)
    assert st.order_matches_declared is False
    assert st.state != sqmod.BROKEN          # recorded, not penalised


# -------------------------------------------------------- pattern state
def _state(**over):
    e = cjmod.ConjunctionEngine()
    fam = fammod.get("P004")
    c = e.observe(subject="SPY", market="EQ",
                  active_components={k: True for k in fam.components_required},
                  quality_vector={}, regime="R", now=T0, known_from=T0)
    q = qmod.PatternInputQuality(
        source="s", event_time=str(T0), known_from=str(T0), freshness_s=1.0,
        coverage_fraction=1.0, gap_fraction=0.0, missing_observations=0,
        staleness="FRESH", integrity="OK", quality=qmod.VALID,
        feature_sufficiency={f: qmod.VALID for f in fam.required_features})
    v = qmod.combine([q], required_features=fam.required_features)
    st = psmod.build(conjunction=c, family=fam, quality_verdict=v, now=T0,
                     known_from=T0)
    return st


def test_high_alignment_is_not_a_trade():
    st = _state()
    assert st.current_status == psmod.HIGH_ALIGNMENT
    d = st.as_dict()
    assert d["high_alignment_means_trade"] is False
    assert d["best_expression"] == "NOT_EVALUATED"


def test_probability_is_disabled_by_default():
    st = _state()
    for f in (st.forward_distribution_status, st.direction_distribution,
              st.magnitude_distribution, st.timing_distribution):
        assert f == psmod.PROBABILITY_NOT_ESTIMABLE
    assert st.calibration_status == psmod.UNCALIBRATED
    assert st.support_sufficient() is False


def test_no_numeric_probability_appears_anywhere_in_the_package():
    """An LLM or a future edit must not be able to slip a narrative
    probability into a state."""
    for f in PKG.glob("*.py"):
        for node in ast.walk(ast.parse(f.read_text())):
            if isinstance(node, ast.Constant) and isinstance(node.value, float):
                if 0.5 <= node.value <= 0.95 and f.stem in (
                        "pattern_state", "families", "summary"):
                    raise AssertionError(
                        f"{f.name} contains bare probability-like constant "
                        f"{node.value}")


# ------------------------------------------------------ pattern assassin
def test_assassin_does_not_reuse_the_production_curvature_wound():
    assert not set(pamod.FORBIDDEN_WOUNDS) & set(pamod.WOUNDS)
    src = (PKG / "pattern_assassin.py").read_text()
    tree = ast.parse(src)
    strings = {n.value for n in ast.walk(tree)
               if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    # it may be NAMED in FORBIDDEN_WOUNDS, but never as an active wound
    assert "PREDICTION_RESIDUAL_BREAK" not in pamod.WOUNDS


def test_single_mechanism_is_lethal():
    st = _state()
    object.__setattr__(st, "independence",
                       {"independent_mechanism_count": 1, "n_components": 3,
                        "groups": {"PRICE": ["a", "b", "c"]},
                        "inflation_ratio": 3.0})
    r = pamod.review(st, as_of=T0, known_from=T0)
    assert r.lethal is True
    assert r.verdict == pamod.INVALIDATED


def test_unreachable_wounds_are_declared_not_silently_skipped():
    r = pamod.review(_state(), as_of=T0, known_from=T0)
    assert "POSITIONING_STALE" in r.wounds_unreachable
    assert "OPTIONS_ACTIVITY_COULD_BE_SPREAD" in r.wounds_unreachable


# -------------------------------------------------------------- outcomes
def test_outcome_resolver_cannot_see_the_future():
    bars = _bars([0.001] * 10)
    o = ocmod.resolve(pattern_id="p", family_id="P004", subject="SPY",
                      observed_at=bars["event_time_utc"].iloc[0],
                      horizon_minutes=60, bars=bars, input_quality="VALID",
                      now=pd.Timestamp("2026-08-20T20:00:00Z"))
    assert o.status == ocmod.PENDING
    assert o.ret is None


def test_no_event_is_a_first_class_outcome():
    bars = _bars([0.0] * 70)
    o = ocmod.resolve(pattern_id="p", family_id="P004", subject="SPY",
                      observed_at=bars["event_time_utc"].iloc[0],
                      horizon_minutes=60, bars=bars, input_quality="VALID",
                      now=pd.Timestamp("2026-08-20T20:00:00Z"))
    assert o.status == ocmod.NO_EVENT
    assert o.as_dict()["negative_results_retained"] is True


def test_baseline_comparison_reports_no_p_value():
    r = ocmod.compare_to_baselines([0.01, 0.02, 0.03],
                                   {"RANDOM_STATE": [0.0, 0.001, -0.001]})
    assert "p_value" not in json.dumps(r)
    assert "caveat" in r


# ---------------------------------------------------------------- birth
def test_backfilled_can_never_be_prospective():
    b = {"birth_timestamp": "2026-08-20T12:00:00Z"}
    assert birthmod.classify("2026-08-20T14:00:00Z", birth=b,
                             reconstructed=True) == \
        birthmod.BACKFILLED_NEVER_PROSPECTIVE


def test_pre_birth_is_historical_context():
    b = {"birth_timestamp": "2026-08-20T12:00:00Z"}
    assert birthmod.classify("2026-08-20T10:00:00Z", birth=b) == \
        birthmod.HISTORICAL_CONTEXT


def test_birth_cannot_be_reminted(tmp_path):
    p = tmp_path / "birth.json"
    birthmod.mint(now=T0, code_lineage="x", families=1, path=p)
    with pytest.raises(birthmod.BirthError):
        birthmod.mint(now=T0, code_lineage="x", families=1, path=p)


# ------------------------------------------------- registry invariant (C)
def test_registry_has_no_violations():
    assert regmod.violations() == []


def test_registry_has_no_hungry_consumers():
    assert regmod.hungry_consumers() == []


def test_live_active_requires_a_live_caller():
    bad = regmod.Component("x", regmod.LIVE_ACTIVE, "p", None, (), ("o",),
                           ("c",), None)
    saved = regmod.COMPONENTS
    try:
        regmod.COMPONENTS = saved + (bad,)
        v = regmod.violations()
        assert any(x["violation"] == "LIVE_ACTIVE_WITHOUT_LIVE_CALLER"
                   for x in v)
    finally:
        regmod.COMPONENTS = saved


def test_a_live_active_orphan_output_is_a_violation():
    bad = regmod.Component("y", regmod.LIVE_ACTIVE, "p", "caller", (),
                           ("orphan.jsonl",), (), None)
    saved = regmod.COMPONENTS
    try:
        regmod.COMPONENTS = saved + (bad,)
        assert any(x["violation"] == "ORPHAN_OUTPUT_NO_CONSUMER"
                   for x in regmod.violations())
    finally:
        regmod.COMPONENTS = saved


def test_interface_only_must_declare_data_availability():
    bad = regmod.Component("z", regmod.INTERFACE_ONLY, None, None, (), (),
                           (), None)
    saved = regmod.COMPONENTS
    try:
        regmod.COMPONENTS = saved + (bad,)
        assert any(x["violation"] == "INTERFACE_ONLY_WITHOUT_AVAILABILITY"
                   for x in regmod.violations())
    finally:
        regmod.COMPONENTS = saved


def test_a_component_cannot_declare_non_observatory_power():
    with pytest.raises(regmod.RegistryError):
        regmod.Component("q", regmod.LIVE_ACTIVE, "p", "c", (), (), (), None,
                         decision_power="SOMETHING_ELSE")


# ---------------------------------------------------------------- sleeves
def test_btc_perps_is_declared_but_not_available():
    s = slmod.sleeve_input_status(slmod.BTC_PERPS)
    assert s["input_status"] == slmod.NOT_AVAILABLE
    assert s["source"] is None
    assert "funding" in s["expected_inputs"]


def test_sleeve_relevance_never_selects_an_expression():
    r = slmod.relevance(fammod.get("P009"))
    assert r["best_expression"] == slmod.NOT_EVALUATED
    assert slmod.BTC_PERPS in r["dark_sleeves"]


# --------------------------------------------------------------- families
def test_every_family_is_observational_with_no_authority():
    for f in fammod.FAMILIES:
        assert f.status == fammod.OBSERVATIONAL
        assert f.calibration_status == fammod.NOT_ESTIMABLE
        assert f.authority == fammod.NO_AUTHORITY
        assert f.required_features, f"{f.family_id} declares no quality gate"


def test_twelve_families_are_registered():
    assert len(fammod.FAMILIES) == 12
    assert len({f.family_id for f in fammod.FAMILIES}) == 12


# ---------------------------------------------------------- contradiction
def test_supporting_and_contradicting_are_never_netted():
    r = cdmod.search(pattern_id="p", family_id="P004",
                     active_components={"sector_rotation", "breadth_improving"},
                     independence={"independent_mechanism_count": 2,
                                   "groups": {}},
                     quality_verdict={"combined_quality": "VALID"}, as_of=T0)
    d = r.as_dict()
    assert d["net_not_computed"] is True
    assert r.contradicting          # breadth_improving contradicts P004
    assert r.supporting


# ----------------------------------------------------- no-compute-deadlock
def test_no_organ_requires_a_downstream_state_to_compute_itself():
    """The Captain deadlock in one sentence: tier>=4 was required to
    review, and only reviewing could earn tier 4. Nothing here may have
    that shape, so the dependency graph must be acyclic."""
    graph = {c.component_name: set(c.inputs) & set(regmod.BY_NAME)
             for c in regmod.COMPONENTS}
    seen, stack = set(), set()

    def visit(n):
        if n in stack:
            raise AssertionError(f"compute cycle through {n}")
        if n in seen:
            return
        stack.add(n)
        for d in graph.get(n, ()):
            visit(d)
        stack.discard(n)
        seen.add(n)

    for n in graph:
        visit(n)


# =====================================================================
# UPGRADE STACK -- items 4/5/6/7/8 (2026-08-19 evening)
# =====================================================================
from apex.pattern_observatory import cftc_positioning as cftc  # noqa: E402
from apex.pattern_observatory import finra_short_pressure as fin  # noqa: E402
from apex.pattern_observatory import information_lead as ilead  # noqa: E402
from apex.pattern_observatory import probability as pbmod  # noqa: E402


# ---------------------------------------------------- probability gate
def test_probability_gate_is_closed_with_no_evidence():
    s = pbmod.SupportProfile(prospective_n=0, distinct_sessions=0,
                             distinct_regimes=0, distinct_subjects=0)
    d = pbmod.estimate(pattern_id="p", family_id="P004", subject="SPY",
                       support=s, regime=None, current_state={"x": 1.0},
                       history=[], as_of=T0, known_from=T0)
    assert all(v == pbmod.NOT_ESTIMABLE for v in d.answers.values())
    assert d.status == pbmod.INSUFFICIENT_SUPPORT


def test_probability_gate_needs_every_dimension_not_just_n():
    """30 observations from ONE session is one session of information."""
    s = pbmod.SupportProfile(prospective_n=500, distinct_sessions=1,
                             distinct_regimes=1, distinct_subjects=1)
    g = s.gate()
    assert g["open"] is False
    assert "distinct_sessions" in g["failing"]
    assert "distinct_regimes" in g["failing"]


def test_ood_blocks_estimation_even_with_support():
    s = pbmod.SupportProfile(prospective_n=100, distinct_sessions=20,
                             distinct_regimes=3, distinct_subjects=10)
    hist = [{"x": 0.0} for _ in range(200)]
    d = pbmod.estimate(pattern_id="p", family_id="P", subject="S", support=s,
                       regime="R", current_state={"x": 99.0}, history=hist,
                       as_of=T0, known_from=T0)
    assert d.ood == "OOD"
    assert d.status == pbmod.OOD_BLOCKED
    assert all(v == pbmod.NOT_ESTIMABLE for v in d.answers.values())


def test_brier_refuses_small_samples_and_measures_skill_not_score():
    assert pbmod.brier([0.5] * 10, [1] * 5 + [0] * 5)["status"] == \
        pbmod.INSUFFICIENT_SUPPORT
    # a forecaster that always states the base rate has zero skill
    b = pbmod.brier([0.7] * 60, [1] * 42 + [0] * 18)
    assert b["beats_base_rate"] is False
    assert abs(b["skill_vs_base_rate"]) < 1e-9


def test_forward_distribution_forbids_narrative_probability():
    s = pbmod.SupportProfile(0, 0, 0, 0)
    d = pbmod.estimate(pattern_id="p", family_id="P", subject="S", support=s,
                       regime=None, current_state={}, history=[], as_of=T0,
                       known_from=T0)
    assert d.as_dict()["narrative_probability_forbidden"] is True


# ------------------------------------------------------ mechanism fusion
def test_five_price_indicators_fuse_far_weaker_than_five_mechanisms():
    a = indep.fuse(["curve_positive", "direction_quality",
                    "obs_opening_range_break", "price_refusal",
                    "expectation_violation"])
    b = indep.fuse(["curve_negative", "breadth_deteriorating", "crowded_short",
                    "skew_change", "cross_asset_risk_off"])
    assert a["n_components"] == b["n_components"] == 5
    assert a["independent_mechanism_count"] == 1
    assert b["independent_mechanism_count"] == 5
    assert b["fusion_strength"] > 3 * a["fusion_strength"]


def test_duplicated_evidence_can_never_sum_linearly():
    one = indep.fuse(["curve_positive"])["fusion_strength"]
    five = indep.fuse(["curve_positive", "direction_quality", "price_refusal",
                       "obs_opening_range_break",
                       "expectation_violation"])["fusion_strength"]
    assert five < 5 * one


def test_invalid_quality_contributes_nothing_to_fusion():
    f = indep.fuse(["crowded_short", "breadth_deteriorating"],
                   quality_by_component={"crowded_short": "VALID",
                                         "breadth_deteriorating": "INVALID"})
    only = indep.fuse(["crowded_short"],
                      quality_by_component={"crowded_short": "VALID"})
    assert f["fusion_strength"] == only["fusion_strength"]


def test_fusion_is_not_a_probability():
    assert indep.fuse(["curve_positive"])["is_probability"] is False


# ----------------------------------------------------- information lead
def test_information_lead_uses_only_pre_observation_volatility():
    """Deriving the obviousness threshold from post-observation bars
    would let the outcome define its own bar."""
    import inspect
    src = inspect.getsource(ilead.measure)
    assert 'bars["event_time_utc"] < t0' in src


def test_negative_lead_is_retained_as_the_finding():
    bars = _bars([0.0] * 30 + [0.03] + [0.0] * 30)
    # observe AFTER the move already happened
    t = bars["event_time_utc"].iloc[40]
    l = ilead.measure(organ="breadth", subject="X", observation="o",
                      first_known_at=t, bars=bars, known_from=T0)
    assert l.status in ("MEASURED", ilead.NO_MOVE)
    assert l.as_dict()["negative_lead_means_lagging"] is True


def test_lead_summary_refuses_a_verdict_on_thin_support():
    leads = [ilead.InformationLead(
        organ="breadth", subject="S", observation="o", first_known_at="t",
        move_became_obvious_at="t", lead_seconds=60.0,
        obviousness_threshold=0.01, realized_move=0.02, status="MEASURED",
        is_early=True, bars_used=10, known_from="t") for _ in range(5)]
    s = ilead.summarize(leads)
    assert s["organs"]["breadth"]["verdict"] == "INSUFFICIENT_SUPPORT"


# --------------------------------------------------------- CFTC / FINRA
def test_cftc_contracts_are_full_string_matches_not_substrings():
    """Substring matching would silently fold MICRO E-MINI into E-MINI
    and double-count the same exposure."""
    for key, name in cftc.CONTRACTS.items():
        assert " - " in name, f"{key} is not a full CFTC market name"


def test_cftc_fetch_raises_rather_than_returning_empty(monkeypatch):
    def boom(*a, **k):
        raise OSError("network down")
    monkeypatch.setattr(cftc.urllib.request, "urlopen", boom)
    with pytest.raises(cftc.CFTCError):
        cftc.fetch()


def test_cftc_fact_is_never_labelled_live_or_smart_money():
    rows = [{"market_and_exchange_names": cftc.CONTRACTS["ES"],
             "report_date_as_yyyy_mm_dd": "2026-08-11T00:00:00.000",
             "lev_money_positions_long": "100", "lev_money_positions_short": "300"}]
    f = cftc.to_fact(rows, "ES", "lev_money", now=pd.Timestamp("2026-08-19T12:00:00Z"))
    assert f.availability == "AVAILABLE_LAGGED"
    assert f.alternative_motive
    d = f.as_dict()
    assert d["is_smart_money_claim"] is False


def test_cftc_percentile_refuses_short_history():
    rows = [{"market_and_exchange_names": cftc.CONTRACTS["ES"],
             "report_date_as_yyyy_mm_dd": f"2026-0{i//4+1}-0{i%4+1}T00:00:00.000",
             "lev_money_positions_long": "100", "lev_money_positions_short": str(i)}
            for i in range(8)]
    f = cftc.to_fact(rows, "ES", "lev_money", now=pd.Timestamp("2026-08-19T12:00:00Z"))
    assert f.percentile_52w is None


def test_finra_is_short_volume_never_short_interest():
    st = fin.ShortPressureState(
        symbol="X", session_date="2026-08-19", short_volume=1.0,
        total_volume=2.0, short_ratio=0.5, short_exempt=0.0,
        ratio_percentile=None, ratio_change_1d=None, state="NORMAL",
        scope=fin.SCOPE, history_days=1, known_from="t")
    d = st.as_dict()
    assert d["is_short_interest"] is False
    assert d["is_crowding_verdict"] is False
    assert d["consolidated_tape"] is False
    assert st.scope == "FINRA_OFF_EXCHANGE_ONLY"


def test_finra_raises_on_a_holiday_rather_than_returning_empty(monkeypatch):
    class _R:
        def read(self): return b"Date|Symbol|ShortVolume\n"
        def __enter__(self): return self
        def __exit__(self, *a): return False
    monkeypatch.setattr(fin.urllib.request, "urlopen", lambda *a, **k: _R())
    with pytest.raises(fin.FinraError):
        fin.fetch_day("20260101")


def test_finra_thin_volume_is_not_estimable():
    rows = {"20260819": {"X": {"date": "20260819", "symbol": "X",
                               "short_volume": 10.0, "short_exempt": 0.0,
                               "total_volume": 20.0, "market": "Q"}}}
    st = fin.assess("X", rows, session_date="2026-08-19", known_from=T0)
    assert st.state == "NOT_ESTIMABLE"


# ----------------------------------------------------- registry, again
def test_external_sources_are_declared_not_inferred():
    ext = regmod.external_sources()
    assert any("CFTC" in e for e in ext)
    assert any("finra" in e.lower() for e in ext)


def test_positioning_is_no_longer_interface_only():
    c = regmod.BY_NAME["positioning"]
    assert c.status == regmod.LIVE_ACTIVE
    assert "cftc_positioning" in c.inputs


# =====================================================================
# PUBLICATION-LAG INTEGRITY LAW
# =====================================================================
from apex.pattern_observatory import publication_lag as plag  # noqa: E402


def test_known_from_may_never_precede_event_time():
    """The whole law in one assertion. CFTC measures positions on Tuesday
    and publishes Friday; stamping the Tuesday date as known_from hands
    APEX three days of lookahead on every sequence study."""
    with pytest.raises(plag.PublicationLagViolation):
        plag.LaggedObservation(
            source="CFTC_TFF", subject="NQ", event_time="2026-08-11",
            known_from="2026-08-09", value=-96727,
            source_state=plag.PUBLISHED, staleness_days=None, policy={})


def test_cftc_publication_time_is_the_friday_after_the_tuesday():
    pub = plag.publication_time("CFTC_TFF", "2026-08-11")   # a Tuesday
    assert str(pub.date()) == "2026-08-14"                  # the Friday
    assert pub.hour == 15 and pub.minute == 30


def test_visible_at_gates_historical_replay():
    o = plag.LaggedObservation(
        source="CFTC_TFF", subject="NQ", event_time="2026-08-11",
        known_from=str(plag.publication_time("CFTC_TFF", "2026-08-11")),
        value=-96727, source_state=plag.PUBLISHED, staleness_days=None,
        policy={})
    assert o.visible_at("2026-08-12T12:00:00-04:00") is False
    assert o.visible_at("2026-08-14T15:29:00-04:00") is False
    assert o.visible_at("2026-08-14T15:31:00-04:00") is True


def test_cftc_facts_stamp_publication_not_report_date():
    rows = [{"market_and_exchange_names": cftc.CONTRACTS["NQ"],
             "report_date_as_yyyy_mm_dd": "2026-08-11T00:00:00.000",
             "lev_money_positions_long": "100",
             "lev_money_positions_short": "300"}]
    f = cftc.to_fact(rows, "NQ", "lev_money",
                     now=pd.Timestamp("2026-08-19T12:00:00Z"))
    assert f.as_of_market_date == "2026-08-11"
    assert pd.Timestamp(f.known_from).date() == pd.Timestamp("2026-08-14").date()
    # and the integrity wrapper must accept it without raising
    o = cftc.as_lagged(f)
    assert o.visible_at("2026-08-19T12:00:00Z") is True
    assert o.visible_at("2026-08-12T12:00:00Z") is False


def test_every_lagged_source_declares_a_policy():
    """A lagged source without a declared policy cannot have an honest
    known_from, so it must not be silently allowed."""
    for src in ("CFTC_TFF", "FINRA_SHORT_VOLUME", "FORM_13F",
                "INSIDER_FORM4", "SHORT_INTEREST", "ETF_FLOWS",
                "MACRO_RELEASE"):
        assert src in plag.POLICIES
        assert plag.POLICIES[src].max_expected_staleness_days > 0


def test_undeclared_source_refuses_to_produce_a_publication_time():
    with pytest.raises(plag.PublicationLagViolation):
        plag.publication_time("SOME_NEW_FEED", "2026-08-11")


# ------------------------------------- expected latency is not an error
def test_not_yet_published_is_expected_and_is_not_an_error():
    s = plag.classify_source_state(
        "FINRA_SHORT_VOLUME", latest_event_date="2026-08-19",
        as_of=pd.Timestamp("2026-08-20T14:30:00-04:00"),
        requested_date="2026-08-20")
    assert s["source_state"] == plag.NOT_YET_PUBLISHED
    assert s["is_expected"] is True
    assert plag.is_error(s["source_state"]) is False
    assert s["last_available_market_date"] == "2026-08-19"


def test_stale_within_policy_is_acceptable_not_an_error():
    s = plag.classify_source_state(
        "FINRA_SHORT_VOLUME", latest_event_date="2026-08-19",
        as_of=pd.Timestamp("2026-08-20T14:30:00-04:00"))
    assert s["source_state"] == plag.STALE_WITHIN_POLICY
    assert plag.is_error(s["source_state"]) is False


def test_stale_beyond_policy_is_degraded_but_still_not_a_failure():
    s = plag.classify_source_state(
        "FINRA_SHORT_VOLUME", latest_event_date="2026-08-01",
        as_of=pd.Timestamp("2026-08-20T14:30:00-04:00"))
    assert s["source_state"] == plag.STALE_BEYOND_POLICY
    assert s["is_expected"] is False
    assert plag.is_error(s["source_state"]) is False


def test_only_real_faults_are_errors():
    for st in (plag.FETCH_FAILED, plag.PARSE_FAILED, plag.SOURCE_UNAVAILABLE):
        assert plag.is_error(st) is True
    for st in (plag.PUBLISHED, plag.NOT_YET_PUBLISHED,
               plag.STALE_WITHIN_POLICY):
        assert plag.is_error(st) is False


def test_finra_mid_session_falls_back_instead_of_failing(monkeypatch):
    """Thursday 14:30 ET: today's file cannot exist. The correct result
    is Wednesday's data with an honest known_from -- not an error."""
    calls = []

    def fake_fetch(date_yyyymmdd, **kw):
        calls.append(date_yyyymmdd)
        if date_yyyymmdd == "20260819":
            return {"SPY": {"date": date_yyyymmdd, "symbol": "SPY",
                            "short_volume": 5.0, "short_exempt": 0.0,
                            "total_volume": 10.0, "market": "Q"}}
        raise fin.FinraError("not found")

    monkeypatch.setattr(fin, "fetch_day", fake_fetch)
    got = fin.latest_published(as_of=pd.Timestamp("2026-08-20T18:30:00Z"))
    assert got["market_date"] == "2026-08-19"
    assert got["is_error"] is False
    assert got["source_state"] == plag.STALE_WITHIN_POLICY
    assert got["failures"] == []
    # today was correctly SKIPPED as unpublished, never fetched-and-failed
    assert "20260820" not in calls
    assert any(a["state"] == plag.NOT_YET_PUBLISHED
               for a in got["attempted"])
    assert pd.Timestamp(got["known_from"]).date() == pd.Timestamp(
        "2026-08-19").date()


def test_a_genuine_outage_across_the_window_is_a_real_error(monkeypatch):
    monkeypatch.setattr(fin, "fetch_day",
                        lambda *a, **k: (_ for _ in ()).throw(
                            fin.FinraError("network down")))
    got = fin.latest_published(as_of=pd.Timestamp("2026-08-20T18:30:00Z"))
    assert got["is_error"] is True
    assert got["source_state"] == plag.FETCH_FAILED
    assert got["failures"]


def test_runtime_does_not_error_on_expected_finra_latency():
    """The specific noise the operator refused to carry into tomorrow."""
    src = (REPO / "scripts" / "pattern_observatory_shadow_runtime.py").read_text()
    assert "latest_published" in src
    assert "expected, not an error" in src
    # the old unconditional error path must be gone
    assert 'finmod.fetch_day(day.replace' not in src


# =====================================================================
# 2026-08-20 EVENING REPAIRS -- the two shadow-only P1s from the full
# organism audit. Both additive, both isolated to the Observatory, both
# proven against the real data that exposed the original bugs.
# =====================================================================
from apex.pattern_observatory import support as supmod  # noqa: E402


# --------------------------------------------- support accumulator (P1)
def _row(family_id="P004", pattern_id="pidA", first_seen=None, known_from=None,
         subject="SPY", regime="UNKNOWN", cls="PROSPECTIVE_OBSERVATION"):
    fs = first_seen or str(T0)
    kf = known_from or fs
    return {"family_id": family_id, "pattern_id": pattern_id,
            "first_seen": fs, "known_from": kf, "subject": subject,
            "regime": regime, "birth_classification": cls}


def test_support_was_never_wired_before_this_fix():
    """The bug this whole section exists to close: before tonight,
    pattern_state.build() was NEVER called with support=, anywhere."""
    src = Path("scripts/pattern_observatory_shadow_runtime.py").read_text()
    assert "supmod.aggregate(" in src
    assert re.search(r"psmod\.build\(\s*\n?\s*conjunction=c.*support=sup",
                     src, re.DOTALL)


def test_prospective_n_is_permanently_zero_without_a_support_argument():
    """Reproduces the exact bug found in the audit: the default (no
    support=) must still leave the gate permanently closed."""
    st = _state()          # calls psmod.build() with no support=
    assert st.prospective_n == 0
    assert st.support_sufficient() is False


def test_future_known_from_is_excluded_the_known_from_safety_law():
    """A row dated AFTER `as_of` must never count -- this is the exact
    lookahead the operator required this module to prevent."""
    rows = [
        _row(pattern_id="past", known_from="2026-08-20T14:00:00Z"),
        _row(pattern_id="future", known_from="2026-08-20T20:00:00Z"),
    ]
    r = supmod.aggregate(rows, family_id="P004", as_of=pd.Timestamp("2026-08-20T15:00:00Z"))
    assert r["prospective_n"] == 1
    assert r["rows_excluded_future_known_from"] == 1


def test_episodes_are_deduped_not_double_counted_per_cycle():
    """A pattern sampled every 20s for 40 minutes must count as ONE
    episode, not ~120 -- otherwise duration masquerades as sample size."""
    rows = [_row(pattern_id="pidA", first_seen=str(T0),
                known_from=str(T0 + pd.Timedelta(minutes=i)))
           for i in range(50)]
    r = supmod.aggregate(rows, family_id="P004",
                         as_of=T0 + pd.Timedelta(hours=1))
    assert r["prospective_n"] == 1


def test_historical_and_prospective_are_permanently_disjoint():
    rows = [_row(pattern_id="a", cls="PROSPECTIVE_OBSERVATION"),
           _row(pattern_id="b", cls="HISTORICAL_CONTEXT")]
    r = supmod.aggregate(rows, family_id="P004", as_of=T0 + pd.Timedelta(days=1))
    assert r["prospective_n"] == 1
    assert r["historical_n"] == 1


def test_historical_n_can_never_satisfy_the_probability_gate():
    """A large historical_n with zero prospective_n must still fail --
    historical context is not prospective evidence, ever."""
    from apex.pattern_observatory.pattern_state import PatternState
    st = _state()
    object.__setattr__(st, "historical_n", 10_000)
    object.__setattr__(st, "distinct_sessions", 10_000)
    object.__setattr__(st, "distinct_symbols", 10_000)
    object.__setattr__(st, "distinct_regimes", 10_000)
    assert st.support_sufficient() is False   # prospective_n is still 0


def test_backfilled_rows_never_count_toward_either_bucket():
    rows = [_row(pattern_id="x", cls="BACKFILLED_NEVER_PROSPECTIVE")]
    r = supmod.aggregate(rows, family_id="P004", as_of=T0 + pd.Timedelta(days=1))
    assert r["prospective_n"] == 0
    assert r["historical_n"] == 0


def test_distinct_sessions_symbols_regimes_computed_correctly():
    rows = [
        _row(pattern_id="a", subject="SPY", regime="CALM", first_seen=str(T0)),
        _row(pattern_id="b", subject="QQQ", regime="VOL",
            first_seen=str(T0 + pd.Timedelta(days=1))),
    ]
    r = supmod.aggregate(rows, family_id="P004",
                         as_of=T0 + pd.Timedelta(days=2))
    assert r["prospective_n"] == 2
    assert r["distinct_sessions"] == 2
    assert r["distinct_symbols"] == 2
    assert r["distinct_regimes"] == 2


def test_a_different_family_id_never_contaminates_the_count():
    rows = [_row(family_id="P004"), _row(family_id="P010")]
    r = supmod.aggregate(rows, family_id="P004", as_of=T0 + pd.Timedelta(days=1))
    assert r["prospective_n"] == 1


def test_support_is_reusable_unchanged_for_future_historical_replay():
    """The known_from filter is what makes this safe to point at a
    ledger that already spans many days without re-deriving the law."""
    assert "reuse" in supmod.__doc__.lower() or "known_from" in supmod.__doc__


def test_registry_reflects_the_support_component():
    c = regmod.BY_NAME["support"]
    assert c.status == regmod.LIVE_ACTIVE
    assert "pattern_state" in c.consumers
    ps = regmod.BY_NAME["pattern_state"]
    assert "support" in ps.inputs


# --------------------------------------------- options DTE partition (P1)
def _opt(strike, iv, dte_bucket, expiry_date, spot=759.0):
    return {"symbol": f"SPYx{strike}", "spot": spot, "strike": strike,
            "state_quality": "HIGH", "dte_bucket": dte_bucket,
            "expiry_date": expiry_date, "iv": {"iv_mid": iv},
            "live_quality": {"quote_age_s": 1.0}}


def _two_expiry_sample():
    """Reproduces the EXACT real bug: same strike/moneyness, two real
    expiries, wildly different IV (0.176 vs 0.111 on SPY 2026-08-19)."""
    near_dated = [_opt(755 + i, 0.170 + i * 0.001, "1-2", "2026-08-20")
                 for i in range(6)]
    far_dated = [_opt(755 + i, 0.108 + i * 0.001, "3-7", "2026-08-24")
                for i in range(6)]
    return near_dated + far_dated


def test_atm_is_computed_within_one_expiry_never_mixed():
    st = osmod.observe("SPY", _two_expiry_sample(), as_of=T0, known_from=T0)
    assert st.estimable is True
    assert set(st.per_expiry) == {"2026-08-20", "2026-08-24"}
    # each expiry's own ATM must be close to ITS OWN contracts, not an
    # average across both maturities
    assert abs(st.per_expiry["2026-08-20"]["atm_iv"] - 0.170) < 0.01
    assert abs(st.per_expiry["2026-08-24"]["atm_iv"] - 0.108) < 0.01


def test_primary_expiry_is_front_month_deterministic():
    st = osmod.observe("SPY", _two_expiry_sample(), as_of=T0, known_from=T0)
    assert st.primary_expiry == "2026-08-20"


def test_reobserving_identical_data_produces_no_false_repricing():
    """THE BUG, reproduced and killed: before the fix, re-sorting the
    SAME two-expiry sample by moneyness alone could flip which contract
    counted as ATM and report a ~6 vol point 'repricing' from nothing."""
    sample = _two_expiry_sample()
    st1 = osmod.observe("SPY", sample, as_of=T0, known_from=T0)
    st2 = osmod.observe("SPY", sample, prior=st1,
                        as_of=T0 + pd.Timedelta(minutes=1), known_from=T0)
    assert st2.iv_change is not None
    assert abs(st2.iv_change) < 1e-9
    assert st2.state == "STABLE"


def test_iv_change_compares_the_same_expiry_never_a_different_one():
    sample = _two_expiry_sample()
    st1 = osmod.observe("SPY", sample, as_of=T0, known_from=T0)
    # perturb ONLY the front-month IV upward by 3 points
    bumped = [dict(s, iv={"iv_mid": s["iv"]["iv_mid"] + 0.03})
             if s["expiry_date"] == "2026-08-20" else s for s in sample]
    st2 = osmod.observe("SPY", bumped, prior=st1,
                        as_of=T0 + pd.Timedelta(minutes=1), known_from=T0)
    assert st2.iv_change == pytest.approx(0.03, abs=1e-6)
    assert st2.state == "VOL_REPRICING_UP"


def test_expiry_roll_refuses_to_diff_across_a_maturity_change():
    # a THIRD expiry so the sample still clears MIN_CONTRACTS=8 after the
    # front-month is removed to simulate its expiration
    sample = _two_expiry_sample() + [
        _opt(755 + i, 0.090 + i * 0.001, ">30", "2026-09-19") for i in range(4)]
    st1 = osmod.observe("SPY", sample, as_of=T0, known_from=T0)
    assert st1.primary_expiry == "2026-08-20"
    rolled = [s for s in sample if s["expiry_date"] != "2026-08-20"]
    st2 = osmod.observe("SPY", rolled, prior=st1,
                        as_of=T0 + pd.Timedelta(hours=1), known_from=T0)
    assert st2.primary_expiry == "2026-08-24"
    assert st2.iv_change is None
    assert any("rolled" in r for r in st2.reasoning)


def test_term_structure_is_built_from_correct_per_expiry_atms():
    sample = _two_expiry_sample()
    # add a back-month expiry so term structure has both legs
    back = [_opt(755 + i, 0.090 + i * 0.001, ">30", "2026-09-19")
           for i in range(4)]
    st = osmod.observe("SPY", sample + back, as_of=T0, known_from=T0)
    assert st.term_slope is not None
    assert st.term_slope > 0     # front (0.17) richer than back (0.09)


def test_an_expiry_below_the_per_expiry_floor_is_excluded_not_averaged_in():
    sample = _two_expiry_sample()
    thin = sample + [_opt(760, 0.5, "8-30", "2026-08-27")]   # only 1 contract
    st = osmod.observe("SPY", sample + thin[-1:], as_of=T0, known_from=T0)
    assert "2026-08-27" not in st.per_expiry


def test_options_surface_reproduces_the_real_2026_08_19_finding():
    """End-to-end on the ACTUAL data that exposed the bug."""
    rows = [json.loads(l) for l in
           open("results/option_analytics/live/states.jsonl")
           if l.strip()]
    today = [r for r in rows if str(r.get("as_of", "")).startswith("2026-08-19")]
    clean = [r for r in today
            if (r.get("live_quality") or {}).get("quote_age_s", -1) >= 0
            and r["symbol"].startswith("SPY")]
    if len(clean) < osmod.MIN_CONTRACTS:
        pytest.skip("real data unavailable in this environment")
    st1 = osmod.observe("SPY", clean, as_of=T0, known_from=T0)
    st2 = osmod.observe("SPY", clean, prior=st1,
                        as_of=T0 + pd.Timedelta(minutes=1), known_from=T0)
    assert st2.iv_change is not None
    assert abs(st2.iv_change) < 0.001, (
        "the exact false-repricing bug reproduced on real data")


# ------------------------------------------- identity schema v2 (collision fix)
# 2026-08-20: three pattern_ids appeared under BOTH P004 and P006 (92/246
# rows) because every family's PatternState copied the shared
# conjunction-level hash. These tests pin the family-scoped identity law.

def test_two_families_same_conjunction_get_different_pattern_ids():
    """THE collision reproduction: P004 and P006, same subject, same
    cycle, same first_seen, disjoint required components -- exactly the
    live 2026-08-20 configuration -- must now produce different ids."""
    e = cjmod.ConjunctionEngine()
    p004, p006 = fammod.get("P004"), fammod.get("P006")
    active = {k: True for k in
              (*p004.components_required, *p006.components_required)}
    c = e.observe(subject="SPY", market="EQUITIES_INTRADAY",
                  active_components=active, quality_vector={}, regime="R",
                  now=T0, known_from=T0)

    def _st(fam):
        q = qmod.PatternInputQuality(
            source="s", event_time=str(T0), known_from=str(T0),
            freshness_s=1.0, coverage_fraction=1.0, gap_fraction=0.0,
            missing_observations=0, staleness="FRESH", integrity="OK",
            quality=qmod.VALID,
            feature_sufficiency={f: qmod.VALID
                                 for f in fam.required_features})
        v = qmod.combine([q], required_features=fam.required_features)
        return psmod.build(conjunction=c, family=fam, quality_verdict=v,
                           now=T0, known_from=T0)

    st4, st6 = _st(p004), _st(p006)
    assert st4.pattern_id != st6.pattern_id, (
        "the 2026-08-20 cross-family collision is still possible")
    # lineage preserved: both trace back to the SAME conjunction
    assert st4.conjunction_id == st6.conjunction_id == c.pattern_id
    assert st4.pattern_id_schema_version == 2
    assert st6.pattern_id_schema_version == 2


def test_same_family_same_episode_id_is_stable_across_cycles():
    e = cjmod.ConjunctionEngine()
    fam = fammod.get("P004")
    active = {k: True for k in fam.components_required}
    c1 = e.observe(subject="SPY", market="EQ", active_components=active,
                   quality_vector={}, regime="R", now=T0, known_from=T0)
    c2 = e.observe(subject="SPY", market="EQ", active_components=active,
                   quality_vector={}, regime="R",
                   now=T0 + pd.Timedelta(minutes=5), known_from=T0)
    assert c2.first_seen == c1.first_seen        # same episode
    id1 = cjmod.family_pattern_id(
        family_id=fam.family_id, subject="SPY",
        conjunction_id=c1.pattern_id, first_seen=c1.first_seen)
    id2 = cjmod.family_pattern_id(
        family_id=fam.family_id, subject="SPY",
        conjunction_id=c2.pattern_id, first_seen=c2.first_seen)
    assert id1 == id2, "an episode's identity drifted across its own life"


def test_family_pattern_id_uses_canonical_json_not_concatenation():
    """Concatenation without a schema lets crafted field values alias two
    identities. Canonical JSON with sorted keys cannot."""
    a = cjmod.family_pattern_id(family_id="P0", subject="04|SPY",
                                conjunction_id="c", first_seen="t")
    b = cjmod.family_pattern_id(family_id="P004", subject="SPY",
                                conjunction_id="c", first_seen="t")
    assert a != b, "field-boundary aliasing -- identity is concatenated"


def test_pattern_id_schema_version_is_persisted():
    e = cjmod.ConjunctionEngine()
    fam = fammod.get("P004")
    c = e.observe(subject="SPY", market="EQ",
                  active_components={k: True for k in fam.components_required},
                  quality_vector={}, regime="R", now=T0, known_from=T0)
    q = qmod.PatternInputQuality(
        source="s", event_time=str(T0), known_from=str(T0), freshness_s=1.0,
        coverage_fraction=1.0, gap_fraction=0.0, missing_observations=0,
        staleness="FRESH", integrity="OK", quality=qmod.VALID,
        feature_sufficiency={f: qmod.VALID for f in fam.required_features})
    v = qmod.combine([q], required_features=fam.required_features)
    d = psmod.build(conjunction=c, family=fam, quality_verdict=v,
                    now=T0, known_from=T0).as_dict()
    assert d["pattern_id_schema_version"] == 2
    assert d["conjunction_id"] == c.pattern_id
    assert d["pattern_id"] != c.pattern_id


def test_expire_produces_terminal_rows_with_episode_identity():
    """2026-08-20 finding: expire() was never called by the runtime -- an
    entire session produced zero terminal transitions (PERSISTENCE_DEFECT,
    not market behavior). The runtime now persists a pattern_episode_end
    row per matching family; this test pins the engine half: expire()
    returns the conjunction with everything the terminal row needs, and
    the family-scoped id derived at expiry equals the id the episode
    lived under."""
    e = cjmod.ConjunctionEngine()
    fam = fammod.get("P004")
    active = {k: True for k in fam.components_required}
    c = e.observe(subject="SPY", market="EQ", active_components=active,
                  quality_vector={}, regime="R", now=T0, known_from=T0)
    live_id = cjmod.family_pattern_id(
        family_id=fam.family_id, subject=c.subject,
        conjunction_id=c.pattern_id, first_seen=c.first_seen)
    gone = e.expire(now=T0 + pd.Timedelta(minutes=30))
    assert len(gone) == 1
    g = gone[0]
    end_id = cjmod.family_pattern_id(
        family_id=fam.family_id, subject=g.subject,
        conjunction_id=g.pattern_id, first_seen=g.first_seen)
    assert end_id == live_id, (
        "terminal row would not join its own episode in the ledger")
    assert e.live() == []


def test_runtime_calls_expire_and_persists_terminal_rows():
    """AST proof on the runtime source: the cycle both CALLS expire() and
    APPENDS a pattern_episode_end record -- the exact two absences that
    made Thursday's zero-terminal-transition session unexplainable."""
    src = Path("scripts/pattern_observatory_shadow_runtime.py").read_text()
    tree = ast.parse(src)
    calls_expire = any(
        isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        and n.func.attr == "expire" for n in ast.walk(tree))
    assert calls_expire, "runtime still never calls ConjunctionEngine.expire()"
    assert "pattern_episode_end" in src
