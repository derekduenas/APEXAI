"""Does the gated production path actually compute the REGISTERED signal?

Every conformance test in `test_nsi_conformance.py` examines `apex.features.nsi`
directly. All of them can pass while the production pipeline never calls that
module -- the tests would be certifying a component that nothing executes.

This audit answers a different question from "is the NSI implementation
correct": it asks whether the code that `scripts/run_validation.py` runs is the
code the conformance suite certified. A signal module that no gated path reaches
is not an implementation of the experiment; it is a library.

The walk is STATIC on purpose. Importing `apex.pipeline` and inspecting it at
runtime would prove only that the module loads, not that the signal is reachable
from the entry point that the ledger records a result for.
"""

from __future__ import annotations

import ast
from pathlib import Path

PACKAGE = "apex"


def _module_path(root: Path, module: str) -> Path | None:
    rel = module.replace(".", "/")
    for candidate in (root / f"{rel}.py", root / rel / "__init__.py"):
        if candidate.exists():
            return candidate
    return None


def module_closure(root: Path, entry: str) -> set[str]:
    """Every `apex.*` module transitively importable from `entry`."""
    seen: set[str] = set()
    stack = [entry]

    while stack:
        module = stack.pop()
        if module in seen:
            continue
        path = _module_path(root, module)
        if path is None:
            continue
        seen.add(module)

        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith(PACKAGE):
                        stack.append(alias.name)
            elif isinstance(node, ast.ImportFrom) and node.module:
                if not node.module.startswith(PACKAGE):
                    continue
                stack.append(node.module)
                # `from apex.features import nsi` -- the module is the NAME.
                for alias in node.names:
                    stack.append(f"{node.module}.{alias.name}")

    return seen


def certify_signal_wiring(closure: set[str], required: str, forbidden: str) -> list[str]:
    """Findings, empty when the wiring conforms.

    `required` -- the registered experiment's signal module, which the gated
    path MUST reach. `forbidden` -- a closed experiment's scoring machinery,
    which it must NOT.
    """
    findings = []
    if required not in closure:
        findings.append(
            f"the gated execution path does not reach {required}: the registered "
            f"signal is never computed by the code that produces a recorded result"
        )
    if forbidden in closure:
        findings.append(
            f"the gated execution path reaches {forbidden}: a closed experiment's "
            f"scoring machinery is inside the live path"
        )
    return findings
