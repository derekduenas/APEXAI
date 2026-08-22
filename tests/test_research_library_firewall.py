"""RESEARCH LIBRARY FIREWALL — mechanical proof, same discipline as
apex/frontier2's own firewall tests:

  1. apex.research_library reaches no production authority module
     (Hunter/Captain/Execution/Capital) and no credit-consuming
     governance module (ledger, holdout_capacity).
  2. apex.research_library is fully separate from apex.research (the
     existing, credit-gated hypothesis pipeline) -- neither imports
     the other.
  3. No function anywhere in the package takes raw document content and
     hands it to anything ML-shaped (no sklearn/torch/tensorflow import,
     no .fit(), no "feature"/"label" return type from a retrieval call)
     -- the ML prose firewall.
  4. Every research_library test file that writes a ledger redirects to
     an isolated tmp_path -- the test-ledger isolation audit, run
     because the frontier2 curve-ledger bug proved this matters.
"""
from __future__ import annotations

from pathlib import Path

from apex.audit.execution_path import module_closure

REPO = Path(__file__).resolve().parents[1]
APEX = REPO / "apex"
LIBRARY = APEX / "research_library"

PRODUCTION_FORBIDDEN = {"apex.hunter", "apex.captain", "apex.execution",
                        "apex.hunter.capital", "apex.frontier2"}
GOVERNANCE_FORBIDDEN = {"apex.governance.ledger", "apex.governance.holdout_capacity"}


def _library_modules() -> list:
    return [f"apex.research_library.{p.stem}" for p in LIBRARY.glob("*.py")
           if p.stem != "__init__"]


def test_library_package_exists():
    assert LIBRARY.exists()


def test_library_reaches_no_production_authority():
    for mod in _library_modules():
        reached = module_closure(REPO, mod)
        hit = {r for r in reached
              if any(r == f or r.startswith(f + ".") for f in PRODUCTION_FORBIDDEN)}
        assert not hit, f"{mod} reaches production authority: {hit}"


def test_library_reaches_no_credit_governance():
    for mod in _library_modules():
        reached = module_closure(REPO, mod)
        hit = {r for r in reached
              if any(r == f or r.startswith(f + ".") for f in GOVERNANCE_FORBIDDEN)}
        assert not hit, f"{mod} reaches credit-gated governance: {hit}"


def test_library_never_imports_apex_research():
    """apex.research (the existing certified discovery pipeline) and
    apex.research_library (this new knowledge substrate) share a word,
    not a dependency."""
    for mod in _library_modules():
        reached = module_closure(REPO, mod)
        hit = {r for r in reached if r == "apex.research" or r.startswith("apex.research.")}
        assert not hit, f"{mod} imports apex.research: {hit}"


def test_apex_research_never_imports_the_library():
    research_pkg = APEX / "research"
    if not research_pkg.exists():
        return
    for p in research_pkg.glob("*.py"):
        entry = f"apex.research.{p.stem}"
        reached = module_closure(REPO, entry)
        hit = {r for r in reached if r.startswith("apex.research_library")}
        assert not hit, f"{entry} imports apex.research_library: {hit}"


def test_no_production_module_reaches_the_library():
    targets = ("apex.hunter.playbooks_v1", "apex.hunter.statemachine",
              "apex.captain.kernel", "apex.execution.gateway",
              "apex.frontier2.captain_shadow")
    for entry in targets:
        mod_path = APEX / (entry.replace("apex.", "").replace(".", "/") + ".py")
        if not mod_path.exists():
            continue
        reached = module_closure(REPO, entry)
        hit = {r for r in reached if r.startswith("apex.research_library")}
        assert not hit, f"{entry} reaches apex.research_library: {hit}"


def test_no_capital_broker_or_placement_keyword_in_the_library():
    src = "\n".join(p.read_text() for p in LIBRARY.glob("*.py")).lower()
    for term in ("place_order", "submit_order", "import ib_insync", "robin_stocks",
                "import alpaca", "size_position", "risk_frac"):
        assert term not in src, f"{term!r} present in apex/research_library/"


def test_library_placement_scan_is_clean():
    from apex.execution.sealing import scan_package_for_placement
    scan = scan_package_for_placement("apex")
    assert scan["clean"], f"a placement surface exists: {scan}"


# ---- ML prose firewall ---------------------------------------------------

def test_no_ml_library_imported_anywhere_in_the_library():
    src = "\n".join(p.read_text() for p in LIBRARY.glob("*.py")).lower()
    for term in ("import sklearn", "import torch", "import tensorflow",
                "import xgboost", "import lightgbm", ".fit("):
        assert term not in src, f"{term!r} present -- prose-to-alpha shortcut risk"


def test_retrieval_never_returns_an_ml_training_shaped_field():
    """Structural proof: nothing in the retrieval layer's return shapes
    could be mistaken for an ML training artifact. ("label" is
    deliberately NOT checked here -- this codebase already uses that
    word for the RESEARCH_PRIOR provenance tag, a different concept
    from an ML training label.)"""
    import inspect

    from apex.research_library import retrieval
    src = inspect.getsource(retrieval)
    for term in ('"feature"', "'feature'", '"target"', "'target'",
                "feature_vector", "training_label"):
        assert term not in src


# ---- test-ledger isolation audit ------------------------------------------

def test_every_research_library_test_file_isolates_its_ledgers():
    tests_dir = REPO / "tests"
    lib_tests = sorted(tests_dir.glob("test_research_library_*.py"))
    assert len(lib_tests) >= 4, "expected the research_library test suite to exist"
    for f in lib_tests:
        if f.name == "test_research_library_firewall.py":
            continue          # this file itself never writes a ledger
        src = f.read_text()
        writes_ledger = any(fn in src for fn in
                            ("ingest(", "register_mechanism(", "propose(",
                             "mint(", "register_program("))
        if not writes_ledger:
            continue
        assert 'monkeypatch.setattr(' in src and '"LEDGER"' in src, (
            f"{f.name} calls a ledger-writing function but has no visible "
            f"LEDGER monkeypatch -- possible real-ledger contamination, "
            f"exactly the class of bug the frontier2 curve-ledger incident "
            f"proved matters")


def test_real_research_library_results_directory_has_no_test_pollution():
    """After the whole suite runs, results/research_library/ must
    contain only genuine artifacts this session explicitly minted
    (the library birth, program registrations), never stray test rows
    from an unpatched LEDGER."""
    real_dir = REPO / "results" / "research_library"
    if not real_dir.exists():
        return
    # a loose sanity check: no file should contain the literal test
    # fixture title used across this test suite.
    for f in real_dir.glob("*.jsonl"):
        content = f.read_text()
        assert "Test Report" not in content
        assert "Test Mechanism" not in content
