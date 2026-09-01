"""PHASE 2 -- PULSE and the Digital Market Twin must tell the truth.

The tests that matter most are the ones that prove PULSE CANNOT lie:
a missing measurement can never present itself as a number, a
reconstruction can never contain the future, and one economic
observation can never become two.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from apex.intraday.sessions import Session
from apex.organism.microstructure import micro_state
from apex.pulse import parity
from apex.pulse.compose import compose, _dt
from apex.pulse.historical import assert_no_future
from apex.pulse.rolling import MIN_COVERAGE, RollingStore
from apex.pulse.twin import (NOT_AVAILABLE, NOT_ESTIMABLE, QUALITIES,
                             SESSION_INAPPLICABLE, STALE, TwinState,
                             TwinViolation, UNKNOWN, VALID, Field,
                             absent, adopt, ok, verify_packet)

REGULAR = "2026-09-01T15:00:04+00:00"     # 11:00 ET Tuesday
PREMKT = "2026-09-01T12:00:04+00:00"      # 08:00 ET Tuesday


def snap(qt=REGULAR, **over):
    s = {"latestQuote": {"bp": 762.90, "ap": 762.94, "bs": 3, "as": 5,
                         "t": qt},
         "prevDailyBar": {"c": 760.10, "v": 70_000_000,
                          "t": "2026-08-31T20:00:00Z"},
         "dailyBar": {"o": 761.00, "h": 763.50, "l": 760.50,
                      "v": 21_000_000, "vw": 762.20, "t": REGULAR},
         "minuteBar": {"v": 120_000, "t": REGULAR}}
    s.update(over)
    return s


def built(when=REGULAR, **kw):
    return compose(subject="SPY", snapshot=kw.pop("snapshot", snap()),
                   scheduled_time=when, capture_start=when,
                   complete_time=when, universe_version="uv0",
                   **kw).seal()


# ------------------------------------ MISSING IS NEVER A MEASUREMENT

def test_an_untrustworthy_field_may_not_carry_a_number():
    """The single most important invariant in the schema."""
    for q in (NOT_ESTIMABLE, NOT_AVAILABLE, UNKNOWN, STALE,
              SESSION_INAPPLICABLE):
        with pytest.raises(TwinViolation):
            Field(0.0, q, "src")
        with pytest.raises(TwinViolation):
            Field(-1.5, q, "src")


def test_a_valid_field_may_not_be_empty():
    with pytest.raises(TwinViolation):
        ok(None, source="src")


def test_the_quality_vocabulary_is_closed():
    with pytest.raises(TwinViolation):
        Field(1.0, "PROBABLY_FINE", "src")
    assert len(QUALITIES) == 7


def test_a_sentinel_from_another_engine_is_honoured_not_overridden():
    f = adopt("NOT_ESTIMABLE", source="micro_state")
    assert f.quality == NOT_ESTIMABLE and f.value is None
    assert not f.usable
    assert adopt(3.5, source="x").usable


def test_missing_nbbo_yields_absence_not_zero():
    p = built(snapshot=snap(latestQuote={}))
    for k in ("mid", "spread_bps", "nbbo_size_imbalance"):
        f = p["features"][k]
        assert f["q"] == NOT_AVAILABLE and f["v"] is None


def test_missing_quote_sizes_do_not_become_a_balanced_book():
    """PULSE-001. Prices are present, sizes are not: the size-derived
    features must withhold while the price-derived ones proceed."""
    q = {"bp": 762.90, "ap": 762.94, "t": REGULAR}
    p = built(snapshot=snap(latestQuote=q))
    assert p["features"]["mid"]["q"] == VALID
    assert p["features"]["spread_bps"]["q"] == VALID
    for k in ("nbbo_size_imbalance", "touch_size"):
        assert p["features"][k]["q"] == NOT_ESTIMABLE
        assert p["features"][k]["v"] is None


def test_micro_state_withholds_size_features_without_sizes():
    """The same law inside the reused primitive."""
    def qt(i, sized):
        d = {"t": f"2026-09-01T15:00:{i % 60:02d}.{i:06d}Z",
             "bp": 100.0, "ap": 100.02}
        if sized:
            d.update({"bs": 5, "as": 7})
        return d
    tr = [{"t": f"2026-09-01T15:00:{i % 60:02d}.{i:06d}Z",
           "p": 100.01, "s": 100} for i in range(40)]
    with_sizes = micro_state(tr, [qt(i, True) for i in range(40)])
    without = micro_state(tr, [qt(i, False) for i in range(40)])
    assert isinstance(with_sizes["microprice_disp_bps_mean"], float)
    # the defect produced -10000.0 here
    assert without["microprice_disp_bps_mean"] == NOT_ESTIMABLE
    assert without["nbbo_imbalance_mean"] == NOT_ESTIMABLE
    # size-independent features are unaffected
    assert isinstance(without["spread_bps_median"], float)


# ----------------------------------------------- SESSION SEMANTICS

def test_cash_open_features_are_inapplicable_before_the_open():
    p = built(PREMKT)
    assert p["market_session"] == Session.PREMARKET.value
    for k in ("cash_open_return_bps", "overnight_gap_bps"):
        assert p["features"][k]["q"] == SESSION_INAPPLICABLE


def test_a_stale_quote_is_stale_not_current():
    old = (_dt(REGULAR) - timedelta(minutes=30)).isoformat()
    p = built(snapshot=snap(latestQuote={
        "bp": 762.90, "ap": 762.94, "bs": 3, "as": 5, "t": old}))
    assert p["features"]["mid"]["q"] == STALE
    assert p["features"]["mid"]["v"] is None
    assert "tolerance" in p["features"]["mid"]["note"]


# ------------------------------------------------------- PROVENANCE

def test_known_from_is_the_latest_ingredient_not_the_schedule():
    st = TwinState(subject="X", scheduled_time="2026-09-01T15:00:00+00:00",
                   capture_start="2026-09-01T15:00:00+00:00",
                   state_complete_time="2026-09-01T15:00:05+00:00",
                   market_session="REGULAR", universe_version="uv0",
                   tier="TIER_2_BROAD")
    st.features["a"] = ok(1.0, source="s",
                          as_of="2026-09-01T15:00:04+00:00")
    p = st.seal()
    assert p["known_from"] == "2026-09-01T15:00:05+00:00"
    assert p["timing"]["capture_latency_ms"] == 5000.0


def test_a_tampered_packet_fails_verification():
    p = built()
    assert verify_packet(p) == []
    p["features"]["mid"]["v"] = 999.0
    assert any("PACKET_HASH_MISMATCH" in x for x in verify_packet(p))


def test_quality_census_and_missingness_are_reported():
    p = built()
    dq = p["data_quality"]
    assert sum(dq["census"].values()) == len(p["features"])
    assert 0.0 <= dq["missingness"] <= 1.0


# -------------------------------------------------- IDENTITY (§24)

def test_the_same_observation_recomputed_keeps_one_identity():
    a = built()
    b = compose(subject="SPY", snapshot=snap(),
                scheduled_time=REGULAR,
                capture_start="2026-09-01T15:00:09+00:00",
                complete_time="2026-09-01T15:00:11+00:00",
                universe_version="uv0").seal()
    assert a["state_id"] == b["state_id"]
    assert a["packet_hash"] != b["packet_hash"]


def test_a_different_minute_is_a_different_observation():
    a = built()
    b = built("2026-09-01T15:01:04+00:00")
    assert a["state_id"] != b["state_id"]


def test_a_different_universe_is_a_different_observation():
    a = built()
    b = compose(subject="SPY", snapshot=snap(), scheduled_time=REGULAR,
                capture_start=REGULAR, complete_time=REGULAR,
                universe_version="DIFFERENT").seal()
    assert a["state_id"] != b["state_id"]


# ------------------------------------------------- ROLLING WINDOWS

def test_a_window_we_did_not_observe_is_not_estimable():
    r = RollingStore()
    base = _dt(REGULAR)
    for i in range(3):
        r.observe("SPY", at=base + timedelta(minutes=i), price=100 + i)
    out = r.ret_bps("SPY", 60, now=base + timedelta(minutes=3))
    assert out["value"] is None
    assert out["coverage"] < MIN_COVERAGE


def test_a_sufficiently_observed_window_returns_a_real_number():
    r = RollingStore()
    base = _dt(REGULAR)
    for i in range(6):
        r.observe("SPY", at=base + timedelta(minutes=i),
                  price=100.0 * (1 + i / 1000))
    out = r.ret_bps("SPY", 5, now=base + timedelta(minutes=5))
    assert out["value"] == pytest.approx(50.0, abs=1.0)


def test_the_store_is_bounded_and_replaying_does_not_double_count():
    r = RollingStore(retention_min=10)
    base = _dt(REGULAR)
    for i in range(60):
        r.observe("SPY", at=base + timedelta(minutes=i), price=100.0)
    assert len(r._obs["SPY"]) <= 11
    assert r.observe("SPY", at=base + timedelta(minutes=59),
                     price=100.0) is False


# --------------------------------------------- NO FUTURE (§18/§27)

def test_a_reconstruction_carrying_the_future_is_caught():
    t = REGULAR
    p = built(t)
    p["evidence_class"] = "HISTORICAL_REPLAY"
    assert assert_no_future(p, t) == []
    p["features"]["mid"]["as_of"] = "2026-09-01T16:00:00+00:00"
    assert any("AFTER" in x for x in assert_no_future(p, t))


def test_a_reconstruction_may_not_be_labelled_live():
    p = built(REGULAR)          # evidence_class LIVE_PROSPECTIVE
    assert any("never be labelled live" in x
               for x in assert_no_future(p, REGULAR))


# ------------------------------------------------------- PARITY

def test_the_parity_declaration_is_checked_against_real_packets():
    live = built()
    hist = built()
    hist["evidence_class"] = "HISTORICAL_REPLAY"
    a = parity.audit(live, hist)
    assert a["verdict"] == "PARITY_DECLARATION_HOLDS", a["findings"]


def test_rolling_returns_are_declared_live_only():
    """They come from PULSE's own observations. History has no record
    of what PULSE saw before PULSE existed."""
    assert parity.MATRIX["ret_5m_bps"]["status"] == parity.LIVE_ONLY


def test_rebuilt_session_aggregates_are_declared_approximate():
    for k in ("session_high", "session_volume", "session_vwap"):
        assert parity.MATRIX[k]["status"] == parity.APPROXIMATE


# ------------------------------------------------- NO AUTHORITY

def test_the_twin_carries_no_decision_authority():
    p = built()
    assert p["decision_power"] == "NONE_STATE"
    blob = str(p).upper()
    for verb in ("BUY", "SELL", "ATTACK_READY", "FUND", "ORDER"):
        assert verb not in blob


# ============ ASYNCHRONOUS REALITY (operator proof #2) ============

def test_a_packet_states_how_wide_its_moment_really_is():
    """Ingredients arrive at different times. A packet that hides
    that is a forgery with good intentions."""
    st = TwinState(subject="X", scheduled_time=REGULAR,
                   capture_start="2026-09-01T15:00:00+00:00",
                   state_complete_time="2026-09-01T15:00:05+00:00",
                   market_session="REGULAR", universe_version="uv0",
                   tier="TIER_1_DEEP")
    st.features["mid"] = ok(1.0, source="sip",
                            as_of="2026-09-01T15:00:04.800000+00:00")
    st.features["catalyst_fact_x"] = ok(
        "EARNINGS", source="edgar",
        as_of="2026-09-01T14:30:00+00:00")
    t = st.seal()["timing"]
    # oldest usable ingredient is 30 minutes old
    assert t["capture_span_ms"] == pytest.approx(1_805_000, abs=2000)
    assert t["max_field_age_ms"] > 1_000_000
    # but the CRITICAL price field is fresh, and that is reported
    # separately so a reader is not misled by the worst field
    assert t["max_critical_field_age_ms"] == pytest.approx(200, abs=50)


def test_each_field_carries_its_own_age():
    st = TwinState(subject="X", scheduled_time=REGULAR,
                   capture_start=REGULAR, state_complete_time=REGULAR,
                   market_session="REGULAR", universe_version="uv0",
                   tier="TIER_2_BROAD")
    st.features["a"] = ok(1.0, source="s",
                          as_of="2026-09-01T14:59:00+00:00")
    f = st.seal()["features"]["a"]
    assert f["age_ms"] == pytest.approx(64_000, abs=1000)


def test_known_from_may_not_precede_as_of():
    """A fact cannot be knowable before it is true."""
    with pytest.raises(TwinViolation):
        ok(1.0, source="edgar", as_of="2026-09-01T15:00:00+00:00",
           known_from="2026-09-01T14:00:00+00:00")


def test_known_from_gates_age_not_as_of():
    """An 8-K true at 02:55 but published at 03:10 is knowable from
    03:10; only that may gate a decision."""
    f = ok("8-K", source="edgar", as_of="2026-09-01T02:55:00+00:00",
           known_from="2026-09-01T03:10:00+00:00")
    assert f.gate_time() == "2026-09-01T03:10:00+00:00"


# ============ ENRICHMENT / SELECTION BIAS (operator proof #3) ======

def test_the_three_causes_of_missing_deep_state_stay_distinct():
    """'missing because boring' must never look like 'missing because
    the vendor failed'."""
    from apex.pulse.enrichment import (EnrichmentRecord,
                                       ATTEMPT_FAILED,
                                       DATA_NOT_AVAILABLE, eligibility)
    e = eligibility("SPY", tier1=True)
    r = EnrichmentRecord(e)
    r.request("options")
    r.request("deep_tape")
    r.failed("options", why="provider 503")
    r.unavailable("deep_tape", why="options do not trade premarket")
    rec = r.record()
    assert rec["failed"]["options"]["outcome"] == ATTEMPT_FAILED
    assert rec["not_available"]["deep_tape"]["outcome"] == \
        DATA_NOT_AVAILABLE
    assert "never collapse these" in rec["SELECTION_BIAS_LAW"]


