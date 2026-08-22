"""FRONTIER FORWARD-PROGRESS HARDENING (Phase 0.3).

Proves, mechanically, that the 2026-08-17 stall shape is (a) correctly
DIAGNOSED by ServiceProgressState/the watchdog, and (b) can no longer
happen silently in scripts/frontier_loop.py: a malformed watchlist entry
(the actual root cause) is now skipped and recorded, cycles advance, and
a STALLED/FAILED service structurally loses decision authority.
"""
from __future__ import annotations

import json

import pandas as pd
import pytest

from apex.governance.service_progress import (
    DEGRADED, FAILED, HEALTHY, STALLED, STARTING,
    ServiceProgressState, check_pid_matches_state, is_pid_alive, start,
    watchdog_classify,
)


# ---------------------------------------------------- classification
def test_fresh_service_is_starting():
    s = start("frontier_loop", expected_cadence_s=120)
    assert s.progress_status() == STARTING


def test_the_exact_2026_08_17_shape_is_never_healthy():
    """cycle_start advances (heartbeat) but last_successful_cycle NEVER
    populates -- the exact repeated-KeyError shape, ~150 consecutive
    failures over ~3h. Must read FAILED (worse than merely STALLED, per
    the >=8-consecutive-failures threshold) -- never HEALTHY, no matter
    how recently the last (failing) attempt was."""
    s = start("frontier_loop", expected_cadence_s=120)
    s.cycle_number = 87
    s.last_cycle_start = str(pd.Timestamp.now(tz="UTC"))
    s.consecutive_failures = 87
    s.total_failures = 87
    s.last_successful_cycle = None
    assert s.progress_status() == FAILED
    assert s.progress_status() != HEALTHY


def test_a_few_early_failures_before_any_success_is_stalled():
    """Fewer than the FAILED threshold, but still zero successes ever:
    STALLED, not STARTING (a real cycle was attempted and failed)."""
    s = start("frontier_loop", expected_cadence_s=120)
    s.cycle_number = 2
    s.consecutive_failures = 2
    s.last_successful_cycle = None
    assert s.progress_status() == STALLED


def test_recovers_to_healthy_after_a_success():
    s = start("frontier_loop", expected_cadence_s=120)
    s.cycle_number = 5
    s.consecutive_failures = 4
    s.last_successful_cycle = str(pd.Timestamp.now(tz="UTC"))
    s.consecutive_failures = 0                # what a success resets
    assert s.progress_status() == HEALTHY


def test_stale_success_ages_into_stalled():
    s = start("frontier_loop", expected_cadence_s=60)
    old = pd.Timestamp.now(tz="UTC") - pd.Timedelta(seconds=600)
    s.cycle_number = 10
    s.last_successful_cycle = str(old)
    assert s.progress_status() == STALLED


def test_occasional_failure_is_degraded_not_stalled():
    s = start("frontier_loop", expected_cadence_s=120)
    s.cycle_number = 10
    s.last_successful_cycle = str(pd.Timestamp.now(tz="UTC"))
    s.consecutive_failures = 1
    assert s.progress_status() == DEGRADED


def test_many_consecutive_failures_is_failed():
    s = start("frontier_loop", expected_cadence_s=120)
    s.cycle_number = 20
    s.consecutive_failures = 9
    assert s.progress_status() == FAILED


# --------------------------------------------------------- restart semantics
def test_new_pid_never_inherits_old_pid_health():
    old_record = {"pid": 111, "cycle_number": 500,
                 "last_successful_cycle": str(pd.Timestamp.now(tz="UTC")),
                 "progress_status": HEALTHY}
    matches, why = check_pid_matches_state(old_record, current_pid=222)
    assert not matches
    assert "PID_MISMATCH" in why


def test_no_persisted_state_is_not_a_match():
    matches, why = check_pid_matches_state(None, current_pid=1)
    assert not matches and why == "NO_PERSISTED_STATE"


# --------------------------------------------------------------- watchdog
def test_watchdog_independently_flags_heartbeat_without_progress():
    """The exact 2026-08-17 shape, seen from an EXTERNAL watchdog's
    point of view (no trust in a self-reported status string)."""
    record = {"pid": 999, "cycle_number": 90,
             "last_cycle_start": str(pd.Timestamp.now(tz="UTC")),
             "last_successful_cycle": None,
             "consecutive_failures": 90, "expected_cadence_s": 120,
             "progress_status": "HEALTHY"}       # a self-report to distrust
    verdict = watchdog_classify(record, current_pid=999, pid_alive=True)
    assert verdict["progress_status"] == STALLED
    assert "heartbeat" in verdict["reason"]


def test_watchdog_flags_stale_pid_as_stopped():
    record = {"pid": 111, "cycle_number": 5,
             "last_successful_cycle": str(pd.Timestamp.now(tz="UTC")),
             "progress_status": HEALTHY}
    verdict = watchdog_classify(record, current_pid=222, pid_alive=True)
    assert verdict["progress_status"] == "STOPPED"


