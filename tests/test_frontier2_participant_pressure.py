"""ParticipantPressureState — F3. Proves possible_driver defaults to
UNKNOWN, the ten drivers this build cannot honestly infer tonight are
mechanically unreachable, and trap/direction can still be described
from price action alone when driver identity cannot.
"""
from __future__ import annotations

import pandas as pd
import pytest

from apex.frontier2.participant_pressure import (UNREACHABLE_DRIVERS,
                                                  ParticipantPressureError,
                                                  ParticipantPressureState,
                                                  infer)

T0 = pd.Timestamp("2026-08-18T14:00:00Z")


def test_no_pattern_active_is_all_unknown_or_none():
    st = infer("AAPL", rvol_tod=1.0, event_time=T0, known_from=T0, now=T0)
    assert st.possible_driver == "UNKNOWN"
    assert st.trap_state == "NONE"
    assert st.pressure_direction == "NONE"


def test_zero_inputs_is_unknown_direction_not_none():
    """With not even an rvol reading, direction cannot honestly be
    called NONE (that implies 'checked and found nothing') -- must be
    UNKNOWN (never checked)."""
    st = infer("AAPL", event_time=T0, known_from=T0, now=T0)
    assert st.pressure_direction == "UNKNOWN"
    assert st.forced_action_potential == "UNKNOWN"


@pytest.mark.parametrize("driver", UNREACHABLE_DRIVERS)
def test_unreachable_drivers_refuse_construction(driver):
    with pytest.raises(ParticipantPressureError):
        ParticipantPressureState(
            candidate="AAPL", possible_driver=driver, pressure_direction="UP",
            forced_action_potential="LOW", trap_state="NONE", support=(),
            contradictions=(), falsification="x", quality="UNKNOWN",
            uncertainty="HIGH", event_time=str(T0), known_from=str(T0),
            as_of=str(T0))


def test_failed_breakdown_reclaim_is_possible_short_trap_with_short_covering():
    st = infer("AAPL", or_break_down=True, or_failure=True, rvol_tod=3.0,
              event_time=T0, known_from=T0, now=T0)
    assert st.trap_state == "POSSIBLE_SHORT_TRAP"
    assert st.pressure_direction == "UP"
    assert st.possible_driver == "SHORT_COVERING"


def test_failed_breakdown_without_elevated_rvol_has_no_driver():
    """The SHORT_COVERING inference specifically requires elevated
    participation -- a quiet failed breakdown names a trap, not a
    driver."""
    st = infer("AAPL", or_break_down=True, or_failure=True, rvol_tod=0.8,
              event_time=T0, known_from=T0, now=T0)
    assert st.trap_state == "POSSIBLE_SHORT_TRAP"
    assert st.possible_driver == "UNKNOWN"


def test_failed_breakout_is_possible_long_trap_direction_down():
    st = infer("AAPL", or_break_up=True, or_failure=True, rvol_tod=3.0,
              event_time=T0, known_from=T0, now=T0)
    assert st.trap_state == "POSSIBLE_LONG_TRAP"
    assert st.pressure_direction == "DOWN"
    # long-trap unwind driver identity is never claimed by this build
    assert st.possible_driver == "UNKNOWN"


def test_subsequent_hold_true_confirms_the_trap():
    st = infer("AAPL", or_break_down=True, or_failure=True, rvol_tod=3.0,
              subsequent_hold=True, event_time=T0, known_from=T0, now=T0)
    assert st.trap_state == "CONFIRMED_BY_PRICE_ACTION"


def test_subsequent_hold_false_makes_it_unclear_not_confirmed():
    st = infer("AAPL", or_break_down=True, or_failure=True, rvol_tod=3.0,
              subsequent_hold=False, event_time=T0, known_from=T0, now=T0)
    assert st.trap_state == "UNCLEAR"
    assert "subsequent_hold_failed_to_confirm" in st.contradictions


def test_vwap_reclaim_with_momentum_is_momentum_chase_up():
    st = infer("AAPL", vwap_reclaim=True, rvol_tod=2.5, trend_slope=0.03,
              event_time=T0, known_from=T0, now=T0)
    assert st.pressure_direction == "UP"
    assert st.possible_driver == "MOMENTUM_CHASE"


def test_vwap_rejection_with_momentum_is_momentum_chase_down():
    st = infer("AAPL", vwap_rejection=True, rvol_tod=2.5, trend_slope=-0.03,
              event_time=T0, known_from=T0, now=T0)
    assert st.pressure_direction == "DOWN"
    assert st.possible_driver == "MOMENTUM_CHASE"


def test_vwap_reclaim_without_elevated_rvol_fires_nothing():
    st = infer("AAPL", vwap_reclaim=True, rvol_tod=1.0, trend_slope=0.03,
              event_time=T0, known_from=T0, now=T0)
    assert st.possible_driver == "UNKNOWN"
    assert st.trap_state == "NONE"


def test_more_support_lowers_uncertainty():
    weak = infer("AAPL", vwap_reclaim=True, rvol_tod=1.0, event_time=T0,
                 known_from=T0, now=T0)
    strong = infer("AAPL", or_break_down=True, or_failure=True, rvol_tod=3.0,
                   subsequent_hold=True, event_time=T0, known_from=T0, now=T0)
    assert weak.uncertainty == "HIGH"
    assert strong.uncertainty == "LOW"


def test_falsification_condition_always_named_when_a_pattern_fires():
    st = infer("AAPL", or_break_down=True, or_failure=True, rvol_tod=3.0,
              event_time=T0, known_from=T0, now=T0)
    assert "reclaims" not in st.falsification  # sanity: is the DOWN-side text
    assert st.falsification


def test_determinism_same_inputs_twice_byte_identical():
    a = infer("AAPL", or_break_down=True, or_failure=True, rvol_tod=3.0,
             event_time=T0, known_from=T0, now=T0)
    b = infer("AAPL", or_break_down=True, or_failure=True, rvol_tod=3.0,
             event_time=T0, known_from=T0, now=T0)
    assert a.as_record() == b.as_record()


def test_persist_writes_and_chains(tmp_path, monkeypatch):
    import apex.frontier2.participant_pressure as pp
    monkeypatch.setattr(pp, "LEDGER", tmp_path / "pp.jsonl")
    st = infer("AAPL", or_break_down=True, or_failure=True, rvol_tod=3.0,
              event_time=T0, known_from=T0, now=T0)
    rec1 = pp.persist(st)
    rec2 = pp.persist(st)
    assert rec2["prev_hash"] == rec1["entry_hash"]
    assert rec1["decision_power"] == "NONE_FRONTIER_SHADOW"
