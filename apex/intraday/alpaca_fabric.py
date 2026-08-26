"""ALPACA REALTIME FABRIC — the PRIMARY_BROAD_SENSOR (Phase 0.4, operator
authorization: Algo Trader Plus, full SIP tape, unlimited symbols on a
SINGLE WebSocket connection — no sharding needed for 164 symbols).

Mirrors the proven design discipline of apex/intraday/equity_fabric.py
(the EODHD DEEP_REALTIME_SENSOR): persistent connection, heartbeat,
reconnect/resubscribe, provider event timestamps never local invention,
outage tracking -> per-bar coverage_status, HEALTH IS AUTHORITY. Bars
are built by the SAME canonical builder (apex/intraday/bar_builder.py)
EODHD uses -- one meaning of "1-minute bar" for every provider.

PROTOCOL (from Alpaca's own docs, quote/bar message shapes CONFIRMED
verbatim from what the operator pasted; trade message shape built to
Alpaca's documented, publicly-stable schema but NOT YET LIVE-VERIFIED --
this adapter has not made a real connection, see the missing-secret note
below):
    connect     wss://stream.data.alpaca.markets/v2/sip   (full SIP feed;
                requires Algo Trader Plus -- the plan just authorized)
    auth        {"action":"auth","key":KEY,"secret":SECRET}
                -> [{"T":"success","msg":"authenticated"}]
    subscribe   {"action":"subscribe","trades":[...],"quotes":[...]}
                (ONE message, all 164 symbols, ONE connection -- their
                docs: "Websocket subscriptions: Unlimited" on this plan)
    messages    a JSON ARRAY per frame; each element carries "T":
                "t"=trade (S,p,s,t ISO8601,x,c,i,z)
                "q"=quote (S,bp,bs,ap,as,c,z,t ISO8601) -- CONFIRMED shape
                "b"=minute bar (Alpaca's own aggregation; NOT used as
                    APEX's canonical bar -- built independently from
                    trades via bar_builder for one controlled semantics)
                "success"/"error"/"subscription" = control

CREDENTIAL STATE (2026-08-17): APCA-API-KEY-ID stored in Keychain
(operator pasted it in chat; treated exactly like the EODHD token --
never logged, never committed, never echoed). APCA-API-SECRET-KEY is
MISSING -- Alpaca requires both for any auth. This module is code-
complete and unit-tested against documented message shapes, but HAS NOT
authenticated, connected, or observed a single real message. No
DATA-2 LIVE CERTIFICATION claim may be made until the secret arrives and
a real connection is proven.

decision_power: NONE_OBSERVATIONAL_EPOCH1.
"""
from __future__ import annotations

import json
import os
import queue
import threading
import time
from collections import deque
from pathlib import Path

WS_URL = "wss://stream.data.alpaca.markets/v2/sip"
TRANSPORT = "ALPACA_WEBSOCKET_SIP_V1"

# THE HEALTH LAW (Phase 0.4 Tuesday arming, operator's explicit
# distinction): CONNECTED != HEALTHY, AUTHENTICATED != HEALTHY,
# SUBSCRIBED != HEALTHY. Only real market-data events establish live
# health -- control messages (open/auth/subscription-ack) advance the
# CONNECTION lifecycle, never the DATA-liveness timestamp.
CONNECTING = "CONNECTING"
AUTHENTICATED = "AUTHENTICATED"
SUBSCRIBED_NO_DATA = "SUBSCRIBED_NO_DATA"
HEALTHY = "HEALTHY"
PARTIAL = "PARTIAL"
DEGRADED = "DEGRADED"
STALE = "STALE"
FAILED = "FAILED"
STALE_AFTER_S = 45.0
# PHASE 12 (2026-08-20): the old FAILED_AFTER_RECONNECTS = 5 labeled the
# sensor FAILED all day while it preserved 97.5% of the tape with zero
# dropped frames -- reconnect COUNT is a transport-stability axis, not a
# verdict on the data. Health is now multi-axis: transport degradation
# with intact data preservation reads DEGRADED, never FAILED. FAILED is
# reserved for the sensor actually not doing its job (no data, dropped
# frames at scale, or dead transport).
RECONNECTS_PER_HOUR_DEGRADED = 6     # ~1 per 10 min: transport unstable
FAILED_AFTER_RECONNECTS_RETIRED = 5  # archaeology only; nothing reads it

# a symbol counts as "reachable" (the feed COULD observe it) once it has
# produced EITHER a quote or a trade -- quotes update far more often
# than trades for a thin name, so requiring a trade specifically would
# misclassify a quiet-but-live symbol as unreachable
ACTIVE_COVERAGE_MIN_FOR_HEALTHY = 0.95
ACTIVE_COVERAGE_MIN_FOR_PARTIAL = 0.50

