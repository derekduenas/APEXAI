"""Operational hardening: the defect class from the Phase A incident.

Each test corresponds to a way the system silently lied about its own
state on 2026-08-23.
"""
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timedelta, timezone

import pytest

from apex.ops import heartbeat as hb
from apex.ops import release as rel

NOW = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)


def _beat(tmp_path, service="svc", **kw):
    h = hb.Heartbeat(service=service, **kw)
    h.beat(tmp_path)
    return h


# ------------------------------------------------- presence != health

def test_a_dead_process_is_detected_not_assumed_fine(tmp_path):
    """Seven hours of undetected death is what this closes."""
    h = _beat(tmp_path, pid=999999)          # a pid that cannot exist
    r = hb.health("svc", beat_stale_s=60, root=tmp_path)
    assert r["state"] == "DEAD"
    assert "is gone" in r["why"]


def test_alive_but_making_no_progress_reads_as_stalled(tmp_path):
    """The failure mode a pid check cannot see."""
    h = hb.Heartbeat(service="svc")
    h.work("item-1", root=tmp_path)
    old = (NOW - timedelta(hours=3)).isoformat()
    data = json.loads((tmp_path / "svc.json").read_text())
    data["last_work_utc"] = old
    data["beat_utc"] = NOW.isoformat()
    (tmp_path / "svc.json").write_text(json.dumps(data))
    r = hb.health("svc", beat_stale_s=600, work_stale_s=1800,
                  root=tmp_path, now=NOW)
    assert r["state"] == "STALLED"
    assert "presence is not progress" in r["why"]


def test_beating_with_no_work_ever_is_stalled_not_healthy(tmp_path):
    """Past the startup grace, a daemon that has never completed a unit
    of work is stuck -- looping on a failing call looks identical to
    working from the outside."""
    h = hb.Heartbeat(service="svc")
    h.beat(tmp_path)
    data = json.loads((tmp_path / "svc.json").read_text())
    data["started_utc"] = (NOW - timedelta(hours=2)).isoformat()
    data["beat_utc"] = NOW.isoformat()
    (tmp_path / "svc.json").write_text(json.dumps(data))
    r = hb.health("svc", beat_stale_s=600, work_stale_s=600,
                  root=tmp_path, now=NOW)
    assert r["state"] == "STALLED"
    assert "EVER" in r["why"]


def test_a_silent_process_reads_as_stale(tmp_path):
    h = hb.Heartbeat(service="svc")
    h.work("x", root=tmp_path)
    data = json.loads((tmp_path / "svc.json").read_text())
    data["beat_utc"] = (NOW - timedelta(hours=7)).isoformat()
    (tmp_path / "svc.json").write_text(json.dumps(data))
    r = hb.health("svc", beat_stale_s=300, root=tmp_path, now=NOW)
    assert r["state"] == "STALE"


def test_a_service_that_never_ran_is_not_silently_absent(tmp_path):
    r = hb.health("nobody", beat_stale_s=60, root=tmp_path)
    assert r["state"] == "NEVER_STARTED"


def test_running_the_wrong_release_is_caught(tmp_path):
    hb.Heartbeat(service="svc", release_commit="a" * 40).work(
        "x", root=tmp_path)
    r = hb.health("svc", beat_stale_s=600, root=tmp_path,
                  expected_commit="b" * 40)
    assert r["state"] == "WRONG_RELEASE"


def test_a_healthy_service_reports_healthy(tmp_path):
    hb.Heartbeat(service="svc").work("x", root=tmp_path)
    r = hb.health("svc", beat_stale_s=600, work_stale_s=600,
                  root=tmp_path)
    assert r["state"] == "HEALTHY"


def test_heartbeat_writes_are_atomic(tmp_path):
    """A reader must never see a half-written heartbeat."""
    h = hb.Heartbeat(service="svc")
    for i in range(25):
        h.work(f"item-{i}", root=tmp_path)
        json.loads((tmp_path / "svc.json").read_text())   # never torn
    assert not list(tmp_path.glob("*.tmp"))


def test_summary_names_what_needs_attention(tmp_path):
    hb.Heartbeat(service="ok").work("x", root=tmp_path)
    hb.Heartbeat(service="gone", pid=999999).beat(tmp_path)
    reports = [hb.health(s, beat_stale_s=600, root=tmp_path)
               for s in ("ok", "gone")]
    s = hb.summarize(reports)
    assert s["verdict"] == "ATTENTION_REQUIRED"
    assert s["unhealthy"] == 1
    assert s["attention"][0]["service"] == "gone"
    assert "existence is not health" in s["law"]


