"""VERIFY THE EXECUTABLE RELEASE, NOT THE WORKING TREE.

Tuesday's preopen gate exited 1 on two checks -- "git tree clean:
false" and "full suite artifact: false" -- because overnight CHRONOS
development left the mutable repository ahead of the last recorded
test artifact. Meanwhile a fully tested, immutable release sat
activated at /opt/apex/current, entirely unaffected.

The gate was asking about the wrong artifact. Development state and
active runtime state are different things, and confusing them means
either (a) research work disarms trading, or (b) someone deletes the
cleanliness check and loses the real protection. Both are bad.

    DEV STATE            /opt/apex-repo, may be dirty, may be ahead
    ACTIVE RELEASE       /opt/apex/current, immutable, approved

The preopen gate judges the ACTIVE RELEASE and its manifest. A dirty
dev tree is reported as INFORMATIONAL and never blocks.

What still blocks, correctly:
  no manifest, or a manifest that does not match what is deployed
  a release whose full suite did not pass
  a release not in canonical history
  an activation that nobody approved

decision_power: NONE_OPERATIONAL.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

MANIFEST_NAME = "RELEASE_MANIFEST.json"

REQUIRED_FIELDS = ("release_sha", "build_timestamp", "suite_result",
                   "suite_passed", "suite_artifact_hash",
                   "environment_fingerprint", "activated_utc",
                   "approved_by")


class ReleaseGateViolation(RuntimeError):
    pass


def environment_fingerprint(*, python_version: str,
                            key_packages: dict) -> str:
    return hashlib.sha256(json.dumps(
        {"python": python_version, "packages": key_packages},
        sort_keys=True).encode()).hexdigest()[:16]


def build_manifest(*, release_sha: str, suite_result: str,
                   suite_passed: int, suite_artifact_hash: str,
                   environment_fingerprint: str, approved_by: str,
                   build_timestamp: str | None = None) -> dict:
    """A release may only be activated with a complete manifest. Every
    field is required: an unstated suite result is not a passing one."""
    m = {"kind": "apex_release_manifest",
         "release_sha": release_sha,
         "build_timestamp": build_timestamp or datetime.now(
             timezone.utc).isoformat(),
         "suite_result": suite_result,
         "suite_passed": suite_passed,
         "suite_artifact_hash": suite_artifact_hash,
         "environment_fingerprint": environment_fingerprint,
         "activated_utc": datetime.now(timezone.utc).isoformat(),
         "approved_by": approved_by}
    missing = [f for f in REQUIRED_FIELDS if not m.get(f)]
    if missing:
        raise ReleaseGateViolation(
            f"incomplete release manifest, missing {missing}: an "
            f"unstated check is not a passed check")
    if suite_result != "PASS":
        raise ReleaseGateViolation(
            f"a release whose suite result is {suite_result!r} may not "
            f"be built for activation")
    return m


def read_manifest(release_root: Path) -> dict | None:
    p = release_root / MANIFEST_NAME
    if not p.exists():
        return None
    return json.loads(p.read_text())


def preopen_gate(*, active_release_path: Path,
                 canonical_shas: tuple | list,
                 dev_tree_dirty: bool,
                 dev_head_sha: str | None = None,
                 extra_checks: list | None = None) -> dict:
    """The gate that decides whether the session may arm.

    It reads the ACTIVE RELEASE. `dev_tree_dirty` is accepted only so
    it can be reported as informational -- it is structurally
    incapable of blocking here, which is the entire point."""
    checks, blocking = [], []

    def add(name, ok, detail, required=True):
        checks.append({"check": name, "ok": bool(ok), "detail": detail,
                       "required": required})
        if required and not ok:
            blocking.append(name)

    resolved = (active_release_path.resolve()
                if active_release_path.exists() else None)
    add("active release exists", resolved is not None,
        str(resolved or active_release_path))

    man = read_manifest(resolved) if resolved else None
    add("release manifest present", man is not None,
        MANIFEST_NAME if man else "absent")

    if man:
        missing = [f for f in REQUIRED_FIELDS if not man.get(f)]
        add("manifest complete", not missing,
            f"missing {missing}" if missing else "all fields")
        add("release suite passed", man.get("suite_result") == "PASS",
            f"{man.get('suite_result')} "
            f"{man.get('suite_passed')} tests")
        # the manifest must describe the release it actually sits in
        deployed_sha = (resolved.name if resolved else "")
        add("manifest matches deployed release",
            bool(deployed_sha) and man.get("release_sha", "").startswith(
                deployed_sha[:8]) or deployed_sha.startswith(
                man.get("release_sha", "")[:8]),
            f"manifest {str(man.get('release_sha'))[:8]} vs deployed "
            f"{deployed_sha[:8]}")
        add("release in canonical history",
            any(str(man.get("release_sha", "")).startswith(s[:8])
                or s.startswith(str(man.get("release_sha", ""))[:8])
                for s in canonical_shas) if canonical_shas else False,
            "checked against canonical history")
        add("activation approved", bool(man.get("approved_by")),
            str(man.get("approved_by")))

    # INFORMATIONAL ONLY -- development must never disarm the runtime
    checks.append({"check": "dev tree clean", "ok": not dev_tree_dirty,
                   "detail": (f"dev HEAD {dev_head_sha} "
                              f"{'dirty' if dev_tree_dirty else 'clean'}"
                              " (informational: the active release is "
                              "what executes)"),
                   "required": False})

    for c in (extra_checks or []):
        add(c.get("check", "unnamed"), c.get("ok"), c.get("detail", ""),
            c.get("required", True))

    return {"kind": "apex_preopen_gate",
            "evaluated_utc": datetime.now(timezone.utc).isoformat(),
            "active_release": str(resolved) if resolved else None,
            "manifest": man,
            "checks": checks,
            "blocking": blocking,
            "verdict": "GATE_PASS" if not blocking else "GATE_BLOCKED",
            "law": "verify the executable release, not the working "
                   "tree; development state may be dirty without "
                   "disabling the approved runtime",
            "decision_power": "NONE_OPERATIONAL"}