# ---------------------------------------------------------------------
# THE 2026-08-19 SENSOR REPAIR (P0-1). MEASURED root cause, not a guess:
# the session logged 352 reconnects, 45% mean tape loss, and 78% loss in
# the final hour. Every one of the 352 closed with exception=None and
# socket_state_before=CLOSED -- a clean close, not a network fault. The
# inter-reconnect intervals clustered at 55s / 75s / 95s, i.e. a base
# offset plus an exact multiple of PING_INTERVAL_S, and the reconnect
# RATE tracked message volume (61/hr at peak, 4/hr after the close) --
# the opposite of what a server idle timer does.
#
# Diagnosis: websocket-client dispatches on_message on the SAME thread
# that maintains ping/pong. on_message was parsing JSON and applying
# ~32M trade/quote events per session inline, so it routinely blocked
# past the 10s pong deadline and the library closed its own socket.
# APEX was starving its own heartbeat.
#
# THE FIX IS ARCHITECTURAL, not a bigger timeout. The reader thread now
# does the cheapest possible thing -- enqueue the raw frame -- and a
# worker thread does all parsing, routing and state mutation:
#
#     WEBSOCKET READER -> bounded queue -> worker -> parse/route/state
#
# A larger ping timeout is kept ONLY as safety margin. It is not the fix
# and must not be treated as one.
INGEST_QUEUE_MAX = 100_000
PING_INTERVAL_S = 20

# ---------------------------------------------------------------------
# L2 HEARTBEAT REMEDY (operator-authorized 2026-08-21 post-seal).
# EVIDENCE: 214 Friday reconnects, every one HEARTBEAT_TIMEOUT with the
# client provably healthy (queue 0, lag ~0, inbound data <=3s old at the
# timeout); pong telemetry showed the server/path STOPS ANSWERING
# protocol pongs under stream load while data keeps flowing (one 58s
# connection: zero pongs, continuous data); after-hours reconnects
# collapsed to ~3 in 2h. The old inference NO PONG = DEAD is invalid
# for this stream.
#
# THE LAW: FRESH VALID INBOUND MARKET DATA = CONNECTION IS ALIVE.
#
# Mechanics (library inspected, websocket-client 1.9.0): with
# ping_timeout=None the library's pong-kill check is skipped entirely
# while pings are still SENT every ping_interval and on_pong still
# fires. Genuine failure detection is preserved and reconnects remain
# valid on: socket close, socket/network exception, provider
# close/error, auth/subscription failure, and -- via the LIVENESS
# WATCHDOG below -- genuine inbound staleness: no data frame AND no
# pong for LIVENESS_STALE_S closes the socket with reason
# MESSAGE_STREAM_STALE. A missing pong with fresh data is COUNTED
# (pong_missing_data_fresh), never fatal. This is not a bigger timeout
# and not an immortal half-open connection.
PING_TIMEOUT_S = None               # library pong-kill DISABLED by law
LIVENESS_STALE_S = 60.0             # no data AND no pong this long = stale
LIVENESS_CHECK_S = 5.0
# a stale-close on a connection that delivered ZERO data frames backs
# off harder (quiet overnight stream), instead of churning every minute
QUIET_RETRY_SLEEP_S = 60.0
WORKER_JOIN_TIMEOUT_S = 5.0


class AlpacaFabricViolation(RuntimeError):
    pass


def _credentials() -> tuple:
    key = os.environ.get("APCA_API_KEY_ID")
    secret = os.environ.get("APCA_API_SECRET_KEY")
    if not key:
        raise AlpacaFabricViolation(
            "APCA_API_KEY_ID absent -- the sensor refuses to start rather "
            "than run blind")
    if not secret:
        raise AlpacaFabricViolation(
            "APCA_API_SECRET_KEY absent -- Alpaca requires BOTH key and "
            "secret to authenticate; the key alone cannot open a session. "
            "No live connection has been attempted without both.")
    return key, secret


