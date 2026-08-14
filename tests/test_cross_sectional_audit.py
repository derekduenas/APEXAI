"""Ruling 5 -- preprocessing must be strictly cross-sectional per date.

    "Assert that winsorization, z-scoring, and ranking are strictly
     cross-sectional per date. No global fit (no using future distribution
     moments). If violated -> hard fail."

WHY THIS IS NOT ALREADY COVERED BY THE LOOKAHEAD AUDITOR

The Stage 3 auditor destroys everything AFTER T and checks that nothing known at
T moved. That catches a preprocessing step fitted on future data. It does NOT
catch a step fitted on an EXPANDING window of past data -- a percentile computed
over "all history up to T", say. That is not lookahead, but it is not
cross-sectional either, and protocol section 5 specifies a per-date
cross-section: winsorise at the 1st/99th percentiles OF THAT DATE, z-score
against THAT DATE's mean and standard deviation, rank within THAT DATE.

A global or expanding fit would change what a security's score means from one
date to the next, and would couple every score to the sample it happened to be
computed over.

THE TEST

Destroy every row EXCEPT T -- past and future alike -- recompute, and require
row T to be bit-identical. Strict per-date cross-sectionality is exactly the
property that makes row T independent of every other row, so this is a direct
measurement of the ruling rather than a proxy for it.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from apex.audit.cross_sectional import (
    CrossSectionalViolation,
    audit_cross_sectional,
    perturb_all_rows_except,
)
from apex.config import load_config
from apex.features.composite import percentile_rank, winsorise, zscore
from tests.conftest import patched

DATES = pd.bdate_range("2020-01-01", periods=25)
SECURITIES = pd.Index([f"S{i}" for i in range(40)], name="security_id")


@pytest.fixture(scope="module")
def config():
    # This module audits #001-era layer behavior on the synthetic panel; it
    # pins the frozen large-cap universe rather than drifting with whatever
    # experiment is currently registered (#004 flipped the live universe to
    # the small-cap band, which the synthetic panel does not inhabit).
    from tests.conftest import LEGACY_LARGE_CAP_UNIVERSE, patched
    return patched(load_config("experiment", "costs", "synthetic"),
                   LEGACY_LARGE_CAP_UNIVERSE)


def _frame(seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    return pd.DataFrame(
        rng.standard_normal((len(DATES), len(SECURITIES))), index=DATES, columns=SECURITIES
    )


# ---------------------------------------------------------------------------
# the primitives, individually
# ---------------------------------------------------------------------------


def test_winsorise_row_depends_only_on_its_own_row():
    values = _frame(1)
    target = DATES[10]

    baseline = winsorise(values, 0.01, 0.99).loc[target]
    disturbed = values.copy()
    disturbed.loc[disturbed.index != target] *= 1000.0
    after = winsorise(disturbed, 0.01, 0.99).loc[target]

    pd.testing.assert_series_equal(baseline, after, check_names=False)


def test_zscore_row_depends_only_on_its_own_row():
    """A global mean or standard deviation would make this fail."""
    values = _frame(2)
    target = DATES[10]

    baseline = zscore(values, ddof=1).loc[target]
    disturbed = values.copy()
    disturbed.loc[disturbed.index != target] += 50.0
    after = zscore(disturbed, ddof=1).loc[target]

    pd.testing.assert_series_equal(baseline, after, check_names=False)


def test_percentile_rank_row_depends_only_on_its_own_row():
    values = _frame(3)
    target = DATES[10]

    baseline = percentile_rank(values, "first", 100.0).loc[target]
    disturbed = values.copy()
    disturbed.loc[disturbed.index != target] = -999.0
    after = percentile_rank(disturbed, "first", 100.0).loc[target]

    pd.testing.assert_series_equal(baseline, after, check_names=False)


def test_the_probe_actually_disturbs_the_other_rows():
    """Guard the guard: an inert perturbation makes every test above vacuous."""
    values = _frame(4)
    target = DATES[10]

    disturbed = perturb_all_rows_except(values, target, seed=0)

    assert disturbed.loc[target].equals(values.loc[target])
    other = values.index != target
    assert not disturbed.loc[other].equals(values.loc[other])


# ---------------------------------------------------------------------------
# the composite, end to end
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def pipeline_output(config):
    from apex.data.synthetic import SyntheticSource
    from apex.pipeline import build_panel_pipeline

    source = SyntheticSource(
        config=config,
        seed=31337,
        alpha=0.0,
        overrides={
            "panel.n_securities": 120,
            "panel.start": "2004-01-01",
            "panel.end": "2006-06-30",
            "sectors.n_sectors": 4,
        },
    )
    return build_panel_pipeline(source.load(), config)


@pytest.fixture(scope="module")
def probe_dates(pipeline_output, config):
    """Dates that are actually scored.

    The section 9 grid anchors at trading day 200, but section 3 requires 252
    trading days of history, so the lake's first ~252 days carry an EMPTY
    universe by construction -- which is exactly why C7 starts the lake a year
    before the in-sample period. Probing there would compare NaN to NaN.
    """
    scored = pipeline_output.scores.apex_score.notna().any(axis=1)
    usable = pipeline_output.scores.apex_score.index[scored]
    assert len(usable) > 10, "the fixture panel produced almost nothing to audit"
    return pd.DatetimeIndex([usable[2], usable[len(usable) // 2], usable[-2]])


def test_the_composite_is_strictly_cross_sectional(pipeline_output, config, probe_dates):
    """The headline assertion for ruling 5."""
    report = audit_cross_sectional(
        pipeline_output.features, pipeline_output.universe.eligible, config, probe_dates
    )

    assert report.clean, report.explain()
    assert report.n_comparisons > 0


def _global_winsorise_scores(features, eligible, config):
    """A GLOBAL winsorisation -- the forbidden fit, in its detectable form.

    Clipping is non-affine, so unlike a global mean or standard deviation it
    genuinely changes which securities are clipped at T when other dates move.
    """
    import dataclasses

    from apex.features.composite import build_scores

    leaked = {}
    for name, frame in features.components.items():
        restricted = frame.where(eligible)
        flat = restricted.stack()
        leaked[name] = restricted.clip(lower=flat.quantile(0.01), upper=flat.quantile(0.99))
    return build_scores(dataclasses.replace(features, components=leaked), eligible, config)


def test_an_affine_global_fit_is_provably_inert(pipeline_output, config, probe_dates):
    """Pins a real robustness property of the composite, discovered here.

    Section 5 z-scores and then percentile-ranks, and BOTH steps are affine
    invariant. A global mean or a global standard deviation therefore cannot
    change the APEX Score at all -- there is no violation to detect, because
    there is no effect. Worth asserting rather than assuming: if the composite
    ever gains a non-affine step, this stops being true and someone should find
    out from a failing test.
    """
    import dataclasses

    from apex.features.composite import build_scores

    def globally_standardised(features, eligible, config):
        shifted = {
            name: (frame - frame.stack().mean()) / frame.stack().std()
            for name, frame in features.components.items()
        }
        return build_scores(
            dataclasses.replace(features, components=shifted), eligible, config
        )

    honest = build_scores(pipeline_output.features, pipeline_output.universe.eligible, config)
    leaked = globally_standardised(
        pipeline_output.features, pipeline_output.universe.eligible, config
    )

    pd.testing.assert_frame_equal(honest.apex_score, leaked.apex_score)


def test_the_audit_catches_a_global_winsorisation(pipeline_output, config, probe_dates):
    """The headline catch for ruling 5: a non-affine whole-sample fit."""
    report = audit_cross_sectional(
        pipeline_output.features,
        pipeline_output.universe.eligible,
        config,
        probe_dates,
        score_fn=_global_winsorise_scores,
    )

    assert not report.clean, (
        "a winsorisation fitted on the WHOLE SAMPLE was not caught; the audit "
        "cannot detect a global fit and ruling 5 is unenforced"
    )
    assert any(v.component == "apex_score" for v in report.violations)


def test_the_audit_catches_a_past_only_expanding_fit(pipeline_output, config, probe_dates):
    """Not lookahead -- past data only -- but still not cross-sectional.

    This is the case that justifies the module existing. The Stage 3 auditor
    perturbs only the FUTURE, so a clip bound fitted on an expanding window of
    PAST data is invisible to it and visible here.
    """
    import dataclasses

    from apex.features.composite import build_scores

    def expanding_clip(features, eligible, config):
        leaked = {}
        for name, frame in features.components.items():
            bound = frame.abs().max(axis=1).expanding().mean()
            leaked[name] = frame.clip(lower=-bound, upper=bound, axis=0)
        return build_scores(
            dataclasses.replace(features, components=leaked), eligible, config
        )

    report = audit_cross_sectional(
        pipeline_output.features,
        pipeline_output.universe.eligible,
        config,
        probe_dates,
        score_fn=expanding_clip,
    )

    assert not report.clean, (
        "an expanding-window fit over PAST data was not caught. The lookahead "
        "auditor cannot see this one either, which is precisely why ruling 5 "
        "needs its own guard."
    )


def test_the_violation_names_what_it_caught(pipeline_output, config, probe_dates):
    report = audit_cross_sectional(
        pipeline_output.features,
        pipeline_output.universe.eligible,
        config,
        probe_dates,
        score_fn=_global_winsorise_scores,
    )

    violation = report.violations[0]
    assert isinstance(violation, CrossSectionalViolation)
    assert violation.date in set(probe_dates)
    assert violation.n_securities > 0
    assert "cross-sectional" in report.explain().lower()


def test_category_scores_are_audited_too(pipeline_output, config, probe_dates):
    report = audit_cross_sectional(
        pipeline_output.features, pipeline_output.universe.eligible, config, probe_dates
    )

    assert {"f1", "f2", "f3", "f4"} <= set(report.components)
    assert "apex_score" in report.components
    assert "decile" in report.components


def test_an_all_nan_probe_date_is_refused(pipeline_output, config):
    """A date with nothing scored would compare NaN to NaN and pass vacuously."""
    too_early = pd.DatetimeIndex([pipeline_output.panel.dates[3]])

    with pytest.raises(Exception):
        audit_cross_sectional(
            pipeline_output.features, pipeline_output.universe.eligible, config, too_early
        )


def test_winsorisation_limits_are_per_date_not_global(pipeline_output, config, probe_dates):
    """Section 5 step 1 specifically: the 1st/99th percentiles OF THAT DATE."""
    tightened = patched(config, {"composite.winsorize_lower": 0.10, "composite.winsorize_upper": 0.90})

    report = audit_cross_sectional(
        pipeline_output.features, pipeline_output.universe.eligible, tightened, probe_dates
    )

    assert report.clean, report.explain()
