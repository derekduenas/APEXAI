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
    assert "<" not in plan["executable_command"] and "--execute" in plan["executable_command"]
    assert "systemd-run" in plan["argv"] or "systemd-run" in plan["executable_command"]


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
        # the child now goes through run_child, so that is what a stand-in
        # intercepts; cmd never sees the experiment
        def run_child(self, argv, *, timeout):
            self.calls.append([str(a) for a in argv])
            res = t.out / RA.EXPERIMENT_ID / "runs" / "standin" / "_RESULT.json"
            res.parent.mkdir(parents=True, exist_ok=True)
            res.write_text(json.dumps({"status": "NO_SIGNAL"}))
            res.with_name("_RUN.json").write_text(json.dumps(
                {"run_id": "standin", "decision_sha256": RA.sha256_of(_decision(rig))}))
            return {"returncode": 0, "timed_out": False, "spawn_error": None,
                    "stdout": json.dumps({"experiment": "ALPHA-EXP-001B",
                                          "process_outcome": "SCIENTIFIC_COMPLETE",
                                          "status": "NO_SIGNAL"}), "stderr": ""}
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


# ================= operator instructions must be accurate =================
# The generated argv carries --execute and RUNS the experiment. An earlier
# signing document told the operator to run "the same command without --apply",
# which is not a dry run of anything: --apply is a flag of the wrapper, not of
# that argv. These tests exist so the instruction cannot drift again.

def test_preparation_launches_nothing(rig):
    t = rig["t"]
    RA.run_setup(t, rig["commit"], apply=True, run=StandIn(t))
    d = _decision(rig)
    run = StandIn(t)
    plan = RA.run_launch(t, rig["commit"], d, apply=False, run=run)
    assert plan["applied"] is False
    assert "execution" not in plan
    assert run.calls == [], run.calls          # nothing was run at all
    assert not any("systemd-run" in " ".join(c) for c in run.calls)


def test_the_two_operator_commands_differ_only_by_apply(rig):
    t = rig["t"]
    RA.run_setup(t, rig["commit"], apply=True, run=StandIn(t))
    oc = RA.prepare_launch(t, rig["commit"], _decision(rig))["operator_commands"]
    assert "--apply" not in oc["prepare"]
    assert oc["execute"] == oc["prepare"] + " --apply"
    assert "research_activation.py launch" in oc["prepare"]
    assert "--execute" not in oc["prepare"]     # that belongs to the inner argv only


def test_the_generated_argv_is_labelled_executable_never_a_dry_run(rig):
    t = rig["t"]
    RA.run_setup(t, rig["commit"], apply=True, run=StandIn(t))
    plan = RA.prepare_launch(t, rig["commit"], _decision(rig))
    assert "--execute" in plan["executable_command"]
    assert "RUNS the experiment" in plan["EXECUTABLE_COMMAND_WARNING"]
    assert "not a dry run" in plan["EXECUTABLE_COMMAND_WARNING"]


def test_preparation_does_not_claim_signature_or_dataset_integrity(rig):
    """Existence of a .sig file is not verification, and a file count is not
    integrity. Preparation must say so itself."""
    t = rig["t"]
    RA.run_setup(t, rig["commit"], apply=True, run=StandIn(t))
    plan = RA.prepare_launch(t, rig["commit"], _decision(rig))
    c = plan["checks_performed"]
    assert c["signature_file_exists"] is True
    assert c["signature_cryptographically_VERIFIED"] is False
    assert c["dataset_view_file_COUNT_matches"] is True
    assert c["dataset_view_file_HASHES_rechecked"] is False
    e = plan["checks_not_performed_here"]
    assert "verify_decision" in e["signature_verification"]
    assert "VIEW_HASH_MISMATCH" in e["dataset_content_integrity"]


def test_a_similarly_named_sibling_of_the_trust_root_is_refused(rig):
    """A string prefix test accepted /etc/apex/admissions-other. Containment
    does not."""
    t = rig["t"]
    RA.run_setup(t, rig["commit"], apply=True, run=StandIn(t))
    sibling = Path(str(t.trust_root) + "-other")
    sibling.mkdir(parents=True, exist_ok=True)
    d = sibling / "d.json"
    d.write_text("{}"); d.with_name("d.json.sig").write_text("s")
    assert str(d.resolve()).startswith(str(t.trust_root.resolve()))   # the old test passed it
    with pytest.raises(Refused, match="DECISION_OUTSIDE_TRUST_ROOT"):
        RA.prepare_launch(t, rig["commit"], d)


