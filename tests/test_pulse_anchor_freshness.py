"""PULSE-010 -- ANCHOR_FRESHNESS_POLICY_V1: an anchor is measured in sessions.

Deterministic: no network, no clock, no vendor. Every calendar case is a
fixture against the exchange calendar that already governs PULSE.
"""
import json
from datetime import date, datetime, timedelta, timezone

import pytest

from apex.intraday.sessions import EARLY_CLOSES, ET, HOLIDAYS, Session, classify
from apex.pulse import anchor_freshness as A
from apex.pulse import compose as C
from apex.pulse import derived as D
from apex.pulse.compose import compose
from apex.pulse.historical import FACTORY_VERSION
from apex.pulse.twin import (NOT_AVAILABLE, NOT_ESTIMABLE, STALE, VALID,
                             Field, TwinViolation, verify_packet)

FROZEN = "/opt/apex-repo/results/pulse007_frozen_packets.jsonl"


def bar_t(d):
    """A vendor daily stamp the way the provider writes one: the session's ET
    midnight expressed in UTC. That is 04:00Z under EDT and 05:00Z under EST,
    so the offset is resolved per date rather than assumed."""
    midnight = datetime.combine(date.fromisoformat(d), datetime.min.time(), tzinfo=ET)
    return midnight.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def snap(*, prev_t="2026-08-31T04:00:00Z", prev=99.0, prev_v=1000, quote_t=None,
         day=True, prev_present=True):
    q = quote_t or "2026-09-01T13:44:59Z"
    s = {"latestQuote": {"bp": 100.0, "ap": 100.04, "bs": 3, "as": 5, "t": q},
         "latestTrade": {"p": 100.01, "t": q}}
    if prev_present:
        s["prevDailyBar"] = {"c": prev, "v": prev_v, "t": prev_t}
    if day:
        s["dailyBar"] = {"o": 99.5, "h": 101.0, "l": 99.0, "c": 100.0, "v": 5000,
                         "vw": 100.02, "t": "2026-09-01T04:00:00Z"}
        s["minuteBar"] = {"v": 20, "c": 100.0, "t": "2026-09-01T13:44:00Z"}
    return s


def built(snapshot=None, at="2026-09-01T13:45:00+00:00", **kw):
    return compose(subject="TEST", snapshot=snapshot if snapshot is not None else snap(),
                   scheduled_time=at, capture_start=at, complete_time=at,
                   universe_version="TEST", **kw).seal()


def f(p, name):
    return p["features"][name]


ANCHOR_DEPENDENT = ("prior_close_return_bps", "overnight_gap_bps", "relative_volume")
CURRENT_SESSION_FIELDS = ("session_open", "session_high", "session_low", "session_vwap",
                          "session_volume", "cash_open_return_bps", "mid", "spread_bps",
                          "nbbo_size_imbalance", "session_range_position", "vwap_distance_bps")


# ---------------------------------------------------------------- the contract
def test_the_policy_is_stated_versioned_and_measured_in_sessions():
    d = A.describe()
    assert d["version"] == "ANCHOR_FRESHNESS_POLICY_V1" == A.ANCHOR_FRESHNESS_POLICY_VERSION
    assert d["defect_closed"] == "LIVE-ANCHOR-STALENESS-V1"
    assert d["measured_in"].startswith("SESSIONS")
    assert "immediately preceding regular session" in d["rule"]
    assert "no tuned threshold" in " ".join(d.keys()).lower() or d["no_tuned_threshold"]
    for k in (A.CURRENT_SESSION_OPEN, A.IMMEDIATELY_PRECEDING, A.SESSIONS_MISSED,
              A.NO_PRIOR_SESSION, A.UNDATED, A.NOT_A_PRIOR_SESSION):
        assert k in d["classifications"]
    # the composer version advances with later bricks; what PULSE-010 pins is
    # that V0.2 exists and still records the defect it closed.
    assert C.COMPOSER_VERSION.startswith("PULSE_COMPOSE_V0.2")
    assert "LIVE-ANCHOR-STALENESS-V1" in C.COMPOSER_HISTORY["V0.2"]


