"""ARCHITECTURE ACCEPTANCE — is the shadow research actually fenced?

Run before declaring APEX_MAJOR_ARCHITECTURE closed, and again after any
change that touches Catalyst, Capital or V1.

EVERY CHECK LOOKS AT STRUCTURE, NOT PROSE. An earlier version of this
harness searched source text for the words "catalyst" and "authorize"
and produced two false alarms off English sentences in docstrings. A
comment saying "this cannot authorize anything" is not a call site.
Coupling is an import; a mutating surface is a definition. Parse, do
not grep.
"""
from __future__ import annotations

import ast
import hashlib
import pathlib
import subprocess
import sys

V1_ROOTS = ("apex/predators", "scripts/options_paper_session.py")
SHADOW_PACKAGES = ("apex/catalyst", "apex/capital")
SHADOW_PREFIXES = ("apex.catalyst", "apex.capital")

# names that would mean the shadow layer can DO something
MUTATING_NAMES = {"place_order", "submit_order", "attack", "promote",
                  "apply", "execute", "authorize", "size_position",
                  "cancel_order"}


def _py(root: str):
    p = pathlib.Path(root)
    return sorted(p.rglob("*.py")) if p.is_dir() else [p]


def _imports(tree: ast.AST):
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            yield from (a.name for a in n.names)
        elif isinstance(n, ast.ImportFrom):
            yield n.module or ""


def check_noninterference() -> tuple[bool, str]:
    """No V1 module may import the shadow layer."""
    v1 = [p for r in V1_ROOTS for p in _py(r)]
    bad = [f"{p}:{m}" for p in v1
           for m in _imports(ast.parse(p.read_text()))
           if m.startswith(SHADOW_PREFIXES)]
    return not bad, (f"{len(v1)} V1 modules AST-parsed, 0 shadow imports"
                     if not bad else "; ".join(bad))


def check_no_mutating_surface() -> tuple[bool, str]:
    """The shadow layer may not DEFINE or CALL anything that acts."""
    hits = []
    for p in (q for r in SHADOW_PACKAGES for q in _py(r)):
        for n in ast.walk(ast.parse(p.read_text())):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                    and n.name in MUTATING_NAMES:
                hits.append(f"{p.name} defines {n.name}()")
            if isinstance(n, ast.Call):
                f = n.func
                name = (f.id if isinstance(f, ast.Name)
                        else f.attr if isinstance(f, ast.Attribute)
                        else None)
                if name in MUTATING_NAMES:
                    hits.append(f"{p.name} calls {name}()")
    return not hits, ("no acting function defined or called"
                      if not hits else "; ".join(hits))


def check_tier3() -> tuple[bool, str]:
    """Tier 3 must refuse, and must refuse WITH an approval argument."""
    from apex.governor.authority import AuthorityViolation, authorize
    notes = []
    for kw in ({}, {"operator_approval": "OPERATOR_SAYS_YES"}):
        try:
            authorize("promote_edge_dna", **kw)
            return False, f"NOT LOCKED — returned with {kw!r}"
        except AuthorityViolation:
            notes.append("refused" if not kw
                         else "refused even with operator_approval")
        except TypeError:
            notes.append("operator_approval is not a parameter")
    return True, " | ".join(notes)


def check_prompt_hash() -> tuple[bool, str]:
    from apex.catalyst.brain import PROMPT_CONTRACT, PROMPT_CONTRACT_SHA
    n = len(PROMPT_CONTRACT_SHA)
    h = hashlib.sha256(PROMPT_CONTRACT.encode()).hexdigest()[:n]
    return h == PROMPT_CONTRACT_SHA, (
        f"recomputed {h} == declared {PROMPT_CONTRACT_SHA} ({n} hex)")


