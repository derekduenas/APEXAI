"""IV_BID / IV_MID / IV_ASK — F "preserve IV_BID/IV_MID/IV_ASK, not one
fake precise IV". A single "the IV" number hides how well-identified it
actually is; a wide bid/ask spread means IV_BID and IV_ASK diverge a
lot, and that divergence IS the information. This module also enforces:
never solve IV from a stale last trade when a current NBBO exists, and
flag (never silently accept) a wide-spread contract where IV is poorly
identified.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

from apex.option_analytics import OPTION_ANALYTICS_POWER
from apex.option_analytics.bsm import implied_volatility

IV_QUALITY_LEVELS = ("HIGH", "MODERATE", "LOW", "UNKNOWN")

# named thresholds for spread-based IV quality -- a spread wider than
# this fraction of the midpoint means IV_BID..IV_ASK is wide enough
# that "the IV" is poorly identified, not a precise number.
WIDE_SPREAD_PCT_MODERATE = 0.10
WIDE_SPREAD_PCT_LOW = 0.30


class IVTripleError(RuntimeError):
    pass


@dataclass(frozen=True)
class IVTriple:
    option_type: str
    iv_bid: float | None
    iv_mid: float | None
    iv_ask: float | None
    spread_pct_of_mid: float | None
    quality: str
    used_stale_trade: bool
    decision_power: str = OPTION_ANALYTICS_POWER

    def __post_init__(self):
        if self.quality not in IV_QUALITY_LEVELS:
            raise IVTripleError(f"unknown quality {self.quality!r}")
        if self.used_stale_trade:
            raise IVTripleError(
                "an IVTriple may never be built from a stale last-trade "
                "price when a current NBBO exists -- this is enforced at "
                "construction, not left to caller discipline")

    def as_record(self) -> dict:
        return asdict(self)


def _quality_from_spread(spread_pct: float | None) -> str:
    if spread_pct is None:
        return "UNKNOWN"
    if spread_pct <= WIDE_SPREAD_PCT_MODERATE:
        return "HIGH"
    if spread_pct <= WIDE_SPREAD_PCT_LOW:
        return "MODERATE"
    return "LOW"


def solve_iv_triple(*, option_type: str, bid: float | None, ask: float | None,
                    last_trade: float | None, quote_is_current: bool,
                    spot: float, strike: float, time_to_expiry_years: float,
                    rate: float) -> IVTriple:
    """Solves IV from the NBBO (bid/ask), never from `last_trade` when
    `quote_is_current` is True -- `last_trade` is accepted as a
    parameter only so callers can be explicit that it exists and was
    deliberately NOT used, not so this function can fall back to it."""
    if bid is None or ask is None:
        if not quote_is_current and last_trade is not None:
            raise IVTripleError(
                "no current NBBO and only a stale last trade is available -- "
                "refuse rather than solve IV from a stale price")
        return IVTriple(option_type=option_type, iv_bid=None, iv_mid=None, iv_ask=None,
                        spread_pct_of_mid=None, quality="UNKNOWN",
                        used_stale_trade=False)

    mid = (bid + ask) / 2.0
    spread_pct = ((ask - bid) / mid) if mid > 0 else None

    def solve(price):
        if price is None or price <= 0:
            return None
        return implied_volatility(option_type=option_type, market_price=price, spot=spot,
                                  strike=strike, time_to_expiry_years=time_to_expiry_years,
                                  rate=rate)

    return IVTriple(option_type=option_type, iv_bid=solve(bid), iv_mid=solve(mid),
                    iv_ask=solve(ask), spread_pct_of_mid=spread_pct,
                    quality=_quality_from_spread(spread_pct), used_stale_trade=False)
