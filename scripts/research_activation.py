#!/usr/bin/env python3
"""RESEARCH_ACTIVATION_V1 -- fail-stop wrapper that PERFORMS and VERIFIES.

V0 described actions instead of taking them: `setup --apply` recorded twelve
objects as created while only building the dataset view, `verify` returned a
configuration dump, and `probe` entered no sandbox. Reproduced in
results/si006_wrapper_reproductions.json. V1 executes every stage, records an
object only after its creation is verified, persists partial progress, and
fails non-zero when anything does not hold.

    research_activation.py preflight --commit C [--decision D]
    research_activation.py setup     --commit C [--apply]
    research_activation.py verify                       # real checks
    research_activation.py probe                        # enters the sandbox
    research_activation.py launch    --commit C --decision D [--apply]
    research_activation.py rollback  [--apply]

Separations kept: PREPARATION (preflight) · SETUP EXECUTION (setup) ·
ADMISSION (never here -- signing is off-host) · RESEARCH EXECUTION (launch).
Dry run is the default everywhere and mutates nothing.
"""
from __future__ import annotations

import argparse
import grp
import hashlib
import json
import os
import pwd
import shutil
import stat
import subprocess
import time
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

ACTIVATION_VERSION = "RESEARCH_ACTIVATION_V1"
EXPERIMENT_ID = "ALPHA-EXP-001B"
# must match apex.world_model.real_data.boundary.RESULT_FILE; a run that has
# not written this has not produced a result, whatever its exit code says
RESULT_FILE = "_RESULT.json"
RUN_FILE = "_RUN.json"
REGISTRATION_HASH = "b3930727334f24379f72df3919c98d689448b2f3f265b2fa6013559ee1bef5c9"
MANIFEST_SHA256 = "3ac8b250eefb47c5f66c7217508e1080f5f86ae5e4a63c20062a4e931a424c39"
SCOPE_SYMBOL, SCOPE_START, SCOPE_END = "SPY", "2016-01-04", "2021-12-31"
EXPECTED_VIEW_FILES = 1511
REQUIREMENTS = ("numpy==2.4.6",)
SYSTEM_PYTHON = "/usr/bin/python3.12"
BOUND_SOURCE_PATHS = ("apex/world_model", "apex/governance/chain_ledger.py",
                      "apex/intraday/sessions.py", "scripts/alpha_exp_real_execute.py")
PRIVILEGED_GROUPS = {"root", "sudo", "admin", "wheel", "adm", "shadow", "disk",
                     "docker", "lxd", "kvm", "systemd-journal", "staff"}
STATE_IN_PROGRESS, STATE_PARTIAL, STATE_COMPLETE = "IN_PROGRESS", "PARTIAL_FAILED", "COMPLETE"


class ActivationRefused(Exception):
    """A precondition or a verification failed. Nothing proceeds."""


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_of(p) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# --------------------------------------------------------------- targets
@dataclass(frozen=True)
class Targets:
    research_user: str = "apexresearch"
    runner_root: Path = Path("/opt/apex-runner")
    research_root: Path = Path("/apex-data/research")
    source_repo: Path = Path("/opt/apex-repo")
    corpus_root: Path = Path("/apex-data/history-b/etf_continuous/bars")
    manifest_path: Path = Path("/apex-data/governance/admissions/manifests/etf_continuous_SPY_manifest_v0.json")
    trust_root: Path = Path("/etc/apex/admissions")
    allowed_signers: Path = Path("/etc/apex/admissions/trust/allowed_signers")
    system_python: str = SYSTEM_PYTHON
    slice_name: str = "wmresearch.slice"
    memory_max: str = "1400M"
    tasks_max: str = "64"
    expected_view_files: int = EXPECTED_VIEW_FILES
    inaccessible: tuple = ("/apex-data/core", "/apex-data/history-a", "/apex-data/runtime")
    # The runner tree must be owned by someone the research account is not.
    # Production hardens it to root; a test harness running unprivileged
    # declares its own uid rather than the check being quietly relaxed.
    runner_owner_uid: int = 0
    # An unprivileged harness cannot hold two distinct uids, and its stand-in
    # `chown` is a no-op, so it cannot exercise ownership separation at all.
    # Saying so here is a declaration that travels into the evidence, rather
    # than a check that quietly passes. Production leaves this True.
    uid_separation_exercisable: bool = True

    @property
    def venv(self): return self.runner_root / "venv"
    @property
    def python(self): return self.venv / "bin" / "python"
    @property
    def pip(self): return self.venv / "bin" / "pip"
    @property
    def requirements(self): return self.runner_root / "requirements.txt"
    @property
    def pinned(self): return self.runner_root / "pinned.txt"
    @property
    def checkout(self): return self.research_root / "checkout"
    @property
    def view(self): return self.research_root / "dataset_view"
    @property
    def view_bars(self): return self.view / "etf_continuous" / "bars"
    @property
    def out(self): return self.research_root / "out"
    @property
    def setup_manifest(self): return self.research_root / "_ACTIVATION_MANIFEST.json"
    @property
    def log(self): return self.research_root / "_ACTIVATION_LOG.jsonl"


def production_targets() -> Targets:
    return Targets()


