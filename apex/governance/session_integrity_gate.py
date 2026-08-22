"""SESSION INTEGRITY GATE — operator-ratified, dated fail-closed refusal.

2026-08-17 finding (APEX DAY-1 FAIL-CLOSED directive): live equity
observation began at 10:17 ET, 47 minutes after the true 09:30 ET open.
apex/hunter/chartstate.py:164 (`open_t = times.iloc[0]`) treats the
FIRST OBSERVED bar as session open — there is no comparison anywhere in
that function against the true exchange session boundary. Confirmed
against live SPY numbers: this corrupts, not merely degrades, every
session-anchored ChartState field (vwap, opening range, gap, rvol,
cum_volume, minutes_into_session) for the affected date.

THIS IS NOT A REPAIR AND NOT A GENERIC MECHANISM. The instruction was
explicit: do not touch ChartState math or any frozen Hunter/Capital/
Captain semantics mid-session. This module is a deliberately narrow,
dated, auditable REFUSAL LIST consulted only by the operational scripts
(hunter_forward_clock.py, frontier_loop.py) at the exact points where a
record would otherwise claim decision-grade session context. It can only
say NO — it authorizes nothing, computes nothing, and is not part of the
Hunter birth-eligibility law.

The post-close repair (a real SESSION_COVERAGE contract with per-feature
validity, replacing today's `open_t` conflation entirely) retires this
file. Until that lands and the full suite is green again, this dated
list is the only thing standing between a corrupted session and a
record that looks like valid evidence.

decision_power: NONE. REFUSAL_ONLY.
"""
from __future__ import annotations

REFUSED = "REFUSED_PARTIAL_SESSION_STATE"
ELIGIBLE = "ELIGIBLE"

# Dated, explicit, one entry per ratified finding. Never a heuristic.
INVALID_SESSIONS = {
    "2026-08-17": {
        "reason": (
            "chartstate.py:164 open_t=first_observed_bar (10:17 ET) vs "
            "true session open 09:30 ET -- session-anchored features "
            "(vwap/opening_range/gap/rvol/cum_volume/"
            "minutes_into_session) are corrupted, not degraded"),
        "known_from": "2026-08-17T14:50:00+00:00",
        "ratified_by": "operator, APEX DAY-1 FAIL-CLOSED directive",
        "first_observed_bar_et": "10:17",
        "required_start_et": "09:30",
        "affected_fields": (
            "vwap", "distance_to_vwap", "vwap_slope", "above_vwap",
            "vwap_reclaim", "vwap_rejection", "or_complete", "or_high",
            "or_low", "position_in_or", "or_break_up", "or_break_down",
            "or_failure", "gap_frac", "gap_direction", "gap_fill_frac",
            "rvol_tod", "cum_volume", "minutes_into_session",
            "day_return"),
    },
}


def decision_eligible(day: str) -> tuple[bool, str]:
    """(ok, label). False -> the caller must refuse to seal this record
    as decision evidence, but may still persist it as raw observation."""
    if day in INVALID_SESSIONS:
        return False, REFUSED
    return True, ELIGIBLE


def refusal_reason(day: str) -> dict | None:
    return INVALID_SESSIONS.get(day)