def test_enrichment_records_the_rule_that_produced_the_coverage():
    from apex.pulse.enrichment import (ENRICHMENT_RULE_VERSION,
                                       MATERIAL_MOVE, eligibility)
    e = eligibility("XYZ", tier1=False, move_bps=350.0,
                    as_of=REGULAR)
    assert e["eligible"] and e["reason"] == MATERIAL_MOVE
    assert e["rule_version"] == ENRICHMENT_RULE_VERSION
    assert e["eligibility_known_from"] == REGULAR
    assert e["thresholds"]["material_move_bps"] == 200.0


def test_a_boring_subject_is_NOT_ENRICHED_with_a_stated_reason():
    from apex.pulse.enrichment import NOT_ENRICHED, eligibility
    e = eligibility("ZZZZZZ", tier1=False, move_bps=3.0,
                    relative_volume=0.9)
    if not e["eligible"]:
        assert e["reason"] == NOT_ENRICHED
        assert e["evidence"]["move_bps"] == 3.0


def test_a_reference_sample_breaks_the_confound():
    """Some ordinary subjects are enriched regardless of activity, or
    'deep state exists' becomes perfectly confounded with 'something
    was happening'."""
    from apex.pulse.enrichment import REFERENCE_SAMPLE, eligibility
    sampled = [s for s in
               (f"SYM{i}" for i in range(3000))
               if eligibility(s, tier1=False)["reason"]
               == REFERENCE_SAMPLE]
    assert 10 < len(sampled) < 200        # ~2% of 3000
    # deterministic: the SAME boring names, followed over time
    assert eligibility(sampled[0], tier1=False)["reason"] == \
        REFERENCE_SAMPLE


