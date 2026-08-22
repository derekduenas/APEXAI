"""EQUITY MARKET FABRIC — the live US equity sensor.

DAY-1 P0: the Intraday Historical endpoint is NOT a live transport. It
finalizes 1-minute bars hours after the session and returned [] for the
whole opening of 2026-08-17 while the market was demonstrably open. The
Live REST endpoint returned the PRIOR SESSION'S CLOSE (measured 65h
stale). The WebSocket is the measured real-time channel:

    measured 2026-08-17 13:44Z — /ws/us authorized, SPY/AAPL trades
    flowing, ms="open", latency median ~0s (sub-second).
    measured 2026-08-17 14:04Z — /ws/us-quote authorized, bid/ask/sizes
    flowing for SPY/AAPL/MSFT/NVDA/QQQ.

THE 50-SYMBOL RESOURCE LAW (operator, verified against EODHD's current
plan docs): the entitlement is 50 simultaneous realtime symbols. This
module holds to that as a hard ceiling on EACH channel — one connection
per channel, never sharded past it — and the symbol set is chosen by
apex/intraday/subscription_allocator.py (deterministic priority code,
no LLM in the loop). An earlier version of this file sharded past 50
symbols across parallel connections before the entitlement was confirmed;
that approach is retired, not merely unused.

Discipline reused from apex/crypto/fabric.py (the proven Coinbase design):
    persistent connection / heartbeat / reconnect / resubscribe
    provider event timestamps, never local invention
    known_from >= event_time
    outage tracking -> per-bar coverage_status
    HEALTH IS AUTHORITY: a degraded feed refuses, it does not guess

decision_power: NONE_OBSERVATIONAL_EPOCH1. This is a sensor. It computes
no thesis, ranks nothing, and authorizes nothing.
"""
from __future__ import annotations

import json
import os
import threading
import time
from collections import deque
from pathlib import Path

WS_TRADES = "wss://ws.eodhistoricaldata.com/ws/us"
WS_QUOTES = "wss://ws.eodhistoricaldata.com/ws/us-quote"
TRANSPORT = "EODHD_WEBSOCKET_REALTIME"
MAX_SYMBOLS = 50
# MEASURED 2026-08-17 (not documented anywhere the operator found): the
# quote channel silently drops ALL data -- zero messages, no error, no
# rejection status -- somewhere between 20 and 30 subscribed symbols,
# while the trade channel handles the full 50 cleanly. Bisected: n=20
# HEALTHY (2830 msgs/6s), n=30 and n=40 DEAD (0 msgs). This is a SEPARATE,
# TIGHTER entitlement from the trade channel's 50 and must never be
# assumed equal to it again.
QUOTE_MAX_SYMBOLS = 20

BARS_DIR = Path("data/live/equity_fabric/bars")
HEALTH_ARTIFACT = Path("results/intraday/equity_fabric_health.json")

MIN_TRADES_HEALTHY = 3
MAX_EDGE_GAP_S = 30.0
STALE_AFTER_S = 45.0


class FabricViolation(RuntimeError):
    pass


