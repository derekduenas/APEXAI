#!/usr/bin/env python3
"""RESEARCH_ACTIVATION_V0 -- fail-stop wrapper for the isolated research runner.

Every check ABORTS. Nothing here prints an expectation and continues: a
mismatched hash, a missing or extra file, a conflicting destination, an
unexpected identity or a partial setup all raise and exit non-zero, and the
launch refuses to start unless a complete, verified setup manifest exists.

    research_activation.py preflight            # read-only; resolves and checks targets
    research_activation.py setup   [--apply]    # dry-run by default
    research_activation.py verify               # identity + sandbox, after setup
    research_activation.py probe                # sandbox probe, SAME config as launch
    research_activation.py launch  --decision P [--apply]
    research_activation.py rollback [--apply]   # setup-owned capability only

WHAT THIS DOES NOT DO
It never signs, never issues an admission, never unseals evaluation, and
never removes evidence. `setup` copies historical bytes into a restricted
view -- that IS data movement, and it is stated as such -- but it performs
no statistical parsing and runs no experiment.
"""
from __future__ import annotations

import argparse
import grp
import hashlib
import json
import os
import pwd
import shutil
import subprocess
import sys
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path

ACTIVATION_VERSION = "RESEARCH_ACTIVATION_V0"
EXPERIMENT_ID = "ALPHA-EXP-001B"
REGISTRATION_HASH = "b3930727334f24379f72df3919c98d689448b2f3f265b2fa6013559ee1bef5c9"
MANIFEST_SHA256 = "3ac8b250eefb47c5f66c7217508e1080f5f86ae5e4a63c20062a4e931a424c39"
SCOPE_SYMBOL = "SPY"
SCOPE_START, SCOPE_END = "2016-01-04", "2021-12-31"
EXPECTED_VIEW_FILES = 1511
REQUIREMENTS = ("numpy==2.4.6",)
BOUND_SOURCE_PATHS = ("apex/world_model", "apex/governance/chain_ledger.py",
                      "apex/intraday/sessions.py", "scripts/alpha_exp_real_execute.py")
PRIVILEGED_GROUPS = {"root", "sudo", "admin", "wheel", "adm", "shadow", "disk",
                     "docker", "lxd", "kvm", "systemd-journal", "staff"}


class ActivationRefused(Exception):
    """A precondition failed. Nothing proceeds; the caller exits non-zero."""


# --------------------------------------------------------------- targets
@dataclass(frozen=True)
class Targets:
    """Every path and identity this activation owns. Production builds one
    from constants; tests build their own. No field can turn a refusal into
    a pass -- they relocate the targets, they do not weaken the checks."""
    research_user: str = "apexresearch"
    runner_root: Path = Path("/opt/apex-runner")
    research_root: Path = Path("/apex-data/research")
    source_repo: Path = Path("/opt/apex-repo")
    corpus_root: Path = Path("/apex-data/history-b/etf_continuous/bars")
    manifest_path: Path = Path("/apex-data/governance/admissions/manifests/etf_continuous_SPY_manifest_v0.json")
    trust_root: Path = Path("/etc/apex/admissions")
    allowed_signers: Path = Path("/etc/apex/admissions/trust/allowed_signers")
    slice_name: str = "wmresearch.slice"
    memory_max: str = "1400M"
    tasks_max: str = "64"
    expected_view_files: int = EXPECTED_VIEW_FILES

    @property
    def venv(self) -> Path: return self.runner_root / "venv"
    @property
    def python(self) -> Path: return self.venv / "bin" / "python"
    @property
    def checkout(self) -> Path: return self.research_root / "checkout"
    @property
    def view(self) -> Path: return self.research_root / "dataset_view"
    @property
    def view_bars(self) -> Path: return self.view / "etf_continuous" / "bars"
    @property
    def out(self) -> Path: return self.research_root / "out"
    @property
    def setup_manifest(self) -> Path: return self.research_root / "_ACTIVATION_MANIFEST.json"
    @property
    def archive(self) -> Path: return self.research_root / "_ROLLBACK_ARCHIVE"


def production_targets() -> Targets:
    return Targets()


# --------------------------------------------------------- small helpers
def sha256_of(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _git(repo: Path, *args, binary: bool = False):
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, timeout=120)
    if r.returncode != 0:
        raise ActivationRefused("GIT_FAILED: git %s in %s: %s"
                                % (" ".join(args), repo, r.stderr.decode()[:200]))
    return r.stdout if binary else r.stdout.decode()


