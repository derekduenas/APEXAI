"""Point-in-time universe construction (protocol section 3).

Eligibility is decided from data available AT each date, for every trading day
in the lake -- not only on rebalance dates -- so section 9's per-date log is a
by-product of the decision rather than a separate reconstruction that could
drift from it.

The universe is built from the full delisted-inclusive panel. A universe
constructed from a current ticker list is invalid (section 3) and
`test_universe_pit.py` fails if one is ever used.

Level filters ($5 close, $1B market cap) use UNADJUSTED as-of-date prices, per
CONVENTIONS section 4.4: cumulative adjustment factors cancel in ratios but not in
levels, so applying a modern factor to a historical level test is lookahead.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from apex.config import Config
from apex.contracts import FILTER_NAMES, Panel, UniverseSnapshot


def build_universe(panel: Panel, config: Config) -> UniverseSnapshot:
    settings = config.section("universe")

    tradable = panel.close_unadj.notna()

    # -- static attribute filters -------------------------------------------
    allowed_types = set(settings["allowed_security_types"])
    allowed_exchanges = set(settings["allowed_exchanges"])
    type_ok = panel.meta["security_type"].isin(allowed_types)
    exchange_ok = panel.meta["exchange"].isin(allowed_exchanges)

    def _broadcast(row: pd.Series) -> pd.DataFrame:
        return pd.DataFrame(
            np.repeat(row.to_numpy()[None, :], len(panel.dates), axis=0),
            index=panel.dates,
            columns=panel.securities,
        )

    pass_flags: dict[str, pd.DataFrame] = {
        "security_type": _broadcast(type_ok),
        "exchange": _broadcast(exchange_ok),
    }

    # -- history filters -----------------------------------------------------
    # Counted in BARS ACTUALLY PRESENT, not calendar days since listing: a
    # security that listed 300 days ago but only traded 40 of them does not have
    # 300 days of trading history.
    bars_to_date = tradable.cumsum()
    pass_flags["history"] = bars_to_date >= int(settings["min_history_trading_days"])

    prior_window = int(settings["prior_bars_window"])
    bars_in_window = tradable.rolling(prior_window, min_periods=1).sum()
    pass_flags["bars_in_prior_252"] = bars_in_window >= int(settings["min_bars_in_prior_252"])

    # -- level filters (unadjusted, as-of-date) ------------------------------
    pass_flags["close"] = panel.close_unadj >= float(settings["min_close_usd"])

    # PIT establishment, then the size test -- deliberately two filters.
    # User ruling 2026-08-09: "If a security-date cannot be established PIT from
    # the required source data, it is excluded and the exclusion is reported. Do
    # not fill missing PIT information with today's shares, today's market cap,
    # current ticker mappings, or later-revised fundamentals."
    #
    # Shares outstanding come from the PIT vendor; where they are absent, market
    # cap is UNKNOWABLE at T, which is a different exclusion from being small.
    market_cap = panel.market_cap
    pass_flags["pit_market_cap"] = market_cap.notna()
    # Where market cap is UNKNOWN the size test passes vacuously, so the
    # security-date fails exactly one filter (pit_market_cap) instead of two.
    # Eligibility is unaffected -- it is the AND of every flag -- but the
    # section 9 counts stay non-overlapping and mean what they say.
    # An OPTIONAL ceiling (APEX-004 small-cap universe). Absent key = no
    # ceiling, bit-for-bit the historical behavior -- the closed experiments'
    # configs carry no ceiling and must keep reproducing. The ceiling folds
    # into the SAME size flag rather than adding a filter name, so the
    # section 9 reason taxonomy and reason_priority are untouched.
    ceiling = float(settings.get("max_market_cap_usd", float("inf")))
    pass_flags["market_cap"] = (
        (market_cap >= float(settings["min_market_cap_usd"]))
        & (market_cap < ceiling)
    ) | market_cap.isna()

    addv = panel.dollar_volume.rolling(
        int(settings["addv_window_days"]),
        min_periods=int(settings["addv_min_periods"]),
    ).mean()
    pass_flags["addv"] = addv >= float(settings["min_addv_usd"])

    for name in FILTER_NAMES:
        pass_flags[name] = pass_flags[name].fillna(False).astype(bool) & tradable

    eligible = tradable.copy()
    for name in FILTER_NAMES:
        eligible &= pass_flags[name]

    exclusion_reason = _first_failure(pass_flags, tradable, panel, settings)

    return UniverseSnapshot(
        dates=panel.dates,
        securities=panel.securities,
        eligible=eligible,
        pass_flags=pass_flags,
        exclusion_reason=exclusion_reason,
        tradable=tradable,
    )


def _first_failure(
    pass_flags: dict[str, pd.DataFrame],
    tradable: pd.DataFrame,
    panel: Panel,
    settings: dict,
) -> pd.DataFrame:
    """Label each excluded security-date with its FIRST failing filter.

    Per-filter counts (`UniverseSnapshot.counts`) are independent and may
    overlap; this single label exists only so the section 9 log is deterministic.
    """
    reason = pd.DataFrame(None, index=panel.dates, columns=panel.securities, dtype=object)
    assigned = pd.DataFrame(False, index=panel.dates, columns=panel.securities)

    for name in settings["reason_priority"]:
        if name not in pass_flags:
            continue
        failing = tradable & ~pass_flags[name] & ~assigned
        reason = reason.mask(failing, name)
        assigned |= failing

    reason = reason.mask(~tradable, "not_trading")
    return reason


def apply_feature_completeness(
    universe: UniverseSnapshot, complete: pd.DataFrame
) -> UniverseSnapshot:
    """Fold section 9's missing-data rule into eligibility.

    "Any security missing a required input for any of the four features at a
    formation date is excluded from that formation date only, and remains
    eligible at subsequent dates." Excluding a date is therefore a mask, never a
    forward-fill and never a drop of the security.

    Note the ordering this creates, which is not optional but forced:
    F1's universe-mean benchmark and F4a's sector benchmark are computed against
    PRE-completeness eligibility. Computing them against post-completeness
    eligibility would be circular -- F1's benchmark cannot depend on whether F1
    is computable.
    """
    flags = dict(universe.pass_flags)
    flags["missing_feature"] = complete
    return UniverseSnapshot(
        dates=universe.dates,
        securities=universe.securities,
        eligible=universe.eligible & complete,
        pass_flags=flags,
        exclusion_reason=universe.exclusion_reason.mask(
            universe.eligible & ~complete, "missing_feature"
        ),
        tradable=universe.tradable,
    )