def test_an_unenriched_packet_says_so_explicitly():
    p = built()
    assert p["enrichment"]["enriched"] is False
    assert p["enrichment"]["reason"] == "NOT_ENRICHED"


# ==================== FRESHNESS POLICY ============================

def test_freshness_is_per_source_and_per_session():
    from apex.pulse import freshness as fr
    # the same 200s quote: broken mid-session, normal premarket
    assert not fr.is_fresh("sip_quote", Session.REGULAR, 200.0)["fresh"]
    assert fr.is_fresh("sip_quote", Session.PREMARKET, 200.0)["fresh"]


def test_an_event_does_not_decay():
    from apex.pulse import freshness as fr
    v = fr.is_fresh("catalyst_event", Session.REGULAR, 7200.0)
    assert v["fresh"] and v["tolerance_s"] is None


def test_an_undeclared_source_gets_the_strictest_rule():
    from apex.pulse import freshness as fr
    assert fr.tolerance_s("mystery_feed", Session.REGULAR) == 60.0


# ==================== CATALYST FACT vs INTERPRETATION =============

def test_official_fact_and_model_opinion_are_separate_fields():
    cat = {"catalyst_status": "EVENTS_PRESENT", "queried": True,
           "events_known": 2,
           "latest_event_time": "2026-09-01T02:55:00+00:00",
           "latest_event_known_from": "2026-09-01T03:10:00+00:00",
           "classification_event_type": "EARNINGS",
           "model_id": "LLM_DERIVED_INTERPRETATION",
           "directional_expectation": "NEGATIVE",
           "interpretation_known_from": "2026-09-01T03:12:00+00:00"}
    p = built(catalyst=cat)
    fact = p["features"]["catalyst_fact_events_known"]
    attributed = p["features"][
        "catalyst_semantic_directional_expectation"]
    unattributed = p["features"][
        "catalyst_semantic_classification_event_type"]
    assert fact["src"] == "catalyst_official_record"
    assert attributed["src"] == \
        "catalyst_llm:LLM_DERIVED_INTERPRETATION"
    assert "not an official fact" in attributed["note"]
    # an UNATTRIBUTED classification may not borrow a model's name
    assert unattributed["src"] == "catalyst_classifier:UNATTRIBUTED"
    assert "no recorded interpreter" in unattributed["note"]


