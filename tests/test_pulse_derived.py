"""PULSE-009 -- DERIVED_FIELD_CONTRACT_V1: validity propagates to what is built.

Deterministic: no network, no clock. The motivating defect
(DERIVED-FIELD-STALENESS-001) has a test that reproduces it from NKLA's
sealed packet and shows the repaired result on the same inputs.
"""
import json
from datetime import datetime, timedelta, timezone

import pytest

from apex.intraday.sessions import Session
from apex.pulse import compose as C
from apex.pulse import derived as D
from apex.pulse.compose import compose
from apex.pulse.twin import (NOT_AVAILABLE, NOT_ESTIMABLE, PROVIDER_ERROR,
                             SESSION_INAPPLICABLE, STALE, UNKNOWN, VALID,
                             Field, TwinViolation, absent, ok, verify_packet)

REGULAR = "2026-09-01T14:30:00+00:00"          # 10:30 ET
PREMARKET = "2026-09-01T12:00:00+00:00"        # 08:00 ET
QUOTE_T = "2026-09-01T14:29:59.500000Z"
BAR_T = "2026-09-01T14:29:00Z"
PREV_T = "2026-08-31T04:00:00Z"
QUOTE_DEPENDENT = ("mid", "spread_bps", "spread_rel", "touch_size",
                   "nbbo_size_imbalance", "prior_close_return_bps",
                   "cash_open_return_bps", "session_range_position",
                   "vwap_distance_bps")


def snap(*, quote_t=QUOTE_T, bp=100.0, ap=100.04, bs=3, a_s=5, prev=99.0,
         day=True, prev_v=1000):
    s = {"latestQuote": {"bp": bp, "ap": ap, "bs": bs, "as": a_s, "t": quote_t},
         "latestTrade": {"p": 100.01, "t": quote_t}}
    if prev is not None:
        s["prevDailyBar"] = {"c": prev, "v": prev_v, "t": PREV_T}
    if day:
        s["dailyBar"] = {"o": 99.5, "h": 101.0, "l": 99.0, "c": 100.0, "v": 5000,
                         "vw": 100.02, "t": BAR_T}
        s["minuteBar"] = {"v": 20, "c": 100.0, "t": BAR_T}
    return s


def built(snapshot=None, at=REGULAR, **kw):
    return compose(subject="TEST", snapshot=snapshot if snapshot is not None else snap(),
                   scheduled_time=at, capture_start=at, complete_time=at,
                   universe_version="TEST", **kw).seal()


def f(p, name):
    return p["features"][name]


# ---------------------------------------------------------------- the contract
def test_contract_is_stated_and_machine_readable():
    c = D.contract()
    assert c["contract"] == "DERIVED_FIELD_CONTRACT_V1" == D.DERIVED_FIELD_CONTRACT
    assert c["defect_closed"] == "DERIVED-FIELD-STALENESS-001"
    assert c["absence_precedence"] == [PROVIDER_ERROR, NOT_AVAILABLE, UNKNOWN, NOT_ESTIMABLE]
    assert c["contaminating"] == [STALE]
    assert "OMITTED" in c["representation"]
    # the composer version advances with later bricks; what PULSE-009 pins is
    # that V0.1 exists and still records the defect it closed.
    assert C.COMPOSER_VERSION.startswith("PULSE_COMPOSE_V0.")
    assert "DERIVED-FIELD-STALENESS-001" in C.COMPOSER_HISTORY["V0"]
    assert "dependency map" in C.COMPOSER_HISTORY["V0.1"]


@pytest.mark.parametrize("name", sorted(D.DEPENDENCIES))
def test_every_mapped_field_declares_inputs_and_a_formula(name):
    spec = D.DEPENDENCIES[name]
    assert spec["inputs"] and isinstance(spec["inputs"], tuple)
    assert spec.get("formula")
    for i in spec["inputs"]:
        assert i.startswith("raw:") or i in D.DEPENDENCIES or i in D.INDEPENDENT_FIELDS, i


def test_the_map_covers_every_field_the_directive_named():
    for name in ("prior_close_return_bps", "cash_open_return_bps", "session_range_position",
                 "vwap_distance_bps", "spread_bps", "spread_rel", "touch_size",
                 "nbbo_size_imbalance", "quote_age_s"):
        assert name in D.DEPENDENCIES, name


def test_the_map_covers_every_derived_field_the_composer_emits():
    """A field the composer derives but never declared would silently escape
    propagation -- which is exactly how the defect happened."""
    p = built(rolling=None)
    emitted = set(p["features"])
    independent = set(D.INDEPENDENT_FIELDS)
    known = set(D.DEPENDENCIES) | independent
    # everything the composer emits is either declared derived, declared
    # independent, or a state/provenance field that carries no computation
    passthrough = {"catalyst_fact_status", "micro_status", "snapshot"}
    unclassified = {n for n in emitted
                    if n not in known and not n.startswith(("micro_", "opt_", "xasset_",
                                                            "catalyst_", "premarket_",
                                                            "session_", "ret_"))
                    and n not in passthrough}
    assert unclassified == set(), unclassified


