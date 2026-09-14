"""Static reachability over the repo's own modules, for one question: what can this entry point actually execute?

R3 answered "does production sleep?" with grep. Grep cannot distinguish a docstring from a statement, and cannot
follow an import. This walks the AST: it resolves every import a module performs -- including the function-local
imports this repo uses everywhere -- and closes over them, so the answer is about the executable closure rather
than about one file's text.

Two questions it is built to answer, both structurally:
  * is scripts/premarket_run.py reachable from the prepared production entry point? (must be: no)
  * where, in the whole closure, can this path call time.sleep? (must be: only the declared network-retry sites)
"""
from __future__ import annotations

import ast
import pathlib

SCHEMA = "CALL_GRAPH_V1"


def _module_path(root: pathlib.Path, dotted: str):
    rel = dotted.replace(".", "/")
    for cand in (root / (rel + ".py"), root / rel / "__init__.py"):
        if cand.exists():
            return cand
    return None


def _imports(tree: ast.AST) -> set:
    """Every module name this file imports, at module level OR inside a function."""
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                out.add(a.name)
        elif isinstance(n, ast.ImportFrom):
            if n.level:                 # relative import: not used by the premarket path
                continue
            if n.module:
                out.add(n.module)
                for a in n.names:
                    out.add("%s.%s" % (n.module, a.name))
    return out


def closure(entry: str, *, repo=".", extra_dirs=("scripts",)) -> dict:
    """Every repo module transitively reachable from `entry` (a path to a .py file)."""
    root = pathlib.Path(repo).resolve()
    seen, queue, files = set(), [pathlib.Path(entry)], {}
    while queue:
        f = queue.pop()
        key = str(f.resolve().relative_to(root))
        if key in files:
            continue
        try:
            tree = ast.parse(f.read_text())
        except (OSError, SyntaxError):
            continue
        files[key] = tree
        for dotted in _imports(tree):
            p = _module_path(root, dotted)
            if p is None:
                for d in extra_dirs:
                    p = _module_path(root / d, dotted)
                    if p is not None:
                        break
            if p is not None and str(p.resolve().relative_to(root)) not in files:
                queue.append(p)
    return files


def sleep_sites(files: dict) -> list:
    """Executable `time.sleep(...)` / bare `sleep(...)` CALL nodes. A docstring that quotes the defect is text and
    is not a call; this cannot confuse the two."""
    out = []
    for name, tree in sorted(files.items()):
        for n in ast.walk(tree):
            if not isinstance(n, ast.Call):
                continue
            f = n.func
            dotted = None
            if isinstance(f, ast.Attribute) and f.attr == "sleep":
                base = f.value
                dotted = "%s.sleep" % (base.id if isinstance(base, ast.Name) else "?")
            elif isinstance(f, ast.Name) and f.id == "sleep":
                dotted = "sleep"
            if dotted:
                out.append({"module": name, "line": n.lineno, "call": dotted})
    return out


def reaches(files: dict, needle: str) -> bool:
    return any(needle in k for k in files)


def report(entry: str, *, repo=".") -> dict:
    files = closure(entry, repo=repo)
    return {"schema": SCHEMA, "entry": entry, "modules": sorted(files),
            "module_count": len(files), "sleep_sites": sleep_sites(files),
            "reaches_legacy_runner": reaches(files, "scripts/premarket_run.py")}