def test_the_real_trust_root_is_still_accepted(rig):
    """The fix must not make the legitimate path unreachable."""
    t = rig["t"]
    RA.run_setup(t, rig["commit"], apply=True, run=StandIn(t))
    RA.prepare_launch(t, rig["commit"], _decision(rig))


# ============ launch outcome reporting, through the real CLI ==============
# An OOM-killed run exited 0. These tests drive the actual CLI with controlled
# child processes and require the outcome to survive to the exit code.

class Child(StandIn):
    """A runner whose experiment child is a REAL process with scripted behaviour."""

    def __init__(self, targets, *, script, **kw):
        super().__init__(targets, **kw)
        self.script = script
        self.child_calls = []

    def run_child(self, argv, *, timeout):
        self.child_calls.append([str(a) for a in argv])
        return super().run_child([sys.executable, "-c", self.script], timeout=timeout)


def _ready(rig):
    RA.run_setup(rig["t"], rig["commit"], apply=True, run=StandIn(rig["t"]))
    return _decision(rig)


def _cli_launch(rig, runner, tmp):
    out = tmp / "launch.json"
    code = RA._cli(["launch", "--commit", rig["commit"], "--decision", str(_decision(rig)),
                    "--apply", "--json", str(out)], targets=rig["t"], runner=runner)
    return code, json.loads(out.read_text())


OK_JSON = ('import json,sys,pathlib\n'
           'p=pathlib.Path(%r)\n'
           'p.parent.mkdir(parents=True,exist_ok=True)\n'
           'p.write_text(json.dumps({"status":"NO_SIGNAL"}))\n'
           'p.with_name("_RUN.json").write_text(json.dumps('
           '{"run_id":"r1","decision_sha256":%r}))\n'
           'print(json.dumps({"process_outcome":"COMPLETED"}))\n')


def _dsha(rig):
    return RA.sha256_of(_decision(rig))


def _seal_script(res_path, dsha, status="NO_SIGNAL", run_id="r1"):
    return ('import json,pathlib\n'
            'p=pathlib.Path(%r)\n'
            'p.parent.mkdir(parents=True,exist_ok=True)\n'
            'p.write_text(json.dumps({"status":%r}))\n'
            'p.with_name("_RUN.json").write_text(json.dumps({"run_id":%r,'
            '"decision_sha256":%r}))\n'
            'print(json.dumps({"process_outcome":"COMPLETED"}))\n'
            % (str(res_path), status, run_id, dsha))


def test_a_child_that_seals_a_result_and_exits_zero_is_the_only_success(rig, tmp_path):
    t = rig["t"]; _ready(rig)
    res = t.out / RA.EXPERIMENT_ID / "runs" / "r1" / "_RESULT.json"
    run = Child(t, script=OK_JSON % (str(res), _dsha(rig)))
    code, rec = _cli_launch(rig, run, tmp_path)
    assert rec["execution"]["outcome"] == RA.LAUNCH_COMPLETED
    assert rec["execution"]["result_sealed"] is True
    assert rec["status"] == "OK" and code == 0


def test_a_child_that_exits_zero_without_sealing_is_not_a_success(rig, tmp_path):
    """The defect in one line: a missing result must never become success."""
    t = rig["t"]; _ready(rig)
    run = Child(t, script="print('did nothing')")
    code, rec = _cli_launch(rig, run, tmp_path)
    assert rec["execution"]["outcome"] == RA.LAUNCH_NO_RESULT
    assert rec["execution"]["result_sealed"] is False
    assert rec["status"] == "FAILED"
    assert code == RA.LAUNCH_EXIT_CODES[RA.LAUNCH_NO_RESULT] != 0


