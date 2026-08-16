"""CRYPTO EPOCH 0 — observability and orchestration repair.

Two infrastructure defects, found 2026-08-16 after the arena had produced
176 world records and ZERO decisions:

1. The archive could not distinguish "scanned and declined" from "never
   scanned". Only the human-readable daemon log carried that fact, and it
   is not the scientific record. LAB-04's lesson, unapplied to crypto.
2. Intentional disk SUSPEND exited the process, launchd's KeepAlive read
   the exit as a crash and resurrected it into the same starved
   condition -- two correct controls fighting every ~17 minutes, each
   restart re-warming the fabric and breaking book continuity.

The eight proofs the operator required. Nothing here tests, tunes, or
touches a predicate: Crypto Epoch 0 semantics are frozen.
"""
from __future__ import annotations

import json

import pandas as pd
import pytest

from apex.crypto import diskgov, health
from apex.crypto.perception import CryptoChartState
from apex.crypto.playbooks import match_crypto_001, match_crypto_002


def _state(**kw) -> CryptoChartState:
    base = dict(
        product="BTC-USD", t_utc="2026-08-16T18:00:00+00:00", price=100.0,
        r_15m=0.001, r_30m=0.002, r_60m=0.003, r_240m=0.01,
        vwap_24h=99.0, distance_to_vwap=0.01, above_vwap=True,
        pos_in_24h_range=0.9, breakout_4h_up=True, breakout_4h_down=False,
        hi_4h=101.0, lo_4h=98.0, realized_vol_1h_ann=0.5,
        vol_scale_30m=0.004, rvol_hour=2.0, vol_accel=1.5,
        spread_bps=1.0, book_imbalance=0.1, minutes_recorded=180)
    base.update(kw)
    import dataclasses
    allowed = {f.name for f in dataclasses.fields(CryptoChartState)}
    return CryptoChartState(**{k: v for k, v in base.items()
                               if k in allowed})


WORLD = {"btc_eth_rs_60m": 0.01, "uncertain": False}


# --- 1/2: the three outcomes are distinguishable in the record -------------

def test_scanned_with_zero_matches_is_distinguishable_from_never_scanned():
    """The whole point. Both produce zero decisions; only one produced
    evaluation counts."""
    scanned: dict = {}
    match_crypto_001(_state(breakout_4h_up=False), WORLD, scanned)
    assert scanned["C001_evaluated"] == 1
    assert scanned.get("C001_matches", 0) == 0

    never_scanned: dict = {}          # the matcher was simply not called
    assert never_scanned.get("C001_evaluated", 0) == 0
    assert scanned != never_scanned, (
        "a tick that scanned must not look like a tick that did not")


def test_data_health_refusal_is_distinguishable_from_zero_matches():
    refused: dict = {}
    match_crypto_001(_state(rvol_hour=None), WORLD, refused)
    assert refused["C001_blocked_inputs_missing"] == 1
    assert refused.get("C001_volume_pass", 0) == 0

    declined: dict = {}
    match_crypto_001(_state(rvol_hour=0.4), WORLD, declined)
    assert declined.get("C001_blocked_inputs_missing", 0) == 0
    assert declined["C001_structure_pass"] == 1     # got past structure
    assert declined.get("C001_volume_pass", 0) == 0  # stopped at volume


def test_the_funnel_records_where_each_candidate_died():
    t: dict = {}
    match_crypto_001(_state(rvol_hour=0.4), WORLD, t)     # volume floor
    assert t["C001_structure_pass"] == 1 and "C001_volume_pass" not in t
    t2: dict = {}
    match_crypto_002(_state(rvol_hour=0.5), WORLD, {"high": 10}, t2)
    assert t2["C002_blocked_volume"] == 1


# --- 3: telemetry cannot change a decision ---------------------------------

def test_no_telemetry_field_changes_a_decision():
    """Byte-identical outputs with and without tracing, for both matchers,
    across matching and non-matching inputs."""
    cases = [
        (_state(), WORLD),                                  # may match
        (_state(breakout_4h_up=False), WORLD),              # structure fail
        (_state(rvol_hour=0.4), WORLD),                     # volume fail
        (_state(vwap_24h=None), WORLD),                     # fail closed
    ]
    for cs, w in cases:
        a = match_crypto_001(cs, w)
        b = match_crypto_001(cs, w, {})
        assert json.dumps(a, sort_keys=True, default=str) == \
            json.dumps(b, sort_keys=True, default=str)
        a2 = match_crypto_002(cs, w, {"high": 10, "low": 30})
        b2 = match_crypto_002(cs, w, {"high": 10, "low": 30}, {})
        assert json.dumps(a2, sort_keys=True, default=str) == \
            json.dumps(b2, sort_keys=True, default=str)


def test_the_trace_is_write_only_and_cannot_be_read_as_input():
    """A hostile pre-populated trace must not steer the matcher."""
    clean = match_crypto_001(_state(rvol_hour=0.4), WORLD)
    poisoned = match_crypto_001(
        _state(rvol_hour=0.4), WORLD,
        {"C001_matches": 999, "C001_volume_pass": 999})
    assert clean == poisoned is None


# --- 4/5/6: suspension semantics and hysteresis ----------------------------

def _ds(crypto_bytes: int) -> dict:
    reserved = (diskgov.PRODUCTION_RESERVE
                + diskgov.CRITICAL_SERVICE_RESERVE)
    free = reserved + crypto_bytes
    return {**diskgov.disk_state(), "free_bytes": free,
            "available_crypto_bytes": crypto_bytes,
            "mode": "SUSPEND" if crypto_bytes <= 0 else "HEALTHY",
            "may_resume": crypto_bytes >= diskgov.CRYPTO_RESUME_ABOVE}