def expected_tree_sha256(repo: Path, commit: str, paths=BOUND_SOURCE_PATHS) -> dict:
    """The source commitment a checkout of `commit` WOULD produce, computed
    from the repository without checking anything out. Mirrors
    boundary.source_identity's algorithm: sha256 per tracked file under the
    bound paths, hashed over sorted 'relpath sha256' lines."""
    listing = _git(repo, "ls-tree", "-r", "--name-only", commit, "--", *paths)
    rels = sorted(l for l in listing.splitlines() if l)
    lines = ["%s %s" % (rel, hashlib.sha256(_git(repo, "show", "%s:%s" % (commit, rel),
                                                 binary=True)).hexdigest()) for rel in rels]
    return {"commit": _git(repo, "rev-parse", commit).strip(),
            "tree_sha256": hashlib.sha256("\n".join(lines).encode()).hexdigest(),
            "n_files": len(lines)}


def _no_symlink_in(path: Path, root: Path) -> None:
    """Refuse a symlink anywhere between root and path, and any escape."""
    rp = Path(os.path.realpath(path))
    if not (rp == root.resolve() or root.resolve() in rp.parents):
        raise ActivationRefused("PATH_ESCAPE: %s resolves to %s, outside %s" % (path, rp, root))
    cur = root
    for part in path.relative_to(root).parts:
        cur = cur / part
        if os.path.islink(cur):
            raise ActivationRefused("SYMLINK_REFUSED: %s is a symlink" % cur)


# ------------------------------------------------------------- inventory
def admitted_files(t: Targets) -> list:
    """The files to copy, selected from the COMMITTED MANIFEST -- never from
    a filename glob. A glob would silently follow whatever happens to be on
    disk; the manifest is what the admission decision commits to."""
    if not t.manifest_path.exists():
        raise ActivationRefused("MANIFEST_MISSING: %s" % t.manifest_path)
    actual = sha256_of(t.manifest_path)
    if t.manifest_path == Targets().manifest_path and actual != MANIFEST_SHA256:
        raise ActivationRefused("MANIFEST_HASH_MISMATCH: expected %s, found %s"
                                % (MANIFEST_SHA256[:16], actual[:16]))
    man = json.loads(t.manifest_path.read_text())
    root = Path(man["root"]).resolve()
    if root != t.corpus_root.resolve():
        raise ActivationRefused("MANIFEST_ROOT_MISMATCH: manifest says %s, target says %s"
                                % (root, t.corpus_root))
    sel = []
    for rel, rec in sorted(man["files"].items()):
        if rec.get("symbol") != SCOPE_SYMBOL:
            continue
        d = rec.get("session_date")
        if not (d and SCOPE_START <= d <= SCOPE_END):
            continue
        sel.append({"rel": rel, "sha256": rec["sha256"], "size": rec["size"],
                    "symbol": rec["symbol"], "session_date": d})
    if not sel:
        raise ActivationRefused("EMPTY_SELECTION: no manifest entry matches %s %s..%s"
                                % (SCOPE_SYMBOL, SCOPE_START, SCOPE_END))
    out_of_scope = [s for s in sel if not (SCOPE_START <= s["session_date"] <= SCOPE_END)]
    if out_of_scope:
        raise ActivationRefused("SCOPE_LEAK: %d selected entries outside the range" % len(out_of_scope))
    return sel


