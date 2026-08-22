#!/usr/bin/env python
"""WORLD LAB -- BTC HISTORICAL ACQUISITION (operator-authorized
2026-08-22 during the BTC-L2 soak).

ALLOWED: download, inventory, normalize, validate semantics, build the
immutable historical store. FORBIDDEN: strategies, models, setups,
thresholds, anything selected from future outcomes.

VENUE FACTS STAY VENUE FACTS -- one file per venue+stream, each row
stamped with venue/instrument/source; no fictional universal exchange.
Raw files are IMMUTABLE once written (acquisition refuses to overwrite;
re-acquisition writes a new versioned file).

Semantics enforced at ingest (same laws as live BTC-L2):
  * Bitnomial funding-rates: price_index/mark_price in TICKS -> both
    raw and canonical USD stored, spec provenance attached.
  * Bitnomial charts: USD ALREADY -- conversion NONE (the 5x
    fabrication law is regression-tested elsewhere).
  * Deribit funding: interest_8h at hourly timestamps -- Deribit's own
    semantics, preserved verbatim.

decision_power: NONE_WORLD_LAB.
"""
from __future__ import annotations

import json
import ssl
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path("results/world_lab/raw/btc")
CTX = ssl.create_default_context(cafile="/etc/ssl/cert.pem")
BITN = "https://bitnomial.com/exchange/api/v1"


def _get(url: str) -> dict | list:
    req = urllib.request.Request(url, headers={
        "User-Agent": "apex-world-lab-acquisition"})
    with urllib.request.urlopen(req, context=CTX, timeout=30) as r:
        return json.loads(r.read())


def _store(venue: str, stream: str, rows: list, meta: dict) -> Path:
    """Immutable write: refuse to overwrite an existing raw file."""
    import pandas as pd
    d = ROOT / venue
    d.mkdir(parents=True, exist_ok=True)
    out = d / f"{stream}.jsonl"
    if out.exists():
        out = d / f"{stream}.v{int(time.time())}.jsonl"
    with open(out, "w") as f:
        for r in rows:
            f.write(json.dumps(r, sort_keys=True) + "\n")
    manifest = {"kind": "world_lab_raw_manifest", "venue": venue,
                "stream": stream, "rows": len(rows),
                "acquisition_time": str(pd.Timestamp.now(tz="UTC")),
                "immutability": "RAW_IMMUTABLE -- never rewritten; "
                                "re-acquisition creates a new version",
                **meta}
    (d / f"{stream}.manifest.json").write_text(
        json.dumps(manifest, indent=1))
    print(f"  stored {out} rows={len(rows)}")
    return out


def acquire_bitnomial() -> None:
    print("BITNOMIAL (product 5614 PBTCUCZ50 + predecessor products)")
    spec = _get(f"{BITN}/prod/product/spec/5614")
    inc = spec["price_increment"]

    # -- funding: full history via cursor pagination (settled 8h
    #    intervals; price_index/mark_price in TICKS)
    rows, cursor, pages = [], None, 0
    while pages < 200:
        q = {"base_symbol": "BTCUC", "limit": 100, "order": "asc"}
        if cursor:
            # the API returns the cursor ALREADY url-encoded; unquote
            # before urlencode or the %3D double-encodes into a 400
            q["cursor"] = urllib.parse.unquote(cursor)
        d = _get(f"{BITN}/funding-rates/?" + urllib.parse.urlencode(q))
        batch = d.get("data", [])
        for r in batch:
            rows.append({
                "venue": "BITNOMIAL", "source": "/funding-rates/",
                "product_id": r.get("product_id"),
                "interval_start": r.get("interval_start"),
                "interval_end": r.get("interval_end"),
                "funding_rate_per_interval": r.get("funding_rate"),
                "interest_rate": r.get("interest_rate"),
                "price_index_ticks": r.get("price_index"),
                "price_index_usd": (r.get("price_index") or 0) * inc
                or None,
                "mark_price_ticks": r.get("mark_price"),
                "mark_price_usd": (r.get("mark_price") or 0) * inc
                or None,
                "price_unit_law": "TICKS x increment "
                                  f"{inc} (spec 5614)",
                "funding_semantics": "ACTUAL_SETTLED_PER_8H_INTERVAL"})
        nxt = (d.get("pagination") or {}).get("cursor")
        pages += 1
        if not batch or not nxt or nxt == cursor:
            break
        cursor = nxt
        time.sleep(0.3)
    _store("bitnomial", "funding_8h_settled", rows,
           {"source_url": f"{BITN}/funding-rates/?base_symbol=BTCUC",
            "coverage": f"{rows[0]['interval_start']} -> "
                        f"{rows[-1]['interval_end']}" if rows else "EMPTY",
            "spec_provenance": {"product_id": 5614,
                                "symbol": spec.get("symbol"),
                                "price_increment": inc}})

    # -- charts price: daily OHLC+settlement, USD ALREADY. NOTE the
    #    THIRD distinct mount discovered 2026-08-22:
    #    /exchange/api/web/ (prod data = /api/v1/prod/, funding =
    #    /api/v1/, charts = /api/web/) -- resolved by probe, recorded
    charts = "https://bitnomial.com/exchange/api/web"
    d = _get(f"{charts}/charts/price/5614")
    price_rows = [dict(r, venue="BITNOMIAL",
                       source="/web/charts/price/5614",
                       price_unit_law="USD_ALREADY -- conversion NONE")
                  for r in (d if isinstance(d, list) else
                            d.get("data", []))]
    _store("bitnomial", "charts_price_daily", price_rows,
           {"source_url": f"{charts}/charts/price/5614",
            "units": "USD decimal strings; volume in contracts"})

    # -- charts voi: daily volume + OI (contracts + cents notional)
    d = _get(f"{charts}/charts/voi?product_id=5614")
    voi_rows = [dict(r, venue="BITNOMIAL", source="/web/charts/voi",
                     oi_publication="OI_DAILY_PUBLISHED",
                     notional_unit_law="CENTS -- divide by 100 for USD")
                for r in (d if isinstance(d, list) else
                          d.get("data", []))]
    _store("bitnomial", "charts_voi_daily", voi_rows,
           {"source_url": f"{charts}/charts/voi?product_id=5614"})


