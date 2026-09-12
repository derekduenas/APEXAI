"""The Student-t module must be right before anything is scored with it."""
import math
import random
from statistics import NormalDist

import pytest

from apex.world_model.exp002 import studentt as T
from apex.world_model.grader import _gauss_logpdf


def test_cdf_matches_the_closed_form_cauchy_at_nu_1():
    for x in (-5.0, -1.0, -0.3, 0.0, 0.3, 1.0, 5.0):
        assert abs(T.cdf(x, 0.0, 1.0, 1.0) - (0.5 + math.atan(x) / math.pi)) < 1e-12


def test_cdf_matches_the_closed_form_at_nu_2():
    for x in (-4.0, -1.0, 0.0, 0.7, 3.0):
        assert abs(T.cdf(x, 0.0, 1.0, 2.0) - (0.5 + x / (2 * math.sqrt(2 + x * x)))) < 1e-12


def test_large_nu_matches_the_known_first_order_expansion():
    """Not a loose limit check: log t_nu(x) - log phi(x) = (x^4 - 2x^2 - 1)/(4 nu)
    + O(1/nu^2). Asserting the expansion itself, to 1e-6 at nu=1e4, tests the
    implementation far more sharply than any tolerance on the raw gap."""
    N = NormalDist()
    nu = 1e4
    for x in (-2.0, -0.5, 0.0, 1.0, 2.5):
        gap = T.logpdf(x, 0.0, 1.0, nu) - _gauss_logpdf(x, 0.0, 1.0)
        first_order = (x ** 4 - 2 * x * x - 1) / (4 * nu)
        assert abs(gap - first_order) < 1e-6, (x, gap, first_order)
        # the CDF gap is O(1/nu) with a small constant; 1e-4 is above it by an order
        assert abs(T.cdf(x, 0.0, 1.0, nu) - N.cdf(x)) < 1e-4


def test_cdf_is_not_flat_around_the_median():
    """The defect the complement fix removes: distinct small t must give
    distinct CDF values, monotone, on both sides of zero."""
    vals = [T.cdf(t, 0.0, 1.0, 30.0) for t in (-1e-7, -1e-9, 0.0, 1e-9, 1e-7)]
    assert all(b > a for a, b in zip(vals, vals[1:])), vals
    assert abs(vals[2] - 0.5) < 1e-15


def test_ppf_inverts_cdf():
    for nu in (2.1, 4.0, 30.0):
        for q in (0.05, 0.25, 0.5, 0.75, 0.95):
            x = T.ppf(q, 0.001, 0.0003, nu)
            assert abs(T.cdf(x, 0.001, 0.0003, nu) - q) < 1e-9


def test_logpdf_integrates_to_one():
    nu, s = 3.5, 0.002
    xs = [(-0.05 + 0.1 * i / 20000) for i in range(20001)]
    dx = 0.1 / 20000
    total = sum(math.exp(T.logpdf(x, 0.0, s, nu)) for x in xs) * dx
    assert abs(total - 1.0) < 1e-3


def test_fit_recovers_known_parameters():
    rng = random.Random(3)
    nu, s = 5.0, 1.3
    z = []
    for _ in range(40000):
        g = rng.gauss(0, 1); c = sum(rng.gauss(0, 1) ** 2 for _ in range(5))
        z.append(s * g / math.sqrt(c / nu))
    f = T.fit_scale_nu(z)
    assert f["converged"] and not f["nu_at_lower_bound"] and not f["nu_at_upper_bound"]
    assert abs(f["nu"] - nu) < 0.5 and abs(f["s"] - s) < 0.05


def test_gaussian_residuals_drive_nu_to_the_upper_bound_and_that_is_legitimate():
    rng = random.Random(4)
    z = [rng.gauss(0, 0.8) for _ in range(30000)]
    f = T.fit_scale_nu(z)
    assert f["converged"]
    assert f["nu_at_upper_bound"] is True       # near-Gaussian; a legitimate outcome, not a failure
    assert f["nu_at_lower_bound"] is False


def test_fit_refuses_degenerate_input():
    with pytest.raises(ValueError):
        T.fit_scale_nu([0.0] * 500)
    with pytest.raises(ValueError):
        T.fit_scale_nu([1.0] * 50)