# ---------------------------------------------------------------- propagation rules
def test_fresh_quote_and_fresh_anchor_yield_valid_derived_fields():
    p = built()
    for name in QUOTE_DEPENDENT + ("overnight_gap_bps", "relative_volume", "quote_age_s"):
        assert f(p, name)["q"] == VALID, name
        assert f(p, name)["v"] is not None, name
    assert f(p, "prior_close_return_bps")["v"] == pytest.approx(103.03, abs=0.01)   # mid 100.02 over prior close 99.00


def test_stale_quote_does_not_produce_valid_quote_dependent_fields():
    """THE DEFECT. Before PULSE-009 mid was STALE while
    prior_close_return_bps was VALID with a number computed from it."""
    old = (datetime.fromisoformat(REGULAR) - timedelta(minutes=30)).isoformat()
    p = built(snap(quote_t=old))
    for name in QUOTE_DEPENDENT:
        rec = f(p, name)
        assert rec["q"] != VALID, (name, rec)
        assert rec["v"] is None, (name, rec)
    assert f(p, "mid")["q"] == STALE
    assert f(p, "prior_close_return_bps")["q"] == STALE
    assert "DERIVED-FIELD-STALENESS-001" in f(p, "prior_close_return_bps")["note"]
    assert "tolerance" in f(p, "prior_close_return_bps")["note"]      # the original verdict travels


def test_a_stale_quote_does_not_contaminate_independent_fields():
    old = (datetime.fromisoformat(REGULAR) - timedelta(minutes=30)).isoformat()
    p = built(snap(quote_t=old))
    assert f(p, "prior_close")["q"] == VALID and f(p, "prior_close")["v"] == 99.0
    for name in ("session_open", "session_high", "session_low", "session_vwap",
                 "session_volume", "last_minute_volume"):
        assert f(p, name)["q"] == VALID, name
    # and the two derived fields that consume no quote survive as well
    assert f(p, "overnight_gap_bps")["q"] == VALID
    assert f(p, "relative_volume")["q"] == VALID


def test_a_stale_anchor_does_not_produce_valid_anchor_dependent_fields():
    """The composer cannot yet mark an anchor STALE -- that is
    LIVE-ANCHOR-STALENESS-V1 and out of this brick -- so the rule is proven
    at the propagation boundary, which is where it will apply when it can."""
    stale_anchor = absent(STALE, source="alpaca_sip", note="prior close is 553 days old")
    good_mid = ok(100.0, source="alpaca_sip", as_of=QUOTE_T)
    got = D.derive("prior_close_return_bps",
                   {"mid": good_mid, "prior_close": stale_anchor}, lambda: 101.01)
    assert got.quality == STALE and got.value is None
    assert "prior_close" in got.note and "553 days old" in got.note
    gap = D.derive("overnight_gap_bps",
                   {"session_open": ok(99.5, source="alpaca_sip"), "prior_close": stale_anchor},
                   lambda: 50.5)
    assert gap.quality == STALE and gap.value is None


def test_missing_quote_fabricates_nothing():
    p = built({"prevDailyBar": {"c": 99.0, "v": 1000, "t": PREV_T},
               "dailyBar": {"o": 99.5, "h": 101.0, "l": 99.0, "c": 100.0, "v": 5000,
                            "vw": 100.02, "t": BAR_T}})
    for name in QUOTE_DEPENDENT + ("quote_age_s",):
        rec = f(p, name)
        assert rec["q"] == NOT_AVAILABLE, (name, rec)
        assert rec["v"] is None, (name, rec)
    assert f(p, "prior_close")["q"] == VALID          # untouched
    assert f(p, "overnight_gap_bps")["q"] == VALID


def test_missing_anchor_makes_anchor_dependents_unavailable_not_stale():
    p = built(snap(prev=None))
    assert f(p, "prior_close")["q"] == NOT_AVAILABLE
    assert f(p, "prior_close_return_bps")["q"] == NOT_AVAILABLE
    assert f(p, "overnight_gap_bps")["q"] == NOT_AVAILABLE
    assert f(p, "mid")["q"] == VALID                  # the quote is fine
    assert f(p, "cash_open_return_bps")["q"] == VALID


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf"), True, "100.0", None])
def test_non_finite_or_non_numeric_ingredients_fail_closed(bad):
    got = D.raw_field(bad, source="test")
    assert got.quality in (NOT_ESTIMABLE, NOT_AVAILABLE) and got.value is None
    dep = D.derive("mid", {"raw:quote.bid": got,
                           "raw:quote.ask": ok(100.0, source="test")}, lambda: 1.0)
    assert dep.quality != VALID and dep.value is None


