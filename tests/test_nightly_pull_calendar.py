"""The nightly pull must not fail every weekend.

Sharadar correctly returns zero rows for a Saturday. `fetch_table`
correctly calls zero rows "a failure, not an empty dataset". Combined
without a calendar, those two correct behaviors produced a job that went
red every weekend -- observed 2026-08-16, asking for 2026-08-15. A job
that cries wolf on schedule is worse than no job: it trains the operator
to ignore the one morning the failure is real.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import pandas as pd
import pytest

from nightly_pull import is_trading_day, pull_range


def test_weekends_and_holidays_are_not_trading_days():
    assert is_trading_day("2026-08-14") is True     # Friday
    assert is_trading_day("2026-08-15") is False    # Saturday (the failure)
    assert is_trading_day("2026-08-16") is False    # Sunday
    assert is_trading_day("2026-08-17") is True     # Monday
    assert is_trading_day("2026-12-25") is False    # holiday


def test_the_calendar_is_the_one_the_intraday_clock_uses():
    """Two calendars would eventually disagree, and the disagreement would
    surface as phantom data gaps."""
    from apex.intraday.sessions import HOLIDAYS
    for h in HOLIDAYS:
        assert is_trading_day(h) is False


@pytest.mark.parametrize("lake_end,today,expected", [
    # the observed failure: lake through Thu, job runs Sun -> Fri only
    ("2026-08-13", "2026-08-16", ("2026-08-14", "2026-08-14")),
    # job runs Sunday with the lake already through Friday -> clean no-op
    ("2026-08-14", "2026-08-16", None),
    # Saturday run, lake through Friday -> nothing to do
    ("2026-08-14", "2026-08-15", None),
    # Tuesday run -> Monday
    ("2026-08-14", "2026-08-18", ("2026-08-17", "2026-08-17")),
])
def test_the_window_is_trimmed_to_trading_days(monkeypatch, tmp_path,
                                               lake_end, today, expected):
    import nightly_pull as np_
    monkeypatch.setattr(np_, "lake_through", lambda root: lake_end)

    class _D:
        @staticmethod
        def now(tz=None):
            return pd.Timestamp(today).to_pydatetime()
    monkeypatch.setattr(np_.dt, "datetime", _D)
    assert pull_range(tmp_path) == expected


def test_a_zero_row_trading_day_is_still_a_hard_failure():
    """The trim must not become a blanket excuse. Zero rows on a day the
    exchange WAS open is the real alarm and must stay loud."""
    src = (Path(__file__).resolve().parent.parent
           / "apex" / "data" / "sharadar_api.py").read_text()
    assert "A failure, not an empty dataset" in src
