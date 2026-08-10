"""Forward returns, delisting conventions, and the excess-return definition.

Timing firewall (protocol section 4):
    features computed from data through the close of day T
    portfolio formed at the close of day T+1
    forward return measured close T+1 -> close T+21

Frames here are indexed by SIGNAL date T, not formation date T+1, so they join
against the score panel without an off-by-one. The T+1 entry is applied inside.

Delisting (section 3, B4):
    performance-related, or not affirmatively identifiable as M&A or voluntary
    (the pre-registered CONVENTIONS section 1 fallback):
        R = (P_last / P_entry) * (1 - 0.30) - 1
    merger, acquisition or voluntary:
        R = (P_last / P_entry) - 1

Excess return (section 2, C11):
    Excess(i, T) = R(i, T) - median over the eligible universe at T.

Section 2 notes this is a single cross-sectional constant per date, so it changes
neither the IC nor the decile spread. It is computed because the protocol locks
it for reporting consistency, not because it moves a test.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from apex.config import Config
from apex.contracts import ForwardReturns, Panel

HELD = "held"
HELD_STALE = "held_last_valid_price"
DELIST_PERFORMANCE = "delist_performance"
DELIST_MERGER = "delist_merger"


def _delisting_multiplier(panel: Panel, config: Config) -> pd.Series:
    """Per security: 0.70 for performance delistings, 1.00 otherwise."""
    terminal = float(config.get("delisting.performance_terminal_return"))
    merger_reasons = {r.lower() for r in config.get("delisting.merger_reasons")}
    unknown_is_performance = bool(config.get("delisting.unknown_reason_is_performance"))

    reasons = panel.meta["delist_reason"]
    multiplier = pd.Series(1.0, index=panel.securities)

    for security, reason in reasons.items():
        if pd.isna(panel.meta.loc[security, "delist_date"]):
            continue
        label = str(reason).lower() if reason is not None else ""
        if label in merger_reasons:
            continue
        if label == "" or label == "none" or label == "nan":
            if not unknown_is_performance:
                continue
        multiplier.loc[security] = 1.0 + terminal

    return multiplier


def compute_forward_returns(
    panel: Panel, eligible: pd.DataFrame, config: Config
) -> ForwardReturns:
    lag = int(config.get("horizon.signal_to_formation_lag"))
    horizon = int(config.get("horizon.forward_trading_days"))

    close = panel.close_adj
    entry = close.shift(-lag)
    scheduled_exit = close.shift(-(lag + horizon))

    # Last price actually available at or before the scheduled exit. For a
    # delisting this is the final traded price (section 9: "closed at its last valid
    # price"); for a halt it is the most recent print.
    last_available = close.ffill().shift(-(lag + horizon))

    n_days, n_sec = close.shape
    exit_date = pd.Series(panel.dates, index=panel.dates).shift(-(lag + horizon))
    exit_values = exit_date.to_numpy()

    delist_values = panel.meta["delist_date"].to_numpy()
    known_delist = ~pd.isna(delist_values)
    known_exit = ~pd.isna(exit_values)

    delisted_by_exit = np.zeros((n_days, n_sec), dtype=bool)
    if known_delist.any() and known_exit.any():
        rows = np.flatnonzero(known_exit)
        comparison = (
            delist_values[None, known_delist].astype("datetime64[ns]")
            <= exit_values[rows, None].astype("datetime64[ns]")
        )
        block = np.zeros((rows.size, n_sec), dtype=bool)
        block[:, known_delist] = comparison
        delisted_by_exit[rows] = block

    delisted_by_exit = pd.DataFrame(delisted_by_exit, index=panel.dates, columns=panel.securities)

    exit_price = scheduled_exit.where(scheduled_exit.notna(), last_available)

    multiplier = _delisting_multiplier(panel, config)
    applied = pd.DataFrame(1.0, index=panel.dates, columns=panel.securities)
    applied = applied.mul(multiplier, axis=1).where(delisted_by_exit, 1.0)

    raw = (exit_price / entry) * applied - 1.0
    raw = raw.where(entry.notna() & exit_price.notna())

    is_performance = delisted_by_exit & (applied < 1.0)
    is_merger = delisted_by_exit & ~is_performance
    stale = ~delisted_by_exit & scheduled_exit.isna() & exit_price.notna()

    exit_reason = pd.DataFrame(HELD, index=panel.dates, columns=panel.securities, dtype=object)
    exit_reason = exit_reason.mask(stale, HELD_STALE)
    exit_reason = exit_reason.mask(is_merger, DELIST_MERGER)
    exit_reason = exit_reason.mask(is_performance, DELIST_PERFORMANCE)
    exit_reason = exit_reason.where(raw.notna())

    median = raw.where(eligible).median(axis=1)
    excess = raw.sub(median, axis=0)

    return ForwardReturns(
        dates=panel.dates,
        securities=panel.securities,
        raw=raw,
        excess=excess,
        exit_reason=exit_reason,
    )