def test_an_oom_killed_child_is_classified_from_systemd_evidence(rig, tmp_path):
    t = rig["t"]; _ready(rig)
    run = Child(t, script=("import sys\n"
                           "sys.stderr.write('Finished with result: oom-kill\\n"
                           "Main processes terminated with: code=killed/status=KILL\\n')\n"
                           "sys.exit(1)\n"))
    code, rec = _cli_launch(rig, run, tmp_path)
    assert rec["execution"]["outcome"] == RA.LAUNCH_OOM
    assert "memory" in rec["execution"]["outcome_evidence"]
    assert code == RA.LAUNCH_EXIT_CODES[RA.LAUNCH_OOM]
    assert "oom-kill" in rec["execution"]["stderr"]      # evidence preserved


def test_a_refusing_child_is_distinguished_from_an_ordinary_failure(rig, tmp_path):
    t = rig["t"]; _ready(rig)
    run = Child(t, script=("import json,sys\n"
                           "print(json.dumps({'process_outcome':'AUTHORIZATION_REFUSED',"
                           "'refusal':'SCOPE_INVALID: made up family'}))\n"
                           "sys.exit(3)\n"))
    code, rec = _cli_launch(rig, run, tmp_path)
    assert rec["execution"]["outcome"] == RA.LAUNCH_REFUSED
    assert rec["execution"]["process_outcome"] == "AUTHORIZATION_REFUSED"
    assert code == RA.LAUNCH_EXIT_CODES[RA.LAUNCH_REFUSED]
    # the refusal text survives; it had to be recovered by hand before
    assert "SCOPE_INVALID" in rec["execution"]["stdout"]


def test_an_ordinary_failure_keeps_its_traceback(rig, tmp_path):
    t = rig["t"]; _ready(rig)
    run = Child(t, script="raise RuntimeError('boom in the experiment')")
    code, rec = _cli_launch(rig, run, tmp_path)
    assert rec["execution"]["outcome"] == RA.LAUNCH_FAILED
    assert code == RA.LAUNCH_EXIT_CODES[RA.LAUNCH_FAILED]
    assert "boom in the experiment" in rec["execution"]["stderr"]


def test_a_timeout_is_its_own_outcome(rig, tmp_path):
    t = rig["t"]; _ready(rig)

    class Slow(Child):
        def run_child(self, argv, *, timeout):
            return RA.SystemRunner.run_child(self, [sys.executable, "-c",
                                                     "import time; time.sleep(30)"], timeout=0.5)
    run = Slow(t, script="")
    code, rec = _cli_launch(rig, run, tmp_path)
    assert rec["execution"]["outcome"] == RA.LAUNCH_TIMEOUT
    assert rec["execution"]["timed_out"] is True
    assert code == RA.LAUNCH_EXIT_CODES[RA.LAUNCH_TIMEOUT]


def test_every_non_completed_outcome_exits_nonzero():
    for name, code in RA.LAUNCH_EXIT_CODES.items():
        assert (code == 0) == (name == RA.LAUNCH_COMPLETED), (name, code)


# ======== a result counts only if it belongs to THIS run and completed ========

def test_a_result_left_by_an_earlier_run_is_not_this_runs_success(rig, tmp_path):
    """Existence is not enough. A stale result must not be adopted."""
    t = rig["t"]; _ready(rig)
    stale = t.out / RA.EXPERIMENT_ID / "runs" / "older" / "_RESULT.json"
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_text(json.dumps({"status": "NO_SIGNAL"}))
    stale.with_name("_RUN.json").write_text(json.dumps(
        {"run_id": "older", "decision_sha256": _dsha(rig)}))
    run = Child(t, script="print('sealed nothing of my own')")
    code, rec = _cli_launch(rig, run, tmp_path)
    assert rec["execution"]["result_sealed"] is False
    assert rec["execution"]["outcome"] == RA.LAUNCH_NO_RESULT
    assert code != 0


def test_a_result_from_a_different_decision_is_not_counted(rig, tmp_path):
    t = rig["t"]; _ready(rig)
    res = t.out / RA.EXPERIMENT_ID / "runs" / "other" / "_RESULT.json"
    run = Child(t, script=_seal_script(res, "0" * 64, run_id="other"))
    code, rec = _cli_launch(rig, run, tmp_path)
    assert rec["execution"]["result_sealed"] is False
    assert any("not the one launched" in r.get("why", "")
               for r in rec["execution"]["results_considered"])
    assert code != 0


