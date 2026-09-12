"""READ-ONLY LIVE SMOKE for the options pilot twin (M2 §A).

    1. print the LiveGate status (switch + credential PRESENCE, never values)
    2. fetch SPY 1-minute bars (Alpaca, last completed regular window) and the latest NBBO
    3. fetch option expirations and the chain snapshot for the nearest >= 21 DTE expiration (ThetaData, local :25503)
    4. ingest through BarStore, compose one OPTIONS_TWIN_STATE_V0 snapshot, run the frozen artifact adapter ONCE,
       and write everything to the OUTPUT DIRECTORY YOU NAME (never the live options ledger), labelled
       data_provenance=LIVE_FEED, evidence_class=SMOKE_READ_ONLY
    5. place no order, write no pilot ledger record, start no service

Gates (all must hold or the script exits 3 before any network access):
    --authorization-file PATH   a file the OPERATOR creates containing the literal line
                                OPTIONS_PILOT_LIVE_SMOKE_AUTHORIZED <YYYY-MM-DD> [note]
    APEX_PILOT_LIVE_DATA=ENABLED in the environment
    Alpaca key id + secret present in the existing secret backend (apex.intraday.options_feed.SECRETS)
The HTTP client is the repository's existing one (apex.intraday.options_feed._get); the feed functions are the
ones the legacy session already used, so this smoke exercises the SAME endpoints with receipt clocks recorded."""
from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apex.intraday import options_feed as OF                                     # noqa: E402
from apex.intraday.sessions import classify                                      # noqa: E402
from apex.pulse_options.ingest import BarStore                                   # noqa: E402
from apex.pulse_options.inference import default_artifact                       # noqa: E402
from apex.pulse_options.providers import ALPACA, THETA, LIVE_SWITCH, LiveGate, ThetaChainAdapter, load_bars   # noqa: E402
from apex.pulse_options.snapshot import compose                                  # noqa: E402

TOKEN = "OPTIONS_PILOT_LIVE_SMOKE_AUTHORIZED"


def plan(symbol: str, minutes: int) -> dict:
    now = datetime.now(timezone.utc)
    return {"symbol": symbol, "minutes": minutes,
            "requests": [
                {"purpose": "underlying 1-minute bars", "method": "GET",
                 "url": "%s/stocks/%s/bars?timeframe=1Min&start=<window>&end=<window>&limit=10000&feed=sip" % (ALPACA, symbol)},
                {"purpose": "underlying NBBO", "method": "GET", "url": "%s/stocks/%s/quotes/latest?feed=sip" % (ALPACA, symbol)},
                {"purpose": "option expirations", "method": "GET", "url": "%s/option/list/expirations?symbol=%s" % (THETA, symbol)},
                {"purpose": "chain snapshot (nearest >= 21 DTE)", "method": "GET", "url": "%s/option/snapshot/quote?symbol=%s&expiration=<YYYY-MM-DD>" % (THETA, symbol)}],
            "writes": ["<out_dir>/smoke_<utc>.json (bars counters, snapshot, one forecast record, gate status)"],
            "does_not": ["write the pilot or live options ledger", "send orders", "start services", "store credential values"],
            "planned_at_utc": now.isoformat()}


def _last_regular_window(now: datetime, minutes: int) -> tuple:
    """If the market is open: [now - minutes, now]. Otherwise the last `minutes` of the most recent regular session."""
    if classify(now).value == "REGULAR":
        return now - timedelta(minutes=minutes), now
    d = now
    for _ in range(7):
        probe = d.replace(hour=19, minute=30, second=0, microsecond=0)              # 15:30 ET (EDT) is inside any regular session
        if probe > now:
            probe -= timedelta(days=1)
        if classify(probe).value == "REGULAR":
            end = probe.replace(hour=20, minute=0) if classify(probe.replace(hour=19, minute=59)).value == "REGULAR" else probe
            return end - timedelta(minutes=minutes), end
        d -= timedelta(days=1)
    raise RuntimeError("NO_REGULAR_SESSION_FOUND")


