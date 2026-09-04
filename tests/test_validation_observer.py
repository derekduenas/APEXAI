"""EQUITY_FABRIC_VALIDATION_PROFILE_V1 -- identity before attribution.

On 2026-09-04 this observer was pointed at an INACTIVE validation unit
and reported raw=3466 dedup=3466 bars=446 sem=EXACT. Those were the
final numbers of a process that had been dead for 33 minutes: the
health artifact is a FILE, and it outlives the process that wrote it.

In a Gate-2 validation that is the worst failure available -- the
candidate could die mid-session and the evidence would keep showing
healthy bounded state from a corpse. These tests make that impossible.
"""
import importlib.util
import json
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "efvp", Path(__file__).resolve().parents[1] / "scripts"
    / "ef_validation_profile.py")
efvp = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(efvp)


def _write(tmp, pid, start="2026-09-04T13:15:00+00:00"):
    h = tmp / "health.json"
    b = tmp / "beat.json"
    h.write_text(json.dumps({
        "status": "HEALTHY", "process_start_utc": start,
        "working_state": {"state_model": "TRADE_WORKING_SET_V1",
                          "raw_trades_retained": 3466,
                          "dedup_keys_retained": 3466,
                          "bars_retained": 446, "counters": {}},
        "ordering_semantics": {"semantic_health": "EXACT"},
        "health_axes": {"state_bound_ok": True},
    }))
    b.write_text(json.dumps({"pid": pid}))
    return h, b


def test_no_live_process_is_never_attributed(tmp_path, monkeypatch):
    h, b = _write(tmp_path, 4242)
    monkeypatch.setattr(efvp, "HEALTH", h)
    monkeypatch.setattr(efvp, "HEARTBEAT", b)
    r = efvp.health_state(pid=0, unit="x.service")
    assert r["available"] is False
    assert r["identity"] == "NO_LIVE_PROCESS"
    assert r["attributed"] is False
    assert r.get("raw_trades_retained") is None, (
        "a dead process's numbers were attributed to a live candidate")


def test_artifact_from_a_different_pid_is_STALE(tmp_path, monkeypatch):
    """The exact 2026-09-04 defect: artifact written by pid 1048478
    while the unit's live process is a different pid."""
    h, b = _write(tmp_path, 1048478)
    monkeypatch.setattr(efvp, "HEALTH", h)
    monkeypatch.setattr(efvp, "HEARTBEAT", b)
    monkeypatch.setattr(efvp, "sh", lambda c: "")
    r = efvp.health_state(pid=999999, unit="x.service")
    assert r["available"] is False
    assert r["identity"] == "STALE_ARTIFACT"
    assert r["attributed"] is False
    assert r["artifact_pid"] == 1048478 and r["live_pid"] == 999999
    assert r.get("bars_retained") is None


def test_matching_pid_IS_attributed(tmp_path, monkeypatch):
    h, b = _write(tmp_path, 777)
    monkeypatch.setattr(efvp, "HEALTH", h)
    monkeypatch.setattr(efvp, "HEARTBEAT", b)
    monkeypatch.setattr(efvp, "sh", lambda c: "")   # no unit start info
    r = efvp.health_state(pid=777, unit="x.service")
    assert r["available"] is True
    assert r["identity"] == "CURRENT_INSTANCE"
    assert r["attributed"] is True
    assert r["raw_trades_retained"] == 3466
    assert r["bars_retained"] == 446
    assert r["semantic_health"] == "EXACT"


def test_unreadable_artifact_is_not_attributed(tmp_path, monkeypatch):
    monkeypatch.setattr(efvp, "HEALTH", tmp_path / "missing.json")
    monkeypatch.setattr(efvp, "HEARTBEAT", tmp_path / "missing2.json")
    r = efvp.health_state(pid=5, unit="x.service")
    assert r["available"] is False
    assert r["identity"] == "ARTIFACT_UNREADABLE"
    assert r["attributed"] is False


def test_observer_is_read_only_toward_the_fabric():
    """It may never write into the candidate's canonical outputs."""
    src = (Path(__file__).resolve().parents[1] / "scripts"
           / "ef_validation_profile.py").read_text()
    for bad in ("write_text", "systemctl start", "systemctl stop",
                "systemctl restart", "rmtree", "unlink"):
        assert bad not in src, "observer performs a mutating action: %s" % bad
    # its ONLY write is its own append-only ledger
    assert src.count("LEDGER.open(\"a\")") == 1