def test_every_state_emitted_is_declared(tmp_path):
    hb.Heartbeat(service="svc", pid=999999).beat(tmp_path)
    assert hb.health("svc", beat_stale_s=60,
                     root=tmp_path)["state"] in hb.HEALTH_STATES


# ------------------------------------------------- release pedigree

def _repo(tmp_path, name="repo"):
    r = tmp_path / name
    r.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=r, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=r)
    subprocess.run(["git", "config", "user.name", "t"], cwd=r)
    (r / "f.py").write_text("x = 1\n")
    subprocess.run(["git", "add", "-A"], cwd=r, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=r, check=True)
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=r,
                         capture_output=True, text=True).stdout.strip()
    return r, sha


def _release(tmp_path, sha, writable=False):
    d = tmp_path / "releases" / sha
    d.mkdir(parents=True)
    (d / "f.py").write_text("x = 1\n")
    (d / rel.RELEASE_STAMP).write_text(json.dumps({"commit": sha}))
    if not writable:
        os.chmod(d, 0o555)
    return d


def test_cloud_only_code_is_the_named_alarm(tmp_path):
    """THE incident: a release whose commit exists on no canonical
    repository."""
    repo, _sha = _repo(tmp_path)
    d = _release(tmp_path, "f" * 40)
    try:
        r = rel.verify_running_release(release_dir=d, canonical_repo=repo)
        assert r["verdict"] == "RUNNING_RELEASE_NOT_IN_CANONICAL_HISTORY"
        assert "not a backup" in " ".join(r["findings"])
    finally:
        os.chmod(d, 0o755)


def test_a_release_in_canonical_history_is_healthy(tmp_path):
    repo, sha = _repo(tmp_path)
    d = _release(tmp_path, sha)
    try:
        r = rel.verify_running_release(release_dir=d, canonical_repo=repo)
        assert r["verdict"] == "RELEASE_HEALTHY"
        assert not r["findings"]
    finally:
        os.chmod(d, 0o755)


def test_a_writable_release_is_flagged_mutable(tmp_path):
    repo, sha = _repo(tmp_path)
    d = _release(tmp_path, sha, writable=True)
    r = rel.verify_running_release(release_dir=d, canonical_repo=repo)
    assert r["verdict"] == "RELEASE_MUTABLE"
    assert "WRITABLE" in " ".join(r["findings"])


def test_running_from_the_repo_itself_is_refused(tmp_path):
    """Exactly what /opt/apex was doing when the daemon died."""
    repo, sha = _repo(tmp_path)
    (repo / rel.RELEASE_STAMP).write_text(json.dumps({"commit": sha}))
    r = rel.verify_running_release(release_dir=repo, canonical_repo=repo)
    assert r["verdict"] == "RELEASE_MUTABLE"


def test_an_unstamped_release_cannot_be_attributed(tmp_path):
    d = tmp_path / "releases" / "x"
    d.mkdir(parents=True)
    r = rel.verify_running_release(release_dir=d,
                                   canonical_repo=tmp_path / "nope")
    assert r["verdict"] == "RELEASE_UNSTAMPED"


def test_pedigree_names_the_secret_backend(tmp_path, monkeypatch):
    """The Phase A death was a secret-backend mismatch; naming it in the
    pedigree makes that visible before startup."""
    sd = tmp_path / "secrets"
    sd.mkdir()
    (sd / "TOKEN").write_text("v")
    monkeypatch.setenv("APEX_SECRETS_DIR", str(sd))
    p = rel.build_pedigree(service="s", release_dir=tmp_path)
    assert p["secret_backend"].startswith("FILES:")


def test_pedigree_reports_no_backend_when_there_is_none(
        tmp_path, monkeypatch):
    monkeypatch.setenv("APEX_SECRETS_DIR", str(tmp_path / "empty"))
    p = rel.build_pedigree(service="s", release_dir=tmp_path)
    assert p["secret_backend"] in ("NONE_AVAILABLE", "MACOS_KEYCHAIN")


