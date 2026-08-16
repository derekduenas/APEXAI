#!/usr/bin/env python
"""CRYPTO ARENA DAEMON — the 24/7 flight simulator.

    python scripts/crypto_daemon.py [--minutes N]

Resident process: the Market Fabric holds a continuous WebSocket to
Coinbase (trades/ticker/L2/heartbeats), the arena ticks every 60s
against live state, and open shadow positions are MANAGED every 30s by
the deterministic manager (thesis conditions, not narrative).

Zero capital: no order endpoint exists in this package. Strategy
semantics frozen (CRYPTO-001/002); this daemon is transport + execution
fidelity + trade management only.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

_S = Path(__file__).resolve().parent
sys.path.insert(0, str(_S.parent)); sys.path.insert(0, str(_S))

import pandas as pd  # noqa: E402


def manage_open_positions(fabric, now) -> list:
    """Deterministic live management of open shadow trades: thesis
    conditions evaluated against CURRENT state; exits are declared
    transitions, never narrative. Emits management records."""
    from apex.crypto.arena import LEDGER, _append, _rows
    from apex.hunter.evidence import EvidenceClass, stamp
    rows = _rows()
    closed = {r["decision_id"] for r in rows
              if r.get("kind") == "crypto_shadow_exit"}
    opened = {r["decision_id"]: r for r in rows
              if r.get("kind") == "crypto_decision"}
    verdicts = {r["decision_id"]: r.get("verdict") for r in rows
                if r.get("kind") == "crypto_assassin"}
    out = []
    snap = fabric.snapshot()
    b = snap["books"].get("BTC-USD", {})
    if b.get("status") != "OK":
        return out                              # degraded: no management
    mid = b["mid"]
    for did, d in opened.items():
        if did in closed or verdicts.get(did) != "SHADOW_TRADE":
            continue
        t0 = pd.Timestamp(d["t_utc"])
        age_min = (now - t0).total_seconds() / 60
        sign = 1.0 if d["direction"] == "LONG" else -1.0
        pnl = sign * (mid / d["shadow_entry_price"] - 1)
        reason = None
        if sign > 0 and mid <= d["stop"] or sign < 0 and mid >= d["stop"]:
            reason = "STOP_TOUCHED"
        elif sign > 0 and mid >= d["target"] or sign < 0 and mid <= d["target"]:
            reason = "TARGET_TOUCHED"
        elif age_min >= d.get("time_stop_minutes", 90):
            reason = "TIME_STOP"
        if reason:
            exit_px = b["best_bid"] if sign > 0 else b["best_ask"]
            rec = stamp({"kind": "crypto_shadow_exit",
                         "decision_id": did, "t_utc": str(now),
                         "exit_reason": reason,
                         "exit_price_crossing_spread": exit_px,
                         "hold_minutes": round(age_min, 1),
                         "dynamic_return": round(
                             sign * (exit_px / d["shadow_entry_price"] - 1),
                             6),
                         "mid_at_exit": mid,
                         "note": "deterministic transition; both spreads "
                                 "paid (entry crossed, exit crossed)"},
                        EvidenceClass.COINBASE_FORWARD_OBSERVATION)
            _append(rec)
            out.append(rec)
        else:
            out.append({"decision_id": did, "state": "MANAGING",
                        "unrealized": round(pnl, 5),
                        "age_min": round(age_min, 1)})
    del LEDGER
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=0,
                    help="0 = run until stopped")
    a = ap.parse_args()
    from apex.crypto.arena import tick
    from apex.crypto.fabric import MarketFabric

    fab = MarketFabric()
    fab.start()
    print(f"fabric starting; warming 45s ...")
    time.sleep(45)
    t_end = time.time() + a.minutes * 60 if a.minutes else None
    last_tick = 0.0
    while t_end is None or time.time() < t_end:
        now = pd.Timestamp.now(tz="UTC")
        try:
            mgmt = manage_open_positions(fab, now)
            exits = [m for m in mgmt if m.get("kind")]
            if exits:
                for e in exits:
                    print(f"{now:%H:%M:%S} SHADOW EXIT {e['decision_id']} "
                          f"{e['exit_reason']} {e['dynamic_return']:+.4%} "
                          f"after {e['hold_minutes']}m")
        except Exception as e:                              # noqa: BLE001
            print(f"manage failed: {type(e).__name__}: {e}")
        if time.time() - last_tick >= 60:
            try:
                st = tick(now=now, fabric=fab)
                h = fab.snapshot()["health"]
                print(f"{now:%H:%M:%S} tick {st} | book={h['book_health']} "
                      f"hb={h['heartbeats']} gaps={h['gaps_detected']} "
                      f"reconn={h['reconnects']}")
            except Exception as e:                          # noqa: BLE001
                print(f"tick failed (shadow-only): {type(e).__name__}: {e}")
            last_tick = time.time()
        time.sleep(30)
    fab.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
