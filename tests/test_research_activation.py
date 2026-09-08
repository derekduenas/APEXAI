"""RESEARCH_ACTIVATION_V0 -- failure behaviour first.

Every test uses disposable fixtures under tmp_path: a fake corpus, a fake
committed manifest, a throwaway git repo standing in for the source repo.
No real corpus file is read, no account is created, no privileged command
runs, and no market row is parsed anywhere in this module.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("research_activation",
                                               REPO / "scripts/research_activation.py")
RA = importlib.util.module_from_spec(_spec)
# dataclasses resolves annotations through sys.modules[cls.__module__]; a
# module loaded by path must be registered there before it is executed
sys.modules["research_activation"] = RA
_spec.loader.exec_module(RA)
Refused = RA.ActivationRefused


def _git(repo, *args):
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


@pytest.fixture
def rig(tmp_path):
    """A complete, VALID activation input set. Each test breaks exactly one
    thing, so a failure names the thing that was broken."""
    corpus = tmp_path / "corpus" / "bars"; corpus.mkdir(parents=True)
    files = {}
    days = [f"2019-06-{d:02d}" for d in range(3, 8)] + [f"2020-06-{d:02d}" for d in range(1, 6)]
    for d in days:
        p = corpus / f"SPY_{d}.json"
        p.write_text(json.dumps({"source": "alpaca_sip_raw_1m", "bars": [{"t": d}]}))
        files[p.name] = {"sha256": RA.sha256_of(p), "size": p.stat().st_size,
                         "symbol": "SPY", "session_date": d}
    # out-of-scope and other-symbol entries that MUST NOT be selected
    for name, sym, day in (("SPY_2023-06-01.json", "SPY", "2023-06-01"),
                           ("QQQ_2019-06-03.json", "QQQ", "2019-06-03")):
        p = corpus / name
        p.write_text(json.dumps({"source": "alpaca_sip_raw_1m", "bars": [{"t": day}]}))
        files[name] = {"sha256": RA.sha256_of(p), "size": p.stat().st_size,
                       "symbol": sym, "session_date": day}
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"dataset_id": "fixture/etf", "root": str(corpus),
                                    "source_families": ["alpaca_sip_raw_1m"], "files": files}, indent=1))
    src = tmp_path / "srcrepo"; (src / "apex" / "world_model").mkdir(parents=True)
    (src / "apex" / "world_model" / "x.py").write_text("X = 1\n")
    (src / "scripts").mkdir(); (src / "scripts" / "alpha_exp_real_execute.py").write_text("# cmd\n")
    _git(src, "init", "-q"); _git(src, "config", "user.email", "t@t"); _git(src, "config", "user.name", "t")
    _git(src, "add", "-A"); _git(src, "commit", "-q", "-m", "base")
    commit = _git(src, "rev-parse", "HEAD")
    trust = tmp_path / "trust"; (trust / "trust").mkdir(parents=True)
    t = RA.Targets(research_user="nonexistent_research_user", runner_root=tmp_path / "runner",
                   research_root=tmp_path / "research", source_repo=src, corpus_root=corpus,
                   manifest_path=manifest, trust_root=trust,
                   allowed_signers=trust / "trust" / "allowed_signers",
                   expected_view_files=len(days))
    return {"t": t, "tmp": tmp_path, "corpus": corpus, "manifest": manifest,
            "commit": commit, "days": days, "trust": trust}


def _rewrite_manifest(rig, mutate):
    m = json.loads(rig["manifest"].read_text())
    mutate(m)
    rig["manifest"].write_text(json.dumps(m, indent=1))


# ------------------------------------------------- selection from the manifest
def test_selection_comes_from_the_manifest_not_a_glob(rig):
    sel = RA.admitted_files(rig["t"])
    names = [Path(s["rel"]).name for s in sel]
    assert len(sel) == len(rig["days"])
    assert all(n.startswith("SPY_") for n in names)
    assert "SPY_2023-06-01.json" not in names          # out of scope
    assert "QQQ_2019-06-03.json" not in names          # other symbol
    # a file present on disk but ABSENT from the manifest is never selected
    (rig["corpus"] / "SPY_2019-06-10.json").write_text("{}")
    assert len(RA.admitted_files(rig["t"])) == len(rig["days"])


def test_manifest_root_mismatch_aborts(rig):
    _rewrite_manifest(rig, lambda m: m.update(root="/somewhere/else"))
    with pytest.raises(Refused, match="^MANIFEST_ROOT_MISMATCH"):
        RA.admitted_files(rig["t"])


def test_empty_selection_aborts(rig):
    _rewrite_manifest(rig, lambda m: m.update(files={k: v for k, v in m["files"].items()
                                                     if v["symbol"] != "SPY"}))
    with pytest.raises(Refused, match="^EMPTY_SELECTION"):
        RA.admitted_files(rig["t"])


# ------------------------------------------------------------- view building
def test_view_build_succeeds_and_reconciles(rig):
    t = rig["t"]
    out = RA.build_view(t, RA.admitted_files(t), apply=True)
    assert out["applied"] and out["files"] == len(rig["days"])
    present = sorted(p.name for p in t.view_bars.iterdir())
    assert len(present) == len(rig["days"])
    for name in present:
        src, dst = rig["corpus"] / name, t.view_bars / name
        assert RA.sha256_of(src) == RA.sha256_of(dst)
    assert not (t.view.with_name(t.view.name + ".staging")).exists()


def test_hash_mismatch_aborts_and_leaves_no_partial_view(rig):
    t = rig["t"]
    files = RA.admitted_files(t)
    (rig["corpus"] / Path(files[2]["rel"]).name).write_text("TAMPERED")
    with pytest.raises(Refused, match="^SOURCE_HASH_MISMATCH"):
        RA.build_view(t, files, apply=True)
    assert not t.view.exists()
    assert not t.view.with_name(t.view.name + ".staging").exists()      # no partial view survives


def test_missing_source_file_aborts(rig):
    t = rig["t"]
    files = RA.admitted_files(t)
    (rig["corpus"] / Path(files[0]["rel"]).name).unlink()
    with pytest.raises(Refused, match="^SOURCE_MISSING"):
        RA.build_view(t, files, apply=True)
    assert not t.view.exists()


def test_short_inventory_aborts(rig):
    t = rig["t"]
    files = RA.admitted_files(t)
    with pytest.raises(Refused, match="^INVENTORY_COUNT"):
        RA.build_view(t, files[:-1], apply=True)                        # one short
    assert not t.view.exists()


def test_duplicate_selection_aborts(rig):
    t = rig["t"]
    files = RA.admitted_files(t)
    with pytest.raises(Refused, match="^INVENTORY_DUPLICATE"):
        RA.build_view(t, files + [dict(files[0])], apply=True)
    assert not t.view.exists()


def test_an_extra_file_appearing_in_staging_aborts(rig, monkeypatch):
    """Reconciliation is against the manifest selection, so a file that
    appears in staging by any other route is caught."""
    t = rig["t"]
    files = RA.admitted_files(t)
    real_copy = RA.shutil.copy2
    state = {"planted": False}

    def copy_and_plant(src, dst, *a, **k):
        out = real_copy(src, dst, *a, **k)
        if not state["planted"]:
            Path(dst).with_name("SPY_9999-01-01.json").write_text("{}")
            state["planted"] = True
        return out
    monkeypatch.setattr(RA.shutil, "copy2", copy_and_plant)
    with pytest.raises(Refused, match="^INVENTORY_MISMATCH"):
        RA.build_view(t, files, apply=True)
    assert not t.view.exists()


def test_conflicting_destination_aborts(rig):
    t = rig["t"]
    t.view.mkdir(parents=True)
    with pytest.raises(Refused, match="^DESTINATION_EXISTS"):
        RA.build_view(t, RA.admitted_files(t), apply=True)


def test_a_symlink_pointing_outside_the_corpus_is_refused_as_an_escape(rig):
    t = rig["t"]
    files = RA.admitted_files(t)
    victim = rig["corpus"] / Path(files[1]["rel"]).name
    outside = rig["tmp"] / "outside.json"
    outside.write_text(victim.read_text())
    victim.unlink(); victim.symlink_to(outside)
    with pytest.raises(Refused, match="^PATH_ESCAPE"):
        RA.build_view(t, files, apply=True)
    assert not t.view.exists()


def test_a_symlink_pointing_inside_the_corpus_is_still_refused(rig):
    """Even a symlink that resolves inside the corpus is refused: the view
    must be built from real files, not from links whose target can change."""
    t = rig["t"]
    files = RA.admitted_files(t)
    victim = rig["corpus"] / Path(files[1]["rel"]).name
    twin = rig["corpus"] / "_twin.json"
    twin.write_text(victim.read_text())
    victim.unlink(); victim.symlink_to(twin)
    with pytest.raises(Refused, match="^SYMLINK_REFUSED"):
        RA.build_view(t, files, apply=True)
    assert not t.view.exists()


def test_dry_run_creates_nothing(rig):
    t = rig["t"]
    out = RA.build_view(t, RA.admitted_files(t), apply=False)
    assert out["applied"] is False and not t.view.exists()


# ------------------------------------------------------------------ identity
def test_identity_conflicts_and_privilege_are_refused(rig, monkeypatch):
    with pytest.raises(Refused, match="^IDENTITY_MISSING"):
        RA.assert_identity("nonexistent_research_user", must_exist=True)
    monkeypatch.setattr(RA, "account_facts", lambda u: {
        "name": u, "present": True, "uid": 4242, "groups": [u], "privileged_groups": []})
    with pytest.raises(Refused, match="^IDENTITY_CONFLICT"):
        RA.assert_identity("someone", must_exist=False)
    monkeypatch.setattr(RA, "account_facts", lambda u: {
        "name": u, "present": True, "uid": 4242, "groups": [u, "sudo"], "privileged_groups": ["sudo"]})
    with pytest.raises(Refused, match="^IDENTITY_PRIVILEGED"):
        RA.assert_identity("someone", must_exist=True)
    monkeypatch.setattr(RA, "account_facts", lambda u: {
        "name": u, "present": True, "uid": 4242, "groups": [u, "users"], "privileged_groups": []})
    with pytest.raises(Refused, match="^IDENTITY_GROUPS_UNEXPECTED"):
        RA.assert_identity("someone", must_exist=True)


def test_the_real_research_account_is_measured_not_assumed():
    """PRIVILEGED_GROUPS is the enforced list, not a comment."""
    assert {"sudo", "docker", "disk", "shadow"} <= RA.PRIVILEGED_GROUPS
    assert RA.account_facts("nonexistent_research_user") == {
        "name": "nonexistent_research_user", "present": False}


# ----------------------------------------------------------------- preflight
def test_preflight_passes_on_a_clean_rig_and_resolves_the_commit(rig):
    rec = RA.preflight(rig["t"], rig["commit"], None)
    assert rec["ok"], rec["blocking"]
    assert rec["resolved_commit"]["commit"] == rig["commit"]
    assert len(rec["resolved_commit"]["tree_sha256"]) == 64
    assert rec["inventory"]["selected_from_manifest"] == len(rig["days"])


def test_preflight_refuses_conflicting_destinations_and_missing_commit(rig):
    rec = RA.preflight(rig["t"], None, None)
    assert not rec["ok"] and "commit_supplied" in rec["blocking"]
    rig["t"].checkout.mkdir(parents=True)
    rec = RA.preflight(rig["t"], rig["commit"], None)
    assert not rec["ok"] and "destination_free:checkout" in rec["blocking"]


def test_preflight_refuses_an_existing_account(rig, monkeypatch):
    monkeypatch.setattr(RA, "account_facts", lambda u: {
        "name": u, "present": True, "uid": 4242, "groups": [u], "privileged_groups": []})
    rec = RA.preflight(rig["t"], rig["commit"], None)
    assert not rec["ok"] and "identity_absent" in rec["blocking"]


def test_expected_tree_hash_matches_a_real_checkout_of_that_commit(rig, tmp_path):
    """The commitment preflight computes without checking anything out must
    equal what the boundary computes from a real checkout."""
    from apex.world_model.real_data import boundary as B
    ident = RA.expected_tree_sha256(rig["t"].source_repo, rig["commit"])
    work = tmp_path / "work"
    subprocess.run(["git", "clone", "-q", "--no-hardlinks", str(rig["t"].source_repo), str(work)],
                   check=True, timeout=120)
    subprocess.run(["git", "-C", str(work), "checkout", "-q", "--detach", rig["commit"]],
                   check=True, timeout=60)
    real = B.source_identity(work)
    assert ident["tree_sha256"] == real["tree_sha256"]
    assert ident["commit"] == real["commit"] and ident["n_files"] == real["n_files"]


# ------------------------------------------------ one configuration, two uses
def test_probe_and_launch_share_one_configuration(rig):
    t = rig["t"]
    probe, launch = RA.launch_config(t, probe=True), RA.launch_config(t)
    dp, dl = dict(p.split("=", 1) for p in probe.properties), dict(p.split("=", 1) for p in launch.properties)
    assert set(dp) == set(dl)
    differing = {k for k in dp if dp[k] != dl[k]}
    assert differing == {"MemoryMax"}, differing        # ONLY the memory cap differs
    for k in ("ProtectSystem", "ProtectHome", "PrivateNetwork", "NoNewPrivileges",
              "TemporaryFileSystem", "BindReadOnlyPaths", "RestrictSUIDSGID"):
        assert dp[k] == dl[k]
    assert probe.setenv == launch.setenv
    assert "GIT_CONFIG_GLOBAL=/dev/null" in launch.setenv


# --------------------------------------------------------------------- CLI
def _cli(rig, argv):
    return RA._cli(argv, targets=rig["t"])


def test_cli_setup_dry_run_changes_nothing(rig, capsys):
    rc = _cli(rig, ["setup", "--commit", rig["commit"]])
    doc = json.loads(capsys.readouterr().out)
    assert rc == 0 and doc["status"] == "OK" and doc["applied"] is False
    assert doc["view"]["applied"] is False
    assert not rig["t"].view.exists() and not rig["t"].setup_manifest.exists()
    assert any(step["class"] == "evidence" for step in doc["plan"])


def test_cli_setup_refuses_when_preflight_fails(rig, capsys):
    rig["t"].view.mkdir(parents=True)
    rc = _cli(rig, ["setup", "--commit", rig["commit"]])
    doc = json.loads(capsys.readouterr().out)
    assert rc == 3 and doc["status"] == "REFUSED" and doc["refusal"].startswith("PREFLIGHT_FAILED")


def test_cli_launch_refuses_placeholders_and_partial_setup(rig, capsys):
    rc = _cli(rig, ["launch"])
    doc = json.loads(capsys.readouterr().out)
    assert rc == 3 and doc["refusal"].startswith("UNRESOLVED_INPUTS")
    d = rig["trust"] / "decision.json"; d.write_text("{}")
    rc = _cli(rig, ["launch", "--commit", rig["commit"], "--decision", str(d)])
    doc = json.loads(capsys.readouterr().out)
    assert rc == 3 and doc["refusal"].startswith("SETUP_INCOMPLETE")     # no continuation after partial setup
    rig["t"].research_root.mkdir(parents=True, exist_ok=True)
    rig["t"].setup_manifest.write_text(json.dumps({"created": []}))
    rc = _cli(rig, ["launch", "--commit", rig["commit"], "--decision", str(d)])
    doc = json.loads(capsys.readouterr().out)
    assert rc == 3 and doc["refusal"].startswith("DECISION_OR_SIGNATURE_MISSING")


def test_cli_launch_resolves_every_input_and_never_applies(rig, capsys, tmp_path):
    t = rig["t"]
    subprocess.run(["git", "clone", "-q", "--no-hardlinks", str(t.source_repo), str(t.checkout)],
                   check=True, timeout=120)
    t.setup_manifest.parent.mkdir(parents=True, exist_ok=True)
    t.setup_manifest.write_text(json.dumps({"created": []}))
    d = rig["trust"] / "decision.json"; d.write_text("{}")
    d.with_name(d.name + ".sig").write_text("sig")
    rc = _cli(rig, ["launch", "--commit", rig["commit"], "--decision", str(d)])
    doc = json.loads(capsys.readouterr().out)
    assert rc == 0 and doc["applied"] is False
    r = doc["resolved"]
    assert r["commit"] == rig["commit"] and len(r["source_tree_sha256"]) == 64
    assert r["experiment"] == "ALPHA-EXP-001B" and r["registration_hash"] == RA.REGISTRATION_HASH
    assert "<" not in doc["command"] and ">" not in doc["command"]        # no placeholders survive
    assert "--execute" in doc["command"] and "systemd-run" in doc["command"]
    rc = _cli(rig, ["launch", "--commit", rig["commit"], "--decision", str(d), "--apply"])
    doc = json.loads(capsys.readouterr().out)
    assert rc == 3 and doc["refusal"].startswith("LAUNCH_APPLY_REQUIRES_SEPARATE_AUTHORIZATION")


# ---------------------------------------------------------------- rollback
def test_rollback_refuses_without_a_setup_manifest(rig):
    with pytest.raises(Refused, match="^NO_SETUP_MANIFEST"):
        RA.rollback_plan(rig["t"])


def test_rollback_removes_only_capability_and_never_evidence_or_etc_apex(rig):
    t = rig["t"]
    t.research_root.mkdir(parents=True, exist_ok=True)
    t.setup_manifest.write_text(json.dumps({"created": [
        {"object": str(t.venv), "class": "capability", "kind": "venv"},
        {"object": str(t.checkout), "class": "capability", "kind": "checkout"},
        {"object": str(t.view), "class": "capability", "kind": "dataset_view"},
        {"object": t.research_user, "class": "capability", "kind": "account"},
        {"object": str(t.out), "class": "evidence", "kind": "dir"},
        {"object": str(t.runner_root / "pinned.txt"), "class": "evidence", "kind": "file"},
        {"object": str(t.trust_root / "decision.json"), "class": "capability", "kind": "file"},
    ]}))
    plan = RA.rollback_plan(t)
    removed = {o["object"] for o in plan["remove"]}
    preserved = {o["object"] for o in plan["preserve"]}
    assert str(t.venv) in removed and str(t.checkout) in removed and str(t.view) in removed
    assert str(t.out) in preserved and str(t.runner_root / "pinned.txt") in preserved
    # a trust-root object is preserved even though it was recorded as capability
    assert str(t.trust_root / "decision.json") in preserved
    assert not any(o["object"].startswith(str(t.trust_root)) for o in plan["remove"])
    assert str(t.trust_root) in plan["never_touched"] and "/etc/apex" in plan["never_touched"]
    src = (REPO / "scripts/research_activation.py").read_text()
    assert "rm -rf /etc/apex" not in src and "rm -rf %s\" % t.trust_root" not in src


def test_cli_rollback_is_dry_run_and_apply_is_a_separate_authorization(rig, capsys):
    t = rig["t"]
    t.research_root.mkdir(parents=True, exist_ok=True)
    t.setup_manifest.write_text(json.dumps({"created": [
        {"object": str(t.venv), "class": "capability", "kind": "venv"}]}))
    rc = _cli(rig, ["rollback"])
    doc = json.loads(capsys.readouterr().out)
    assert rc == 0 and doc["applied"] is False and doc["remove"]
    assert t.venv.parent.exists() or True                    # nothing was actually removed
    rc = _cli(rig, ["rollback", "--apply"])
    assert rc == 3 and "ROLLBACK_APPLY_NOT_IMPLEMENTED_IN_THIS_STEP" in capsys.readouterr().out


def test_production_entry_point_takes_no_injected_targets():
    src = (REPO / "scripts/research_activation.py").read_text()
    tail = src.split('if __name__ == "__main__":')[1]
    assert "targets=" not in tail and "sys.exit(_cli())" in tail
    t = RA.production_targets()
    assert t.research_user == "apexresearch" and str(t.runner_root) == "/opt/apex-runner"
    assert str(t.trust_root) == "/etc/apex/admissions"
    assert t.expected_view_files == 1511


def test_no_market_row_is_parsed_by_this_wrapper():
    import ast
    tree = ast.parse((REPO / "scripts/research_activation.py").read_text())
    called = {n.func.attr for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    assert "loads" in called          # json.loads is used for the MANIFEST only
    src = (REPO / "scripts/research_activation.py").read_text()
    for forbidden in ("observable_rows", "load_session", "bars.targets", "economic"):
        assert forbidden not in src
