"""LIVE WORLD -- build the commissioned FrozenState from live feeds.

The whole Options stack (state, expression, geometry, assassin, paper
execution) was commissioned against `FrozenState`. Live trading must
therefore produce a FrozenState, not a parallel live-only object.
Anything else would mean the thing we validated is not the thing we
run.

WHY A FIREWALL STILL MATTERS LIVE. In replay the firewall stops us
reading the future. Live, the future does not exist yet -- but a STALE
quote is the same disease wearing different clothes: it makes the
Predator believe something the market has already stopped saying. So
every live quote carries its age, and the loop refuses to attack on
quotes it cannot vouch for.

VENDOR IGNORANCE. Feed access lives in the sensor layer
(apex/intraday/options_feed.py). This module does not know, and must
not learn, which vendor answered -- research that names its broker has
stopped being research.

decision_power: NONE -- a sensor adapter.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from apex.intraday.options_feed import (
    FeedUnavailable, option_chain_snapshot, option_expirations,
    underlying_bars, underlying_nbbo)
from apex.predators.options.replay import FrozenState

__all__ = ["FeedUnavailable", "LiveObservation", "observe",
           "MAX_QUOTE_AGE_S", "MAX_BAR_AGE_S"]

MAX_QUOTE_AGE_S = 120.0        # pre-declared: older than this is stale
MAX_BAR_AGE_S = 300.0


# -------------------------------------------------------------- world

@dataclass(frozen=True)
class LiveObservation:
    frozen: FrozenState
    stock_bid: float | None
    stock_ask: float | None
    quote_age_s: float | str
    bar_age_s: float | str
    feed_quality: str
    reasons: tuple = ()

    def as_record(self) -> dict:
        return {"kind": "live_observation", "symbol": self.frozen.symbol,
                "T": self.frozen.T, "feed_quality": self.feed_quality,
                "quote_age_s": self.quote_age_s,
                "bar_age_s": self.bar_age_s,
                "option_quotes": len(self.frozen.option_quotes),
                "bars": len(self.frozen.underlying_bars),
                "reasons": list(self.reasons)}


def observe(symbol: str, *, now: datetime | None = None,
            expirations: int = 3, session_open_utc: datetime | None = None
            ) -> LiveObservation:
    """One live observation, shaped as the commissioned FrozenState.

    Feed quality is judged, never assumed: a stale chain or a gap in
    bars downgrades the observation so the funnel can refuse it."""
    import pandas as pd

    now = now or datetime.now(timezone.utc)
    start = session_open_utc or (now - timedelta(hours=8))
    reasons = []

    # TIMEZONE CONVENTION. Option quote timestamps arrive ET-NAIVE;
    # bar timestamps arrive UTC-AWARE. Comparing an ET-naive quote
    # against a UTC clock makes every live quote look ~4 hours stale,
    # which would have refused every scan of a live session while
    # looking like a working staleness guard. The historical corpus is
    # ET-naive, so live adopts ET-naive too -- the convention the whole
    # stack was commissioned against.
    now_et = pd.Timestamp(now).tz_convert("America/New_York") \
        .tz_localize(None)

    bars = underlying_bars(symbol, start, now)
    if len(bars) < 30:
        raise FeedUnavailable(
            f"{symbol}: only {len(bars)} bars -- the commissioned "
            f"equity geometry needs history it does not have")
    last_bar_t = pd.Timestamp(bars[-1]["t"])
    bar_age = (pd.Timestamp(now) - last_bar_t).total_seconds()

    exps = [e for e in option_expirations(symbol)
            if e >= now.strftime("%Y-%m-%d")][:expirations]
    quotes = []
    for e in exps:
        try:
            quotes.extend(option_chain_snapshot(symbol, e))
        except Exception as exc:                          # noqa: BLE001
            reasons.append(f"expiry {e} unavailable: {type(exc).__name__}")
    if not quotes:
        raise FeedUnavailable(f"{symbol}: no usable option quotes")

    newest = max(q["timestamp"] for q in quotes)
    q_age = (now_et - pd.Timestamp(newest)).total_seconds()

    try:
        nbbo = underlying_nbbo(symbol)
        s_bid, s_ask = nbbo["bid"], nbbo["ask"]
    except Exception as exc:                              # noqa: BLE001
        s_bid = s_ask = None
        reasons.append(f"no equity NBBO ({type(exc).__name__}) -- stock "
                       f"comparator falls back to LIMITED")

    quality = "GOOD"
    if q_age > MAX_QUOTE_AGE_S:
        quality = "STALE_QUOTES"
        reasons.append(f"newest option quote is {q_age:.0f}s old "
                       f"(limit {MAX_QUOTE_AGE_S:.0f}s)")
    if bar_age > MAX_BAR_AGE_S:
        quality = "STALE_BARS"
        reasons.append(f"newest bar is {bar_age:.0f}s old")

    frozen = FrozenState(
        symbol=symbol, session=now_et.strftime("%Y-%m-%d"),
        T=str(now_et),
        underlying_bars=tuple(bars), option_quotes=tuple(quotes),
        oi_rows=(), spot_ref=bars[-1]["c"],
        spot_ref_source_label=str(last_bar_t),
        spot_ref_age_s=bar_age)
    return LiveObservation(
        frozen=frozen, stock_bid=s_bid, stock_ask=s_ask,
        quote_age_s=round(q_age, 1), bar_age_s=round(bar_age, 1),
        feed_quality=quality, reasons=tuple(reasons))
