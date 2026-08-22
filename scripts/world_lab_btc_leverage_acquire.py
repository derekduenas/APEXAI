#!/usr/bin/env python
"""WORLD LAB -- BTC HISTORICAL LEVERAGE ACQUISITION.

Authorized 2026-08-22. Operates ONLY inside World Lab raw storage. It
touches no live daemon, no BTC-L0/L1/L2 code, no schema the soak uses.

THE PRIORITY-1 TARGET WAS INTRADAY OPEN INTEREST, and the audit's
"no historical intraday OI exists" conclusion turned out to be WRONG:

    KRAKEN FUTURES  /api/charts/v1/analytics/PI_XBTUSD/open-interest
                    hourly OI, paginated 2000 rows/call, back to
                    2023-07-22 (probed; earlier `since` returns empty)
    OKX             /api/v5/rubik/stat/contracts/open-interest-history
                    1H and 5m, but only ~100 rows retained (~4 days)

So multi-year hourly OI IS obtainable. Kraken is the OI spine; OKX is
a short-window cross-check, not a history source.

VENUE FACTS STAY VENUE FACTS. Kraken OI is Kraken's OI (PI_XBTUSD,
inverse perp, contracts = USD); Deribit's is Deribit's. Nothing here
averages venues, forward-fills a slow publication into a fast one, or
interpolates an unobserved value. Missing means UNKNOWN, never zero.

    python scripts/world_lab_btc_leverage_acquire.py

decision_power: NONE_WORLD_LAB.
"""
from __future__ import annotations

import json
import ssl
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path("results/world_lab/raw/btc")
CTX = ssl.create_default_context(cafile="/etc/ssl/cert.pem")

KRAKEN_OI = ("https://futures.kraken.com/api/charts/v1/analytics/"
             "PI_XBTUSD/open-interest?interval={iv}&since={since}")
KRAKEN_EARLIEST = 1690000000          # probed 2026-08-22
DERIBIT = "https://www.deribit.com/api/v2/public"
COINBASE = "https://api.exchange.coinbase.com/products/BTC-USD/candles"


def _get(url: str, tries: int = 3):
    for i in range(tries):
        try:
            r = urllib.request.Request(url, headers={
                "User-Agent": "apex-world-lab-acquisition"})
            with urllib.request.urlopen(r, context=CTX, timeout=30) as f:
                return json.loads(f.read())
        except Exception:                                # noqa: BLE001
            if i == tries - 1:
                raise
            time.sleep(2 * (i + 1))


def _store(venue: str, stream: str, rows: list, meta: dict) -> Path:
    import pandas as pd
    d = ROOT / venue
    d.mkdir(parents=True, exist_ok=True)
    out = d / f"{stream}.jsonl"
    if out.exists():
        out = d / f"{stream}.v{int(time.time())}.jsonl"
    with open(out, "w") as f:
        for r in rows:
            f.write(json.dumps(r, sort_keys=True) + "\n")
    (d / f"{stream}.manifest.json").write_text(json.dumps({
        "kind": "world_lab_raw_manifest", "venue": venue,
        "stream": stream, "rows": len(rows),
        "acquired_at": str(pd.Timestamp.now(tz="UTC")),
        "immutability": "RAW_IMMUTABLE -- never rewritten; "
                        "re-acquisition creates a new version",
        "decision_power": "NONE_WORLD_LAB", **meta}, indent=1))
    print(f"  stored {out.name}  rows={len(rows)}")
    return out


# ------------------------------------------------ KRAKEN: THE OI SPINE
def acquire_kraken_oi() -> dict:
    print("KRAKEN FUTURES PI_XBTUSD -- hourly open interest (the spine)")
    rows, since, pages = [], KRAKEN_EARLIEST, 0
    seen = set()
    while pages < 60:
        d = _get(KRAKEN_OI.format(iv=3600, since=since))
        res = d.get("result") or {}
        ts = res.get("timestamp") or []
        # SCHEMA (verified against the live response, not assumed):
        # result.data[i] is an OHLC QUADRUPLE OF STRINGS for hour i --
        # [open, high, low, close] of open interest, not a scalar. A
        # first pass stored the raw array as `value` and then compared
        # lists lexically; both the unit and the type were wrong.
        vals = res.get("data") or []
        if not ts:
            break
        for i, t in enumerate(ts):
            if t in seen:
                continue
            seen.add(t)
            q = vals[i] if i < len(vals) else None
            if not (isinstance(q, list) and len(q) == 4):
                continue                      # refuse an unknown shape
            o, h, lo, c = (float(x) for x in q)
            rows.append({
                "venue": "KRAKEN_FUTURES", "product": "PI_XBTUSD",
                "field": "open_interest",
                "event_time_s": t,
                "oi_open": o, "oi_high": h, "oi_low": lo, "oi_close": c,
                "value": c,          # canonical point value = hour close
                "native_units": "CONTRACTS_1USD",
                "canonical_units": "USD_NOTIONAL",
                "publication_cadence_s": 3600,
                "oi_class": "OI_DELAYED",
                "semantics": "inverse perp; 1 contract = 1 USD; "
                             "hourly analytics series"})
        pages += 1
        nxt = max(ts) + 3600
        if nxt <= since:
            break
        since = nxt
        if since > time.time():
            break
        time.sleep(0.3)
    rows.sort(key=lambda r: r["event_time_s"])
    import pandas as pd
    cov = ((str(pd.Timestamp(rows[0]["event_time_s"], unit="s", tz="UTC")),
            str(pd.Timestamp(rows[-1]["event_time_s"], unit="s", tz="UTC")))
           if rows else ("EMPTY", "EMPTY"))
    _store("kraken_futures", "open_interest_hourly", rows,
           {"source_url": KRAKEN_OI.format(iv=3600, since="<walked>"),
            "coverage": cov, "resolution_s": 3600,
            "note": "PRIORITY-1 TARGET. Earlier `since` values return "
                    "empty -- 2023-07-22 is the venue's own horizon, "
                    "not a truncation by us."})
    return {"rows": len(rows), "coverage": cov}