# ---------------------------------------------------------------- runner
class SystemRunner:
    """Performs the actions. Every command is an argv list -- no shell -- and
    a non-zero exit raises."""
    name = "system"

    def cmd(self, argv, *, timeout=1800, input_text=None) -> subprocess.CompletedProcess:
        argv = [str(x) for x in argv]
        try:
            r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, input=input_text)
        except (OSError, subprocess.SubprocessError) as e:
            raise ActivationRefused("COMMAND_FAILED: %s: %s" % (" ".join(argv[:3]), e)) from e
        if r.returncode != 0:
            raise ActivationRefused("COMMAND_FAILED: %s exited %d: %s"
                                    % (" ".join(argv[:3]), r.returncode,
                                       (r.stderr or r.stdout).strip()[:300]))
        return r

    def mkdir(self, path: Path, mode=0o755) -> None:
        try:
            path.mkdir(mode=mode, parents=False, exist_ok=False)
            os.chmod(path, mode)      # mkdir's mode is masked by umask; this is not
        except OSError as e:
            raise ActivationRefused("MKDIR_FAILED: %s: %s" % (path, e)) from e

    def write_text(self, path: Path, text: str, mode=0o644) -> None:
        try:
            with open(path, "x") as fh:
                fh.write(text)
            os.chmod(path, mode)
        except OSError as e:
            raise ActivationRefused("WRITE_FAILED: %s: %s" % (path, e)) from e

    def chown_tree(self, path: Path, user: str, group: str) -> None:
        self.cmd(["chown", "-R", "%s:%s" % (user, group), path])

    def chmod_go_w(self, path: Path) -> None:
        self.cmd(["chmod", "-R", "go-w", path])

    def copy(self, src: Path, dst: Path) -> None:
        shutil.copy2(src, dst)

    def run_child(self, argv, *, timeout) -> dict:
        """Run the experiment child and return what happened, without raising.

        `cmd` raises on non-zero and keeps 300 characters of stderr, which threw
        away the refusal that explained the failure. Nothing is discarded here."""
        argv = [str(x) for x in argv]
        try:
            r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired as e:
            return {"returncode": None, "timed_out": True,
                    "stdout": (e.stdout or b"").decode("utf-8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or ""),
                    "stderr": (e.stderr or b"").decode("utf-8", "replace") if isinstance(e.stderr, bytes) else (e.stderr or ""),
                    "spawn_error": None}
        except OSError as e:
            return {"returncode": None, "timed_out": False, "stdout": "", "stderr": "",
                    "spawn_error": "%s: %s" % (type(e).__name__, e)}
        return {"returncode": r.returncode, "timed_out": False,
                "stdout": r.stdout or "", "stderr": r.stderr or "", "spawn_error": None}


# ------------------------------------------------------------ inventory
def admitted_files(t: Targets) -> list:
    if not t.manifest_path.exists():
        raise ActivationRefused("MANIFEST_MISSING: %s" % t.manifest_path)
    actual = sha256_of(t.manifest_path)
    if t.manifest_path == Targets().manifest_path and actual != MANIFEST_SHA256:
        raise ActivationRefused("MANIFEST_HASH_MISMATCH: expected %s, found %s"
                                % (MANIFEST_SHA256[:16], actual[:16]))
    man = json.loads(t.manifest_path.read_text())
    if Path(man["root"]).resolve() != t.corpus_root.resolve():
        raise ActivationRefused("MANIFEST_ROOT_MISMATCH: %s vs %s" % (man["root"], t.corpus_root))
    sel = [{"rel": rel, "sha256": r["sha256"], "size": r["size"], "symbol": r["symbol"],
            "session_date": r["session_date"]}
           for rel, r in sorted(man["files"].items())
           if r.get("symbol") == SCOPE_SYMBOL and r.get("session_date")
           and SCOPE_START <= r["session_date"] <= SCOPE_END]
    if not sel:
        raise ActivationRefused("EMPTY_SELECTION: no manifest entry matches %s %s..%s"
                                % (SCOPE_SYMBOL, SCOPE_START, SCOPE_END))
    if any(not (SCOPE_START <= s["session_date"] <= SCOPE_END) for s in sel):
        raise ActivationRefused("SCOPE_LEAK")
    return sel


def out_of_scope_example(t: Targets) -> str | None:
    """A SPY file the manifest knows about but the decision does not admit --
    used by the probe as the file that MUST be unreadable."""
    man = json.loads(t.manifest_path.read_text())
    for rel, r in sorted(man["files"].items()):
        if r.get("symbol") == SCOPE_SYMBOL and r.get("session_date", "") > SCOPE_END:
            return rel
    return None


def _no_symlink_in(path: Path, root: Path) -> None:
    rp = Path(os.path.realpath(path))
    if not (rp == root.resolve() or root.resolve() in rp.parents):
        raise ActivationRefused("PATH_ESCAPE: %s resolves to %s, outside %s" % (path, rp, root))
    cur = root
    for part in path.relative_to(root).parts:
        cur = cur / part
        if os.path.islink(cur):
            raise ActivationRefused("SYMLINK_REFUSED: %s is a symlink" % cur)


def build_view(t: Targets, files: list, run: SystemRunner) -> dict:
    if t.view.exists():
        raise ActivationRefused("DESTINATION_EXISTS: %s" % t.view)
    names = [Path(f["rel"]).name for f in files]
    if len(set(names)) != len(names):
        raise ActivationRefused("INVENTORY_DUPLICATE: %s"
                                % sorted({n for n in names if names.count(n) > 1})[:3])
    staging = t.view.with_name(t.view.name + ".staging")
    if staging.exists():
        raise ActivationRefused("DESTINATION_EXISTS: %s" % staging)
    bars = staging / "etf_continuous" / "bars"
    bars.mkdir(parents=True)
    try:
        for f in files:
            src = t.corpus_root / f["rel"]
            _no_symlink_in(src, t.corpus_root)
            if not src.is_file():
                raise ActivationRefused("SOURCE_MISSING: %s" % src)
            if sha256_of(src) != f["sha256"]:
                raise ActivationRefused("SOURCE_HASH_MISMATCH: %s" % f["rel"])
            dst = bars / Path(f["rel"]).name
            run.copy(src, dst)
            if sha256_of(dst) != f["sha256"]:
                raise ActivationRefused("COPY_HASH_MISMATCH: %s" % f["rel"])
        present = sorted(p.name for p in bars.iterdir())
        missing, extra = sorted(set(names) - set(present)), sorted(set(present) - set(names))
        if missing or extra:
            raise ActivationRefused("INVENTORY_MISMATCH: %d missing, %d extra" % (len(missing), len(extra)))
        if len(present) != t.expected_view_files:
            raise ActivationRefused("INVENTORY_COUNT: %d, expected %d" % (len(present), t.expected_view_files))
        if any(os.path.islink(bars / n) for n in present):
            raise ActivationRefused("SYMLINK_IN_VIEW")
        staging.rename(t.view)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return {"files": len(names), "first": names[0], "last": names[-1]}


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
        raise ActivationRefused("IDENTITY_CONFLICT: %s already exists (uid %s, groups %s)"
                                % (user, a.get("uid"), a.get("groups")))
    if a["present"]:
        if a["privileged_groups"]:
            raise ActivationRefused("IDENTITY_PRIVILEGED: %s is in %s" % (user, a["privileged_groups"]))
        if a["groups"] != [user]:
            raise ActivationRefused("IDENTITY_GROUPS_UNEXPECTED: %s is in %s, expected only %r"
                                    % (user, a["groups"], user))
    return a


# ----------------------------------------------------------- source ident
# The checkout is handed to the research account, so root inspects a tree it
# does not own and git refuses on "dubious ownership". The exception is pinned
# to the one repo being read, and the other account's global and system config
# is neutralised so nothing it could write can influence the inspection.
# Residual: repo-local .git/config still applies. The checkout is cloned by
# root from a trusted local repo and handed over within the same process, so
# there is no window in which the research account could author it.
_GIT_ENV = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null",
            "PATH": "/usr/bin:/bin", "LC_ALL": "C"}


def _git(repo: Path, *args, binary=False):
    r = subprocess.run(["git", "-C", str(repo), "-c", "safe.directory=%s" % repo,
                        *[str(a) for a in args]],
                       capture_output=True, timeout=300, env=dict(_GIT_ENV))
    if r.returncode != 0:
        raise ActivationRefused("GIT_FAILED: git %s in %s: %s"
                                % (" ".join(map(str, args)), repo, r.stderr.decode()[:200]))
    return r.stdout if binary else r.stdout.decode()


def working_tree_identity(repo: Path, paths=BOUND_SOURCE_PATHS) -> dict:
    """What is ON DISK right now, mirroring boundary.source_identity: sha256
    of each tracked working file plus the dirty list. expected_tree_sha256
    reads COMMITTED blobs, so it cannot see an edited working file -- which
    is exactly the drift a launch must refuse."""
    repo = Path(repo).resolve()
    dirty = [l for l in _git(repo, "status", "--porcelain", "--untracked-files=all", "--", *paths).splitlines() if l]
    rels = sorted(l for l in _git(repo, "ls-files", "--", *paths).splitlines() if l)
    lines = ["%s %s" % (rel, sha256_of(repo / rel)) for rel in rels if (repo / rel).exists()]
    return {"commit": _git(repo, "rev-parse", "HEAD").strip(),
            "tree_sha256": hashlib.sha256("\n".join(lines).encode()).hexdigest(),
            "n_files": len(lines), "dirty": dirty}


def expected_tree_sha256(repo: Path, commit: str, paths=BOUND_SOURCE_PATHS) -> dict:
    """The source commitment a checkout of `commit` WOULD produce, computed
    from the repository. Mirrors boundary.source_identity exactly."""
    rels = sorted(l for l in _git(repo, "ls-tree", "-r", "--name-only", commit, "--", *paths).splitlines() if l)
    lines = ["%s %s" % (rel, hashlib.sha256(_git(repo, "show", "%s:%s" % (commit, rel),
                                                 binary=True)).hexdigest()) for rel in rels]
    return {"commit": _git(repo, "rev-parse", commit).strip(),
            "tree_sha256": hashlib.sha256("\n".join(lines).encode()).hexdigest(), "n_files": len(lines)}


# ---------------------------------------------------------------- stages
@dataclass(frozen=True)
class Stage:
    name: str
    obj: str
    cls: str            # capability | evidence
    kind: str
    execute: object     # (t, ctx, run) -> None
    verify: object      # (t, ctx) -> dict   (raises ActivationRefused)