def test_the_policy_uses_the_governed_calendar_not_utc_day_arithmetic():
    # 2026-09-07 is Labor Day. Naive "yesterday" from Tuesday 09-08 would be
    # the holiday; the calendar gives Friday 09-04.
    assert not A.is_trading_day(date(2026, 9, 7))
    assert A.expected_anchor_session("2026-09-08T13:45:00Z") == date(2026, 9, 4)
    # and a UTC instant before ET midnight belongs to the PREVIOUS session date
    assert A.expected_anchor_session("2026-09-02T01:00:00Z") == date(2026, 8, 31)


def test_no_quality_state_is_flattened_into_another():
    q = {A.SESSIONS_MISSED: STALE, A.NO_PRIOR_SESSION: NOT_AVAILABLE,
         A.UNDATED: NOT_ESTIMABLE, A.NOT_A_PRIOR_SESSION: NOT_ESTIMABLE}
    assert C._ANCHOR_QUALITY[A.SESSIONS_MISSED] == STALE
    assert C._ANCHOR_QUALITY[A.NO_PRIOR_SESSION] == NOT_AVAILABLE
    assert C._ANCHOR_QUALITY[A.UNDATED] == NOT_ESTIMABLE
    assert len({STALE, NOT_AVAILABLE, NOT_ESTIMABLE}) == 3


# ---------------------------------------------------------------- calendar cases
@pytest.mark.parametrize("anchor,packet,expected", [
    ("2026-09-01", "2026-09-02T13:45:00Z", True),      # consecutive sessions
    ("2026-09-04", "2026-09-08T13:45:00Z", True),      # Fri -> Tue over Labor Day
    ("2026-08-28", "2026-08-31T13:45:00Z", True),      # Fri -> Mon, plain weekend
    ("2026-11-25", "2026-11-27T14:45:00Z", True),      # -> the early-close session
    ("2026-11-27", "2026-11-30T14:45:00Z", True),      # early close -> next Monday
    ("2026-03-06", "2026-03-09T13:45:00Z", True),      # across the DST start
    ("2026-10-30", "2026-11-02T14:45:00Z", True),      # across the DST end
    ("2026-09-01", "2026-09-03T13:45:00Z", False),     # one session skipped
    ("2026-08-31", "2026-09-03T13:45:00Z", False),     # two skipped
])
def test_session_adjacency_across_the_calendar(anchor, packet, expected):
    r = A.classify_prior_close(anchor_stamp=bar_t(anchor), packet_session_date=packet)
    assert r["fresh"] is expected, r
    assert r["classification"] == (A.IMMEDIATELY_PRECEDING if expected else A.SESSIONS_MISSED)


@pytest.mark.parametrize("anchor", ["2026-11-26", "2026-09-07", "2026-09-05"])
def test_a_bar_dated_on_a_closed_day_is_not_a_session_close(anchor):
    """Thanksgiving, Labor Day and a Saturday: the exchange held no regular
    session, so a bar dated there is anomalous and cannot be judged current."""
    r = A.classify_prior_close(anchor_stamp=bar_t(anchor),
                               packet_session_date="2026-11-30T14:45:00Z"
                               if anchor.startswith("2026-11") else "2026-09-08T13:45:00Z")
    assert r["classification"] == A.NOT_A_TRADING_SESSION and r["fresh"] is False
    assert r["anchor_is_a_trading_day"] is False


def test_dst_is_handled_by_the_calendar_not_by_a_fixed_offset():
    """The same 04:00Z stamp is a different ET date across the DST boundary,
    and the policy must read the ET session date, not the UTC one."""
    edt = A.classify_prior_close(anchor_stamp="2026-09-01T04:00:00Z",
                                 packet_session_date="2026-09-02T13:45:00Z")
    est = A.classify_prior_close(anchor_stamp="2026-01-05T05:00:00Z",
                                 packet_session_date="2026-01-06T14:45:00Z")
    assert edt["fresh"] and est["fresh"]
    assert edt["anchor_session_date"] == "2026-09-01" and est["anchor_session_date"] == "2026-01-05"