def test_suspend_does_not_immediately_resume_at_the_same_threshold():
    """THE SAWTOOTH REGRESSION. One spare byte above the kill boundary
    must NOT be enough to come back."""
    at_boundary = _ds(1)
    assert diskgov.must_suspend(at_boundary) is False   # no longer SUSPEND
    assert diskgov.may_resume(at_boundary) is False, (
        "recovery at the boundary that caused suspension is the sawtooth")


def test_recovery_requires_the_hysteresis_margin():
    assert diskgov.may_resume(_ds(diskgov.CRYPTO_RESUME_ABOVE - 1)) is False
    assert diskgov.may_resume(_ds(diskgov.CRYPTO_RESUME_ABOVE)) is True


def test_resume_threshold_is_materially_healthier_than_suspend():
    """The law, asserted rather than assumed."""
    assert diskgov.CRYPTO_RESUME_ABOVE > 0
    assert diskgov.CRYPTO_RESUME_ABOVE >= diskgov.CRYPTO_MINIMAL_BELOW * 2


def test_intentional_suspension_is_distinguishable_from_a_crash(tmp_path,
                                                                monkeypatch):
    monkeypatch.setattr(health, "HEALTH_PATH", tmp_path / "h.json")
    health.write(process_pid=1, suspension_state="SUSPENDED_INTENTIONAL_DISK",
                 last_heartbeat=str(pd.Timestamp.now(tz="UTC")))
    assert health.read()["suspension_state"] == "SUSPENDED_INTENTIONAL_DISK"
    health.write(process_pid=1, suspension_state="RUNNING",
                 last_heartbeat=str(pd.Timestamp.now(tz="UTC")))
    assert health.read()["suspension_state"] == "RUNNING"


def test_the_daemon_stays_alive_instead_of_exiting_into_keepalive():
    src = open("scripts/crypto_daemon.py").read()
    susp = src.split("if must_suspend(ds):", 1)[1].split("continue")[0]
    assert "return 0" not in susp, (
        "exiting on intentional suspension is what KeepAlive resurrects")
    assert "suspended = True" in susp
    assert "may_resume" in src


# --- 7: a stale log cannot imply a healthy (or dead) daemon ----------------

def test_health_is_read_from_the_artifact_not_the_text_log(tmp_path,
                                                           monkeypatch):
    monkeypatch.setattr(health, "HEALTH_PATH", tmp_path / "h.json")
    assert health.read()["status"] == "NO_HEALTH_ARTIFACT", (
        "a missing artifact is UNKNOWN, never healthy")
    now = pd.Timestamp("2026-08-16T18:00:00Z")
    health.write(process_pid=42, last_heartbeat=str(now),
                 suspension_state="RUNNING")
    # the exact observed condition: process alive, ledger current, log stale
    assert health.staleness_seconds(now + pd.Timedelta(minutes=1)) == 60.0
    assert health.staleness_seconds(now + pd.Timedelta(hours=2)) == 7200.0


def test_an_unreadable_health_artifact_is_not_reported_as_healthy(tmp_path,
                                                                  monkeypatch):
    p = tmp_path / "h.json"
    monkeypatch.setattr(health, "HEALTH_PATH", p)
    p.write_text('{"artifact": "crypto_health_v1", "last_heart')  # torn
    assert health.read()["status"] == "HEALTH_ARTIFACT_UNREADABLE"
    assert health.staleness_seconds() is None      # unknown, never zero


def test_the_health_write_is_atomic(tmp_path, monkeypatch):
    monkeypatch.setattr(health, "HEALTH_PATH", tmp_path / "h.json")
    health.write(process_pid=1, last_heartbeat="a")
    health.write(process_pid=2, last_heartbeat="b")
    assert health.read()["process_pid"] == 2
    assert not (tmp_path / "h.tmp").exists(), "temp file left behind"


# --- 8: Epoch 0 decision semantics are unchanged ---------------------------

def test_epoch0_predicates_and_thresholds_are_untouched():
    """Guard against tuning from today's diagnostics. These are the frozen
    numbers; changing one is an Epoch break, not a repair."""
    import apex.crypto.playbooks as pb
    assert (pb.C001_RVOL_MIN, pb.C001_ACCEL_MIN) == (1.5, 1.3)
    assert (pb.C001_RISK_MIN, pb.C001_RISK_MAX) == (0.001, 0.015)
    assert (pb.C002_RETRACE_MIN, pb.C002_RETRACE_MAX) == (0.50, 1.00)
    assert pb.C002_RVOL_MIN == 1.2
    assert pb.C002_EXTREME_WINDOW_MIN == 45
    assert (pb.C002_RISK_MIN, pb.C002_RISK_MAX) == (0.0015, 0.03)


def test_the_scan_tick_holds_no_decision_power():
    src = open("apex/crypto/arena.py").read()
    assert '"decision_power": "NONE_OBSERVATIONAL_EPOCH0"' in src
    # nothing downstream may branch on the tally
    body = src.split("trace: dict = {}", 1)[1]
    for bad in ("if trace", "trace.get(\"C001_matches\") >",
                "if trace["):
        assert bad not in body, f"a decision branched on telemetry: {bad}"


def test_zero_matches_remains_completely_legal():
    """A quiet tape must produce a COMPLETE_HEALTHY scan with no matches
    and no error. Selectivity is the design, not a fault."""
    t: dict = {}
    assert match_crypto_001(_state(breakout_4h_up=False), WORLD, t) is None
    assert t["C001_evaluated"] == 1
    assert t.get("C001_matches", 0) == 0