def _tree_entries(root: Path):
    """The root itself, then every entry beneath it. Symlinks are yielded, not
    followed -- the caller decides what a link means."""
    yield root
    for d, dirs, files in os.walk(root, followlinks=False):
        for n in dirs + files:
            yield Path(d) / n


def _path_under(p, root) -> bool:
    """True only when `p` is `root` or lies beneath it.

    A string prefix test is not containment: "/etc/apex/admissions-other/d.json"
    startswith "/etc/apex/admissions", so a similarly named SIBLING directory
    passed. Both paths are resolved first so symlinks cannot dress one up as the
    other."""
    p, root = Path(p).resolve(), Path(root).resolve()
    return p == root or root in p.parents


def _mode_of(p: Path) -> str:
    return "%o" % stat.S_IMODE(os.stat(p).st_mode)


def stages(t: Targets) -> list:
    def s_mkdir(path, mode=0o755):
        def _verify(tt, ctx):
            if not path.is_dir():
                _raise("DIR_NOT_CREATED: %s" % path)
            got, want = _mode_of(path), "%o" % mode
            if got != want:
                # reporting the mode found is not the same as requiring the mode
                # asked for; a world-writable evidence directory must not pass
                _raise("DIR_MODE: %s is %s, expected %s" % (path, got, want))
            return {"exists": True, "mode": got}
        return (lambda tt, ctx, run: run.mkdir(path, mode), _verify)

    def _raise(msg):
        raise ActivationRefused(msg)

    def v_account(tt, ctx):
        a = assert_identity(tt.research_user, must_exist=True)
        return {"uid": a["uid"], "groups": a["groups"], "privileged_groups": a["privileged_groups"]}

    def x_account(tt, ctx, run):
        run.cmd(["adduser", "--system", "--group", "--disabled-password",
                 "--shell", "/usr/sbin/nologin", "--home", "/home/%s" % tt.research_user,
                 tt.research_user])
        run.cmd(["passwd", "-l", tt.research_user])

    def v_own(tt, ctx):
        a = account_facts(tt.research_user)
        if not a.get("present"):
            # guarding the only assertion behind "if the account exists" means a
            # missing account turns this stage into a no-op that still reports
            # VERIFIED. That is the V0 defect, surviving in one verifier.
            raise ActivationRefused("OWNERSHIP_UNVERIFIABLE: account %s does not exist"
                                    % tt.research_user)
        wrong = [str(q) for q in _tree_entries(tt.research_root)
                 if os.lstat(q).st_uid != a["uid"]]
        if wrong:
            raise ActivationRefused("OWNERSHIP_NOT_APPLIED: %d path(s) not uid %d, e.g. %s"
                                    % (len(wrong), a["uid"], wrong[:3]))
        return {"research_root_uid": a["uid"], "entries_checked": sum(
            1 for _ in _tree_entries(tt.research_root))}

    def v_venv(tt, ctx):
        if not tt.python.exists():
            raise ActivationRefused("VENV_NOT_CREATED: %s absent" % tt.python)
        if not os.access(tt.python, os.X_OK):
            raise ActivationRefused("VENV_PYTHON_NOT_EXECUTABLE: %s" % tt.python)
        return {"python": str(tt.python)}

    def v_requirements(tt, ctx):
        if not tt.requirements.exists():
            raise ActivationRefused("REQUIREMENTS_NOT_WRITTEN: %s" % tt.requirements)
        got = [l.strip() for l in tt.requirements.read_text().splitlines() if l.strip()]
        if got != list(REQUIREMENTS):
            raise ActivationRefused("REQUIREMENTS_CONTENT: %s != %s" % (got, list(REQUIREMENTS)))
        return {"pins": got}

    def v_packages(tt, ctx):
        want = dict(r.split("==") for r in REQUIREMENTS)
        r = subprocess.run([str(tt.python), "-c",
                            "import json,numpy;print(json.dumps({'numpy':numpy.__version__}))"],
                           capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            raise ActivationRefused("PACKAGES_NOT_IMPORTABLE: %s" % (r.stderr.strip()[:200]))
        got = json.loads(r.stdout)
        if got.get("numpy") != want["numpy"]:
            raise ActivationRefused("PACKAGE_VERSION_MISMATCH: numpy %s, expected %s"
                                    % (got.get("numpy"), want["numpy"]))
        return got

    def v_pinned(tt, ctx):
        if not tt.pinned.exists() or not tt.pinned.read_text().strip():
            raise ActivationRefused("PINNED_NOT_WRITTEN: %s" % tt.pinned)
        if REQUIREMENTS[0] not in tt.pinned.read_text():
            raise ActivationRefused("PINNED_MISSING_REQUIREMENT: %s" % REQUIREMENTS[0])
        return {"lines": len(tt.pinned.read_text().splitlines())}

    def v_harden(tt, ctx):
        """The stage exists so the research account cannot modify the runner.

        Mode bits alone do not establish that: an OWNER may chmod at will, so a
        tree owned by the research account satisfies every permission check and
        still fails the property. Ownership is the load-bearing fact and is
        checked first. The action is `chmod -R`, so the check is recursive too --
        a verify weaker than the action it verifies is not a verify."""
        expect_uid = (ctx or {}).get("expect_uid", tt.runner_owner_uid)   # production: root
        if tt.uid_separation_exercisable and expect_uid == account_facts(tt.research_user).get("uid"):
            raise ActivationRefused("RUNNER_OWNED_BY_RESEARCH_ACCOUNT: the account the "
                                    "hardening exists to exclude cannot be its owner")
        writable, wrong_owner, links = [], [], []
        for q in _tree_entries(tt.runner_root):
            st = os.lstat(q)
            if stat.S_ISLNK(st.st_mode):
                links.append(str(q))
                continue
            if st.st_uid != expect_uid:
                wrong_owner.append(str(q))
            if st.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
                writable.append(str(q))
        if wrong_owner:
            raise ActivationRefused("RUNNER_NOT_OWNED_BY_UID_%d: %d path(s), e.g. %s"
                                    % (expect_uid, len(wrong_owner), wrong_owner[:3]))
        if writable:
            raise ActivationRefused("RUNNER_GROUP_OR_OTHER_WRITABLE: %d path(s), e.g. %s"
                                    % (len(writable), writable[:3]))
        return {"runner_root_mode": _mode_of(tt.runner_root),
                "runner_root_uid": os.lstat(tt.runner_root).st_uid,
                "uid_separation_checked": bool(tt.uid_separation_exercisable),
                "entries_checked": len(writable) + len(wrong_owner) + sum(
                    1 for _ in _tree_entries(tt.runner_root)),
                "symlinks_skipped": len(links)}

    def x_checkout(tt, ctx, run):
        run.cmd(["git", "clone", "--no-hardlinks", tt.source_repo, tt.checkout])
        run.cmd(["git", "-C", tt.checkout, "checkout", "--detach", ctx["ident"]["commit"]])
        a = account_facts(tt.research_user)
        if a.get("present"):
            run.chown_tree(tt.checkout, tt.research_user, tt.research_user)

    def v_checkout(tt, ctx):
        if not (tt.checkout / ".git").exists():
            raise ActivationRefused("CHECKOUT_NOT_CREATED: %s" % tt.checkout)
        got = expected_tree_sha256(tt.checkout, "HEAD")
        want = ctx["ident"]
        if got["commit"] != want["commit"]:
            raise ActivationRefused("CHECKOUT_COMMIT_MISMATCH: %s != %s"
                                    % (got["commit"][:12], want["commit"][:12]))
        if got["tree_sha256"] != want["tree_sha256"]:
            raise ActivationRefused("CHECKOUT_SOURCE_MISMATCH: %s != %s"
                                    % (got["tree_sha256"][:16], want["tree_sha256"][:16]))
        return got

    def v_view(tt, ctx):
        if not tt.view_bars.is_dir():
            raise ActivationRefused("VIEW_NOT_CREATED: %s" % tt.view_bars)
        present = sorted(p.name for p in tt.view_bars.iterdir())
        if len(present) != tt.expected_view_files:
            raise ActivationRefused("VIEW_COUNT: %d, expected %d" % (len(present), tt.expected_view_files))
        by_name = {Path(f["rel"]).name: f["sha256"] for f in ctx["files"]}
        if set(present) != set(by_name):
            raise ActivationRefused("VIEW_INVENTORY_MISMATCH")
        for n in present:
            if sha256_of(tt.view_bars / n) != by_name[n]:
                raise ActivationRefused("VIEW_HASH_MISMATCH: %s" % n)
        return {"files": len(present), "first": present[0], "last": present[-1]}

    mk_research, v_research = s_mkdir(t.research_root)
    mk_out, v_out = s_mkdir(t.out)
    mk_runner, v_runner = s_mkdir(t.runner_root)
    return [
        Stage("research_root", str(t.research_root), "capability", "dir", mk_research, v_research),
        Stage("out", str(t.out), "evidence", "dir", mk_out, v_out),
        Stage("account", t.research_user, "capability", "account", x_account, v_account),
        Stage("own_research_paths", str(t.research_root), "capability", "own",
              lambda tt, ctx, run: run.chown_tree(tt.research_root, tt.research_user, tt.research_user),
              v_own),
        Stage("runner_root", str(t.runner_root), "capability", "dir", mk_runner, v_runner),
        Stage("venv", str(t.venv), "capability", "venv",
              lambda tt, ctx, run: run.cmd([tt.system_python, "-m", "venv", tt.venv]), v_venv),
        Stage("requirements", str(t.requirements), "capability", "file",
              lambda tt, ctx, run: run.write_text(tt.requirements, "\n".join(REQUIREMENTS) + "\n"),
              v_requirements),
        Stage("packages", str(t.venv) + " [packages]", "capability", "packages",
              lambda tt, ctx, run: run.cmd([tt.pip, "install", "--no-cache-dir", "-r", tt.requirements]),
              v_packages),
        Stage("pinned", str(t.pinned), "evidence", "file",
              lambda tt, ctx, run: run.write_text(tt.pinned, run.cmd([tt.pip, "freeze"]).stdout),
              v_pinned),
        Stage("harden_runner", str(t.runner_root), "capability", "own",
              lambda tt, ctx, run: (run.chown_tree(tt.runner_root, "root", "root"),
                                    run.chmod_go_w(tt.runner_root)), v_harden),
        Stage("checkout", str(t.checkout), "capability", "checkout", x_checkout, v_checkout),
        Stage("dataset_view", str(t.view), "capability", "dataset_view",
              lambda tt, ctx, run: ctx.update(view=build_view(tt, ctx["files"], run)), v_view),
    ]


# ------------------------------------------------------------ persistence
def _persist(t: Targets, rec: dict) -> None:
    if not t.research_root.is_dir():
        return                                  # nothing to persist into yet
    tmp = t.setup_manifest.with_suffix(".tmp")
    tmp.write_text(json.dumps(rec, indent=1, sort_keys=True, default=str))
    os.replace(tmp, t.setup_manifest)           # atomic
    with open(t.log, "a") as fh:                # append-only audit trail
        fh.write(json.dumps({"utc": now(), "state": rec["state"],
                             "stages_done": len(rec["created"])}, default=str) + "\n")


def load_setup_record(t: Targets) -> dict:
    if not t.setup_manifest.exists():
        raise ActivationRefused("NO_SETUP_MANIFEST: %s absent" % t.setup_manifest)
    rec = json.loads(t.setup_manifest.read_text())
    if rec.get("contract") != ACTIVATION_VERSION:
        raise ActivationRefused("SETUP_RECORD_CONTRACT: %r" % rec.get("contract"))
    if rec.get("state") not in (STATE_IN_PROGRESS, STATE_PARTIAL, STATE_COMPLETE):
        raise ActivationRefused("SETUP_RECORD_STATE_UNKNOWN: %r" % rec.get("state"))
    for o in rec.get("created") or []:
        if o.get("class") not in ("capability", "evidence") or not o.get("object"):
            raise ActivationRefused("SETUP_RECORD_INCONSISTENT: %r" % o)
    return rec


# ----------------------------------------------------------------- setup
def run_setup(t: Targets, commit: str, *, apply: bool, run: SystemRunner | None = None,
              resume: bool = False) -> dict:
    run = run or SystemRunner()
    prior = None
    if resume:
        try:
            prior = load_setup_record(t)
        except ActivationRefused as e:
            raise ActivationRefused("NOTHING_TO_RESUME: %s" % e) from e
        if prior.get("state") not in (STATE_PARTIAL, STATE_IN_PROGRESS):
            raise ActivationRefused("NOT_RESUMABLE: recorded state is %s" % prior.get("state"))
    pre = preflight(t, commit, None, resuming=resume)
    if not pre["ok"]:
        raise ActivationRefused("PREFLIGHT_FAILED: %s" % ", ".join(pre["blocking"]))
    if prior is not None and prior.get("commit") != pre["resolved_commit"]["commit"]:
        raise ActivationRefused("RESUME_COMMIT_MISMATCH: partial run was %s, requested %s"
                                % (str(prior.get("commit"))[:12], pre["resolved_commit"]["commit"][:12]))
    # Fresh: the account must NOT exist. Resuming: it may, and if it does it
    # must still be the unprivileged account this wrapper is allowed to use --
    # assert_identity checks group membership and privilege either way.
    assert_identity(t.research_user,
                    must_exist=bool(resume and account_facts(t.research_user)["present"]))
    ctx = {"ident": pre["resolved_commit"], "files": admitted_files(t)}
    plan = stages(t)
    rec = {"contract": ACTIVATION_VERSION, "action": "setup", "applied": bool(apply),
           "started_utc": now(), "state": STATE_IN_PROGRESS, "commit": ctx["ident"]["commit"],
           "source_tree_sha256": ctx["ident"]["tree_sha256"],
           "expected_view_files": t.expected_view_files, "runner": run.name,
           "targets": {"research_user": t.research_user, "runner_root": str(t.runner_root),
                       "research_root": str(t.research_root), "checkout": str(t.checkout),
                       "view": str(t.view), "out": str(t.out)},
           "planned_stages": [{"stage": s.name, "object": s.obj, "class": s.cls, "kind": s.kind}
                              for s in plan],
           "created": [], "stages": []}
    if not apply:
        rec["state"] = "DRY_RUN"
        rec["note"] = "nothing executed; no object created; run with --apply to perform these stages"
        return rec
    rec["resumed_from"] = (prior or {}).get("failed_at")
    for s in plan:
        try:
            if resume:
                # Ask reality first. A stage whose object already satisfies its
                # own verifier is not redone; anything else is executed and then
                # verified exactly as on a fresh run. Nothing is trusted because
                # a previous record claimed it.
                try:
                    ev = s.verify(t, ctx)
                    rec["stages"].append({"stage": s.name, "status": "ALREADY_VERIFIED",
                                          "utc": now(), "evidence": ev})
                    rec["created"].append({"object": s.obj, "class": s.cls, "kind": s.kind,
                                           "stage": s.name, "utc": now(), "evidence": ev,
                                           "carried_from_partial_run": True})
                    _persist(t, rec)
                    continue
                except ActivationRefused:
                    pass
            s.execute(t, ctx, run)
            ev = s.verify(t, ctx)
        except ActivationRefused as e:
            rec["state"] = STATE_PARTIAL
            rec["stages"].append({"stage": s.name, "status": "FAILED", "utc": now(), "detail": str(e)})
            rec["failed_at"] = s.name
            rec["finished_utc"] = now()
            _persist(t, rec)
            raise ActivationRefused("SETUP_FAILED_AT %s: %s" % (s.name, e))
        rec["stages"].append({"stage": s.name, "status": "VERIFIED", "utc": now(), "evidence": ev})
        rec["created"].append({"object": s.obj, "class": s.cls, "kind": s.kind,
                               "stage": s.name, "utc": now(), "evidence": ev})
        _persist(t, rec)                        # partial progress is on disk after every stage
    rec["state"] = STATE_COMPLETE
    rec["finished_utc"] = now()
    rec["view"] = ctx.get("view")
    _persist(t, rec)
    return rec


# ---------------------------------------------------------------- verify
def run_verify(t: Targets) -> dict:
    """Check what actually exists. Raises on the first thing that does not."""
    rec = load_setup_record(t)
    if rec["state"] != STATE_COMPLETE:
        raise ActivationRefused("SETUP_NOT_COMPLETE: state is %s" % rec["state"])
    checks = []

    def ck(name, fn):
        checks.append({"check": name, "ok": True, "detail": fn()})

    ck("identity", lambda: assert_identity(t.research_user, must_exist=True))
    ck("environment", lambda: stages(t)[5].verify(t, {}))                    # venv
    ck("packages", lambda: stages(t)[7].verify(t, {}))
    ck("pinned", lambda: stages(t)[8].verify(t, {}))
    ck("runner_not_writable_by_research", lambda: stages(t)[9].verify(t, {}))
    ck("checkout_identity", lambda: stages(t)[10].verify(
        t, {"ident": {"commit": rec["commit"], "tree_sha256": rec["source_tree_sha256"]}}))
    ck("dataset_inventory", lambda: stages(t)[11].verify(t, {"files": admitted_files(t)}))

    def perms():
        a = account_facts(t.research_user)
        out = {"out_owner_uid": os.stat(t.out).st_uid, "view_mode": _mode_of(t.view_bars),
               "research_uid": a.get("uid")}
        if not a.get("present"):
            raise ActivationRefused("PERMISSIONS_UNVERIFIABLE: account %s does not exist"
                                    % t.research_user)
        if os.stat(t.out).st_uid != a["uid"]:
            raise ActivationRefused("OUT_NOT_OWNED_BY_RESEARCH")
        if os.stat(t.venv).st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            raise ActivationRefused("VENV_WRITABLE_BY_OTHERS")
        return out
    ck("permissions", perms)
    return {"action": "verify", "state": rec["state"], "checks": checks, "ok": True}


# ----------------------------------------------------- launch configuration
@dataclass(frozen=True)
class LaunchConfig:
    properties: tuple
    setenv: tuple

    def args(self) -> list:
        a = []
        for p in self.properties:
            a += ["-p", p]
        return a + ["--setenv=" + e for e in self.setenv]


def launch_config(t: Targets, *, probe: bool = False) -> LaunchConfig:
    """One configuration, used by both the probe and the launch.

    The probe used to run under a smaller memory cap, which meant the isolation
    that was measured was not, literally, the isolation that would run. The
    `probe` parameter is kept so callers need not change, but it no longer
    alters a single property: a probe of a different configuration proves
    nothing about this one."""
    props = ("User=%s" % t.research_user, "Group=%s" % t.research_user,
             "MemoryMax=%s" % t.memory_max, "TasksMax=%s" % t.tasks_max,
             "ProtectSystem=strict", "ProtectHome=yes", "PrivateTmp=yes", "PrivateNetwork=yes",
             "NoNewPrivileges=yes", "RestrictSUIDSGID=yes",
             "TemporaryFileSystem=%s" % t.corpus_root.parent.parent,
             "BindReadOnlyPaths=%s:%s" % (t.view_bars, t.corpus_root),
             *["InaccessiblePaths=%s" % p for p in t.inaccessible],
             "ReadOnlyPaths=%s" % t.manifest_path.parent.parent,
             "ReadOnlyPaths=%s" % t.trust_root,
             "ReadWritePaths=%s" % t.out)
    env = ("GIT_CONFIG_GLOBAL=/dev/null", "GIT_CONFIG_NOSYSTEM=1", "PYTHONPATH=%s" % t.checkout)
    return LaunchConfig(properties=props, setenv=env)


def _systemd_run(t: Targets, cfg: LaunchConfig, argv: list) -> list:
    base = ["systemd-run", "--pipe", "--wait", "--collect", "--slice=%s" % t.slice_name]
    if os.geteuid() != 0:
        base = ["sudo", "-n"] + base
    return base + cfg.args() + ["--working-directory=%s" % t.checkout] + [str(a) for a in argv]


PROBE_EXPECTATIONS = {"admitted_readable": True, "evaluation_readable": False,
                      "other_corpus_files_visible": False, "core_readable": False,
                      "history_a_readable": False, "secrets_readable": False,
                      "corpus_writable": False, "manifest_readable": True,
                      "network_reachable": False}


def run_probe(t: Targets, *, run: SystemRunner | None = None) -> dict:
    """ENTER the sandbox and measure. Not a description of one."""
    run = run or SystemRunner()
    rec = load_setup_record(t)
    if rec["state"] != STATE_COMPLETE:
        raise ActivationRefused("SETUP_NOT_COMPLETE: state is %s" % rec["state"])
    files = admitted_files(t)
    admitted = Path(files[0]["rel"]).name
    denied = out_of_scope_example(t)
    if not denied:
        raise ActivationRefused("NO_OUT_OF_SCOPE_EXAMPLE: cannot prove exclusion without one")
    script = "\n".join([
        "cd / || exit 9",
        'test -r "%s/%s" && echo admitted_readable=true || echo admitted_readable=false' % (t.corpus_root, admitted),
        'test -r "%s/%s" && echo evaluation_readable=true || echo evaluation_readable=false' % (t.corpus_root, denied),
        'test -e "%s/integrity.jsonl" && echo other_corpus_files_visible=true || echo other_corpus_files_visible=false'
        % t.corpus_root.parent,
        'ls %s >/dev/null 2>&1 && echo core_readable=true || echo core_readable=false' % t.inaccessible[0],
        'ls %s >/dev/null 2>&1 && echo history_a_readable=true || echo history_a_readable=false' % t.inaccessible[1],
        'cat /home/apex/.apex-secrets/ALPACA_API_KEY_ID >/dev/null 2>&1 && echo secrets_readable=true || echo secrets_readable=false',
        'touch "%s/_probe_write" 2>/dev/null && echo corpus_writable=true || echo corpus_writable=false' % t.corpus_root,
        'test -r "%s" && echo manifest_readable=true || echo manifest_readable=false' % t.manifest_path,
        'getent hosts github.com >/dev/null 2>&1 && echo network_reachable=true || echo network_reachable=false',
    ])
    cfg = launch_config(t, probe=True)
    r = run.cmd(_systemd_run(t, cfg, ["/bin/sh", "-c", script]))
    obs = {}
    for line in (r.stdout or "").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            obs[k.strip()] = {"true": True, "false": False}.get(v.strip(), v.strip())
    deviations = {k: {"expected": v, "observed": obs.get(k)}
                  for k, v in PROBE_EXPECTATIONS.items() if obs.get(k) != v}
    out = {"action": "probe", "executed": True, "properties": list(cfg.properties),
           "observations": obs, "expected": PROBE_EXPECTATIONS, "deviations": deviations,
           "admitted_example": admitted, "denied_example": denied,
           "ok": not deviations and len(obs) == len(PROBE_EXPECTATIONS)}
    if not out["ok"]:
        raise ActivationRefused("PROBE_FAILED: %s" % json.dumps(deviations or {"observed": obs}))
    return out


# ---------------------------------------------------------------- launch
def prepare_launch(t: Targets, commit: str, decision: Path) -> dict:
    rec = load_setup_record(t)
    if rec["state"] != STATE_COMPLETE:
        raise ActivationRefused("SETUP_NOT_COMPLETE: state is %s; launch requires a verified setup"
                                % rec["state"])
    required = {"account", "checkout", "dataset_view", "venv", "packages"}
    done = {o["stage"] for o in rec["created"]}
    if not required <= done:
        raise ActivationRefused("SETUP_RECORD_INCOMPLETE: missing stages %s" % sorted(required - done))
    if rec["commit"] != _git(t.checkout, "rev-parse", commit).strip():
        raise ActivationRefused("COMMIT_MISMATCH: setup recorded %s, requested %s"
                                % (rec["commit"][:12], commit[:12]))
    got = working_tree_identity(t.checkout)          # ON DISK, not the committed blobs
    if got["dirty"]:
        raise ActivationRefused("SOURCE_DIRTY: %s" % got["dirty"][:5])
    if got["tree_sha256"] != rec["source_tree_sha256"]:
        raise ActivationRefused("SOURCE_DRIFT: checkout is %s, setup recorded %s"
                                % (got["tree_sha256"][:16], rec["source_tree_sha256"][:16]))
    n = len(list(t.view_bars.iterdir())) if t.view_bars.is_dir() else 0
    if n != t.expected_view_files:
        raise ActivationRefused("VIEW_DRIFT: %d files, expected %d" % (n, t.expected_view_files))
    if not t.python.exists():
        raise ActivationRefused("ENVIRONMENT_MISSING: %s" % t.python)
    d = Path(decision)
    if not d.exists() or not d.with_name(d.name + ".sig").exists():
        raise ActivationRefused("DECISION_OR_SIGNATURE_MISSING: %s" % d)
    if not _path_under(d, t.trust_root):
        raise ActivationRefused("DECISION_OUTSIDE_TRUST_ROOT: %s is not inside %s "
                                "(a similarly named sibling is not the trust root)"
                                % (d, t.trust_root))
    cfg = launch_config(t)
    argv = _systemd_run(t, cfg, [t.python, "scripts/alpha_exp_real_execute.py",
                                 "--decision", d, "--execute"])
    return {"action": "launch", "resolved": {
                "commit": got["commit"], "source_tree_sha256": got["tree_sha256"],
                "interpreter": str(t.python), "decision": str(d),
                "decision_sha256": sha256_of(d), "view_files": n,
                "experiment": EXPERIMENT_ID, "registration_hash": REGISTRATION_HASH},
            "argv": argv,
            "executable_command": " ".join(argv),
            "EXECUTABLE_COMMAND_WARNING":
                "This argv RUNS the experiment. It carries --execute and is not a dry "
                "run in any form. Preparation and execution are distinguished by the "
                "WRAPPER invocation in operator_commands, not by editing this argv.",
            "operator_commands": operator_commands(t, commit, d),
            "checks_performed": PREPARE_CHECKS_PERFORMED,
            "checks_not_performed_here": PREPARE_CHECKS_ELSEWHERE}


# What preparation actually establishes. Stated as data so the documentation
# cannot drift away from the code.
PREPARE_CHECKS_PERFORMED = {
    "setup_record_state_is_COMPLETE": True,
    "required_stages_present_in_record": True,
    "requested_commit_matches_setup_record": True,
    "checkout_working_tree_clean": True,
    "bound_source_tree_hash_matches_record": True,
    "dataset_view_file_COUNT_matches": True,
    "interpreter_present": True,
    "decision_file_exists": True,
    "signature_file_exists": True,
    "decision_contained_in_trust_root": True,
    # the two that existence checks do NOT establish
    "dataset_view_file_HASHES_rechecked": False,
    "signature_cryptographically_VERIFIED": False,
}

PREPARE_CHECKS_ELSEWHERE = {
    "signature_verification":
        "NOT done by preparation. Done by "
        "apex.world_model.real_data.boundary.verify_decision, called from "
        "scripts/alpha_exp_real_execute.py at execution time, which runs "
        "ssh-keygen -Y verify against /etc/apex/admissions/trust/allowed_signers. "
        "The operator can establish it in advance with the same ssh-keygen -Y "
        "verify command shown in the signing document.",
    "dataset_content_integrity":
        "NOT done by preparation, which counts files only. Done by the wrapper's "
        "`verify` action, whose dataset_inventory check re-hashes every admitted "
        "file and refuses on VIEW_HASH_MISMATCH. Run `verify` immediately before "
        "launching.",
}


def operator_commands(t: Targets, commit: str, decision) -> dict:
    """The two wrapper invocations, generated rather than described.

    Preparation and execution differ by --apply on the WRAPPER, never by editing
    the inner argv."""
    base = ["sudo", "-n", t.system_python, "scripts/research_activation.py", "launch",
            "--commit", str(commit), "--decision", str(decision)]
    return {"prepare": " ".join(base),
            "prepare_effect": "resolves and checks inputs, prints the plan, "
                              "and launches NOTHING",
            "execute": " ".join(base + ["--apply"]),
            "execute_effect": "runs the registered experiment inside the sandbox",
            "difference": "--apply, on the wrapper invocation"}


# Launch outcomes. Only one of them is success, and it requires a sealed result.
LAUNCH_COMPLETED = "COMPLETED_WITH_RESULT"
LAUNCH_NO_RESULT = "COMPLETED_WITHOUT_RESULT"
LAUNCH_REFUSED = "REFUSED"
LAUNCH_OOM = "OOM_KILLED"
LAUNCH_TIMEOUT = "TIMED_OUT"
LAUNCH_FAILED = "FAILED"
LAUNCH_NOT_STARTED = "NOT_STARTED"
LAUNCH_EXIT_CODES = {LAUNCH_COMPLETED: 0, LAUNCH_REFUSED: 3, LAUNCH_FAILED: 4,
                     LAUNCH_OOM: 5, LAUNCH_TIMEOUT: 6, LAUNCH_NO_RESULT: 7,
                     LAUNCH_NOT_STARTED: 8}
# systemd reports the kill reason on its own stderr. Classifying on that text is
# evidence, not inference; without it an OOM is reported as an ordinary failure.
_OOM_EVIDENCE = ("oom-kill", "oom_kill", "out of memory", "status=KILL")


def classify_launch(child: dict, result_sealed: bool) -> tuple:
    """(outcome, evidence). Never returns success without a sealed result."""
    if child.get("spawn_error"):
        return LAUNCH_NOT_STARTED, "the child could not be started: %s" % child["spawn_error"]
    if child.get("timed_out"):
        return LAUNCH_TIMEOUT, "the child exceeded its timeout and was terminated"
    rc = child.get("returncode")
    blob = "%s\n%s" % (child.get("stderr") or "", child.get("stdout") or "")
    oom = any(m.lower() in blob.lower() for m in _OOM_EVIDENCE)
    outcome = None
    try:
        doc = json.loads(child.get("stdout") or "")
        outcome = doc.get("process_outcome") if isinstance(doc, dict) else None
    except ValueError:
        pass
    if rc not in (0, None):
        if oom:
            return LAUNCH_OOM, "systemd reported the process was killed for memory"
        if outcome and "REFUS" in str(outcome).upper():
            return LAUNCH_REFUSED, "the experiment refused: %s" % outcome
        return LAUNCH_FAILED, "the child exited %s" % rc
    if oom:
        return LAUNCH_OOM, "systemd reported a memory kill despite exit %s" % rc
    if not result_sealed:
        # the defect this exists to prevent: a run that dies mid-way, or exits
        # zero having sealed nothing, must never be reported as a success
        return LAUNCH_NO_RESULT, "the child exited %s but sealed no result" % rc
    return LAUNCH_COMPLETED, "the child exited 0 and sealed a result"


def _run_dirs(t: Targets) -> set:
    base = t.out / EXPERIMENT_ID / "runs"
    return {str(d) for d in base.iterdir()} if base.is_dir() else set()


# A result whose status begins with any of these is not a completed outcome.
_NOT_COMPLETED = ("REFUS", "INCOMPLETE", "ERROR", "FAIL", "ABORT", "INVALID")


def _sealed_results_for(t: Targets, decision_sha256: str, before: set) -> list:
    """Results that belong to THIS launch and record a completed outcome.

    Existence was not enough. A result left by an earlier run, or by a run under
    a different decision, would otherwise be read as this launch succeeding, and
    a result recording a refusal would be read as a completed one. A run counts
    only when its directory is new to this launch, its _RUN.json names the
    decision we launched with, and its result records a completed outcome."""
    out = []
    for d in sorted(Path(x) for x in (_run_dirs(t) - before)):
        rp, runp = d / RESULT_FILE, d / RUN_FILE
        if not (rp.is_file() and runp.is_file()):
            continue
        try:
            runrec = json.loads(runp.read_text())
            res = json.loads(rp.read_text())
        except (OSError, ValueError) as e:
            out.append({"path": str(rp), "counted": False, "why": "unreadable: %s" % e})
            continue
        if decision_sha256 and runrec.get("decision_sha256") != decision_sha256:
            out.append({"path": str(rp), "counted": False,
                        "why": "belongs to decision %s, not the one launched"
                               % str(runrec.get("decision_sha256"))[:16]})
            continue
        status = str(res.get("status") or res.get("process_outcome") or "").upper()
        if not status:
            out.append({"path": str(rp), "counted": False, "why": "result records no outcome"})
            continue
        if any(m in status for m in _NOT_COMPLETED):
            out.append({"path": str(rp), "counted": False,
                        "why": "result records %s, which is not a completed outcome" % status})
            continue
        out.append({"path": str(rp), "counted": True, "run_id": runrec.get("run_id"),
                    "status": status})
    return out


def run_launch(t: Targets, commit: str, decision: Path, *, apply: bool,
               run: SystemRunner | None = None) -> dict:
    plan = prepare_launch(t, commit, decision)
    plan["applied"] = bool(apply)
    if not apply:
        plan["note"] = "prepared only; authorization C is required to run this command"
        plan["ok"] = True
        return plan
    run = run or SystemRunner()
    before = _run_dirs(t)
    dsha = sha256_of(Path(decision)) if Path(decision).exists() else ""
    started = now()
    child = run.run_child(plan["argv"], timeout=7200)
    considered = _sealed_results_for(t, dsha, before)
    sealed = [r for r in considered if r.get("counted")]
    outcome, why = classify_launch(child, bool(sealed))
    plan["execution"] = {
        "started_utc": started, "finished_utc": now(),
        "returncode": child.get("returncode"),
        "timed_out": bool(child.get("timed_out")),
        "spawn_error": child.get("spawn_error"),
        "outcome": outcome, "outcome_evidence": why,
        "exit_code": LAUNCH_EXIT_CODES[outcome],
        "result_sealed": bool(sealed), "sealed_results": sealed,
        "results_considered": considered,      # including the ones NOT counted, and why
        "decision_sha256": dsha,
        # the whole of both streams: on failure these ARE the evidence
        "stdout": child.get("stdout") or "",
        "stderr": child.get("stderr") or "",
    }
    try:
        doc = json.loads(child.get("stdout") or "")
        plan["execution"]["process_outcome"] = doc.get("process_outcome") if isinstance(doc, dict) else None
    except ValueError:
        plan["execution"]["process_outcome"] = None
    plan["ok"] = outcome == LAUNCH_COMPLETED
    rp = t.out / ("_LAUNCH_%s.json" % started.replace(":", "").replace("-", ""))
    rp.write_text(json.dumps(plan, indent=1, sort_keys=True, default=str))
    plan["launch_record"] = str(rp)
    return plan


def run_repin(t: Targets, commit: str, *, apply: bool, run: SystemRunner | None = None) -> dict:
    """Move the prepared checkout to another commit, and ONLY when that commit
    leaves the experiment code byte-identical.

    Wrapper repairs land after a checkout is prepared, and an auditor opening
    the checkout should not find an older tree than the one under review. But
    re-pinning must never become a way to change what runs: the bound source
    tree hash must match exactly, or this refuses and the environment has to be
    rebuilt under fresh review."""
    rec = load_setup_record(t)
    if rec["state"] != STATE_COMPLETE:
        raise ActivationRefused("SETUP_NOT_COMPLETE: state is %s" % rec["state"])
    new_ident = expected_tree_sha256(t.source_repo, commit)
    plan = {"contract": ACTIVATION_VERSION, "action": "repin", "utc": now(),
            "from": {"commit": rec["commit"], "source_tree_sha256": rec["source_tree_sha256"]},
            "to": {"commit": new_ident["commit"], "source_tree_sha256": new_ident["tree_sha256"],
                   "n_files": new_ident["n_files"]},
            "bound_paths": list(BOUND_SOURCE_PATHS), "applied": bool(apply)}
    if new_ident["tree_sha256"] != rec["source_tree_sha256"]:
        raise ActivationRefused(
            "REPIN_CHANGES_EXPERIMENT_CODE: bound tree would move %s -> %s. A commit that "
            "changes what runs is a new experiment, not a re-pin."
            % (rec["source_tree_sha256"][:16], new_ident["tree_sha256"][:16]))
    if not apply:
        plan["note"] = "prepared only; nothing moved"
        return plan
    run = run or SystemRunner()
    if t.checkout.resolve().parent != t.research_root.resolve():
        raise ActivationRefused("REFUSING_TO_REMOVE: %s is not directly under %s"
                                % (t.checkout, t.research_root))
    shutil.rmtree(t.checkout)                     # capability, never evidence
    ctx = {"ident": new_ident, "files": admitted_files(t)}
    stage = [x for x in stages(t) if x.name == "checkout"][0]
    stage.execute(t, ctx, run)
    plan["evidence"] = stage.verify(t, ctx)
    rec["commit"] = new_ident["commit"]
    rec["source_tree_sha256"] = new_ident["tree_sha256"]
    rec.setdefault("repins", []).append({"utc": now(), "from": plan["from"], "to": plan["to"]})
    _persist(t, rec)
    plan["setup_record_updated"] = True
    return plan


# -------------------------------------------------------------- rollback
def rollback_plan(t: Targets) -> dict:
    """Capability only, and never a directory that contains preserved
    evidence: recursive removal of such a parent would erase the evidence the
    plan claims to keep. Such a parent is preserved and only its recorded
    capability CHILDREN are removed."""
    rec = load_setup_record(t)
    created = rec.get("created") or []
    always_preserve = {t.out, t.setup_manifest, t.log}
    evidence = {Path(o["object"]) for o in created
                if o["class"] == "evidence" and o["kind"] != "account"} | always_preserve
    cap = [o for o in created if o["class"] == "capability"]
    cap_paths = {Path(o["object"]) for o in cap if o["kind"] != "account"}
    remove, preserve = [], [o for o in created if o["class"] == "evidence"]
    seen = set()
    for o in cap:
        key = (o["object"], o["kind"])
        if key in seen:
            continue
        seen.add(key)
        if o["kind"] == "account":
            remove.append({**o, "how": "deluser"})
            continue
        p = Path(o["object"])
        if p == t.trust_root or str(p).startswith(str(t.trust_root) + "/") or str(p) in ("/etc", "/etc/apex"):
            preserve.append({**o, "why_preserved": "PROTECTED_PATH: trust material is never removed"})
            continue
        contained = sorted(str(e) for e in evidence if e == p or p in e.parents)
        if contained:
            children = sorted(str(c) for c in cap_paths
                              if c != p and p in c.parents
                              and not any(e == c or c in e.parents for e in evidence))
            preserve.append({**o, "why_preserved": "PARENT_CONTAINS_EVIDENCE",
                             "evidence_inside": contained, "removable_children": children})
            continue
        remove.append({**o, "how": "recursive_remove"})
    # a child whose parent is already being removed need not be listed twice
    rm_paths = {Path(o["object"]) for o in remove if o.get("kind") != "account"}
    remove = [o for o in remove
              if o.get("kind") == "account"
              or not any(par != Path(o["object"]) and par in Path(o["object"]).parents
                         for par in rm_paths)]
    for o in remove:
        if o.get("kind") == "account":
            continue
        p = Path(o["object"])
        bad = [str(e) for e in evidence if e == p or p in e.parents]
        if bad:                                  # belt and braces: never schedule evidence
            raise ActivationRefused("ROLLBACK_WOULD_REMOVE_EVIDENCE: %s contains %s" % (p, bad))
    return {"state": rec["state"], "remove": remove, "preserve": preserve,
            "never_touched": [str(t.trust_root), "/etc/apex", str(t.out), str(t.setup_manifest), str(t.log)],
            "law": "capability is removed, evidence is preserved, and a directory containing "
                   "evidence is never removed recursively"}


def run_rollback(t: Targets, *, apply: bool, run: SystemRunner | None = None) -> dict:
    plan = rollback_plan(t)
    plan.update(action="rollback", applied=bool(apply))
    if not apply:
        return plan
    run = run or SystemRunner()
    done = []
    for o in plan["remove"]:
        p = o["object"]
        if o.get("kind") == "account":
            run.cmd(["deluser", "--remove-home", p])
            done.append({"object": p, "removed": "account"})
        else:
            shutil.rmtree(p, ignore_errors=False) if Path(p).is_dir() else Path(p).unlink(missing_ok=True)
            done.append({"object": p, "removed": "path", "still_exists": Path(p).exists()})
    plan["removed"] = done
    plan["evidence_intact"] = {str(x): Path(x).exists() for x in (t.out, t.setup_manifest, t.log)}
    return plan


# -------------------------------------------------------------- preflight
def preflight(t: Targets, commit: str | None, decision: Path | None,
              *, resuming: bool = False) -> dict:
    rec = {"contract": ACTIVATION_VERSION, "utc": now(), "action": "preflight",
           "targets": {k: str(v) for k, v in (("research_user", t.research_user),
                                              ("runner_root", t.runner_root), ("venv", t.venv),
                                              ("checkout", t.checkout), ("view", t.view),
                                              ("out", t.out), ("trust_root", t.trust_root),
                                              ("allowed_signers", t.allowed_signers))},
           "requirements": list(REQUIREMENTS), "checks": [], "blocking": []}

    def chk(name, ok, detail, blocking=True):
        rec["checks"].append({"check": name, "ok": bool(ok), "detail": detail})
        if not ok and blocking:
            rec["blocking"].append(name)

    a = account_facts(t.research_user)
    # A fresh run demands untouched ground. A resumption is finishing a run
    # that already broke ground, so existing objects are the premise rather
    # than a contradiction -- they are still each re-verified before use.
    chk("identity_absent", (not a["present"]) or resuming,
        a if a["present"] else "%s does not exist yet" % t.research_user)
    for label, p in (("runner_root", t.runner_root), ("research_root", t.research_root),
                     ("checkout", t.checkout), ("view", t.view)):
        chk("destination_free:%s" % label, (not p.exists()) or resuming,
            ("EXISTS (resuming)" if resuming else "EXISTS") if p.exists() else "free")
    rec["resuming"] = bool(resuming)
    chk("source_repo", t.source_repo.is_dir(), str(t.source_repo))
    chk("system_python", Path(t.system_python).exists(), t.system_python)
    chk("corpus_readable", os.access(t.corpus_root, os.R_OK), str(t.corpus_root))
    chk("manifest_present", t.manifest_path.exists(), str(t.manifest_path))
    if t.manifest_path.exists():
        observed, production = sha256_of(t.manifest_path), t.manifest_path == Targets().manifest_path
        chk("manifest_hash", (observed == MANIFEST_SHA256) if production else True,
            observed[:16] + ("" if production else " (non-production manifest: recorded, not pinned)"))
        try:
            sel = admitted_files(t)
            rec["inventory"] = {"selected_from_manifest": len(sel), "expected": t.expected_view_files,
                                "first": sel[0]["session_date"], "last": sel[-1]["session_date"],
                                "symbol": SCOPE_SYMBOL, "range": [SCOPE_START, SCOPE_END]}
            chk("inventory_count", len(sel) == t.expected_view_files,
                "%d selected, expected %d" % (len(sel), t.expected_view_files))
        except ActivationRefused as e:
            chk("inventory", False, str(e))
    chk("trust_root_present", t.trust_root.exists(), "%s (authority creates)" % t.trust_root, blocking=False)
    chk("allowed_signers_present", t.allowed_signers.exists(),
        "%s (authority installs)" % t.allowed_signers, blocking=False)
    if commit:
        try:
            rec["resolved_commit"] = expected_tree_sha256(t.source_repo, commit)
            chk("commit_resolves", True, rec["resolved_commit"]["commit"])
        except ActivationRefused as e:
            chk("commit_resolves", False, str(e))
    else:
        chk("commit_supplied", False, "--commit is required; this package carries no placeholder")
    if decision is not None:
        d = Path(decision)
        chk("decision_present", d.exists(), str(d))
        chk("decision_signature_present", d.with_name(d.name + ".sig").exists(), str(d) + ".sig")
        chk("decision_under_trust_root", _path_under(d, t.trust_root), str(t.trust_root))
    rec["ok"] = not rec["blocking"]
    return rec


# -------------------------------------------------------------------- CLI
def _cli(argv=None, *, targets: Targets | None = None, runner: SystemRunner | None = None) -> int:
    ap = argparse.ArgumentParser(prog="research_activation.py")
    ap.add_argument("action", choices=["preflight", "setup", "verify", "probe", "launch",
                                       "repin", "rollback"])
    ap.add_argument("--commit", default=None)
    ap.add_argument("--decision", default=None)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--resume", action="store_true",
                    help="finish a PARTIAL setup: re-verify each stage and perform only "
                         "the ones reality does not already satisfy")
    ap.add_argument("--json", default=None)
    a = ap.parse_args(argv)
    t = targets or production_targets()
    try:
        if a.action == "preflight":
            rec = preflight(t, a.commit, Path(a.decision) if a.decision else None)
        elif a.action == "setup":
            if not a.commit:
                raise ActivationRefused("UNRESOLVED_INPUTS: --commit is required")
            rec = run_setup(t, a.commit, apply=a.apply, run=runner, resume=a.resume)
        elif a.action == "verify":
            rec = run_verify(t)
        elif a.action == "probe":
            rec = run_probe(t, run=runner)
        elif a.action == "repin":
            if not a.commit:
                raise ActivationRefused("UNRESOLVED_INPUTS: --commit is required")
            rec = run_repin(t, a.commit, apply=a.apply, run=runner)
        elif a.action == "launch":
            if not a.commit or not a.decision:
                raise ActivationRefused("UNRESOLVED_INPUTS: --commit and --decision are both required")
            rec = run_launch(t, a.commit, Path(a.decision), apply=a.apply, run=runner)
        else:
            rec = run_rollback(t, apply=a.apply, run=runner)
    except ActivationRefused as e:
        print(json.dumps({"contract": ACTIVATION_VERSION, "action": a.action,
                          "status": "REFUSED", "refusal": str(e)}, indent=1))
        return 3
    ok = rec.get("ok")
    if ok is None:
        # An action that reports no verdict is not a success. The launch record
        # defaulting to True is what let an OOM-killed run exit 0.
        ok = rec.get("state") in (STATE_COMPLETE, "DRY_RUN") or rec.get("action") != "launch"
    status = "OK" if ok else "FAILED"
    out = json.dumps({"contract": ACTIVATION_VERSION, "status": status, **rec}, indent=1, default=str)
    if a.json:
        Path(a.json).write_text(out)
    print(out)
    if ok:
        return 0
    ex = (rec.get("execution") or {}).get("exit_code")
    return int(ex) if isinstance(ex, int) else 3


if __name__ == "__main__":
    sys.exit(_cli())
