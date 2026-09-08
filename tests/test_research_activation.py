"""RESEARCH_ACTIVATION_V1 -- behaviour, not descriptions.

Every test drives the wrapper with disposable fixtures and a controlled
subprocess stand-in, and asserts what actually happened: which commands ran,
in what order, what exists on disk afterwards, and what the record says. The
V0 defect these replace was precisely a wrapper that described its actions
and recorded them as done.

No account is created, no privileged command runs, no real corpus file is
read, and no market row is parsed.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("research_activation",
                                               REPO / "scripts/research_activation.py")
RA = importlib.util.module_from_spec(_spec)
sys.modules["research_activation"] = RA
_spec.loader.exec_module(RA)
Refused = RA.ActivationRefused

PY_STUB = '#!/bin/sh\necho \'{"numpy": "2.4.6"}\'\n'


class StandIn(RA.SystemRunner):
    """Records every command in order. Filesystem operations are REAL; the
    commands that need root or a package index are emulated just enough for
    verification to have something true to check."""
    name = "stand-in"

    def __init__(self, targets, *, fail_on=None, account=True):
        self.t, self.calls, self.fail_on, self.account = targets, [], fail_on, account

    def cmd(self, argv, *, timeout=1800, input_text=None):
        argv = [str(x) for x in argv]
        self.calls.append(argv)
        joined = " ".join(argv)
        if self.fail_on and self.fail_on in joined:
            raise Refused("COMMAND_FAILED: %s exited 1: stand-in forced failure" % argv[0])
        if argv[0] == "adduser":
            if self.account:
                RA.account_facts = lambda u, _t=self.t: (
                    {"name": u, "present": True, "uid": os.getuid(), "gid": os.getgid(),
                     "shell": "/usr/sbin/nologin", "home": "/home/%s" % u,
                     "groups": [u], "privileged_groups": []} if u == _t.research_user
                    else {"name": u, "present": False})
            return subprocess.CompletedProcess(argv, 0, "", "")
        if "-m" in argv and "venv" in argv:                     # python -m venv
            # real `python -m venv` repairs an existing directory; the
            # stand-in must too, or it cannot model a resumed run
            venv = Path(argv[-1]); (venv / "bin").mkdir(parents=True, exist_ok=True)
            p = venv / "bin" / "python"; p.write_text(PY_STUB); os.chmod(p, 0o755)
            pip = venv / "bin" / "pip"; pip.write_text("#!/bin/sh\necho numpy==2.4.6\n"); os.chmod(pip, 0o755)
            return subprocess.CompletedProcess(argv, 0, "", "")
        if argv[0].endswith("/pip") and "freeze" in argv:
            return subprocess.CompletedProcess(argv, 0, "numpy==2.4.6\n", "")
        if argv[0].endswith("/pip"):
            return subprocess.CompletedProcess(argv, 0, "installed", "")
        if argv[0] in ("chown", "passwd", "deluser"):
            return subprocess.CompletedProcess(argv, 0, "", "")
        if argv[0] == "chmod":
            for root, dirs, fs in os.walk(argv[-1]):
                for n in dirs + fs:
                    p = Path(root) / n
                    os.chmod(p, stat.S_IMODE(os.stat(p).st_mode) & ~(stat.S_IWGRP | stat.S_IWOTH))
            os.chmod(argv[-1], stat.S_IMODE(os.stat(argv[-1]).st_mode) & ~(stat.S_IWGRP | stat.S_IWOTH))
            return subprocess.CompletedProcess(argv, 0, "", "")
        return super().cmd(argv, timeout=timeout, input_text=input_text)   # git etc: run for real


def _git(repo, *args):
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


@pytest.fixture(autouse=True)
def _restore_account_facts():
    original = RA.account_facts
    yield
    RA.account_facts = original


@pytest.fixture
def rig(tmp_path):
    corpus = tmp_path / "corpus" / "bars"; corpus.mkdir(parents=True)
    files, days = {}, [f"2019-06-{d:02d}" for d in range(3, 8)]
    for d in days:
        p = corpus / f"SPY_{d}.json"
        p.write_text(json.dumps({"bars": [{"t": d}]}))
        files[p.name] = {"sha256": RA.sha256_of(p), "size": p.stat().st_size,
                         "symbol": "SPY", "session_date": d}
    for name, sym, day in (("SPY_2023-06-01.json", "SPY", "2023-06-01"),
                           ("QQQ_2019-06-03.json", "QQQ", "2019-06-03")):
        p = corpus / name; p.write_text(json.dumps({"bars": [{"t": day}]}))
        files[name] = {"sha256": RA.sha256_of(p), "size": p.stat().st_size,
                       "symbol": sym, "session_date": day}
    man = tmp_path / "manifest.json"
    man.write_text(json.dumps({"dataset_id": "f", "root": str(corpus), "files": files}))
    src = tmp_path / "srcrepo"; (src / "apex" / "world_model").mkdir(parents=True)
    (src / "apex" / "world_model" / "x.py").write_text("X = 1\n")
    (src / "scripts").mkdir(); (src / "scripts" / "alpha_exp_real_execute.py").write_text("#\n")
    _git(src, "init", "-q"); _git(src, "config", "user.email", "t@t"); _git(src, "config", "user.name", "t")
    _git(src, "add", "-A"); _git(src, "commit", "-q", "-m", "b")
    trust = tmp_path / "trust"; (trust / "trust").mkdir(parents=True)
    t = RA.Targets(research_user="nonexistent_research_user",
                   runner_owner_uid=os.getuid(),   # harness is unprivileged; production is root
                   uid_separation_exercisable=False,  # stand-in chown is a no-op; see host proof
                   runner_root=tmp_path / "runner",
                   research_root=tmp_path / "research", source_repo=src, corpus_root=corpus,
                   manifest_path=man, trust_root=trust,
                   allowed_signers=trust / "trust" / "allowed_signers",
                   system_python=sys.executable, expected_view_files=len(days))
    return {"t": t, "tmp": tmp_path, "corpus": corpus, "manifest": man,
            "commit": _git(src, "rev-parse", "HEAD"), "days": days, "trust": trust}


# ======================= the V0 defects, now absent =======================
def test_dry_run_creates_nothing_and_records_nothing_as_created(rig):
    t = rig["t"]
    rec = RA.run_setup(t, rig["commit"], apply=False)
    assert rec["state"] == "DRY_RUN" and rec["created"] == []
    assert len(rec["planned_stages"]) == 12
    for p in (t.runner_root, t.research_root, t.checkout, t.view):
        assert not p.exists()


def test_setup_actually_creates_what_it_records(rig):
    """The V0 defect: 12 objects recorded, venv and checkout absent."""
    t = rig["t"]
    run = StandIn(t)
    rec = RA.run_setup(t, rig["commit"], apply=True, run=run)
    assert rec["state"] == "COMPLETE"
    for p in (t.research_root, t.out, t.runner_root, t.venv, t.python, t.requirements,
              t.pinned, t.checkout, t.view, t.view_bars, t.setup_manifest, t.log):
        assert p.exists(), p
    recorded = {o["object"] for o in rec["created"]}
    for o in rec["created"]:
        if o["kind"] != "account" and "[packages]" not in o["object"]:
            assert Path(o["object"]).exists(), o          # every recorded object EXISTS
    assert str(t.venv) in recorded and str(t.checkout) in recorded
    assert len(rec["created"]) == 12 and all(s["status"] == "VERIFIED" for s in rec["stages"])
    assert len(list(t.view_bars.iterdir())) == len(rig["days"])


def test_commands_actually_run_in_the_declared_order(rig):
    t = rig["t"]
    run = StandIn(t)
    RA.run_setup(t, rig["commit"], apply=True, run=run)
    seq = [c[0].split("/")[-1] + (":" + c[1] if len(c) > 1 and c[1].startswith("-") else "")
           for c in run.calls]
    assert "adduser" in [c[0] for c in run.calls]
    order = [i for i, c in enumerate(run.calls)]
    idx = {}
    for i, c in enumerate(run.calls):
        key = ("adduser" if c[0] == "adduser" else
               "venv" if "venv" in c else
               "pip_install" if c[0].endswith("/pip") and "install" in c else
               "pip_freeze" if c[0].endswith("/pip") and "freeze" in c else
               "git_clone" if c[:2] == ["git", "-C"] and "clone" in c or (c[0] == "git" and "clone" in c) else None)
        if key and key not in idx:
            idx[key] = i
    assert idx["adduser"] < idx["venv"] < idx["pip_install"] < idx["pip_freeze"] < idx["git_clone"], idx


def test_a_failed_stage_stops_and_records_partial_progress(rig):
    t = rig["t"]
    run = StandIn(t, fail_on="-m venv")
    with pytest.raises(Refused, match="^SETUP_FAILED_AT venv"):
        RA.run_setup(t, rig["commit"], apply=True, run=run)
    rec = json.loads(t.setup_manifest.read_text())
    assert rec["state"] == "PARTIAL_FAILED" and rec["failed_at"] == "venv"
    done = [o["stage"] for o in rec["created"]]
    assert done == ["research_root", "out", "account", "own_research_paths", "runner_root"]
    assert not t.venv.exists() and not t.checkout.exists() and not t.view.exists()
    assert t.log.exists() and len(t.log.read_text().splitlines()) >= len(done)
    # and nothing continues to launch
    d = rig["trust"] / "d.json"; d.write_text("{}"); d.with_suffix(".json.sig").write_text("s")
    with pytest.raises(Refused, match="^SETUP_NOT_COMPLETE"):
        RA.prepare_launch(t, rig["commit"], d)


def test_a_stage_that_does_not_create_its_object_is_not_recorded(rig):
    """Verification is what makes a record true: a stage whose command
    'succeeds' without producing anything must still fail."""
    t = rig["t"]

    class Liar(StandIn):
        def cmd(self, argv, *, timeout=1800, input_text=None):
            argv = [str(x) for x in argv]
            self.calls.append(argv)
            if "-m" in argv and "venv" in argv:
                return subprocess.CompletedProcess(argv, 0, "", "")   # claims success, creates nothing
            return StandIn.cmd(self, argv, timeout=timeout, input_text=input_text)
    with pytest.raises(Refused, match="VENV_NOT_CREATED"):
        RA.run_setup(t, rig["commit"], apply=True, run=Liar(t))
    rec = json.loads(t.setup_manifest.read_text())
    assert rec["state"] == "PARTIAL_FAILED"
    assert str(t.venv) not in {o["object"] for o in rec["created"]}


def test_verify_fails_when_the_account_or_environment_is_absent(rig):
    """The V0 defect: verify returned exit 0 with nothing installed."""
    t = rig["t"]
    with pytest.raises(Refused, match="^NO_SETUP_MANIFEST"):
        RA.run_verify(t)
    run = StandIn(t)
    RA.run_setup(t, rig["commit"], apply=True, run=run)
    assert RA.run_verify(t)["ok"]                       # honest pass
    RA.account_facts = lambda u: {"name": u, "present": False}
    with pytest.raises(Refused, match="^IDENTITY_MISSING"):
        RA.run_verify(t)


def test_verify_detects_a_removed_environment_and_a_tampered_view(rig):
    t = rig["t"]
    RA.run_setup(t, rig["commit"], apply=True, run=StandIn(t))
    victim = sorted(t.view_bars.iterdir())[0]
    victim.write_text("TAMPERED")
    with pytest.raises(Refused, match="^VIEW_HASH_MISMATCH"):
        RA.run_verify(t)
    RA.run_setup.__doc__                                  # (no-op; keeps the intent explicit)


def test_verify_detects_a_missing_interpreter(rig):
    t = rig["t"]
    RA.run_setup(t, rig["commit"], apply=True, run=StandIn(t))
    t.python.unlink()
    with pytest.raises(Refused, match="^VENV_NOT_CREATED"):
        RA.run_verify(t)


# ================================ probe ==================================
def _complete(rig):
    RA.run_setup(rig["t"], rig["commit"], apply=True, run=StandIn(rig["t"]))


def test_probe_enters_the_sandbox_and_measures(rig):
    """The V0 defect: probe printed a configuration and executed nothing."""
    t = rig["t"]; _complete(rig)
    good = "\n".join("%s=%s" % (k, str(v).lower()) for k, v in RA.PROBE_EXPECTATIONS.items())

    class ProbeRunner(StandIn):
        def cmd(self, argv, *, timeout=1800, input_text=None):
            argv = [str(x) for x in argv]
            self.calls.append(argv)
            if "systemd-run" in argv:
                return subprocess.CompletedProcess(argv, 0, good, "")
            return StandIn.cmd(self, argv, timeout=timeout, input_text=input_text)
    run = ProbeRunner(t)
    out = RA.run_probe(t, run=run)
    assert out["executed"] and out["ok"] and out["deviations"] == {}
    invocation = [c for c in run.calls if "systemd-run" in c]
    assert len(invocation) == 1, "the probe must actually invoke the sandbox"
    argv = invocation[0]
    for prop in ("ProtectSystem=strict", "PrivateNetwork=yes", "NoNewPrivileges=yes"):
        assert prop in argv
    assert any(a.startswith("BindReadOnlyPaths=%s:" % t.view_bars) for a in argv)
    assert any(a.startswith("TemporaryFileSystem=") for a in argv)
    assert out["denied_example"] == "SPY_2023-06-01.json"     # an out-of-scope file, from the manifest


def test_probe_fails_when_an_expectation_is_violated(rig):
    t = rig["t"]; _complete(rig)
    bad = "\n".join("%s=%s" % (k, "true" if k == "evaluation_readable" else str(v).lower())
                    for k, v in RA.PROBE_EXPECTATIONS.items())

    class BadProbe(StandIn):
        def cmd(self, argv, *, timeout=1800, input_text=None):
            argv = [str(x) for x in argv]
            self.calls.append(argv)
            if "systemd-run" in argv:
                return subprocess.CompletedProcess(argv, 0, bad, "")
            return StandIn.cmd(self, argv, timeout=timeout, input_text=input_text)
    with pytest.raises(Refused, match="^PROBE_FAILED"):
        RA.run_probe(t, run=BadProbe(t))


def test_probe_fails_when_the_sandbox_returns_nothing(rig):
    t = rig["t"]; _complete(rig)

    class Silent(StandIn):
        def cmd(self, argv, *, timeout=1800, input_text=None):
            argv = [str(x) for x in argv]
            self.calls.append(argv)
            if "systemd-run" in argv:
                return subprocess.CompletedProcess(argv, 0, "", "")
            return StandIn.cmd(self, argv, timeout=timeout, input_text=input_text)
    with pytest.raises(Refused, match="^PROBE_FAILED"):
        RA.run_probe(t, run=Silent(t))


def test_probe_refuses_before_setup_is_complete(rig):
    with pytest.raises(Refused, match="^NO_SETUP_MANIFEST"):
        RA.run_probe(rig["t"], run=StandIn(rig["t"]))


# ================================ launch =================================
def _decision(rig):
    d = rig["trust"] / "decision.json"
    d.write_text(json.dumps({"decision": "ADMIT"}))
    d.with_name(d.name + ".sig").write_text("signature")
    return d


def test_working_tree_identity_matches_the_boundary_computation(rig):
    """The wrapper and apex.world_model.real_data.boundary must agree, or a
    launch could pass here and be refused there (or worse, the reverse)."""
    from apex.world_model.real_data import boundary as B
    t = rig["t"]; _complete(rig)
    mine, theirs = RA.working_tree_identity(t.checkout), B.source_identity(t.checkout)
    assert mine["tree_sha256"] == theirs["tree_sha256"]
    assert mine["commit"] == theirs["commit"] and mine["dirty"] == theirs["dirty"]


def test_launch_prepares_with_every_input_resolved(rig):
    t = rig["t"]; _complete(rig)
    plan = RA.prepare_launch(t, rig["commit"], _decision(rig))
    r = plan["resolved"]
    assert r["commit"] == rig["commit"] and len(r["source_tree_sha256"]) == 64
    assert r["view_files"] == len(rig["days"]) and r["experiment"] == "ALPHA-EXP-001B"
    assert r["decision_sha256"] and r["interpreter"] == str(t.python)
    assert "<" not in plan["command"] and "--execute" in plan["command"]
    assert "systemd-run" in plan["argv"] or "systemd-run" in plan["command"]


def test_launch_refuses_source_drift_and_view_drift(rig):
    t = rig["t"]; _complete(rig)
    d = _decision(rig)
    (t.checkout / "apex" / "world_model" / "x.py").write_text("X = 999\n")
    # an edited WORKING file: the committed blobs are unchanged, so only a
    # working-tree check can see this
    with pytest.raises(Refused, match="^SOURCE_DIRTY|^SOURCE_DRIFT"):
        RA.prepare_launch(t, rig["commit"], d)
    _git(t.checkout, "checkout", "--", "apex/world_model/x.py")
    assert RA.prepare_launch(t, rig["commit"], d)["resolved"]["commit"] == rig["commit"]
    sorted(t.view_bars.iterdir())[0].unlink()
    with pytest.raises(Refused, match="^VIEW_DRIFT"):
        RA.prepare_launch(t, rig["commit"], d)


def test_launch_refuses_a_decision_outside_the_trust_root_or_without_a_signature(rig):
    t = rig["t"]; _complete(rig)
    d = rig["tmp"] / "elsewhere.json"; d.write_text("{}")
    d.with_name(d.name + ".sig").write_text("s")
    with pytest.raises(Refused, match="^DECISION_OUTSIDE_TRUST_ROOT"):
        RA.prepare_launch(t, rig["commit"], d)
    d2 = rig["trust"] / "unsigned.json"; d2.write_text("{}")
    with pytest.raises(Refused, match="^DECISION_OR_SIGNATURE_MISSING"):
        RA.prepare_launch(t, rig["commit"], d2)


def test_launch_apply_executes_and_records_the_outcome(rig):
    """The execution path is IMPLEMENTED. It is exercised here against a
    stand-in; the real command is never run in development."""
    t = rig["t"]; _complete(rig)

    class LaunchRunner(StandIn):
        def cmd(self, argv, *, timeout=1800, input_text=None):
            argv = [str(x) for x in argv]
            self.calls.append(argv)
            if "systemd-run" in argv:
                return subprocess.CompletedProcess(
                    argv, 0, json.dumps({"experiment": "ALPHA-EXP-001B",
                                         "process_outcome": "SCIENTIFIC_COMPLETE",
                                         "status": "NO_SIGNAL"}), "")
            return StandIn.cmd(self, argv, timeout=timeout, input_text=input_text)
    run = LaunchRunner(t)
    out = RA.run_launch(t, rig["commit"], _decision(rig), apply=True, run=run)
    assert out["applied"] and out["execution"]["process_outcome"] == "SCIENTIFIC_COMPLETE"
    assert out["execution"]["returncode"] == 0
    rp = Path(out["launch_record"])
    assert rp.exists() and rp.parent == t.out
    assert json.loads(rp.read_text())["resolved"]["commit"] == rig["commit"]
    inv = [c for c in run.calls if "systemd-run" in c]
    assert len(inv) == 1 and "--execute" in inv[0]


def test_launch_without_apply_executes_nothing(rig):
    t = rig["t"]; _complete(rig)
    run = StandIn(t)
    out = RA.run_launch(t, rig["commit"], _decision(rig), apply=False, run=run)
    assert out["applied"] is False and "execution" not in out
    assert not [c for c in run.calls if "systemd-run" in c]


# =============================== rollback ================================
def test_rollback_never_schedules_a_parent_that_contains_evidence(rig):
    """The V0 defect: /apex-data/research listed for removal while its own
    manifest and out/ were listed as preserved."""
    t = rig["t"]; _complete(rig)
    plan = RA.rollback_plan(t)
    removes = [o["object"] for o in plan["remove"]]
    preserves = [o["object"] for o in plan["preserve"]]
    for r in removes:
        for p in preserves:
            assert not p.startswith(r.rstrip("/") + "/"), (r, p)
    assert str(t.research_root) in preserves and str(t.runner_root) in preserves
    parent = [o for o in plan["preserve"] if o["object"] == str(t.research_root)][0]
    assert parent["why_preserved"] == "PARENT_CONTAINS_EVIDENCE"
    assert str(t.out) in parent["evidence_inside"]
    assert str(t.checkout) in parent["removable_children"] and str(t.view) in parent["removable_children"]
    assert str(t.checkout) in removes and str(t.view) in removes
    assert t.research_user in removes                     # the account is removable


def test_rollback_apply_removes_capability_and_keeps_evidence(rig):
    t = rig["t"]; _complete(rig)
    run = StandIn(t)
    out = RA.run_rollback(t, apply=True, run=run)
    assert not t.checkout.exists() and not t.view.exists() and not t.venv.exists()
    assert t.out.exists() and t.setup_manifest.exists() and t.log.exists()
    assert t.pinned.exists() and t.research_root.exists() and t.runner_root.exists()
    assert out["evidence_intact"] == {str(t.out): True, str(t.setup_manifest): True, str(t.log): True}
    assert ["deluser", "--remove-home", t.research_user] in run.calls


def test_rollback_refuses_missing_or_inconsistent_records(rig):
    t = rig["t"]
    with pytest.raises(Refused, match="^NO_SETUP_MANIFEST"):
        RA.rollback_plan(t)
    t.research_root.mkdir(parents=True)
    t.setup_manifest.write_text(json.dumps({"contract": RA.ACTIVATION_VERSION, "state": "COMPLETE",
                                            "created": [{"object": str(t.venv), "class": "nonsense"}]}))
    with pytest.raises(Refused, match="^SETUP_RECORD_INCONSISTENT"):
        RA.rollback_plan(t)
    t.setup_manifest.write_text(json.dumps({"contract": "OTHER", "state": "COMPLETE", "created": []}))
    with pytest.raises(Refused, match="^SETUP_RECORD_CONTRACT"):
        RA.rollback_plan(t)


def test_rollback_never_touches_trust_material_even_if_recorded(rig):
    t = rig["t"]
    t.research_root.mkdir(parents=True)
    t.setup_manifest.write_text(json.dumps({
        "contract": RA.ACTIVATION_VERSION, "state": "COMPLETE", "created": [
            {"object": str(t.trust_root), "class": "capability", "kind": "dir", "stage": "x"},
            {"object": str(t.trust_root / "decision.json"), "class": "capability", "kind": "file", "stage": "x"},
        ]}))
    plan = RA.rollback_plan(t)
    assert plan["remove"] == []
    assert all(o["why_preserved"].startswith("PROTECTED_PATH") for o in plan["preserve"])
    src = (REPO / "scripts/research_activation.py").read_text()
    assert "rm -rf /etc/apex" not in src


def test_rollback_after_a_partial_setup_only_removes_what_was_verified(rig):
    t = rig["t"]
    with pytest.raises(Refused):
        RA.run_setup(t, rig["commit"], apply=True, run=StandIn(t, fail_on="-m venv"))
    plan = RA.rollback_plan(t)
    assert plan["state"] == "PARTIAL_FAILED"
    removes = [o["object"] for o in plan["remove"]]
    assert str(t.venv) not in removes and str(t.checkout) not in removes
    assert t.research_user in removes and str(t.runner_root) in removes


# ============================ end to end =================================
def test_end_to_end_setup_verify_probe_launch_rollback(rig):
    t = rig["t"]
    good = "\n".join("%s=%s" % (k, str(v).lower()) for k, v in RA.PROBE_EXPECTATIONS.items())

    class Full(StandIn):
        def cmd(self, argv, *, timeout=1800, input_text=None):
            argv = [str(x) for x in argv]
            if "systemd-run" in argv:
                self.calls.append(argv)
                return subprocess.CompletedProcess(argv, 0, good, "")
            return StandIn.cmd(self, argv, timeout=timeout, input_text=input_text)
    run = Full(t)
    setup = RA.run_setup(t, rig["commit"], apply=True, run=run)
    assert setup["state"] == "COMPLETE"
    assert RA.run_verify(t)["ok"]
    assert RA.run_probe(t, run=run)["ok"]
    plan = RA.run_launch(t, rig["commit"], _decision(rig), apply=False, run=run)
    assert plan["applied"] is False and plan["resolved"]["commit"] == rig["commit"]
    roll = RA.run_rollback(t, apply=True, run=run)
    assert roll["evidence_intact"][str(t.setup_manifest)] is True
    assert not t.checkout.exists()


def test_cli_exit_codes(rig, capsys):
    t = rig["t"]
    assert RA._cli(["setup"], targets=t) == 3
    assert json.loads(capsys.readouterr().out)["refusal"].startswith("UNRESOLVED_INPUTS")
    assert RA._cli(["setup", "--commit", rig["commit"]], targets=t) == 0
    assert json.loads(capsys.readouterr().out)["state"] == "DRY_RUN"
    assert RA._cli(["verify"], targets=t) == 3
    assert RA._cli(["probe"], targets=t) == 3
    capsys.readouterr()
    assert RA._cli(["setup", "--commit", rig["commit"], "--apply"], targets=t,
                   runner=StandIn(t)) == 0
    capsys.readouterr()
    assert RA._cli(["verify"], targets=t) == 0
    capsys.readouterr()


def test_production_entry_point_injects_nothing():
    src = (REPO / "scripts/research_activation.py").read_text()
    tail = src.split('if __name__ == "__main__":')[1]
    assert "targets=" not in tail and "runner=" not in tail and "sys.exit(_cli())" in tail
    t = RA.production_targets()
    assert (t.research_user, str(t.runner_root), str(t.trust_root), t.expected_view_files) == \
           ("apexresearch", "/opt/apex-runner", "/etc/apex/admissions", 1511)


def test_no_market_row_is_parsed():
    src = (REPO / "scripts/research_activation.py").read_text()
    for forbidden in ("observable_rows", "load_session", "economic_evaluation", "bars.targets"):
        assert forbidden not in src


# ============================ resumption ==================================
# A partial setup used to be terminal: preflight demands untouched ground and
# rollback refuses to delete a parent holding evidence, so the wrapper could
# neither continue nor reset. Finishing the run is the only honest way out.

def _partial(rig, fail_on="git"):
    run = StandIn(rig["t"], fail_on=fail_on)
    with pytest.raises(Refused):
        RA.run_setup(rig["t"], rig["commit"], apply=True, run=run)
    return run


def test_resume_refuses_when_there_is_nothing_to_resume(rig):
    with pytest.raises(Refused, match="NOTHING_TO_RESUME"):
        RA.run_setup(rig["t"], rig["commit"], apply=True, run=StandIn(rig["t"]), resume=True)


def test_resume_refuses_a_setup_that_already_completed(rig):
    RA.run_setup(rig["t"], rig["commit"], apply=True, run=StandIn(rig["t"]))
    with pytest.raises(Refused, match="NOT_RESUMABLE"):
        RA.run_setup(rig["t"], rig["commit"], apply=True, run=StandIn(rig["t"]), resume=True)


def test_resume_refuses_a_different_commit(rig):
    _partial(rig)
    src = rig["t"].source_repo
    (src / "apex" / "world_model" / "x.py").write_text("X = 2\n")
    _git(src, "add", "-A"); _git(src, "commit", "-q", "-m", "second")
    other = _git(src, "rev-parse", "HEAD")
    with pytest.raises(Refused, match="RESUME_COMMIT_MISMATCH"):
        RA.run_setup(rig["t"], other, apply=True, run=StandIn(rig["t"]), resume=True)


def test_resume_finishes_the_run_without_redoing_satisfied_stages(rig):
    """The point of resuming is to perform what is missing and nothing else."""
    t = rig["t"]
    _partial(rig)
    before = json.loads(t.setup_manifest.read_text())
    assert before["state"] == "PARTIAL_FAILED"
    run = StandIn(t)
    rec = RA.run_setup(t, rig["commit"], apply=True, run=run, resume=True)
    assert rec["state"] == "COMPLETE"
    assert rec["resumed_from"] == before["failed_at"]
    carried = {s["stage"] for s in rec["stages"] if s["status"] == "ALREADY_VERIFIED"}
    redone = {s["stage"] for s in rec["stages"] if s["status"] == "VERIFIED"}
    assert "account" in carried and "venv" in carried      # already real, not repeated
    assert before["failed_at"] in redone                   # the missing one was performed
    assert "adduser" not in [c[0] for c in run.calls]      # the account was NOT recreated
    for p in (t.venv, t.python, t.checkout, t.view_bars):
        assert p.exists()


def test_resume_still_verifies_rather_than_trusting_the_record(rig):
    """A carried stage is carried because reality satisfies its verifier now,
    never because a previous record said so. Break the object and the resume
    must rebuild or refuse -- it must not wave it through."""
    t = rig["t"]
    _partial(rig)
    t.python.unlink()                                   # the recorded venv is now a lie
    run = StandIn(t)
    rec = RA.run_setup(t, rig["commit"], apply=True, run=run, resume=True)
    assert rec["state"] == "COMPLETE"
    assert "venv" in {s["stage"] for s in rec["stages"] if s["status"] == "VERIFIED"}
    assert t.python.exists()


def test_a_fresh_setup_still_refuses_ground_that_is_already_broken(rig):
    """Resumption must not become a way to run setup over an existing tree."""
    t = rig["t"]
    _partial(rig)
    with pytest.raises(Refused, match="PREFLIGHT_FAILED"):
        RA.run_setup(t, rig["commit"], apply=True, run=StandIn(t))     # no resume=True


# ============================= re-pinning =================================
def test_probe_uses_the_configuration_the_launch_will_use(rig):
    """A probe of a different configuration proves nothing about this one."""
    t = rig["t"]
    assert RA.launch_config(t, probe=True).properties == RA.launch_config(t).properties


def test_repin_refuses_a_commit_that_changes_the_experiment_code(rig):
    t = rig["t"]
    RA.run_setup(t, rig["commit"], apply=True, run=StandIn(t))
    src = t.source_repo
    (src / "apex" / "world_model" / "x.py").write_text("X = 99\n")     # bound path
    _git(src, "add", "-A"); _git(src, "commit", "-q", "-m", "changes the experiment")
    with pytest.raises(Refused, match="REPIN_CHANGES_EXPERIMENT_CODE"):
        RA.run_repin(t, _git(src, "rev-parse", "HEAD"), apply=True, run=StandIn(t))


def test_repin_moves_the_checkout_when_the_experiment_is_untouched(rig):
    """Wrapper repairs land after a checkout is prepared. Re-pinning to them is
    allowed precisely because the bound tree does not move."""
    t = rig["t"]
    RA.run_setup(t, rig["commit"], apply=True, run=StandIn(t))
    before = json.loads(t.setup_manifest.read_text())
    src = t.source_repo
    (src / "README_tooling.md").write_text("wrapper repair, not experiment code\n")
    _git(src, "add", "-A"); _git(src, "commit", "-q", "-m", "tooling only")
    newc = _git(src, "rev-parse", "HEAD")
    plan = RA.run_repin(t, newc, apply=True, run=StandIn(t))
    assert plan["to"]["commit"] == newc
    assert plan["to"]["source_tree_sha256"] == before["source_tree_sha256"]
    after = json.loads(t.setup_manifest.read_text())
    assert after["commit"] == newc
    assert after["source_tree_sha256"] == before["source_tree_sha256"]
    assert RA._git(t.checkout, "rev-parse", "HEAD").strip() == newc
    # and the launch now resolves against the re-pinned commit
    d = rig["trust"] / "d.json"; d.write_text("{}"); d.with_name("d.json.sig").write_text("s")
    RA.prepare_launch(t, newc, d)


def test_repin_without_apply_moves_nothing(rig):
    t = rig["t"]
    RA.run_setup(t, rig["commit"], apply=True, run=StandIn(t))
    plan = RA.run_repin(t, rig["commit"], apply=False, run=StandIn(t))
    assert plan["applied"] is False and "evidence" not in plan
    assert json.loads(t.setup_manifest.read_text())["commit"] == rig["commit"]