class AlpacaRealtimeFabric:
    """ONE connection, unlimited symbols (measured plan behavior per
    Alpaca's own published entitlement table -- not yet independently
    re-measured by APEX, see the module docstring)."""

    def __init__(self, symbols: list, url: str = WS_URL,
                max_trades: int = 2_000_000):
        self.symbols = [s.upper().replace(".US", "") for s in symbols]
        self.url = url
        self.trades: dict = {s: deque(maxlen=max_trades) for s in self.symbols}
        self.quotes: dict = {}
        self._seen: dict = {s: set() for s in self.symbols}
        self._lock = threading.RLock()
        self._ws = None
        self._thread = None
        self._stop = False
        self.authorized = False
        self.subscribed = False
        self.connected_at = None
        self.last_msg_at = None                 # real trade/quote data only
        self._outages: list = []
        self._disconnected_at = None
        self._symbols_with_trades: set = set()
        self._symbols_with_quotes: set = set()
        # §3: requested vs ACCEPTED, per Alpaca's own "subscription" echo
        # -- never assumed from what we asked for
        self.trade_symbols_accepted: tuple = ()
        self.quote_symbols_accepted: tuple = ()
        # PROCESS START, not connection start. An auditor comparing a
        # reconnect COUNTER against a reconnect EVENT LEDGER needs to know
        # whether the running process is older than the instrumentation --
        # otherwise a legitimately-empty ledger reads as a mismatch. This
        # is the only artifact field that can answer that.
        self.process_start_utc = str(
            __import__("pandas").Timestamp.now(tz="UTC"))
        # --- INGEST DECOUPLING (P0-1 repair) -------------------------
        # BOUNDED, and it drops rather than blocks when full: blocking
        # here would push backpressure straight back onto the reader
        # thread and recreate the exact starvation this fix removes. A
        # drop is real data loss, so it is COUNTED and surfaced in
        # health() -- never silent.
        self._ingest: queue.Queue = queue.Queue(maxsize=INGEST_QUEUE_MAX)
        self._worker = None
        self.queue_depth_max = 0
        self.worker_lag_s_max = 0.0
        self.worker_lag_s_last = 0.0
        # Phase 11 close/error forensics (None until first observed)
        self._last_close_code = None
        self._last_close_msg = None
        self._last_close_at = None
        self._last_error_type = None
        self._last_error_repr = None
        self._last_error_at = None
        # Layer 2 pong telemetry (which side of the heartbeat died?)
        self._last_pong_at = None
        self._pongs_received = 0
        self._last_server_ping_at = None
        self._server_pings = 0
        # L2 remedy: liveness watchdog state
        self._liveness_thread = None
        self._stale_close_pending = False
        self._data_frames_this_connection = 0
        self._last_frame_at = None
        # VALIDITY-GATED LIVENESS (operator law, 2026-08-24). A frame
        # ARRIVING is not evidence the feed is alive -- a peer emitting
        # malformed or replayed bytes keeps a transport anchor fresh
        # forever while delivering no market truth. Only a frame that
        # PARSES, carries a usable market message, and is neither
        # future-dated nor older than what we have already seen may
        # advance liveness.
        self._last_valid_data_at = None
        self._newest_event_epoch = 0.0
        self.counters = {"messages": 0, "trades": 0, "quote_messages": 0,
                         "duplicates": 0, "out_of_order": 0,
                         "future_rejected": 0, "unknown_symbol": 0,
                         "reconnects": 0, "provider_errors": 0,
                         "resubscriptions": 0, "frames_dropped": 0,
                         "frames_processed": 0}

    # ------------------------------------------------------- transport
    def _on_open(self, ws) -> None:
        key, secret = _credentials()
        with self._lock:
            self.connected_at = time.time()
            self._data_frames_this_connection = 0
            self.authorized = False
            if self._disconnected_at is not None:
                self._outages.append((self._disconnected_at, time.time()))
                self._disconnected_at = None
        ws.send(json.dumps({"action": "auth", "key": key, "secret": secret}))

    def _on_close(self, _ws=None, close_status_code=None,
                  close_msg=None) -> None:
        # PHASE 11 TELEMETRY (2026-08-20): 644 lifetime reconnect events
        # all carried the HARDCODED literal reason=NETWORK_RECONNECT and
        # a null exception, because this handler discarded the close
        # frame and on_error was aliased here, discarding the exception
        # too. Root-causing 278 reconnects/day was IMPOSSIBLE from the
        # artifacts. Observability only -- reconnect BEHAVIOR unchanged.
        with self._lock:
            self.authorized = False
            self.subscribed = False
            if self._disconnected_at is None:
                self._disconnected_at = time.time()
            if close_status_code is not None or close_msg:
                self._last_close_code = close_status_code
                self._last_close_msg = (str(close_msg)[:512]
                                        if close_msg else None)
                self._last_close_at = time.time()

    def _on_error(self, _ws=None, error=None) -> None:
        """Separate from _on_close for the first time: the exception the
        websocket library actually raised (ping/pong timeout, TCP reset,
        TLS error...) is the single most diagnostic fact about a
        reconnect, and it was being thrown away."""
        with self._lock:
            if error is not None:
                self._last_error_type = type(error).__name__
                self._last_error_repr = repr(error)[:512]
                self._last_error_at = time.time()
        self._on_close(_ws)

    # LAYER 2 COMMISSIONING TELEMETRY (2026-08-21). Friday labeled every
    # reconnect HEARTBEAT_TIMEOUT with the client provably healthy --
    # the next question is WHICH side of the heartbeat died: did our
    # pings go unanswered (server/path swallowing pongs) or did the
    # library's ping thread stall (client-side)? These handlers give the
    # timeout its pong history. Observability only; behavior unchanged.
    def _on_ping(self, _ws=None, _msg=None) -> None:
        with self._lock:
            self._last_server_ping_at = time.time()
            self._server_pings += 1

    def _on_pong(self, _ws=None, _msg=None) -> None:
        with self._lock:
            self._last_pong_at = time.time()
            self._pongs_received += 1

    def _subscribe_all(self, ws) -> None:
        ws.send(json.dumps({"action": "subscribe",
                            "trades": self.symbols, "quotes": self.symbols}))

    def _liveness_watchdog(self) -> None:
        """THE L2 REMEDY's enforcement thread. Every LIVENESS_CHECK_S:
        if the connection is open and NEITHER a data frame NOR a pong
        has arrived within LIVENESS_STALE_S, close the socket -- the
        reconnect loop then labels it MESSAGE_STREAM_STALE. A missing
        pong while data is fresh is counted, never fatal."""
        while not self._stop:
            time.sleep(LIVENESS_CHECK_S)
            with self._lock:
                ws = self._ws
                connected = self.connected_at
                # liveness anchors on VALID data, not raw frames
                last_msg = self._last_valid_data_at
                pong_at = self._last_pong_at
            if ws is None or connected is None:
                continue
            now = time.time()
            anchor = max(connected,
                         last_msg or 0.0, pong_at or 0.0)
            if now - anchor <= LIVENESS_STALE_S:
                # alive; additionally count the previously-fatal shape
                pong_stale = (pong_at is None
                              or now - pong_at > LIVENESS_STALE_S)
                data_fresh = (last_msg is not None
                              and now - last_msg <= 5.0)   # VALID data
                if pong_stale and data_fresh:
                    with self._lock:
                        self.counters["pong_missing_data_fresh"] =                             self.counters.get(
                                "pong_missing_data_fresh", 0) + 1
                continue
            # genuinely stale: no data AND no pong for LIVENESS_STALE_S
            with self._lock:
                self._stale_close_pending = True
            try:
                ws.close()
            except Exception:                           # noqa: BLE001
                pass

    def _on_message(self, ws, raw) -> None:
        """READER THREAD ONLY. Must stay O(1) and allocation-light: every
        microsecond spent here is a microsecond the library cannot spend
        answering a ping. Parsing happens on the worker."""
        now = time.time()
        with self._lock:
            self.counters["messages"] += 1
            self._data_frames_this_connection += 1
            # TRANSPORT liveness: a frame ARRIVED, regardless of what
            # the application does with it. The watchdog anchors here --
            # a starved worker surfaces as queue/lag metrics, never as
            # a fake transport death.
            self._last_frame_at = now
        try:
            self._ingest.put_nowait((raw, now, ws))
            d = self._ingest.qsize()
            if d > self.queue_depth_max:
                self.queue_depth_max = d
        except queue.Full:
            # real data loss -- counted, never swallowed
            with self._lock:
                self.counters["frames_dropped"] += 1

    def _drain(self) -> None:
        """WORKER THREAD. All parsing, routing and state mutation. Kept
        entirely off the socket thread so a slow cycle here can never
        cost us a pong."""
        while True:
            try:
                item = self._ingest.get(timeout=0.5)
            except queue.Empty:
                if self._stop:
                    return
                continue
            if item is None:                    # shutdown sentinel
                return
            self._handle(item)

    def _handle(self, item) -> None:
        raw, now, ws = item
        lag = time.time() - now
        self.worker_lag_s_last = lag
        if lag > self.worker_lag_s_max:
            self.worker_lag_s_max = lag
        try:
            self._process_frame(raw, now, ws)
            self._advance_valid_liveness(raw, now)
        except Exception as e:                  # noqa: BLE001
            # a poison frame must not kill ingestion, and must not vanish
            try:
                from apex.governance.ledger_error import record as _lerr
                _lerr(service="alpaca_fabric", operation="OTHER", exc=e,
                      recovery_action="frame skipped; ingestion continues")
            except Exception:                   # noqa: BLE001
                pass
        finally:
            with self._lock:
                self.counters["frames_processed"] += 1

    def _advance_valid_liveness(self, raw, now: float) -> None:
        """Advance the liveness anchor ONLY for valid, fresh market data.

        Three rejections, each a way a dead feed can look alive:
          malformed  -- bytes that do not parse are not market truth
          future     -- an event stamped ahead of now is not observation
          replayed   -- an event no newer than one already seen carries
                        no new information, so a peer replaying its
                        buffer cannot hold the connection open
        """
        try:
            msgs = json.loads(raw)
        except Exception:                       # noqa: BLE001
            with self._lock:
                self.counters["liveness_rejected_malformed"] = \
                    self.counters.get("liveness_rejected_malformed", 0) + 1
            return
        if isinstance(msgs, dict):
            msgs = [msgs]
        if not isinstance(msgs, list):
            return
        newest = 0.0
        for m in msgs:
            if not isinstance(m, dict) or m.get("T") not in (
                    "t", "q", "b"):             # trade / quote / bar
                continue
            ts = m.get("t")
            if not ts:
                continue
            try:
                import pandas as pd
                ev = pd.Timestamp(ts).timestamp()
            except Exception:                   # noqa: BLE001
                continue
            if ev > now + 5.0:                  # future-invalid
                with self._lock:
                    self.counters["liveness_rejected_future"] = \
                        self.counters.get("liveness_rejected_future", 0) + 1
                continue
            newest = max(newest, ev)
        if newest <= 0.0:
            return
        with self._lock:
            if newest <= self._newest_event_epoch:
                self.counters["liveness_rejected_replay"] = \
                    self.counters.get("liveness_rejected_replay", 0) + 1
                return
            self._newest_event_epoch = newest
            self._last_valid_data_at = now

    def _pump(self, limit: int = 1_000_000) -> int:
        """Drain the ingest queue on the CALLING thread.

        The worker owns this in production. This exists so a test can
        exercise the real reader -> queue -> handler path synchronously
        instead of asserting against a weaker, hand-rolled substitute:
        the frames still go through put_nowait and still come back out
        the same way, just without a thread to schedule."""
        n = 0
        while n < limit:
            try:
                item = self._ingest.get_nowait()
            except queue.Empty:
                return n
            if item is None:
                return n
            self._handle(item)
            n += 1
        return n

    def _process_frame(self, raw, now: float, ws=None) -> None:
        try:
            frames = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return
        if isinstance(frames, dict):
            frames = [frames]
        for d in frames:
            t = d.get("T")
            # ONLY real trade/quote data updates last_msg_at (the same
            # fix applied to equity_fabric.py this morning): an
            # authorized-but-silent connection must read CONNECTED_NO_
            # DATA, never HEALTHY off a control-message handshake that
            # happened once and was never followed by real data.
            if t == "success" and d.get("msg") == "authenticated":
                with self._lock:
                    self.authorized = True
                self._subscribe_all(ws)
            elif t == "error":
                # never silently absorbed -- surfaced via health/counters
                self.counters["provider_errors"] += 1
            elif t == "subscription":
                # THE ACCEPTED-SYMBOL SOURCE OF TRUTH (§3): never assume
                # "requested" == "accepted" -- Alpaca echoes back exactly
                # what it actually subscribed us to.
                with self._lock:
                    was_subscribed = self.subscribed
                    self.subscribed = True
                    self.trade_symbols_accepted = tuple(
                        sorted(d.get("trades") or []))
                    self.quote_symbols_accepted = tuple(
                        sorted(d.get("quotes") or []))
                    if was_subscribed:
                        self.counters["resubscriptions"] += 1
            elif t == "t":
                self._apply_trade(d, now)
            elif t == "q":
                self._apply_quote(d, now)
            # "b" (Alpaca's own bars) intentionally not consumed -- see
            # module docstring: APEX builds its own canonical bars

    def _apply_trade(self, d: dict, now: float) -> None:
        with self._lock:
            self.last_msg_at = now
        sym = str(d.get("S", "")).upper()
        if sym not in self.trades:
            with self._lock:
                self.counters["unknown_symbol"] += 1
            return
        try:
            import pandas as pd
            price = float(d["p"])
            size = float(d.get("s") or 0.0)
            event_s = pd.Timestamp(d["t"]).timestamp()
        except (KeyError, TypeError, ValueError):
            return
        if event_s > now + 5.0:
            with self._lock:
                self.counters["future_rejected"] += 1
            return
        key = (d.get("t"), price, size, str(d.get("i")))
        with self._lock:
            self.counters["trades"] += 1
            self._symbols_with_trades.add(sym)
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
                       "known_from_s": now, "conditions": d.get("c")})

    def _apply_quote(self, d: dict, now: float) -> None:
        with self._lock:
            self.last_msg_at = now
            self.counters["quote_messages"] += 1
        sym = str(d.get("S", "")).upper()
        try:
            import pandas as pd
            bid, ask = float(d["bp"]), float(d["ap"])
            bid_sz, ask_sz = float(d.get("bs") or 0), float(d.get("as") or 0)
            event_s = pd.Timestamp(d["t"]).timestamp()
        except (KeyError, TypeError, ValueError):
            return
        if event_s > now + 5.0:
            with self._lock:
                self.counters["future_rejected"] += 1
            return
        with self._lock:
            self._symbols_with_quotes.add(sym)
            self.quotes[sym] = {"bid": bid, "ask": ask, "bid_size": bid_sz,
                                "ask_size": ask_sz, "event_s": event_s,
                                "known_from_s": now}

    def _run(self) -> None:
        import websocket
        while not self._stop:
            last_exception = None
            rf_returned = None
            try:
                self._ws = websocket.WebSocketApp(
                    self.url, on_open=self._on_open,
                    on_message=self._on_message, on_close=self._on_close,
                    on_error=self._on_error, on_ping=self._on_ping,
                    on_pong=self._on_pong)
                rf_returned = self._ws.run_forever(
                    sslopt={"ca_certs": "/etc/ssl/cert.pem"},
                    ping_interval=PING_INTERVAL_S,
                    ping_timeout=PING_TIMEOUT_S)
            except Exception as e:                          # noqa: BLE001
                last_exception = f"{type(e).__name__}: {e}"
                self._on_close()
            if self._stop:
                break
            # THE COUNTER LAW (Phase 1.0, 2026-08-18): no reconnect
            # counter may increment without a durable event. Before this,
            # the counter reached 388 with zero log lines and zero
            # persisted events, leaving "did those reconnects damage the
            # stream?" unanswerable from the artifacts.
            with self._lock:
                self.counters["reconnects"] += 1
                seq = self.counters["reconnects"]
                disconnected_at = self._disconnected_at
                expected_subs = len(self.symbols)
                close_code = self._last_close_code
                close_msg = self._last_close_msg
                close_at = self._last_close_at
                err_type = self._last_error_type
                err_repr = self._last_error_repr
                err_at = self._last_error_at
                pong_at = self._last_pong_at
                pongs = self._pongs_received
                srv_pings = self._server_pings
                stale_close = self._stale_close_pending
                self._stale_close_pending = False
                conn_frames = self._data_frames_this_connection
                q_depth = self._ingest.qsize()
                q_hw = self.queue_depth_max
                lag_now = self.worker_lag_s_last
                lag_hw = self.worker_lag_s_max
                last_msg = self.last_msg_at
                # consume the forensics: each event reports only what
                # was observed since the LAST event, never stale reuse
                self._last_close_code = self._last_close_msg = None
                self._last_close_at = None
                self._last_error_type = self._last_error_repr = None
                self._last_error_at = None
            try:
                import pandas as pd

                from apex.intraday import reconnect_ledger as _rlg
                _now = pd.Timestamp.now(tz="UTC")
                duration_ms = ((time.time() - disconnected_at) * 1000.0
                              if disconnected_at is not None else None)
                # PHASE 11 (2026-08-20): reason DERIVED from evidence,
                # never the old hardcoded NETWORK_RECONNECT. When no
                # evidence exists, say UNKNOWN and attach what raw
                # observations there are.
                # PING_TIMEOUT_S is None BY LAW (the library pong-kill is
                # deliberately disabled), so it must never be summed
                # naively. From 2026-08-24 to 2026-08-25 this line raised
                # TypeError on EVERY reconnect, before persist() was ever
                # reached: 50 reconnect counter increments produced 0
                # event records across two prospective sessions, and the
                # cause of every one of them is now permanently
                # unrecoverable. The recovery handler worked perfectly and
                # logged 37 LEDGER_WRITE errors -- which is how this was
                # found. Code that "looks correct" is not evidence it ran.
                recent = 3.0 * (PING_INTERVAL_S + (PING_TIMEOUT_S or 0))
                err_recent = (err_at is not None
                              and time.time() - err_at < recent)
                close_recent = (close_at is not None
                                and time.time() - close_at < recent)
                if stale_close:
                    reason = "MESSAGE_STREAM_STALE"  # our watchdog: no
                                                     # data AND no pong
                elif err_recent and "Timeout" in (err_type or ""):
                    reason = "HEARTBEAT_TIMEOUT"     # legacy; should not
                                                     # occur with the
                                                     # remedy active
                elif err_recent or last_exception:
                    reason = "NETWORK_RECONNECT"     # a REAL client error
                elif close_recent and close_code is not None:
                    reason = "PROVIDER_RECONNECT"    # server sent a close
                else:
                    reason = "UNKNOWN_CAUSE"
                _rlg.persist(_rlg.make_event(
                    event_id=f"{TRANSPORT}-reconnect-{seq}",
                    event_time=_now, known_from=_now,
                    reason=reason,
                    exception=(last_exception or err_repr),
                    socket_state_before="CLOSED", socket_state_after="CONNECTING",
                    trade_stream_state="UNSUBSCRIBED",
                    quote_stream_state="UNSUBSCRIBED",
                    subscriptions_expected=expected_subs,
                    subscriptions_restored=None,
                    disconnect_duration_ms=duration_ms,
                    first_message_after_reconnect=None,
                    symbols_missing_before=(), symbols_missing_after=(),
                    source="alpaca_fabric._run",
                    telemetry={
                        "close_code": close_code, "close_msg": close_msg,
                        "error_type": err_type, "error_repr": err_repr,
                        "run_forever_returned": (None if last_exception
                                                 else rf_returned),
                        "queue_depth_at_event": q_depth,
                        "queue_depth_high_water": q_hw,
                        "worker_lag_s_at_event": round(lag_now, 3),
                        "worker_lag_s_high_water": round(lag_hw, 3),
                        "last_message_age_s": (round(time.time() - last_msg,
                                                     2)
                                               if last_msg else None),
                        "ping_interval_s": PING_INTERVAL_S,
                        "ping_timeout_s": PING_TIMEOUT_S,
                        "last_pong_age_s": (round(time.time() - pong_at, 1)
                                            if pong_at else None),
                        "pongs_received_lifetime": pongs,
                        "server_pings_lifetime": srv_pings}))
            except Exception as _e:                         # noqa: BLE001
                # A ledger write must never kill the sensor loop -- but it
                # must not vanish either. reconcile() would surface the
                # missing event as COUNTER_LEDGER_MISMATCH; this makes the
                # CAUSE durable too instead of stdout-only.
                try:
                    from apex.governance.ledger_error import record as _lerr
                    _lerr(service="alpaca_fabric", operation="LEDGER_WRITE",
                          exc=_e, ledger="alpaca_reconnect_events.jsonl",
                          recovery_action="sensor loop continues; reconcile() "
                                          "will report COUNTER_LEDGER_MISMATCH")
                except Exception:                           # noqa: BLE001
                    pass
            # a stale-close on a connection that never delivered a single
            # data frame is a quiet stream, not an outage -- back off so
            # overnight silence does not become a reconnect churn.
            if stale_close and conn_frames == 0:
                time.sleep(QUIET_RETRY_SLEEP_S)
            else:
                time.sleep(2.0)

    def start(self) -> None:
        self._stop = False
        # worker FIRST: the reader must never find itself with nowhere to
        # hand a frame
        self._worker = threading.Thread(target=self._drain, daemon=True,
                                        name="alpaca-ingest-worker")
        self._worker.start()
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="alpaca-ws-reader")
        self._thread.start()
        self._liveness_thread = threading.Thread(
            target=self._liveness_watchdog, daemon=True,
            name="alpaca-liveness-watchdog")
        self._liveness_thread.start()

    def stop(self) -> None:
        self._stop = True
        try:
            self._ingest.put_nowait(None)       # wake the worker to exit
        except queue.Full:
            pass
        if self._worker is not None:
            self._worker.join(timeout=WORKER_JOIN_TIMEOUT_S)
        if self._ws:
            try:
                self._ws.close()
            except Exception:                               # noqa: BLE001
                pass

    # ----------------------------------------------------------- bars
    # A SESSION, not a rolling 400 minutes. On 2026-08-19 the 400-bar
    # window silently erased 09:30-11:39 from SPY/QQQ *during* the
    # session -- the same class of failure as 2026-08-18. 800 covers
    # premarket 08:14 ET through post-close 19:14 ET (660 min) with
    # margin. The in-memory ring is WORKING STORAGE ONLY; the durable
    # record is the accumulating session file written by persist_bars().
    SESSION_BAR_WINDOW_MIN = 800

    def bars_1m(self, symbol: str, minutes: int = SESSION_BAR_WINDOW_MIN):
        import pandas as pd
        from apex.intraday.bar_builder import build_1m_bars
        sym = symbol.upper().replace(".US", "")
        with self._lock:
            tr = list(self.trades.get(sym, ()))
            outages = list(self._outages)
            if self._disconnected_at is not None:
                outages = outages + [(self._disconnected_at, time.time())]
        return build_1m_bars(tr, outages, now=pd.Timestamp.now(tz="UTC"),
                             symbol=sym, transport=TRANSPORT, minutes=minutes)

    def latest_quote(self, symbol: str) -> dict | None:
        sym = symbol.upper().replace(".US", "")
        with self._lock:
            q = self.quotes.get(sym)
        return dict(q) if q else None

    def symbol_activity(self, symbol: str) -> str:
        """§6: distinguishes NO_PROVIDER_DATA (the feed never reached
        this symbol at all -- a real gap) from NO_TRADES_OCCURRED (the
        feed IS delivering for this symbol -- it has quote activity --
        but no trade has printed, which is legitimate for a genuinely
        quiet name and must never make the FEED read unhealthy)."""
        sym = symbol.upper().replace(".US", "")
        with self._lock:
            has_trades = sym in self._symbols_with_trades
            has_quotes = sym in self._symbols_with_quotes
        if has_trades:
            return "TRADES_OBSERVED"
        if has_quotes:
            return "NO_TRADES_OCCURRED"          # reachable, just quiet
        return "NO_PROVIDER_DATA"                # never reached at all

    # --------------------------------------------------------- health
    def health(self) -> dict:
        now = time.time()
        with self._lock:
            last = self.last_msg_at
            authorized, subscribed = self.authorized, self.subscribed
            reconnects = self.counters["reconnects"]
            counters = dict(self.counters)
            trade_accepted = self.trade_symbols_accepted
            quote_accepted = self.quote_symbols_accepted
            n_trade_active = len(self._symbols_with_trades)
            n_quote_active = len(self._symbols_with_quotes)
            n_reachable = len(self._symbols_with_trades
                              | self._symbols_with_quotes)
        age = None if last is None else round(now - last, 2)
        n_intended = len(self.symbols) or 1
        reachable_frac = round(n_reachable / n_intended, 4)

        # THE HEALTH LAW (Phase 12, multi-axis): connection lifecycle
        # first (never claims data health it hasn't earned), then
        # data-preservation tiers, and transport stability as its OWN
        # axis that can DEGRADE the verdict but cannot alone call a
        # data-preserving sensor FAILED.
        import pandas as _pd
        try:
            hours_up = max(0.25, (_pd.Timestamp.now(tz="UTC")
                                  - _pd.Timestamp(self.process_start_utc)
                                  ).total_seconds() / 3600.0)
        except (ValueError, TypeError):
            hours_up = 0.25
        reconnects_per_hour = reconnects / hours_up
        transport_stable = reconnects_per_hour < RECONNECTS_PER_HOUR_DEGRADED
        frames_dropped = counters.get("frames_dropped", 0)
        preservation_ok = frames_dropped == 0

        if not authorized:
            status = CONNECTING
        elif not subscribed:
            status = AUTHENTICATED
        elif last is None:
            status = SUBSCRIBED_NO_DATA
        elif age is not None and age > STALE_AFTER_S:
            status = STALE
        elif not preservation_ok:
            status = FAILED           # the sensor is losing frames: its job
        elif reachable_frac < ACTIVE_COVERAGE_MIN_FOR_PARTIAL:
            status = DEGRADED
        elif not transport_stable:
            status = DEGRADED         # data intact, transport churning
        elif reachable_frac >= ACTIVE_COVERAGE_MIN_FOR_HEALTHY:
            status = HEALTHY
        else:
            status = PARTIAL

        health_axes = {
            "process_alive": True,
            "input_progress": last is not None,
            "data_preservation": preservation_ok,
            "transport_stability": transport_stable,
            "reconnects_per_hour": round(reconnects_per_hour, 2),
            "freshness_ok": age is not None and age <= STALE_AFTER_S,
            "queue_pressure_ok": self.queue_depth_max < INGEST_QUEUE_MAX
            // 10,
            "worker_pressure_ok": self.worker_lag_s_max < 30.0,
            "coverage_fraction": reachable_frac}

        return {"kind": "alpaca_fabric_health", "status": status,
               "health_axes": health_axes,
               "transport": TRANSPORT, "authorized": authorized,
               "subscribed": subscribed,
               "symbols": list(self.symbols), "symbol_count": len(self.symbols),
               "trade_symbols_requested": len(self.symbols),
               "trade_symbols_accepted": len(trade_accepted),
               "quote_symbols_requested": len(self.symbols),
               "quote_symbols_accepted": len(quote_accepted),
               "symbols_with_trade_activity": n_trade_active,
               "symbols_with_quote_activity": n_quote_active,
               "symbols_reachable": n_reachable,
               "reachable_fraction": reachable_frac,
               "last_message_age_s": age, "counters": counters,
               "process_start_utc": self.process_start_utc,
               # INGEST HEALTH (P0-1 repair). queue_depth_max and
               # worker_lag_s_max are the early-warning signal that the
               # worker is falling behind -- the condition that used to
               # present only as unexplained reconnects.
               "ingest_queue_depth": self._ingest.qsize(),
               "ingest_queue_depth_max": self.queue_depth_max,
               "ingest_queue_max": INGEST_QUEUE_MAX,
               "worker_lag_s_max": round(self.worker_lag_s_max, 3),
               "ping_interval_s": PING_INTERVAL_S,
               "ping_timeout_s": PING_TIMEOUT_S,
               "decision_power": "NONE_OBSERVATIONAL_EPOCH1",
               "measured_at_utc": str(__import__("pandas").Timestamp.now(tz="UTC"))}


# --------------------------------------------------------- persistence
# PRIMARY_BROAD_SENSOR consumer read: identical contract to
# apex/intraday/equity_fabric.py's load_live_bars/as_normalize_rows_shape
# so hunter_forward_clock.py / fastwatch.py can try Alpaca FIRST, then
# EODHD, then the historical fallback, with zero shape differences.
BARS_DIR = Path("data/live/alpaca_fabric/bars")


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
    normalize_rows() produces -- the same contract EODHD's live path
    already honors, so a caller can try providers in priority order with
    zero downstream shape changes. Absent -> empty frame."""
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