def test_a_result_recording_a_refusal_is_not_a_completed_outcome(rig, tmp_path):
    t = rig["t"]; _ready(rig)
    res = t.out / RA.EXPERIMENT_ID / "runs" / "refused" / "_RESULT.json"
    run = Child(t, script=_seal_script(res, _dsha(rig), status="ADMISSION_REFUSED",
                                       run_id="refused"))
    code, rec = _cli_launch(rig, run, tmp_path)
    assert rec["execution"]["result_sealed"] is False
    assert any("not a completed outcome" in r.get("why", "")
               for r in rec["execution"]["results_considered"])
    assert code != 0


def test_a_result_with_no_outcome_recorded_is_not_counted(rig, tmp_path):
    t = rig["t"]; _ready(rig)
    res = t.out / RA.EXPERIMENT_ID / "runs" / "blank" / "_RESULT.json"
    run = Child(t, script=('import json,pathlib\n'
                           'p=pathlib.Path(%r)\n'
                           'p.parent.mkdir(parents=True,exist_ok=True)\n'
                           'p.write_text(json.dumps({"note":"nothing useful"}))\n'
                           'p.with_name("_RUN.json").write_text(json.dumps('
                           '{"run_id":"blank","decision_sha256":%r}))\n'
                           % (str(res), _dsha(rig))))
    code, rec = _cli_launch(rig, run, tmp_path)
    assert rec["execution"]["result_sealed"] is False
    assert any("records no outcome" in r.get("why", "")
               for r in rec["execution"]["results_considered"])
    assert code != 0


def test_a_result_that_does_belong_to_this_run_still_succeeds(rig, tmp_path):
    """The tightening must not make the real success path unreachable."""
    t = rig["t"]; _ready(rig)
    res = t.out / RA.EXPERIMENT_ID / "runs" / "mine" / "_RESULT.json"
    run = Child(t, script=_seal_script(res, _dsha(rig), run_id="mine"))
    code, rec = _cli_launch(rig, run, tmp_path)
    assert rec["execution"]["result_sealed"] is True
    assert rec["execution"]["sealed_results"][0]["run_id"] == "mine"
    assert rec["execution"]["outcome"] == RA.LAUNCH_COMPLETED and code == 0


# ============== exit 4 is EVALUATION_SEALED, not a free pass ==============
# The experiment's own table gives exit 4 to EVALUATION_SEALED: validation
# detected signal and evaluation stayed sealed. That is a completed run. But it
# must be accepted BECAUSE a valid bound result exists, never merely because the
# child returned 4.

def test_exit_4_without_a_bound_result_is_not_accepted(rig, tmp_path):
    t = rig["t"]; _ready(rig)
    run = Child(t, script="import sys; print('signal detected'); sys.exit(4)")
    code, rec = _cli_launch(rig, run, tmp_path)
    assert rec["execution"]["returncode"] == 4
    assert rec["execution"]["result_sealed"] is False
    # exit 4 loses its standing entirely without a bound result: it falls back
    # to an ordinary failure rather than being read as a completed run
    assert rec["execution"]["outcome"] == RA.LAUNCH_FAILED
    assert rec["status"] == "FAILED"
    assert code == RA.LAUNCH_EXIT_CODES[RA.LAUNCH_FAILED] != 0


def test_exit_4_with_a_result_from_another_decision_is_not_accepted(rig, tmp_path):
    t = rig["t"]; _ready(rig)
    res = t.out / RA.EXPERIMENT_ID / "runs" / "elsewhere" / "_RESULT.json"
    run = Child(t, script=_seal_script(res, "0" * 64, status="SEALED_EVALUATION_PENDING",
                                       run_id="elsewhere") +
                          "import sys; sys.exit(4)\n")
    code, rec = _cli_launch(rig, run, tmp_path)
    assert rec["execution"]["returncode"] == 4
    assert rec["execution"]["result_sealed"] is False
    assert code != 0