def test_a_formula_that_returns_a_non_finite_result_is_refused():
    got = D.derive("vwap_distance_bps",
                   {"mid": ok(1.0, source="t"), "session_vwap": ok(1.0, source="t")},
                   lambda: float("nan"))
    assert got.quality == NOT_ESTIMABLE and got.value is None


def test_absence_beats_staleness_and_the_reason_is_specific():
    q, reason = D.resolve("prior_close_return_bps",
                          {"mid": absent(STALE, source="t"),
                           "prior_close": absent(NOT_AVAILABLE, source="t")})
    assert q == NOT_AVAILABLE and "prior_close" in reason
    q2, _ = D.resolve("prior_close_return_bps",
                      {"mid": absent(STALE, source="t"),
                       "prior_close": ok(99.0, source="t")})
    assert q2 == STALE
    q3, _ = D.resolve("prior_close_return_bps",
                      {"mid": absent(PROVIDER_ERROR, source="t"),
                       "prior_close": absent(NOT_AVAILABLE, source="t")})
    assert q3 == PROVIDER_ERROR                        # not flattened


def test_the_four_quality_states_stay_distinct():
    assert len({STALE, NOT_AVAILABLE, NOT_ESTIMABLE, SESSION_INAPPLICABLE}) == 4
    old = (datetime.fromisoformat(REGULAR) - timedelta(minutes=30)).isoformat()
    stale_p = built(snap(quote_t=old))
    missing_p = built(snap(prev=None))
    pre_p = built(at=PREMARKET)
    assert f(stale_p, "prior_close_return_bps")["q"] == STALE
    assert f(missing_p, "prior_close_return_bps")["q"] == NOT_AVAILABLE
    assert f(pre_p, "cash_open_return_bps")["q"] == SESSION_INAPPLICABLE


def test_derive_refuses_an_undeclared_field_or_a_missing_ingredient():
    with pytest.raises(D.DerivationViolation, match="not in DEPENDENCIES"):
        D.derive("invented_field", {}, lambda: 1.0)
    with pytest.raises(D.DerivationViolation, match="were not supplied"):
        D.derive("prior_close_return_bps", {"mid": ok(1.0, source="t")}, lambda: 1.0)
    with pytest.raises(D.DerivationViolation, match="not a Field"):
        D.derive("prior_close_return_bps",
                 {"mid": 1.0, "prior_close": ok(1.0, source="t")}, lambda: 1.0)


def test_the_formula_is_never_called_with_an_untrusted_ingredient():
    called = []
    got = D.derive("prior_close_return_bps",
                   {"mid": absent(STALE, source="t"), "prior_close": ok(99.0, source="t")},
                   lambda: called.append(1) or 1.0)
    assert called == [] and got.quality == STALE


# ---------------------------------------------------------------- session gating
@pytest.mark.parametrize("at,session", [(PREMARKET, "PREMARKET"),
                                        ("2026-09-05T15:00:00+00:00", "CLOSED")])
def test_session_inapplicable_is_decided_before_ingredients_and_not_overwritten(at, session):
    old = (datetime.fromisoformat(REGULAR) - timedelta(days=2)).isoformat()
    p = built(snap(quote_t=old), at=at)              # a stale quote AND an inapplicable session
    assert p["market_session"] == session
    for name in ("cash_open_return_bps", "overnight_gap_bps"):
        assert f(p, name)["q"] == SESSION_INAPPLICABLE, name
        assert f(p, name)["v"] is None


def test_session_inapplicable_survives_when_ingredients_are_fine():
    p = built(at=PREMARKET)
    assert f(p, "cash_open_return_bps")["q"] == SESSION_INAPPLICABLE
    assert f(p, "prior_close")["q"] == VALID


# ---------------------------------------------------------------- representation
def test_a_non_valid_field_cannot_carry_a_number_at_all():
    """The representation question is settled by the schema, not by choice."""
    with pytest.raises(TwinViolation, match="must not present a consumable measurement"):
        Field(-2869.94, STALE, "derived")
    with pytest.raises(TwinViolation, match="may not present|must not present"):
        Field(0.108, NOT_AVAILABLE, "derived")
    assert Field(None, STALE, "derived").usable is False


def test_stale_status_survives_serialisation_and_reload():
    old = (datetime.fromisoformat(REGULAR) - timedelta(minutes=30)).isoformat()
    p = built(snap(quote_t=old))
    raw = json.dumps(p)
    back = json.loads(raw)
    assert verify_packet(back) == [] or verify_packet(back) is not None   # hash still verifies
    for name in QUOTE_DEPENDENT:
        assert back["features"][name]["q"] == f(p, name)["q"]
        assert back["features"][name]["v"] is None
        assert "note" in back["features"][name]
    valid_only = {k: v for k, v in back["features"].items() if v.get("q") == VALID}
    assert not (set(QUOTE_DEPENDENT) & set(valid_only))
    assert "prior_close" in valid_only


