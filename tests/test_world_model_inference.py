"""WM-0E-R1: the repaired statistic, the fresh seeds, the V1 court.

The estimator is proven on ARTIFICIAL statistical fixtures that have
nothing to do with the court: their PRNG seeds live in their own
namespace, none of them is a court seed, and the acceptance seeds are
never executed here. The two end-to-end cells below use a DEVELOPMENT
seed (1000, from the observed V0 set) and say so.
"""
import ast
import hashlib
import math
import random
from types import SimpleNamespace

import pytest

from apex.world_model import controls as C
from apex.world_model import court as V0
from apex.world_model import court_v1 as V1
from apex.world_model import inference as I
from apex.world_model.budget import wm0d_truth, wm0e_r1_truth
from apex.world_model.grader import GradingViolation, Z_RULE
from apex.world_model.holdout import (HOLDOUT, HOLDOUT_SEEDS, HOLDOUT_SIZE,
                                      WM_0E_DEVELOPMENT_NULL_SET_V0,
                                      derive_holdout, derive_seed)
from apex.world_model.targets import TARGET_HORIZON_STEPS

FIX = 7_301_000          # fixture PRNG namespace; not a court seed


def _grades(d):
    """Fake paired grades carrying a differential d (model - null)."""
    m = [SimpleNamespace(outcome_hash="o%d" % i, metrics={"log_likelihood": x})
         for i, x in enumerate(d)]
    n = [SimpleNamespace(outcome_hash="o%d" % i, metrics={"log_likelihood": 0.0})
         for i, _ in enumerate(d)]
    return m, n


def _ma_overlap(rng, n, mu=0.0, h=TARGET_HORIZON_STEPS):
    """d_t = mu + sum of h consecutive iid increments: the exact overlap
    structure of an h-step forward return."""
    e = [rng.gauss(0, 1) for _ in range(n + h)]
    return [mu + sum(e[t:t + h]) for t in range(n)]


def _iid_z(d):
    n = len(d); m = sum(d) / n
    v = sum((x - m) ** 2 for x in d) / (n - 1)
    return m / math.sqrt(v / n)


# ---------------------------------------------------------------- §3/§5
def test_lag_is_derived_from_horizon_and_other_lags_are_refused():
    assert I.HAC_LAG == TARGET_HORIZON_STEPS - 1 == 14
    rng = random.Random(FIX + 1)
    d = _ma_overlap(rng, 465)
    with pytest.raises(I.InferenceViolation):
        I.dm_hac_statistic(d, lag=13)
    with pytest.raises(I.InferenceViolation):
        I.dm_hac_statistic(d, lag=20)


def test_threshold_retained_not_searched():
    assert I.DM_THRESHOLD == Z_RULE == 2.0
    assert abs(I.NOMINAL_ALPHA_ONE_SIDED - 0.02275) < 1e-4
    c = I.inference_contract()
    assert c["threshold_search_performed"] is False
    assert c["hac_kernel"] == "BARTLETT" and c["hac_lag"] == 14
    assert "DETERMINISTIC" in c["limitation"]           # §4 documented


def test_too_few_samples_refused():
    rng = random.Random(FIX + 2)
    with pytest.raises(I.InferenceViolation):
        I.dm_hac_statistic([rng.gauss(0, 1) for _ in range(40)])


# ---------------------------------------------------------------- §6
def test_iid_fixture_hac_and_iid_se_agree():
    rng = random.Random(FIX + 3)
    d = [rng.gauss(0, 1) for _ in range(3000)]
    s = I.dm_hac_statistic(d)
    assert 0.85 < s["se_inflation_vs_iid"] < 1.20


def test_ar1_fixture_hac_exceeds_iid():
    rng = random.Random(FIX + 4)
    phi, x, d = 0.8, 0.0, []
    for _ in range(3000):
        x = phi * x + rng.gauss(0, 1)
        d.append(x)
    s = I.dm_hac_statistic(d)
    assert s["se_inflation_vs_iid"] > 1.8       # true ratio is 3.0


