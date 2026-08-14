"""STAGE 3 -- the lookahead auditor.

Protocol section 4 states the timing firewall as an absolute:

    "Any calculation that references a price at or after T+1 in the feature set
     is a lookahead violation and voids the run."

Until now that firewall was DECLARED, not measured. `features._max_input_offsets`
returns a hand-written table of how far back each component's latest input sits,
and `FeaturePanel.max_input_date` stamps it. A hand-written table cannot catch a
bug in the code it describes -- if a feature silently started reading T+1, the
table would keep asserting it read T-5.

This module measures the property instead of asserting it, by black-box
perturbation:

    Destroy every observation strictly after T. Recompute. If anything the
    pipeline knows at T changed, it was reading the future.

That is unfakeable. It needs no instrumentation of individual numpy calls, it
covers universe eligibility and cross-sectional scoring as well as features, and
it cannot be satisfied by editing a comment.

Two independent modes, because they fail differently:

  PERTURB   -- overwrite post-T values, keeping the panel's shape. Catches a
               feature that reads a specific future row.
  TRUNCATE  -- cut the panel off at T. Catches code that reads "the last row"
               or otherwise depends on the panel's extent.

The final test in this file is the one that proves the auditor works at all: a
deliberately introduced one-day lookahead must be CAUGHT, and must visibly
inflate the IC. An auditor that has never caught a violation is decoration.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from apex.audit.lookahead import (
    AuditReport,
    audit_lookahead,
    audit_targets,
    perturb_after,
    truncate_at,
)
from apex.config import load_config
from apex.data.synthetic import SyntheticSource
from apex.evaluate.ic import evaluate_ic
from apex.pipeline import build_panel_pipeline, evaluate


# ---------------------------------------------------------------------------
# a compact panel; the audit recomputes the pipeline once per date per mode
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def audit_config():
    # Pins the frozen #001-#003 large-cap universe: this module audits layer
    # behavior on the synthetic panel, which does not inhabit #004's
    # registered small-cap band.
    from tests.conftest import LEGACY_LARGE_CAP_UNIVERSE, patched
    return patched(load_config("experiment", "costs", "synthetic"),
                   LEGACY_LARGE_CAP_UNIVERSE)


@pytest.fixture(scope="module")
def audit_panel(audit_config):
    source = SyntheticSource(
        config=audit_config,
        seed=4242,
        alpha=0.0,
        overrides={
            "panel.n_securities": 150,
            "panel.start": "2004-01-01",
            "panel.end": "2006-12-31",
            "sectors.n_sectors": 4,
        },
    )
    return source.load()


@pytest.fixture(scope="module")
def audit_dates(audit_panel, audit_config):
    """A few dates late enough that every feature is computable."""
    anchor = int(audit_config.get("calendar.anchor_trading_days"))
    usable = audit_panel.dates[anchor + 20 :]
    return pd.DatetimeIndex([usable[10], usable[len(usable) // 2], usable[-30]])


# ---------------------------------------------------------------------------
# guard the guard -- a vacuous audit passes trivially
# ---------------------------------------------------------------------------


def test_perturbation_actually_destroys_the_future(audit_panel):
    """If the perturbation changed nothing, every audit below is meaningless."""
    date = audit_panel.dates[400]
    perturbed = perturb_after(audit_panel, date, seed=1)

    before = audit_panel.close_adj.loc[:date]
    after = audit_panel.close_adj.loc[audit_panel.dates > date]

    assert perturbed.close_adj.loc[:date].equals(before), (
        "the perturbation must leave data at or before T untouched, or the audit "
        "is comparing two different histories rather than testing lookahead"
    )
    # Denominator is cells that HAVE a value: the panel is ~15% NaN after T
    # (halts, late listings, delistings), and a NaN cannot be perturbed.
    present = after.notna().to_numpy()
    changed = ((perturbed.close_adj.loc[audit_panel.dates > date] != after).to_numpy()) & present
    assert changed.sum() == present.sum(), (
        f"the perturbation left {present.sum() - changed.sum()} of {present.sum()} "
        f"observed future values intact; the audit would pass trivially on them"
    )


def test_truncation_removes_every_row_after_the_date(audit_panel):
    date = audit_panel.dates[400]
    truncated = truncate_at(audit_panel, date)

    assert truncated.dates.max() == date
    assert truncated.dates.equals(audit_panel.dates[audit_panel.dates <= date])
    assert truncated.close_adj.loc[:date].equals(audit_panel.close_adj.loc[:date])


def test_audit_targets_cover_everything_decided_before_the_trade(audit_panel, audit_config):
    """Eligibility, every feature component, and the score itself.

    Forward returns are deliberately NOT audited: they are the label and are
    supposed to look forward.
    """
    targets = audit_targets(audit_panel, audit_config)

    assert "eligible" in targets
    assert "apex_score" in targets
    for component in (
        "f1_mom_126",
        "f1_mom_63",
        "f2_close_over_sma200",
        "f2_frac_above_sma50",
        "f3_vol_ratio",
        "f3_atr_over_close",
        "f4_vs_sector",
        "f4_vs_market",
    ):
        assert component in targets, f"{component} is not audited for lookahead"
    assert not any("forward" in k or "return" in k for k in targets), (
        "forward returns must not be audited; they are the label and look "
        "forward by design"
    )


# ---------------------------------------------------------------------------
# the pipeline as it stands
# ---------------------------------------------------------------------------


def test_the_real_pipeline_has_no_lookahead(audit_panel, audit_config, audit_dates):
    """The headline assertion. Protocol section 4, measured rather than declared."""
    report = audit_lookahead(audit_panel, audit_config, audit_dates)

    assert report.clean, report.explain()
    assert report.n_comparisons > 0, "the audit compared nothing"


def test_audit_runs_both_modes(audit_panel, audit_config, audit_dates):
    report = audit_lookahead(audit_panel, audit_config, audit_dates)
    assert set(report.modes) == {"perturb", "truncate"}


# ---------------------------------------------------------------------------
# MUTATION -- does the auditor actually catch a violation?
# ---------------------------------------------------------------------------


def _leaky_targets(shift: int):
    """Build an audit target function with a deliberate `shift`-day lookahead."""

    def targets(panel, config):
        clean = audit_targets(panel, config)
        # F2 reads the close of T. Shifting it back by `shift` rows makes the
        # value at row T the value that was computed at T+shift -- exactly the
        # bug protocol section 4 forbids.
        leaked = dict(clean)
        leaked["f2_close_over_sma200"] = clean["f2_close_over_sma200"].shift(-shift)
        return leaked

    return targets


def test_audit_catches_a_one_day_lookahead(audit_panel, audit_config, audit_dates):
    """The mutation test. A one-day leak is the smallest violation that matters."""
    report = audit_lookahead(
        audit_panel, audit_config, audit_dates, target_fn=_leaky_targets(1)
    )

    assert not report.clean, (
        "a deliberately introduced one-day lookahead was NOT caught. The auditor "
        "does not work, and every clean report it has ever produced is worthless."
    )
    assert any(v.component == "f2_close_over_sma200" for v in report.violations), (
        f"the auditor flagged something, but not the component that was leaked: "
        f"{sorted({v.component for v in report.violations})}"
    )


def test_audit_names_the_date_and_component_it_caught(audit_panel, audit_config, audit_dates):
    report = audit_lookahead(
        audit_panel, audit_config, audit_dates, target_fn=_leaky_targets(1)
    )

    violation = next(v for v in report.violations if v.component == "f2_close_over_sma200")
    assert violation.date in set(audit_dates)
    assert violation.n_securities > 0
    assert violation.max_abs_delta > 0
    assert "f2_close_over_sma200" in report.explain()


def test_a_clean_component_is_not_flagged(audit_panel, audit_config, audit_dates):
    """Specificity: the auditor must not indict components that are fine."""
    report = audit_lookahead(
        audit_panel, audit_config, audit_dates, target_fn=_leaky_targets(1)
    )

    flagged = {v.component for v in report.violations}
    assert "f1_mom_126" not in flagged, (
        f"F1 was not tampered with but was flagged; the auditor produces false "
        f"positives and its clean reports mean nothing either. Flagged: {flagged}"
    )


@pytest.mark.slow
def test_lookahead_visibly_inflates_the_ic(audit_config):
    """Proves the audited property is the one that matters commercially.

    A leak the auditor catches must also be a leak that manufactures apparent
    alpha. If shifting a feature forward changed nothing measurable, catching it
    would be pedantry rather than protection.
    """
    source = SyntheticSource(
        config=audit_config,
        seed=4242,
        alpha=0.0,
        overrides={
            "panel.n_securities": 150,
            "panel.start": "2004-01-01",
            "panel.end": "2006-12-31",
            "sectors.n_sectors": 4,
        },
    )
    output = build_panel_pipeline(source.load(), audit_config)
    period = audit_config.period("in_sample")
    honest = evaluate(output, audit_config, period["start"], "2006-12-31")

    # The same leak the auditor catches, applied to the score itself: the score
    # at T becomes the score that was only knowable at T+20.
    leaked_score = output.scores.apex_score.shift(-20)
    dates = output.calendar.daily_formation_dates(period["start"], "2006-12-31")
    leaked = evaluate_ic(
        leaked_score,
        output.forward_returns.excess,
        output.universe.eligible,
        audit_config,
        dates,
        "daily_newey_west",
    )

    assert abs(leaked.mean) > abs(honest.ic_daily.mean) + 0.02, (
        f"a 20-day lookahead moved mean IC only from {honest.ic_daily.mean:+.4f} "
        f"to {leaked.mean:+.4f}. Either the null panel has no forward structure "
        f"to leak, or the evaluation is not reading the score."
    )


def test_report_is_a_frozen_value_object(audit_panel, audit_config, audit_dates):
    report = audit_lookahead(audit_panel, audit_config, audit_dates[:1])
    assert isinstance(report, AuditReport)
    with pytest.raises(Exception):
        report.clean = True  # type: ignore[misc]


def test_audit_refuses_a_date_outside_the_calendar(audit_panel, audit_config):
    with pytest.raises(Exception):
        audit_lookahead(
            audit_panel, audit_config, pd.DatetimeIndex([pd.Timestamp("1990-01-02")])
        )


def test_audit_refuses_a_date_with_no_computable_features(audit_panel, audit_config):
    """Auditing before the anchor compares NaN against NaN and always passes."""
    too_early = pd.DatetimeIndex([audit_panel.dates[5]])
    with pytest.raises(Exception):
        audit_lookahead(audit_panel, audit_config, too_early)
