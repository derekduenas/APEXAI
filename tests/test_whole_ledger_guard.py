"""WHOLE-LEDGER RUNTIME GUARD.

THE LAW
-------
APPEND-ONLY EVIDENCE IS NOT AN OPERATIONAL STATE DATABASE.

A recurring runtime path must consume bounded windows, indexes,
checkpoints or incremental cursors -- never the whole ledger.

WHY
---
Five production/repeating paths have exhibited this, each discovered
only after it caused damage:

  mirror_run.py            read_text() on a 2.1 GB twin ledger; would
                           have OOM-killed live PULSE to run the gate
  rolling.restore          whole journal every cycle; startup 1.35s ->
                           57.59s (42.6x) in one session
  premarket.restore        same, same session
  btc_paper._rows          ~350 MB every 30s; 243 OOM kills, 35 hours
                           with zero decisions produced
  btc_window_resolver      261 MB every 30 min; hit its hard cap 8,647
                           times

At five occurrences this is a systemic pattern, not five bugs. A static
check cannot prove complexity, but it can catch the exact shape that
has already burned us five times.

SCOPE
-----
Flags whole-file reads of APPEND-ONLY EVIDENCE (.jsonl ledgers/journals)
inside repeating runtime paths. Bounded config/reference reads (.json,
.toml, small fixtures) are explicitly permitted.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO = Path("/opt/apex-repo")

# Paths that legitimately read whole files: tests, one-shot analysis,
# migrations, and the audit tooling written to investigate this very
# defect.
EXEMPT_DIRS = {"tests", "docs", "results", ".git", "__pycache__"}

# Evidence-shaped names. These grow without bound by design.
EVIDENCE_HINT = re.compile(
    r"(ledger|journal|_log|jsonl|evidence|outcomes|twin)", re.I)

# Calls that pull an entire file into memory.
#   read_text() / readlines()  -- always whole-file
#   read()                     -- whole-file ONLY when unbounded;
#                                 read(n) is a bounded window and is
#                                 exactly what we want people to use
WHOLE_FILE_CALLS = {"read_text", "readlines", "read"}


def _is_unbounded(node) -> bool:
    """.read(n) is bounded; bare .read() is not."""
    if node.func.attr == "read":
        return not node.args
    return True

# Registered legacy offenders: known, sealed, scheduled for repair.
# Listing them here is deliberate -- the guard must FAIL if a NEW one
# appears, while not blocking the tree on repairs that are gated on
# other evidence.
KNOWN_UNREPAIRED = {
    "scripts/btc_window_resolver.py",   # 261 MB / 30 min; cap hit 8,647x
    "scripts/btc_paper_session.py",     # decommissioned 2026-09-02
    "scripts/mirror_run.py",            # superseded by a streaming driver
    "apex/pulse/rolling.py",            # superseded by PULSE_BOUNDED_STATE_V1
    "apex/pulse/premarket.py",          # superseded by PULSE_BOUNDED_STATE_V1
    "scripts/alpaca_fabric_daemon.py",  # BLOCKED pending RTH profile
}


def _py_files() -> list[Path]:
    out = []
    for base in ("apex", "scripts"):
        d = REPO / base
        if not d.exists():
            continue
        for p in d.rglob("*.py"):
            if any(part in EXEMPT_DIRS for part in p.parts):
                continue
            out.append(p)
    return sorted(out)


def _repeating_functions(tree: ast.AST) -> set[int]:
    """Line ranges inside `while True:` / `for ...: sleep()` loops."""
    lines: set[int] = set()
    for node in ast.walk(tree):
        is_loop = isinstance(node, (ast.While, ast.For))
        if not is_loop:
            continue
        src = ast.dump(node)
        # a loop that sleeps is a repeating runtime path
        if "'sleep'" not in src and not isinstance(
                getattr(node, "test", None), ast.Constant):
            continue
        for sub in ast.walk(node):
            if hasattr(sub, "lineno"):
                lines.add(sub.lineno)
    return lines


def _whole_ledger_reads(path: Path) -> list[str]:
    try:
        src = path.read_text()
        tree = ast.parse(src)
    except (SyntaxError, UnicodeDecodeError, OSError):
        return []
    repeating = _repeating_functions(tree)
    if not repeating:
        return []
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if not isinstance(fn, ast.Attribute) or \
                fn.attr not in WHOLE_FILE_CALLS:
            continue
        if not _is_unbounded(node):
            continue
        if node.lineno not in repeating:
            continue
        seg = ast.get_source_segment(src, node) or ""
        # widen slightly: the receiver name usually carries the hint
        ctx = src.splitlines()[max(0, node.lineno - 2):node.lineno + 1]
        blob = seg + " " + " ".join(ctx)
        if EVIDENCE_HINT.search(blob):
            hits.append(f"{path.relative_to(REPO)}:{node.lineno}: "
                        f"{seg[:70]}")
    return hits


def test_no_new_whole_ledger_read_in_a_repeating_runtime_path():
    """A NEW occurrence of the pattern fails the build."""
    offenders = {}
    for p in _py_files():
        hits = _whole_ledger_reads(p)
        if hits:
            offenders[str(p.relative_to(REPO))] = hits
    new = {k: v for k, v in offenders.items()
           if k not in KNOWN_UNREPAIRED}
    assert not new, (
        "APPEND-ONLY EVIDENCE IS NOT AN OPERATIONAL STATE DATABASE.\n"
        "New whole-ledger read(s) in a repeating runtime path:\n"
        + "\n".join(f"  {h}" for hits in new.values() for h in hits)
        + "\n\nUse a bounded window, an index, a checkpoint or an "
          "incremental cursor. This pattern has already caused 5 "
          "production failures.")


def test_every_registered_offender_still_exists():
    """A register entry for a deleted file is a stale exemption.

    This deliberately does NOT assert that the AST detector still flags
    each entry. The detector is a heuristic tuned to the obvious shape;
    the register is human-verified truth and is the stricter of the
    two. Requiring them to agree would weaken the register down to the
    detector's precision.
    """
    missing = {r for r in KNOWN_UNREPAIRED if not (REPO / r).exists()}
    assert not missing, (
        "registered offenders no longer present -- remove them from "
        f"KNOWN_UNREPAIRED: {sorted(missing)}")


def test_pulse_v1_minute_path_reads_no_ledger():
    """The V1 runtime must never acquire the defect it was built to
    eliminate."""
    p = REPO / "apex/pulse/runtime_v1.py"
    assert p.exists()
    hits = _whole_ledger_reads(p)
    assert not hits, hits
    # Check the CODE, not the prose. runtime_v1's module docstring
    # carries a V0-vs-V1 comparison table that mentions read_text()
    # precisely BECAUSE V1 abolished it -- string matching on raw
    # source flags the documentation of the fix as the defect itself.
    tree = ast.parse(p.read_text())
    minute_path = {"run_cycle", "restore", "_prev_cycle_hash"}
    bad = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        if node.name not in minute_path:
            continue
        for sub in ast.walk(node):
            if (isinstance(sub, ast.Call)
                    and isinstance(sub.func, ast.Attribute)
                    and sub.func.attr in WHOLE_FILE_CALLS
                    and _is_unbounded(sub)):
                bad.append(f"{node.name}:{sub.lineno} "
                           f".{sub.func.attr}()")
    assert not bad, (
        f"PULSE_V1 minute path must not read a whole file: {bad}")


def test_checkpoint_module_declares_the_law():
    src = (REPO / "apex/pulse/checkpoint.py").read_text()
    assert "OPERATIONAL WORKING STATE" in src