def check_authorities() -> tuple[bool, str]:
    from apex.capital import AUTHORITY as CAP
    from apex.catalyst import AUTHORITY as CAT
    ok = (CAT == "SHADOW_CONTEXT_ONLY"
          and CAP == "SHADOW_COUNTERFACTUAL_ONLY")
    return ok, f"catalyst={CAT} capital={CAP}"


def check_isolation() -> tuple[bool, str]:
    from apex.capital.counterfactual import LEDGER
    v1 = pathlib.Path("results/outbox/v1_decisions.jsonl")
    return (str(LEDGER) != str(v1) and "capital" in str(LEDGER),
            f"shadow={LEDGER} v1={v1}")


def tree_digest(root: str = ".") -> str:
    """Deterministic digest of the Python surface. Comparable across
    machines, which is the only way to prove the code running in the
    cloud is the code that was reviewed here."""
    h = hashlib.sha256()
    base = pathlib.Path(root)
    for p in sorted(base.rglob("*.py")):
        rel = p.relative_to(base).as_posix()
        if rel.startswith((".venv/", "venv/")) or "__pycache__" in rel:
            continue
        h.update(rel.encode())
        h.update(hashlib.sha256(p.read_bytes()).digest())
    return h.hexdigest()[:16]


def check_lineage(expected: str | None) -> tuple[bool, str]:
    """Prove WHICH code this is.

    A git checkout proves it by HEAD plus a clean tree. A deployed
    release is not a checkout, and an earlier version of this check
    read git's empty output there as "clean" and PASSED on no evidence
    at all. An unverifiable lineage is a FAIL, never a pass.
    """
    def git(*a):
        r = subprocess.run(("git",) + a, capture_output=True, text=True)
        return r.stdout.strip() if r.returncode == 0 else ""

    digest = tree_digest()
    head = git("rev-parse", "HEAD")

    if head:                                   # development checkout
        dirty = git("status", "--porcelain")
        ok = not dirty and (expected is None or head == expected)
        return ok, (f"checkout {head[:8]}, tree "
                    + ("clean" if not dirty else "DIRTY")
                    + (f", expected {expected[:8]}" if expected else "")
                    + f", py_digest {digest}")

    stamp = pathlib.Path("RELEASE.json")       # immutable release
    if not stamp.exists():
        return False, ("NOT_VERIFIABLE — no git HEAD and no "
                       "RELEASE.json; refusing to call this clean")
    import json
    commit = json.loads(stamp.read_text()).get("commit", "")
    here = pathlib.Path.cwd().resolve().name
    if not commit:
        return False, "RELEASE.json carries no commit"
    if here != commit and here != "current":
        return False, f"RELEASE.json {commit[:8]} != directory {here[:8]}"
    ok = expected is None or commit == expected
    return ok, (f"release {commit[:8]} stamped, py_digest {digest}"
                + ("" if expected is None
                   else f", expected {expected[:8]}"))


CHECKS = (("CATALYST/CAPITAL_AUTHORITY", check_authorities),
          ("CATALYST_V1_NONINTERFERENCE", check_noninterference),
          ("CAPITAL_V1_NONINTERFERENCE", check_noninterference),
          ("NO_MUTATING_SURFACE", check_no_mutating_surface),
          ("TIER3_LOCK", check_tier3),
          ("RESOURCE_ISOLATION", check_isolation),
          ("PROMPT_CONTRACT_HASH", check_prompt_hash))


def main(expected_release: str | None = None) -> int:
    rows = [(k, *fn()) for k, fn in CHECKS]
    rows.append(("HASH_LINEAGE", *check_lineage(expected_release)))
    w = max(len(r[0]) for r in rows)
    for k, ok, note in rows:
        print(f"{k:<{w}}  {'PASS' if ok else 'FAIL'}  {note}")
    allok = all(r[1] for r in rows)
    print("\n" + ("ARCHITECTURE ACCEPTANCE: ALL PASS"
                  if allok else "ARCHITECTURE ACCEPTANCE: FAILED"))
    return 0 if allok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else None))