def test_a_packet_on_a_non_trading_day_expects_the_last_completed_session():
    sat = A.classify_prior_close(anchor_stamp=bar_t("2026-09-04"),
                                 packet_session_date="2026-09-05T15:00:00Z")
    assert sat["fresh"] and sat["expected_anchor_session"] == "2026-09-04"


@pytest.mark.parametrize("session_time", ["2026-09-02T12:00:00Z",      # premarket
                                          "2026-09-02T13:45:00Z",      # regular
                                          "2026-09-02T22:00:00Z"])     # postmarket
def test_every_session_state_of_a_trading_day_looks_back_to_the_same_close(session_time):
    r = A.classify_prior_close(anchor_stamp=bar_t("2026-09-01"), packet_session_date=session_time)
    assert r["fresh"] and r["expected_anchor_session"] == "2026-09-01"


# ---------------------------------------------------------------- the instrument cases
def test_a_missing_latest_bar_is_stale_not_absent():
    """The vendor returned A bar, just not the right session's."""
    r = A.classify_prior_close(anchor_stamp=bar_t("2026-08-28"),
                               packet_session_date="2026-09-02T13:45:00Z")
    assert r["classification"] == A.SESSIONS_MISSED and r["sessions_missed"] == 2
    assert "no print from this instrument" in r["why"]


def test_a_long_halt_and_a_delisting_land_on_the_same_rule():
    halt = A.classify_prior_close(anchor_stamp=bar_t("2026-06-01"),
                                  packet_session_date="2026-09-01T13:45:00Z")
    dead = A.classify_prior_close(anchor_stamp="2025-02-24T05:00:00Z",
                                  packet_session_date="2026-09-01T13:45:00Z")
    for r in (halt, dead):
        assert r["classification"] == A.SESSIONS_MISSED and r["fresh"] is False
    assert halt["sessions_missed"] > 50 and dead["sessions_missed"] > 300
    # the verdict does not depend on the size of the gap, only the reporting
    # does: the same classification and the same closing sentence, with only
    # the dates differing.
    assert halt["classification"] == dead["classification"]
    tail = "It is a real number and it does not describe the current market."
    assert halt["why"].endswith(tail) and dead["why"].endswith(tail)


def test_a_newly_listed_instrument_has_no_prior_session_and_is_absent():
    r = A.classify_prior_close(anchor_stamp=None, packet_session_date="2026-09-01T13:45:00Z",
                               present=False)
    assert r["classification"] == A.NO_PRIOR_SESSION and r["fresh"] is False
    assert "never substituted" in r["why"]


@pytest.mark.parametrize("stamp", [None, "", "not-a-date", "2026-13-45", {}, [], 12345.0])
def test_a_malformed_or_undated_vendor_bar_cannot_be_judged_current(stamp):
    r = A.classify_prior_close(anchor_stamp=stamp, packet_session_date="2026-09-01T13:45:00Z")
    assert r["classification"] == A.UNDATED and r["fresh"] is False
    assert "cannot be identified" in r["why"] or "no usable session date" in r["why"]


@pytest.mark.parametrize("stamp,expected_session", [("2026-08-31", "2026-08-31"),
                                                    ("20260831", "2026-08-31")])
def test_a_date_only_record_is_a_session_date_and_is_not_shifted_by_a_timezone(stamp,
                                                                               expected_session):
    """Caught by this suite: reading a bare date as UTC midnight and converting
    to ET moves it back one session, so a bar from the CURRENT session would
    have passed as the immediately preceding one."""
    r = A.classify_prior_close(anchor_stamp=stamp, packet_session_date="2026-09-01T13:45:00Z")
    assert r["anchor_session_date"] == expected_session
    assert r["classification"] == A.IMMEDIATELY_PRECEDING and r["fresh"] is True
    same_day = A.classify_prior_close(anchor_stamp="2026-09-01",
                                      packet_session_date="2026-09-01T13:45:00Z")
    assert same_day["classification"] == A.NOT_A_PRIOR_SESSION


def test_a_bar_from_the_current_session_or_later_is_not_a_prior_close():
    for stamp in (bar_t("2026-09-01"), bar_t("2026-09-02")):
        r = A.classify_prior_close(anchor_stamp=stamp, packet_session_date="2026-09-01T13:45:00Z")
        assert r["classification"] == A.NOT_A_PRIOR_SESSION and r["fresh"] is False


