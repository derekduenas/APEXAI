#!/usr/bin/env python
"""Resident live equity sensor. Starts the WebSocket fabric (trades +
quotes, both capped at the measured 50-symbol entitlement), persists
APEX's own completed 1m bars, republishes bid/ask, and reallocates the
subscription set deterministically as candidates change tier.

    python scripts/equity_fabric_daemon.py [--minutes 400]

DAY-1 P0 RECOVERY: this replaces the Intraday Historical endpoint as the
LIVE transport. That endpoint is preserved for historical/replay use and
is never again read as "now". The 50-SYMBOL RESOURCE LAW is enforced by
apex.intraday.subscription_allocator, not by this script.

decision_power NONE_OBSERVATIONAL_EPOCH1 — a sensor, nothing more.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

_S = Path(__file__).resolve().parent
sys.path.insert(0, str(_S.parent)); sys.path.insert(0, str(_S))

import pandas as pd  # noqa: E402

from apex.intraday.equity_fabric import (  # noqa: E402
    EquityRealtimeFabric, persist_bars, write_health)
from apex.intraday.subscription_allocator import (  # noqa: E402
    allocate, persist_change)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=400)
    ap.add_argument("--persist-every", type=float, default=20.0)
    ap.add_argument("--reallocate-every", type=float, default=90.0)
    a = ap.parse_args()

    alloc = allocate()
    print(f"initial allocation: {alloc['streamed_count']}/"
          f"{alloc['intended_universe_size']} "
          f"(coverage={alloc['coverage_frac']:.3f})", flush=True)
    for tier, syms in alloc["tiers"].items():
        print(f"  {tier}: {len(syms)}", flush=True)
    persist_change([], alloc)

    # EODHD-FABRIC-LATENT-001: this raises. The daemon is left
    # intact deliberately -- deleting it would hide that a
    # blocked sensor still has an entry point.
    fab = EquityRealtimeFabric(symbols=alloc["symbols"])
    fab.start()
    t_end = time.time() + a.minutes * 60

    last_report = 0.0
    last_realloc = time.time()
    current_symbols = list(alloc["symbols"])
    while time.time() < t_end:
        time.sleep(a.persist_every)
        day = str(pd.Timestamp.now(tz="America/New_York").date())
        h = fab.health()
        cov = {"streamed_count": len(current_symbols),
              "intended_universe_size": alloc["intended_universe_size"],
              "coverage_frac": alloc["coverage_frac"]}
        try:
            written = persist_bars(fab, day, coverage=cov)
        except Exception as e:                              # noqa: BLE001
            h["persist_error"] = f"{type(e).__name__}: {e}"
            written = {}
        h["bars_persisted"] = written
        h["realtime_universe_coverage"] = cov
        write_health(h)

        if time.time() - last_realloc > a.reallocate_every:
            last_realloc = time.time()
            new_alloc = allocate()
            if set(new_alloc["symbols"]) != set(current_symbols):
                diff = fab.resubscribe(new_alloc["symbols"])
                persist_change(current_symbols, new_alloc)
                print(f"{pd.Timestamp.now(tz='UTC'):%H:%M:%S} "
                      f"REALLOCATE +{len(diff['added'])} "
                      f"-{len(diff['dropped'])} "
                      f"coverage={new_alloc['coverage_frac']:.3f}",
                      flush=True)
                current_symbols = list(new_alloc["symbols"])
                alloc = new_alloc

        if time.time() - last_report > 60:
            last_report = time.time()
            tot = sum(written.values()) if written else 0
            tc, qc = h["trade_channel"], h["quote_channel"]
            print(f"{pd.Timestamp.now(tz='UTC'):%H:%M:%S} {h['status']} "
                  f"trade={tc['status']} quote={qc['status']} "
                  f"trades={h['counters']['trades']} "
                  f"quotes={h['counters']['quote_messages']} "
                  f"dup={h['counters']['duplicates']} "
                  f"ooo={h['counters']['out_of_order']} "
                  f"bars={tot} n_sym={len(current_symbols)}", flush=True)
    fab.stop()
    write_health({**fab.health(), "status_note": "daemon budget reached"})
    print("equity fabric stopped (budget reached)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
