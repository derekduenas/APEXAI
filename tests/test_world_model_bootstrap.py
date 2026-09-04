"""WM-0E-R2: dependent block-bootstrap inference, block-length law, V2 court.

Fixture PRNGs live in their own namespace (FIX = 8_100_000). No court
seed, development or acceptance, is used except where a test says
DEVELOPMENT and uses seed 1000 of the observed V0 set.

These tests REFUSE to run outside WORLD_MODEL_COMPUTE_CONTAINMENT_V0.
"""
import ast
import math
import random
from types import SimpleNamespace

import numpy as np
import pytest

from apex.world_model import bootstrap as BS
from apex.world_model import controls as C
from apex.world_model import court as V0
from apex.world_model import court_v2 as V2
from apex.world_model import inference as I
from apex.world_model.budget import wm0e_r1_truth, wm0e_r2_truth
from apex.world_model.holdout import HOLDOUT_SEEDS, WM_0E_DEVELOPMENT_NULL_SET_V0
from apex.world_model.targets import TARGET_HORIZON_STEPS

FIX = 8_100_000


def test_running_inside_research_containment():
    """WORLD_MODEL_COMPUTE_CONTAINMENT_V0: World Model compute runs in
    apex-research.slice or not at all."""
    cg = open("/proc/self/cgroup").read()
    assert cg.strip().split("::")[-1].startswith("/wmresearch.slice/"), (
        "World Model compute must run through wm_contained.sh "
        "(dedicated wmresearch.slice); got %r" % cg.strip())
    # the dedicated slice holds no production service
    import subprocess
    tree = subprocess.run(["systemd-cgls", "--no-pager", "/wmresearch.slice"],
                          capture_output=True, text=True).stdout
    assert "apex-" not in tree, "production unit inside the WM slice:\n" + tree


def _ma(rng, n, mu=0.0, h=TARGET_HORIZON_STEPS):
    e = [rng.gauss(0, 1) for _ in range(n + h)]
    return [mu + sum(e[t:t + h]) for t in range(n)]


def _grades(d):
    m = [SimpleNamespace(outcome_hash="o%d" % i, metrics={"log_likelihood": x})
         for i, x in enumerate(d)]
    n = [SimpleNamespace(outcome_hash="o%d" % i, metrics={"log_likelihood": 0.0})
         for i, _ in enumerate(d)]
    return m, n


# ---------------------------------------------------------------- §2 orientation
def test_orientation_positive_means_M0_better_and_is_invariant():
    m, n = _grades([0.5] * 120)             # M0 log-likelihood higher by 0.5
    d = I.paired_differentials(m, n)
    assert all(x == 0.5 for x in d)
    assert "positive mean(d) = M0 improves" in BS.STATISTIC_ORIENTATION
    assert "logL_M0 - logL_null" in BS.STATISTIC_ORIENTATION
    assert "logL_M0(y_t) - logL_null(y_t)" in I.STATISTIC_ORIENTATION


def test_bootstrap_studentiser_matches_R1_hac_statistic():
    rng = random.Random(FIX + 1)
    d = _ma(rng, 465)
    t_rows = float(BS.hac_t_rows(np.asarray(d)[None, :])[0])
    t_r1 = I.dm_hac_statistic(d)["t"]
    assert abs(t_rows - t_r1) < 1e-9


# ---------------------------------------------------------------- §4 block law
def test_block_law_floor_is_H_on_white_noise():
    rng = random.Random(FIX + 2)
    d = [rng.gauss(0, 1) for _ in range(465)]
    b = BS.block_length(d)
    assert b["block_length"] == TARGET_HORIZON_STEPS == 15
    assert b["clamped"] == "lower"
    assert b["lower"] == 15 and b["upper"] == 465 // 6


def test_block_law_grows_beyond_H_on_overlap_and_on_long_memory():
    rng = random.Random(FIX + 3)
    b_ma = BS.block_length(_ma(rng, 2000))
    assert b_ma["block_length"] > 15, b_ma
    x, phi, ar = 0.0, 0.9, []
    for _ in range(2000):
        x = phi * x + rng.gauss(0, 1)
        ar.append(x)
    b_ar = BS.block_length(ar)
    assert b_ar["block_length"] > 15, b_ar
    assert b_ar["selector_output"]["selector"] == "POLITIS_WHITE_2004_PPW_2009"


