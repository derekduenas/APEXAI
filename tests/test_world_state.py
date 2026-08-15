"""Track 4's five mandated test families (v4.0 §2.5): vintage integrity /
classifier online / labels never revised / staleness propagation /
REVISED_ONLY exclusion. Plus the refusal that defines the module: no notion
of a 'profitable' state exists anywhere in it.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from apex.world.state import (
    LabelStore, StateVariable, classify_online, cross_sectional_state_variables,
    detection_lag_days, index_state_variables,
)
from apex.world.vintage import RevisedOnlyRefused, VintageError, VintageStore


# --- 1. vintage integrity ----------------------------------------------------

def test_a_revised_value_cannot_be_returned_before_its_revision(tmp_path):
    vs = VintageStore(tmp_path / "v.jsonl")
    vs.declare("gdp", source="test", revised_only=False)
    vs.add("gdp", "2026Q1", 2.1, released_at="2026-04-28")   # first release
    vs.add("gdp", "2026Q1", 2.8, released_at="2026-06-26")   # revision

    # Before the revision was published, only the first release is knowable.
    assert vs.asof("gdp", "2026Q1", "2026-05-15") == 2.1
    # After it, the revision governs.
    assert vs.asof("gdp", "2026Q1", "2026-07-01") == 2.8
    # Before ANY release: nothing was knowable.
    assert vs.asof("gdp", "2026Q1", "2026-04-01") is None
    # `latest` is display-only and returns the revision regardless.
    assert vs.latest("gdp", "2026Q1") == 2.8


def test_undeclared_series_are_refused_and_flags_are_immutable(tmp_path):
    vs = VintageStore(tmp_path / "v.jsonl")
    with pytest.raises(VintageError, match="declared before"):
        vs.add("cpi", "2026-06", 3.1, released_at="2026-07-10")
    vs.declare("cpi", source="test", revised_only=True)
    with pytest.raises(VintageError, match="cannot be revised"):
        vs.declare("cpi", source="test", revised_only=False)


# --- 2. the classifier is online --------------------------------------------

def _spy(n=1600, seed=5):
    rng = np.random.default_rng(seed)
    days = pd.bdate_range("2020-01-01", periods=n)
    return pd.Series(100 * np.cumprod(1 + rng.normal(3e-4, 0.01, n)), index=days)


def test_classifier_output_is_identical_with_or_without_future_data():
    spy = _spy()
    t = spy.index[1200]
    with_future = classify_online(spy, t)
    truncated = classify_online(spy.loc[:t], t)
    assert with_future == truncated, (
        "the classifier's output at T changed when post-T data existed: "
        "it is not online")


def test_the_vol_threshold_is_a_trailing_quantile_not_full_sample():
    """Append a violent future; the state at T must not move."""
    spy = _spy()
    t = spy.index[1200]
    before = classify_online(spy, t)
    crash = spy.copy()
    crash.iloc[1300:] = crash.iloc[1300] * np.cumprod(
        1 + np.random.default_rng(0).normal(-0.01, 0.05, len(crash) - 1300))
    assert classify_online(crash, t) == before


# --- 3. labels are never revised --------------------------------------------

def test_a_past_label_cannot_be_overwritten(tmp_path):
    store = LabelStore(tmp_path / "labels.jsonl")
    store.assign({"date": "2026-07-06", "regime": "CALM_UP", "stress": False,
                  "uncertain": False})
    # idempotent re-assignment of the SAME label is fine
    store.assign({"date": "2026-07-06", "regime": "CALM_UP", "stress": False,
                  "uncertain": False})
    with pytest.raises(ValueError, match="never revised"):
        store.assign({"date": "2026-07-06", "regime": "VOL_DOWN",
                      "stress": True, "uncertain": False})
    assert store.series().loc[pd.Timestamp("2026-07-06")] == "CALM_UP"


# --- 4. staleness propagates ------------------------------------------------

def test_staleness_is_infectious():
    fresh = StateVariable("a", 1.0, "2026-08-14", "2026-08-14", "t", stale=False)
    old = StateVariable("b", 2.0, "2026-07-01", "2026-07-01", "t", stale=True)
    assert StateVariable.combine_staleness(fresh, fresh) is False
    assert StateVariable.combine_staleness(fresh, old) is True, (
        "one stale input must make the combination stale")


def test_a_variable_computed_from_old_data_is_born_stale():
    spy = _spy()
    asof = spy.index[-1]
    vars_ = index_state_variables(spy, asof, now=asof + pd.Timedelta(days=20))
    assert all(v.stale for v in vars_.values()), (
        "20 days after its data date, every variable must flag stale")
    vars_fresh = index_state_variables(spy, asof, now=asof)
    assert not any(v.stale for v in vars_fresh.values())


# --- 5. REVISED_ONLY exclusion ----------------------------------------------

def test_a_revised_only_series_cannot_enter_a_confirmatory_path(tmp_path):
    vs = VintageStore(tmp_path / "v.jsonl")
    vs.declare("cpi_revised", source="test", revised_only=True)
    vs.declare("payrolls_vintaged", source="test", revised_only=False)
    with pytest.raises(RevisedOnlyRefused, match="never evidence"):
        vs.require_confirmatory_series("cpi_revised", context="test")
    vs.require_confirmatory_series("payrolls_vintaged", context="test")  # passes


# --- the module's defining refusal ------------------------------------------

def test_no_notion_of_a_profitable_state_exists_in_the_module():
    """The state layer describes; it never selects. Any appearance of
    per-state returns or state-conditional performance is the hidden
    optimizer the operator's ruling forbids."""
    import inspect

    import apex.world.state as W
    import apex.world.vintage as V
    from apex.audit.execution_path import executable_source
    for mod in (W, V):
        # executable source only -- docstrings legitimately NAME the refusal
        # (prose-vs-code is this repo's oldest recurring trap)
        src = executable_source(inspect.getsource(mod)).lower()
        for banned in ("sharpe", "profitab", "best_regime", "select_regime",
                       "conditional_return", "expectancy"):
            assert banned not in src, (
                f"{mod.__name__} mentions {banned!r}: the state layer must "
                f"not know which states make money")


def test_detection_lag_is_reported_as_a_diagnostic():
    spy = _spy(2000)
    labels = pd.Series(
        [classify_online(spy, t)["regime"] for t in spy.index[900::10]],
        index=spy.index[900::10])
    lag = detection_lag_days(labels, spy)
    assert "mean_lag_days" in lag and "durable_transitions_in_reference" in lag
    assert "contaminated" in lag["note"], "the reference must confess itself"