def test_the_gap_count_is_context_and_says_when_the_calendar_stops_covering_it():
    r = A.classify_prior_close(anchor_stamp="2025-02-24T05:00:00Z",
                               packet_session_date="2026-09-01T13:45:00Z")
    assert r["calendar_covers_range"] is False and r["gap_note"]
    assert "VERDICT does not use it" in r["gap_note"]
    near = A.classify_prior_close(anchor_stamp=bar_t("2026-08-27"),
                                  packet_session_date="2026-09-01T13:45:00Z")
    assert near["calendar_covers_range"] is True and near["sessions_missed"] == 2


# ---------------------------------------------------------------- composer integration
def test_a_fresh_anchor_is_valid_and_its_dependents_are_valid():
    p = built()
    assert f(p, "prior_close")["q"] == VALID and f(p, "prior_close")["v"] == 99.0
    assert f(p, "prior_close_session")["v"] == "2026-08-31"
    for name in ANCHOR_DEPENDENT:
        assert f(p, name)["q"] == VALID, name


def test_a_stale_anchor_is_not_valid_and_carries_no_number():
    p = built(snap(prev_t="2025-02-24T05:00:00Z", prev=0.2568))
    rec = f(p, "prior_close")
    assert rec["q"] == STALE and rec["v"] is None
    assert "immediately preceding session" in rec["note"]
    assert f(p, "prior_close_session")["v"] == "2025-02-24"


def test_a_stale_anchor_propagates_to_every_anchor_dependent_field():
    p = built(snap(prev_t="2025-02-24T05:00:00Z", prev=0.2568))
    for name in ANCHOR_DEPENDENT:
        rec = f(p, name)
        assert rec["q"] == STALE, (name, rec)
        assert rec["v"] is None, (name, rec)
        assert "prior_close" in rec["note"] or "prior_session" in rec["note"], name


def test_current_session_fields_survive_a_stale_anchor():
    """The cash open is an event of the session in progress. A prior close
    from another session must not touch it."""
    p = built(snap(prev_t="2025-02-24T05:00:00Z", prev=0.2568))
    for name in CURRENT_SESSION_FIELDS:
        assert f(p, name)["q"] == VALID, name
        assert f(p, name)["v"] is not None, name
    assert f(p, "cash_open_return_bps")["v"] == pytest.approx(52.26, abs=0.01)


def test_an_absent_anchor_is_not_available_and_an_undated_one_is_not_estimable():
    absent_p = built(snap(prev_present=False))
    assert f(absent_p, "prior_close")["q"] == NOT_AVAILABLE
    assert f(absent_p, "prior_close_return_bps")["q"] == NOT_AVAILABLE
    undated_p = built(snap(prev_t=None))
    assert f(undated_p, "prior_close")["q"] == NOT_ESTIMABLE
    assert f(undated_p, "prior_close_return_bps")["q"] == NOT_ESTIMABLE
    # distinct, not flattened
    assert f(absent_p, "prior_close")["q"] != f(undated_p, "prior_close")["q"]


def test_no_formula_runs_on_an_untrusted_anchor():
    calls = []
    original = D.derive

    def spy(name, inputs, compute, **kw):
        def watched():
            calls.append(name)
            return compute()
        return original(name, inputs, watched, **kw)

    D_derive, C.derived.derive = C.derived.derive, spy
    try:
        built(snap(prev_t="2025-02-24T05:00:00Z", prev=0.2568))
    finally:
        C.derived.derive = D_derive
    for name in ANCHOR_DEPENDENT:
        assert name not in calls, name


def test_the_anchor_policy_version_is_recorded_in_the_packet():
    p = built()
    assert p["sources"]["anchor_freshness"] == "ANCHOR_FRESHNESS_POLICY_V1"