def build_view(t: Targets, files: list, *, apply: bool) -> dict:
    """Copy into FRESH staging, verify every hash, reconcile the whole
    inventory. Any discrepancy aborts and the staging directory is removed
    so a partial view can never be mistaken for a complete one."""
    if t.view.exists():
        raise ActivationRefused("DESTINATION_EXISTS: %s already exists; refusing to merge into it" % t.view)
    if not apply:
        return {"planned_files": len(files), "destination": str(t.view_bars), "applied": False}
    staging = t.view.with_name(t.view.name + ".staging")
    if staging.exists():
        raise ActivationRefused("DESTINATION_EXISTS: %s" % staging)
    names = [Path(f["rel"]).name for f in files]
    if len(set(names)) != len(names):
        dupes = sorted({n for n in names if names.count(n) > 1})
        raise ActivationRefused("INVENTORY_DUPLICATE: %d duplicated name(s): %s" % (len(dupes), dupes[:3]))
    bars = staging / "etf_continuous" / "bars"
    bars.mkdir(parents=True)
    copied = 0
    try:
        for f in files:
            src = t.corpus_root / f["rel"]
            _no_symlink_in(src, t.corpus_root)
            if not src.is_file():
                raise ActivationRefused("SOURCE_MISSING: %s" % src)
            if sha256_of(src) != f["sha256"]:
                raise ActivationRefused("SOURCE_HASH_MISMATCH: %s" % f["rel"])
            dst = bars / Path(f["rel"]).name
            shutil.copy2(src, dst)
            if sha256_of(dst) != f["sha256"]:
                raise ActivationRefused("COPY_HASH_MISMATCH: %s" % f["rel"])
            copied += 1
        present = sorted(p.name for p in bars.iterdir())
        expected = sorted(Path(f["rel"]).name for f in files)
        missing, extra = sorted(set(expected) - set(present)), sorted(set(present) - set(expected))
        if missing or extra:
            raise ActivationRefused("INVENTORY_MISMATCH: %d missing, %d extra" % (len(missing), len(extra)))
        if len(present) != t.expected_view_files:
            raise ActivationRefused("INVENTORY_COUNT: %d files, expected %d"
                                    % (len(present), t.expected_view_files))
        if any(os.path.islink(bars / n) for n in present):
            raise ActivationRefused("SYMLINK_IN_VIEW")
        staging.rename(t.view)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return {"applied": True, "files": copied, "destination": str(t.view_bars),
            "first": expected[0], "last": expected[-1]}


# -------------------------------------------------------------- identity
def account_facts(user: str) -> dict:
    try:
        pw = pwd.getpwnam(user)
    except KeyError:
        return {"name": user, "present": False}
    groups = sorted({g.gr_name for g in grp.getgrall() if user in g.gr_mem}
                    | {grp.getgrgid(pw.pw_gid).gr_name})
    return {"name": user, "present": True, "uid": pw.pw_uid, "gid": pw.pw_gid,
            "shell": pw.pw_shell, "home": pw.pw_dir, "groups": groups,
            "privileged_groups": sorted(set(groups) & PRIVILEGED_GROUPS)}


def assert_identity(user: str, *, must_exist: bool) -> dict:
    a = account_facts(user)
    if must_exist and not a["present"]:
        raise ActivationRefused("IDENTITY_MISSING: %s does not exist" % user)
    if not must_exist and a["present"]:
        raise ActivationRefused("IDENTITY_CONFLICT: %s already exists (uid %s, groups %s); refusing "
                                "to reuse or modify an existing account" % (user, a["uid"], a["groups"]))
    if a["present"]:
        if a["privileged_groups"]:
            raise ActivationRefused("IDENTITY_PRIVILEGED: %s is in %s; the research identity must hold "
                                    "no privileged group" % (user, a["privileged_groups"]))
        if a["groups"] != [user]:
            raise ActivationRefused("IDENTITY_GROUPS_UNEXPECTED: %s is in %s; expected only %r"
                                    % (user, a["groups"], user))
    return a


# ---------------------------------------------------- launch configuration
@dataclass(frozen=True)
class LaunchConfig:
    """ONE configuration, used by BOTH the probe and the real launch. If the
    probe and the launch could differ, the probe would prove nothing."""
    targets: Targets
    view_bars: Path
    properties: tuple
    setenv: tuple

    def systemd_args(self) -> list:
        a = []
        for p in self.properties:
            a += ["-p", p]
        for e in self.setenv:
            a += ["--setenv=" + e]
        return a


def launch_config(t: Targets, *, view_bars: Path | None = None, probe: bool = False) -> LaunchConfig:
    vb = view_bars or t.view_bars
    props = (
        "User=%s" % t.research_user, "Group=%s" % t.research_user,
        "MemoryMax=%s" % ("512M" if probe else t.memory_max), "TasksMax=%s" % t.tasks_max,
        "ProtectSystem=strict", "ProtectHome=yes", "PrivateTmp=yes",
        "PrivateNetwork=yes", "NoNewPrivileges=yes", "RestrictSUIDSGID=yes",
        "TemporaryFileSystem=%s" % t.corpus_root.parent.parent,          # /apex-data/history-b
        "BindReadOnlyPaths=%s:%s" % (vb, t.corpus_root),
        "InaccessiblePaths=/apex-data/core", "InaccessiblePaths=/apex-data/history-a",
        "InaccessiblePaths=/apex-data/runtime",
        "ReadOnlyPaths=%s" % t.manifest_path.parent.parent,              # governance
        "ReadOnlyPaths=%s" % t.trust_root,
        "ReadWritePaths=%s" % t.out,
    )
    env = ("GIT_CONFIG_GLOBAL=/dev/null", "GIT_CONFIG_NOSYSTEM=1",
           "PYTHONPATH=%s" % t.checkout)
    return LaunchConfig(targets=t, view_bars=vb, properties=props, setenv=env)


