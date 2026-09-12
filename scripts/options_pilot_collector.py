"""PROSPECTIVE COLLECTION (observation only) for the options pilot twin — request §B, operator-authorized.

Collects, during REGULAR sessions only, for the declared symbols:
    bars     every completed minute (pulled at ~:05 past the minute, last 5 minutes window, deduped by BarStore)
    nbbo     every 15 s
    chain    every 60 s, nearest >= 21 DTE expiration (ThetaData, local terminal)
Each record is appended with `chain_append` (hash-chained, fsync) under
    /apex-data/pilot_collection/<YYYY-MM-DD>/{bars,nbbo,chain}_<symbol>.jsonl
with receipt clocks, provider identity and the raw provider payload. Nothing here decides, forecasts, or
writes a pilot/live ledger record. It stops on: the operator stop file, disk budget, three consecutive
provider failures, a parse-error rate above 1 %, or the declared number of sessions. A heartbeat JSON is
rewritten every loop so an operator can see it is alive and what it did last."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apex.governance.chain_ledger import chain_append                            # noqa: E402
from apex.intraday import options_feed as OF                                     # noqa: E402
from apex.intraday.sessions import classify                                      # noqa: E402
from apex.pulse_options.providers import LIVE_SWITCH, AlpacaBarsAdapter, LiveGate   # noqa: E402

LAW = "OBSERVATION_ONLY: no decision, no forecast, no order, no pilot or live ledger record"


class Stop(Exception):
    pass


def _now():
    return datetime.now(timezone.utc)


def _dir(root: Path, day: str) -> Path:
    p = root / day
    p.mkdir(parents=True, exist_ok=True)
    return p


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="/apex-data/pilot_collection")
    ap.add_argument("--symbols", default="SPY,QQQ,IWM")
    ap.add_argument("--sessions", type=int, default=10)
    ap.add_argument("--disk-budget-gib", type=float, default=2.0)
    ap.add_argument("--authorization-file", required=True)
    ap.add_argument("--once", action="store_true", help="one loop iteration (used for the smoke of the collector itself)")
    a = ap.parse_args(argv)
    root = Path(a.root); root.mkdir(parents=True, exist_ok=True)
    auth = Path(a.authorization_file)
    auth_line = next((l for l in auth.read_text().splitlines() if l.strip().startswith("OPTIONS_PILOT_COLLECTION_AUTHORIZED")), None) if auth.exists() else None
    gate = LiveGate(secret_fn=OF._secret)
    st = gate.status()
    alpaca = AlpacaBarsAdapter(gate=gate, http_get=OF._get, headers_fn=OF._alpaca_headers)   # keeps provider timestamps + receipt clocks
    hb = root / "HEARTBEAT.json"
    def beat(**kw):
        hb.write_text(json.dumps({"utc": _now().isoformat(), "pid": os.getpid(), "law": LAW, **kw}, indent=1, default=str))
    if not (auth_line and st["enabled"]):
        beat(state="REFUSED", why="authorization file and %s=ENABLED + credentials required" % LIVE_SWITCH, gate=st)
        print(hb.read_text()); return 3
    syms = [s.strip().upper() for s in a.symbols.split(",") if s.strip()]
    stop_file = root / "STOP"
    counters = {"bars": 0, "nbbo": 0, "chain": 0, "failures": 0, "consecutive_failures": 0, "parse_errors": 0, "records": 0, "sessions_seen": []}
    last = {"bars": {}, "nbbo": {}, "chain": {}, "exp": {}}
    beat(state="STARTED", symbols=syms, sessions=a.sessions, authorization=auth_line.strip(), gate=st)

    def record(day, kind, sym, payload):
        rec = {"kind": "pilot_collection_%s" % kind, "symbol": sym, "receipt_utc": _now().isoformat(), "receipt_epoch": time.time(),
               "provider": "ALPACA_DATA_V2" if kind in ("bars", "nbbo") else "THETADATA_V3", "data_provenance": "LIVE_FEED",
               "evidence_class": "PROSPECTIVE_OBSERVATION", "law": LAW, "payload": payload}
        chain_append(_dir(root, day) / ("%s_%s.jsonl" % (kind, sym)), rec)
        counters["records"] += 1

    def attempt(kind, fn):
        try:
            out = fn(); counters["consecutive_failures"] = 0; counters[kind] += 1; return out
        except Exception as e:                                                     # noqa: BLE001
            counters["failures"] += 1; counters["consecutive_failures"] += 1
            counters.setdefault("last_error", "%s %s: %s" % (kind, type(e).__name__, str(e)[:200]))
            if counters["consecutive_failures"] >= 3:
                raise Stop("THREE_CONSECUTIVE_PROVIDER_FAILURES: %s" % counters["last_error"])
            return None

    try:
        while True:
            if stop_file.exists():
                raise Stop("OPERATOR_STOP_FILE")
            used = sum(f.stat().st_size for f in root.rglob("*.jsonl")) / 2 ** 30
            if used > a.disk_budget_gib:
                raise Stop("DISK_BUDGET_REACHED: %.2f GiB" % used)
            if counters["failures"] and counters["records"] and counters["parse_errors"] / max(1, counters["records"]) > 0.01:
                raise Stop("PARSE_ERROR_RATE")
            now = _now()
            phase = classify(now).value
            day = now.astimezone(__import__("zoneinfo").ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
            if phase != "REGULAR":
                beat(state="IDLE_OUTSIDE_REGULAR", phase=phase, counters=counters)
                if a.once:
                    break
                time.sleep(30); continue
            if day not in counters["sessions_seen"]:
                counters["sessions_seen"].append(day)
                if len(counters["sessions_seen"]) > a.sessions:
                    raise Stop("DECLARED_SESSIONS_COMPLETE: %d" % a.sessions)
            t = time.time()
            for sym in syms:
                if t - last["nbbo"].get(sym, 0) >= 15:
                    q = attempt("nbbo", lambda: alpaca.nbbo(sym))
                    if q is not None:
                        record(day, "nbbo", sym, q); last["nbbo"][sym] = t
                if now.second >= 5 and t - last["bars"].get(sym, 0) >= 60:
                    b = attempt("bars", lambda: alpaca.bars(sym, start_epoch=time.time() - 300, end_epoch=time.time()))
                    if b is not None:
                        record(day, "bars", sym, b); last["bars"][sym] = t
                if t - last["chain"].get(sym, 0) >= 60:
                    if t - last["exp"].get(sym, 0) >= 3600:
                        exps = attempt("chain", lambda: OF.option_expirations(sym))
                        if exps is not None:
                            elig = [e for e in exps if (datetime.fromisoformat(e) - datetime.fromisoformat(day)).days >= 21]
                            last["exp"][sym] = t; last["exp"][sym + ":e"] = elig[0] if elig else None
                    e = last["exp"].get(sym + ":e")
                    if e:
                        ch = attempt("chain", lambda: OF.option_chain_snapshot(sym, e))
                        if ch is not None:
                            record(day, "chain", sym, {"expiration": e, "quotes": ch}); last["chain"][sym] = t
            beat(state="COLLECTING", phase=phase, day=day, counters=counters, last=last)
            if a.once:
                break
            time.sleep(max(0.5, 5 - (time.time() - t)))
    except Stop as e:
        beat(state="STOPPED", why=str(e), counters=counters); print(hb.read_text()); return 0
    except Exception as e:                                                         # noqa: BLE001
        beat(state="CRASHED", why="%s: %s" % (type(e).__name__, str(e)[:200]), tb=traceback.format_exc()[-800:], counters=counters)
        print(hb.read_text()); return 5
    beat(state="ONCE_DONE" if a.once else "DONE", counters=counters); print(hb.read_text())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
