#!/usr/bin/env python
"""BTC-L2 -- BITNOMIAL NATIVE WEBSOCKET TRADES + BOOK COMMISSIONING.

Protocol (docs read 2026-08-21, never guessed):
  wss://bitnomial.com/exchange/ws ; subscribe within 10s or be
  disconnected; trade={ack_id,price,quantity,symbol,taker_side,
  timestamp}; book snapshot + level deltas (apply iff level.ack_id >
  snapshot ack_id; qty 0 clears; book ack_id 0 = markets closed).

LAWS ENFORCED HERE:
  * WS price units are UNKNOWN until empirically resolved against the
    REST tick value at startup -- USD conversion is REFUSED before
    resolution and the resolution evidence is persisted.
  * After any sequence uncertainty the book is INVALID until a clean
    snapshot resync (engine law) -- an invalid book yields a reason,
    never a price. Resync is forced by reconnecting.
  * Liveness (Alpaca L2 lesson): fresh inbound frames = alive; the
    watchdog closes only when frames AND pongs are BOTH stale.
  * Every persisted event carries event_time (venue), arrival_time
    (ours), known_from.

Writes: results/btc/ws_trades_ledger.jsonl   (hash-chained)
        results/btc/ws_book_ledger.jsonl     (hash-chained; snapshots,
                                              invalidations, 15s top-
                                              of-book samples -- raw
                                              levels are folded into
                                              engine state, counted,
                                              not individually stored)
        results/btc/ws_health.json

decision_power: NONE -- a sensor.
"""
from __future__ import annotations

import json
import ssl
import sys
import threading
import time
import urllib.request
from collections import deque
from pathlib import Path

_S = Path(__file__).resolve().parent
sys.path.insert(0, str(_S.parent))

from apex.btc_sleeve.book_engine import BOOK_VALID, BookState  # noqa: E402
from apex.btc_sleeve.semantics import (  # noqa: E402
    BITNOMIAL_WS_SEMANTICS, convert_bitnomial_product_data_price)
from apex.governance.chain_ledger import chain_append  # noqa: E402

WS_URL = BITNOMIAL_WS_SEMANTICS["url"]
SPEC_URL = "https://bitnomial.com/exchange/api/v1/prod/product/spec/5614"
DATA_URL = "https://bitnomial.com/exchange/api/v1/prod/product/data/5614"
# LEDGER GENERATION 2 (2026-08-23): generation 1 is closed as
# FORENSIC_TAINTED_CONCURRENCY_DEFECT (2 thread-race chain breaks,
# root cause proven + repaired in chain_ledger). The g1 files are
# immutable evidence and are NEVER repaired to verify. g2 opens with
# a genesis record carrying full provenance.
TRADES_LEDGER = Path("results/btc/ws_trades_ledger.g2.jsonl")
BOOK_LEDGER = Path("results/btc/ws_book_ledger.g2.jsonl")
G1_CLOSURE = {
    "g1_book": "results/btc/forensic_2026-08-23/ws_book_ledger.jsonl",
    "g1_trades": "results/btc/forensic_2026-08-23/ws_trades_ledger.jsonl",
    "reason": "FORENSIC_TAINTED_CONCURRENCY_DEFECT -- two intra-process "
              "append races (watchdog vs reader thread) broke the g1 "
              "book chain; primitive repaired (atomic thread+flock "
              "transaction); g1 preserved immutable as evidence",
    "incident": "BTC-L2 Defect B, adjudicated 2026-08-23",
}


def _ensure_genesis() -> None:
    """Write the g2 genesis provenance record once per ledger."""
    import hashlib
    import pandas as pd
    for ledger, g1_key in ((BOOK_LEDGER, "g1_book"),
                           (TRADES_LEDGER, "g1_trades")):
        if ledger.exists():
            continue
        g1 = Path(G1_CLOSURE[g1_key])
        g1_hash = (hashlib.sha256(g1.read_bytes()).hexdigest()
                   if g1.exists() else "G1_FILE_ABSENT")
        chain_append(ledger, {
            "kind": "ledger_generation_genesis",
            "generation": 2,
            "known_from": str(pd.Timestamp.now(tz="UTC")),
            "previous_ledger": str(g1),
            "previous_ledger_sha256": g1_hash,
            "reason": G1_CLOSURE["reason"],
            "incident": G1_CLOSURE["incident"],
            "code_version": "chain_ledger atomic tx + book_engine "
                            "v2_stale_snapshot_law_2026_08_23",
            "decision_power": "NONE"})
HEALTH = Path("results/btc/ws_health.json")
CTX = ssl.create_default_context(cafile="/etc/ssl/cert.pem")