# -------------------------------------------------------------- preflight
def preflight(t: Targets, commit: str | None, decision: Path | None) -> dict:
    """Resolve every target and refuse conflicts. Read-only."""
    rec = {"contract": ACTIVATION_VERSION, "utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "targets": {k: str(v) for k, v in (("research_user", t.research_user), ("runner_root", t.runner_root),
                                              ("venv", t.venv), ("checkout", t.checkout), ("view", t.view),
                                              ("out", t.out), ("trust_root", t.trust_root),
                                              ("allowed_signers", t.allowed_signers))},
           "requirements": list(REQUIREMENTS), "checks": [], "blocking": []}

    def chk(name, ok, detail, blocking=True):
        rec["checks"].append({"check": name, "ok": bool(ok), "detail": detail})
        if not ok and blocking:
            rec["blocking"].append(name)

    a = account_facts(t.research_user)
    chk("identity_absent", not a["present"],
        "exists already: %s" % a if a["present"] else "%s does not exist yet" % t.research_user)
    for label, p in (("runner_root", t.runner_root), ("research_root", t.research_root),
                     ("checkout", t.checkout), ("view", t.view)):
        chk("destination_free:%s" % label, not p.exists(),
            "EXISTS (refusing to reuse)" if p.exists() else "free")
    chk("source_repo", t.source_repo.is_dir(), str(t.source_repo))
    chk("corpus_readable", os.access(t.corpus_root, os.R_OK), str(t.corpus_root))
    chk("manifest_present", t.manifest_path.exists(), str(t.manifest_path))
    if t.manifest_path.exists():
        observed = sha256_of(t.manifest_path)
        production = t.manifest_path == Targets().manifest_path
        # the committed hash pins the PRODUCTION manifest; a relocated manifest
        # (tests, a staged copy) is recorded, not silently accepted as that one
        chk("manifest_hash", (observed == MANIFEST_SHA256) if production else True,
            "%s%s" % (observed[:16], "" if production else " (non-production manifest: recorded, not pinned)"))
    chk("trust_root_present", t.trust_root.exists(),
        "%s (created by setup step A4)" % t.trust_root, blocking=False)
    chk("allowed_signers_present", t.allowed_signers.exists(),
        "%s (installed by the admission authority)" % t.allowed_signers, blocking=False)

    if t.manifest_path.exists():
        try:
            sel = admitted_files(t)
            rec["inventory"] = {"selected_from_manifest": len(sel), "expected": t.expected_view_files,
                                "first": sel[0]["session_date"], "last": sel[-1]["session_date"],
                                "symbol": SCOPE_SYMBOL, "range": [SCOPE_START, SCOPE_END]}
            chk("inventory_count", len(sel) == t.expected_view_files,
                "%d selected, expected %d" % (len(sel), t.expected_view_files))
            chk("inventory_in_scope", sel[0]["session_date"] >= SCOPE_START and sel[-1]["session_date"] <= SCOPE_END,
                "%s..%s" % (sel[0]["session_date"], sel[-1]["session_date"]))
        except ActivationRefused as e:
            chk("inventory", False, str(e))

    if commit:
        try:
            ident = expected_tree_sha256(t.source_repo, commit)
            rec["resolved_commit"] = ident
            chk("commit_resolves", True, ident["commit"])
        except ActivationRefused as e:
            chk("commit_resolves", False, str(e))
    else:
        chk("commit_supplied", False, "--commit is required: an executable package carries no placeholder")

    if decision is not None:
        d = Path(decision)
        chk("decision_present", d.exists(), str(d))
        chk("decision_under_trust_root", str(d.resolve()).startswith(str(t.trust_root.resolve())),
            str(t.trust_root))
        chk("decision_signature_present", d.with_name(d.name + ".sig").exists(), str(d) + ".sig")
    rec["ok"] = not rec["blocking"]
    return rec


