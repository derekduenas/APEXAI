"""A bar is assigned to a SESSION, and a session is a market-date fact.

OBSERVED. `assemble()` computes `day` and `prior_day` in America/New_York, but `_premarket_state` split the bars
on the UTC date. Those disagree for every bar after 20:00 ET, so the prior session's closing bar was counted as
a premarket print of today. Every sealed packet from 2026-08-18 onward shows the signature:
`premarket_bars = 1`, `last_bar_time = <today> 00:00:00+00:00` -- 20:00 ET the evening before.

The consequence was not merely cosmetic: `gap_frac` was then computed from the prior close against essentially
the same prior close, so it was always ~0, no name ever cleared the abnormality threshold, and `gap_map` was
empty in every packet this producer has ever sealed.
"""
from __future__ import annotations

import pandas as pd
import pytest

from apex.frontier import premarket as PM


def bars(pairs, symbol="SPY.US"):
    """(ET wall time, close) -> the vendor row shape the real normalizer consumes."""
    return [{"timestamp": int(pd.Timestamp(t, tz="America/New_York").timestamp()),
             "open": c, "high": c, "low": c, "close": c, "volume": 1000} for t, c in pairs]


class Gov:
    used = 0

    def acquire(self, cost):
        return True


PRIOR_DAY, DAY = "2026-09-11", "2026-09-14"


@pytest.fixture()
def served(monkeypatch):
    """Substitute ONLY the network call. normalize_rows and _premarket_state stay real."""
    from apex.intraday import eodhd

    def serve(rows):
        monkeypatch.setattr(eodhd, "fetch_intraday_chunk", lambda *a, **k: (rows, "fixture"))
        return PM._premarket_state("SPY.US", Gov(), DAY, PRIOR_DAY)
    return serve


class TestTheEveningBarBelongsToTheEveningSession:
    def test_the_2000_ET_close_bar_is_NOT_a_premarket_print_of_the_next_day(self, served):
        """2026-09-11 20:00 ET is 2026-09-12 00:00 UTC. It is Friday's close, not Monday's premarket."""
        rows = bars([("2026-09-11 15:59", 100.0), ("2026-09-11 20:00", 101.0)])
        st = served(rows)
        assert st["status"] == "OK"
        assert st.get("premarket_status") == "NO_PREMARKET_PRINTS_YET", st
        assert "gap_frac" not in st, "a gap computed from the prior evening's own close is not a gap"
        assert st["prior_close"] == 101.0, "the 20:00 ET bar is the prior session's last print"

    def test_a_real_premarket_print_IS_counted(self, served):
        rows = bars([("2026-09-11 20:00", 100.0), ("2026-09-14 08:10", 103.0)])
        st = served(rows)
        assert st["premarket_bars"] == 1
        assert st["premarket_last"] == 103.0
        assert st["gap_frac"] == pytest.approx(0.03, abs=1e-6)

    def test_premarket_bars_accumulate_across_the_morning(self, served):
        rows = bars([("2026-09-11 20:00", 100.0)]
                    + [("2026-09-14 %02d:%02d" % (h, m), 100.0 + h) for h in (4, 6, 8) for m in (0, 30)])
        st = served(rows)
        assert st["premarket_bars"] == 6

    def test_a_bar_after_2000_ET_on_the_SESSION_day_is_still_that_session(self, served):
        """The mirror case: today's own 20:00 ET bar has tomorrow's UTC date and must not vanish."""
        rows = bars([("2026-09-11 20:00", 100.0), ("2026-09-14 08:10", 103.0), ("2026-09-14 20:00", 105.0)])
        st = served(rows)
        assert st["premarket_bars"] == 2 and st["premarket_last"] == 105.0


class TestTheSignatureOfTheOldDefect:
    def test_the_old_filter_would_have_called_the_evening_bar_a_premarket_print(self):
        """Reproduces what the sealed packets actually recorded, so the fix is anchored to the evidence."""
        rows = bars([("2026-09-11 15:59", 100.0), ("2026-09-11 20:00", 101.0)])
        f = __import__("apex.intraday.eodhd", fromlist=["x"]).normalize_rows(rows, "SPY.US")
        old_today = f[f["event_time_utc"].dt.date.astype(str) == DAY]
        new_today = f[f["event_time_utc"].dt.tz_convert("America/New_York").dt.date.astype(str) == DAY]
        assert len(old_today) == 0 and len(new_today) == 0, "Friday 20:00 ET is 2026-09-12 UTC, not 09-14"

    def test_the_defect_bites_when_the_prior_session_is_the_previous_calendar_day(self):
        rows = bars([("2026-08-18 20:00", 101.0)])
        f = __import__("apex.intraday.eodhd", fromlist=["x"]).normalize_rows(rows, "SPY.US")
        old_today = f[f["event_time_utc"].dt.date.astype(str) == "2026-08-19"]
        new_today = f[f["event_time_utc"].dt.tz_convert("America/New_York").dt.date.astype(str) == "2026-08-19"]
        assert len(old_today) == 1, "this is the bar the packets recorded as premarket_bars=1"
        assert len(new_today) == 0, "and it belongs to 2026-08-18"
