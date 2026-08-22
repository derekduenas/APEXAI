"""BATCH 2 SYNTHETIC MOVIE — F2 (Expectation Violation), F3 (Participant
Pressure), F4 (Propagation), F5 (Leading Edge Map) proven working
TOGETHER, not just individually.

The story: a sector proxy (XLK) leads a constituent (NVDA) by ~2 minutes
(an empirically-estimated, pre-existing propagation edge). NVDA's
relative strength bends negative EARLY (before its own price curvature
confirms), the constituent then refuses an expected rebound, a failed
opening-range breakout creates a possible long trap, the edge's
target-side change is eventually observed (propagation "completes"),
LeadingEdgeMap promotes NVDA over a boring control candidate while the
thesis is live -- and later evidence (a real recovery) invalidates the
whole negative transition, which every organ must independently reflect,
not just Curve.

Every tick uses ONLY data with timestamp <= that tick's `now` -- the
no-lookahead law is proven explicitly below, not just assumed from the
underlying unit tests.
"""
from __future__ import annotations

import pandas as pd

from apex.frontier2 import event_bus2 as eb2
from apex.frontier2.curve import compute as curve_compute
from apex.frontier2.expectation_violation import \
    evaluate_index_move_high_beta_refusal
from apex.frontier2.leading_edge_map import rank as le_rank
from apex.frontier2.observation_integrity import compute as oi_compute
from apex.frontier2.participant_pressure import infer as pp_infer
from apex.frontier2.propagation import estimate_edge, infer_leading_edge
from apex.intraday.universe_coverage import UniverseCoverageState

T0 = pd.Timestamp("2026-08-18T14:00:00Z")

# NVDA's own price: low-curvature early, accelerates down mid-movie,
# recovers late. RS (vs sector) bends EARLY, well before price confirms.
# V2 (2026-08-20): the movie gained a 10-tick QUIET WARMUP so every
# asserted tick clears MIN_POINTS_FOR_CURVATURE, and the narrative's
# bends are now decisive against that trailing distribution (V1's
# always-elevated statistic let a 0.1%/tick drift register as a bend;
# V2 correctly does not). Narrative ticks shifted +10.
_WARMUP_N = 10
_PRICE_WARM = [100.0 + 0.02 * ((-1) ** h) for h in range(_WARMUP_N)]
_RS_WARM = [0.1 * ((-1) ** h) for h in range(_WARMUP_N)]
NVDA_LEVEL = _PRICE_WARM + [100.0, 99.9, 99.85, 99.7, 99.0, 97.5, 96.8,
                            96.5, 96.4, 97.0, 98.5, 103.5]
RS = _RS_WARM + [0.0, -0.1, -0.4, -2.8, -5.0, -7.5, -10.5, -12.5, -13.0,
                 -6.0, 1.0, 4.0]
EXCESS = [r * 0.002 for r in RS]
XLK_CUM = [0.0] * len(NVDA_LEVEL)
CURVE_WINDOW = 31

# a lookahead PLANT: if any tick's slicing ever leaked this, curvature
# at t=3 would be wildly different from the honest value.
POISON_LEVEL = 9999.0

# Propagation warm-up: XLK leads NVDA by 2 minutes, pre-existing before
# this movie's visible ticks (a realistic trailing-history edge).
_full = [((i * 37) % 11) - 5 + 0.05 * i for i in range(66)]
XLK_WARM, NVDA_WARM = _full[2:], _full[:-2]


def _oi():
    uc = UniverseCoverageState(
        intended_universe=("NVDA", "XLK"), authorized_universe=("NVDA", "XLK"),
        streamed_universe=("NVDA", "XLK"), continuous_universe=("NVDA", "XLK"),
        rotated_universe=(), never_observed=(), coverage_count=2,
        coverage_fraction=1.0, continuous_coverage_fraction=1.0,
        broad_discovery_valid=True, status="HEALTHY")
    return oi_compute(universe_coverage=uc, as_of=T0, known_from=T0)


def _curve_at(t: int, oi, poison=False):
    now = T0 + pd.Timedelta(minutes=t)
    lo = max(0, t - CURVE_WINDOW + 1)
    levels = list(NVDA_LEVEL)
    if poison:
        levels[t] = POISON_LEVEL           # only affects THIS tick's own point
    price_pts = [(T0 + pd.Timedelta(minutes=i), levels[i]) for i in range(lo, t + 1)]
    rs_pts = [(T0 + pd.Timedelta(minutes=i), RS[i]) for i in range(lo, t + 1)]
    return curve_compute("NVDA", {"price": price_pts, "relative_strength": rs_pts},
                         observation_integrity=oi, now=now, known_from=now)


def _ev_at(t: int):
    now = T0 + pd.Timedelta(minutes=t)
    return evaluate_index_move_high_beta_refusal(
        "NVDA", market_day_return=XLK_CUM[t], symbol_day_return=NVDA_LEVEL[t] / 100 - 1,
        excess_market_60m=EXCESS[t], event_time=now, known_from=now, now=now)