# ------------------------------------------------------------ setup plan
def setup_plan(t: Targets, commit: str, ident: dict) -> list:
    """The exact commands, and the object each one creates. Every object is
    classified: capability objects are removable by rollback, evidence
    objects are never removed."""
    return [
        {"object": str(t.runner_root), "class": "capability", "kind": "dir",
         "cmd": "install -d -o root -g root -m 0755 %s" % t.runner_root},
        {"object": str(t.venv), "class": "capability", "kind": "venv",
         "cmd": "/usr/bin/python3.12 -m venv %s" % t.venv},
        {"object": str(t.runner_root / "requirements.txt"), "class": "capability", "kind": "file",
         "cmd": "printf '%%s\\n' %s > %s" % (" ".join(REQUIREMENTS), t.runner_root / "requirements.txt")},
        {"object": str(t.venv) + " [packages]", "class": "capability", "kind": "packages",
         "cmd": "%s/bin/pip install --no-cache-dir -r %s" % (t.venv, t.runner_root / "requirements.txt")},
        {"object": str(t.runner_root / "pinned.txt"), "class": "evidence", "kind": "file",
         "cmd": "%s/bin/pip freeze > %s" % (t.venv, t.runner_root / "pinned.txt")},
        {"object": str(t.runner_root), "class": "capability", "kind": "own",
         "cmd": "chown -R root:root %s && chmod -R go-w %s" % (t.runner_root, t.runner_root)},
        {"object": t.research_user, "class": "capability", "kind": "account",
         "cmd": "adduser --system --group --disabled-password --shell /usr/sbin/nologin "
                "--home /home/%s %s && passwd -l %s" % (t.research_user, t.research_user, t.research_user)},
        {"object": str(t.research_root), "class": "capability", "kind": "dir",
         "cmd": "install -d -o %s -g %s -m 0755 %s" % (t.research_user, t.research_user, t.research_root)},
        {"object": str(t.out), "class": "evidence", "kind": "dir",
         "cmd": "install -d -o %s -g %s -m 0755 %s" % (t.research_user, t.research_user, t.out)},
        {"object": str(t.checkout), "class": "capability", "kind": "checkout",
         "cmd": "git clone --no-hardlinks %s %s && git -C %s checkout --detach %s && "
                "chown -R %s:%s %s" % (t.source_repo, t.checkout, t.checkout, ident["commit"],
                                       t.research_user, t.research_user, t.checkout)},
        {"object": str(t.view), "class": "capability", "kind": "dataset_view",
         "cmd": "research_activation.py setup --apply  (builds the view from the manifest, "
                "verifies %d hashes, reconciles the inventory)" % t.expected_view_files},
        {"object": str(t.setup_manifest), "class": "evidence", "kind": "file",
         "cmd": "written by this wrapper at the end of setup"},
    ]


def write_setup_manifest(t: Targets, rec: dict) -> Path:
    t.setup_manifest.parent.mkdir(parents=True, exist_ok=True)
    with open(t.setup_manifest, "x") as fh:                 # O_EXCL: never overwrite a record
        json.dump(rec, fh, indent=1, sort_keys=True, default=str)
    return t.setup_manifest


# --------------------------------------------------------------- rollback
def rollback_plan(t: Targets) -> dict:
    """Only objects THIS activation recorded creating, and only those
    classed as capability. Evidence is never removed, and nothing outside
    the recorded set is touched -- in particular /etc/apex is never removed
    recursively: it holds signed decisions, signatures and trust material
    that this activation did not create."""
    if not t.setup_manifest.exists():
        raise ActivationRefused("NO_SETUP_MANIFEST: %s absent; rollback refuses to guess what it owns"
                                % t.setup_manifest)
    rec = json.loads(t.setup_manifest.read_text())
    created = rec.get("created") or []
    remove, preserve = [], []
    for o in created:
        (remove if o.get("class") == "capability" else preserve).append(o)
    for guard in (str(t.trust_root), "/etc", "/etc/apex", str(t.out), str(t.setup_manifest)):
        for o in list(remove):
            if o["object"] == guard or o["object"].startswith(guard.rstrip("/") + "/"):
                remove.remove(o)
                preserve.append({**o, "why_preserved": "PROTECTED_PATH: %s" % guard})
    return {"remove": remove, "preserve": preserve,
            "never_touched": [str(t.trust_root), "/etc/apex", str(t.out), str(t.setup_manifest)],
            "archive": str(t.archive),
            "law": "disable capability, preserve evidence; signed decisions, signatures, trust "
                   "fingerprints, setup records and run outputs are never removed"}


