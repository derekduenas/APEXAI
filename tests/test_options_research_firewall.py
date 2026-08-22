"""OPTIONS RESEARCH FIREWALL — mechanical proof, same discipline as the
Frontier-2 and Research Library firewall tests (F O28):

  1. apex.options_research reaches no production authority module
     (Hunter/Captain/Execution/Capital) and no live Frontier-2 code --
     it reads Frontier-2's PERSISTED LEDGER FILES via plain file I/O,
     never by importing apex.frontier2 modules.
  2. apex.options_research reaches no credit-consuming governance
     module (no confirmatory experiment credits are ever spent).
  3. apex.options_research never places an order or imports a broker
     client -- CONSERVATIVE_TAKER fills are arithmetic over caller-
     supplied bid/ask, never a live quote fetch or order submission.
  4. No production module (Hunter/Captain/Execution/Capital/Frontier-2)
     ever reaches back INTO apex.options_research -- Options Research
     can be read from, but reads nothing it did not ask for and grants
     nothing back.
  5. Every options_research test file that writes a ledger redirects
     to an isolated tmp_path (the Curve-ledger-bug discipline).
"""
from __future__ import annotations

from pathlib import Path

from apex.audit.execution_path import module_closure

REPO = Path(__file__).resolve().parents[1]
APEX = REPO / "apex"
PKG = APEX / "options_research"

PRODUCTION_FORBIDDEN = {"apex.hunter", "apex.captain", "apex.execution",
                        "apex.hunter.capital", "apex.frontier2"}
GOVERNANCE_FORBIDDEN = {"apex.governance.ledger", "apex.governance.holdout_capacity"}


def _pkg_modules() -> list:
    return [f"apex.options_research.{p.stem}" for p in PKG.glob("*.py")
           if p.stem != "__init__"]


def test_package_exists():
    assert PKG.exists()


def test_reaches_no_production_authority():
    for mod in _pkg_modules():
        reached = module_closure(REPO, mod)
        hit = {r for r in reached
              if any(r == f or r.startswith(f + ".") for f in PRODUCTION_FORBIDDEN)}
        assert not hit, f"{mod} reaches production authority: {hit}"


def test_reaches_no_credit_governance():
    for mod in _pkg_modules():
        reached = module_closure(REPO, mod)
        hit = {r for r in reached
              if any(r == f or r.startswith(f + ".") for f in GOVERNANCE_FORBIDDEN)}
        assert not hit, f"{mod} reaches credit-gated governance: {hit}"


def test_no_production_module_reaches_options_research():
    targets = ("apex.hunter.playbooks_v1", "apex.hunter.statemachine",
              "apex.captain.kernel", "apex.execution.gateway",
              "apex.frontier2.captain_shadow")
    for entry in targets:
        mod_path = APEX / (entry.replace("apex.", "").replace(".", "/") + ".py")
        if not mod_path.exists():
            continue
        reached = module_closure(REPO, entry)
        hit = {r for r in reached if r.startswith("apex.options_research")}
        assert not hit, f"{entry} reaches apex.options_research: {hit}"


def test_no_broker_client_or_order_placement_keyword():
    """`risk_frac` is deliberately NOT in this list: growth_panel.py
    uses it as a local variable name inside a bootstrap RESEARCH
    simulation (sizing_authority="NONE" hardcoded on every output,
    label=RESEARCH_SCENARIO_NOT_PRODUCTION_SIZING) -- it never reaches
    a live position-sizing call, so banning the bare substring here
    would be a false-positive tripwire, not a real firewall check."""
    src = "\n".join(p.read_text() for p in PKG.glob("*.py")).lower()
    for term in ("place_order", "submit_order", "import ib_insync", "robin_stocks",
                "import alpaca", "size_position", "place_option_order",
                "mcp__robinhood"):
        assert term not in src, f"{term!r} present in apex/options_research/"


def test_placement_scan_is_clean():
    from apex.execution.sealing import scan_package_for_placement
    scan = scan_package_for_placement("apex")
    assert scan["clean"], f"a placement surface exists: {scan}"


def test_no_ml_library_imported():
    src = "\n".join(p.read_text() for p in PKG.glob("*.py")).lower()
    for term in ("import sklearn", "import torch", "import tensorflow",
                "import xgboost", "import lightgbm", ".fit("):
        assert term not in src, f"{term!r} present in apex/options_research/"


def test_every_module_stamps_none_options_research_where_it_carries_decision_power():
    for p in PKG.glob("*.py"):
        if p.stem in ("__init__",):
            continue
        src = p.read_text()
        if "decision_power" in src:
            assert "OPTIONS_RESEARCH_POWER" in src, (
                f"{p.name} references decision_power without importing "
                f"the package-level OPTIONS_RESEARCH_POWER constant")


def test_forward_distribution_reads_frontier2_only_as_files_not_imports():
    """The one legitimate coupling to Frontier-2 is read-only file I/O
    against its persisted ledgers -- never a Python import of
    apex.frontier2 itself."""
    src = (PKG / "forward_distribution.py").read_text()
    assert "import apex.frontier2" not in src
    assert "from apex.frontier2" not in src
    assert "results/frontier2/" in src


# ---- test-ledger isolation audit ------------------------------------------

def test_every_options_research_test_file_isolates_its_ledgers():
    tests_dir = REPO / "tests"
    pkg_tests = sorted(tests_dir.glob("test_options_research_*.py"))
    assert len(pkg_tests) >= 6, "expected the options_research test suite to exist"
    for f in pkg_tests:
        if f.name == "test_options_research_firewall.py":
            continue
        src = f.read_text()
        writes_ledger = any(fn in src for fn in
                            ("mint(", "seal(", "resolve_horizon(",
                             "resolve_all_due_horizons(", "mint_all("))
        if not writes_ledger:
            continue
        assert 'monkeypatch.setattr(' in src and '"LEDGER"' in src, (
            f"{f.name} calls a ledger-writing function but has no visible "
            f"LEDGER monkeypatch -- possible real-ledger contamination, "
            f"exactly the class of bug the frontier2 curve-ledger incident "
            f"proved matters")


def test_real_options_research_results_directory_has_no_test_pollution():
    real_dir = REPO / "results" / "options_research"
    if not real_dir.exists():
        return
    for f in real_dir.glob("*.jsonl"):
        content = f.read_text()
        assert "OPP-1" not in content
        assert "OPP-2" not in content
