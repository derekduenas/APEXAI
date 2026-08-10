"""Trading calendar and the locked formation schedule.

protocol section 9 locks the schedule: "Every 20th trading day, beginning with the first
date on which all features are computable (i.e. 200 trading days after the start
of available data). The schedule is generated mechanically from that anchor and
is never shifted, aligned to month-ends, or adjusted for holidays, earnings, or
any market condition."

Two distinct schedules follow from B2, and conflating them is the single easiest
way to run the wrong test:

  * DAILY formation dates -- the primary IC test. Every trading day on which all
    features are computable. In the holdout this is ~1,133 observations, which
    is what the Newey-West lag-25 correction in section 7 exists to handle.

  * The 20-DAY GRID -- the non-overlapping robustness subset AND the portfolio
    rebalance schedule. ~12.6 per year; ~57 in the holdout, matching section 7's
    "roughly 58".

The grid is anchored ONCE at trading day 200 of the data lake and then filtered
to whichever period is being evaluated. It is emphatically not re-anchored per
period: re-anchoring would shift the grid, and section 9 forbids shifting it.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from apex.config import Config


class CalendarError(ValueError):
    pass


@dataclass(frozen=True)
class FormationCalendar:
    """The trading calendar of the data lake plus both formation schedules."""

    trading_days: pd.DatetimeIndex
    anchor_index: int
    step: int

    @property
    def anchor(self) -> pd.Timestamp:
        return self.trading_days[self.anchor_index]

    def computable_days(self) -> pd.DatetimeIndex:
        """Every trading day at or after the feature-computability anchor."""
        return self.trading_days[self.anchor_index :]

    def grid(self) -> pd.DatetimeIndex:
        """The locked 20-trading-day grid, anchored globally at the lake anchor."""
        positions = range(self.anchor_index, len(self.trading_days), self.step)
        return self.trading_days[list(positions)]

    def daily_formation_dates(self, start, end) -> pd.DatetimeIndex:
        return self._clip(self.computable_days(), start, end)

    def grid_formation_dates(self, start, end) -> pd.DatetimeIndex:
        return self._clip(self.grid(), start, end)

    @staticmethod
    def _clip(index: pd.DatetimeIndex, start, end) -> pd.DatetimeIndex:
        lo, hi = pd.Timestamp(start), pd.Timestamp(end)
        if lo > hi:
            raise CalendarError(f"period start {lo.date()} is after end {hi.date()}")
        return index[(index >= lo) & (index <= hi)]

    def shift(self, dates: pd.DatetimeIndex, n: int) -> pd.Series:
        """Shift each date forward by n trading days.

        Returns NaT where the shifted date runs past the end of the calendar,
        so a truncated forward window is visible rather than silently short.
        """
        positions = self.trading_days.get_indexer(dates)
        if (positions < 0).any():
            bad = dates[positions < 0]
            raise CalendarError(f"dates absent from the trading calendar: {list(bad[:5])}")
        target = positions + n
        valid = target < len(self.trading_days)
        out = pd.Series(pd.NaT, index=dates, dtype="datetime64[ns]")
        out.loc[dates[valid]] = self.trading_days[target[valid]]
        return out


def build_calendar(trading_days: pd.DatetimeIndex, config: Config) -> FormationCalendar:
    """Construct the calendar from the data lake's own trading days.

    The calendar is DERIVED FROM THE DATA, never from a hardcoded holiday list.
    A hardcoded list that disagrees with the vendor's dates would silently drop
    or invent formation dates.
    """
    if not isinstance(trading_days, pd.DatetimeIndex):
        raise CalendarError("trading_days must be a DatetimeIndex")
    if not trading_days.is_monotonic_increasing or not trading_days.is_unique:
        raise CalendarError("trading_days must be sorted and unique")

    anchor = int(config.get("calendar.anchor_trading_days"))
    step = int(config.get("schedule.rebalance_step_days"))
    if len(trading_days) <= anchor:
        raise CalendarError(
            f"data lake has {len(trading_days)} trading days; the section 9 anchor "
            f"requires more than {anchor}"
        )
    return FormationCalendar(trading_days=trading_days, anchor_index=anchor, step=step)