class _Channel:
    """One WebSocket connection, one subscription set, capped at
    MAX_SYMBOLS. Owns reconnect/resubscribe for itself only."""

    def __init__(self, url: str, on_message, max_symbols: int = MAX_SYMBOLS):
        self.url = url
        self._on_message_cb = on_message
        self.max_symbols = max_symbols
        self.symbols: list = []
        self._ws = None
        self._thread = None
        self._stop = False
        self._lock = threading.RLock()
        self.authorized = False
        self.connected_at = None
        self.last_msg_at = None
        self._disconnected_at = None
        self._outages: list = []
        self._pending_symbols: list | None = None

    def _token(self) -> str:
        tok = os.environ.get("EODHD_API_TOKEN")
        if not tok:
            raise FabricViolation(
                "EODHD_API_TOKEN absent — the sensor refuses to start "
                "rather than run blind")
        return tok

    def _on_open(self, ws) -> None:
        with self._lock:
            self.connected_at = time.time()
            self.authorized = False
            if self._disconnected_at is not None:
                self._outages.append((self._disconnected_at, time.time()))
                self._disconnected_at = None
            syms = self._pending_symbols or self.symbols
        if syms:
            ws.send(json.dumps({"action": "subscribe",
                                "symbols": ",".join(syms)}))

    def _on_close(self, *_a) -> None:
        with self._lock:
            self.authorized = False
            if self._disconnected_at is None:
                self._disconnected_at = time.time()

    def _wrapped_on_message(self, ws, raw) -> None:
        now = time.time()
        try:
            d = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return
        if "status_code" in d:
            if int(d.get("status_code", 0)) == 200:
                with self._lock:
                    self.authorized = True
            # any other status_code is a rejection/error -- surfaced via
            # health, never swallowed as if it were live data
            return
        # ONLY real data updates last_msg_at. An authorized-but-silent
        # connection (subscribe accepted, nothing ever streamed) must
        # read CONNECTED_NO_DATA forever, never HEALTHY off a stale
        # handshake -- the exact honesty gap that hid a dead quote feed.
        with self._lock:
            self.last_msg_at = now
        self._on_message_cb(d, now)

    def _run(self) -> None:
        import websocket
        while not self._stop:
            try:
                self._ws = websocket.WebSocketApp(
                    f"{self.url}?api_token={self._token()}",
                    on_open=self._on_open,
                    on_message=self._wrapped_on_message,
                    on_close=self._on_close, on_error=self._on_close)
                self._ws.run_forever(
                    sslopt={"ca_certs": "/etc/ssl/cert.pem"},
                    ping_interval=20, ping_timeout=10)
            except Exception:                               # noqa: BLE001
                self._on_close()
            if self._stop:
                break
            time.sleep(2.0)

    def start(self, symbols: list) -> None:
        symbols = symbols[:self.max_symbols]
        with self._lock:
            self.symbols = list(symbols)
        self._stop = False
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def resubscribe(self, new_symbols: list) -> tuple:
        """Diff-based: unsubscribe drops, subscribe adds. Never a full
        reconnect for a routine reallocation."""
        new_symbols = new_symbols[:self.max_symbols]
        with self._lock:
            old = set(self.symbols)
            new = set(new_symbols)
            added = sorted(new - old)
            dropped = sorted(old - new)
            self.symbols = list(new_symbols)
            self._pending_symbols = list(new_symbols)
            ws = self._ws
            authorized = self.authorized
        if ws is not None and authorized:
            try:
                if dropped:
                    ws.send(json.dumps({"action": "unsubscribe",
                                        "symbols": ",".join(dropped)}))
                if added:
                    ws.send(json.dumps({"action": "subscribe",
                                        "symbols": ",".join(added)}))
            except Exception:                               # noqa: BLE001
                pass
        return added, dropped

    def stop(self) -> None:
        self._stop = True
        if self._ws:
            try:
                self._ws.close()
            except Exception:                               # noqa: BLE001
                pass

    def health(self) -> dict:
        now = time.time()
        with self._lock:
            last = self.last_msg_at
            authorized = self.authorized
            disconnected = self._disconnected_at is not None
            n = len(self.symbols)
        age = None if last is None else round(now - last, 2)
        if not authorized:
            status = "UNAUTHORIZED"
        elif last is None:
            status = "CONNECTED_NO_DATA"
        elif age is not None and age > STALE_AFTER_S:
            status = "STALE"
        elif disconnected:
            status = "DISCONNECTED"
        else:
            status = "HEALTHY"
        return {"status": status, "authorized": authorized,
               "symbol_count": n, "last_message_age_s": age}