def test_ma14_overlap_iid_is_anticonservative_hac_is_centered():
    """The explicit overlapping construction. iid inference rejects far
    above nominal; the corrected statistic is centred and rejects far
    less. The exact HAC rejection rate is REPORTED by the calibration
    exercise, not asserted here beyond 'much better than iid'."""
    rng = random.Random(FIX + 5)
    reps, n = 300, 465
    iid_rej = hac_rej = 0
    ts = []
    for _ in range(reps):
        d = _ma_overlap(rng, n)
        m = sum(d) / n
        if m > 0 and _iid_z(d) > 2.0:
            iid_rej += 1
        s = I.dm_hac_statistic(d)
        ts.append(s["t"])
        if m > 0 and s["t"] > 2.0:
            hac_rej += 1
    assert iid_rej / reps > 0.10, iid_rej            # anti-conservative
    assert hac_rej < iid_rej / 2, (hac_rej, iid_rej)
    assert abs(sum(ts) / reps) < 0.15                # centred near zero


def test_positive_mean_dependent_process_retains_power():
    rng = random.Random(FIX + 6)
    reps, n, det = 150, 465, 0
    for _ in range(reps):
        d = _ma_overlap(rng, n, mu=3.0)
        s = I.dm_hac_statistic(d)
        if s["mean"] > 0 and s["t"] > 2.0:
            det += 1
    assert det / reps >= 0.85, det


# ---------------------------------------------------------------- §7
def test_non_overlap_subset_is_spaced_by_horizon_and_anchor_fixed():
    rng = random.Random(FIX + 7)
    d = _ma_overlap(rng, 465)
    m, n = _grades(d)
    r = I.non_overlap_rule(m, n)
    assert r["spacing"] == 15 and r["anchor"] == 0
    assert r["n"] == len(d[0::15]) == 31
    with pytest.raises(I.InferenceViolation):
        I.non_overlap_rule(m, n, anchor=3)


def test_paired_differentials_refuse_mismatched_outcomes():
    m, n = _grades([0.1, 0.2, 0.3])
    n[1].outcome_hash = "other"
    with pytest.raises(GradingViolation):
        I.paired_differentials(m, n)


# ---------------------------------------------------------------- §2/§8
def test_development_set_is_the_observed_v0_set_and_is_excluded():
    assert WM_0E_DEVELOPMENT_NULL_SET_V0 == tuple(V0.SEED_SET)
    assert len(WM_0E_DEVELOPMENT_NULL_SET_V0) == 25
    assert not set(HOLDOUT_SEEDS) & set(WM_0E_DEVELOPMENT_NULL_SET_V0)


def test_holdout_is_deterministic_and_derived_not_chosen():
    assert len(HOLDOUT_SEEDS) == HOLDOUT_SIZE == 50
    assert len(set(HOLDOUT_SEEDS)) == 50
    again = derive_holdout()
    assert tuple(again["seeds"]) == HOLDOUT_SEEDS
    assert again["seed_set_hash"] == HOLDOUT["seed_set_hash"]
    # the algorithm is exactly what the docstring says
    h = hashlib.sha256(b"WM0E_R1_HOLDOUT_V0|0").digest()
    assert derive_seed("WM0E_R1_HOLDOUT_V0", 0) == \
        int.from_bytes(h[:8], "big") % (2 ** 31 - 1)
    assert HOLDOUT["indices_consumed"] == 50 + len(HOLDOUT["skipped"])


def test_holdout_derivation_skips_excluded_seeds_deterministically():
    first = derive_seed("WM0E_R1_HOLDOUT_V0", 0)
    d = derive_holdout(excluded=(first,), size=5)
    assert first not in d["seeds"]
    assert d["skipped"][0] == {"index": 0, "seed": first,
                               "reason": "in development set"}


