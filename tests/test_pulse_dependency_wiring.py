"""PULSE-010 REPAIR -- each derived call receives exactly what it declares.

Astra found that compose.py handed one shared dict, spanning the quote, the
anchor and every session aggregate, to five derived fields at once. The map
kept it harmless -- resolve() consults DEPENDENCIES[name]["inputs"] and
ignores the rest -- and the independence rule was measured to hold both
before and after this repair (results/pulse010r_before_after.json). The
hazard was that the declaration was the ONLY thing preventing unrelated
fields from coupling. These tests fix that in both directions: the callers
pass exactly their declared ingredients, and an undeclared one is refused.

Deterministic: no network, no clock.
"""
import json
from datetime import datetime, timedelta, timezone

import pytest

from apex.pulse import compose as C
from apex.pulse import derived as D
from apex.pulse.compose import compose
from apex.pulse.twin import (NOT_AVAILABLE, NOT_ESTIMABLE, SESSION_INAPPLICABLE,
                             STALE, VALID, ok, absent)

AT = "2026-09-01T13:45:00+00:00"
PREMARKET_AT = "2026-09-01T12:00:00+00:00"
FRESH_Q = "2026-09-01T13:44:59Z"
STALE_Q = "2025-02-26T00:59:59Z"
FRESH_A = "2026-08-31T04:00:00Z"
STALE_A = "2025-02-24T05:00:00Z"

USES_MID = ("mid", "spread_bps", "spread_rel", "touch_size", "nbbo_size_imbalance",
            "prior_close_return_bps", "cash_open_return_bps", "session_range_position",
            "vwap_distance_bps")
USES_ANCHOR = ("prior_close_return_bps", "overnight_gap_bps", "relative_volume")
QUOTE_NOT_ANCHOR = ("cash_open_return_bps", "session_range_position", "vwap_distance_bps")
ANCHOR_NOT_QUOTE = ("overnight_gap_bps", "relative_volume")
CURRENT_SESSION = ("session_open", "session_high", "session_low", "session_vwap",
                   "session_volume")


def built(quote_t=FRESH_Q, anchor_t=FRESH_A, at=AT):
    snap = {"latestQuote": {"bp": 100.0, "ap": 100.04, "bs": 3, "as": 5, "t": quote_t},
            "latestTrade": {"p": 100.01, "t": quote_t},
            "prevDailyBar": {"c": 99.0, "v": 1000, "t": anchor_t},
            "dailyBar": {"o": 99.5, "h": 101.0, "l": 99.0, "c": 100.0, "v": 5000,
                         "vw": 100.02, "t": "2026-09-01T04:00:00Z"},
            "minuteBar": {"v": 20, "c": 100.0, "t": "2026-09-01T13:44:00Z"}}
    return compose(subject="SYNTH", snapshot=snap, scheduled_time=at, capture_start=at,
                   complete_time=at, universe_version="TEST").seal()


def f(p, name):
    return p["features"][name]


# ---------------------------------------------------------------- the guard
def test_an_undeclared_ingredient_is_refused_not_ignored():
    good = {"mid": ok(100.0, source="t"), "session_open": ok(99.5, source="t")}
    assert D.derive("cash_open_return_bps", good, lambda: 50.0).quality == VALID
    with pytest.raises(D.DerivationViolation, match="NOT declared in DEPENDENCIES"):
        D.derive("cash_open_return_bps",
                 {**good, "prior_close": absent(STALE, source="t")}, lambda: 50.0)


def test_the_guard_names_every_undeclared_ingredient():
    with pytest.raises(D.DerivationViolation) as e:
        D.derive("vwap_distance_bps",
                 {"mid": ok(1.0, source="t"), "session_vwap": ok(1.0, source="t"),
                  "prior_close": ok(1.0, source="t"), "session_volume": ok(1.0, source="t")},
                 lambda: 1.0)
    assert "prior_close" in str(e.value) and "session_volume" in str(e.value)


def test_a_missing_declared_ingredient_is_still_refused():
    with pytest.raises(D.DerivationViolation, match="were not supplied"):
        D.derive("cash_open_return_bps", {"mid": ok(1.0, source="t")}, lambda: 1.0)


@pytest.mark.parametrize("name", sorted(D.DEPENDENCIES))
def test_exactly_the_declared_set_is_accepted_for_every_mapped_field(name):
    """Neither more nor less, for all 26 fields."""
    declared = D.DEPENDENCIES[name]["inputs"]
    exact = {k: ok(1.0, source="t") for k in declared}
    assert D.derive(name, exact, lambda: 1.0).quality == VALID
    with pytest.raises(D.DerivationViolation, match="NOT declared"):
        D.derive(name, {**exact, "prior_close": ok(1.0, source="t")}
                 if "prior_close" not in declared else {**exact, "session_volume": ok(1.0, source="t")}
                 if "session_volume" not in declared else {**exact, "__extra__": ok(1.0, source="t")},
                 lambda: 1.0)


def test_the_composer_reads_the_map_rather_than_restating_it():
    """The wiring is derived FROM DEPENDENCIES, so it cannot drift from it."""
    src = open(C.__file__).read()
    assert 'derived.DEPENDENCIES[name]["inputs"]' in src
    assert "D = {k: F[k] for k in (" not in src          # the shared dict is gone
    assert C.COMPOSER_VERSION == "PULSE_COMPOSE_V0.2.1"
    assert "REFUSES an undeclared ingredient" in C.COMPOSER_HISTORY["V0.2.1"]