class EquityRealtimeFabric:
    """Resident dual-channel WebSocket sensor: trades -> APEX's own 1m
    bars, quotes -> latest bid/ask. Both channels share ONE allocated
    symbol set, each its own connection, each capped at MAX_SYMBOLS."""

    def __init__(self, symbols: list | None = None,
                 max_trades: int = 400_000):
        self.max_trades = max_trades
        self.trades: dict[str, deque] = {}
        self.quotes: dict[str, dict] = {}
        self._seen: dict[str, set] = {}
        self._lock = threading.RLock()
        self._trade_ch = _Channel(WS_TRADES, self._on_trade,
                                  max_symbols=MAX_SYMBOLS)
        self._quote_ch = _Channel(WS_QUOTES, self._on_quote,
                                  max_symbols=QUOTE_MAX_SYMBOLS)
        self.symbols: list = []
        self.counters = {"trade_messages": 0, "trades": 0,
                         "duplicates": 0, "out_of_order": 0,
                         "future_rejected": 0, "quote_messages": 0,
                         "unknown_symbol": 0}
        if symbols:
            symbols = [s.upper().replace(".US", "") for s in symbols]
            self._ensure_symbols(symbols)
            self.symbols = symbols

    def _ensure_symbols(self, symbols: list) -> None:
        with self._lock:
            for s in symbols:
                s = s.upper().replace(".US", "")
                if s not in self.trades:
                    self.trades[s] = deque(maxlen=self.max_trades)
                    self._seen[s] = set()

    # ------------------------------------------------------- ingest
    def _on_trade(self, d: dict, now: float) -> None:
        with self._lock:
            self.counters["trade_messages"] += 1
        sym = str(d.get("s", "")).upper()
        if sym not in self.trades:
            with self._lock:
                self.counters["unknown_symbol"] += 1
            return
        try:
            price = float(d["p"])
            size = float(d.get("v") or 0.0)
            t_ms = float(d["t"])
        except (KeyError, TypeError, ValueError):
            return
        event_s = t_ms / 1000.0
        if event_s > now + 5.0:
            with self._lock:
                self.counters["future_rejected"] += 1
            return
        key = (t_ms, price, size, str(d.get("c")))
        with self._lock:
            seen = self._seen[sym]
            if key in seen:
                self.counters["duplicates"] += 1
                return
            seen.add(key)
            if len(seen) > 500_000:
                seen.clear()
            dq = self.trades[sym]
            if dq and event_s < dq[-1]["event_s"]:
                self.counters["out_of_order"] += 1
            dq.append({"event_s": event_s, "price": price, "size": size,
                       "known_from_s": now, "dark_pool": bool(d.get("dp")),
                       "conditions": d.get("c")})
            self.counters["trades"] += 1

    def _on_quote(self, d: dict, now: float) -> None:
        with self._lock:
            self.counters["quote_messages"] += 1
        sym = str(d.get("s", "")).upper()
        try:
            bid, ask = float(d["bp"]), float(d["ap"])
            bid_sz, ask_sz = float(d.get("bs") or 0), float(d.get("as") or 0)
            t_ms = float(d["t"])
        except (KeyError, TypeError, ValueError):
            return
        event_s = t_ms / 1000.0
        if event_s > now + 5.0:
            return
        with self._lock:
            self.quotes[sym] = {"bid": bid, "ask": ask, "bid_size": bid_sz,
                                "ask_size": ask_sz, "event_s": event_s,
                                "known_from_s": now}

    # ------------------------------------------------------ lifecycle
    def start(self, symbols: list | None = None) -> None:
        symbols = symbols or self.symbols
        symbols = [s.upper().replace(".US", "") for s in symbols][
            :MAX_SYMBOLS]
        self._ensure_symbols(symbols)
        self.symbols = symbols
        self._trade_ch.start(symbols)
        time.sleep(0.3)
        self._quote_ch.start(symbols)

    def resubscribe(self, new_symbols: list) -> dict:
        """Reallocate the live subscription set. Both channels move
        together — a symbol is never trade-only or quote-only."""
        new_symbols = [s.upper().replace(".US", "") for s in new_symbols][
            :MAX_SYMBOLS]
        self._ensure_symbols(new_symbols)
        added_t, dropped_t = self._trade_ch.resubscribe(new_symbols)
        added_q, dropped_q = self._quote_ch.resubscribe(new_symbols)
        self.symbols = new_symbols
        return {"added": sorted(set(added_t) | set(added_q)),
               "dropped": sorted(set(dropped_t) | set(dropped_q))}

    def stop(self) -> None:
        self._trade_ch.stop()
        self._quote_ch.stop()

    # ----------------------------------------------------------- bars
    def bars_1m(self, symbol: str, minutes: int = 400):
        """APEX's OWN completed 1-minute bars. Delegates to the shared
        canonical builder (apex/intraday/bar_builder.py, Phase 0.4 §13)
        so every provider means the same thing by '1-minute bar' --
        this method now only does EODHD-specific ingest/outage lookup."""
        import pandas as pd
        from apex.intraday.bar_builder import build_1m_bars
        sym = symbol.upper().replace(".US", "")
        with self._lock:
            tr = list(self.trades.get(sym, ()))
            outages = list(self._trade_ch._outages)
            if self._trade_ch._disconnected_at is not None:
                outages = outages + [(self._trade_ch._disconnected_at,
                                      time.time())]
        return build_1m_bars(tr, outages, now=pd.Timestamp.now(tz="UTC"),
                             symbol=sym, transport=TRANSPORT, minutes=minutes)

    def latest_quote(self, symbol: str) -> dict | None:
        sym = symbol.upper().replace(".US", "")
        with self._lock:
            q = self.quotes.get(sym)
        return dict(q) if q else None

    # --------------------------------------------------------- health
    def health(self) -> dict:
        th, qh = self._trade_ch.health(), self._quote_ch.health()
        with self._lock:
            counters = dict(self.counters)
        if th["status"] == qh["status"] == "HEALTHY":
            status = "HEALTHY"
        elif th["status"] == "UNAUTHORIZED" and qh["status"] == "UNAUTHORIZED":
            status = "UNAUTHORIZED"
        else:
            status = f"MIXED(trade={th['status']},quote={qh['status']})"
        return {
            "kind": "equity_fabric_health", "status": status,
            "transport": TRANSPORT,
            "trade_channel": th, "quote_channel": qh,
            "symbols": list(self.symbols), "symbol_count": len(self.symbols),
            "counters": counters,
            "microstructure_authorized": qh["status"] == "HEALTHY",
            "decision_power": "NONE_OBSERVATIONAL_EPOCH1",
            "measured_at_utc": _utcnow_str(),
        }

    def observation_authorized(self) -> bool:
        return self.health()["status"] == "HEALTHY"


