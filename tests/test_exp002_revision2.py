"""Revision-2 contract: matched-only selection, declared bootstrap estimator,
strong linear control blocking, weak linear world diagnostic, attributable run."""
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pytest

from apex.world_model.exp002 import controls as CW
from apex.world_model.exp002.bootstrap import session_stationary_bootstrap
from apex.world_model.exp002.registration import (BOOT_P_ESTIMATOR, FIT_BUDGET, GATES, OUTCOMES,
                                                  QUALIFICATION_REVISION, REPORTED)
from apex.world_model.exp002.run import tournament


def test_revision_two_is_declared_and_designed_after_the_failed_battery():
    from apex.world_model.exp002.registration import QUALIFICATION_REVISION_NOTE
    assert QUALIFICATION_REVISION == 2
    assert "DESIGNED AFTER OBSERVING" in QUALIFICATION_REVISION_NOTE
    assert "NOT QUALIFIED" in QUALIFICATION_REVISION_NOTE


def test_selection_authority_is_the_matched_comparison_only():
    assert GATES == {"G1": ("C", "L")}
    assert ("C", "M1") in REPORTED.values() and ("C", "M0") in REPORTED.values()
    assert "BASELINE_REPLACEMENT_CANDIDATE" not in OUTCOMES
    assert set(OUTCOMES) == {"MATCHED_IMPROVEMENT", "NOT_SELECTED",
                             "NOT_SELECTED_INFERENCE_DISAGREEMENT", "INVALID_NULL_CONTROL"}


def test_strong_linear_world_is_blocking_and_weak_one_is_diagnostic():
    assert "W1S_LINEAR" in CW.WORLDS and CW.WORLDS["W1S_LINEAR"]["r2"] == 0.0100
    assert CW.WORLDS["W1S_LINEAR"]["seed"] == 1006
    assert ("M1", "M0") in CW.BLOCKING["W1S_LINEAR"]
    assert "W1_LINEAR" not in CW.BLOCKING
    assert ("M1", "M0") in CW.DIAGNOSTIC_ONLY["W1_LINEAR"]
    # the weak world is preserved unchanged from revision 1
    assert CW.WORLDS["W1_LINEAR"]["r2"] == 0.0010 and CW.WORLDS["W1_LINEAR"]["seed"] == 1001
    assert ("C", "L") in CW.BLOCKING["W2S_INTERACTION"]


def test_budget_is_thirty_with_the_previous_twenty_five_retained():
    assert FIT_BUDGET["synthetic_control_fits"] == 30 == 5 * len(CW.WORLDS)
    assert FIT_BUDGET["synthetic_control_fits_revision_1"] == 25
    assert FIT_BUDGET["synthetic_control_fits_cumulative"] == 55


def test_bootstrap_reports_exceedances_and_never_a_zero_probability():
    rng = np.random.default_rng(1)
    d = rng.normal(0.01, 1.0, 5000)                  # a clear positive mean
    sids = [i // 50 for i in range(5000)]
    b = session_stationary_bootstrap(d, sids, expected_block_sessions=5, n_resamples=999,
                                     seed=3, threshold=0.0228)
    assert b["p_estimator"] == BOOT_P_ESTIMATOR.split(",")[0].strip() == "(k + 1) / (B + 1)"
    assert b["p_one_sided"] == (b["exceedances"] + 1) / (b["resamples"] + 1)
    assert b["p_one_sided"] > 0.0
    assert b["smallest_reportable_p"] == 1 / 1000
    assert "raw_fraction_k_over_B" in b


def test_verdict_is_matched_improvement_when_only_the_matched_gate_passes():
    w = CW.make_world("W2S_INTERACTION", n_fit_sessions=60, n_dev_sessions=30)
    rec = tournament(w["fit"], w["dev"], tag="W2S", bootstrap_resamples=400)
    assert rec["status"] == "MATCHED_IMPROVEMENT"
    assert rec["comparisons"]["R5"]["promotion_authority"] is False
    assert rec["comparisons"]["R6"]["promotion_authority"] is False
    assert "baseline_replacement_candidate" not in rec


def test_the_process_can_capture_the_identity_of_what_it_imported():
    spec = importlib.util.spec_from_file_location(
        "exp002_qual", Path(__file__).resolve().parents[1] / "scripts" / "exp002_synthetic_qualification.py")
    m = importlib.util.module_from_spec(spec); sys.modules["exp002_qual"] = m; spec.loader.exec_module(m)
    ident = m.capture_source_identity()
    assert ident["n_modules"] >= 8
    assert "apex.world_model.exp002.run" in ident["modules"]
    for v in ident["modules"].values():
        assert len(v["sha256"]) == 64 and v["file"].endswith(".py")
    assert ident["registration_hash"] and ident["numpy"] and ident["python"]