# ---------------------------------------------------------------- fresh quote, stale anchor
def test_fresh_quote_stale_anchor_refuses_only_the_anchor_dependents():
    p = built(quote_t=FRESH_Q, anchor_t=STALE_A)
    assert f(p, "prior_close")["q"] == STALE and f(p, "prior_close")["v"] is None
    for name in USES_ANCHOR:
        assert f(p, name)["q"] == STALE, name
        assert f(p, name)["v"] is None, name
    for name in QUOTE_NOT_ANCHOR:
        assert f(p, name)["q"] == VALID, name
        assert f(p, name)["v"] is not None, name
    assert f(p, "cash_open_return_bps")["v"] == pytest.approx(52.26, abs=0.01)
    assert f(p, "session_range_position")["v"] == pytest.approx(0.51, abs=0.01)
    assert f(p, "vwap_distance_bps")["v"] == pytest.approx(0.0, abs=0.01)
    for name in CURRENT_SESSION + ("mid", "spread_bps", "nbbo_size_imbalance"):
        assert f(p, name)["q"] == VALID, name


# ---------------------------------------------------------------- stale quote, fresh anchor
def test_stale_quote_fresh_anchor_refuses_only_the_mid_dependents():
    p = built(quote_t=STALE_Q, anchor_t=FRESH_A)
    for name in USES_MID:
        assert f(p, name)["q"] != VALID, name
        assert f(p, name)["v"] is None, name
    assert f(p, "prior_close")["q"] == VALID and f(p, "prior_close")["v"] == 99.0
    for name in ANCHOR_NOT_QUOTE:
        assert f(p, name)["q"] == VALID, name
        assert f(p, name)["v"] is not None, name
    for name in CURRENT_SESSION:
        assert f(p, name)["q"] == VALID, name


# ---------------------------------------------------------------- both stale
def test_both_stale_each_field_is_refused_for_its_own_declared_reason():
    p = built(quote_t=STALE_Q, anchor_t=STALE_A)
    for name in USES_MID + USES_ANCHOR:
        assert f(p, name)["q"] != VALID, name
    # the provenance must name the ACTUAL failing ingredient of each field
    assert "raw:quote" in f(p, "mid")["note"]
    assert "prior_close" in f(p, "prior_close_return_bps")["note"]
    assert "mid" in f(p, "prior_close_return_bps")["note"]
    # the note names the CULPRITS, not every declared input: overnight_gap_bps
    # declares session_open too, and the current session's open is fine.
    assert "prior_close" in f(p, "overnight_gap_bps")["note"]
    assert "session_open" not in f(p, "overnight_gap_bps")["note"]
    assert f(p, "session_open")["q"] == VALID
    assert "mid" in f(p, "cash_open_return_bps")["note"]
    assert "prior_close" not in f(p, "cash_open_return_bps")["note"]
    assert "prior_close" not in f(p, "session_range_position")["note"]
    assert "prior_close" not in f(p, "vwap_distance_bps")["note"]
    for name in CURRENT_SESSION:
        assert f(p, name)["q"] == VALID, name


def test_provenance_lists_only_declared_ingredients():
    p = built(quote_t=STALE_Q, anchor_t=STALE_A)
    for name in ("cash_open_return_bps", "session_range_position", "vwap_distance_bps",
                 "prior_close_return_bps", "overnight_gap_bps", "relative_volume"):
        note = f(p, name)["note"] or ""
        declared = set(D.DEPENDENCIES[name]["inputs"])
        for other in {"mid", "prior_close", "session_open", "session_high", "session_low",
                      "session_vwap", "session_volume"} - declared:
            assert "'%s'" % other not in note, (name, other, note)


# ---------------------------------------------------------------- preserved semantics
def test_session_inapplicable_still_dominates_a_stale_anchor():
    p = built(quote_t=FRESH_Q, anchor_t=STALE_A, at=PREMARKET_AT)
    assert f(p, "cash_open_return_bps")["q"] == SESSION_INAPPLICABLE
    assert f(p, "overnight_gap_bps")["q"] == SESSION_INAPPLICABLE
    assert f(p, "prior_close")["q"] == STALE          # judged on its own terms


def test_no_formula_runs_with_an_untrusted_ingredient_after_the_rewiring():
    calls = []
    original = D.derive

    def spy(name, inputs, compute, **kw):
        return original(name, inputs, lambda: calls.append(name) or compute(), **kw)

    C.derived.derive = spy
    try:
        built(quote_t=FRESH_Q, anchor_t=STALE_A)
    finally:
        C.derived.derive = original
    for name in USES_ANCHOR:
        assert name not in calls, name
    for name in QUOTE_NOT_ANCHOR:
        assert name in calls, name


def test_non_valid_fields_still_carry_no_number_and_survive_reload():
    p = built(quote_t=FRESH_Q, anchor_t=STALE_A)
    back = json.loads(json.dumps(p))
    for name in ("prior_close",) + USES_ANCHOR:
        assert back["features"][name]["q"] == STALE and back["features"][name]["v"] is None
    usable = {k for k, v in back["features"].items() if v.get("q") == VALID}
    assert set(QUOTE_NOT_ANCHOR) <= usable and not (set(USES_ANCHOR) & usable)


def test_both_fresh_leaves_everything_valid():
    p = built()
    for name in USES_MID + USES_ANCHOR + CURRENT_SESSION + ("prior_close",):
        assert f(p, name)["q"] == VALID, name
        assert f(p, name)["v"] is not None, name
