"""The minimal monetisation evaluator: fixed policy, no optimisation.

Proves the evaluator is an evaluator: deterministic, cost-monotone, and
structurally incapable of tuning or selecting. Viability thresholds are declared
constants, asserted present before any use. No candidate data is touched.
"""

from __future__ import annotations

import pytest

from apex.portfolio import projection as P
from apex.portfolio import viability as V


def test_projection_is_deterministic():
    a = P.project(gross_spread_annualised=0.08, breadth_median_names=1000)
    b = P.project(gross_spread_annualised=0.08, breadth_median_names=1000)
    assert a.as_dict() == b.as_dict()


def test_higher_cost_lowers_net_return():
    lo = P.project(gross_spread_annualised=0.08, breadth_median_names=1000,
                   cost_bps_one_way=10)
    hi = P.project(gross_spread_annualised=0.08, breadth_median_names=1000,
                   cost_bps_one_way=40)
    assert hi.net_spread_annualised < lo.net_spread_annualised


def test_higher_turnover_lowers_net_return():
    lo = P.project(gross_spread_annualised=0.08, breadth_median_names=1000,
                   monthly_turnover=0.1)
    hi = P.project(gross_spread_annualised=0.08, breadth_median_names=1000,
                   monthly_turnover=0.5)
    assert hi.net_spread_annualised < lo.net_spread_annualised


def test_positive_control_a_strong_wide_factor_is_viable():
    r = P.project(gross_spread_annualised=0.08, breadth_median_names=1200)
    assert V.assess(r).viable is True


def test_negative_control_a_weak_factor_is_not_viable():
    r = P.project(gross_spread_annualised=0.01, breadth_median_names=1200)
    verdict = V.assess(r)
    assert verdict.viable is False
    assert any("net spread" in f for f in verdict.failures)


def test_counterexample_a_narrow_factor_fails_the_breadth_gate():
    r = P.project(gross_spread_annualised=0.08, breadth_median_names=100)
    verdict = V.assess(r)
    assert verdict.viable is False
    assert any("breadth" in f for f in verdict.failures)


def test_the_evaluator_exposes_no_optimiser():
    for banned in ("optimise", "optimize", "best_policy", "select", "search",
                   "tune", "argmax"):
        assert not hasattr(P, banned), f"projection exposes {banned}"


def test_the_policy_is_fixed_and_declared():
    assert P.POLICY["construction"] == "long_top_decile_short_bottom_decile"
    assert P.POLICY["rebalance"] == "monthly"
    # the policy is a constant, not a function argument that could be searched
    import inspect
    sig = inspect.signature(P.project)
    assert "policy" not in sig.parameters


def test_viability_thresholds_are_declared_constants():
    """Declared BEFORE use, versioned like the section-13 criteria."""
    assert V.MIN_NET_SPREAD_ANNUALISED == 0.02
    assert V.MAX_MONTHLY_TURNOVER == 0.50
    assert V.MAX_DEGRADATION_FRACTION == 0.60
    assert V.MIN_BREADTH_MEDIAN_NAMES == 400


def test_counterexample_a_bad_breadth_is_refused():
    with pytest.raises(P.ProjectionError):
        P.project(gross_spread_annualised=0.05, breadth_median_names=0)


def test_the_projection_touches_no_candidate_or_forward_return():
    """It consumes a NUMBER (gross spread), never a signal or returns -- so it
    cannot pre-empt the one paid validation look."""
    import inspect
    from apex.audit.execution_path import executable_source
    code = executable_source(inspect.getsource(P))   # docstrings excluded
    for leak in ("forward_return", "compute_ic", "validation", "holdout"):
        assert leak not in code, f"projection executes against {leak}"


# --- the SECOND declared policy: long-only ----------------------------------

def test_long_only_is_deterministic_and_costs_bite():
    a = P.project_long_only(gross_long_excess_annualised=0.06, names_held=28)
    b = P.project_long_only(gross_long_excess_annualised=0.06, names_held=28)
    assert a == b
    assert a.net_long_excess_annualised < a.gross_long_excess_annualised
    # one-sided book: 4 * 0.40 * 2 * 20bp = 64bp/yr
    assert abs(a.annual_cost_drag - 0.0064) < 1e-12


def test_long_only_policy_is_fixed_and_declared():
    assert P.LONG_ONLY_POLICY["construction"] == "long_top_decile_only"
    assert P.LONG_ONLY_POLICY["rebalance"] == "quarterly"
    import inspect
    sig = inspect.signature(P.project_long_only)
    assert "policy" not in sig.parameters


def test_long_only_positive_control_a_strong_sleeve_is_viable():
    proj = P.project_long_only(gross_long_excess_annualised=0.06, names_held=28)
    assert V.assess_long_only(proj).viable


def test_long_only_negative_control_a_weak_sleeve_is_not_viable():
    proj = P.project_long_only(gross_long_excess_annualised=0.015, names_held=28)
    verdict = V.assess_long_only(proj)
    assert not verdict.viable
    assert any("net long excess" in f for f in verdict.failures)


def test_counterexample_a_sleeve_below_20_names_fails_the_gate():
    proj = P.project_long_only(gross_long_excess_annualised=0.06, names_held=12)
    verdict = V.assess_long_only(proj)
    assert not verdict.viable
    assert any("names held" in f for f in verdict.failures)


def test_long_only_viability_thresholds_are_declared_constants():
    assert V.MIN_NET_LONG_EXCESS_ANNUALISED == 0.02
    assert V.MAX_QUARTERLY_TURNOVER == 0.60
    assert V.MAX_LONG_ONLY_DEGRADATION == 0.60
    assert V.MIN_NAMES_HELD == 20


def test_no_function_evaluates_both_policies():
    """The two policies answer different deployment questions. A function that
    touched both would be a policy CHOOSER -- the search this module exists to
    not contain."""
    import inspect
    for name, fn in inspect.getmembers(P, inspect.isfunction):
        src = inspect.getsource(fn)
        assert not ("dict(POLICY)" in src and "dict(LONG_ONLY_POLICY)" in src), (
            f"{name} constructs results under BOTH declared policies"
        )
