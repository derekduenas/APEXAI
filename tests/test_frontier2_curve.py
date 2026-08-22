"""MarketCurvatureState — F1. Proves the derivative stack is real
calculus (not an indicator dressed up), every dimension without real
data reads NO_SUPPORT honestly, the breadth gate obeys the directive's
explicit law, and the three-axis verdict (likelihood/direction/
expression) never collapses into a forced BUY/SELL read.
"""
from __future__ import annotations

import pandas as pd
import pytest

from apex.frontier2.curve import (DIMENSIONS, CurveViolation,
                                  DimensionCurvature, compute,
                                  compute_dimension)
from apex.frontier2.observation_integrity import compute as oi_compute

T0 = pd.Timestamp("2026-08-18T14:00:00Z")


def _oi(breadth_valid: bool):
    from apex.intraday.universe_coverage import UniverseCoverageState
    uc = UniverseCoverageState(
        intended_universe=("A",), authorized_universe=("A",),
        streamed_universe=("A",), continuous_universe=("A",),
        rotated_universe=(), never_observed=(), coverage_count=1,
        coverage_fraction=1.0, continuous_coverage_fraction=1.0,
        broad_discovery_valid=breadth_valid, status="HEALTHY")
    return oi_compute(universe_coverage=uc, as_of=T0, known_from=T0)


# ---- compute_dimension: the pure calculus -------------------------------

def test_empty_points_is_no_support():
    d = compute_dimension("price", [], now=T0, known_from=T0,
                          reason_unsupported="TEST_ABSENT")
    assert d.status == "NO_SUPPORT"
    assert d.coverage == "TEST_ABSENT"
    assert d.value is None


def test_one_point_is_insufficient_history_but_has_a_level():
    d = compute_dimension("price", [(T0, 100.0)], now=T0, known_from=T0)
    assert d.status == "INSUFFICIENT_HISTORY"
    assert d.value == 100.0
    assert d.velocity is None


def test_two_points_gives_velocity_not_curvature():
    pts = [(T0, 100.0), (T0 + pd.Timedelta(hours=1), 102.0)]
    d = compute_dimension("price", pts, now=T0 + pd.Timedelta(hours=1),
                          known_from=T0)
    assert d.status == "INSUFFICIENT_HISTORY"
    assert d.velocity == pytest.approx(2.0)          # +2/hour
    assert d.curvature is None


def test_constant_acceleration_series_yields_expected_curvature_sign():
    """value = 100 + t^2 (in hours) -> velocity ~ 2t, acceleration ~
    constant positive, so V2 curvature (z of the newest return change
    against the trailing return distribution) must be positive."""
    pts = [(T0 + pd.Timedelta(hours=h), 100.0 + float(h * h))
           for h in range(11)]
    d = compute_dimension("price", pts, now=T0 + pd.Timedelta(hours=10),
                          known_from=T0)
    assert d.status == "SUPPORTED"
    assert d.acceleration > 0
    assert d.curvature > 0


def test_flat_series_is_supported_with_zero_curvature():
    pts = [(T0 + pd.Timedelta(hours=h), 50.0) for h in range(11)]
    d = compute_dimension("price", pts, now=T0 + pd.Timedelta(hours=10),
                          known_from=T0)
    assert d.status == "SUPPORTED"
    assert d.velocity == 0.0
    assert d.curvature == 0.0
    assert d.elevated() is False


def test_future_dated_points_are_excluded_not_used():
    """Future-blindness: a point timestamped after `now` must never
    enter the fit."""
    pts = [(T0, 100.0), (T0 + pd.Timedelta(hours=1), 101.0),
          (T0 + pd.Timedelta(hours=100), 9999.0)]     # a lookahead plant
    d = compute_dimension("price", pts, now=T0 + pd.Timedelta(hours=1),
                          known_from=T0)
    assert d.support == 2
    assert d.value == 101.0