def test_block_law_upper_clamp_and_refusals():
    rng = random.Random(FIX + 4)
    d = _ma(rng, 100)                       # upper = 16
    b = BS.block_length(d)
    assert b["block_length"] <= 100 // 6
    with pytest.raises(BS.BootstrapViolation):
        BS.block_length([rng.gauss(0, 1) for _ in range(80)])   # 80//6 < 15


def test_block_selector_is_blind_to_the_mean():
    rng = random.Random(FIX + 5)
    d = _ma(rng, 465)
    a = BS.block_length(d)
    b = BS.block_length([x + 50.0 for x in d])
    assert a["block_length"] == b["block_length"]
    assert abs(a["selector_output"]["b_opt"] - b["selector_output"]["b_opt"]) < 1e-6


def test_circular_block_indices_wrap_and_cover():
    rng = np.random.default_rng(FIX + 6)
    idx = BS.circular_block_indices(n=100, l=15, B=7, rng=rng)
    assert idx.shape == (7, 100)
    assert idx.min() >= 0 and idx.max() < 100
    row = idx[0]
    # within a block, consecutive indices increase by 1 modulo n
    assert all((row[i + 1] - row[i]) % 100 == 1 for i in range(14))


# ---------------------------------------------------------------- §5/§6
def test_bootstrap_is_deterministic_per_identity_and_fixed_B_alpha():
    rng = random.Random(FIX + 7)
    d = _ma(rng, 465)
    a = BS.bootstrap_test(d, court_id="X", control="N1", seed=1)
    b = BS.bootstrap_test(d, court_id="X", control="N1", seed=1)
    c = BS.bootstrap_test(d, court_id="X", control="N1", seed=2)
    assert a["p_bootstrap"] == b["p_bootstrap"] and a["n_ge"] == b["n_ge"]
    assert a["n_ge"] != c["n_ge"] or a["p_bootstrap"] != c["p_bootstrap"]
    assert a["B"] == 1999 and a["alpha"] == 0.025
    assert a["p_bootstrap"] >= 1.0 / 2000                # +1 convention
    with pytest.raises(BS.BootstrapViolation):
        BS.bootstrap_test(d, court_id="X", control="N1", seed=1, B=999)
    with pytest.raises(BS.BootstrapViolation):
        BS.bootstrap_test(d, court_id="X", control="N1", seed=1, alpha=0.05)


def test_bootstrap_detects_a_strong_positive_mean_and_not_a_negative_one():
    rng = random.Random(FIX + 8)
    pos = BS.bootstrap_test(_ma(rng, 465, mu=3.0), court_id="X", control="P", seed=1)
    neg = BS.bootstrap_test(_ma(rng, 465, mu=-3.0), court_id="X", control="P", seed=1)
    assert pos["verdict"] == "SIGNAL_DETECTED" and pos["p_bootstrap"] <= 0.025
    assert neg["verdict"] == "NO_SIGNAL"


def test_envelope_predeclared_and_contract_hashable():
    e = BS.CALIBRATION_ENVELOPE
    assert e["null_fixture_type1_max"] == 0.05 and e["power_fixture_min"] == 0.80
    c = BS.bootstrap_contract()
    assert c["B"] == 1999 and c["alpha_one_sided"] == 0.025
    assert c["block_lower"] == 15 and "Politis-White" in c["block_length_rule"]
    assert len(c["implementation_sha256"]) == 64
    assert BS.content_identity() == BS.content_identity()


# ---------------------------------------------------------------- §9/§10/§13
def test_court_v2_requires_a_passed_calibration_artifact(tmp_path):
    bad = tmp_path / "cal.json"
    bad.write_text('{"envelope_verdict": "FAIL", "bootstrap_contract_hash": "%s"}'
                   % BS.content_identity())
    with pytest.raises(V0.CourtViolation):
        V2.define_v2("TEST", 0.0, str(bad))
    stale = tmp_path / "cal2.json"
    stale.write_text('{"envelope_verdict": "PASS", "bootstrap_contract_hash": "other"}')
    with pytest.raises(V0.CourtViolation):
        V2.define_v2("TEST", 0.0, str(stale))


