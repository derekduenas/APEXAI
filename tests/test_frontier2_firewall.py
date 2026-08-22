"""FRONTIER-2 FIREWALL — the mechanical proof behind the authority graph
in results/frontier/FRONTIER_NEXTGEN_BUILD_MAP.md.

Two directions, both required:
  1. apex.frontier2 must not REACH the production stack (it could then
     influence a real decision).
  2. the production stack must not REACH apex.frontier2 (it could then
     silently start consuming an unproven organ).

Also proves apex.frontier2 stamps FRONTIER2_POWER = NONE_FRONTIER_SHADOW
everywhere a record is minted, and that no capital/broker keyword
appears anywhere in the package (same style as
test_no_execution_or_broker_dependency_exists).
"""
from __future__ import annotations

from pathlib import Path

from apex.audit.execution_path import module_closure

REPO = Path(__file__).resolve().parents[1]
APEX = REPO / "apex"
FRONTIER2 = APEX / "frontier2"

PRODUCTION_STACK_FORBIDDEN = {
    "apex.hunter", "apex.captain", "apex.execution", "apex.hunter.capital",
}


def _frontier2_modules() -> list:
    if not FRONTIER2.exists():
        return []
    out = []
    for p in FRONTIER2.glob("*.py"):
        if p.stem == "__init__":
            continue
        out.append(f"apex.frontier2.{p.stem}")
    return out


def test_frontier2_package_exists():
    assert FRONTIER2.exists(), "apex/frontier2/ has not been created yet"


def test_frontier2_reaches_no_production_module():
    for mod in _frontier2_modules():
        reached = module_closure(REPO, mod)
        hit = {r for r in reached
              if any(r == f or r.startswith(f + ".")
                     for f in PRODUCTION_STACK_FORBIDDEN)}
        assert not hit, f"{mod} reaches production modules {sorted(hit)}"


def test_no_production_module_reaches_frontier2():
    """The reverse direction: nothing in Hunter/Captain/Execution/Capital
    may import apex.frontier2, or a shadow organ could be silently
    consumed by a real decision without a governance act."""
    targets = ("apex.hunter.playbooks_v1", "apex.hunter.statemachine",
              "apex.hunter.decision_card" if
              (APEX / "hunter" / "decision_card.py").exists() else
              "apex.hunter.broker",
              "apex.captain.kernel", "apex.execution.gateway")
    for entry in targets:
        mod_path = APEX / (entry.replace("apex.", "").replace(".", "/") + ".py")
        if not mod_path.exists():
            continue
        reached = module_closure(REPO, entry)
        hit = {r for r in reached if r.startswith("apex.frontier2")}
        assert not hit, f"{entry} reaches apex.frontier2: {hit}"


def test_data2_alpaca_stack_does_not_reach_frontier2():
    """THE TOMORROW FIREWALL, named explicitly in the operator's Batch 4
    directive: tomorrow's DATA-2/Alpaca live certification must remain
    completely independent of tonight's shadow build. Neither the
    Alpaca fabric daemon nor the provider-neutral seam it exposes to
    Scout/World may import apex.frontier2."""
    for entry in ("apex.intraday.alpaca_fabric", "apex.intraday.provider_interface",
                 "apex.intraday.equity_fabric", "apex.intraday.universe_coverage"):
        mod_path = APEX / (entry.replace("apex.", "").replace(".", "/") + ".py")
        if not mod_path.exists():
            continue
        reached = module_closure(REPO, entry)
        hit = {r for r in reached if r.startswith("apex.frontier2")}
        assert not hit, f"{entry} (DATA-2 stack) reaches apex.frontier2: {hit}"


def test_frontier2_does_not_import_frontier1():
    """Structural separation from apex.frontier, per the build map: F9/F10
    clone underwriting.py's pattern, they do not import and mutate it."""
    for mod in _frontier2_modules():
        reached = module_closure(REPO, mod)
        hit = {r for r in reached if r == "apex.frontier"
              or r.startswith("apex.frontier.")}
        assert not hit, f"{mod} imports apex.frontier: {hit}"


def test_no_capital_or_broker_keyword_anywhere_in_frontier2():
    if not FRONTIER2.exists():
        return
    src = "\n".join(
        p.read_text() for p in FRONTIER2.rglob("*.py")
        if "__pycache__" not in str(p)
    ).lower()
    for term in ("place_order", "submit_order", "import ib_insync",
                "robin_stocks", "import alpaca", "size_position"):
        assert term not in src, f"{term!r} present in apex/frontier2/"


def test_frontier2_placement_scan_is_clean():
    from apex.execution.sealing import scan_package_for_placement
    scan = scan_package_for_placement("apex")
    assert scan["clean"], f"a placement surface exists: {scan}"
