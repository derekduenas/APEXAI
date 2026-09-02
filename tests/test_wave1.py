"""Implementation Wave 1 tests.

Every test here encodes a failure that ACTUALLY HAPPENED on
2026-09-01. No predictive tests, no alpha, no capital authority.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from apex.ops.cadence import (Lifecycle, SlotState, classify_slot,
                              expected_slots, latency_distribution,
                              reconcile)
from apex.ops.health_observer import (Registered, Registration,
                                      reconcile_registry)
from apex.ops.resource_governance import (Criticality, GovernanceViolation,
                                          HostBudget, Lifecycle as Life,
                                          Plan, ServiceSpec, headroom_plan)
from apex.ops.writer_health import (Health, Schedule, WriterObservation,
                                    evaluate,
                                    substrate_only_is_never_healthy)
from apex.pulse.checkpoint import (Checkpoint, CheckpointCorrupt,
                                   CheckpointVersionMismatch, RollingState,
                                   UnboundedStateRefused, load, recover,
                                   restore_complexity_probe, write_atomic)

UTC = timezone.utc
MiB = 1024 * 1024
GiB = 1024 * MiB


def _now():
    return datetime(2026, 9, 2, 15, 0, tzinfo=UTC)


# ============================ RESOURCE GOVERNANCE ====================
def _host(ram=7941 * MiB, swap=0):
    return HostBudget(ram_bytes=ram, swap_bytes=swap,
                      non_apex_baseline_bytes=600 * MiB,
                      kernel_cache_reserve_bytes=1200 * MiB)


def test_active_service_cannot_be_unbounded():
    """The apex-pulse defect must be unconstructible."""
    with pytest.raises(GovernanceViolation):
        ServiceSpec(unit="apex-pulse.service",
                    criticality=Criticality.CRITICAL_FACTUAL_INPUT,
                    lifecycle=Life.ACTIVE_REQUIRED,
                    slice_name="system.slice",
                    observed_peak_bytes=4081 * MiB,
                    memory_high=None, memory_max=None)


def test_active_service_cannot_live_in_system_slice():
    with pytest.raises(GovernanceViolation):
        ServiceSpec(unit="apex-pulse.service",
                    criticality=Criticality.CRITICAL_FACTUAL_INPUT,
                    lifecycle=Life.ACTIVE_REQUIRED,
                    slice_name="system.slice",
                    observed_peak_bytes=100 * MiB,
                    memory_high=100 * MiB, memory_max=200 * MiB)


def test_memory_high_above_max_is_incoherent():
    with pytest.raises(GovernanceViolation):
        ServiceSpec(unit="x.service",
                    criticality=Criticality.RESEARCH,
                    lifecycle=Life.ACTIVE_REQUIRED,
                    slice_name="apex-research.slice",
                    observed_peak_bytes=10 * MiB,
                    memory_high=900 * MiB, memory_max=100 * MiB)


def test_headroom_plan_is_derived_from_measurement():
    high, hard = headroom_plan(996397056)          # equity-fabric peak
    assert high == 996397056                        # throttle AT peak
    assert hard == int(996397056 * 1.5)
    assert hard % (100 * MiB) != 0                  # not a round number


def test_headroom_plan_refuses_unmeasured():
    with pytest.raises(ValueError):
        headroom_plan(0)


def _plan_ok():
    specs = [
        ServiceSpec("apex-btc-ws.service",
                    Criticality.CRITICAL_FACTUAL_INPUT,
                    Life.ACTIVE_REQUIRED, "apex-market.slice",
                    61599744, *headroom_plan(61599744),
                    canonical_writer=True),
        ServiceSpec("apex-organism.service",
                    Criticality.RISK_EXECUTION_CRITICAL,
                    Life.ACTIVE_REQUIRED, "apex-market.slice",
                    132595712, *headroom_plan(132595712)),
        ServiceSpec("apex-edgeforge-observatory.service",
                    Criticality.RESEARCH,
                    Life.ACTIVE_REQUIRED, "apex-research.slice",
                    49889280, *headroom_plan(49889280)),
    ]
    return Plan(host=_host(), services=specs)


def test_valid_plan_contains_global_oom():
    r = _plan_ok().validate()
    assert r["GLOBAL_OOM_STRUCTURALLY_CONTAINED"] is True
    assert r["fatal"] == []
    assert r["headroom_bytes"] > 0


def test_working_set_exceeding_allocatable_is_fatal():
    p = _plan_ok()
    p.services.append(ServiceSpec(
        "apex-hog.service", Criticality.RESEARCH, Life.ACTIVE_REQUIRED,
        "apex-research.slice", 9 * GiB, 9 * GiB, 9 * GiB))
    r = p.validate()
    assert r["GLOBAL_OOM_STRUCTURALLY_CONTAINED"] is False
    with pytest.raises(GovernanceViolation):
        p.enforce()


def test_aggregate_max_over_ram_without_proven_exclusivity_is_fatal():
    """The operator's correction: sum-of-caps may exceed RAM ONLY where
    non-concurrency is proven."""
    p = _plan_ok()
    for s in list(p.services):
        p.services.remove(s)
        p.services.append(ServiceSpec(
            s.unit, s.criticality, s.lifecycle, s.slice_name,
            s.observed_peak_bytes, s.memory_high, 3 * GiB))
    r = p.validate()
    assert r["worst_case_containment"] > r["allocatable_bytes"]
    assert r["GLOBAL_OOM_STRUCTURALLY_CONTAINED"] is False


def test_proven_exclusivity_permits_higher_aggregate():
    p = _plan_ok()
    for s in list(p.services):
        p.services.remove(s)
        p.services.append(ServiceSpec(
            s.unit, s.criticality, s.lifecycle, s.slice_name,
            s.observed_peak_bytes, s.memory_high, 3 * GiB))
    p.proven_exclusive.add(frozenset(("a", "b")))
    r = p.validate()
    assert r["GLOBAL_OOM_STRUCTURALLY_CONTAINED"] is True


def test_service_at_its_cap_is_reported():
    """apex-btc-resolver: MemoryPeak == MemoryMax exactly."""
    p = _plan_ok()
    p.services.append(ServiceSpec(
        "apex-btc-resolver.service", Criticality.RESEARCH,
        Life.ACTIVE_REQUIRED, "apex-research.slice",
        838860800, 800 * MiB, 838860800))
    r = p.validate()
    assert any("REACHED its containment boundary" in f
               for f in r["findings"])


def test_zero_swap_is_surfaced():
    r = _plan_ok().validate()
    assert any("ZERO swap" in f for f in r["findings"])


def test_research_yields_before_factual_input():
    p = _plan_ok()
    assert p.yields_before("apex-edgeforge-observatory.service",
                           "apex-btc-ws.service")
    assert not p.yields_before("apex-btc-ws.service",
                               "apex-edgeforge-observatory.service")
    assert Criticality.RESEARCH.yields_under_pressure
    assert not Criticality.CRITICAL_FACTUAL_INPUT.yields_under_pressure


def test_inactive_ungoverned_unit_is_still_a_landmine():
    p = _plan_ok()
    p.services.append(ServiceSpec(
        "apex-edge-sensor.service", Criticality.RESEARCH,
        Life.INACTIVE_FUTURE, "system.slice", None, None, None))
    r = p.validate()
    assert any("landmine" in f for f in r["fatal"])
    assert len(p.ungoverned()) == 1


# ============================ WRITER HEALTH ==========================
def test_substrate_signals_alone_are_never_healthy():
    """THE btc-paper counterexample: alive + mtime + valid chain."""
    r = substrate_only_is_never_healthy(
        process_alive=True, mtime_changing=True, chain_valid=True,
        now=_now())
    assert r["state"] != Health.HEALTHY.value
    assert r["state"] == Health.FAILED.value


def test_running_process_with_dead_economic_job_is_failed():
    obs = WriterObservation(
        unit="apex-btc-paper.service", now=_now(),
        process_alive=True, unit_enabled=True,
        schedule=Schedule(always_on=True),
        last_valid_output_at=_now() - timedelta(hours=35),
        expected_output_period_s=1800,
        file_mtime_at=_now(), chain_valid=True, restart_count=244)
    r = evaluate(obs)
    assert r["state"] == Health.FAILED.value
    assert any("economic job has stopped" in x for x in r["reasons"])


def test_scheduled_inactive_is_not_failure():
    """equity-fabric between its 06:42Z exit and 12:45Z start."""
    obs = WriterObservation(
        unit="apex-equity-fabric.service",
        now=datetime(2026, 9, 2, 9, 0, tzinfo=UTC),
        process_alive=False, unit_enabled=False,
        schedule=Schedule(windows=[("12:45", "23:59")]),
        last_valid_output_at=datetime(2026, 9, 2, 6, 42, tzinfo=UTC))
    r = evaluate(obs)
    assert r["state"] == Health.SCHEDULED_INACTIVE.value


def test_clean_session_end_is_not_stale():
    """apex-options-paper exited successfully at the close."""
    obs = WriterObservation(
        unit="apex-options-paper.service",
        now=datetime(2026, 9, 2, 23, 0, tzinfo=UTC),
        process_alive=False, unit_enabled=True,
        schedule=Schedule(windows=[("13:30", "20:05")]),
        last_valid_output_at=datetime(2026, 9, 2, 20, 4, tzinfo=UTC))
    assert evaluate(obs)["state"] == Health.SCHEDULED_INACTIVE.value


def test_missing_intervals_produce_evidence_gap():
    obs = WriterObservation(
        unit="w", now=_now(), process_alive=True, unit_enabled=True,
        schedule=Schedule(always_on=True),
        last_valid_output_at=_now() - timedelta(seconds=30),
        expected_output_period_s=60,
        missing_intervals=37, chain_valid=True)
    assert evaluate(obs)["state"] == Health.EVIDENCE_GAP.value


def test_valid_chain_with_short_denominator_is_evidence_gap():
    """chain valid != evidence continuous."""
    obs = WriterObservation(
        unit="w", now=_now(), process_alive=True, unit_enabled=True,
        schedule=Schedule(always_on=True),
        last_valid_output_at=_now() - timedelta(seconds=10),
        expected_output_period_s=60,
        expected_denominator=726, actual_denominator=625,
        chain_valid=True)
    assert evaluate(obs)["state"] == Health.EVIDENCE_GAP.value


def test_restart_does_not_restore_health():
    obs = WriterObservation(
        unit="w", now=_now(), process_alive=True, unit_enabled=True,
        schedule=Schedule(always_on=True),
        last_valid_output_at=_now() - timedelta(seconds=10),
        expected_output_period_s=60,
        restart_count=96, oom_count=96, chain_valid=True)
    r = evaluate(obs)
    assert r["state"] == Health.DEGRADED.value
    assert any("restart does not restore evidence health" in x
               for x in r["reasons"])


def test_genuinely_healthy_writer():
    obs = WriterObservation(
        unit="apex-btc-ws.service", now=_now(),
        process_alive=True, unit_enabled=True,
        schedule=Schedule(always_on=True),
        last_valid_output_at=_now() - timedelta(seconds=5),
        expected_output_period_s=60,
        expected_denominator=1440, actual_denominator=1440,
        missing_intervals=0, chain_valid=True)
    assert evaluate(obs)["state"] == Health.HEALTHY.value


# ============================ CADENCE ================================
def test_expected_denominator_comes_from_schedule():
    slots = expected_slots(datetime(2026, 9, 1, 8, 0, tzinfo=UTC),
                           datetime(2026, 9, 1, 20, 5, tzinfo=UTC))
    assert len(slots) == 726          # the real PULSE_V0 denominator


def test_true_occupancy_not_internal_work():
    """PULSE_V0: internal 28.4s, true occupancy 85.8s."""
    s = datetime(2026, 9, 1, 18, 43, tzinfo=UTC)
    lc = Lifecycle(scheduled_time=s,
                   service_start=s + timedelta(seconds=0.5),
                   capture_start=s + timedelta(seconds=57.4),
                   persistence_complete=s + timedelta(seconds=85.8))
    assert lc.true_slot_occupancy_s == pytest.approx(85.8, abs=0.1)
    assert lc.internal_work_s == pytest.approx(28.4, abs=0.1)
    assert lc.startup_s == pytest.approx(57.4, abs=0.1)
    assert lc.occupies_next_slot()


def test_oom_killed_slot_classified_from_kernel_not_app():
    """The cycle wrote nothing; only the kernel knows."""
    s = datetime(2026, 9, 1, 18, 44, tzinfo=UTC)
    st = classify_slot(s, lifecycle=None,
                       oom_kills={s + timedelta(seconds=34)},
                       start_events={s})
    assert st is SlotState.OOM_KILLED


def test_overrun_collision_classified():
    s = datetime(2026, 9, 1, 18, 6, tzinfo=UTC)
    st = classify_slot(s, lifecycle=None, start_events=set(),
                       prior_occupied=True)
    assert st is SlotState.OVERRUN_COLLISION


def test_missed_no_invocation_distinct_from_oom():
    s = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
    assert classify_slot(s, lifecycle=None) is \
        SlotState.MISSED_NO_INVOCATION


def test_completed_late_vs_on_time():
    s = datetime(2026, 9, 1, 8, 0, tzinfo=UTC)
    fast = Lifecycle(scheduled_time=s,
                     persistence_complete=s + timedelta(seconds=8))
    slow = Lifecycle(scheduled_time=s,
                     persistence_complete=s + timedelta(seconds=85))
    assert classify_slot(s, lifecycle=fast) is SlotState.COMPLETED_ON_TIME
    assert classify_slot(s, lifecycle=slow) is SlotState.COMPLETED_LATE


def test_reconciliation_reproduces_pulse_v0():
    states = {}
    base = datetime(2026, 9, 1, 8, 0, tzinfo=UTC)
    for i in range(726):
        t = base + timedelta(minutes=i)
        if i < 625:
            states[t] = SlotState.COMPLETED_ON_TIME
        elif i < 625 + 77:
            states[t] = SlotState.OOM_KILLED
        else:
            states[t] = SlotState.OVERRUN_COLLISION
    r = reconcile(states)
    assert r["expected_slots"] == 726
    assert r["observed"] == 625
    assert r["LOST_PROSPECTIVE_OBSERVATIONS"] == 101
    assert r["miss_rate_pct"] == pytest.approx(13.912, abs=0.01)
    assert r["reconciles"]


def test_latency_reports_both_distributions():
    s = datetime(2026, 9, 1, 8, 0, tzinfo=UTC)
    lcs = [Lifecycle(scheduled_time=s + timedelta(minutes=i),
                     capture_start=s + timedelta(minutes=i, seconds=40),
                     persistence_complete=s + timedelta(minutes=i,
                                                        seconds=70))
           for i in range(10)]
    d = latency_distribution(lcs)
    assert d["AUTHORITATIVE_true_slot_occupancy"]["p50"] == 70.0
    assert d["DIAGNOSTIC_internal_work"]["p50"] == 30.0


# ============================ CHECKPOINT =============================
def test_checkpoint_roundtrip(tmp_path):
    ck = Checkpoint(session_date="2026-09-02", cycle_number=42)
    ck.rolling.observe("SPY", _now(), 761.9, 1000)
    info = write_atomic(tmp_path / "ck.json", ck)
    back = load(tmp_path / "ck.json")
    assert back.cycle_number == 42
    assert back.rolling.observations["SPY"][0][1] == 761.9
    assert info["bytes"] < 8 * 1024 * 1024


def test_checkpoint_corruption_detected(tmp_path):
    p = tmp_path / "ck.json"
    write_atomic(p, Checkpoint(session_date="2026-09-02"))
    d = json.loads(p.read_text())
    d["cycle_number"] = 999                    # tamper
    p.write_text(json.dumps(d))
    with pytest.raises(CheckpointCorrupt):
        load(p)


def test_checkpoint_invalid_json_detected(tmp_path):
    p = tmp_path / "ck.json"
    p.write_text("{not json")
    with pytest.raises(CheckpointCorrupt):
        load(p)


def test_checkpoint_version_mismatch(tmp_path):
    p = tmp_path / "ck.json"
    write_atomic(p, Checkpoint(session_date="2026-09-02"))
    d = json.loads(p.read_text())
    d["schema_version"] = "PULSE_BOUNDED_STATE_V0"
    p.write_text(json.dumps(d))
    with pytest.raises(CheckpointVersionMismatch):
        load(p)


def test_rolling_state_is_bounded_by_window():
    r = RollingState(window_minutes=60)
    t0 = _now()
    for i in range(600):                       # 10 hours of minutes
        r.observe("SPY", t0 + timedelta(minutes=i), 100.0 + i)
    r.prune_all(t0 + timedelta(minutes=599))
    assert r.cardinality() <= r.bound(subjects=1)
    assert r.cardinality() <= 61


def test_oversized_checkpoint_is_refused(tmp_path):
    """An unbounded checkpoint is PULSE-005 in a different hat."""
    ck = Checkpoint(session_date="2026-09-02")
    t0 = _now()
    for s in range(300):
        for i in range(60):
            ck.rolling.observations.setdefault(f"SYM{s}", []).append(
                [(t0 + timedelta(minutes=i)).isoformat(), 1.0, 1])
    with pytest.raises(UnboundedStateRefused):
        write_atomic(tmp_path / "ck.json", ck, max_bytes=64 * 1024)


def test_full_history_fallback_is_permanently_refused(tmp_path):
    with pytest.raises(UnboundedStateRefused):
        recover(tmp_path / "missing.json",
                bounded_rebuild=lambda d: Checkpoint(session_date=d),
                session_date="2026-09-02", allow_full_history=True)


def test_recover_uses_bounded_rebuild_when_missing(tmp_path):
    ck, how = recover(tmp_path / "missing.json",
                      bounded_rebuild=lambda d: Checkpoint(session_date=d),
                      session_date="2026-09-02")
    assert "BOUNDED_REBUILD" in how
    assert ck.session_date == "2026-09-02"


def test_recover_rebuilds_on_session_change(tmp_path):
    p = tmp_path / "ck.json"
    write_atomic(p, Checkpoint(session_date="2026-09-01"))
    ck, how = recover(p, bounded_rebuild=lambda d: Checkpoint(
        session_date=d), session_date="2026-09-02")
    assert how == "BOUNDED_REBUILD (session_date changed)"


def test_restore_complexity_independent_of_ledger_size(tmp_path):
    """The acceptance property: evidence grows, restore cost does not."""
    p = tmp_path / "ck.json"
    ck = Checkpoint(session_date="2026-09-02")
    for i in range(60):
        ck.rolling.observe("SPY", _now() + timedelta(minutes=i), 1.0)
    write_atomic(p, ck)
    small = restore_complexity_probe(p, ledger_bytes=1 * MiB)
    huge = restore_complexity_probe(p, ledger_bytes=2103328140)
    assert small["checkpoint_bytes"] == huge["checkpoint_bytes"]
    assert huge["BOUNDED"]
    assert huge["ratio"] < 0.01


def test_atomic_write_leaves_no_partial(tmp_path):
    p = tmp_path / "ck.json"
    write_atomic(p, Checkpoint(session_date="2026-09-02"))
    assert not list(tmp_path.glob("*.tmp"))
    assert load(p).session_date == "2026-09-02"


# ============================ OBSERVER REGISTRY ======================
def test_orphan_heartbeat_is_not_an_active_organ(tmp_path):
    hb = tmp_path / "heartbeats"
    hb.mkdir()
    (hb / "capital-arena-shadow.json").write_text("{}")
    (hb / "btc-ws.json").write_text("{}")
    registry = [Registered("apex-btc-ws.service",
                           Registration.REGISTERED_ACTIVE,
                           heartbeat="btc-ws.json")]
    r = reconcile_registry(registry, hb, now=_now())
    assert len(r["orphans"]) == 1
    assert r["orphans"][0]["file"] == "capital-arena-shadow.json"
    assert r["orphans"][0]["registration"] == \
        Registration.ORPHAN_ARTIFACT.value


def test_missing_heartbeat_for_registered_service_is_reported(tmp_path):
    hb = tmp_path / "heartbeats"
    hb.mkdir()
    registry = [Registered("apex-pulse.service",
                           Registration.REGISTERED_SCHEDULED,
                           heartbeat="pulse.json")]
    r = reconcile_registry(registry, hb, now=_now())
    assert len(r["expected_but_missing"]) == 1
    assert "absence of a file is NOT absence of a service" in \
        r["expected_but_missing"][0]["verdict"]


def test_decommissioned_heartbeat_is_registered_not_orphan(tmp_path):
    hb = tmp_path / "heartbeats"
    hb.mkdir()
    (hb / "options-acquire.json").write_text("{}")
    registry = [Registered("apex-options-acquire.service",
                           Registration.DECOMMISSIONED,
                           heartbeat="options-acquire.json")]
    r = reconcile_registry(registry, hb, now=_now())
    assert r["orphans"] == []
    assert r["registered_found"][0]["registration"] == \
        Registration.DECOMMISSIONED.value
