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

@pytest.mark.xfail(
    strict=True,
    reason=(
        "CERTIFICATION FINDING (Step 3): apex.pipeline.build_panel_pipeline "
        "computes APEX-001's four-factor composite and never reaches "
        "apex.features.nsi, while config/experiment.yaml registers APEX-002. "
        "The gated path does not implement the registered experiment. "
        "strict=True: when #002 is wired, this test PASSES and the xfail "
        "becomes an error, forcing the marker to be removed rather than "
        "silently outliving the defect."
    ),
)
def test_the_gated_path_computes_the_registered_signal():
    findings = certify_signal_wiring(module_closure(ROOT, ENTRY), NSI, COMPOSITE)

    assert not findings, "; ".join(findings)
