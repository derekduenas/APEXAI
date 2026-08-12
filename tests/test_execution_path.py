"""Does the gated path run the signal the conformance suite certified?

`test_nsi_conformance.py` examines `apex.features.nsi` directly. Every one of
its 37 tests can pass while the production pipeline never calls that module.
These tests cover the seam between "the signal is correct" and "the signal is
the one that runs".
"""

from __future__ import annotations

from pathlib import Path

import pytest

from apex.audit.execution_path import certify_signal_wiring, module_closure

ROOT = Path(__file__).resolve().parents[1]
ENTRY = "apex.pipeline"

NSI = "apex.features.nsi"
COMPOSITE = "apex.features.composite"


# --- the auditor itself -----------------------------------------------------

def test_the_closure_walk_reaches_transitively_imported_modules():
    closure = module_closure(ROOT, ENTRY)

    assert ENTRY in closure
    assert "apex.universe" in closure, "a direct import was not found"
    assert "apex.contracts" in closure, "a transitive import was not found"


def test_the_closure_walk_is_not_vacuous():
    """A walk that silently returns everything, or nothing, proves nothing."""
    closure = module_closure(ROOT, ENTRY)

    assert len(closure) > 5, "the walk found implausibly few modules"
    # apex.evaluate.turnover is real, importable, and NOT imported by the
    # pipeline. A walk that returns the whole package would wrongly include it.
    assert "apex.evaluate.turnover" not in closure, (
        "the walk returned a module the pipeline does not import; it is not "
        "discriminating between reachable and unreachable"
    )
    assert not module_closure(ROOT, "apex.no_such_module")


def test_counterexample_the_auditor_flags_a_missing_signal_module():
    """The violation this audit exists to catch."""
    wired = {ENTRY, NSI}
    assert not certify_signal_wiring(wired, NSI, COMPOSITE)

    unwired = {ENTRY, "apex.universe"}

    findings = certify_signal_wiring(unwired, NSI, COMPOSITE)
    assert any("does not reach" in f for f in findings), (
        "a path that never computes the registered signal was certified clean"
    )


def test_counterexample_the_auditor_flags_a_closed_experiments_scorer():
    contaminated = {ENTRY, NSI, COMPOSITE}

    findings = certify_signal_wiring(contaminated, NSI, COMPOSITE)
    assert any("reaches" in f and COMPOSITE in f for f in findings), (
        "a closed experiment's scoring machinery inside the live path was "
        "certified clean"
    )


def test_counterexample_the_walk_sees_from_package_import_name_form():
    """`from apex.features import nsi` imports a MODULE, not an attribute.

    A walk that records only `node.module` would credit the pipeline with
    reaching `apex.features` and never notice which signal it pulled.
    """
    closure = module_closure(ROOT, "scripts_probe_not_a_module")
    assert not closure

    # scripts/run_002_b1.py uses exactly that form; prove the walk sees it.
    probe = module_closure(ROOT, "apex.audit.execution_path")
    assert probe, "the probe module itself was not found"


# --- the live finding -------------------------------------------------------

# The Step 3 finding is FIXED, so the xfail(strict=True) placeholder that
# recorded it has been removed rather than left to rot. Its guard is superseded
# by `test_each_registered_experiment_reaches_its_own_signal` below: the old
# test asked whether apex.pipeline reaches nsi and NOT composite, and that
# question stopped being meaningful when apex.pipeline became the dispatcher
# for both experiments. Isolation is now certified per experiment, from each
# experiment's own entry module, which is the stronger property.


# --- per-experiment isolation (Step 3A) -------------------------------------

def test_each_registered_experiment_reaches_its_own_signal():
    from apex.audit.execution_path import EXPERIMENT_ENTRY, certify_experiment

    for experiment in EXPERIMENT_ENTRY:
        assert not certify_experiment(ROOT, experiment), (
            f"{experiment}: {certify_experiment(ROOT, experiment)}"
        )


def test_apex_002_does_not_reach_apex_001_scoring_machinery():
    closure = module_closure(ROOT, "apex.experiments.apex002")

    assert NSI in closure and "apex.features.nsi_scores" in closure
    for foreign in (COMPOSITE, "apex.features.f1_momentum", "apex.features.f2_trend",
                    "apex.features.f3_volatility", "apex.features.f4_relative_strength"):
        assert foreign not in closure, f"#002 reaches {foreign}"


def test_counterexample_the_per_experiment_audit_flags_a_contaminated_path():
    """Prove certify_experiment can fail, not merely report clean."""
    from apex.audit import execution_path as ep

    original = ep.EXPERIMENT_ENTRY["APEX-002"]
    try:
        # Point #002's entry at #001's pipeline: the exact Step 3 defect.
        ep.EXPERIMENT_ENTRY["APEX-002"] = "apex.pipeline"
        findings = ep.certify_experiment(ROOT, "APEX-002")
    finally:
        ep.EXPERIMENT_ENTRY["APEX-002"] = original

    assert any(COMPOSITE in f for f in findings), (
        "a path reaching #001's composite was certified clean"
    )
    assert not ep.certify_experiment(ROOT, "APEX-002"), "restore failed"


def test_counterexample_an_unregistered_experiment_is_refused():
    from apex.audit.execution_path import certify_experiment

    findings = certify_experiment(ROOT, "APEX-999")

    assert findings and "no execution path" in findings[0]


# --- the dispatcher actually routes (runtime, not static) -------------------

def test_the_dispatcher_routes_apex_002_to_the_nsi_path():
    """Static reachability is necessary, not sufficient: the branch must run.

    This asserts on the OUTPUT TYPE, which only the #002 builder can produce.
    #001 returns PipelineOutput; #002 returns NSIOutput.
    """
    import ast
    import inspect

    from apex.pipeline import run_period

    src = inspect.getsource(run_period)
    tree = ast.parse(src.lstrip())

    branches = [n for n in ast.walk(tree) if isinstance(n, ast.Compare)]
    literals = {c.value for n in branches for c in n.comparators
                if isinstance(c, ast.Constant)}

    assert "APEX-001" in literals and "APEX-002" in literals, (
        f"run_period does not branch on both experiments; found {literals}"
    )
    assert "build_nsi_output" in src, "the #002 branch does not call the NSI builder"
    assert "UnregisteredExperiment" in src, "there is no refusal for an unknown id"


def test_counterexample_an_unknown_experiment_id_raises_rather_than_defaulting():
    """The Step 3 failure mode, made impossible.

    A config naming an experiment with no execution path must REFUSE, not fall
    through to whichever signal happens to be implemented first.
    """
    from apex.config import load_config
    from apex.pipeline import UnregisteredExperiment, run_period

    config = load_config("experiment", "costs", "synthetic", "sharadar")
    import copy
    tampered = copy.deepcopy(config.data)
    tampered["experiment"]["id"] = "APEX-999"
    config = type(config)(data=tampered, sources=config.sources)

    class _Source:
        name = "stub"
        requires_signed_registration = False
        dataset_fingerprint = "dev-stub"

        def load(self):
            raise AssertionError("data must not be loaded for an unknown experiment")

    with pytest.raises(UnregisteredExperiment, match="APEX-999"):
        run_period(_Source(), config, "in_sample")
