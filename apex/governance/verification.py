"""VERIFY THE ARTIFACT, NOT THE ECHO.

Pinned permanently 2026-08-23 after two operational failures in one
session: a string substitution reported "installed" without the
substitution landing, and an audit read a stale output file while the
real run was still going, briefly reporting a vacuous zero-failure
result.

Both failures share one shape -- a command's CLAIM of success was
treated as proof of the WORLD's state. A claim is not evidence. The
only cure that survives fatigue and autonomy is structural: make the
artifact carry proof of what produced it, and make readers refuse
artifacts that cannot prove it.

    A run STAMPS its provenance (commit sha, dirty flag, code digest,
    wall clock, host, argv) into everything it writes.

    A reader VERIFIES that stamp before interpreting a single number,
    and REFUSES rather than reporting results from an artifact it
    cannot attribute to a known run.

An unstamped or mismatched artifact is not "probably fine". It is not
evidence, and this module will not let it be read as evidence.

decision_power: NONE -- a governance primitive.
"""
from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


class StaleArtifact(RuntimeError):
    """Raised when an artifact cannot be attributed to the current run."""


class VerificationFailed(RuntimeError):
    """Raised when an expected change is absent from the source tree."""


def _git(*args: str) -> str | None:
    try:
        out = subprocess.run(("git", "-C", str(REPO)) + args,
                             capture_output=True, text=True, timeout=15)
        return out.stdout.strip() if out.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def code_digest(paths: list[str]) -> str:
    """Content hash of the modules that actually produced a result.

    The commit sha alone is not enough -- an uncommitted edit changes
    behaviour without changing the sha, which is exactly the gap that
    lets a stale artifact look current."""
    h = hashlib.sha256()
    for rel in sorted(paths):
        p = REPO / rel
        h.update(rel.encode())
        h.update(p.read_bytes() if p.exists() else b"<MISSING>")
    return h.hexdigest()


def provenance(code_paths: list[str] | None = None) -> dict:
    """Stamp identifying the run that produced an artifact."""
    dirty = _git("status", "--porcelain")
    return {
        "kind": "run_provenance",
        "commit": _git("rev-parse", "HEAD"),
        "commit_short": _git("rev-parse", "--short", "HEAD"),
        "working_tree_dirty": bool(dirty),
        "dirty_files": [ln[3:] for ln in (dirty or "").splitlines()][:20],
        "code_digest": code_digest(code_paths or []),
        "code_paths": sorted(code_paths or []),
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "host": socket.gethostname(),
        "argv": sys.argv,
        "pid": os.getpid(),
        "law": "VERIFY THE ARTIFACT, NOT THE ECHO",
    }


def verify_artifact_is_current(art: dict, *,
                               code_paths: list[str] | None = None,
                               require_clean: bool = False) -> dict:
    """Refuse to interpret an artifact that a different run produced.

    This is the guard that would have caught reading a previous run's
    output file while the current run was still writing."""
    prov = art.get("provenance")
    if not prov:
        raise StaleArtifact(
            "artifact carries no provenance stamp -- it cannot be "
            "attributed to any run and is therefore not evidence")

    now = provenance(code_paths or prov.get("code_paths") or [])
    problems = []
    if prov.get("commit") != now["commit"]:
        problems.append(
            f"produced at commit {prov.get('commit_short')}, "
            f"current is {now['commit_short']}")
    if code_paths and prov.get("code_digest") != now["code_digest"]:
        problems.append(
            "the code that produced it differs from the code on disk "
            "(uncommitted edit, or a partially-synced host)")
    if require_clean and prov.get("working_tree_dirty"):
        problems.append("produced from a dirty working tree")
    if problems:
        raise StaleArtifact(
            "artifact does not belong to the current run: "
            + "; ".join(problems)
            + ". Re-run before interpreting it -- a stale artifact "
              "reporting zero failures reports nothing at all.")
    return {"verdict": "ARTIFACT_CURRENT",
            "commit": prov.get("commit_short"),
            "code_digest": (prov.get("code_digest") or "")[:16],
            "produced_utc": prov.get("started_utc")}


def verify_source_contains(rel_path: str, *needles: str) -> dict:
    """Prove an intended edit actually landed.

    `str.replace` on a non-matching pattern silently returns the
    original string, so an edit script can print 'installed' having
    changed nothing. Call this instead of believing the print."""
    p = REPO / rel_path
    if not p.exists():
        raise VerificationFailed(f"{rel_path} does not exist")
    text = p.read_text()
    missing = [n for n in needles if n not in text]
    if missing:
        raise VerificationFailed(
            f"{rel_path} is missing {len(missing)} expected change(s): "
            + "; ".join(repr(m[:70]) for m in missing)
            + ". The edit did NOT land -- do not interpret any result "
              "produced by this file.")
    return {"verdict": "SOURCE_CHANGE_PRESENT", "path": rel_path,
            "checked": len(needles)}


def stamp(payload: dict, code_paths: list[str] | None = None) -> dict:
    """Attach provenance to something about to be written to disk."""
    return {**payload, "provenance": provenance(code_paths)}


def load_verified(path: str | Path, *,
                  code_paths: list[str] | None = None) -> dict:
    """Read a result file, refusing it if it is not from this code."""
    art = json.loads(Path(path).read_text())
    art["_verification"] = verify_artifact_is_current(
        art, code_paths=code_paths)
    return art
