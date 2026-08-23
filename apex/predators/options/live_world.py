"""LIVE WORLD — build the commissioned FrozenState from live feeds.

The whole Options stack (state, expression, geometry, assassin, paper
execution) was commissioned against `FrozenState`. Live trading must
therefore produce a FrozenState, not a parallel live-only object.
Anything else would mean the thing we validated is not the thing we
run.

WHY A FIREWALL STILL MATTERS LIVE. In replay the firewall stops us
reading the future. Live, the future does not exist yet -- but a
STALE quote is the same disease wearing different clothes: it makes
the Predator believe something the market has already stopped saying.
So every live quote carries its age, and the loop refuses to attack on
quotes it cannot vouch for.

FEEDS
    options   ThetaData v3 snapshot (options entitlement confirmed)
    underlying Alpaca SIP bars + NBBO (real equity quotes, so the
              stock comparator crosses a real spread)

decision_power: NONE -- a sensor adapter.
"""
from __future__ import annotations

import csv
import io
import json
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from apex.predators.options.replay import FrozenState

THETA = "http://127.0.0.1:25503/v3"
ALPACA = "https://data.alpaca.markets/v2"
SECRETS = Path.home() / ".apex-secrets"

MAX_QUOTE_AGE_S = 120.0        # pre-declared: older than this is stale
MAX_BAR_AGE_S = 300.0


class FeedUnavailable(RuntimeError):
    """A feed could not be read. The loop must skip, never guess."""


def _secret(name: str) -> str:
    p = SECRETS / name
    if not p.exists():
        raise FeedUnavailable(
            f"{name} not present -- the sensor refuses to start rather "
            f"than run on an unauthenticated feed")
    return p.read_text().strip()


def _get(url: str, headers: dict | None = None, timeout: int = 20) -> str:
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode()


# ------------------------------------------------------------ options

def option_expirations(symbol: str) -> list:
    txt = _get(f"{THETA}/option/list/expirations?symbol={symbol}")
    return [r["expiration"] for r in csv.DictReader(io.StringIO(txt))
            if r.get("expiration")]


def option_chain_snapshot(symbol: str, expiration: str) -> list:
    """Live quotes for one expiration. Rows shaped exactly like the
    historical corpus so downstream code cannot tell the difference."""
    txt = _get(f"{THETA}/option/snapshot/quote"
               f"?symbol={symbol}&expiration={expiration}")
    rows = []
    for r in csv.DictReader(io.StringIO(txt)):
        try:
            bid, ask = float(r["bid"]), float(r["ask"])
        except (TypeError, ValueError, KeyError):
            continue
        if bid <= 0 or ask <= 0 or ask < bid:
            continue
        rows.append({
            "symbol": symbol, "expiration": r["expiration"],
            "strike": r["strike"],
            "right": "CALL" if r["right"].upper().startswith("C")
            else "PUT",
            "timestamp": r["timestamp"],
            "bid": r["bid"], "ask": r["ask"],
            "bid_size": r.get("bid_size", "0"),
            "ask_size": r.get("ask_size", "0"),
            # live quotes are causal by construction -- they cannot
            # describe a future that has not happened
            "moneyness_status": "CAUSAL",
        })
    return rows


# ----------------------------------------------------------- equities

def _alpaca_headers() -> dict:
    return {"APCA-API-KEY-ID": _secret("ALPACA_API_KEY_ID"),
            "APCA-API-SECRET-KEY": _secret("ALPACA_API_SECRET_KEY")}


def underlying_bars(symbol: str, start: datetime, end: datetime) -> list:
    url = (f"{ALPACA}/stocks/{symbol}/bars?timeframe=1Min"
           f"&start={start.strftime('%Y-%m-%dT%H:%M:%SZ')}"
           f"&end={end.strftime('%Y-%m-%dT%H:%M:%SZ')}"
           f"&limit=10000&feed=sip&adjustment=raw")
    data = json.loads(_get(url, _alpaca_headers()))
    return [{"t": b["t"], "o": b["o"], "h": b["h"], "l": b["l"],
             "c": b["c"], "v": b["v"], "session": "REGULAR"}
            for b in (data.get("bars") or [])]


def underlying_nbbo(symbol: str) -> dict:
    """Real equity NBBO -- what makes the stock comparator legitimate."""
    url = f"{ALPACA}/stocks/{symbol}/quotes/latest?feed=sip"
    q = json.loads(_get(url, _alpaca_headers())).get("quote") or {}
    if not q:
        raise FeedUnavailable(f"no NBBO for {symbol}")
    return {"bid": q.get("bp"), "ask": q.get("ap"),
            "bid_size": q.get("bs"), "ask_size": q.get("as"),
            "t": q.get("t")}


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

    # TIMEZONE CONVENTION. ThetaData option timestamps are ET-NAIVE;
    # Alpaca bar timestamps are UTC-AWARE. Comparing an ET-naive quote
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
