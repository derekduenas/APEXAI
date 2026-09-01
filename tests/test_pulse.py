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
    assert p["capture_latency_s"] == 5.0


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