def acquire_deribit() -> None:
    print("DERIBIT (BTC-PERPETUAL)")
    base = "https://www.deribit.com/api/v2/public"
    # -- funding: 8h rates reconstructed from hourly interest via
    #    get_funding_rate_history (Deribit returns interest_8h per hour)
    rows, end_ms = [], int(time.time() * 1000)
    start_ms = 1546300800000            # 2019-01-01, pre-history safe
    cur = start_ms
    while cur < end_ms:
        nxt = min(cur + 30 * 86400_000, end_ms)
        d = _get(f"{base}/get_funding_rate_history?"
                 f"instrument_name=BTC-PERPETUAL&start_timestamp={cur}"
                 f"&end_timestamp={nxt}")
        for r in d.get("result", []):
            rows.append({"venue": "DERIBIT",
                         "source": "get_funding_rate_history",
                         "timestamp_ms": r.get("timestamp"),
                         "interest_8h": r.get("interest_8h"),
                         "interest_1h": r.get("interest_1h"),
                         "index_price": r.get("index_price"),
                         "prev_index_price": r.get("prev_index_price"),
                         "funding_semantics":
                             "DERIBIT_NATIVE_HOURLY_RECORD_8H_RATE"})
        cur = nxt
        time.sleep(0.25)
    _store("deribit", "funding_hourly", rows,
           {"source_url": f"{base}/get_funding_rate_history",
            "coverage_ms": [start_ms, end_ms]})

    # -- daily bars (mark-based chart data, Deribit's own series)
    d = _get(f"{base}/get_tradingview_chart_data?"
             f"instrument_name=BTC-PERPETUAL&resolution=1D"
             f"&start_timestamp={start_ms}&end_timestamp={end_ms}")
    r = d.get("result", {})
    bar_rows = [{"venue": "DERIBIT",
                 "source": "get_tradingview_chart_data 1D",
                 "timestamp_ms": t, "open": o, "high": h, "low": lo,
                 "close": c, "volume": v,
                 "series_semantics": "DERIBIT_CHART_SERIES_USD"}
                for t, o, h, lo, c, v in zip(
                    r.get("ticks", []), r.get("open", []),
                    r.get("high", []), r.get("low", []),
                    r.get("close", []), r.get("volume", []))]
    _store("deribit", "perp_bars_daily", bar_rows,
           {"source_url": f"{base}/get_tradingview_chart_data"})


def main() -> int:
    ROOT.mkdir(parents=True, exist_ok=True)
    acquire_bitnomial()
    acquire_deribit()
    inv = {p.parent.name + "/" + p.name: p.stat().st_size
           for p in sorted(ROOT.rglob("*.jsonl"))}
    print(json.dumps({"inventory": inv}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
