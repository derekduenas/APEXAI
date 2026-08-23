"""OPTIONS + UNDERLYING MARKET-DATA FEED (sensor layer).

This module names its market-DATA vendors, which is why it lives in the
sensor layer rather than in research. Same reasoning as
alpaca_fabric.py: naming a data provider is not a broker relationship.
It defines no order, no placement function, and imports no broker SDK.

The research package consumes it through neutral function names and
never learns which vendor answered.

decision_power: NONE -- a market-data sensor.
"""
from __future__ import annotations

import csv
import io
import json
import urllib.request
from datetime import datetime
from pathlib import Path

THETA = "http://127.0.0.1:25503/v3"
ALPACA = "https://data.alpaca.markets/v2"
SECRETS = Path.home() / ".apex-secrets"


class FeedUnavailable(RuntimeError):
    """A feed could not be read. Callers must skip, never guess."""


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


