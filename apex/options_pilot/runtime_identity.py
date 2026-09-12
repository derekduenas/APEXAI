"""RUNTIME RELEASE IDENTITY, measured at process start (Brick 1, weekend commissioning).

A source-text `git_commit` description is not a release identity. This records what the running process can
actually observe: the git commit of the code tree it imports from (or NOT_A_GIT_CHECKOUT), whether that tree is
dirty, content digests of the modules on the decision path, the versions of the third-party packages it imports,
the interpreter, and the digests of the configuration/parameter artifacts it was handed. The SCOPE line says what
is and is not covered: this is the identity of the code and artifacts the process loaded, not proof that the host
installed them from a reviewed release (that is the deployment package's job)."""
from __future__ import annotations

import hashlib
import importlib
import os
import platform
import subprocess
import sys
from pathlib import Path

DECISION_PATH_MODULES = ("apex.options_pilot.session", "apex.options_pilot.boundary", "apex.options_pilot.records",
                         "apex.options_pilot.expression_rule", "apex.options_pilot.risk_authority", "apex.options_pilot.fees",
                         "apex.options_pilot.exit_policy", "apex.options_pilot.entrypoint", "apex.pulse_options.sources",
                         "apex.pulse_options.providers", "apex.decision_wb.engine", "apex.decision_wb.supervision",
                         "apex.joint_wb.engine", "apex.joint_wb.state", "apex.organism.risk_certificate", "apex.organism.risk_kernel")
DEPENDENCIES = ("numpy", "scipy", "pandas")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(root: Path, *args) -> str | None:
    try:
        r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def runtime_identity(artifacts: dict | None = None) -> dict:
    """artifacts: {name: path} of configuration / parameter files the process was handed; each is digested."""
    import apex
    root = Path(apex.__file__).resolve().parent.parent
    commit = _git(root, "rev-parse", "HEAD")
    dirty = _git(root, "status", "--porcelain", "--untracked-files=no")
    mods = {}
    for name in DECISION_PATH_MODULES:
        try:
            m = importlib.import_module(name)
            mods[name] = _sha(Path(m.__file__))
        except Exception as e:                                             # noqa: BLE001 - an unimportable module is recorded, not hidden
            mods[name] = "UNIMPORTABLE: %s" % type(e).__name__
    deps = {}
    for d in DEPENDENCIES:
        try:
            deps[d] = importlib.import_module(d).__version__
        except Exception:                                                  # noqa: BLE001
            deps[d] = "NOT_IMPORTABLE"
    arts = {}
    for name, p in (artifacts or {}).items():
        p = Path(p)
        arts[name] = {"path": str(p), "sha256": _sha(p) if p.exists() else "MISSING"}
    tree_digest = hashlib.sha256("".join("%s=%s" % kv for kv in sorted(mods.items())).encode()).hexdigest()
    return {
        "kind": "RUNTIME_IDENTITY",
        "code_root": str(root),
        "git_commit": commit or "NOT_A_GIT_CHECKOUT",
        "git_dirty": (bool(dirty) if dirty is not None else None),
        "git_branch": _git(root, "branch", "--show-current"),
        "decision_path_module_digests": mods, "decision_path_tree_digest": tree_digest,
        "dependencies": deps,
        "interpreter": {"executable": sys.executable, "python": sys.version.split()[0], "platform": platform.platform()},
        "host": platform.node(), "pid": os.getpid(),
        "artifacts": arts,
        "scope": ("identity of the code tree and artifacts THIS process loaded at start, measured by the process; it does not "
                  "prove the host installed them from a reviewed release, and modules outside DECISION_PATH_MODULES are not digested"),
    }