def test_exit_4_with_a_valid_bound_result_is_accepted(rig, tmp_path):
    """A signal-detecting run must not be reported as a failure."""
    t = rig["t"]; _ready(rig)
    res = t.out / RA.EXPERIMENT_ID / "runs" / "sealed" / "_RESULT.json"
    run = Child(t, script=_seal_script(res, _dsha(rig), status="SEALED_EVALUATION_PENDING",
                                       run_id="sealed") +
                          "import sys; sys.exit(4)\n")
    code, rec = _cli_launch(rig, run, tmp_path)
    assert rec["execution"]["returncode"] == 4
    assert rec["execution"]["result_sealed"] is True
    assert rec["execution"]["outcome"] == RA.LAUNCH_COMPLETED
    assert code == 0


def test_no_other_nonzero_exit_is_rescued_by_a_sealed_result(rig, tmp_path):
    """Only 4 has this standing. A crash that happens to leave a result behind
    is still a failure."""
    t = rig["t"]; _ready(rig)
    res = t.out / RA.EXPERIMENT_ID / "runs" / "crashed" / "_RESULT.json"
    run = Child(t, script=_seal_script(res, _dsha(rig), run_id="crashed") +
                          "import sys; sys.exit(5)\n")
    code, rec = _cli_launch(rig, run, tmp_path)
    assert rec["execution"]["outcome"] == RA.LAUNCH_FAILED
    assert code == RA.LAUNCH_EXIT_CODES[RA.LAUNCH_FAILED]


# ================= two environments, side by side =========================
# Revision 2 must be unable to reach revision 1: not through setup, not through
# resume, and above all not through rollback, which removes an account by name.

from dataclasses import replace as _replace


class Multi(StandIn):
    """A stand-in with a SHARED account registry, so two environments can hold
    two accounts at once and one teardown can be seen not to touch the other."""

    def __init__(self, targets, users, **kw):
        super().__init__(targets, **kw)
        self.users = users

    def cmd(self, argv, *, timeout=1800, input_text=None):
        argv = [str(x) for x in argv]
        if argv[0] == "adduser":
            self.calls.append(argv); self.users.add(argv[-1])
            return subprocess.CompletedProcess(argv, 0, "", "")
        if argv[0] == "deluser":
            self.calls.append(argv); self.users.discard(argv[-1])
            return subprocess.CompletedProcess(argv, 0, "", "")
        return super().cmd(argv, timeout=timeout, input_text=input_text)


@pytest.fixture
def two(rig, monkeypatch):
    users = set()

    def facts(u, _u=users):
        if u in _u:
            return {"name": u, "present": True, "uid": os.getuid(), "gid": os.getgid(),
                    "shell": "/usr/sbin/nologin", "home": "/home/%s" % u,
                    "groups": [u], "privileged_groups": []}
        return {"name": u, "present": False}
    monkeypatch.setattr(RA, "account_facts", facts)
    tmp = rig["tmp"]
    e1 = _replace(rig["t"], research_user="rev1_research")
    e2 = _replace(rig["t"], research_root=tmp / "research2", runner_root=tmp / "runner2",
                  research_user="rev2_research")
    return {"users": users, "e1": e1, "e2": e2, "commit": rig["commit"], "rig": rig}


def _setup(env, users, commit, **kw):
    run = Multi(env, users, **kw)
    return RA.run_setup(env, commit, apply=True, run=run), run


def test_two_environments_stand_up_independently(two):
    e1, e2, users = two["e1"], two["e2"], two["users"]
    r1, _ = _setup(e1, users, two["commit"])
    r2, _ = _setup(e2, users, two["commit"])
    assert r1["state"] == "COMPLETE" and r2["state"] == "COMPLETE"
    assert users == {"rev1_research", "rev2_research"}
    for e in (e1, e2):
        for p in (e.checkout, e.venv, e.view_bars, e.out):
            assert p.exists(), (e.research_user, p)
    assert e1.research_root != e2.research_root
    assert e1.setup_manifest != e2.setup_manifest


def test_rolling_back_the_second_leaves_the_first_and_its_account_intact(two):
    e1, e2, users = two["e1"], two["e2"], two["users"]
    _setup(e1, users, two["commit"])
    _setup(e2, users, two["commit"])
    before = {p: p.exists() for p in (e1.checkout, e1.venv, e1.view_bars, e1.out,
                                      e1.setup_manifest)}
    run = Multi(e2, users)
    RA.run_rollback(e2, apply=True, run=run)

    # the first environment is untouched, including its account
    assert "rev1_research" in users
    assert {p: p.exists() for p in before} == before
    # and nothing the rollback ran named the first environment
    for c in run.calls:
        joined = " ".join(c)
        assert "rev1_research" not in joined, c
        assert str(e1.research_root) not in joined, c
        assert str(e1.runner_root) not in joined, c