def test_an_event_with_no_interpreter_says_so():
    cat = {"catalyst_status": "EVENTS_PRESENT", "queried": True,
           "events_known": 1,
           "latest_event_known_from": "2026-09-01T03:10:00+00:00",
           "interpretation_status": "INTERPRETATION_NOT_AVAILABLE"}
    f = built(catalyst=cat)["features"][
        "catalyst_semantic_directional_expectation"]
    assert f["q"] == NOT_AVAILABLE
    assert "no attributed interpreter" in f["note"]


def test_asked_and_found_nothing_differs_from_never_asked():
    asked = built(catalyst={"catalyst_status": "NO_RELEVANT_EVENT",
                            "queried": True, "events_known": 0})
    never = built()
    assert asked["features"]["catalyst_fact_status"]["v"] == \
        "NO_RELEVANT_EVENT"
    assert never["features"]["catalyst_fact_status"]["q"] == UNKNOWN
    assert "CATALYST_NOT_QUERIED" in \
        never["features"]["catalyst_fact_status"]["note"]


def test_an_unreachable_catalyst_is_a_provider_error():
    f = built(catalyst={"catalyst_status": "CATALYST_UNAVAILABLE",
                        "queried": False,
                        "why": "no ledger"})["features"]
    assert f["catalyst_fact_events_known"]["q"] == "PROVIDER_ERROR"


