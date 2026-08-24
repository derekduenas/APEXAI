"""RELEASE PEDIGREE — what code is actually running, provably.

Written 2026-08-23 after a data-acquisition daemon died silently for
seven hours. Its root cause was not a bug in the daemon: it was that a
running service shared a working tree with development, and a sync
overwrote a commit that existed only on that host.

Two rules follow, and this module exists to make them checkable rather
than remembered.

RUNTIME IMMUTABILITY
    A service executes from an immutable release directory, never from
    a tree that may be checked out, reset, bundled, pulled, rebased or
    replaced underneath it. Development happens in the repo; services
    run from /opt/apex/current.

CLOUD-ONLY CODE IS FORBIDDEN
    Code required by a canonical running service must exist in the
    canonical repository history. A host's working tree is not a
    backup. `RUNNING_RELEASE_NOT_IN_CANONICAL_HISTORY` is the alarm for
    the exact failure that happened.

VERIFY THE ARTIFACT, NOT THE ECHO applies to processes too: a service
claiming to be healthy proves nothing about which code it is running.

decision_power: NONE -- an operational primitive.
"""
from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
from datetime import datetime, timezone
from pathlib import Path

RELEASE_ROOT = Path(os.environ.get("APEX_RELEASE_ROOT", "/opt/apex"))
CURRENT = RELEASE_ROOT / "current"
RELEASES = RELEASE_ROOT / "releases"
CANONICAL_REPO = Path(os.environ.get("APEX_CANONICAL_REPO",
                                     "/opt/apex-repo"))

RELEASE_STAMP = "RELEASE.json"


class ReleaseViolation(RuntimeError):
    """The running code cannot be accounted for."""


def _git(repo: Path, *args: str) -> str | None:
    try:
        r = subprocess.run(("git", "-C", str(repo)) + args,
                           capture_output=True, text=True, timeout=20)
        return r.stdout.strip() if r.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def module_digest(root: Path, paths: list[str]) -> str:
    """Content hash of the modules that decide a service's behaviour."""
    h = hashlib.sha256()
    for rel in sorted(paths):
        p = Path(root) / rel
        h.update(rel.encode())
        h.update(p.read_bytes() if p.exists() else b"<MISSING>")
    return h.hexdigest()


def config_digest(values: dict) -> str:
    return hashlib.sha256(
        json.dumps(values, sort_keys=True, default=str).encode()
    ).hexdigest()


def secret_backend(secrets_dir: Path | None = None) -> str:
    """Which secret mechanism is actually in play.

    The Phase A death was ultimately a secret-backend mismatch: a Linux
    host reaching for the macOS keychain. Naming the backend in the
    pedigree makes that visible before startup rather than after."""
    d = Path(secrets_dir or os.environ.get(
        "APEX_SECRETS_DIR", Path.home() / ".apex-secrets"))
    if d.is_dir() and any(d.iterdir()):
        return f"FILES:{d}"
    if os.uname().sysname == "Darwin":
        return "MACOS_KEYCHAIN"
    return "NONE_AVAILABLE"


def build_pedigree(*, service: str, release_dir: Path,
                   code_paths: list[str] | None = None,
                   config: dict | None = None,
                   authority: str = "OBSERVE") -> dict:
    """Everything needed to say what is running, independently."""
    release_dir = Path(release_dir)
    stamp = release_dir / RELEASE_STAMP
    stamped = {}
    if stamp.exists():
        try:
            stamped = json.loads(stamp.read_text())
        except json.JSONDecodeError:
            stamped = {}
    return {
        "kind": "release_pedigree",
        "service": service,
        "commit": stamped.get("commit"),
        "commit_short": (stamped.get("commit") or "")[:8] or None,
        "release_path": str(release_dir),
        "release_is_immutable": not os.access(release_dir, os.W_OK),
        "module_digest": module_digest(release_dir, code_paths or []),
        "code_paths": sorted(code_paths or []),
        "config_digest": config_digest(config or {}),
        "secret_backend": secret_backend(),
        "host": socket.gethostname(),
        "pid": os.getpid(),
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "authority": authority,
        "law": "a service must be able to prove which code it runs",
    }


def resolve_current() -> Path:
    """The release a supervised service should be executing."""
    if not CURRENT.exists():
        raise ReleaseViolation(
            f"{CURRENT} does not exist -- no approved release is "
            f"designated, so nothing may be started")
    return CURRENT.resolve()


def verify_running_release(*, release_dir: Path | None = None,
                           canonical_repo: Path | None = None) -> dict:
    """Prove the running code is immutable AND in canonical history.

    Returns a report; raises nothing, because an operator needs the
    findings more than a traceback."""
    findings, verdict = [], "RELEASE_HEALTHY"
    try:
        rd = Path(release_dir) if release_dir else resolve_current()
    except ReleaseViolation as e:
        return {"kind": "release_verification",
                "verdict": "NO_CURRENT_RELEASE", "findings": [str(e)]}

    stamp = rd / RELEASE_STAMP
    if not stamp.exists():
        return {"kind": "release_verification", "release_path": str(rd),
                "verdict": "RELEASE_UNSTAMPED",
                "findings": [f"{RELEASE_STAMP} missing -- this release "
                             f"cannot be attributed to any commit"]}
    meta = json.loads(stamp.read_text())
    commit = meta.get("commit")

    # 1. immutability
    if os.access(rd, os.W_OK):
        findings.append(
            "release directory is WRITABLE -- development activity can "
            "still mutate running code, which is the defect this model "
            "exists to close")
        verdict = "RELEASE_MUTABLE"

    # 2. running from the repo itself
    repo = Path(canonical_repo or CANONICAL_REPO)
    try:
        if repo.resolve() in rd.resolve().parents or \
                rd.resolve() == repo.resolve():
            findings.append(
                "release path is inside the mutable repository")
            verdict = "RELEASE_MUTABLE"
    except OSError:
        pass

    # 3. cloud-only code -- THE incident
    if repo.exists() and commit:
        known = _git(repo, "cat-file", "-t", commit)
        if known != "commit":
            findings.append(
                f"commit {commit[:8]} is not present in the canonical "
                f"repository at {repo} -- this release exists only on "
                f"this host, and a host working tree is not a backup")
            verdict = "RUNNING_RELEASE_NOT_IN_CANONICAL_HISTORY"
        else:
            # present as an object is not the same as reachable
            reachable = _git(repo, "merge-base", "--is-ancestor",
                             commit, "HEAD")
            if reachable is None:
                anc = subprocess.run(
                    ["git", "-C", str(repo), "merge-base",
                     "--is-ancestor", commit, "HEAD"],
                    capture_output=True)
                if anc.returncode != 0:
                    findings.append(
                        f"commit {commit[:8]} exists but is not an "
                        f"ancestor of canonical HEAD -- it is dangling "
                        f"and one gc away from being lost")
                    if verdict == "RELEASE_HEALTHY":
                        verdict = "RELEASE_NOT_IN_MAIN_HISTORY"
    return {"kind": "release_verification", "release_path": str(rd),
            "commit": commit, "verdict": verdict, "findings": findings,
            "law": "code required by a running canonical service must "
                   "exist in canonical history"}
