"""Independent reference for the Student-t module. scipy is a TEST-ONLY
reference and is deliberately absent from the research runner; this module
skips cleanly where it is not importable and is never a production dependency.

The full sweep (nu 2.1..50, |x| to 50, quantiles to 1e-6, fitter versus scipy's
MLE) is recorded in results/exp002_studentt_reference_check.json; this is the
committed, repeatable subset."""
import pytest

scipy_stats = pytest.importorskip(
    "scipy.stats",
    reason="SKIPPED, NOT PASSED: scipy is a test-only reference dependency and is absent here. "
           "The executed comparison is recorded in results/exp002_studentt_reference_check.json.")

from apex.world_model.exp002 import studentt as T
from apex.world_model.exp002.registration import NU_BOUNDS

NUS = (NU_BOUNDS[0], 3.0, 5.0, 10.0, 30.0, NU_BOUNDS[1])
XS = (-50.0, -6.0, -2.0, -1e-6, 0.0, 1e-3, 1.0, 4.0, 20.0, 50.0)
MU, SCALE = 0.00037, 0.00021


@pytest.mark.parametrize("nu", NUS)
def test_logpdf_matches_scipy_across_the_declared_range_and_tails(nu):
    ref = scipy_stats.t(df=nu, loc=MU, scale=SCALE)
    for x in XS:
        y = MU + x * SCALE
        assert abs(T.logpdf(y, MU, SCALE, nu) - float(ref.logpdf(y))) < 1e-10


@pytest.mark.parametrize("nu", NUS)
def test_lower_tail_matches_scipy_relatively_out_to_50_scale_units(nu):
    """Tails are compared on the LOWER side, where both implementations return
    the small probability directly. An upper tail formed as 1 - cdf rounds to
    exactly zero near |x|=50 and cannot be compared relatively; symmetry (tested
    separately) makes the lower tail sufficient."""
    ref = scipy_stats.t(df=nu, loc=MU, scale=SCALE)
    for x in XS:
        y = MU - abs(x) * SCALE
        ours, theirs = T.cdf(y, MU, SCALE, nu), float(ref.cdf(y))
        assert theirs > 0.0
        if theirs < 1e-3:
            assert abs(ours - theirs) / theirs < 1e-8
        else:
            assert abs(ours - theirs) < 1e-10


@pytest.mark.parametrize("nu", NUS)
def test_cdf_is_symmetric_about_the_location(nu):
    for x in (0.0, 1e-3, 0.5, 2.0, 6.0, 20.0):
        lo = T.cdf(MU - x * SCALE, MU, SCALE, nu)
        hi = T.cdf(MU + x * SCALE, MU, SCALE, nu)
        assert abs(lo + hi - 1.0) < 1e-15


@pytest.mark.parametrize("nu", NUS)
def test_ppf_matches_scipy_to_1e_minus_6_including_1e_minus_6_levels(nu):
    ref = scipy_stats.t(df=nu, loc=MU, scale=SCALE)
    for q in (1e-6, 1e-3, 0.05, 0.5, 0.95, 0.999, 1 - 1e-6):
        assert abs(T.ppf(q, MU, SCALE, nu) - float(ref.ppf(q))) / SCALE < 1e-6


def test_fitter_reaches_the_same_optimum_as_scipy_mle():
    import numpy as np
    rng = np.random.default_rng(20260909)
    z = 0.9 * rng.standard_t(3.0, size=40000)
    ours = T.fit_scale_nu(z)
    df_s, _, sc_s = scipy_stats.t.fit(z, floc=0.0)
    assert abs(ours["nu"] - df_s) < 0.02 and abs(ours["s"] - sc_s) < 0.002
    nll_scipy = float(-scipy_stats.t.logpdf(z, df_s, 0.0, sc_s).sum())
    assert abs(ours["nll"] - nll_scipy) < 0.05
