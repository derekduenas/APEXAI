"""APEX MARKET FABRIC — continuous WebSocket senses for the crypto arena.

Transport and execution-fidelity infrastructure ONLY. CRYPTO-001/002
predicates, thresholds, Assassin semantics, and Capital logic are frozen
and untouched by this module.

  Coinbase public WS (no auth) -> raw immutable event archive
    -> canonical live state (own bars, live book, health)

WHY OUR OWN BAR BUILDER: the exchange's candle channel buckets at five
minutes; the arena's battlefield is 15-90 minutes with sub-minute
perception, so bars are built from the TRADE stream (1s/1m aggregation)
and the ticker/book streams feed liquidity state directly.

BOOK HEALTH IS AN AUTHORITY, NOT A COMMENT: sequence gaps, stale
messages, or a missed heartbeat set BOOK_HEALTH=DEGRADED, and degraded
microstructure state is REFUSED downstream rather than assumed
unchanged. Missing updates never mean "nothing changed" — the weekend's
five LAB lessons applied to a live socket.

REST's job is memory (bootstrap history, resync after a gap); the socket
is the present. Reconnect/resubscribe is first-class, with heartbeats
subscribed to keep quiet-period subscriptions alive.
"""

from __future__ import annotations

import json
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

WS_URL = "wss://advanced-trade-ws.coinbase.com"
CHANNELS = ("heartbeats", "ticker", "market_trades", "level2")
STALE_AFTER_S = 20.0
RAW_ARCHIVE = Path("results/crypto/raw_events")
FABRIC_VERSION = "crypto_market_fabric_v1.1"
# LAB-06: the L2 firehose writes ~2.9GB/day — enough to fill the disk and
# take DOWN MONDAY'S CLOCK. Archive the semantically valuable, bounded
# streams (trades + ticker, ~50MB/day); L2 lives as LIVE STATE only, with
# periodic book SNAPSHOTS preserving what matters for later study.
ARCHIVE_CHANNELS = ("market_trades", "ticker")
BOOK_SNAPSHOT_EVERY_S = 60
ARCHIVE_MAX_MB = 400
ARCHIVE_RETAIN_HOURS = 72


@dataclass
class BookState:
    bids: dict = field(default_factory=dict)      # price -> size
    asks: dict = field(default_factory=dict)
    last_update: float = 0.0
    synced: bool = False

    def apply(self, side: str, price: float, qty: float) -> None:
        book = self.bids if side == "bid" else self.asks
        if qty == 0:
            book.pop(price, None)
        else:
            book[price] = qty
        self.last_update = time.time()

    def snapshot(self, depth: int = 10) -> dict:
        if not self.bids or not self.asks:
            return {"status": "EMPTY"}
        bb = sorted(self.bids.items(), reverse=True)[:depth]
        ba = sorted(self.asks.items())[:depth]
        best_bid, best_ask = bb[0][0], ba[0][0]
        mid = (best_bid + best_ask) / 2
        bid_sz = sum(q for _, q in bb)
        ask_sz = sum(q for _, q in ba)
        return {"status": "OK", "best_bid": best_bid, "best_ask": best_ask,
                "mid": mid,
                "spread_bps": round((best_ask - best_bid) / mid * 1e4, 3),
                "depth1_bid": bb[0][1], "depth1_ask": ba[0][1],
                "depth10_bid": round(bid_sz, 6),
                "depth10_ask": round(ask_sz, 6),
                "imbalance_top10": round(bid_sz / (bid_sz + ask_sz), 3)
                if bid_sz + ask_sz else None,
                "levels_bid": len(self.bids), "levels_ask": len(self.asks)}

    def walk(self, side: str, notional_usd: float) -> dict:
        """Book-walk a hypothetical order: VWAP fill, slippage vs top of
        book, and whether displayed depth can even absorb it."""
        levels = (sorted(self.asks.items()) if side == "BUY"
                  else sorted(self.bids.items(), reverse=True))
        if not levels:
            return {"status": "NO_BOOK"}
        top = levels[0][0]
        filled_usd = filled_qty = 0.0
        for price, qty in levels:
            take_usd = min(notional_usd - filled_usd, price * qty)
            if take_usd <= 0:
                break
            filled_qty += take_usd / price
            filled_usd += take_usd
        if filled_usd < notional_usd * 0.999:
            return {"status": "INSUFFICIENT_DISPLAYED_DEPTH",
                    "absorbed_usd": round(filled_usd, 2), "top": top}
        vwap = filled_usd / filled_qty
        slip = ((vwap - top) / top if side == "BUY" else (top - vwap) / top)
        return {"status": "OK", "fill_vwap": round(vwap, 2),
                "top_of_book": top,
                "slippage_bps": round(slip * 1e4, 3),
                "levels_consumed": sum(
                    1 for p, q in levels
                    if (p <= vwap if side == "BUY" else p >= vwap))}


