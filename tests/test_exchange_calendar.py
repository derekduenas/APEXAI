"""NYSE regular-session calendar: DST, early closes, holidays, refusals."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from apex.intraday import sessions as S
from apex.world_model.exp001b import exchange_calendar as C


def _hm(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%H:%M")


def test_regular_session_is_exchange_local_and_dst_aware():
    winter = C.session_bounds("2019-01-15")
    summer = C.session_bounds("2019-06-03")
    assert (_hm(winter["open_utc"]), _hm(winter["close_utc"])) == ("14:30", "21:00")
    assert (_hm(summer["open_utc"]), _hm(summer["close_utc"])) == ("13:30", "20:00")
    assert winter["regular_minutes"] == summer["regular_minutes"] == 390
    assert winter["utc_offset_hours"] == -5.0 and summer["utc_offset_hours"] == -4.0
    # the DST transition days themselves
    assert _hm(C.session_bounds("2019-03-08")["open_utc"]) == "14:30"   # Friday before spring forward
    assert _hm(C.session_bounds("2019-03-11")["open_utc"]) == "13:30"   # Monday after


@pytest.mark.parametrize("day,close", [("2019-11-29", "18:00"), ("2019-12-24", "18:00"),
                                       ("2019-07-03", "17:00"), ("2024-11-29", "18:00"),
                                       ("2018-12-24", "18:00"), ("2023-07-03", "17:00")])
def test_early_closes(day, close):
    b = C.session_bounds(day)
    assert b["early_close"] and _hm(b["close_utc"]) == close and b["regular_minutes"] == 210


@pytest.mark.parametrize("day", ["2019-07-03", "2019-11-29", "2020-12-24", "2019-12-24"])
def test_early_close_table_membership(day):
    assert day in C.EARLY_CLOSES


@pytest.mark.parametrize("day,why", [
    ("2019-07-04", "HOLIDAY"), ("2018-12-05", "HOLIDAY"), ("2025-01-09", "HOLIDAY"),
    ("2022-06-20", "HOLIDAY"),      # Juneteenth observed (Sunday -> Monday)
    ("2021-12-24", "HOLIDAY"),      # Christmas observed (Saturday -> Friday)
    ("2020-07-03", "HOLIDAY"),      # Independence Day observed
    ("2019-04-19", "HOLIDAY"),      # Good Friday
    ("2019-01-21", "HOLIDAY"),      # MLK
    ("2019-06-01", "WEEKEND"), ("2019-06-02", "WEEKEND"),
    ("2015-12-31", "OUTSIDE_CALENDAR_RANGE"), ("2027-01-04", "OUTSIDE_CALENDAR_RANGE"),
])
def test_non_sessions_are_refused_by_name(day, why):
    with pytest.raises(C.NotASession, match="^" + why):
        C.session_bounds(day)


def test_new_year_on_saturday_is_not_observed_on_friday():
    assert "2021-12-31" not in C.HOLIDAYS
    assert C.session_bounds("2021-12-31")["regular_minutes"] == 390
    assert "2017-01-02" in C.HOLIDAYS                      # Sunday -> Monday IS observed


def test_no_early_close_on_days_that_are_holidays_or_weekends():
    assert "2020-07-03" not in C.EARLY_CLOSES               # observed holiday
    assert "2021-12-24" not in C.EARLY_CLOSES               # observed holiday
    assert "2022-12-24" not in C.EARLY_CLOSES               # Saturday
    assert "2016-07-03" not in C.EARLY_CLOSES               # Sunday


def test_parity_with_the_governed_sessions_module_across_years():
    """The laboratory may not import apex.intraday; prove the rule is the
    same by running both over a grid: every 15 minutes of every 7th day
    2016-2026 plus the DST-transition and early-close days, with the SAME
    tables handed to the production classifier."""
    import itertools
    from datetime import date, timedelta
    days = [date(2016, 1, 1) + timedelta(days=7 * k) for k in range(0, 570)]
    days += [date(y, m, d) for y, m, d in ((2019, 3, 10), (2019, 3, 11), (2019, 11, 3), (2019, 11, 4),
                                           (2019, 11, 29), (2019, 7, 3), (2024, 12, 24), (2018, 12, 5))]
    n = 0
    for d, (h, m) in itertools.product(days, [(h, m) for h in range(24) for m in (0, 15, 30, 45)]):
        ts = datetime(d.year, d.month, d.day, h, m, tzinfo=timezone.utc).timestamp()
        ours = C.classify_utc(ts)
        theirs = S.classify(datetime.fromtimestamp(ts, timezone.utc), early_closes=C.EARLY_CLOSES,
                            holidays=C.HOLIDAYS).value
        assert ours == theirs, (d, h, m, ours, theirs)
        n += 1
    assert n > 50000


def test_calendar_lives_inside_the_experiment_package_and_imports_no_production_apex():
    import ast
    from pathlib import Path
    p = Path(C.__file__)
    assert p.parent.name == "exp001b"
    tree = ast.parse(p.read_text())
    mods = {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | \
           {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert not any(m.startswith("apex.") and not m.startswith("apex.world_model") for m in mods), mods


def test_classification_rule():
    ts_w = datetime(2019, 1, 15, 14, 0, tzinfo=timezone.utc).timestamp()   # 09:00 ET winter
    ts_s = datetime(2019, 6, 3, 14, 0, tzinfo=timezone.utc).timestamp()    # 10:00 ET summer
    assert C.classify_utc(ts_w) == "PREMARKET" and C.classify_utc(ts_s) == "REGULAR"
    ts_e = datetime(2019, 11, 29, 18, 30, tzinfo=timezone.utc).timestamp()  # 13:30 ET early-close day
    assert C.classify_utc(ts_e) == "POSTMARKET"
    assert C.local_date(datetime(2019, 1, 16, 2, 0, tzinfo=timezone.utc).timestamp()) == "2019-01-15"