# ---------------------------------------------------------------- §9/§10/§13
def test_court_v1_commits_to_everything_before_sitting():
    defn = V1.define_v1("TEST", 0.0)
    c = defn.canonical()
    assert c["court_version"] == "NULL_COURT_V1_DEPENDENCE_AWARE"
    assert c["supersedes_without_overwriting"].startswith("NULL_COURT_V0")
    assert c["inference"]["hac_lag"] == 14 and c["inference"]["threshold"] == 2.0
    assert c["seed_set"]["seeds"] == list(HOLDOUT_SEEDS)
    assert c["development_set_excluded"]["overlap_with_acceptance"] == 0
    assert c["controls_version"] == C.CONTROLS_VERSION
    assert c["model_config_hash"].startswith("b6aec556e20cf6617cf7797cb0ef0d84")
    assert c["research_budget"]["counts"]["court_sitting"] == 3
    assert c["research_budget"]["counts"]["defect_registered"] == 1
    assert c["research_budget"]["counts"]["inference_rule_revision"] == 1
    assert c["number_of_tests"] == 300
    assert c["rescue_logic"] == "NONE"
    assert len(c["feature_set_sha256"]) == 64
    # identity is a pure function of the commitment
    assert V1.define_v1("TEST", 0.0).court_hash == defn.court_hash
    assert V1.define_v1("OTHER", 0.0).court_hash != defn.court_hash


def test_error_control_v1_exact_numbers_and_no_independence_assumed():
    e = V1.error_control_v1()
    assert e["trials_per_control"] == 50 and e["max_tolerated_false_positives"] == 5
    assert abs(e["expected_false_positives"] - 1.1375) < 1e-3
    assert abs(e["court_false_fail_probability_per_control"] - 0.000934) < 2e-5
    assert e["family_false_fail_probability_union_bound"] < 0.005
    assert "union bound" in e["family_method"]


def test_research_budget_does_not_record_zero_attempts():
    b0, b1 = wm0d_truth(), wm0e_r1_truth()
    assert len(b1.attempts) == len(b0.attempts) + 5
    ids = [a[1] for a in b1.attempts]
    assert "WM-STAT-001" in ids and "DEPENDENCE_AWARE_DM_HAC_V0" in ids
    assert sum(1 for a in b1.attempts if a[0] == "court_sitting") == 3
    assert b1.budget_hash != b0.budget_hash


# ---------------------------------------------------------------- §14
def test_no_rescue_logic_in_court_v1_source():
    src = open(V1.__file__).read()
    tree = ast.parse(src)
    forbidden = {"HAC_LAG", "DM_THRESHOLD", "HOLDOUT_SEEDS", "Z_RULE",
                 "HAC_KERNEL", "MAX_FALSE_POSITIVES_V1", "NON_OVERLAP_ANCHOR"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Attribute) and t.attr in forbidden:
                    raise AssertionError("court_v1 rebinds %s" % t.attr)
    # module-level constants are bound exactly once, at module level
    tops = [t.id for n in tree.body if isinstance(n, ast.Assign)
            for t in n.targets if isinstance(t, ast.Name)]
    assert tops.count("MAX_FALSE_POSITIVES_V1") == 1
    for word in ("retry", "rerun", "reseed", "drop_seed", "while not court_pass"):
        assert word not in src, word


# ---------------------------------------------------------------- end-to-end
def test_one_cell_each_on_a_DEVELOPMENT_seed():
    """Machinery check on seed 1000 of WM_0E_DEVELOPMENT_NULL_SET_V0.
    Development use, allowed; NOT acceptance evidence."""
    defn = V1.define_v1("TEST", 0.0)
    dev_seed = WM_0E_DEVELOPMENT_NULL_SET_V0[0]
    for ctl in ("N1", "P0"):
        cell = V1.run_control_v1(defn, ctl, dev_seed)
        assert cell["verdict"] != V0.RUN_INVALID, cell.get("error")
        # N1 shifts by 200 so its evaluation set is shorter (~270 -> 18)
        assert cell["non_overlap"]["n"] >= 15
        assert cell["se_inflation_vs_iid"] > 1.0     # dependence is real here
        assert isinstance(cell["legacy_iid_z_reference_only"], float)