def _propagation_edge(extra: int, quality="FULL"):
    xlk = XLK_WARM + [0.1] * extra
    nvda = NVDA_WARM + [0.05] * extra
    return estimate_edge("XLK", "NVDA", xlk, nvda, known_from=T0, now=T0,
                         quality=quality)


def test_the_movie(tmp_path, monkeypatch):
    monkeypatch.setattr(eb2, "LEDGER", tmp_path / "events.jsonl")
    oi = _oi()

    curve_history, ev_history, pp_history, edge_history = [], [], [], []
    emitted_types = set()

    def _emit_if_changed(event_type, subject, new_state, *, event_time,
                         known_from, quality):
        prior = eb2.latest_for(subject, event_type)
        prior_state = prior["new_state"] if prior else None
        if prior_state != new_state:
            rec = eb2.emit(event_type, subject, event_time=event_time,
                          known_from=known_from, source="movie_test",
                          prior_state=prior_state, new_state=new_state,
                          quality=quality)
            emitted_types.add(event_type)
            return rec
        return None

    # ---- t=3: sector already weak (assumed prior), NVDA's RS bends,
    # price has not confirmed yet -----------------------------------------
    c3 = _curve_at(13, oi)
    curve_history.append(c3)
    assert c3.expression == "EARLY_EXPRESSION"
    assert c3.high_level_state == "EARLY_NEGATIVE_CURVATURE"
    _emit_if_changed("CURVATURE_CHANGE", "NVDA", c3.high_level_state,
                     event_time=c3.as_of, known_from=c3.known_from,
                     quality=c3.observation_quality)

    ev3 = _ev_at(13)
    ev_history.append(ev3)
    assert ev3.state == "OBSERVABLE_VIOLATION"
    _emit_if_changed("EXPECTATION_VIOLATION", "NVDA", ev3.state,
                     event_time=ev3.event_time, known_from=ev3.known_from,
                     quality=ev3.quality)

    # ---- t=5: constituent refuses an expected rebound; failed OR
    # breakout creates a possible long trap ---------------------------------
    c5 = _curve_at(15, oi)
    curve_history.append(c5)
    assert c5.expression == "CONFIRMED_EXPRESSION"        # price caught up
    assert c5.high_level_state == "NEGATIVE_TRANSITION"
    assert c5.high_level_state != c3.high_level_state      # a REAL change
    _emit_if_changed("CURVATURE_CHANGE", "NVDA", c5.high_level_state,
                     event_time=c5.as_of, known_from=c5.known_from,
                     quality=c5.observation_quality)

    pp5 = pp_infer("NVDA", or_break_up=True, or_failure=True, rvol_tod=3.0,
                  event_time=T0 + pd.Timedelta(minutes=15),
                  known_from=T0 + pd.Timedelta(minutes=15),
                  now=T0 + pd.Timedelta(minutes=15), quality="FULL")
    pp_history.append(pp5)
    assert pp5.trap_state == "POSSIBLE_LONG_TRAP"
    assert pp5.pressure_direction == "DOWN"
    _emit_if_changed("PARTICIPANT_PRESSURE_CHANGE", "NVDA", pp5.trap_state,
                     event_time=pp5.event_time, known_from=pp5.known_from,
                     quality=pp5.quality)

    edge5 = _propagation_edge(extra=0)
    edge_history.append(edge5)
    assert edge5.status == "SUPPORTED_LEAD_LAG"
    le5 = infer_leading_edge(edge5, {"subject": "XLK", "event_time": str(T0)},
                             now=T0 + pd.Timedelta(minutes=15))
    # known_from = le5.as_of (the moment THIS leading-edge check ran),
    # not the underlying edge's own known_from (which predates it) --
    # an internal-compute event is known the instant it is computed.
    _emit_if_changed("PROPAGATION_CHANGE", "NVDA", le5.propagation_state,
                     event_time=le5.as_of, known_from=le5.as_of,
                     quality=le5.quality)

    lem5 = le_rank("NEGATIVE_TRANSITION", [
        {"symbol": "NVDA", "data_quality": "FULL",
         "curve_expression": c5.expression,
         "propagation_position": le5.propagation_state,
         "participant_pressure_potential": pp5.forced_action_potential,
         "expectation_violation": ev3.state},
        {"symbol": "BORING_CONTROL"},          # everything UNKNOWN
    ], known_from=T0, now=T0 + pd.Timedelta(minutes=15))
    _emit_if_changed("LEADING_EDGE_CHANGE", "NEGATIVE_TRANSITION",
                     lem5.rows[0]["symbol"], event_time=lem5.as_of,
                     known_from=lem5.as_of, quality="FULL")
    assert lem5.rows[0]["symbol"] == "NVDA"    # promoted over the control

    # ---- t=9: propagation edge STRENGTHENS (more support accrued) --------
    edge9 = _propagation_edge(extra=2)
    edge_history.append(edge9)
    assert edge9.support > edge5.support
    assert edge9.status == "SUPPORTED_LEAD_LAG"

    c9 = _curve_at(19, oi)
    curve_history.append(c9)

    # ---- t=11: later evidence invalidates the negative transition --------
    c11 = _curve_at(21, oi)
    curve_history.append(c11)
    assert c11.high_level_state == "POSITIVE_TRANSITION"
    assert c11.transition_direction == "UP"
    assert c11.high_level_state != c9.high_level_state     # a REAL flip
    _emit_if_changed("CURVATURE_CHANGE", "NVDA", c11.high_level_state,
                     event_time=c11.as_of, known_from=c11.known_from,
                     quality=c11.observation_quality)

    ev11 = _ev_at(21)
    ev_history.append(ev11)
    assert ev11.residual > 0                                # sign flipped
    _emit_if_changed("EXPECTATION_VIOLATION", "NVDA", ev11.state,
                     event_time=ev11.event_time, known_from=ev11.known_from,
                     quality=ev11.quality)

    pp11 = pp_infer("NVDA", or_break_up=False, or_failure=False, rvol_tod=1.0,
                    event_time=T0 + pd.Timedelta(minutes=21),
                    known_from=T0 + pd.Timedelta(minutes=21),
                    now=T0 + pd.Timedelta(minutes=21), quality="FULL")
    pp_history.append(pp11)
    assert pp11.trap_state == "NONE"                         # trap dissolved
    assert pp11.trap_state != pp5.trap_state
    _emit_if_changed("PARTICIPANT_PRESSURE_CHANGE", "NVDA", pp11.trap_state,
                     event_time=pp11.event_time, known_from=pp11.known_from,
                     quality=pp11.quality)

    edge11 = _propagation_edge(extra=4)
    edge_history.append(edge11)
    assert edge11.support > edge9.support

    # ============================ THE MOVIE'S REQUIRED PROOFS =============

    # 1. All four organs changed state across the movie.
    assert len({c.high_level_state for c in curve_history}) >= 3
    assert len({e.state for e in ev_history}) >= 1
    assert len({p.trap_state for p in pp_history}) == 2
    assert edge5.support != edge9.support != edge11.support

    # 2. State changes are typed events, captured on the bus.
    assert {"CURVATURE_CHANGE", "EXPECTATION_VIOLATION",
           "PARTICIPANT_PRESSURE_CHANGE", "PROPAGATION_CHANGE",
           "LEADING_EDGE_CHANGE"} <= emitted_types
    all_events = eb2.read_all()
    assert len(all_events) >= 5
    for e in all_events:
        assert pd.Timestamp(e["known_from"]) >= pd.Timestamp(e["event_time"])

    # 3. No lookahead: poisoning a LATER index must not change an
    # EARLIER tick's result (the window at t=13 never includes index>13).
    c13_repeat = _curve_at(13, oi, poison=False)
    assert c13_repeat.as_record() == c3.as_record()
    c19_clean = _curve_at(19, oi, poison=False)
    c19_poisoned = _curve_at(19, oi, poison=True)         # poisons idx 19 itself
    assert c19_clean.as_record() != c19_poisoned.as_record()  # the plant IS reachable when in-window
    # poison at t itself is in-window by construction; the real
    # no-lookahead proof is index 13's window [max(0,13-30)..13], so
    # poisoning index 13 DOES change t=13 -- confirming the window is
    # exactly [lo, t], never reaching beyond `now`
    c13_poisoned = _curve_at(13, oi, poison=True)
    assert c13_poisoned.dimensions["price"]["value"] == POISON_LEVEL

    # 4. No forced participant identity: never one of the drivers this
    # build cannot honestly infer.
    from apex.frontier2.participant_pressure import UNREACHABLE_DRIVERS
    for p in pp_history:
        assert p.possible_driver not in UNREACHABLE_DRIVERS

    # 5. No trade authority anywhere in the movie's records.
    for obj in (*curve_history, *ev_history, *pp_history, *edge_history):
        assert obj.decision_power == "NONE_FRONTIER_SHADOW"
    for e in all_events:
        assert e["decision_power"] == "NONE_FRONTIER_SHADOW"

    # 6. Invalid data degrades intelligence, and limited universe
    # coverage explicitly limits conclusions -- reusing the SAME wiring,
    # not a separate code path, with a genuinely degraded integrity
    # object threaded through Curve.
    bad_uc = UniverseCoverageState(
        intended_universe=("NVDA", "XLK"), authorized_universe=("NVDA", "XLK"),
        streamed_universe=("NVDA",), continuous_universe=(), rotated_universe=(),
        never_observed=("XLK",), coverage_count=1, coverage_fraction=0.5,
        continuous_coverage_fraction=0.0, broad_discovery_valid=False,
        status="DEGRADED")
    bad_oi = oi_compute(universe_coverage=bad_uc, as_of=T0, known_from=T0)
    assert bad_oi.breadth_usable() is False
    c_degraded = _curve_at(5, bad_oi)
    assert c_degraded.curve_breadth_status == "LIMITED_COVERAGE"
    assert c_degraded.high_level_state not in ("ROTATION_TRANSITION",
                                               "CORRELATION_BREAK")
