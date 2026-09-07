"""Truthful launch reporting.

Spawning `systemctl start` proves that a command was launched. systemd SKIPS a
unit whose Condition*= fails, the start job succeeds, and systemctl exits 0 --
so exit status alone cannot distinguish a start from a refusal. On 2026-09-04
three refusals were recorded as STARTED. These tests pin the distinctions:
request, command result, systemd's answer, observed process state, and work.

Process creation is intercepted: subprocess.run is replaced for BOTH the start
command and the systemctl show query, and no service is ever started.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_spec = importlib.util.spec_from_file_location(
    "apex_orchestrator_launch", ROOT / "scripts" / "apex_orchestrator.py")
ORCH = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ORCH)
from apex.ops.orchestrator import ServiceSpec  # noqa: E402

T0 = datetime(2026, 9, 8, 14, 0, tzinfo=timezone.utc)
SYSTEMCTL = ("/usr/bin/sudo", "-n", "/usr/bin/systemctl", "start")
UNIT = "apex-equity-fabric.service"


def spec():
    return ServiceSpec(name="equity-fabric", phases_running=("RTH",), always_on=True,
                       first_work_deadline_s=1800, start_cmd=SYSTEMCTL + (UNIT,),
                       supervised_by="orchestrator")


class Systemd:
    """A scripted systemd: what `start` returns, and what `show` reports."""

    def __init__(self, *, start_rc=0, start_raises=None, show=None, show_fails=False):
        self.start_rc, self.start_raises = start_rc, start_raises
        self.show, self.show_fails = show or {}, show_fails
        self.starts, self.shows = [], []

    def install(self, monkeypatch):
        sd = self

        def fake_run(cmd, *a, **k):
            if list(cmd[:4]) == list(SYSTEMCTL):
                sd.starts.append(list(cmd))
                if sd.start_raises:
                    raise sd.start_raises
                return subprocess.CompletedProcess(cmd, sd.start_rc, stdout="",
                                                   stderr="unit failed" if sd.start_rc else "")
            if cmd[:2] == ["systemctl", "show"]:
                sd.shows.append(list(cmd))
                if "DropInPaths" in " ".join(cmd):
                    return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
                if sd.show_fails:
                    return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="no such unit")
                return subprocess.CompletedProcess(
                    cmd, 0, stdout="\n".join("%s=%s" % kv for kv in sd.show.items()), stderr="")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        monkeypatch.setattr(ORCH.subprocess, "run", fake_run)
        monkeypatch.setattr(ORCH.subprocess, "Popen",
                            lambda *a, **k: (_ for _ in ()).throw(AssertionError("Popen used")))
        return sd


def one_tick(monkeypatch, tmp_path, *, preflight=ORCH.NOT_BLOCKED):
    clock = {"t": T0}
    monkeypatch.setattr(ORCH, "time", type("C", (), {
        "time": lambda self: clock["t"].timestamp(),
        "sleep": lambda self, s: (_ for _ in ()).throw(AssertionError("sleep"))})())
    monkeypatch.setattr(ORCH, "default_roster", lambda host: [spec()])
    monkeypatch.setattr(ORCH, "process_running", lambda name: False)
    monkeypatch.setattr(ORCH, "first_work_seen", lambda name: False)
    monkeypatch.setattr(ORCH, "qualify_host", lambda **k: None)
    monkeypatch.setattr(ORCH, "phase_at", lambda t, s: {
        "phase": "RTH", "why": "fixed", "trading_day": True, "half_day": False})
    monkeypatch.setattr(ORCH, "now", lambda: clock["t"])
    monkeypatch.setattr(ORCH, "LEDGER", tmp_path / "led.jsonl")
    monkeypatch.setattr(ORCH, "maintenance_status", lambda s: (preflight, "scripted"))
    state = {"attempts": {}, "host": "cloud", "phase": "RTH",
             "phase_started": T0.timestamp() - 7200}
    out = ORCH.tick(state, dry_run=False)
    return state, out


ACTIVE = {"ActiveState": "active", "SubState": "running", "ConditionResult": "yes",
          "ConditionTimestamp": "", "Result": "success", "ExecMainStatus": "0"}
REFUSED = {"ActiveState": "inactive", "SubState": "dead", "ConditionResult": "no",
           "ConditionTimestamp": "", "Result": "success", "ExecMainStatus": "0"}
LIMBO = {"ActiveState": "inactive", "SubState": "dead", "ConditionResult": "yes",
         "ConditionTimestamp": "", "Result": "success", "ExecMainStatus": "0"}


def test_started_is_no_longer_a_possible_outcome():
    src = (ROOT / "scripts" / "apex_orchestrator.py").read_text()
    assert 'outcome="STARTED"' not in src
    assert "START_REQUESTED" in src and "CONDITION_REFUSED" in src


def test_spawning_the_command_never_establishes_a_start(monkeypatch, tmp_path):
    """rc=0 with the unit still inactive is UNCONFIRMED, never STARTED."""
    sd = Systemd(start_rc=0, show=LIMBO).install(monkeypatch)
    state, out = one_tick(monkeypatch, tmp_path)
    assert sd.starts, "the command was not issued"
    a = out["actions"][0]
    assert a["outcome"] == ORCH.START_UNCONFIRMED
    assert a["outcome"] != "STARTED"
    assert "ActiveState=inactive" in a["detail"]
    assert len(state["attempts"]["equity-fabric"]["recovery"]) == 1


def test_a_condition_refusal_after_preflight_is_reported_and_costs_no_attempt(
        monkeypatch, tmp_path):
    """The 2026-09-04 case, and the race a preflight cannot close: preflight
    said NOT_BLOCKED, the block arrived, systemd skipped the unit, rc=0."""
    sd = Systemd(start_rc=0, show=REFUSED).install(monkeypatch)
    state, out = one_tick(monkeypatch, tmp_path, preflight=ORCH.NOT_BLOCKED)
    assert sd.starts
    a = out["actions"][0]
    assert a["outcome"] == ORCH.CONDITION_REFUSED
    assert "Condition" in a["detail"]
    st = state["attempts"]["equity-fabric"]
    assert st["recovery"] == [], "a refused start spent a recovery attempt"
    assert st["maintenance"]["count"] == 1
    assert st["maintenance"]["state"] == ORCH.BLOCKED


def test_process_active_is_reported_as_active_not_as_work(monkeypatch, tmp_path):
    sd = Systemd(start_rc=0, show=ACTIVE).install(monkeypatch)
    state, out = one_tick(monkeypatch, tmp_path)
    a = out["actions"][0]
    assert a["outcome"] == ORCH.PROCESS_ACTIVE
    # first_work_seen is False, so the verdict must NOT be WORK_CONFIRMED
    assert all(i["verdict"] != "WORK_CONFIRMED" for i in out["incidents"])
    assert len(state["attempts"]["equity-fabric"]["recovery"]) == 1


def test_work_is_confirmed_only_by_the_work_artifact(monkeypatch, tmp_path):
    """A running process plus the existing first-work evidence -> the service
    is skipped entirely and no incident is raised. Work, not liveness."""
    Systemd(start_rc=0, show=ACTIVE).install(monkeypatch)
    clock = {"t": T0}
    monkeypatch.setattr(ORCH, "time", type("C", (), {
        "time": lambda self: clock["t"].timestamp(), "sleep": lambda self, s: None})())
    monkeypatch.setattr(ORCH, "default_roster", lambda host: [spec()])
    monkeypatch.setattr(ORCH, "process_running", lambda name: True)
    monkeypatch.setattr(ORCH, "first_work_seen", lambda name: True)
    monkeypatch.setattr(ORCH, "qualify_host", lambda **k: None)
    monkeypatch.setattr(ORCH, "phase_at", lambda t, s: {
        "phase": "RTH", "why": "fixed", "trading_day": True, "half_day": False})
    monkeypatch.setattr(ORCH, "now", lambda: clock["t"])
    monkeypatch.setattr(ORCH, "LEDGER", tmp_path / "led.jsonl")
    state = {"attempts": {}, "host": "cloud", "phase": "RTH",
             "phase_started": T0.timestamp() - 7200}
    out = ORCH.tick(state, dry_run=False)
    assert out["actions"] == [] and out["incidents"] == []


def test_nonzero_exit_is_command_failed_and_spends_an_attempt(monkeypatch, tmp_path):
    sd = Systemd(start_rc=1).install(monkeypatch)
    state, out = one_tick(monkeypatch, tmp_path)
    a = out["actions"][0]
    assert a["outcome"] == ORCH.START_COMMAND_FAILED
    assert "rc=1" in a["detail"] and "unit failed" in a["detail"]
    assert len(state["attempts"]["equity-fabric"]["recovery"]) == 1
    assert not sd.shows or all("DropInPaths" in " ".join(c) for c in sd.shows), \
        "state was queried after a failed command"


def test_timeout_is_command_failed(monkeypatch, tmp_path):
    Systemd(start_raises=subprocess.TimeoutExpired(cmd="x", timeout=30)).install(monkeypatch)
    state, out = one_tick(monkeypatch, tmp_path)
    a = out["actions"][0]
    assert a["outcome"] == ORCH.START_COMMAND_FAILED
    assert "did not return within" in a["detail"]


def test_spawn_error_is_command_failed(monkeypatch, tmp_path):
    Systemd(start_raises=OSError("sudo missing")).install(monkeypatch)
    state, out = one_tick(monkeypatch, tmp_path)
    assert out["actions"][0]["outcome"] == ORCH.START_COMMAND_FAILED


def test_unreadable_unit_state_is_unconfirmed_not_started(monkeypatch, tmp_path):
    Systemd(start_rc=0, show_fails=True).install(monkeypatch)
    state, out = one_tick(monkeypatch, tmp_path)
    a = out["actions"][0]
    assert a["outcome"] == ORCH.START_UNCONFIRMED
    assert "could not be read" in a["detail"]


def test_the_command_is_bounded_and_its_output_is_read(monkeypatch, tmp_path):
    seen = {}

    def fake_run(cmd, *a, **k):
        if list(cmd[:4]) == list(SYSTEMCTL):
            seen.update(k)
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        if cmd[:2] == ["systemctl", "show"]:
            body = "" if "DropInPaths" in " ".join(cmd) else \
                "\n".join("%s=%s" % kv for kv in LIMBO.items())
            return subprocess.CompletedProcess(cmd, 0, stdout=body, stderr="")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
    monkeypatch.setattr(ORCH.subprocess, "run", fake_run)
    one_tick(monkeypatch, tmp_path)
    assert seen.get("timeout") == ORCH.START_TIMEOUT_S
    assert seen.get("capture_output") is True


def test_every_outcome_name_is_distinct_and_schema_compatible():
    names = {ORCH.START_REQUESTED, ORCH.START_COMMAND_FAILED, ORCH.CONDITION_REFUSED,
             ORCH.PROCESS_ACTIVE, ORCH.START_UNCONFIRMED, ORCH.BLOCKED,
             ORCH.INDETERMINATE, ORCH.NOT_BLOCKED}
    assert len(names) == 8
    assert "STARTED" not in names
    # the alarm still carries evidence for an unconfirmed start
    a = ORCH.StartAttempt(service="x", attempted_utc="t",
                          outcome=ORCH.START_UNCONFIRMED, detail="d")
    assert set(a.__dict__) == {"service", "attempted_utc", "outcome", "detail"}