def test_resuming_the_second_cannot_disturb_the_first(two):
    e1, e2, users = two["e1"], two["e2"], two["users"]
    _setup(e1, users, two["commit"])
    with pytest.raises(Refused):
        RA.run_setup(e2, two["commit"], apply=True, run=Multi(e2, users, fail_on="git"))
    m1_before = e1.setup_manifest.read_text()
    rec = RA.run_setup(e2, two["commit"], apply=True, run=Multi(e2, users), resume=True)
    assert rec["state"] == "COMPLETE"
    assert e1.setup_manifest.read_text() == m1_before
    assert "rev1_research" in users


# ---------------- target validation, before any mutation ------------------

def test_a_revision_may_not_share_the_production_account(rig):
    d = RA.production_targets()
    t = _replace(rig["t"], research_user=d.research_user)
    with pytest.raises(Refused, match="SHARED_RESEARCH_ACCOUNT"):
        RA.validate_targets(t)


def test_a_revision_may_not_reach_the_preserved_environment(rig):
    d = RA.production_targets()
    for field, val in (("research_root", Path(str(d.research_root)) / "rev2"),
                       ("runner_root", Path(str(d.runner_root)) / "rev2")):
        t = _replace(rig["t"], research_user="rev2", **{field: val})
        with pytest.raises(Refused, match="TARGET_WOULD_REACH_PRESERVED_ENVIRONMENT"):
            RA.validate_targets(t)


@pytest.mark.parametrize("bad", ["/", "/etc", "/etc/apex", "/opt", "/apex-data",
                                 "/apex-data/history-b", "/usr", "/root"])
def test_protected_locations_are_refused(rig, bad):
    t = _replace(rig["t"], research_root=Path(bad), research_user="rev2")
    with pytest.raises(Refused, match="TARGET_IS_OR_CONTAINS_PROTECTED|TARGET_INSIDE_PROTECTED"):
        RA.validate_targets(t)


def test_overlapping_roots_are_refused(rig):
    t = _replace(rig["t"], runner_root=rig["t"].research_root / "runner",
                 research_user="rev2")
    with pytest.raises(Refused, match="TARGETS_OVERLAP"):
        RA.validate_targets(t)


def test_the_production_default_triple_still_validates():
    facts = RA.validate_targets(RA.production_targets())
    assert facts["environment"] == "PRODUCTION DEFAULT"
    assert facts["disjoint_from_default"] is False


def test_validation_runs_before_anything_is_created(rig, tmp_path):
    """Refusal must happen with the ground untouched."""
    t = _replace(rig["t"], research_root=Path("/etc/apex/rev2"), research_user="rev2")
    with pytest.raises(Refused):
        RA.run_setup(t, rig["commit"], apply=True, run=StandIn(t))
    assert not Path("/etc/apex/rev2").exists()


# ------------- generated commands must carry the selections ---------------

def test_operator_commands_name_the_environment_they_act_on(two):
    e2, users = two["e2"], two["users"]
    _setup(e2, users, two["commit"])
    d = _decision(two["rig"])
    oc = RA.prepare_launch(e2, two["commit"], d)["operator_commands"]
    for flag, val in (("--research-root", str(e2.research_root)),
                      ("--runner-root", str(e2.runner_root)),
                      ("--research-user", e2.research_user)):
        assert "%s %s" % (flag, val) in oc["prepare"], (flag, oc["prepare"])
        assert "%s %s" % (flag, val) in oc["execute"]
    assert oc["execute"] == oc["prepare"] + " --apply"


def test_default_environment_commands_carry_no_flags(rig):
    """Production must not grow noise it does not need."""
    d = RA.production_targets()
    oc = RA.operator_commands(d, "abc123", Path("/etc/apex/admissions/x.json"))
    assert "--research-root" not in oc["prepare"]
    assert "--runner-root" not in oc["prepare"]
    assert "--research-user" not in oc["prepare"]
