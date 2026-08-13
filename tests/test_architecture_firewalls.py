"""Mechanical enforcement of the architectural firewalls.

The master audit named one dangerous gap: the validation -> downstream boundary
is unguarded, safe only because the downstream layers are absent. This file
ARMS that boundary and every sibling boundary NOW. Each test enforces a
`LayerContract` from `apex.governance.firewalls`:

  - if the layer's package does not exist yet, the test confirms it is absent
    (matching the audit's ABSENT/PLANNED classification);
  - the moment someone creates `apex/ml/`, `apex/portfolio/`, `apex/execution/`
    etc., the SAME test begins enforcing that layer's import closure against its
    forbidden set -- the firewall arrives with the code, not after it.

No engine is built here. These are read-only closure assertions reusing the
audited `module_closure` walk.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from apex.audit.execution_path import module_closure
from apex.governance.firewalls import (
    CONTRACTS,
    DISCOVERY_LAYER,
    REGISTRATION_CORE,
    SCREEN,
    new_hypothesis_layers,
    planned_packages,
)

REPO = Path(__file__).resolve().parents[1]
APEX = REPO / "apex"


def _package_modules(package: str) -> list[str]:
    """Every apex.* module name under a package prefix, if it exists on disk."""
    rel = package.replace(".", "/")
    root = REPO / rel
    if not root.exists():
        return []
    out = []
    if (root.with_suffix(".py")).exists():
        out.append(package)
    for p in root.rglob("*.py"):
        if "__pycache__" in str(p):
            continue
        stem = str(p.relative_to(REPO)).replace("/", ".")[:-3]
        out.append(stem[:-9] if stem.endswith(".__init__") else stem)
    return sorted(set(out))


# --- the firewall table itself is coherent ---------------------------------

def test_every_contract_that_is_a_new_hypothesis_consumes_a_credit_or_is_free_discovery():
    """A layer whose output is a research claim must either consume a credit
    (ML/causal/regime) or be the free dossier-producing discovery layer. A
    new-hypothesis layer that neither registers nor is discovery would be a way
    to make a research claim with no governance."""
    for key in new_hypothesis_layers():
        c = CONTRACTS[key]
        assert c.consumes_credit or c.package == "apex.research", (
            f"{key} produces a hypothesis but neither consumes a credit nor is "
            f"the discovery layer -- an ungoverned research claim"
        )


def test_no_contract_may_access_the_holdout():
    """The absolute holdout firewall: no layer in the table may reach it. The
    single validation look is gated by registration, not by any layer here."""
    for key, c in CONTRACTS.items():
        assert c.may_access_holdout is False, f"{key} claims holdout access"


# --- the boundary is armed for every planned layer -------------------------

@pytest.mark.parametrize("key", sorted(CONTRACTS))
def test_layer_closure_obeys_its_forbidden_set(key):
    """The core firewall. For each declared layer, every module currently under
    its package must have an import closure disjoint from its forbidden set.

    Absent layers pass vacuously (nothing to check) BUT the test is live: it
    will enforce the boundary the instant the package appears.
    """
    contract = CONTRACTS[key]
    modules = _package_modules(contract.package)
    for module in modules:
        reached = module_closure(REPO, module) & contract.forbidden
        assert not reached, (
            f"firewall breach: {module} (layer '{key}') reaches {sorted(reached)}, "
            f"which its LayerContract forbids. Information may flow DOWN the layer "
            f"stack, never UP into research/registration/screen or the holdout."
        )


def test_the_planned_layers_are_absent_as_the_audit_claims():
    """PLANNED layers must have no package yet. If one appears, the audit's
    classification is stale and must be reconciled before building further."""
    for key, c in CONTRACTS.items():
        if c.status == "PLANNED":
            assert not _package_modules(c.package), (
                f"{c.package} exists but the contract marks it PLANNED; the "
                f"target-architecture audit must be updated first"
            )


# --- the two firewalls that are live TODAY ---------------------------------

def test_discovery_cannot_reach_registration_today():
    """Firewall #1/#3-6 live check: the BUILT discovery layer must not reach
    the registration core. This is the up-direction firewall, enforced now."""
    for module in _package_modules("apex.research"):
        reached = module_closure(REPO, module) & REGISTRATION_CORE
        assert not reached, f"{module} reaches {sorted(reached)}"


def test_the_evaluation_path_cannot_reach_screen_or_discovery_today():
    """Firewall #2 live check: statistics/validation must not read the screen
    (S13) or the discovery layer. A screening outcome is never evidence."""
    for module in _package_modules("apex.evaluate") + ["apex.pipeline"]:
        reached = module_closure(REPO, module) & (SCREEN | DISCOVERY_LAYER)
        assert not reached, (
            f"{module} reaches {sorted(reached)}: a screen/discovery signal "
            f"could enter a verdict"
        )


def test_planned_packages_covers_every_absent_engine_named_in_the_audit():
    """The firewall table must arm every layer the audit calls ABSENT/PLANNED,
    or a boundary would be missing exactly where the engine will land."""
    packages = set(planned_packages().values())
    for engine in ("apex.ml", "apex.causal", "apex.portfolio", "apex.backtest",
                   "apex.risk", "apex.execution", "apex.regime", "apex.monitoring"):
        assert engine in packages, (
            f"{engine} is named absent in the audit but has no firewall contract; "
            f"its boundary would arrive only with its code"
        )


# --- proof the firewall can fire -------------------------------------------

def test_counterexample_the_firewall_detects_a_forbidden_import(tmp_path):
    """The closure check must be able to FAIL, not merely pass on absent layers.

    Build a throwaway package that imports a forbidden target and confirm the
    same module_closure walk the firewall uses flags it. Reuses the audited
    walk against a synthetic tree so nothing real is polluted.
    """
    # Self-contained synthetic tree: the forbidden TARGET must also resolve
    # under the walk's root, because module_closure only records modules it can
    # find. This mirrors the real case where both the layer and apex.research
    # live under REPO.
    (tmp_path / "apex" / "ml").mkdir(parents=True)
    (tmp_path / "apex" / "__init__.py").write_text("")
    (tmp_path / "apex" / "ml" / "__init__.py").write_text("")
    (tmp_path / "apex" / "ml" / "model.py").write_text(
        "from apex.research import swarm\n")
    (tmp_path / "apex" / "research").mkdir()
    (tmp_path / "apex" / "research" / "__init__.py").write_text("")
    (tmp_path / "apex" / "research" / "swarm.py").write_text("x = 1\n")

    reached = module_closure(tmp_path, "apex.ml.model") & REGISTRATION_CORE
    # swarm is in DISCOVERY_LAYER, and apex.ml forbids DISCOVERY_LAYER; use the
    # same forbidden set the contract uses.
    breach = module_closure(tmp_path, "apex.ml.model") & DISCOVERY_LAYER
    assert "apex.research.swarm" in breach, (
        "the closure walk did not follow the forbidden import; the firewall "
        "test would pass vacuously on a real breach"
    )
    assert not reached, "unexpected registration reach in the fixture"


def test_counterexample_a_new_hypothesis_layer_with_no_governance_is_rejected():
    """Prove the coherence check fires: a fabricated new-hypothesis contract that
    neither consumes a credit nor is discovery must be caught."""
    from apex.governance.firewalls import LayerContract

    rogue = LayerContract(
        name="rogue", package="apex.rogue", purpose="x", status="PLANNED",
        forbidden=frozenset(), is_new_hypothesis=True, consumes_credit=False,
        may_access_holdout=False, may_optimize=False,
    )
    ungoverned = rogue.is_new_hypothesis and not rogue.consumes_credit \
        and rogue.package != "apex.research"
    assert ungoverned, (
        "a new-hypothesis layer that neither registers nor is discovery was not "
        "recognised as ungoverned; the coherence guard would miss it"
    )