PING_INTERVAL_S = 20.0
LIVENESS_STALE_S = 90.0     # frames AND pongs both older -> reconnect
HEALTH_EVERY_S = 15.0
RECONNECT_BACKOFF_S = (2, 5, 15, 60)


def _get(url: str) -> dict:
    req = urllib.request.Request(url, headers={
        "User-Agent": "apex-btc-l2-ws-commissioning"})
    with urllib.request.urlopen(req, context=CTX, timeout=10) as r:
        return json.loads(r.read())


def _utcnow() -> str:
    import pandas as pd
    return str(pd.Timestamp.now(tz="UTC"))


class BitnomialStream:
    def __init__(self) -> None:
        self.spec = _get(SPEC_URL)
        self.symbol = self.spec["symbol"]
        self.increment = self.spec.get("price_increment")
        self.book = BookState()
        self.unit: str | None = None          # TICKS | USD_ALREADY
        self.unit_evidence: dict | None = None
        self.seen_trade_acks: deque = deque(maxlen=4096)
        self.counts = {"frames": 0, "trades": 0, "trade_duplicates": 0,
                       "trade_ts_regressions": 0, "books": 0,
                       "levels": 0, "status_msgs": 0, "unknown_types": 0,
                       "reconnects": 0, "pongs": 0,
                       "unit_resolution_refusals": 0}
        self.last_frame_at = time.time()
        self.last_pong_at = time.time()
        self.last_trade: dict | None = None
        self.prev_trade_ts: str | None = None
        self.started_at = time.time()
        self.reconnect_reasons: list = []
        self._ws = None
        self._stop = False
        self._t_end: float | None = None

    # ---- unit resolution: empirical, persisted, refusal-first -------
    def _resolve_unit(self, raw_price: float) -> None:
        if self.unit is not None or raw_price <= 0:
            return
        try:
            rest = _get(DATA_URL)
        except OSError:
            self.counts["unit_resolution_refusals"] += 1
            return
        ticks = rest.get("last_price")
        if not ticks or not self.increment:
            self.counts["unit_resolution_refusals"] += 1
            return
        usd = ticks * self.increment
        r_ticks = raw_price / ticks
        r_usd = raw_price / usd
        if 0.5 < r_ticks < 2.0 and not 0.5 < r_usd < 2.0:
            self.unit = "TICKS"
        elif 0.5 < r_usd < 2.0 and not 0.5 < r_ticks < 2.0:
            self.unit = "USD_ALREADY"
        else:
            self.counts["unit_resolution_refusals"] += 1
            return
        self.unit_evidence = {
            "kind": "ws_price_unit_resolution", "known_from": _utcnow(),
            "ws_raw_price": raw_price, "rest_last_price_ticks": ticks,
            "rest_last_price_usd": usd, "resolved_unit": self.unit,
            "method": "magnitude reconciliation vs REST /product/data "
                      "(docs are silent on WS units)"}
        chain_append(BOOK_LEDGER, dict(self.unit_evidence,
                                       decision_power="NONE"))
        print(f"WS PRICE UNIT RESOLVED: {self.unit} "
              f"(ws={raw_price} rest_ticks={ticks})", flush=True)

    def _usd(self, raw_price) -> dict:
        """Convert a WS raw price honestly; refuses before resolution."""
        if raw_price is None:
            return {"raw_value": None, "canonical_value": None}
        if self.unit == "TICKS":
            out = convert_bitnomial_product_data_price(
                raw_price, product_spec=self.spec)
        elif self.unit == "USD_ALREADY":
            out = {"raw_value": raw_price, "raw_unit": "USD_ALREADY",
                   "conversion": "NONE", "canonical_value": raw_price,
                   "canonical_unit": "USD_PER_BTC"}
        else:
            out = {"raw_value": raw_price,
                   "raw_unit": "UNKNOWN_UNTIL_RESOLVED",
                   "canonical_value": None,
                   "conversion": "REFUSED_UNIT_UNRESOLVED"}
        return out

    # ---- websocket callbacks ----------------------------------------
    def _on_open(self, ws) -> None:
        sub = {"type": "subscribe", "product_codes": [self.symbol],
               "channels": [
                   {"name": "trade", "product_codes": [self.symbol]},
                   {"name": "book", "product_codes": [self.symbol]}]}
        ws.send(json.dumps(sub))
        print(f"subscribed trade+book {self.symbol}", flush=True)

    def _on_pong(self, ws, _msg) -> None:
        self.last_pong_at = time.time()
        self.counts["pongs"] += 1

    def _on_message(self, ws, raw: str) -> None:
        arrival = time.time()
        self.last_frame_at = arrival
        self.counts["frames"] += 1
        try:
            msg = json.loads(raw)
        except ValueError:
            self.counts["unknown_types"] += 1
            return
        mtype = msg.get("type")
        if mtype == "trade":
            self._on_trade(msg, arrival)
        elif mtype == "book":
            self.counts["books"] += 1
            self._resolve_unit(float(msg["asks"][0][0])
                               if msg.get("asks") else 0.0)
            self.book.apply_snapshot(msg, arrival=arrival)
            recon = self.book.last_reconciliation
            if recon and (recon.get("mismatched_levels") or
                          "classification" in recon or
                          "prior_divergence_classification" in recon):
                chain_append(BOOK_LEDGER, dict(
                    recon, kind="ws_book_reconciliation",
                    known_from=_utcnow(), decision_power="NONE"))
            chain_append(BOOK_LEDGER, {
                "kind": "ws_book_snapshot", "known_from": _utcnow(),
                "venue": "BITNOMIAL", "symbol": msg.get("symbol"),
                "ack_id": msg.get("ack_id"),
                "event_time": msg.get("timestamp"),
                "arrival_time_epoch": round(arrival, 3),
                "bids_raw": msg.get("bids", [])[:10],
                "asks_raw": msg.get("asks", [])[:10],
                "price_unit": self.unit or "UNKNOWN_UNTIL_RESOLVED",
                "book_quality_after": self.book.quality,
                "decision_power": "NONE"})
        elif mtype == "level":
            self.counts["levels"] += 1
            before = self.book.quality
            self.book.apply_level(msg, arrival=arrival)
            if self.book.quality != before and \
                    self.book.quality != BOOK_VALID:
                chain_append(BOOK_LEDGER, {
                    "kind": "ws_book_invalidation",
                    "known_from": _utcnow(),
                    "reason": self.book.invalid_reason,
                    "ack_id": msg.get("ack_id"),
                    "arrival_time_epoch": round(arrival, 3),
                    "decision_power": "NONE"})
                # resync law: force a fresh snapshot via reconnect
                self._request_reconnect("BOOK_INVALID_RESYNC")
        elif mtype == "status":
            self.counts["status_msgs"] += 1
        elif mtype == "disconnect":
            self._request_reconnect(
                f"VENUE_DISCONNECT:{msg.get('reason')}")
        else:
            self.counts["unknown_types"] += 1

    def _on_trade(self, msg: dict, arrival: float) -> None:
        ack = msg.get("ack_id")
        if ack in self.seen_trade_acks:
            self.counts["trade_duplicates"] += 1
            return
        self.seen_trade_acks.append(ack)
        ts = msg.get("timestamp")
        if self.prev_trade_ts is not None and ts is not None and \
                ts < self.prev_trade_ts:
            self.counts["trade_ts_regressions"] += 1
        self.prev_trade_ts = ts
        raw_price = msg.get("price")
        self._resolve_unit(float(raw_price) if raw_price else 0.0)
        rec = {"kind": "ws_trade", "known_from": _utcnow(),
               "venue": "BITNOMIAL", "symbol": msg.get("symbol"),
               "trade_id": ack, "price": self._usd(raw_price),
               "quantity_contracts": msg.get("quantity"),
               "taker_side": msg.get("taker_side"),
               "event_time": ts,
               "arrival_time_epoch": round(arrival, 3),
               "decision_power": "NONE"}
        chain_append(TRADES_LEDGER, rec)
        self.counts["trades"] += 1
        self.last_trade = rec

    def _on_error(self, ws, err) -> None:
        print(f"ws error: {type(err).__name__}: {err}", flush=True)

    def _request_reconnect(self, reason: str) -> None:
        self.reconnect_reasons.append(
            {"at": _utcnow(), "reason": reason})
        try:
            if self._ws is not None:
                self._ws.close()
        except OSError:
            pass

    # ---- liveness watchdog + health ---------------------------------
    def _watchdog(self) -> None:
        last_health = 0.0
        while not self._stop:
            time.sleep(2.0)
            now = time.time()
            if self._t_end is not None and now > self._t_end:
                # budget law: run_forever blocks inside a healthy
                # connection, so the watchdog enforces the time budget
                # (the first soak left an immortal daemon behind and a
                # second writer nearly interleaved the hash chain)
                self._stop = True
                self._request_reconnect("BUDGET_REACHED_SHUTDOWN")
                return
            frame_age = now - self.last_frame_at
            pong_age = now - self.last_pong_at
            if frame_age > LIVENESS_STALE_S and \
                    pong_age > LIVENESS_STALE_S:
                self._request_reconnect(
                    f"LIVENESS_STALE frames={frame_age:.0f}s "
                    f"pongs={pong_age:.0f}s")
                self.last_frame_at = self.last_pong_at = now
            if now - last_health >= HEALTH_EVERY_S:
                last_health = now
                self._write_health(frame_age, pong_age)
                if self.book.quality == BOOK_VALID:
                    top = self.book.top()
                    chain_append(BOOK_LEDGER, dict(
                        top, kind="ws_book_top_sample",
                        known_from=_utcnow(),
                        price_unit=self.unit or "UNKNOWN_UNTIL_RESOLVED",
                        book_mid_usd=self._usd(
                            top.get("book_mid_raw"))["canonical_value"],
                        decision_power="NONE"))

    def _write_health(self, frame_age: float, pong_age: float) -> None:
        try:
            HEALTH.write_text(json.dumps({
                "kind": "btc_ws_health", "as_of": _utcnow(),
                "symbol": self.symbol,
                "uptime_s": round(time.time() - self.started_at),
                "price_unit": self.unit or "UNKNOWN_UNTIL_RESOLVED",
                "book_quality": self.book.quality,
                "book_invalid_reason": self.book.invalid_reason,
                "book_top": self.book.top(),
                "book_continuity": self.book.continuity(),
                "counts": self.counts,
                "frame_age_s": round(frame_age, 1),
                "pong_age_s": round(pong_age, 1),
                "last_trade_event_time":
                    (self.last_trade or {}).get("event_time"),
                "reconnects": self.reconnect_reasons[-10:],
                "decision_power": "NONE"}, indent=1))
        except OSError:
            pass

    # ---- run loop ---------------------------------------------------
    def run(self, minutes: float) -> None:
        import websocket
        t_end = time.time() + minutes * 60
        self._t_end = t_end
        threading.Thread(target=self._watchdog, daemon=True).start()
        backoff_i = 0
        while time.time() < t_end and not self._stop:
            ws = websocket.WebSocketApp(
                WS_URL, on_open=self._on_open,
                on_message=self._on_message, on_error=self._on_error,
                on_pong=self._on_pong)
            self._ws = ws
            connected_at = time.time()
            ws.run_forever(ping_interval=PING_INTERVAL_S,
                           sslopt={"context": CTX})
            # any exit of run_forever = the previous book is uncertain
            self.book.on_disconnect()
            self.counts["reconnects"] += 1
            if not self.reconnect_reasons or \
                    self.reconnect_reasons[-1]["at"] < _utcnow()[:19]:
                self.reconnect_reasons.append(
                    {"at": _utcnow(), "reason": "SOCKET_CLOSED"})
            if time.time() >= t_end:
                break
            if time.time() - connected_at > 120:
                backoff_i = 0        # a stable stint resets the ladder
            time.sleep(RECONNECT_BACKOFF_S[
                min(backoff_i, len(RECONNECT_BACKOFF_S) - 1)])
            backoff_i += 1
        self._stop = True