class MarketFabric:
    """Continuous senses. Thread-safe reads via snapshot()."""

    def __init__(self, products=("BTC-USD", "ETH-USD", "SOL-USD"),
                 archive: bool = True):
        self.products = list(products)
        self.books = {p: BookState() for p in products}
        self.trades = {p: deque(maxlen=20000) for p in products}
        self.ticker = {p: {} for p in products}
        self.health = {"connected": False, "last_msg": 0.0,
                       "heartbeats": 0, "reconnects": 0,
                       "gaps_detected": 0, "gap_unresolved": False,
                       "last_sequence": None,
                       "book_health": "NO_DATA", "connection_age_s": 0.0}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._archive = archive
        self._ws = None
        self._t0 = 0.0
        self._archive_writes = 0
        self._last_book_snap = 0.0

    # ---------------------------------------------------------- transport
    def _archive_event(self, msg: dict) -> None:
        """Bounded archive (LAB-06): value-dense channels only, with
        rotation, retention, and a hard size cap. A research archive must
        never be able to starve the production clock of disk."""
        if not self._archive or msg.get("channel") not in ARCHIVE_CHANNELS:
            return
        hour = pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%d-%H")
        RAW_ARCHIVE.mkdir(parents=True, exist_ok=True)
        with (RAW_ARCHIVE / f"events_{hour}.jsonl").open("a") as fh:
            fh.write(json.dumps(msg, separators=(",", ":")) + "\n")
        self._archive_writes += 1
        if self._archive_writes % 2000 == 0:
            self._prune_archive()

    def _prune_archive(self) -> None:
        files = sorted(RAW_ARCHIVE.glob("events_*.jsonl"))
        cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(
            hours=ARCHIVE_RETAIN_HOURS)
        for f in files:
            try:
                stamp_h = pd.Timestamp(f.stem.replace("events_", "")
                                       .rsplit("-", 1)[0] + " "
                                       + f.stem.rsplit("-", 1)[1] + ":00",
                                       tz="UTC")
                if stamp_h < cutoff:
                    f.unlink()
            except Exception:                               # noqa: BLE001
                continue
        files = sorted(RAW_ARCHIVE.glob("events_*.jsonl"))
        total = sum(f.stat().st_size for f in files)
        while total > ARCHIVE_MAX_MB * 1e6 and len(files) > 1:
            oldest = files.pop(0)
            total -= oldest.stat().st_size
            oldest.unlink()
            self.health["archive_pruned"] = \
                self.health.get("archive_pruned", 0) + 1

    def _maybe_snapshot_book(self, now: float) -> None:
        """Periodic bounded book snapshots: the microstructure record we
        actually study, ~1.4MB/day instead of 2.9GB."""
        if now - self._last_book_snap < BOOK_SNAPSHOT_EVERY_S:
            return
        self._last_book_snap = now
        if not self._archive:
            return
        hour = pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%d")
        RAW_ARCHIVE.mkdir(parents=True, exist_ok=True)
        rec = {"channel": "book_snapshot",
               "t": str(pd.Timestamp.now(tz="UTC")),
               "books": {p: b.snapshot() for p, b in self.books.items()},
               "health": {k: v for k, v in self.health.items()
                          if k != "last_msg"}}
        with (RAW_ARCHIVE / f"book_{hour}.jsonl").open("a") as fh:
            fh.write(json.dumps(rec, separators=(",", ":")) + "\n")

    def _on_message(self, _ws, raw) -> None:
        now = time.time()
        try:
            msg = json.loads(raw)
        except Exception:                                   # noqa: BLE001
            return
        with self._lock:
            self.health["last_msg"] = now
            seq = msg.get("sequence_num")
            if seq is not None:
                last = self.health["last_sequence"]
                if last is not None and seq != last + 1:
                    self.health["gaps_detected"] += 1
                    self.health["gap_unresolved"] = True
                    for b in self.books.values():
                        b.synced = False        # authority revoked on gap
                self.health["last_sequence"] = seq
            ch = msg.get("channel")
            if ch == "heartbeats":
                self.health["heartbeats"] += 1
                return
            self._archive_event(msg)
            for ev in msg.get("events", []):
                self._apply_event(ch, ev, now)
            self._refresh_book_health(now)
            self._maybe_snapshot_book(now)

    def _apply_event(self, channel: str, ev: dict, now: float) -> None:
        if channel == "l2_data":
            p = ev.get("product_id")
            book = self.books.get(p)
            if book is None:
                return
            if ev.get("type") == "snapshot":
                book.bids.clear(); book.asks.clear()
                self.health["gap_unresolved"] = False   # true resync
            for u in ev.get("updates", []):
                try:
                    book.apply(u["side"], float(u["price_level"]),
                               float(u["new_quantity"]))
                except Exception:                           # noqa: BLE001
                    continue
            book.synced = True
        elif channel == "market_trades":
            for t in ev.get("trades", []):
                p = t.get("product_id")
                if p in self.trades:
                    self.trades[p].append({
                        "t": t.get("time"), "price": float(t["price"]),
                        "size": float(t["size"]), "side": t.get("side")})
        elif channel == "ticker":
            for t in ev.get("tickers", []):
                p = t.get("product_id")
                if p in self.ticker:
                    self.ticker[p] = {
                        "price": float(t["price"]),
                        "best_bid": float(t.get("best_bid") or 0) or None,
                        "best_ask": float(t.get("best_ask") or 0) or None,
                        "ts": now}

    def _refresh_book_health(self, now: float) -> None:
        age = now - self.health["last_msg"]
        btc = self.books.get("BTC-USD")
        # a gap revokes authority until an explicit SNAPSHOT re-syncs the
        # book (an incremental update after a gap is applied to a book we
        # know is wrong — resync means snapshot, not "next message")
        if self.health.get("gap_unresolved"):
            self.health["book_health"] = "DEGRADED_SEQUENCE_GAP"
        elif age > STALE_AFTER_S:
            self.health["book_health"] = "DEGRADED_STALE"
        elif btc and btc.bids and btc.asks:
            self.health["book_health"] = "OK"
        else:
            self.health["book_health"] = "NO_DATA"

    def _run(self) -> None:
        import websocket
        while not self._stop.is_set():
            try:
                self._t0 = time.time()
                ws = websocket.WebSocketApp(
                    WS_URL, on_message=self._on_message,
                    on_open=self._on_open,
                    on_error=lambda *_: None,
                    on_close=lambda *_: None)
                self._ws = ws
                with self._lock:
                    self.health["connected"] = True
                ws.run_forever(sslopt={"ca_certs": "/etc/ssl/cert.pem"},
                               ping_interval=20, ping_timeout=10)
            except Exception:                               # noqa: BLE001
                pass
            with self._lock:
                self.health["connected"] = False
                self.health["reconnects"] += 1
                for b in self.books.values():
                    b.synced = False            # resubscribe -> resync
            if not self._stop.is_set():
                time.sleep(2)

    def _on_open(self, ws) -> None:
        for ch in CHANNELS:
            ws.send(json.dumps({"type": "subscribe", "channel": ch,
                                "product_ids": self.products}))
            time.sleep(0.1)

    def start(self) -> None:
        threading.Thread(target=self._run, daemon=True).start()

    def stop(self) -> None:
        self._stop.set()
        if self._ws:
            try:
                self._ws.close()
            except Exception:                               # noqa: BLE001
                pass

    # ------------------------------------------------------------- state
    def bars_1m(self, product: str, minutes: int = 90) -> pd.DataFrame:
        """OUR bars, built from the trade stream (not the 5m candle
        channel). Only COMPLETED minutes are returned."""
        with self._lock:
            tr = list(self.trades.get(product, ()))
        if not tr:
            return pd.DataFrame()
        f = pd.DataFrame(tr)
        f["ts"] = pd.to_datetime(f["t"], utc=True, format="ISO8601")
        f = f.set_index("ts").sort_index()
        now_min = pd.Timestamp.now(tz="UTC").floor("1min")
        g = f.resample("1min")
        bars = pd.DataFrame({
            "open": g["price"].first(), "high": g["price"].max(),
            "low": g["price"].min(), "close": g["price"].last(),
            "volume": g["size"].sum(),
            "trades": g["price"].count(),
            "buy_volume": g.apply(
                lambda x: x.loc[x["side"] == "BUY", "size"].sum()
                if len(x) else 0.0)}).dropna(subset=["close"])
        bars = bars[bars.index < now_min]         # completed only
        bars = bars.reset_index().rename(columns={"ts": "event_time_utc"})
        return bars.tail(minutes)

    def snapshot(self) -> dict:
        with self._lock:
            now = time.time()
            self.health["connection_age_s"] = round(now - self._t0, 1) \
                if self._t0 else 0.0
            self._refresh_book_health(now)
            return {
                "fabric_version": FABRIC_VERSION,
                "health": dict(self.health),
                "last_message_age_s": round(now - self.health["last_msg"], 2)
                if self.health["last_msg"] else None,
                "books": {p: b.snapshot() for p, b in self.books.items()},
                "ticker": {p: dict(t) for p, t in self.ticker.items()},
                "trade_counts": {p: len(t) for p, t in self.trades.items()},
            }

    def microstructure_authorized(self) -> bool:
        """Degraded book state REFUSES microstructure authority — never
        'assume nothing changed'."""
        with self._lock:
            return self.health["book_health"] == "OK"