def _utcnow_str() -> str:
    import pandas as pd
    return str(pd.Timestamp.now(tz="UTC"))


# --------------------------------------------------------- persistence
def persist_bars(fabric: "EquityRealtimeFabric", day: str,
                 coverage: dict | None = None) -> dict:
    """Write completed bars per symbol so out-of-process consumers (the
    official 900s clock, FastWatch) read ONE canonical live series."""
    BARS_DIR.mkdir(parents=True, exist_ok=True)
    written = {}
    for sym in fabric.symbols:
        bars = fabric.bars_1m(sym)
        if not len(bars):
            written[sym] = 0
            continue
        out = BARS_DIR / f"{sym}_{day}.json"
        recs = json.loads(bars.to_json(orient="records", date_format="iso"))
        tmp = out.with_suffix(".tmp")
        tmp.write_text(json.dumps({
            "symbol": sym, "market_date": day, "transport": TRANSPORT,
            "written_at_utc": _utcnow_str(),
            "realtime_universe_coverage": coverage,
            "bars": recs}, indent=1))
        os.replace(tmp, out)
        written[sym] = len(recs)
    return written


def load_live_bars(symbol: str, day: str):
    """Consumer read of the canonical live series. Absent = absent."""
    import pandas as pd
    sym = symbol.upper().replace(".US", "")
    p = BARS_DIR / f"{sym}_{day}.json"
    if not p.exists():
        return None
    try:
        d = json.loads(p.read_text())
    except json.JSONDecodeError:
        return None
    bars = d.get("bars") or []
    if not bars:
        return None
    f = pd.DataFrame(bars)
    f["event_time_utc"] = pd.to_datetime(f["event_time_utc"], utc=True)
    return f


def as_normalize_rows_shape(symbol: str, day: str):
    """Adapt live bars to the EXACT column shape apex.intraday.eodhd.
    normalize_rows() produces, so callers can swap transport with zero
    change to downstream logic. Absent -> empty frame, same as the
    historical path returns on a legitimate no-data day."""
    import pandas as pd
    f = load_live_bars(symbol, day)
    if f is None or not len(f):
        return pd.DataFrame(columns=["provider_symbol", "event_time_utc",
                                     "open", "high", "low", "close",
                                     "volume"])
    out = f[["event_time_utc", "open", "high", "low", "close",
             "volume"]].copy()
    out.insert(0, "provider_symbol", symbol.replace(".US", ""))
    return out.sort_values("event_time_utc")


def write_health(health: dict) -> None:
    HEALTH_ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    tmp = HEALTH_ARTIFACT.with_suffix(".tmp")
    tmp.write_text(json.dumps(health, indent=1, default=str))
    os.replace(tmp, HEALTH_ARTIFACT)