# ------------------------------------------------ DERIBIT
def acquire_deribit_intraday() -> dict:
    print("DERIBIT BTC-PERPETUAL -- intraday bars + DVOL")
    out = {}
    for res_name, res in (("1h", "60"), ("1m", "1")):
        rows = []
        end = int(time.time() * 1000)
        # 1m is heavy: take the most recent 90 days; 1h takes 3 years
        span_days = 90 if res_name == "1m" else 1100
        cur = end - span_days * 86400_000
        step = 5 * 86400_000 if res_name == "1m" else 120 * 86400_000
        while cur < end:
            nxt = min(cur + step, end)
            d = _get(f"{DERIBIT}/get_tradingview_chart_data?"
                     f"instrument_name=BTC-PERPETUAL&resolution={res}"
                     f"&start_timestamp={cur}&end_timestamp={nxt}")
            r = d.get("result", {})
            for t, o, h, lo, c, v in zip(
                    r.get("ticks", []), r.get("open", []),
                    r.get("high", []), r.get("low", []),
                    r.get("close", []), r.get("volume", [])):
                rows.append({"venue": "DERIBIT",
                             "product": "BTC-PERPETUAL",
                             "event_time_ms": t, "open": o, "high": h,
                             "low": lo, "close": c, "volume": v,
                             "resolution": res_name,
                             "native_units": "USD_PER_BTC",
                             "semantics": "inverse perp chart series"})
            cur = nxt
            time.sleep(0.2)
        rows.sort(key=lambda r: r["event_time_ms"])
        _store("deribit", f"perp_bars_{res_name}", rows,
               {"source_url": f"{DERIBIT}/get_tradingview_chart_data",
                "resolution": res_name, "span_days": span_days})
        out[res_name] = len(rows)

    # DVOL: Deribit's own implied-volatility index -- a genuine
    # volatility-regime memory for BTC, obtainable at 1h
    rows, end = [], int(time.time() * 1000)
    cur = end - 1100 * 86400_000
    while cur < end:
        nxt = min(cur + 120 * 86400_000, end)
        d = _get(f"{DERIBIT}/get_volatility_index_data?currency=BTC"
                 f"&start_timestamp={cur}&end_timestamp={nxt}"
                 f"&resolution=3600")
        for row in (d.get("result", {}) or {}).get("data", []):
            t, o, h, lo, c = row[:5]
            rows.append({"venue": "DERIBIT", "product": "DVOL_BTC",
                         "event_time_ms": t, "open": o, "high": h,
                         "low": lo, "close": c, "resolution": "1h",
                         "native_units": "ANNUALIZED_VOL_PCT",
                         "semantics": "Deribit implied volatility index"})
        cur = nxt
        time.sleep(0.2)
    rows.sort(key=lambda r: r["event_time_ms"])
    _store("deribit", "dvol_hourly", rows,
           {"source_url": f"{DERIBIT}/get_volatility_index_data",
            "resolution": "1h"})
    out["dvol"] = len(rows)
    return out


# ------------------------------------------------ COINBASE SPOT
def acquire_coinbase_spot() -> dict:
    print("COINBASE BTC-USD -- spot candles (spot truth)")
    rows, gran = [], 3600
    end = int(time.time())
    start = end - 1100 * 86400
    cur = start
    while cur < end:
        nxt = min(cur + 300 * gran, end)
        import datetime as dt
        d = _get(f"{COINBASE}?granularity={gran}"
                 f"&start={dt.datetime.utcfromtimestamp(cur).isoformat()}"
                 f"&end={dt.datetime.utcfromtimestamp(nxt).isoformat()}")
        for c in (d or []):
            t, lo, hi, op, cl, vol = c
            rows.append({"venue": "COINBASE", "product": "BTC-USD",
                         "event_time_s": t, "open": op, "high": hi,
                         "low": lo, "close": cl, "volume": vol,
                         "resolution": "1h",
                         "native_units": "USD_PER_BTC",
                         "semantics": "spot reference truth"})
        cur = nxt
        time.sleep(0.35)
    seen, dedup = set(), []
    for r in sorted(rows, key=lambda r: r["event_time_s"]):
        if r["event_time_s"] in seen:
            continue
        seen.add(r["event_time_s"])
        dedup.append(r)
    _store("coinbase", "spot_candles_hourly", dedup,
           {"source_url": COINBASE, "resolution": "1h"})
    return {"rows": len(dedup)}


def main() -> int:
    ROOT.mkdir(parents=True, exist_ok=True)
    summary = {"kraken_oi": acquire_kraken_oi(),
               "deribit": acquire_deribit_intraday(),
               "coinbase": acquire_coinbase_spot()}
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