def test_unknown_dimension_name_refused():
    with pytest.raises(CurveViolation):
        DimensionCurvature(dimension="NOT_A_REAL_DIM", value=1.0,
                           velocity=None, acceleration=None, curvature=None,
                           status="NO_SUPPORT", support=0, coverage="x",
                           freshness_s=None, known_from=str(T0), as_of=str(T0))


# ---- compute(): the assembly + classifier --------------------------------

def _rising_price(hours=11, slope=1.0):
    # V2 shape: a QUIET trailing stretch (small alternating wobble, so
    # the trailing sigma is well-defined and small) ending in a decisive
    # upward break. The break is judged against the trailing return
    # distribution -- that is what elevates under V2. `slope` scales the
    # break; z is scale-invariant in it, direction is not.
    quiet = [(T0 + pd.Timedelta(hours=h),
              100.0 + 0.02 * ((-1) ** h)) for h in range(hours - 1)]
    last = (T0 + pd.Timedelta(hours=hours - 1), 100.0 + 3.0 * slope)
    return quiet + [last]


def _falling_price(hours=11, slope=1.0):
    quiet = [(T0 + pd.Timedelta(hours=h),
              100.0 + 0.02 * ((-1) ** h)) for h in range(hours - 1)]
    last = (T0 + pd.Timedelta(hours=hours - 1), 100.0 - 3.0 * slope)
    return quiet + [last]


def _flat(hours=11, level=100.0):
    return [(T0 + pd.Timedelta(hours=h), level) for h in range(hours)]


def test_all_dimensions_present_in_output_even_when_unsupplied():
    st = compute("AAPL", {}, observation_integrity=_oi(True),
                now=T0, known_from=T0)
    assert set(st.dimensions.keys()) == set(DIMENSIONS)
    for name, rec in st.dimensions.items():
        assert rec["status"] == "NO_SUPPORT"
    assert st.high_level_state == "UNKNOWN"
    assert st.transition_likelihood == "UNKNOWN"


def test_rising_price_and_rs_gives_positive_transition_with_confirmation():
    now = T0 + pd.Timedelta(hours=10)
    dims = {"price": _rising_price(), "relative_strength": _rising_price()}
    st = compute("AAPL", dims, observation_integrity=_oi(True),
                now=now, known_from=now)
    assert st.transition_direction == "UP"
    assert st.expression == "CONFIRMED_EXPRESSION"
    assert st.high_level_state == "POSITIVE_TRANSITION"
    assert st.transition_likelihood in ("MODERATE", "HIGH")


def test_rs_leads_price_lagging_is_early_positive_curvature_not_confirmed():
    """The directive's central goal: detect the transition BEFORE price
    fully expresses it. RS curving up, price flat -> EARLY, not full."""
    now = T0 + pd.Timedelta(hours=10)
    dims = {"price": _flat(), "relative_strength": _rising_price()}
    st = compute("AAPL", dims, observation_integrity=_oi(True),
                now=now, known_from=now)
    assert st.expression == "EARLY_EXPRESSION"
    assert st.high_level_state == "EARLY_POSITIVE_CURVATURE"


def test_falling_price_is_negative_transition():
    now = T0 + pd.Timedelta(hours=10)
    dims = {"price": _falling_price(), "relative_strength": _falling_price()}
    st = compute("AAPL", dims, observation_integrity=_oi(True),
                now=now, known_from=now)
    assert st.transition_direction == "DOWN"
    assert st.high_level_state == "NEGATIVE_TRANSITION"


def test_disagreeing_directional_dimensions_is_mixed_not_forced():
    """No forced direction: price up, RS down must read MIXED, never
    silently pick one."""
    now = T0 + pd.Timedelta(hours=10)
    dims = {"price": _rising_price(), "relative_strength": _falling_price()}
    st = compute("AAPL", dims, observation_integrity=_oi(True),
                now=now, known_from=now)
    assert st.transition_direction == "MIXED"
    # a MIXED direction must never yield a directional high-level state
    assert st.high_level_state not in (
        "POSITIVE_TRANSITION", "EARLY_POSITIVE_CURVATURE",
        "NEGATIVE_TRANSITION", "EARLY_NEGATIVE_CURVATURE")


