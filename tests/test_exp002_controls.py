"""The control worlds must be what they claim."""
import math
import statistics

from apex.world_model.exp002 import controls as CW


def test_every_world_is_declared_with_seed_r2_and_expectation():
    for name, spec in CW.WORLDS.items():
        assert {"signal", "r2", "seed", "noise", "role"} <= set(spec)
        assert name in CW.EXPECTED or name == "W2_INTERACTION"


def test_beta_gives_the_declared_r2():
    for r2 in (0.001, 0.01):
        b = CW.beta_for_r2(r2)
        assert abs(b * b / (b * b + 1) - r2) < 1e-12


def test_interaction_is_orthogonal_to_the_linear_features():
    w = CW.make_world("W2S_INTERACTION", n_fit_sessions=60, n_dev_sessions=0)
    z1 = [r["features"]["ret_1"] / CW.SIGMA_RET1 for r, _, _ in w["fit"]]
    z5 = [r["features"]["ret_5"] / CW.SIGMA_RET5 for r, _, _ in w["fit"]]
    g = [a * b for a, b in zip(z1, z5)]
    for z in (z1, z5):
        assert abs(statistics.correlation(g, z)) < 0.03


def test_features_are_standardised_and_dependent_as_declared():
    w = CW.make_world("W4_NULL", n_fit_sessions=60, n_dev_sessions=0)
    z1 = [r["features"]["ret_1"] / CW.SIGMA_RET1 for r, _, _ in w["fit"]]
    assert abs(statistics.mean(z1)) < 0.05 and abs(statistics.pstdev(z1) - 1.0) < 0.05
    lag1 = statistics.correlation(z1[:-1], z1[1:])
    assert abs(lag1 - CW.FEATURE_PHI) < 0.05


def test_heavy_tail_world_has_fat_tails_and_null_world_does_not():
    def kurt(xs):
        m = statistics.mean(xs); s = statistics.pstdev(xs)
        return statistics.mean([((x - m) / s) ** 4 for x in xs])
    w3 = CW.make_world("W3_HEAVY_TAIL", n_fit_sessions=60, n_dev_sessions=0)
    w4 = CW.make_world("W4_NULL", n_fit_sessions=60, n_dev_sessions=0)
    y3 = [y / r["features"]["rv_30"] for r, y, _ in w3["fit"]]
    y4 = [y / r["features"]["rv_30"] for r, y, _ in w4["fit"]]
    assert kurt(y3) > kurt(y4) + 0.5


def test_worlds_are_reproducible_from_their_seeds():
    a = CW.make_world("W1_LINEAR", n_fit_sessions=3, n_dev_sessions=1)
    b = CW.make_world("W1_LINEAR", n_fit_sessions=3, n_dev_sessions=1)
    assert [y for _, y, _ in a["fit"]] == [y for _, y, _ in b["fit"]]
