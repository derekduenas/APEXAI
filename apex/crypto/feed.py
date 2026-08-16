"""Coinbase Exchange PUBLIC market data — the crypto arena's feed.

No authentication, no capital pathway, no order endpoints imported. The
arena is shadow-only by construction: this module can READ candles,
tickers, and the L2 book, and can do nothing else. Zero interaction with
the EODHD quota (separate provider, free public data).
"""

from __future__ import annotations

import json
import ssl
import time
import urllib.request

import pandas as pd

BASE = "https://api.exchange.coinbase.com"
UA = "apex-research/1.0 (jrzcxph2dt@privaterelay.appleid.com)"
_CTX = ssl.create_default_context(cafile="/etc/ssl/cert.pem")


def _get(path: str, retries: int = 3) -> object:
    url = f"{BASE}{path}"
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            return json.loads(urllib.request.urlopen(
                req, timeout=30, context=_CTX).read())
        except Exception as e:                              # noqa: BLE001
            last = e
            time.sleep(1 + attempt)
    raise RuntimeError(f"coinbase fetch failed {path}: {type(last).__name__}")


def candles_1m(product: str, hours: float) -> pd.DataFrame:
    """Trailing 1m candles, oldest->newest, COMPLETED candles only (the
    current in-progress minute is dropped: as-of law). Coinbase returns
    [time, low, high, open, close, volume], max 300/request."""
    end = pd.Timestamp.now(tz="UTC").floor("1min")
    frames = []
    cursor = end
    remaining = int(hours * 60)
    while remaining > 0:
        chunk = min(remaining, 300)
        start = cursor - pd.Timedelta(minutes=chunk)
        raw = _get(f"/products/{product}/candles?granularity=60"
                   f"&start={start.isoformat()}&end={cursor.isoformat()}")
        if raw:
            frames.append(pd.DataFrame(
                raw, columns=["ts", "low", "high", "open", "close",
                              "volume"]))
        cursor = start
        remaining -= chunk
    if not frames:
        return pd.DataFrame(columns=["event_time_utc", "open", "high",
                                     "low", "close", "volume"])
    f = pd.concat(frames, ignore_index=True).drop_duplicates("ts")
    f["event_time_utc"] = pd.to_datetime(f["ts"], unit="s", utc=True)
    f = f.sort_values("event_time_utc").reset_index(drop=True)
    f = f[f["event_time_utc"] + pd.Timedelta(minutes=1) <= end]  # completed
    return f[["event_time_utc", "open", "high", "low", "close", "volume"]]


def ticker(product: str) -> dict:
    t = _get(f"/products/{product}/ticker")
    return {"bid": float(t["bid"]), "ask": float(t["ask"]),
            "last": float(t["price"]), "time": t["time"]}


def book_top(product: str, depth: int = 10) -> dict:
    b = _get(f"/products/{product}/book?level=2")
    bids = [(float(p), float(q)) for p, q, _ in b["bids"][:depth]]
    asks = [(float(p), float(q)) for p, q, _ in b["asks"][:depth]]
    bid_sz = sum(q for _, q in bids)
    ask_sz = sum(q for _, q in asks)
    mid = (bids[0][0] + asks[0][0]) / 2 if bids and asks else None
    return {"spread_bps": round((asks[0][0] - bids[0][0]) / mid * 1e4, 3)
            if mid else None,
            "imbalance_top10": round(bid_sz / (bid_sz + ask_sz), 3)
            if bid_sz + ask_sz else None,
            "mid": mid}