def _ok_cal(tmp_path):
    p = tmp_path / "cal_ok.json"
    p.write_text('{"envelope_verdict": "PASS", "bootstrap_contract_hash": "%s"}'
                 % BS.content_identity())
    return str(p)


def test_court_v2_commits_to_everything_before_sitting(tmp_path):
    cal = _ok_cal(tmp_path)
    defn = V2.define_v2("TEST", 0.0, cal)
    c = defn.canonical()
    assert c["court_version"] == "NULL_COURT_V2_BLOCK_BOOTSTRAP"
    assert c["primary_inference"]["B"] == 1999
    assert c["seed_set"]["seeds"] == list(HOLDOUT_SEEDS)
    assert c["development_set_excluded"]["overlap_with_acceptance"] == 0
    assert c["model_config_hash"].startswith("b6aec556e20cf6617cf7797cb0ef0d84")
    assert c["research_budget"]["counts"]["inference_rule_revision"] == 3
    assert c["research_budget"]["counts"]["court_sitting"] == 3
    assert c["number_of_tests"] == 300 and c["rescue_logic"] == "NONE"
    assert len(c["calibration_evidence_sha256"]) == 64
    assert V2.define_v2("TEST", 0.0, cal).court_hash == defn.court_hash
    assert V2.define_v2("OTHER", 0.0, cal).court_hash != defn.court_hash


def test_error_control_v2_tails_predeclared():
    e = V2.error_control_v2()
    assert e["max_tolerated_false_positives"] == 5
    t = e["tails"]
    assert abs(t["nominal"]["expected_false_positives"] - 1.25) < 1e-9
    assert abs(t["nominal"]["P_FP_exceeds_tolerance"] - 0.00151) < 2e-5
    assert t["nominal"]["family_union_bound"] < 0.01
    assert abs(t["envelope_fixture_max"]["P_FP_exceeds_tolerance"] - 0.0378) < 5e-4
    assert "union bound" in e["family_method"]


def test_budget_records_R1_rejection_and_R2_as_methodology_search():
    b1, b2 = wm0e_r1_truth(), wm0e_r2_truth()
    ids = [a[1] for a in b2.attempts]
    assert "DEPENDENCE_AWARE_DM_HAC_V0" in ids
    assert any("R1_STOPPED_AT_CALIBRATION" in i for i in ids)
    assert "DEPENDENT_BLOCK_BOOTSTRAP_V0" in ids
    assert b2.counts()["inference_rule_revision"] == 3
    assert len(b2.attempts) == len(b1.attempts) + 2


# ---------------------------------------------------------------- §14
def test_no_rescue_logic_in_court_v2_and_bootstrap_source():
    for mod in (V2, BS):
        src = open(mod.__file__).read()
        tree = ast.parse(src)
        forbidden = {"ALPHA", "B_REPLICATIONS", "BLOCK_LOWER", "MIN_BLOCKS",
                     "HOLDOUT_SEEDS", "MAX_FALSE_POSITIVES_V2", "HAC_LAG"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Attribute) and t.attr in forbidden:
                        raise AssertionError("%s rebinds %s" % (mod.__name__, t.attr))
        for word in ("retry", "rerun", "reseed", "drop_seed", "while not court_pass"):
            assert word not in src, (mod.__name__, word)


def test_holdout_still_unexecuted_in_this_tree():
    import glob
    assert not glob.glob("evidence/*court_v1*") and not glob.glob("evidence/*court_v2*")
    assert not glob.glob("evidence/*COURT-V1*") and not glob.glob("evidence/*COURT-V2*")


# ---------------------------------------------------------------- end-to-end
def test_one_cell_each_on_a_DEVELOPMENT_seed(tmp_path):
    """Seed 1000 of WM_0E_DEVELOPMENT_NULL_SET_V0. Development use."""
    defn = V2.define_v2("TEST", 0.0, _ok_cal(tmp_path))
    dev_seed = WM_0E_DEVELOPMENT_NULL_SET_V0[0]
    for ctl in ("N1", "P0"):
        cell = V2.run_control_v2(defn, ctl, dev_seed)
        assert cell["verdict"] != V0.RUN_INVALID, cell.get("error")
        assert cell["block_length"] >= 15
        assert 0 < cell["p_bootstrap"] <= 1
        assert "hac_t" in cell["secondary"]
