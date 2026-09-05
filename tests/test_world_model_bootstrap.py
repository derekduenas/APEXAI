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
from apex.world_model.budget import wm0e_r1_truth, wm0e_r2_truth, wm0e_r2_1_truth
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
    assert c["court_version"] == "NULL_COURT_V2.1_BLOCK_BOOTSTRAP"
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


def test_holdout_executed_exactly_once_and_never_again():
    """WM0E_R1_HOLDOUT_V0 was opened ONCE, by NULL_COURT_V2.1 on
    2026-09-05 (COURT-V2-386a408b7417, FAIL). It is now CONSUMED: any
    second acceptance artifact against these seeds is a violation."""
    import glob, json
    v21 = glob.glob("evidence/court_v21_*.json")
    assert len(v21) == 1, v21
    assert json.load(open(v21[0]))["definition"]["court_id"] == "COURT-V2-386a408b7417"
    assert not glob.glob("evidence/*court_v1_*") and not glob.glob("evidence/court_v2_*")


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


# ================================================================ WM-IMPL-001 (R2.1)
def _v0_selector(d):
    """VERBATIM replica of the V0 selector (the buffer bug included), kept
    here so the defect is reproducible forever and equivalence is testable."""
    x = np.asarray(d, dtype=float); n = len(x); c = x - x.mean()
    K_N = max(5, int(math.ceil(math.sqrt(math.log10(n)))))
    m_max = int(math.ceil(math.sqrt(n))) + K_N
    band = 2.0 * math.sqrt(math.log10(n) / n)
    R = np.array([(c[k:] * c[:n - k]).sum() / n for k in range(m_max + K_N + 1)])
    rho = R / R[0]
    m_hat = None
    for m in range(0, m_max + 1):
        if np.all(np.abs(rho[m + 1:m + K_N + 1]) < band):
            m_hat = m; break
    if m_hat is None: m_hat = m_max
    M = max(1, 2 * m_hat)
    ks = np.arange(-M, M + 1)
    lam = BS._flat_top(ks / M)
    Rk = R[np.abs(ks)]                       # <- IndexError when M > m_max + K_N
    G = float((lam * np.abs(ks) * Rk).sum()); S = float((lam * Rk).sum())
    D = (4.0 / 3.0) * S * S
    b = ((2.0 * G * G / D) ** (1.0 / 3.0)) * (n ** (1.0 / 3.0)) if D > 0 else 0.0
    return {"m_hat": m_hat, "M": M, "b_opt": b}


def _ar1(seed, n, phi):
    rng = random.Random(seed); x, out = 0.0, []
    for _ in range(n):
        x = phi * x + rng.gauss(0, 1); out.append(x)
    return out


def test_wm_impl_001_constants_and_history():
    k = BS.selector_constants(465)
    assert k == {"K_N": 5, "m_max": 27, "v0_buffer_lags": 32, "required_lags": 54}
    assert BS.required_autocov_lags(270) == 2 * BS.selector_constants(270)["m_max"]
    assert BS.BOOTSTRAP_VERSION == "DEPENDENT_BLOCK_BOOTSTRAP_V0.1"
    assert "V0" in BS.IMPLEMENTATION_HISTORY and "V0.1" in BS.IMPLEMENTATION_HISTORY
    assert BS.bootstrap_contract()["implementation_history"] == BS.IMPLEMENTATION_HISTORY


@pytest.mark.parametrize("phi,seed", [(0.9, FIX + 20), (0.995, FIX + 21)])
def test_wm_impl_001_regression_v0_raises_v01_runs(phi, seed):
    """Legal long-memory inputs where 2*m_hat exceeds the V0 buffer."""
    d = _ar1(seed, 465, phi)
    with pytest.raises(IndexError):                       # the exact defect
        _v0_selector(d)
    out = BS.block_length(d)                              # V0.1 executes
    sel = out["selector_output"]
    assert sel["M"] == max(1, 2 * sel["m_hat"])           # no clamping sneaked in
    assert sel["M"] > BS.selector_constants(465)["v0_buffer_lags"]
    assert sel["autocov_lags_available"] >= sel["max_lag_read"]
    assert 15 <= out["block_length"] <= 465 // 6


def test_wm_impl_001_boundary_m_hat_equals_m_max_and_zero():
    d = _ar1(FIX + 22, 465, 0.998)                        # never insignificant
    sel = BS.block_length(d)["selector_output"]
    assert sel["m_hat"] == sel["m_max"] == 27 and sel["M"] == 54
    assert sel["autocov_lags_available"] == 54 >= sel["max_lag_read"]
    rng = random.Random(FIX + 23)
    w = [rng.gauss(0, 1) for _ in range(465)]             # m_hat = 0
    sel0 = BS.block_length(w)["selector_output"]
    assert sel0["m_hat"] == 0 and sel0["M"] == 1
    assert BS.block_length(w)["block_length"] == 15       # floor H, unchanged


def test_wm_impl_001_semantic_equivalence_where_v0_could_run():
    """On every input V0 could execute, V0.1 returns the identical
    selection (bit-identical b_opt) and the identical bootstrap result."""
    cases = [[random.Random(FIX + 30).gauss(0, 1) for _ in range(465)],
             _ma(random.Random(FIX + 31), 465), _ma(random.Random(FIX + 32), 270),
             _ar1(FIX + 33, 465, 0.5)]
    compared = 0
    for d in cases:
        try:
            v0 = _v0_selector(d)
        except IndexError:
            continue                                      # outside V0's domain
        v01 = BS.block_length(d)["selector_output"]
        assert v01["m_hat"] == v0["m_hat"] and v01["M"] == v0["M"]
        assert v01["b_opt"] == v0["b_opt"]                # same arithmetic, same float
        compared += 1
    assert compared >= 3, compared


def test_budget_r2_1_distinguishes_implementation_repair():
    b2, b21 = wm0e_r2_truth(), wm0e_r2_1_truth()
    c = b21.counts()
    assert c["implementation_repair"] == 1 and c["defect_registered"] == 2
    assert c["inference_rule_revision"] == 3               # NOT 4: no method change
    assert c["court_sitting"] == 3
    assert len(b21.attempts) == len(b2.attempts) + 2
    ids = [a[1] for a in b21.attempts]
    assert "WM-IMPL-001" in ids and "DEPENDENT_BLOCK_BOOTSTRAP_V0->V0.1" in ids