# ---------------------------------------------------------------- live vs historical
def test_live_and_historical_paths_get_identical_quality_semantics():
    """There is ONE composer. The historical factory hands it a snapshot of
    the same shape, so the anchor verdict cannot differ between the paths."""
    s = snap(prev_t="2025-02-24T05:00:00Z", prev=0.2568)
    live = compose(subject="TEST", snapshot=s, scheduled_time="2026-09-01T13:45:00+00:00",
                   capture_start="2026-09-01T13:45:00+00:00",
                   complete_time="2026-09-01T13:45:00+00:00", universe_version="LIVE",
                   evidence_class="LIVE_PROSPECTIVE").seal()
    hist = compose(subject="TEST", snapshot=s, scheduled_time="2026-09-01T13:45:00+00:00",
                   capture_start="2026-09-01T13:45:00+00:00",
                   complete_time="2026-09-01T13:45:00+00:00", universe_version="HISTORICAL",
                   evidence_class="HISTORICAL_REPLAY").seal()
    for name in ("prior_close", "prior_close_session") + ANCHOR_DEPENDENT:
        assert live["features"][name]["q"] == hist["features"][name]["q"], name
        assert live["features"][name]["v"] == hist["features"][name]["v"], name
    assert FACTORY_VERSION.startswith("HISTORICAL_MARKET_TWIN_FACTORY_V0.")


# ---------------------------------------------------------------- schema and serialisation
def test_a_non_valid_anchor_can_never_carry_a_number():
    with pytest.raises(TwinViolation, match="must not present a consumable measurement"):
        Field(0.2568, STALE, "alpaca_sip")


def test_the_stale_anchor_survives_serialisation_and_reload():
    p = built(snap(prev_t="2025-02-24T05:00:00Z", prev=0.2568))
    back = json.loads(json.dumps(p))
    assert verify_packet(back) == []
    for name in ("prior_close",) + ANCHOR_DEPENDENT:
        assert back["features"][name]["q"] == STALE
        assert back["features"][name]["v"] is None
        assert back["features"][name].get("note")
    usable = {k for k, v in back["features"].items() if v.get("q") == VALID}
    assert "prior_close" not in usable and not (set(ANCHOR_DEPENDENT) & usable)
    assert "session_open" in usable and "cash_open_return_bps" in usable


# ---------------------------------------------------------------- NKLA, from the sealed packet
def test_NKLA_sealed_packet_still_shows_the_original_anchor_defect():
    nkla = next(json.loads(l) for l in open(FROZEN) if json.loads(l)["subject"] == "NKLA")
    rec = nkla["features"]["prior_close"]
    assert rec["q"] == VALID and rec["v"] == 0.2568
    assert rec["as_of"].startswith("2025-02-24")
    r = A.classify_prior_close(anchor_stamp=rec["as_of"],
                               packet_session_date=nkla["scheduled_time"])
    assert r["classification"] == A.SESSIONS_MISSED and r["fresh"] is False


def test_NKLA_inputs_recomposed_refuse_the_anchor_and_everything_built_on_it():
    nkla = next(json.loads(l) for l in open(FROZEN) if json.loads(l)["subject"] == "NKLA")
    b = nkla["features"]
    s = {"prevDailyBar": {"c": b["prior_close"]["v"], "v": 100, "t": b["prior_close"]["as_of"]},
         "dailyBar": {"o": b["session_open"]["v"], "h": b["session_high"]["v"],
                      "l": b["session_low"]["v"], "c": b["session_low"]["v"],
                      "v": b["session_volume"]["v"], "vw": b["session_vwap"]["v"],
                      "t": b["session_open"]["as_of"]}}
    p = compose(subject="NKLA", snapshot=s, scheduled_time=nkla["scheduled_time"],
                capture_start=nkla["capture_start"], complete_time=nkla["state_complete_time"],
                universe_version="PULSE010_DIAGNOSTIC",
                evidence_class="DIAGNOSTIC_RECOMPOSITION").seal()
    assert f(p, "prior_close")["q"] == STALE and f(p, "prior_close")["v"] is None
    for name in ("prior_close_return_bps", "overnight_gap_bps", "relative_volume"):
        assert f(p, name)["q"] in (STALE, NOT_AVAILABLE), name
        assert f(p, name)["v"] is None, name
    # the current session's own aggregates are untouched by the anchor verdict
    for name in ("session_open", "session_high", "session_low", "session_volume"):
        assert f(p, name)["q"] == VALID, name
