#!/usr/bin/env python3
"""Reproduce the reviewer's finding against the wrapper AS COMMITTED at 87948c1.

Four claims, each exercised through the committed code with disposable
fixtures: setup records objects it never created, verify passes with no
account or environment, probe never runs anything, and rollback schedules
directories that contain preserved evidence.

This is a REPRODUCTION of a defect in scripts/research_activation.py. It is
NOT the sandbox probe from results/si004_sandbox_probe.json -- that probe
executed a real systemd-run and remains valid evidence for the launch
configuration it tested. The two must not be confused.

    python scripts/si006_reproduce_wrapper_gaps.py <out.json> <path-to-87948c1-wrapper>
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

findings = []


def rec(n, claim, reproduced, evidence):
    findings.append({"finding": n, "claim": claim,
                     "status": "REPRODUCED" if reproduced else "NOT_REPRODUCED",
                     "evidence": evidence})


def load(path: str):
    spec = importlib.util.spec_from_file_location("committed_wrapper", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["committed_wrapper"] = mod
    spec.loader.exec_module(mod)
    return mod


def _git(repo, *args):
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def fixture(RA, tmp: Path):
    corpus = tmp / "corpus" / "bars"; corpus.mkdir(parents=True)
    files, days = {}, [f"2019-06-{d:02d}" for d in range(3, 8)]
    for d in days:
        p = corpus / f"SPY_{d}.json"
        p.write_text(json.dumps({"bars": [{"t": d}]}))
        files[p.name] = {"sha256": RA.sha256_of(p), "size": p.stat().st_size,
                         "symbol": "SPY", "session_date": d}
    man = tmp / "manifest.json"
    man.write_text(json.dumps({"dataset_id": "f", "root": str(corpus), "files": files}))
    src = tmp / "srcrepo"; (src / "apex" / "world_model").mkdir(parents=True)
    (src / "apex" / "world_model" / "x.py").write_text("X = 1\n")
    (src / "scripts").mkdir(); (src / "scripts" / "alpha_exp_real_execute.py").write_text("#\n")
    _git(src, "init", "-q"); _git(src, "config", "user.email", "t@t"); _git(src, "config", "user.name", "t")
    _git(src, "add", "-A"); _git(src, "commit", "-q", "-m", "b")
    trust = tmp / "trust"; (trust / "trust").mkdir(parents=True)
    t = RA.Targets(research_user="nonexistent_research_user", runner_root=tmp / "runner",
                   research_root=tmp / "research", source_repo=src, corpus_root=corpus,
                   manifest_path=man, trust_root=trust,
                   allowed_signers=trust / "trust" / "allowed_signers",
                   expected_view_files=len(days))
    return t, _git(src, "rev-parse", "HEAD")


def main(out_path: str, wrapper_path: str) -> int:
    RA = load(wrapper_path)
    src_text = Path(wrapper_path).read_text()

    # ---- F1: setup --apply records objects it never created ----------
    tmp = Path(tempfile.mkdtemp(prefix="si006_f1_"))
    t, commit = fixture(RA, tmp)
    rc = RA._cli(["setup", "--commit", commit, "--apply", "--json", str(tmp / "out.json")], targets=t)
    doc = json.loads((tmp / "out.json").read_text())
    created = doc.get("created") or []
    exists = {"venv": t.venv.exists(), "checkout": t.checkout.exists(),
              "runner_root": t.runner_root.exists(), "account_recorded": any(
                  o.get("kind") == "account" for o in created),
              "dataset_view": t.view.exists(), "setup_manifest": t.setup_manifest.exists()}
    rec(1, "setup --apply records planned objects as created without executing their creation",
        rc == 0 and doc.get("applied") is True and len(created) >= 10
        and not exists["venv"] and not exists["checkout"],
        {"exit_code": rc, "applied": doc.get("applied"), "objects_recorded_as_created": len(created),
         "actually_exists": exists,
         "note": "created is assigned the PLAN verbatim: only the dataset view is built"})

    # ---- F2: verify passes with no account, environment or checkout ---
    rc2 = RA._cli(["verify"], targets=t)
    rec(2, "verify succeeds with an absent account, environment and checkout",
        rc2 == 0 and not t.venv.exists() and not t.checkout.exists(),
        {"exit_code": rc2, "account_present": RA.account_facts(t.research_user)["present"],
         "venv_exists": t.venv.exists(), "checkout_exists": t.checkout.exists(),
         "note": "verify returns the configuration and the account facts; it asserts nothing"})

    # ---- F3: probe executes nothing --------------------------------
    calls = []
    real_run = RA.subprocess.run
    RA.subprocess.run = lambda *a, **k: (calls.append(a[0] if a else k.get("args")), real_run(*a, **k))[1]
    try:
        rc3 = RA._cli(["probe"], targets=t)
    finally:
        RA.subprocess.run = real_run
    ran_systemd = [c for c in calls if c and "systemd-run" in " ".join(map(str, c))]
    rec(3, "probe does not execute its checks",
        rc3 == 0 and not ran_systemd,
        {"exit_code": rc3, "subprocess_calls_during_probe": len(calls),
         "systemd_run_invocations": len(ran_systemd),
         "note": "probe prints config_properties; no sandbox is entered and nothing is measured"})

    # ---- F4: rollback schedules evidence-containing parents -----------
    tmp4 = Path(tempfile.mkdtemp(prefix="si006_f4_"))
    t4, _ = fixture(RA, tmp4)
    t4.research_root.mkdir(parents=True, exist_ok=True)
    t4.setup_manifest.write_text(json.dumps({"created": [
        {"object": str(t4.research_root), "class": "capability", "kind": "dir"},
        {"object": str(t4.out), "class": "evidence", "kind": "dir"},
        {"object": str(t4.setup_manifest), "class": "evidence", "kind": "file"},
        {"object": str(t4.runner_root), "class": "capability", "kind": "dir"},
        {"object": str(t4.runner_root / "pinned.txt"), "class": "evidence", "kind": "file"},
    ]}))
    plan = RA.rollback_plan(t4)
    removes = [o["object"] for o in plan["remove"]]
    preserves = [o["object"] for o in plan["preserve"]]
    conflicts = []
    for r in removes:
        for p in preserves:
            if p != r and p.startswith(r.rstrip("/") + "/"):
                conflicts.append({"removable_parent": r, "preserved_child": p})
    rec(4, "rollback schedules directories that contain preserved evidence",
        bool(conflicts),
        {"remove": removes, "preserve": preserves, "parent_child_conflicts": conflicts,
         "note": "recursive removal of the parent would erase the evidence the plan claims to preserve"})

    # ---- corroborating source facts (not a substitute for the runs) ---
    src_facts = {
        "setup_assigns_plan_to_created": '"created": plan if a.apply else []' in src_text,
        "setup_plan_returns_command_strings": '"cmd":' in src_text,
        "no_subprocess_run_in_setup_path": "subprocess.run" in src_text and "adduser" not in src_text.split("def setup_plan")[0],
        "rollback_apply_unimplemented": "ROLLBACK_APPLY_NOT_IMPLEMENTED_IN_THIS_STEP" in src_text,
        "launch_checks_manifest_existence_only": "SETUP_INCOMPLETE" in src_text and '"state"' not in src_text,
    }

    result = {"produced_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
              "wrapper_under_test": wrapper_path,
              "what_this_is": "reproduction of a DESCRIBE-BUT-DO-NOT-DO defect in the wrapper",
              "what_this_is_not": "the systemd sandbox probe in results/si004_sandbox_probe.json, which "
                                  "executed real containment checks and remains valid for the launch "
                                  "configuration it tested",
              "findings": findings, "source_facts": src_facts,
              "summary": {"reproduced": sum(f["status"] == "REPRODUCED" for f in findings),
                          "not_reproduced": sum(f["status"] == "NOT_REPRODUCED" for f in findings)}}
    Path(out_path).write_text(json.dumps(result, indent=1, default=str))
    print(json.dumps({f["finding"]: f["status"] for f in findings}))
    print(json.dumps(result["summary"]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
