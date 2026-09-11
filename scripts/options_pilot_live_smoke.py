"""READ-ONLY LIVE SMOKE for the options pilot twin (M2) — PREPARED, NOT AUTHORIZED.

What it would do, once an operator authorizes it:
    1. print the LiveGate status (switch + credential PRESENCE, never values)
    2. fetch the last N minutes of SPY 1-minute bars (Alpaca) and the latest NBBO
    3. fetch the nearest >= 21 DTE expiration chain snapshot (ThetaData, local :25503)
    4. ingest through BarStore, compose one OPTIONS_TWIN_STATE_V0 snapshot, run the frozen
       artifact adapter ONCE, and write everything to an OUTPUT DIRECTORY YOU NAME
       (never the live options ledger), labelled data_provenance=LIVE_FEED, evidence_class=SMOKE_READ_ONLY
    5. place no order, write no pilot ledger record, start no service

Gates (all must hold or the script exits 3 before any network access):
    --authorization-file PATH   a file the OPERATOR creates containing the literal line
                                OPTIONS_PILOT_LIVE_SMOKE_AUTHORIZED <YYYY-MM-DD>
    APEX_PILOT_LIVE_DATA=ENABLED in the environment
    credentials present (Alpaca key id + secret via the existing secret backend)
This script contains no HTTP client wiring on purpose: `--dry-plan` prints the exact requests it
would make; `--execute` requires the gates and an `http_get` implementation supplied by the
operator-reviewed commissioning change (see docs/OPTIONS_PILOT_LIVE_SMOKE_AND_COLLECTION_REQUEST.md)."""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apex.pulse_options.providers import ALPACA, THETA, LIVE_SWITCH, LiveGate   # noqa: E402

TOKEN = "OPTIONS_PILOT_LIVE_SMOKE_AUTHORIZED"


def plan(symbol: str, minutes: int) -> dict:
    now = datetime.now(timezone.utc)
    return {"symbol": symbol, "minutes": minutes,
            "requests": [
                {"purpose": "underlying 1-minute bars", "method": "GET",
                 "url": "%s/stocks/%s/bars?timeframe=1Min&start=<now-%dm>&end=<now>&limit=10000&feed=sip" % (ALPACA, symbol, minutes)},
                {"purpose": "underlying NBBO", "method": "GET", "url": "%s/stocks/%s/quotes/latest?feed=sip" % (ALPACA, symbol)},
                {"purpose": "option expirations", "method": "GET", "url": "%s/option/list/expirations?symbol=%s" % (THETA, symbol)},
                {"purpose": "chain snapshot (nearest >= 21 DTE)", "method": "GET", "url": "%s/option/snapshot/quote?symbol=%s&expiration=<YYYYMMDD>" % (THETA, symbol)}],
            "writes": ["<out_dir>/smoke_<utc>.json (bars counters, snapshot, one forecast record, gate status)"],
            "does_not": ["write the pilot or live options ledger", "send orders", "start services", "store credential values"],
            "planned_at_utc": now.isoformat()}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="SPY")
    ap.add_argument("--minutes", type=int, default=90)
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--authorization-file", default=None)
    ap.add_argument("--dry-plan", action="store_true", help="print the exact requests; contact nothing")
    ap.add_argument("--execute", action="store_true", help="requires every gate; NOT wired in this build")
    a = ap.parse_args(argv)
    p = plan(a.symbol, a.minutes)
    if a.dry_plan or not a.execute:
        print(json.dumps({"mode": "DRY_PLAN", **p}, indent=1))
        return 0
    gate = LiveGate()
    st = gate.status()
    auth_ok = False
    if a.authorization_file and Path(a.authorization_file).exists():
        auth_ok = any(line.strip().startswith(TOKEN) for line in Path(a.authorization_file).read_text().splitlines())
    if not (auth_ok and st["enabled"] and a.out_dir):
        print(json.dumps({"mode": "REFUSED", "authorization_file_ok": auth_ok, "gate": st, "out_dir": a.out_dir,
                          "why": "operator authorization file, %s=ENABLED, credentials and --out-dir are all required" % LIVE_SWITCH}, indent=1))
        return 3
    print(json.dumps({"mode": "REFUSED", "why": "HTTP_CLIENT_NOT_WIRED: the executing client is supplied by the reviewed commissioning change"}, indent=1))
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