def test_volatility_expansion_detected_independent_of_direction():
    now = T0 + pd.Timedelta(hours=10)
    dims = {"volatility": _rising_price(slope=5.0)}     # curving up hard
    st = compute("AAPL", dims, observation_integrity=_oi(True),
                now=now, known_from=now)
    assert st.high_level_state == "VOLATILITY_EXPANSION"
    assert st.transition_direction == "UNKNOWN"          # honestly unforced


def test_no_forced_probability_the_directive_example_shape():
    """A valid Curve output is TRANSITION_RISK_HIGH-equivalent /
    DIRECTION_UNKNOWN / NO_EXPRESSION -- likelihood, direction and
    expression must be independently readable, never collapsed."""
    now = T0 + pd.Timedelta(hours=10)
    # two non-directional-but-elevated dims, no price/RS supplied at all
    dims = {"volatility": _rising_price(slope=5.0),
           "liquidity": _falling_price(slope=5.0)}
    st = compute("AAPL", dims, observation_integrity=_oi(True),
                now=now, known_from=now)
    assert st.transition_likelihood in ("MODERATE", "HIGH")
    assert st.transition_direction == "UNKNOWN"
    assert st.expression == "UNKNOWN"                     # no price dim supplied


# ---- THE F1 LAW: breadth gate --------------------------------------------

def test_limited_coverage_suppresses_breadth_scoped_states():
    """Directive: 'If broad coverage is not certified: CURVE_BREADTH_
    STATUS = LIMITED_COVERAGE. Do not infer broad-market curvature from
    a partial universe.' sector_leadership/correlation-driven states
    must not fire even if those dimensions are individually elevated."""
    now = T0 + pd.Timedelta(hours=10)
    dims = {"sector_leadership": _rising_price(slope=5.0),
           "correlation": _rising_price(slope=5.0)}
    st = compute("AAPL", dims, observation_integrity=_oi(False),
                now=now, known_from=now)
    assert st.curve_breadth_status == "LIMITED_COVERAGE"
    assert st.high_level_state not in ("ROTATION_TRANSITION", "CORRELATION_BREAK")


def test_full_coverage_allows_breadth_scoped_states():
    now = T0 + pd.Timedelta(hours=10)
    dims = {"sector_leadership": _rising_price(slope=5.0)}
    st = compute("AAPL", dims, observation_integrity=_oi(True),
                now=now, known_from=now)
    assert st.curve_breadth_status == "FULL_COVERAGE"
    assert st.high_level_state == "ROTATION_TRANSITION"


# ---- determinism + persistence -------------------------------------------

def test_determinism_same_inputs_twice_byte_identical():
    now = T0 + pd.Timedelta(hours=10)
    dims = {"price": _rising_price()}
    a = compute("AAPL", dims, observation_integrity=_oi(True), now=now,
               known_from=now)
    b = compute("AAPL", dims, observation_integrity=_oi(True), now=now,
               known_from=now)
    assert a.as_record() == b.as_record()


def test_persist_writes_and_chains(tmp_path, monkeypatch):
    import apex.frontier2.curve as curve_mod
    monkeypatch.setattr(curve_mod, "LEDGER", tmp_path / "curve.jsonl")
    now = T0 + pd.Timedelta(hours=10)
    st = compute("AAPL", {"price": _rising_price()},
                observation_integrity=_oi(True), now=now, known_from=now)
    rec1 = curve_mod.persist(st)
    rec2 = curve_mod.persist(st)
    assert rec2["prev_hash"] == rec1["entry_hash"]
    assert rec1["decision_power"] == "NONE_FRONTIER_SHADOW"
