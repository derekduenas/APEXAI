"""Optimizer trial points must be rejected numerically, not crash the fit."""
import numpy as np
import pytest
from apex.worldmodel_wb import vol_models as VM


@pytest.mark.parametrize("gjr", [False, True])
@pytest.mark.parametrize("field,value", [(0, 1000.), (1, -1000.), (-1, 1000.), (-1, -1000.),
                                         (0, float("nan")), (0, float("inf"))])
def test_invalid_trial_point_gets_penalty(gjr, field, value):
    theta = [np.log(1e-8), -2.2, 1.9] + ([-3.] if gjr else []) + [np.log(6.)]
    theta[field] = value
    x = np.random.default_rng(3).normal(0, 2e-4, 500)
    assert VM._nll(theta, x, gjr) == 1e12


def test_ordinary_trial_still_has_finite_nonpenalty_likelihood():
    theta = [np.log(1e-8), -2.2, 1.9, np.log(6.)]
    x = np.random.default_rng(3).normal(0, 2e-4, 500)
    value = VM._nll(theta, x, False)
    assert np.isfinite(value) and value < 1e11
