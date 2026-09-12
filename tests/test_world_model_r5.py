"""WM-0E-R5: WM-META-001 executed-split binding; E1860 geometry for every
frozen negative control; seeds; frozen engine; budget."""
import pytest

from apex.world_model import bootstrap as BS, controls as C, controls_r4 as R4, controls_r5 as R5, teststand as TS
from apex.world_model.budget import wm0e_r4_truth, wm0e_r5_truth
from apex.world_model.controls_r3 import N3_DEV_SEEDS, P0_DEV_SEEDS
from apex.world_model.court import _world
from apex.world_model.holdout import HOLDOUT_SEEDS
from apex.world_model.models import M0SyntheticBaseline, NullBaseline
from apex.world_model.runs import ChronologicalSplit

FROZEN_ENGINE = "af3ae117a69ee485bf8ac2fa86c7b962db7f21ab639507dffb6389ed0a2f35ac"
DEV = 1000


def test_engine_frozen_and_p0_not_rerun_here():
    assert BS.content_identity() == FROZEN_ENGINE
    assert "P0" not in R5.R5_CONTROLS and R5.E_SELECTED == 1860 and R5.R5_MAX_FP == 5


# ---------------------------------------------------------------- WM-META-001
def test_default_call_binds_default_split_as_executed_and_is_unlabelled():
    w = _world(DEV)
    m = TS.run_pipeline(w, NullBaseline())
    es = m["executed_split"]
    assert es["split_contract_id"] == "EXECUTED_SPLIT_V1"
    assert es["boundary"] == 720 and es["n_steps"] == 1200 and es["usable_evaluation_count"] == 465
    assert es["training_count"] == 701 and es["forecast_horizon_steps"] == 15
    assert m["run"].training_configuration["executed_split"] == es
    assert "NOT_EXECUTED_DEFAULT_METADATA" not in m["run"].training_configuration
    assert m["run"].split.canonical() == m["split"]


def test_explicit_split_is_the_executed_one_and_default_is_labelled():
    w = R4.r4_world(DEV)
    m = TS.run_pipeline(w, NullBaseline(), split=R4.R4_SPLIT)
    es = m["executed_split"]
    assert es["boundary"] == 720 and es["n_steps"] == 2595 and es["usable_evaluation_count"] == 1860
    assert m["run"].split.boundary == 720                       # the record's split IS the executed one
    tc = m["run"].training_configuration
    assert tc["executed_split"]["executed_split_hash"] == es["executed_split_hash"]
    assert tc["NOT_EXECUTED_DEFAULT_METADATA"]["default_split"]["boundary"] == 1557
    # hash is a pure function of the executed geometry
    again = TS.executed_split_record(R4.R4_SPLIT, 1860)
    assert again["executed_split_hash"] == es["executed_split_hash"]
    assert TS.executed_split_record(ChronologicalSplit(n_steps=2595, boundary=721), 1860)["executed_split_hash"] != es["executed_split_hash"]


def test_split_must_match_the_world():
    with pytest.raises(TS.StandViolation):
        TS.run_pipeline(_world(DEV), NullBaseline(), split=R4.R4_SPLIT)   # 2595 split on a 1200 world


def test_executed_split_is_inside_the_sealed_run_hash():
    w = R4.r4_world(DEV)
    a = TS.run_pipeline(w, NullBaseline(), split=R4.R4_SPLIT)
    b = TS.run_pipeline(w, NullBaseline(), split=ChronologicalSplit(n_steps=2595, boundary=1557))
    assert a["run"].run_hash != b["run"].run_hash                 # different executed split -> different artifact


# ---------------------------------------------------------------- geometry
@pytest.mark.parametrize("ctl", R5.R5_CONTROLS)
def test_every_control_runs_at_E1860_geometry(ctl):
    w = R4.r4_world(DEV)
    m = TS.run_pipeline(w, R5.r5_model(ctl, DEV), dataset=R5.r5_dataset(ctl, DEV), split=R4.R4_SPLIT)
    assert m["executed_split"]["boundary"] == 720 and m["executed_split"]["n_steps"] == 2595
    assert m["n_eval"] == R5.EXPECTED_USABLE[ctl] and m["n_train"] == R5.EXPECTED_TRAIN[ctl]


def test_n1_still_shifts_200_and_n3_v0_is_not_among_controls():
    assert C.N1_SHIFT_STEPS == 200 and R5.EXPECTED_USABLE["N1"] == 1660
    assert R5.predeclaration()["controls"]["N3_V0"].startswith("RETIRED")


def test_seeds_new_paired_disjoint_no_acceptance():
    assert len(R5.R5_DEV_SEEDS) == 100
    old = set(HOLDOUT_SEEDS) | set(N3_DEV_SEEDS) | set(P0_DEV_SEEDS) | set(R4.DEV_SEEDS) | {1000 + 37 * i for i in range(25)}
    assert not set(R5.R5_DEV_SEEDS) & old
    p = R5.predeclaration()
    assert p["seeds"]["shared_by_all_controls"] is True and p["new_acceptance_seeds_created"] is False
    assert p["acceptance_court"] == "NONE" and R5.predeclaration_hash() == R5.predeclaration_hash()


def test_budget_r5():
    b4, b5 = wm0e_r4_truth(), wm0e_r5_truth()
    assert b5.counts()["null_control_validation"] == 5
    assert b5.counts()["null_control_design"] == 2 and b5.counts()["inference_rule_revision"] == 3
    assert len(b5.attempts) == len(b4.attempts) + 5
