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


# Each registered experiment's entry module, the signal it MUST compute, and
# the machinery it must NOT reach. #001 is closed; its entry is retained so a
# change to the live path cannot quietly alter the code that produced its
# recorded result.
EXPERIMENT_ENTRY = {
    "APEX-001": "apex.pipeline",
    "APEX-002": "apex.experiments.apex002",
    "APEX-003": "apex.experiments.apex003",
    # #004 deliberately shares #003's entry: same signal, same certified path;
    # the protocols differ only in the config universe (section 3 + ceiling).
    "APEX-004": "apex.experiments.apex003",
}

EXPERIMENT_REQUIRES = {
    "APEX-001": frozenset({"apex.features.composite"}),
    "APEX-002": frozenset({"apex.features.nsi", "apex.features.nsi_scores"}),
    "APEX-003": frozenset({"apex.experiments.apex003", "apex.features.factory"}),
    "APEX-004": frozenset({"apex.experiments.apex003", "apex.features.factory"}),
}

EXPERIMENT_FORBIDS = {
    "APEX-001": frozenset(),
    "APEX-002": frozenset({
        "apex.features.composite",
        "apex.features.f1_momentum",
        "apex.features.f2_trend",
        "apex.features.f3_volatility",
        "apex.features.f4_relative_strength",
    }),
    "APEX-003": frozenset({
        "apex.features.composite",       # #001 scorer
        "apex.features.nsi_scores",      # #002 scorer
        "apex.features.nsi",
    }),
    "APEX-004": frozenset({
        "apex.features.composite",       # #001 scorer
        "apex.features.nsi_scores",      # #002 scorer
        "apex.features.nsi",
    }),
}


def certify_experiment(root: Path, experiment: str) -> list[str]:
    """Findings for one experiment's execution path. Empty when it conforms."""
    if experiment not in EXPERIMENT_ENTRY:
        return [f"no execution path is registered for {experiment!r}"]

    closure = module_closure(root, EXPERIMENT_ENTRY[experiment])
    findings = []

    for required in sorted(EXPERIMENT_REQUIRES[experiment]):
        if required not in closure:
            findings.append(
                f"{experiment}: entry {EXPERIMENT_ENTRY[experiment]} does not "
                f"reach {required}; the registered signal is never computed"
            )
    for forbidden in sorted(EXPERIMENT_FORBIDS[experiment]):
        if forbidden in closure:
            findings.append(
                f"{experiment}: entry {EXPERIMENT_ENTRY[experiment]} reaches "
                f"{forbidden}, which belongs to another experiment"
            )
    return findings


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


def executable_source(source: str) -> str:
    """Source with docstrings and comments removed, leaving only what runs.

    THE single definition. Three separate scans have now been written that
    matched a module's own prose: `nsi.py` documents why `.last()` is
    forbidden, `nsi_scores.py` documents that it does not call `build_scores`,
    and the Step 3 certification read both. A scan that reads documentation
    reports the prohibition as a violation of itself.

    Note the token join drops original whitespace, so multi-token literals must
    be matched whitespace-normalised.
    """
    import io
    import tokenize

    tree = ast.parse(source)
    docstrings = {
        ast.get_docstring(node, clean=False)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef))
    }
    return "".join(
        tok.string
        for tok in tokenize.generate_tokens(io.StringIO(source).readline)
        if tok.type != tokenize.COMMENT
        and not (tok.type == tokenize.STRING and tok.string.strip("\"'") in docstrings)
    )