# ---------------------------------------------- live rehearsal (the fix)
def _watchlist_scan(entries, t_utc):
    from apex.hunter.watchlist import make_entry
    return {"kind": "scan", "t_utc": t_utc, "watchlist": [
        e.as_record() if not isinstance(e, dict) else e for e in entries]}


def test_live_rehearsal_the_actual_crash_no_longer_crashes(
        tmp_path, monkeypatch):
    """Reproduces the EXACT 2026-08-17 sequence through the real
    frontier_loop.tick() function: empty watchlist, then the first real
    dict-shaped entry, across consecutive cycles. Proves forward progress
    -- no exception, and each cycle is independently callable in a loop
    (the shape scripts/frontier_loop.py's main() actually runs)."""
    import sys
    sys.path.insert(0, "scripts")
    import frontier_loop as fl
    from apex.hunter.watchlist import make_entry

    ledger = tmp_path / "forward_ledger.jsonl"
    monkeypatch.setattr(fl, "OFFICIAL", ledger)
    monkeypatch.setattr(fl, "FASTWATCH", tmp_path / "fw.jsonl")
    monkeypatch.setattr(fl, "STATE", tmp_path / "state.json")
    monkeypatch.setattr(fl, "REFUSALS", tmp_path / "refusals.jsonl")

    scans = [
        _watchlist_scan([], "2026-08-17T14:20:00+00:00"),
        _watchlist_scan([make_entry("CBRS", ["GAP_AND_GO"], None,
                                    rvol_status="INVALID_MISSING_SESSION_START")],
                       "2026-08-17T14:52:10+00:00"),
        _watchlist_scan([make_entry("CBRS", ["GAP_AND_GO"], None,
                                    rvol_status="INVALID_MISSING_SESSION_START"),
                        make_entry("AXTI", ["GAP_AND_GO"], None,
                                  rvol_status="INVALID_MISSING_SESSION_START")],
                       "2026-08-17T15:07:56+00:00"),
    ]

    st = {"day": "2026-08-17", "child_calls": 0, "carded": [],
         "bus_seen": [], "persistence": {}, "traced": [],
         "opportunity_states": {}, "shadow_positions": {}}

    for i, scan in enumerate(scans):
        with ledger.open("a") as f:
            f.write(json.dumps(scan) + "\n")
        # this is EXACTLY what crashed on 2026-08-17: calling tick() as
        # the watchlist transitions from empty to real dict entries
        fl.tick(st, service_progress_status="HEALTHY")   # must not raise

    assert st["traced"], "watchlist entries should have been traced"
    refusals_path = tmp_path / "refusals.jsonl"
    if refusals_path.exists():
        # today (2026-08-17) is session-integrity-invalid, so any carded
        # candidate would be a refusal, never a silently-sealed card
        for line in refusals_path.read_text().splitlines():
            rec = json.loads(line)
            assert rec["gate"] in ("SESSION_INTEGRITY_GATE",
                                   "SERVICE_HEALTH_GATE")


def test_service_health_gate_refuses_even_a_valid_session(tmp_path, monkeypatch):
    """KILL/DEGRADE LAW: a STALLED Frontier loses decision authority
    even on a day that is otherwise session-integrity-eligible."""
    import sys
    sys.path.insert(0, "scripts")
    import frontier_loop as fl

    ledger = tmp_path / "forward_ledger.jsonl"
    monkeypatch.setattr(fl, "OFFICIAL", ledger)
    monkeypatch.setattr(fl, "FASTWATCH", tmp_path / "fw.jsonl")
    monkeypatch.setattr(fl, "STATE", tmp_path / "state.json")
    refusals = tmp_path / "refusals.jsonl"
    monkeypatch.setattr(fl, "REFUSALS", refusals)
    # a future date the session_integrity_gate does NOT name -> eligible
    future_day = "2026-08-18"
    dec = {"kind": "decision", "decision_id": "D1", "symbol": "TEST",
          "playbook_id": "HUNTER-001_v1", "t_utc": f"{future_day}T15:05:00Z",
          "session_date": future_day}
    with ledger.open("w") as f:
        f.write(json.dumps(dec) + "\n")
        f.write(json.dumps(_watchlist_scan(
            [], f"{future_day}T15:05:00+00:00")) + "\n")

    st = {"day": future_day, "child_calls": 0, "carded": [],
         "bus_seen": [], "persistence": {}, "traced": [],
         "opportunity_states": {}, "shadow_positions": {}}
    fl.tick(st, service_progress_status="STALLED")   # the KILL/DEGRADE LAW

    assert "D1" in st["carded"]                      # seen, not retried
    assert refusals.exists()
    rec = json.loads(refusals.read_text().splitlines()[0])
    assert rec["gate"] == "SERVICE_HEALTH_GATE"
    assert "STALLED" in rec["reason"]