def test_pedigree_carries_what_is_needed_to_identify_the_code(tmp_path):
    p = rel.build_pedigree(service="s", release_dir=tmp_path,
                           code_paths=["f.py"], config={"a": 1},
                           authority="PAPER_EXPLORATORY")
    for k in ("service", "release_path", "module_digest",
              "config_digest", "secret_backend", "host", "started_utc",
              "authority"):
        assert k in p
    assert p["authority"] == "PAPER_EXPLORATORY"


def test_no_current_release_refuses_rather_than_defaulting(tmp_path,
                                                           monkeypatch):
    monkeypatch.setattr(rel, "CURRENT", tmp_path / "absent")
    r = rel.verify_running_release()
    assert r["verdict"] == "NO_CURRENT_RELEASE"


def test_a_freshly_restarted_daemon_is_starting_not_stalled(tmp_path):
    """Every restart would otherwise fire an alert, and an alarm that
    cries wolf is the failure mode we are trying to avoid."""
    hb.Heartbeat(service="svc").beat(tmp_path)
    r = hb.health("svc", beat_stale_s=600, work_stale_s=3600,
                  root=tmp_path)
    assert r["state"] == "STARTING"
    assert "startup grace" in r["why"]
    assert hb.summarize([r])["verdict"] == "ALL_HEALTHY"


def test_the_grace_expires_and_a_stuck_daemon_is_caught(tmp_path):
    h = hb.Heartbeat(service="svc")
    h.beat(tmp_path)
    data = json.loads((tmp_path / "svc.json").read_text())
    data["started_utc"] = (NOW - timedelta(hours=4)).isoformat()
    data["beat_utc"] = NOW.isoformat()
    (tmp_path / "svc.json").write_text(json.dumps(data))
    r = hb.health("svc", beat_stale_s=600, work_stale_s=3600,
                  root=tmp_path, now=NOW)
    assert r["state"] == "STALLED", (
        "a daemon that never completed work in four hours is stuck, "
        "grace or not")


def test_a_daemon_that_has_worked_before_gets_no_grace(tmp_path):
    """Grace covers startup, never an established daemon going quiet."""
    h = hb.Heartbeat(service="svc")
    h.work("one", root=tmp_path)
    data = json.loads((tmp_path / "svc.json").read_text())
    data["last_work_utc"] = (NOW - timedelta(hours=2)).isoformat()
    data["started_utc"] = (NOW - timedelta(minutes=1)).isoformat()
    data["beat_utc"] = NOW.isoformat()
    (tmp_path / "svc.json").write_text(json.dumps(data))
    r = hb.health("svc", beat_stale_s=600, work_stale_s=1800,
                  root=tmp_path, now=NOW)
    assert r["state"] == "STALLED"


def test_a_restart_loop_is_visible_even_when_heartbeats_look_fine(
        tmp_path):
    """The 2026-08-24 OOM loop: 69 restarts while health read HEALTHY,
    because each short life completed a little work."""
    hb.Heartbeat(service="svc").work("x", root=tmp_path)
    ok = hb.health("svc", beat_stale_s=600, work_stale_s=600,
                   root=tmp_path, restarts_since_last_check=0)
    assert ok["state"] == "HEALTHY"
    looping = hb.health("svc", beat_stale_s=600, work_stale_s=600,
                        root=tmp_path, restarts_since_last_check=12)
    assert looping["state"] == "RESTART_LOOPING"
    assert "heartbeats alone cannot see" in looping["why"]
    assert hb.summarize([looping])["verdict"] == "ATTENTION_REQUIRED"


def test_expecting_nothing_differs_from_declaring_nothing(monkeypatch,
                                                          tmp_path):
    """A host between sessions expects no services and is healthy. An
    UNSET declaration falls back to the roster. Conflating the two made
    a quiet host report its finished session as DEAD."""
    import os
    import subprocess
    import sys
    from pathlib import Path
    repo = Path(__file__).resolve().parents[1]
    env = {**os.environ, "APEX_HEARTBEAT_DIR": str(tmp_path),
           "APEX_RELEASE_ROOT": str(tmp_path / "nope")}
    env["APEX_EXPECTED_SERVICES"] = ""
    r = subprocess.run([sys.executable, "scripts/apex_health.py",
                        "--json"], capture_output=True, text=True,
                       env=env, cwd=str(repo))
    assert '"services": 0' in r.stdout or '"healthy": 0' in r.stdout
    assert "quiet host is not an unhealthy one" in r.stdout