LOCK = Path("results/btc/ws_stream.pid")


def _acquire_single_writer_lock() -> None:
    """Two concurrent daemons interleave the hash chains -- REFUSE to
    start while a prior instance is alive (caught live 2026-08-21)."""
    import os
    import signal
    if LOCK.exists():
        try:
            pid = int(LOCK.read_text().strip())
            os.kill(pid, 0)
            # contention must be OBSERVABLE (operator mandate) -- the
            # refusal is logged to a sidecar, never to the chain ledger
            # (a second writer touching the ledger is the disease)
            with open("results/btc/ws_lock_contention.jsonl", "a") as f:
                f.write(json.dumps({
                    "kind": "ws_lock_contention",
                    "known_from": _utcnow(), "holder_pid": pid,
                    "refused_pid": os.getpid(),
                    "outcome": "REFUSED_SINGLE_WRITER_LAW"}) + "\n")
            raise SystemExit(f"REFUSED: btc_ws_stream pid={pid} is "
                             f"alive -- single-writer law")
        except (ValueError, ProcessLookupError):
            pass                      # stale lock: dead pid
    LOCK.write_text(str(os.getpid()))
    signal.signal(signal.SIGTERM, lambda *_: SystemExit(0))


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=1e9)
    a = ap.parse_args()
    TRADES_LEDGER.parent.mkdir(parents=True, exist_ok=True)
    _acquire_single_writer_lock()
    _ensure_genesis()
    s = BitnomialStream()
    print(f"BITNOMIAL WS STREAM start symbol={s.symbol} "
          f"increment={s.increment} url={WS_URL}", flush=True)
    s.run(a.minutes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
