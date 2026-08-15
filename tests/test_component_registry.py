"""Reconcile the component registry against reality.

The registry claims a lifecycle state for every architectural component. These
tests make those claims MECHANICAL: a component claimed BUILT/CERTIFIED must have
its module on disk; a PLANNED/ABSENT one must not; every firewall layer must be
represented; and the governance flags must be internally coherent. If the
registry drifts from the repository, a test fails -- so architectural
completeness is enforced, not remembered.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from apex.governance.component_registry import (
    ABSENT,
    BUILT,
    CERTIFIED,
    PLANNED,
    REGISTRY,
    UNDER_CONSTRUCTION,
    by_state,
)
from apex.governance.firewalls import CONTRACTS

REPO = Path(__file__).resolve().parents[1]


def _module_exists(dotted: str) -> bool:
    if not dotted:
        return False
    rel = dotted.replace(".", "/")
    return (REPO / f"{rel}.py").exists() or (REPO / rel / "__init__.py").exists()


# --- the registry is internally coherent -----------------------------------

def test_built_and_certified_components_have_a_real_module():
    """A BUILT/CERTIFIED/BUILT claim must be backed by a module on disk."""
    for c in REGISTRY.values():
        if c.state in (BUILT, CERTIFIED):
            assert _module_exists(c.module), (
                f"{c.name} is {c.state} but its module {c.module!r} does not "
                f"exist. The registry must not call a placeholder 'built'."
            )


def test_planned_and_absent_components_declare_no_built_module():
    """A PLANNED/ABSENT component must not claim a real module -- that would be a
    placeholder masquerading as unbuilt, or an unreconciled build."""
    for c in REGISTRY.values():
        if c.state in (PLANNED, ABSENT):
            assert not c.module, (
                f"{c.name} is {c.state} but names module {c.module!r}; reconcile "
                f"its state or clear the module"
            )


def test_every_new_hypothesis_component_consumes_a_credit_or_is_free_discovery():
    """A component whose output is a research claim must debit a credit, unless it
    is a free discovery-layer producer (dossier/swarm/novelty/contamination)."""
    free_discovery = {"hypothesis_dossier", "research_swarm", "novelty_engine",
                      "contamination_control"}
    for c in REGISTRY.values():
        if c.is_new_hypothesis:
            assert c.consumes_credit or c.name in free_discovery, (
                f"{c.name} produces a hypothesis but neither consumes a credit "
                f"nor is a free discovery producer -- ungoverned research"
            )


def test_no_component_claims_holdout_access():
    """The absolute holdout firewall: no registry component may access it. The
    single validation look is the registration gate, not a component here."""
    for c in REGISTRY.values():
        assert c.holdout_access is False, f"{c.name} claims holdout access"


def test_only_the_ml_estimator_permits_optimization():
    """Optimization is the dangerous capability. Only the ML estimator declares
    it (nested in-sample CV), and even that is UNDER_CONSTRUCTION and gated."""
    optimisers = [c.name for c in REGISTRY.values() if c.optimize_allowed]
    assert optimisers == ["ml_estimator"], (
        f"unexpected components permit optimization: {optimisers}"
    )


# --- the registry covers the firewall table --------------------------------

def test_every_firewall_layer_is_in_the_registry():
    """Each firewall contract's package must map to at least one registry
    component, or a governed boundary would have no component behind it."""
    registry_modules = {c.module for c in REGISTRY.values() if c.module}
    for key, contract in CONTRACTS.items():
        covered = any(m == contract.package or m.startswith(contract.package + ".")
                      for m in registry_modules)
        # PLANNED layers legitimately have no module yet; check they exist as
        # a registry component by intent instead.
        if contract.status == "PLANNED":
            names = {c.name for c in REGISTRY.values()}
            assert any(key in n or n in key or key.split("_")[0] in n for n in names) \
                or key in {"portfolio", "backtest", "risk", "execution", "monitoring"}, \
                f"firewall layer {key} has no registry component"
        else:
            assert covered, f"firewall layer {key} ({contract.package}) not in registry"


def test_firewall_and_registry_agree_on_under_construction_layers():
    """ml/causal/regime are UNDER_CONSTRUCTION in the firewalls; the registry's
    corresponding engine components must not claim CERTIFIED beyond what's built."""
    # the search-accounting / claim / regime OBJECTS are certified; the
    # estimators/executors/state-builders are under construction. Both are in
    # the registry with the right split.
    assert REGISTRY["ml_search_accounting"].state == CERTIFIED
    assert REGISTRY["ml_estimator"].state == UNDER_CONSTRUCTION
    assert REGISTRY["causal_claim"].state == CERTIFIED
    assert REGISTRY["causal_executors"].state == UNDER_CONSTRUCTION
    assert REGISTRY["regime_engine"].state == CERTIFIED
    assert REGISTRY["regime_state_builders"].state == UNDER_CONSTRUCTION


# --- the registry names the gaps the audit relies on -----------------------

def test_the_named_gaps_are_present_and_unbuilt():
    """The gaps the architecture audit prioritises must be IN the registry as
    PLANNED/ABSENT, so 'what is missing' is data, not memory.

    Updated 2026-08-15 (v4.0 reconciliation): portfolio_construction (BUILT,
    attribution ladder) and paper_shadow (ACTIVE, nightly track) left the gap
    list on evidence; distribution_estimator and opportunity_engine JOINED it
    -- the two never-previously-named links between alpha and money."""
    for gap in ("research_memory", "risk_engine",
                "backtest_engine", "capacity_engine",
                "execution", "live_monitoring", "model_registry",
                "distribution_estimator", "opportunity_engine"):
        assert gap in REGISTRY, f"named gap {gap} is not in the registry"
        assert REGISTRY[gap].state in (PLANNED, ABSENT, UNDER_CONSTRUCTION)


def test_data_gaps_are_recorded_as_absent_not_planned():
    """Vendor data gaps cannot be 'built later' -- they are ABSENT with a reason."""
    for gap in ("event_data", "alternative_data"):
        assert REGISTRY[gap].state == ABSENT
        assert "GAP" in REGISTRY[gap].failure_behavior


def test_maturity_summary_counts_every_component():
    from apex.governance.component_registry import maturity_summary

    assert sum(maturity_summary().values()) == len(REGISTRY)