def _cli(argv=None, *, targets: Targets | None = None) -> int:
    ap = argparse.ArgumentParser(prog="research_activation.py")
    ap.add_argument("action", choices=["preflight", "setup", "verify", "probe", "launch", "rollback"])
    ap.add_argument("--commit", default=None)
    ap.add_argument("--decision", default=None)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--json", default=None)
    a = ap.parse_args(argv)
    t = targets or production_targets()

    try:
        if a.action == "preflight":
            rec = preflight(t, a.commit, Path(a.decision) if a.decision else None)
        elif a.action == "setup":
            rec = preflight(t, a.commit, None)
            if not rec["ok"]:
                raise ActivationRefused("PREFLIGHT_FAILED: %s" % ", ".join(rec["blocking"]))
            ident = rec["resolved_commit"]
            assert_identity(t.research_user, must_exist=False)
            files = admitted_files(t)
            plan = setup_plan(t, ident["commit"], ident)
            rec = {**rec, "action": "setup", "applied": bool(a.apply), "plan": plan,
                   "view": build_view(t, files, apply=a.apply),
                   "created": plan if a.apply else []}
            if a.apply:
                write_setup_manifest(t, rec)
        elif a.action == "rollback":
            rec = {"action": "rollback", "applied": False, **rollback_plan(t)}
            if a.apply:
                raise ActivationRefused("ROLLBACK_APPLY_NOT_IMPLEMENTED_IN_THIS_STEP: the plan above is "
                                        "what would be removed; applying it is a separate authorization")
        elif a.action in ("probe", "verify"):
            cfg = launch_config(t, probe=(a.action == "probe"))
            rec = {"action": a.action, "config_properties": list(cfg.properties),
                   "config_setenv": list(cfg.setenv),
                   "account": account_facts(t.research_user),
                   "note": "account permissions and sandbox restrictions are different things; see "
                           "the activation package section 7"}
        else:                                                            # launch
            if not a.commit or not a.decision:
                raise ActivationRefused("UNRESOLVED_INPUTS: --commit and --decision are both required; "
                                        "an executable package carries no placeholders")
            if not t.setup_manifest.exists():
                raise ActivationRefused("SETUP_INCOMPLETE: %s absent; launch does not run after a partial "
                                        "or absent setup" % t.setup_manifest)
            d = Path(a.decision)
            if not d.exists() or not d.with_name(d.name + ".sig").exists():
                raise ActivationRefused("DECISION_OR_SIGNATURE_MISSING: %s" % d)
            ident = expected_tree_sha256(t.checkout, a.commit)
            cfg = launch_config(t)
            argv2 = ["systemd-run", "--pipe", "--wait", "--collect",
                     "--slice=%s" % t.slice_name, *cfg.systemd_args(),
                     "--working-directory=%s" % t.checkout, str(t.python),
                     "scripts/alpha_exp_real_execute.py", "--decision", str(d), "--execute"]
            rec = {"action": "launch", "applied": False, "resolved": {
                       "commit": ident["commit"], "source_tree_sha256": ident["tree_sha256"],
                       "interpreter": str(t.python), "decision": str(d),
                       "experiment": EXPERIMENT_ID, "registration_hash": REGISTRATION_HASH},
                   "command": " ".join(argv2)}
            if a.apply:
                raise ActivationRefused("LAUNCH_APPLY_REQUIRES_SEPARATE_AUTHORIZATION: authorization C is "
                                        "not granted by this wrapper")
    except ActivationRefused as e:
        print(json.dumps({"contract": ACTIVATION_VERSION, "action": a.action,
                          "status": "REFUSED", "refusal": str(e)}, indent=1))
        return 3
    out = json.dumps({"contract": ACTIVATION_VERSION, "status": "OK", **rec}, indent=1, default=str)
    if a.json:
        Path(a.json).write_text(out)
    print(out)
    return 0 if rec.get("ok", True) else 3


if __name__ == "__main__":
    sys.exit(_cli())
