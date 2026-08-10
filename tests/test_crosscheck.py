"""The secondary source is structurally incapable of influencing a filter.

CONVENTIONS A-002: Sharadar is authoritative for every universe filter; Norgate
is optional, for prices and cross-checking only. These tests assert that the
restriction is enforced by the TYPES rather than by anyone's memory -- a rule
that depends on discipline is a rule that fails on a deadline.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from apex.data.crosscheck import (
    CrossCheckReport,
    NorgateSecondary,
    NotWired,
    SecondarySource,
    cross_check,
)
from tests.conftest import hand_panel

DATES = pd.bdate_range("2020-01-01", periods=30)


class FakeSecondary:
    name = "fake-secondary"

    def __init__(self, frame):
        self._frame = frame

    def close_adjusted(self):
        return self._frame


def _panel(prices):
    return hand_panel(DATES, close_adj={"S1": prices, "S2": [50.0] * 30})


# ---------------------------------------------------------------------------
# THE STRUCTURAL GUARANTEE
# ---------------------------------------------------------------------------


def test_a_secondary_source_cannot_supply_anything_but_prices():
    """The protocol declares no surface for identity, shares or fundamentals.

    This is what "may never be authoritative for a universe filter" means in
    code: there is no method to call, so there is nothing to misuse.
    """
    surface = set(dir(SecondarySource))

    for forbidden in (
        "shares_outstanding",
        "market_cap",
        "securities",
        "corporate_actions",
        "delistings",
        "sectors",
        "exchanges",
    ):
        assert forbidden not in surface, (
            f"SecondarySource exposes '{forbidden}', which would let an optional "
            f"secondary vendor reach a universe filter"
        )
    assert "close_adjusted" in surface


def test_the_cross_check_cannot_return_data():
    """No overload of it produces a Panel, a price frame or an eligibility mask."""
    panel = _panel([100.0] * 30)
    report = cross_check(panel, FakeSecondary(panel.close_adj.copy()))

    assert isinstance(report, CrossCheckReport)
    for attribute in vars(report).values():
        assert not isinstance(attribute, pd.DataFrame), (
            "the report carries a DataFrame, which is a value someone could "
            "substitute back into the panel"
        )


def test_the_report_states_who_governs():
    panel = _panel([100.0] * 30)
    report = cross_check(panel, FakeSecondary(panel.close_adj.copy()))

    assert "Sharadar governs" in report.as_dict()["authority"]


# ---------------------------------------------------------------------------
# THE CHECK ITSELF
# ---------------------------------------------------------------------------


def test_agreeing_vendors_produce_a_clean_report():
    panel = _panel(list(100.0 + np.arange(30)))

    report = cross_check(panel, FakeSecondary(panel.close_adj.copy()))

    assert report.clean
    assert report.observations_compared > 0
    assert "no disagreements" in report.explain()


def test_a_disagreeing_security_is_named():
    panel = _panel(list(100.0 + np.arange(30)))
    other = panel.close_adj.copy()
    other.loc[DATES[10], "S1"] = 500.0

    report = cross_check(panel, FakeSecondary(other))

    assert not report.clean
    assert {d.security_id for d in report.disagreements} == {"S1"}
    assert "investigate, do not substitute" in report.explain()


def test_a_pure_adjustment_vintage_difference_is_not_a_disagreement():
    """A vendor using a different split factor rescales the whole LEVEL series.

    That cancels in a return. Comparing levels would flag every security and
    train everyone to ignore the report.
    """
    panel = _panel(list(100.0 + np.arange(30)))
    rescaled = panel.close_adj * 0.5

    report = cross_check(panel, FakeSecondary(rescaled))

    assert report.clean, (
        "a constant rescaling was reported as a disagreement, so the comparison "
        "is on levels rather than returns"
    )


def test_securities_the_secondary_does_not_carry_are_counted_not_dropped():
    panel = _panel([100.0] * 30)
    partial = panel.close_adj[["S1"]].copy()

    report = cross_check(panel, FakeSecondary(partial))

    assert report.securities_compared == 1
    assert report.securities_unmatched == 1


# ---------------------------------------------------------------------------
# THE UNWIRED ADAPTER
# ---------------------------------------------------------------------------


def test_the_cross_check_is_optional():
    panel = _panel([100.0] * 30)

    with pytest.raises(NotWired) as excinfo:
        cross_check(panel, None)
    assert "OPTIONAL" in str(excinfo.value)


def test_norgate_raises_rather_than_returning_an_empty_frame():
    """A silent empty frame is indistinguishable from a vendor outage."""
    with pytest.raises(NotWired) as excinfo:
        NorgateSecondary().close_adjusted()

    message = str(excinfo.value)
    assert "Windows-only" in message
    assert "Sharadar is authoritative" in message


def test_norgate_satisfies_the_prices_only_protocol():
    assert isinstance(NorgateSecondary(), SecondarySource)
    assert not hasattr(NorgateSecondary, "shares_outstanding")
    assert not hasattr(NorgateSecondary, "securities")
