"""OPTION ANALYTICS FIREWALL — same discipline as the options_research
and research_library firewall suites:

  1. apex.option_analytics reaches no production authority module
     (Hunter/Captain/Execution/Capital) and no live Frontier-2 code.
  2. apex.option_analytics reaches no credit-consuming governance
     module.
  3. apex.option_analytics contains no broker client or order-
     placement keyword, and never imports an Alpaca/Robinhood SDK --
     it is pure numerical computation over caller-supplied inputs, it
     fetches nothing itself.
  4. No production module reaches back into it.
  5. Every option_analytics test file that writes a certification
     ledger redirects to an isolated tmp_path.
"""
from __future__ import annotations

from pathlib import Path

from apex.audit.execution_path import module_closure

REPO = Path(__file__).resolve().parents[1]
APEX = REPO / "apex"
PKG = APEX / "option_analytics"

PRODUCTION_FORBIDDEN = {"apex.hunter", "apex.captain", "apex.execution",
                        "apex.hunter.capital", "apex.frontier2"}
GOVERNANCE_FORBIDDEN = {"apex.governance.ledger", "apex.governance.holdout_capacity"}


def _pkg_modules() -> list:
    return [f"apex.option_analytics.{p.stem}" for p in PKG.glob("*.py")
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


def test_no_production_module_reaches_option_analytics():
    targets = ("apex.hunter.playbooks_v1", "apex.hunter.statemachine",
              "apex.captain.kernel", "apex.execution.gateway",
              "apex.frontier2.captain_shadow")
    for entry in targets:
        mod_path = APEX / (entry.replace("apex.", "").replace(".", "/") + ".py")
        if not mod_path.exists():
            continue
        reached = module_closure(REPO, entry)
        hit = {r for r in reached if r.startswith("apex.option_analytics")}
        assert not hit, f"{entry} reaches apex.option_analytics: {hit}"


def test_no_broker_sdk_or_network_fetch():
    src = "\n".join(p.read_text() for p in PKG.glob("*.py")).lower()
    for term in ("place_order", "submit_order", "import ib_insync", "robin_stocks",
                "import alpaca", "mcp__robinhood", "urllib.request", "requests.get",
                "requests.post"):
        assert term not in src, f"{term!r} present in apex/option_analytics/"


def test_no_ml_library_imported():
    src = "\n".join(p.read_text() for p in PKG.glob("*.py")).lower()
    for term in ("import sklearn", "import torch", "import tensorflow",
                "import xgboost", "import lightgbm"):
        assert term not in src, f"{term!r} present in apex/option_analytics/"


def test_every_module_stamps_option_analytics_power_where_it_carries_decision_power():
    for p in PKG.glob("*.py"):
        if p.stem == "__init__":
            continue
        src = p.read_text()
        if "decision_power" in src:
            assert "OPTION_ANALYTICS_POWER" in src, (
                f"{p.name} references decision_power without importing "
                f"the package-level OPTION_ANALYTICS_POWER constant")


def test_options_research_may_import_option_analytics_but_not_vice_versa():
    """The one legitimate coupling: options_research reads
    option_analytics's OUTPUT contracts directly (a plain Python
    import is fine here -- unlike Frontier-2, option_analytics holds
    no live authority of its own to firewall against). The reverse
    must never happen."""
    for mod in _pkg_modules():
        reached = module_closure(REPO, mod)
        hit = {r for r in reached if r.startswith("apex.options_research")}
        assert not hit, f"{mod} reaches apex.options_research: {hit}"


def test_every_option_analytics_test_file_isolates_its_ledgers():
    tests_dir = REPO / "tests"
    pkg_tests = sorted(tests_dir.glob("test_option_analytics_*.py"))
    assert len(pkg_tests) >= 6, "expected the option_analytics test suite to exist"
    for f in pkg_tests:
        if f.name == "test_option_analytics_firewall.py":
            continue
        src = f.read_text()
        writes_ledger = "record_certification(" in src
        if not writes_ledger:
            continue
        assert 'monkeypatch.setattr(' in src and '"LEDGER"' in src, (
            f"{f.name} calls record_certification() but has no visible "
            f"LEDGER monkeypatch -- possible real-ledger contamination")