def execute(symbol: str, minutes: int, out_dir: Path, auth_line: str) -> dict:
    gate = LiveGate(secret_fn=OF._secret)
    rec = {"kind": "live_smoke_read_only", "evidence_class": "SMOKE_READ_ONLY", "data_provenance": "LIVE_FEED", "symbol": symbol,
           "authorization": auth_line.strip(), "gate": gate.status(), "started_utc": datetime.now(timezone.utc).isoformat(), "steps": []}
    def step(name, fn):
        t0 = time.time()
        try:
            out = fn()
            rec["steps"].append({"step": name, "ok": True, "receipt_epoch": time.time(), "elapsed_s": round(time.time() - t0, 3)})
            return out
        except Exception as e:                                                    # noqa: BLE001
            rec["steps"].append({"step": name, "ok": False, "error": "%s: %s" % (type(e).__name__, str(e)[:300]), "receipt_epoch": time.time()})
            raise
    now = datetime.now(timezone.utc)
    start, end = _last_regular_window(now, minutes)
    rec["bar_window_utc"] = [start.isoformat(), end.isoformat()]
    try:
        raw_bars = step("alpaca_bars", lambda: OF.underlying_bars(symbol, start, end))
        t_bars = rec["steps"][-1]["receipt_epoch"]
        st = BarStore(symbol, source="ALPACA_DATA_V2")
        pb = [{"event_time": datetime.fromisoformat(b["t"].replace("Z", "+00:00")).timestamp(), "open": b["o"], "high": b["h"], "low": b["l"],
               "close": b["c"], "volume": b["v"], "trades": b.get("n"), "vwap": b.get("vw"), "receipt_time": t_bars, "publication_time": None} for b in raw_bars]
        rec["bars"] = {"n_raw": len(raw_bars), "first": raw_bars[0]["t"] if raw_bars else None, "last": raw_bars[-1]["t"] if raw_bars else None,
                       "ingest": load_bars(st, pb)}
        try:
            nbbo = step("alpaca_nbbo", lambda: OF.underlying_nbbo(symbol))
            t_nb = rec["steps"][-1]["receipt_epoch"]
            book = {"bid": nbbo["bid"], "ask": nbbo["ask"], "bid_size": nbbo.get("bid_size"), "ask_size": nbbo.get("ask_size"), "as_of": t_nb, "available": t_nb, "source": "ALPACA_DATA_V2:sip"}
            rec["nbbo"] = {k: nbbo.get(k) for k in ("bid", "ask", "bid_size", "ask_size", "timestamp")} if isinstance(nbbo, dict) else str(nbbo)[:200]
        except Exception:                                                          # noqa: BLE001
            book = None
        exps = step("theta_expirations", lambda: OF.option_expirations(symbol))
        today = now.strftime("%Y-%m-%d")
        elig = [e for e in exps if (datetime.fromisoformat(e) - datetime.fromisoformat(today)).days >= 21]
        rec["expirations"] = {"n": len(exps), "nearest_ge_21dte": elig[0] if elig else None}
        chain = step("theta_chain", lambda: OF.option_chain_snapshot(symbol, elig[0])) if elig else []
        t_ch = rec["steps"][-1]["receipt_epoch"]
        conv = ThetaChainAdapter.et_naive_to_epoch
        ages = []
        for q in chain:
            try:
                ages.append(t_ch - conv(str(q["timestamp"])))
            except Exception:                                                      # noqa: BLE001
                pass
        rec["chain"] = {"n_quotes": len(chain), "fields": sorted(chain[0].keys()) if chain else [], "sample": chain[0] if chain else None,
                        "quote_age_s_at_receipt": {"min": min(ages) if ages else None, "max": max(ages) if ages else None, "n": len(ages)},
                        "timestamp_convention": "provider ET-naive wall clock localized to America/New_York (recorded)"}
        as_of = max([b["available"] for b in st.bars_available_by(t_bars + 1)] + [t_bars]) + 0.5
        snap = compose(symbol=symbol, as_of=as_of, bars=st.bars_available_by(as_of), source="ALPACA_DATA_V2", book=book if book and book["available"] <= as_of else None,
                       chain_meta={"quote_count": len(chain), "expirations": elig[:3], "as_of": t_ch, "available": t_ch, "source": "THETADATA_V3"} if chain and t_ch <= as_of else None)
        rec["snapshot"] = {"as_of_utc": snap["as_of_utc"], "state_hash": snap["state_hash"], "quality_census": snap["quality_census"], "missingness": snap["missingness"],
                           "fields": {k: {kk: v[kk] for kk in ("value", "quality") if kk in v} for k, v in snap["fields"].items()}}
        try:
            fc = default_artifact().forecast(snap, created_epoch=as_of + 0.1, direction_signal=None)
            fc["evidence_class"] = "SMOKE_READ_ONLY"; fc["data_provenance"] = "LIVE_FEED"
            rec["forecast"] = fc
        except Exception as e:                                                     # noqa: BLE001
            rec["forecast"] = {"refused": "%s: %s" % (type(e).__name__, str(e)[:200])}
        rec["result"] = "COMPLETED"
    except Exception as e:                                                         # noqa: BLE001
        rec["result"] = "STOPPED: %s: %s" % (type(e).__name__, str(e)[:200])
        rec["traceback_tail"] = traceback.format_exc()[-600:]
    rec["finished_utc"] = datetime.now(timezone.utc).isoformat()
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / ("smoke_%s.json" % datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    p.write_text(json.dumps(rec, indent=1, default=str))
    rec["written"] = str(p)
    return rec


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="SPY")
    ap.add_argument("--minutes", type=int, default=90)
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--authorization-file", default=None)
    ap.add_argument("--dry-plan", action="store_true", help="print the exact requests; contact nothing")
    ap.add_argument("--execute", action="store_true", help="requires every gate")
    a = ap.parse_args(argv)
    p = plan(a.symbol, a.minutes)
    if a.dry_plan or not a.execute:
        print(json.dumps({"mode": "DRY_PLAN", **p}, indent=1))
        return 0
    gate = LiveGate(secret_fn=OF._secret)
    st = gate.status()
    auth_line = None
    if a.authorization_file and Path(a.authorization_file).exists():
        auth_line = next((line for line in Path(a.authorization_file).read_text().splitlines() if line.strip().startswith(TOKEN)), None)
    if not (auth_line and st["enabled"] and a.out_dir):
        print(json.dumps({"mode": "REFUSED", "authorization_file_ok": bool(auth_line), "gate": st, "out_dir": a.out_dir,
                          "why": "operator authorization file, %s=ENABLED, credentials and --out-dir are all required" % LIVE_SWITCH}, indent=1))
        return 3
    rec = execute(a.symbol, a.minutes, Path(a.out_dir), auth_line)
    print(json.dumps({k: rec.get(k) for k in ("result", "gate", "bar_window_utc", "bars", "nbbo", "expirations", "chain", "snapshot", "forecast", "written")}, indent=1, default=str))
    return 0 if rec.get("result") == "COMPLETED" else 4


if __name__ == "__main__":
    raise SystemExit(main())