def test_a_replay_refuses_present_day_cognition_about_an_old_event():
    st = compose(subject="SPY", snapshot=snap(),
                 scheduled_time=REGULAR, capture_start=REGULAR,
                 complete_time=REGULAR, universe_version="uv0",
                 catalyst={"catalyst_status": "EVENTS_PRESENT",
                           "queried": True, "events_known": 1,
                           "classification_event_type": "EARNINGS",
                           "model_id": "today-model"},
                 evidence_class="HISTORICAL_REPLAY")
    feats = st.seal()["features"]
    # every interpretation layer, attributed or not, is suppressed
    for k in ("catalyst_semantic_event_type",
              "catalyst_semantic_classification_event_type",
              "catalyst_semantic_directional_expectation"):
        assert feats[k]["q"] == NOT_AVAILABLE, k
        assert "NOT_HISTORICALLY_AVAILABLE" in feats[k]["note"]
    # the FACTUAL record survives -- only cognition is refused
    assert feats["catalyst_fact_status"]["v"] == "EVENTS_PRESENT"


# ==================== PREMARKET PATH ==============================

def test_the_premarket_path_is_accumulated_from_our_own_eyes():
    from apex.pulse.premarket import PremarketPath
    pp = PremarketPath()
    base = _dt("2026-09-01T12:00:00+00:00")     # 08:00 ET
    for i, px in enumerate([100.0, 95.0, 92.0, 97.0, 99.0]):
        pp.observe("AXTI", at=base + timedelta(minutes=i), price=px)
    path = pp.path("AXTI", at=base + timedelta(minutes=4),
                   prior_close=100.0)
    assert path["status"] == "OBSERVED"
    assert path["low"] == 92.0 and path["high"] == 100.0
    # down 800bps at the low, recovered to -100bps: the AXTI shape
    assert path["premarket_return_bps"] == pytest.approx(-100, abs=1)
    assert path["premarket_travel_bps"] == pytest.approx(-100, abs=1)
    assert path["source"] == "PULSE_OWN_OBSERVATIONS"


def test_no_premarket_observations_is_not_a_flat_premarket():
    from apex.pulse.premarket import PremarketPath
    path = PremarketPath().path("XYZ", at=PREMKT, prior_close=10.0)
    assert path["status"] == "NO_PREMARKET_OBSERVATIONS"
    assert "not a flat premarket" in path["why"]


def test_premarket_accumulation_ignores_the_regular_session():
    from apex.pulse.premarket import PremarketPath
    pp = PremarketPath()
    assert pp.observe("SPY", at=REGULAR, price=100.0) is None


# ==================== OPTIONS SESSION SEMANTICS ===================

def test_options_absence_premarket_is_expected_not_unknown():
    p = built(PREMKT)
    f = p["features"]["opt_state"]
    assert f["q"] == SESSION_INAPPLICABLE
    assert "Friday" in f["note"]


def test_cross_asset_absence_is_not_available_not_zero():
    p = built()
    assert p["features"]["xasset_btc"]["q"] == NOT_AVAILABLE
    assert p["features"]["xasset_btc"]["v"] is None