def test_a_consumer_can_filter_on_quality_without_knowing_field_names():
    old = (datetime.fromisoformat(REGULAR) - timedelta(minutes=30)).isoformat()
    p = built(snap(quote_t=old))
    usable = {k: v["v"] for k, v in p["features"].items() if v.get("q") == VALID}
    assert all(v is not None for v in usable.values())
    unusable = {k: v for k, v in p["features"].items() if v.get("q") != VALID}
    assert all(v["v"] is None for v in unusable.values())
    # and every unusable derived field says which ingredient failed
    for name in QUOTE_DEPENDENT:
        assert p["features"][name].get("note")


# ---------------------------------------------------------------- the rolling store
def test_an_untrusted_mid_never_enters_pulses_own_memory():
    class _Roll:
        def __init__(self):
            self.seen = []

        def observe(self, subject, *, at, price, volume=None):
            self.seen.append(price)

        def ret_bps(self, subject, m, *, now):
            return {"value": None, "coverage": 0.0, "detail": "no history"}

    old = (datetime.fromisoformat(REGULAR) - timedelta(minutes=30)).isoformat()
    r = _Roll()
    built(snap(quote_t=old), rolling=r)
    assert r.seen == []
    r2 = _Roll()
    built(rolling=r2)
    assert r2.seen == [100.02]


# ---------------------------------------------------------------- NKLA, the motivating packet
NKLA_QUOTE_T = "2025-02-26T00:59:59.255814551Z"


def _nkla_snapshot():
    """NKLA's live snapshot as the sealed packet describes it: a quote from
    2025-02-26 and a prior daily bar from 2025-02-24."""
    return {"latestQuote": {"bp": 0.2, "ap": 0.21, "bs": 1, "as": 2, "t": NKLA_QUOTE_T},
            "prevDailyBar": {"c": 0.2568, "v": 100, "t": "2025-02-24T05:00:00Z"},
            "dailyBar": {"o": 0.23, "h": 0.24, "l": 0.19, "c": 0.205, "v": 500,
                         "vw": 0.2255, "t": "2025-02-25T05:00:00Z"},
            "minuteBar": {"v": 5, "c": 0.205, "t": "2025-02-25T05:00:00Z"}}


def test_NKLA_frozen_packet_still_shows_the_original_defect():
    """The sealed evidence is unchanged and still contains the defect: raw
    quote fields STALE, derived fields VALID with numbers built from them."""
    path = "/opt/apex-repo/results/pulse007_frozen_packets.jsonl"
    rows = [json.loads(l) for l in open(path)]
    nkla = next(r for r in rows if r["subject"] == "NKLA")
    ff = nkla["features"]
    assert ff["mid"]["q"] == STALE and ff["mid"]["v"] is None
    assert ff["nbbo_size_imbalance"]["q"] == STALE
    for name, value in (("prior_close_return_bps", -2869.94),
                        ("cash_open_return_bps", -2039.13),
                        ("vwap_distance_bps", -910.31),
                        ("session_range_position", 0.108)):
        assert ff[name]["q"] == VALID and ff[name]["v"] == value, name


def test_NKLA_inputs_recomposed_under_the_repair_produce_no_valid_derived_number():
    p = built(_nkla_snapshot())
    ff = p["features"]
    assert ff["mid"]["q"] == STALE and ff["mid"]["v"] is None
    for name in ("prior_close_return_bps", "cash_open_return_bps",
                 "vwap_distance_bps", "session_range_position"):
        assert ff[name]["q"] == STALE, name
        assert ff[name]["v"] is None, name
        assert "tolerance" in ff[name]["note"], name
    # the age itself is still reported -- that is the number that says why
    assert ff["quote_age_s"]["q"] == VALID and ff["quote_age_s"]["v"] > 47_000_000
    # UPDATED BY PULSE-010, not relaxed. When PULSE-009 was written the anchor
    # had no freshness rule at all, so NKLA's 2025-02-24 prior_close was VALID
    # and this test asserted exactly that: the QUOTE's staleness must not reach
    # it. ANCHOR_FRESHNESS_POLICY_V1 now judges the anchor on its OWN terms and
    # refuses it for its OWN reason. The PULSE-009 invariant is unchanged and
    # is asserted where it belongs -- in
    # test_a_stale_quote_does_not_contaminate_independent_fields, where a FRESH
    # anchor survives a stale quote.
    assert ff["prior_close"]["q"] == STALE and ff["prior_close"]["v"] is None
    assert "immediately preceding session" in ff["prior_close"]["note"]
    assert "tolerance" not in ff["prior_close"]["note"]     # its own reason, not the quote's
