"""Maintenance-block enforcement in the orchestrator's launch path.

Every test drives the REAL decision path in tick() with process creation
intercepted, so a "launch" is observed rather than assumed. No service is ever
started: subprocess.Popen is replaced and asserted against.

WHAT THIS ENFORCES, AND WHAT IT DOES NOT. systemd already refuses a blocked
unit through ConditionPathExists in a drop-in, and that refusal is atomic with
the start. This check runs in the orchestrator BEFORE it asks, so that a
doomed start is not attempted and, above all, not recorded as STARTED. On
2026-09-04 three refused starts were recorded as STARTED in the governance
ledger; that falsification is what this closes.

RACE LIMITATIONS, stated rather than glossed. The check is a file-existence
test and is NOT atomic with block creation. A marker written in the window
between the check and systemd's own evaluation is caught by systemd, not by us.
A marker REMOVED in that window means we refuse a launch that would now have
been permitted, which is the safe direction and self-corrects on the next tick.
The orchestrator's check is therefore an advisory pre-filter whose purpose is
honest recording; systemd remains the enforcing authority.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_spec = importlib.util.spec_from_file_location(
    "apex_orchestrator_maint", ROOT / "scripts" / "apex_orchestrator.py")
ORCH = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ORCH)

from apex.ops.orchestrator import ServiceSpec  # noqa: E402

T0 = datetime(2026, 9, 8, 14, 0, 0, tzinfo=timezone.utc)
SYSTEMCTL = ("/usr/bin/sudo", "-n", "/usr/bin/systemctl", "start")


class _Clock:
    def __init__(self, h):
        self._h = h

    def time(self):
        return self._h["t"].timestamp()

    def sleep(self, _s):
        raise AssertionError("a test must never sleep")


def spec(name="equity-fabric", unit="apex-equity-fabric.service"):
    return ServiceSpec(name=name, phases_running=("RTH",), always_on=True,
                       first_work_deadline_s=1800,
                       start_cmd=SYSTEMCTL + (unit,),
                       supervised_by="orchestrator")


class Rig:
    """A controllable systemd: a drop-in declaring a marker, and the marker."""

    def __init__(self, tmp_path, *, declare=True, marker=False,
                 dropin_readable=True, show_rc=0, show_raises=False):
        self.dir = tmp_path
        self.marker = tmp_path / "MAINTENANCE_BLOCK_equity_fabric"
        self.dropin = tmp_path / "10-maintenance-block.conf"
        self.launches = []
        self.show_rc, self.show_raises = show_rc, show_raises
        if declare:
            self.dropin.write_text(
                "[Unit]\nConditionPathExists=!%s\n" % self.marker)
            if not dropin_readable:
                os.chmod(self.dropin, 0o000)
        else:
            self.dropin.write_text("[Unit]\n")
        if marker:
            self.marker.write_text("BLOCKED for the test\n")

    def install(self, monkeypatch):
        rig = self

        def fake_run(cmd, *a, **k):
            cmd = list(cmd)
            # THE LAUNCH. start() now issues `systemctl start` through
            # subprocess.run and reads its result, so this is where process
            # creation is observed. Record it; answer as an accepted command.
            if cmd[:4] == list(SYSTEMCTL):
                rig.launches.append(cmd)
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
            if cmd[:2] == ["systemctl", "show"]:
                if rig.show_raises:
                    raise OSError("systemctl unavailable")
                if "DropInPaths" in " ".join(cmd):          # the preflight query
                    return subprocess.CompletedProcess(
                        cmd, rig.show_rc, stdout=str(rig.dropin), stderr="")
                # the post-start state query: report an active unit, so an
                # accepted launch is classified PROCESS_ACTIVE, not UNCONFIRMED
                return subprocess.CompletedProcess(
                    cmd, 0, stdout="ActiveState=active\nSubState=running\n"
                                   "ConditionResult=yes\nConditionTimestamp=\n"
                                   "Result=success\nExecMainStatus=0", stderr="")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        def no_popen(*a, **k):
            raise AssertionError("Popen must not be used for launches any more")
        monkeypatch.setattr(ORCH.subprocess, "run", fake_run)
        monkeypatch.setattr(ORCH.subprocess, "Popen", no_popen)
        return rig


def run_ticks(monkeypatch, tmp_path, specs, n, *, phase="RTH", state=None,
              start_t=T0, observed=False, work=False):
    clock = {"t": start_t}
    monkeypatch.setattr(ORCH, "time", _Clock(clock))
    monkeypatch.setattr(ORCH, "default_roster", lambda host: specs)
    monkeypatch.setattr(ORCH, "process_running", lambda name: observed)
    monkeypatch.setattr(ORCH, "first_work_seen", lambda name: work)
    monkeypatch.setattr(ORCH, "qualify_host", lambda **k: None)
    monkeypatch.setattr(ORCH, "phase_at", lambda t, s: {
        "phase": phase, "why": "fixed", "trading_day": True, "half_day": False})
    monkeypatch.setattr(ORCH, "now", lambda: clock["t"])
    monkeypatch.setattr(ORCH, "LEDGER", tmp_path / "led.jsonl")
    if state is None:
        state = {"attempts": {}, "host": "cloud", "phase": phase,
                 "phase_started": clock["t"].timestamp() - 7200}
    out = None
    for _ in range(n):
        out = ORCH.tick(state, dry_run=False)
        clock["t"] = clock["t"] + timedelta(seconds=60)
    return state, out


# ------------------------------------------------- 1. blocked never launches
def test_a_blocked_service_is_never_launched(monkeypatch, tmp_path):
    rig = Rig(tmp_path, marker=True).install(monkeypatch)
    state, out = run_ticks(monkeypatch, tmp_path, [spec()], 5)
    assert rig.launches == [], "a blocked service was launched"
    st = state["attempts"]["equity-fabric"]
    assert st["recovery"] == [], "a blocked service consumed a recovery attempt"
    assert st["maintenance"]["count"] == 5
    assert st["maintenance"]["state"] == ORCH.BLOCKED
    assert str(rig.marker) in st["maintenance"]["detail"]
    assert out["maintenance"]["equity-fabric"]["state"] == ORCH.BLOCKED


def test_no_false_started_is_recorded_for_a_blocked_service(monkeypatch, tmp_path):
    """The 2026-09-04 falsification: three refused starts recorded STARTED."""
    Rig(tmp_path, marker=True).install(monkeypatch)
    state, out = run_ticks(monkeypatch, tmp_path, [spec()], 3)
    assert out["actions"] == []
    rows = [json.loads(x) for x in (tmp_path / "led.jsonl").read_text().splitlines()
            if x.strip()]
    assert rows, "the tick must still be recorded"
    for r in rows:
        for a in r.get("actions", []):
            assert a.get("outcome") != "STARTED", "a refused start was logged as STARTED"


# ------------------------------------------------- 2. unblocked unchanged
def test_an_unblocked_eligible_service_still_launches(monkeypatch, tmp_path):
    rig = Rig(tmp_path, marker=False).install(monkeypatch)
    state, out = run_ticks(monkeypatch, tmp_path, [spec()], 1)
    assert rig.launches, "the unblocked service was not launched"
    assert out["actions"] and out["actions"][0]["outcome"] == ORCH.PROCESS_ACTIVE
    assert len(state["attempts"]["equity-fabric"]["recovery"]) == 1
    assert rig.launches[0][-1] == "apex-equity-fabric.service"
    assert rig.launches[0][:4] == list(SYSTEMCTL)


def test_a_unit_declaring_no_condition_is_not_blocked(monkeypatch, tmp_path):
    rig = Rig(tmp_path, declare=False).install(monkeypatch)
    run_ticks(monkeypatch, tmp_path, [spec()], 1)
    assert rig.launches


# --------------------------------- 3. a block applied after startup is honored
def test_a_block_applied_after_startup_is_honored_on_a_later_tick(
        monkeypatch, tmp_path):
    rig = Rig(tmp_path, marker=False).install(monkeypatch)
    run_ticks(monkeypatch, tmp_path, [spec()], 1)      # unblocked: it launches
    assert len(rig.launches) == 1
    rig.marker.write_text("blocked now\n")          # the block arrives
    state, out = run_ticks(monkeypatch, tmp_path, [spec()], 4)
    assert len(rig.launches) == 1, "it launched again after being blocked"
    assert state["attempts"]["equity-fabric"]["maintenance"]["count"] == 4


def test_a_block_applied_before_a_phase_transition_is_honored_after_it(
        monkeypatch, tmp_path):
    rig = Rig(tmp_path, marker=True).install(monkeypatch)
    state, _ = run_ticks(monkeypatch, tmp_path, [spec()], 2, phase="PREOPEN")
    assert rig.launches == []
    # a phase change clears per-service state; the block must still hold
    state, out = run_ticks(monkeypatch, tmp_path, [spec()], 2, phase="RTH",
                           state=state, start_t=T0 + timedelta(hours=1))
    assert rig.launches == [], "the phase transition bypassed the block"
    assert state["attempts"]["equity-fabric"]["maintenance"]["count"] == 2
    assert state["phase"] == "RTH"


# ------------------------------------------------- 4. bounded under repetition
@pytest.mark.parametrize("ticks", [1, 10, 500, 2000])
def test_repeated_blocked_ticks_stay_bounded(monkeypatch, tmp_path, ticks):
    Rig(tmp_path, marker=True).install(monkeypatch)
    state, out = run_ticks(monkeypatch, tmp_path, [spec()], ticks)
    st = state["attempts"]["equity-fabric"]
    assert st["maintenance"]["count"] == ticks
    assert len(st["maintenance"]["recent"]) <= ORCH.MAX_MAINTENANCE_DETAIL
    hist = ORCH._attempt_history(st, "equity-fabric")
    assert len(hist) <= (ORCH.MAX_RECOVERY_ATTEMPTS + 1 + ORCH.MAX_DEFERRAL_DETAIL
                         + 1 + ORCH.MAX_MAINTENANCE_DETAIL)
    assert len(json.dumps(out, sort_keys=True, default=str)) < 6000


def test_the_maintenance_disposition_is_not_a_recovery_attempt(monkeypatch, tmp_path):
    Rig(tmp_path, marker=True).install(monkeypatch)
    state, _ = run_ticks(monkeypatch, tmp_path, [spec()], 400)
    st = state["attempts"]["equity-fabric"]
    assert st["recovery"] == [], "the allowance was consumed by a block"
    hist = ORCH._attempt_history(st, "equity-fabric")
    entry = next(h for h in hist if h.get("kind") == "maintenance_disposition")
    assert entry["count"] == 400
    assert "NOT a recovery attempt" in entry["note"]
    assert entry["disposition"] == "MAINTENANCE_BLOCKED"


# ------------------------------------------------- 5. indeterminate fails closed
@pytest.mark.parametrize("rig_kw,why", [
    ({"show_rc": 1}, "systemctl returned nonzero"),
    ({"show_raises": True}, "systemctl could not be run"),
    ({"dropin_readable": False}, "the drop-in could not be read"),
])
def test_indeterminate_block_status_refuses_the_launch(monkeypatch, tmp_path,
                                                       rig_kw, why):
    if os.geteuid() == 0 and "dropin_readable" in rig_kw:
        pytest.skip("root ignores file permissions, so unreadability cannot "
                    "be simulated this way")
    rig = Rig(tmp_path, **rig_kw).install(monkeypatch)
    state, out = run_ticks(monkeypatch, tmp_path, [spec()], 3)
    assert rig.launches == [], "failed open: launched despite %s" % why
    st = state["attempts"]["equity-fabric"]
    assert st["maintenance"]["state"] == ORCH.INDETERMINATE
    assert st["recovery"] == []


def test_a_spec_without_a_systemd_unit_is_indeterminate(monkeypatch, tmp_path):
    rig = Rig(tmp_path).install(monkeypatch)
    s = ServiceSpec(name="odd", phases_running=("RTH",), always_on=True,
                    first_work_deadline_s=1800, start_cmd=("/bin/true",),
                    supervised_by="orchestrator")
    state, _ = run_ticks(monkeypatch, tmp_path, [s], 2)
    assert rig.launches == []
    assert state["attempts"]["odd"]["maintenance"]["state"] == ORCH.INDETERMINATE


# ------------------------------- 6. removing a block restores existing rules
def test_removing_a_block_restores_eligibility_under_the_existing_rules(
        monkeypatch, tmp_path):
    rig = Rig(tmp_path, marker=True).install(monkeypatch)
    state, _ = run_ticks(monkeypatch, tmp_path, [spec()], 3)
    assert rig.launches == []
    rig.marker.unlink()
    run_ticks(monkeypatch, tmp_path, [spec()], 1, state=state)
    assert len(rig.launches) == 1, "unblocking did not restore eligibility"


def test_removing_a_block_does_not_bypass_the_recovery_allowance(
        monkeypatch, tmp_path):
    """Unblocking restores the NORMAL rules -- it does not grant extra tries."""
    rig = Rig(tmp_path, marker=False).install(monkeypatch)
    state, _ = run_ticks(monkeypatch, tmp_path, [spec()], 20)
    assert len(rig.launches) == ORCH.MAX_RECOVERY_ATTEMPTS == 3


def test_a_service_out_of_phase_is_not_launched_blocked_or_not(monkeypatch, tmp_path):
    rig = Rig(tmp_path, marker=False).install(monkeypatch)
    s = ServiceSpec(name="options-paper", phases_running=("RTH",),
                    first_work_deadline_s=1800,
                    start_cmd=SYSTEMCTL + ("apex-options-paper.service",),
                    supervised_by="orchestrator")
    state, out = run_ticks(monkeypatch, tmp_path, [s], 3, phase="IDLE")
    assert rig.launches == [], "a service was launched outside its phase"
    assert "options-paper" not in state["attempts"]


# ------------------------------------------------- monitoring survives
def test_monitoring_and_heartbeat_work_continue_while_blocked(monkeypatch, tmp_path):
    Rig(tmp_path, marker=True).install(monkeypatch)
    state, out = run_ticks(monkeypatch, tmp_path, [spec()], 5)
    assert out["reconciliation"]["missing"] == ["equity-fabric"]
    assert out["reconciliation"]["verdict"] != "OK"
    assert out["observed"] == {"equity-fabric": False}
    assert out["decision_power"] == "NONE_OPERATIONAL"
    rows = [json.loads(x) for x in (tmp_path / "led.jsonl").read_text().splitlines()
            if x.strip()]
    assert len(rows) == 5, "ticks stopped being recorded while blocked"
    assert all(r["prev_hash"] == rows[i - 1]["entry_hash"]
               for i, r in enumerate(rows) if i)


def test_the_mapping_comes_from_systemd_not_from_the_filename(monkeypatch, tmp_path):
    """A marker whose name matches nothing still blocks, because the unit's
    own drop-in declares it. Guessing from names would miss this."""
    rig = Rig(tmp_path, marker=False)
    odd = tmp_path / "SOME_OTHER_NAME"
    rig.dropin.write_text("[Unit]\nConditionPathExists=!%s\n" % odd)
    odd.write_text("blocked\n")
    rig.install(monkeypatch)
    state, _ = run_ticks(monkeypatch, tmp_path, [spec()], 2)
    assert rig.launches == []
    assert str(odd) in state["attempts"]["equity-fabric"]["maintenance"]["detail"]
