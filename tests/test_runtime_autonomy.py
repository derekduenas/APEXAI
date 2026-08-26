"""PHASE A CONTRACTS — APEX must show up by itself.

Every test here exists because 2026-08-25 was lost to "deployed
capability != running capability".
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from apex.ops.orchestrator import (ArmCheck, OrchestratorViolation,
                                   ServiceSpec, default_roster,
                                   evaluate_arm, is_trading_day,
                                   missed_start_verdict, phase_at,
                                   reconcile_expected, session_bounds)
from apex.ops.outbox import (Cursor, OutboxViolation, consume,
                             consumer_health, emit, pending,
                             read_records)
from apex.ops.release_gate import (ReleaseGateViolation, build_manifest,
                                   preopen_gate)


def U(s):
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


# ==================================================== CALENDAR

def test_half_days_are_not_four_oclock():
    """A hardcoded 16:00 would arm paper trading into three hours of a
    closed market."""
    half = session_bounds("2026-11-27")      # day after Thanksgiving
    full = session_bounds("2026-11-30")
    assert half["half_day"] is True
    assert half["close_utc"].hour < full["close_utc"].hour


def test_holidays_and_weekends_are_not_trading_days():
    assert is_trading_day("2026-11-26") is False   # Thanksgiving
    assert is_trading_day("2026-08-29") is False   # Saturday
    assert is_trading_day("2026-08-26") is True
    b = session_bounds("2026-11-26")
    assert b["open_utc"] is None


def test_a_holiday_never_reaches_a_trading_phase():
    for hour in range(0, 24):
        p = phase_at(U(f"2026-11-26T{hour:02d}:00:00"), "2026-11-26")
        assert p["phase"] == "IDLE"


def test_the_lifecycle_walks_in_order_on_a_normal_day():
    s = "2026-08-26"
    seq = [phase_at(U(f"2026-08-26T{t}"), s)["phase"]
           for t in ("06:00:00", "13:00:00", "13:27:00",
                     "15:00:00", "20:30:00", "23:00:00")]
    assert seq == ["IDLE", "PREOPEN", "SESSION_ARMED", "RTH",
                   "POST_CLOSE", "IDLE"]


# ==================================================== ARMING

def test_a_required_check_that_fails_refuses_the_arm():
    r = evaluate_arm(session="2026-08-26", now_utc=U(
        "2026-08-26T13:25:00"), checks=[
        ArmCheck("theta alive", True, "ok"),
        ArmCheck("quotes fresh", False, "last quote 400s old")])
    assert r["verdict"] == "ARM_REFUSED"
    assert r["blocking"] == ["quotes fresh"]


def test_optional_failures_do_not_block_the_arm():
    r = evaluate_arm(session="2026-08-26", now_utc=U(
        "2026-08-26T13:25:00"), checks=[
        ArmCheck("theta alive", True, "ok"),
        ArmCheck("dev tree clean", False, "dirty", required=False)])
    assert r["verdict"] == "SESSION_ARMED"
    assert r["non_blocking_failures"] == ["dev tree clean"]


# ==================================================== SENTINEL

def test_alive_is_not_started():
    """The Tuesday failure: a service can be 'fine' and never produce
    a single unit of work."""
    v = missed_start_verdict(
        service="options-paper", phase="RTH",
        expected_lifecycle="EXPECTED_RUNNING", first_work_seen=False,
        seconds_since_phase_start=900, deadline_s=600,
        recovery_attempts=[{"outcome": "FAILED", "detail": "no unit"}],
        dependency_states={"theta-terminal": "MISSING"},
        release="9f9868b")
    assert v["verdict"] == "SESSION_MISSED_START"
    assert v["severity"] == "CRITICAL"
    assert v["dependency_states"]["theta-terminal"] == "MISSING"
    assert v["recovery_attempts"], "evidence must ride with the alarm"


def test_the_sentinel_waits_its_declared_grace():
    v = missed_start_verdict(
        service="options-paper", phase="RTH",
        expected_lifecycle="EXPECTED_RUNNING", first_work_seen=False,
        seconds_since_phase_start=120, deadline_s=600,
        recovery_attempts=[], dependency_states={}, release="x")
    assert v["verdict"] == "WITHIN_GRACE"


def test_first_work_confirms_the_start():
    v = missed_start_verdict(
        service="options-paper", phase="RTH",
        expected_lifecycle="EXPECTED_RUNNING", first_work_seen=True,
        seconds_since_phase_start=9999, deadline_s=600,
        recovery_attempts=[], dependency_states={}, release="x")
    assert v["verdict"] == "WORK_CONFIRMED"


# ==================================================== RECONCILIATION

def test_both_failure_directions_are_critical():
    specs = default_roster("cloud")       # options lives with Theta
    obs = {s.name: True for s in specs}
    obs["options-paper"] = False          # should run in RTH: MISSING
    r = reconcile_expected(phase="RTH", specs=specs,
                           observed_running=obs)
    assert "options-paper" in r["missing"]
    assert r["verdict"] == "CRITICAL"

    obs2 = {s.name: False for s in specs}
    obs2["options-paper"] = True          # should be idle at IDLE
    r2 = reconcile_expected(phase="IDLE", specs=specs,
                            observed_running=obs2)
    assert "options-paper" in r2["unexpectedly_running"]
    assert r2["verdict"] == "CRITICAL"


def test_a_roster_must_know_which_machine_it_describes():
    """ThetaTerminal exists only on the cloud; a host-blind roster
    would try forever to start options on a Mac that cannot run it."""
    mac = {s.name for s in default_roster("mac")}
    cloud = {s.name for s in default_roster("cloud")}
    assert "options-paper" in cloud and "options-paper" not in mac
    assert "equity-fabric" in mac and "equity-fabric" not in cloud
    with pytest.raises(OrchestratorViolation, match="which machine"):
        default_roster("laptop2")


def test_every_service_declares_how_to_start_itself():
    """A spec without a start_cmd cannot be auto-recovered, which is
    the whole failure this phase exists to remove."""
    for host in ("mac", "cloud"):
        for s in default_roster(host):
            assert s.start_cmd, f"{s.name} has no start_cmd"


def test_edgeforge_is_an_always_on_sidecar_not_a_session_job():
    """Tying research observation to a market-open scheduler is what
    lost Tuesday."""
    ef = next(s for s in default_roster("mac")
              if s.name == "edgeforge-observatory")
    assert ef.always_on is True
    for phase in ("IDLE", "PREOPEN", "SESSION_ARMED", "RTH",
                  "POST_CLOSE"):
        assert ef.expected_lifecycle(phase) == "EXPECTED_RUNNING", \
            f"a sidecar must stay supervised in {phase}"


def test_options_paper_is_required_for_arm():
    op = next(s for s in default_roster("cloud")
              if s.name == "options-paper")
    assert op.required_for_arm is True
    assert op.phases_running == ("RTH",)


def test_the_roster_does_not_invent_dependencies():
    """An earlier draft required a ThetaTerminal the options session
    never uses. A roster that invents a dependency reports CRITICAL
    forever for a service that should not exist."""
    names = {s.name for s in default_roster("cloud")}
    assert "theta-terminal" not in names
    for s in default_roster("cloud"):
        for d in s.dependencies:
            assert d in names, f"{s.name} depends on unrostered {d}"


def test_the_calendar_owns_triggering_and_systemd_owns_supervision():
    """systemd OnCalendar cannot express holidays or half-days, so the
    orchestrator triggers; Restart=on-failure then supervises."""
    op = next(s for s in default_roster("cloud")
              if s.name == "options-paper")
    assert op.supervised_by == "orchestrator"
    assert op.externally_supervised is False
    assert "systemctl" in " ".join(op.start_cmd)


# ==================================================== OUTBOX

def _ob(tmp):
    return tmp / "outbox.jsonl", Cursor(path=tmp / "cursor.json",
                                        consumer="edgeforge")


def test_an_observation_without_lineage_is_refused(tmp_path):
    ob, _ = _ob(tmp_path)
    with pytest.raises(OutboxViolation, match="lineage"):
        emit(ob, kind="", session="2026-08-26", payload={},
             source="v1", known_from="x")


def test_the_consumer_catches_up_after_an_outage(tmp_path):
    """THE POINT OF THIS MODULE: a 30-minute EdgeForge outage costs 30
    minutes of latency, not a day of research evidence."""
    ob, cur = _ob(tmp_path)
    for i in range(40):
        emit(ob, kind="boundary_map", session="2026-08-26",
             payload={"i": i}, source="v1", known_from="t")
    seen = []
    r = consume(ob, cur, lambda rec: seen.append(rec) or 1)
    assert r["records_processed"] == 40
    # V1 keeps emitting while the consumer is dead
    for i in range(40, 55):
        emit(ob, kind="boundary_map", session="2026-08-26",
             payload={"i": i}, source="v1", known_from="t")
    r2 = consume(ob, cur, lambda rec: seen.append(rec) or 1)
    assert r2["records_processed"] == 15
    assert len(seen) == 55, "nothing skipped, nothing duplicated"


def test_a_failed_record_is_retried_never_skipped(tmp_path):
    ob, cur = _ob(tmp_path)
    for i in range(5):
        emit(ob, kind="k", session="s", payload={"i": i},
             source="v1", known_from="t")
    calls = {"n": 0}

    def boom(rec):
        calls["n"] += 1
        if rec["payload"]["i"] == 2:
            raise RuntimeError("consumer bug")
        return 1

    r = consume(ob, cur, boom)
    assert r["records_processed"] == 2
    assert r["failed_at"]["seq"] == 2
    assert r["records_remaining"] == 3
    ok = consume(ob, cur, lambda rec: 1)
    assert ok["records_processed"] == 3, "resumes AT the failed record"


def test_committing_the_same_record_twice_is_a_noop(tmp_path):
    ob, cur = _ob(tmp_path)
    emit(ob, kind="k", session="s", payload={}, source="v1",
         known_from="t")
    cur.commit(seq=0, record_hash="h", writes=1)
    before = cur.load()["events_processed"]
    cur.commit(seq=0, record_hash="h", writes=1)
    assert cur.load()["events_processed"] == before


def test_two_consumers_cannot_share_one_cursor(tmp_path):
    ob, cur = _ob(tmp_path)
    emit(ob, kind="k", session="s", payload={}, source="v1",
         known_from="t")
    cur.commit(seq=0, record_hash=None, writes=0)
    other = Cursor(path=cur.path, consumer="someone_else")
    with pytest.raises(OutboxViolation, match="silently skip"):
        other.load()


def test_a_stalled_consumer_during_a_session_is_critical(tmp_path):
    ob, cur = _ob(tmp_path)
    for i in range(120):
        emit(ob, kind="k", session="s", payload={"i": i},
             source="v1", known_from="t")
    h = consumer_health(ob, cur, session_active=True)
    assert h["state"] == "EDGEFORGE_CONSUMER_STALLED"
    assert h["severity"] == "CRITICAL"
    assert h["consumer_lag"] == 120
    quiet = consumer_health(ob, cur, session_active=False)
    assert quiet["state"] == "CATCHING_UP"
    assert quiet["severity"] == "OK"


def test_records_keep_their_source_lineage(tmp_path):
    ob, cur = _ob(tmp_path)
    emit(ob, kind="genome", session="2026-08-26",
         payload={"gap_pct": 0.4}, source="apex.intraday.state",
         known_from="2026-08-26 13:55:00+00:00")
    r = read_records(ob)[0]
    assert r["source"] == "apex.intraday.state"
    assert r["known_from"] == "2026-08-26 13:55:00+00:00"
    assert r["entry_hash"], "chain hash preserved"


# ==================================================== RELEASE GATE

def _manifest(tmp, sha="9f9868b1c", suite="PASS"):
    rel = tmp / sha
    rel.mkdir(parents=True, exist_ok=True)
    m = build_manifest(release_sha=sha, suite_result=suite,
                       suite_passed=2922, suite_artifact_hash="abc123",
                       environment_fingerprint="env1",
                       approved_by="operator")
    (rel / "RELEASE_MANIFEST.json").write_text(json.dumps(m))
    return rel


def test_a_dirty_dev_tree_can_never_block_the_gate(tmp_path):
    """Tuesday's exact failure: overnight research commits disarmed a
    perfectly good deployed release."""
    rel = _manifest(tmp_path)
    g = preopen_gate(active_release_path=rel,
                     canonical_shas=("9f9868b1c",),
                     dev_tree_dirty=True, dev_head_sha="deadbeef")
    assert g["verdict"] == "GATE_PASS"
    dev = [c for c in g["checks"] if c["check"] == "dev tree clean"][0]
    assert dev["ok"] is False and dev["required"] is False
    assert "informational" in dev["detail"]


def test_a_release_with_no_manifest_is_blocked(tmp_path):
    bare = tmp_path / "nomanifest"
    bare.mkdir()
    g = preopen_gate(active_release_path=bare, canonical_shas=(),
                     dev_tree_dirty=False)
    assert g["verdict"] == "GATE_BLOCKED"
    assert "release manifest present" in g["blocking"]


def test_a_release_outside_canonical_history_is_blocked(tmp_path):
    rel = _manifest(tmp_path)
    g = preopen_gate(active_release_path=rel,
                     canonical_shas=("0000000",),
                     dev_tree_dirty=False)
    assert "release in canonical history" in g["blocking"]


def test_a_failing_suite_cannot_be_built_into_a_manifest():
    with pytest.raises(ReleaseGateViolation, match="suite result"):
        build_manifest(release_sha="x", suite_result="FAIL",
                       suite_passed=1, suite_artifact_hash="h",
                       environment_fingerprint="e",
                       approved_by="operator")


def test_an_incomplete_manifest_is_refused():
    with pytest.raises(ReleaseGateViolation, match="unstated check"):
        build_manifest(release_sha="x", suite_result="PASS",
                       suite_passed=1, suite_artifact_hash="h",
                       environment_fingerprint="", approved_by="op")


# ==================================================== RECONNECT LEDGER

def test_ping_timeout_none_no_longer_kills_the_reconnect_writer():
    """THE TUESDAY DEFECT. PING_TIMEOUT_S is None by law; the recency
    window summed it naively and raised TypeError on every reconnect
    BEFORE persist() was reached. 50 counter increments produced 0
    event records across two prospective sessions."""
    from apex.intraday.alpaca_fabric import (PING_INTERVAL_S,
                                             PING_TIMEOUT_S)
    assert PING_TIMEOUT_S is None, "the pong-kill stays disabled"
    recent = 3.0 * (PING_INTERVAL_S + (PING_TIMEOUT_S or 0))
    assert recent == 60.0


def test_the_recency_window_is_computed_safely_in_source():
    from apex.governance.verification import verify_source_contains
    r = verify_source_contains(
        "apex/intraday/alpaca_fabric.py",
        "(PING_TIMEOUT_S or 0)")
    assert r["verdict"] == "SOURCE_CHANGE_PRESENT"


def test_every_spec_name_matches_a_real_heartbeat_identity():
    """A verifier that misnames what it verifies is worse than none.
    The btc spec said 'btc-loop' while the daemon writes 'btc-paper',
    so first_work_seen() always read ABSENT and the sentinel would
    have fired a false SESSION_MISSED_START every session."""
    import subprocess
    from apex.ops.orchestrator import default_roster
    names = {s.name for s in default_roster("mac")}
    assert "btc-paper" in names and "btc-loop" not in names
    # and the daemon's pgrep map must cover every spec it verifies
    src = Path("scripts/apex_orchestrator.py").read_text()
    for n in names:
        assert f'"{n}"' in src, f"{n} has no process pattern"


# ============ HOST QUALIFICATION (operator, 2026-08-26)
# "Do not call a battery/network-degraded day a valid commissioning
#  session."

from apex.ops.host_qualification import (qualify_host,
                                         recent_host_incidents)


def _incidents(tmp_path, rows):
    p = tmp_path / "host.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in rows))
    return p


def test_recent_incidents_respect_the_lookback_window(tmp_path):
    now = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
    p = _incidents(tmp_path, [
        {"kind": "host_network_unreachable",
         "detected_at": "2026-08-26T11:00:00+00:00"},
        {"kind": "host_network_unreachable",
         "detected_at": "2026-08-25T01:00:00+00:00"}])
    rows = recent_host_incidents(kinds=("host_network_unreachable",),
                                 hours=6, now=now, path=p)
    assert len(rows) == 1, "yesterday's failure is not today's"


def test_a_degraded_host_is_safe_blocked_not_failed(tmp_path):
    """The distinction that matters: SAFE_BLOCKED says nothing about
    whether the fabric can hold a clean tape."""
    now = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
    p = _incidents(tmp_path, [
        {"kind": "host_network_unreachable",
         "detected_at": "2026-08-26T11:30:00+00:00"}])
    r = qualify_host(now=now, fabric_ready=True, incidents_path=p)
    assert r["verdict"] == "SAFE_BLOCKED"
    assert "NETWORK_STABLE" in r["blocking"]
    assert r["commissioning_eligible"] is False
    assert "never be counted against it" in r["law"]


def test_an_unready_fabric_blocks_the_session(tmp_path):
    now = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
    p = _incidents(tmp_path, [])
    r = qualify_host(now=now, fabric_ready=False, incidents_path=p)
    assert "FABRIC_READY" in r["blocking"]


def test_all_four_operator_named_gates_are_required(tmp_path):
    now = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
    r = qualify_host(now=now, fabric_ready=True,
                     incidents_path=_incidents(tmp_path, []))
    names = {c["check"] for c in r["checks"]}
    for required in ("AC_POWER", "NETWORK_STABLE", "DISK_OK",
                     "FABRIC_READY"):
        assert required in names
    assert all(c["required"] for c in r["checks"])
