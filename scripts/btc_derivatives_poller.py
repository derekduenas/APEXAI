#!/usr/bin/env python
"""BTC-L1 DERIVATIVES CAPTURE -- the first real perp observations.

Commissioning law: BTC_PERPS_DERIVATIVES stays NOT_AVAILABLE until real
perpetual-specific observations FLOW (probes are not capture). This
poller makes funding / open interest / mark / index / basis flow, with
full per-field provenance, from the venues that are actually reachable
from this host (probed 2026-08-21: Deribit REACHABLE, Kraken Futures
REACHABLE, OKX REACHABLE; Binance HTTP 451 and Bybit HTTP 403 --
geo-blocked, recorded honestly, never fabricated).

VENUE FACTS STAY VENUE FACTS. Deribit's funding is Deribit's funding;
OKX's is OKX's. Nothing here merges venues into a fictional universal
BTC market -- cross-venue divergence is itself a first-class
observation.

Poll cadence 15s (these are slow-moving derivatives facts; trades/book
need WebSocket streams -- declared future BTC-L1 work, not faked here).

    python scripts/btc_derivatives_poller.py [--minutes 1440]

Writes: results/btc/derivatives_ledger.jsonl   (hash-chained)
        results/btc/derivatives_health.json

decision_power: NONE -- a sensor.
"""
from __future__ import annotations

import argparse
import json
import ssl
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

_S = Path(__file__).resolve().parent
sys.path.insert(0, str(_S.parent))

LEDGER = Path("results/btc/derivatives_ledger.jsonl")
HEALTH = Path("results/btc/derivatives_health.json")
POLL_S = 15.0
CTX = ssl.create_default_context(cafile="/etc/ssl/cert.pem")

VENUES = {
    "BITNOMIAL": {
        "instrument": "PBTCUCZ50 (product_id 5614)",
        "url": ("https://bitnomial.com/exchange/api/v1/prod"
                "/product/data/5614"),
        "spec_url": ("https://bitnomial.com/exchange/api/v1/prod"
                     "/product/spec/5614"),
        # RESOLVED 2026-08-21: funding lives at /exchange/api/v1/ --
        # NOT under /prod/ (the mount mismatch was the 404 mystery).
        # Publishes SETTLED 8h intervals only; price_index/mark_price
        # in TICKS.
        "funding_url": ("https://bitnomial.com/exchange/api/v1"
                        "/funding-rates/?product_id=5614&limit=3"
                        "&order=desc"),
        "semantics": "PRIMARY VENUE (operator ruling 2026-08-21): "
                     "US-regulated perpetual, 0.01 BTC, 8h funding, "
                     "CASH SETTLED (live spec 5614, verified "
                     "2026-08-21 -- the expired PBUC series was "
                     "deliverable; old specs never contaminate current "
                     "metadata). Product Data prices are TICKS; "
                     "converted via the live spec's price_increment "
                     "(BITNOMIAL_PRICE_UNIT_ISSUE=RESOLVED_BY_SPEC). "
                     "OI is DAILY_PUBLISHED per docs + measurement -- "
                     "polled 15s but NOT intraday information.",
    },
    "DERIBIT": {
        "instrument": "BTC-PERPETUAL",
        "url": ("https://www.deribit.com/api/v2/public/ticker"
                "?instrument_name=BTC-PERPETUAL"),
        "semantics": "USD-margined inverse perpetual; funding continuous "
                     "(current_funding = 8h-equivalent rate); OI in USD",
    },
    "KRAKEN_FUTURES": {
        "instrument": "PI_XBTUSD",
        "url": "https://futures.kraken.com/derivatives/api/v3/tickers",
        "semantics": "inverse perpetual; fundingRate per its own docs; "
                     "openInterest in contracts (USD)",
    },
    "OKX": {
        "instrument": "BTC-USDT-SWAP",
        "url": ("https://www.okx.com/api/v5/public/funding-rate"
                "?instId=BTC-USDT-SWAP"),
        "semantics": "USDT-margined linear swap; 8h funding cycle",
    },
    "COINBASE_SPOT": {
        "instrument": "BTC-USD",
        "url": "https://api.exchange.coinbase.com/products/BTC-USD/ticker",
        "semantics": "spot reference for perp/spot basis",
    },
}

UNREACHABLE = {"BINANCE": "HTTP 451 (geo-blocked, probed 2026-08-21)",
               "BYBIT": "HTTP 403 (geo-blocked, probed 2026-08-21)"}

# the ACTIVE product's live spec, fetched once at startup -- provenance
# for every tick conversion; never a hardcoded increment
_BITNOMIAL_SPEC: dict | None = None
_BITNOMIAL_SPEC_FETCHED_AT: str | None = None


def _fetch_bitnomial_spec() -> None:
    global _BITNOMIAL_SPEC, _BITNOMIAL_SPEC_FETCHED_AT
    import pandas as pd
    try:
        _BITNOMIAL_SPEC = _get(VENUES["BITNOMIAL"]["spec_url"])
        _BITNOMIAL_SPEC_FETCHED_AT = str(pd.Timestamp.now(tz="UTC"))
        print(f"BITNOMIAL spec: {_BITNOMIAL_SPEC.get('symbol')} "
              f"increment={_BITNOMIAL_SPEC.get('price_increment')} "
              f"settlement={_BITNOMIAL_SPEC.get('settlement_method')}",
              flush=True)
    except Exception as e:                              # noqa: BLE001
        print(f"BITNOMIAL spec fetch failed: {type(e).__name__} -- "
              f"tick conversion will refuse", flush=True)


def _get(url: str) -> dict | list:
    req = urllib.request.Request(url, headers={
        "User-Agent": "apex-btc-l1-commissioning"})
    with urllib.request.urlopen(req, context=CTX, timeout=10) as r:
        return json.loads(r.read())


# funding is published 3x/day -- fetch every 20th poll (5 min), cache
# between; polling it at 15s would be noise, not information
_FUNDING_CACHE: dict = {"n": -1, "value": None}


def _bitnomial_funding(cfg: dict, spec: dict) -> dict | None:
    """Settled 8h funding intervals with full lineage. price_index and
    mark_price arrive in TICKS (verified live 2026-08-21) and convert
    via the live spec. ACTUAL settled funding -- never an estimate;
    the in-progress interval is honestly absent upstream."""
    from apex.btc_sleeve.semantics import (
        convert_bitnomial_product_data_price)
    _FUNDING_CACHE["n"] += 1
    if _FUNDING_CACHE["n"] % 20 != 0:
        return _FUNDING_CACHE["value"]
    try:
        d = _get(cfg["funding_url"])
    except (urllib.error.URLError, OSError, ValueError) as e:
        return {"status": "FETCH_FAILED", "error": type(e).__name__}
    intervals = []
    for row in d.get("data", [])[:2]:
        intervals.append({
            "interval_start": row.get("interval_start"),
            "interval_end": row.get("interval_end"),
            "funding_rate_per_interval": row.get("funding_rate"),
            "interest_rate": row.get("interest_rate"),
            "price_index": dict(
                convert_bitnomial_product_data_price(
                    row.get("price_index"), product_spec=spec),
                semantic_type="INDEX",
                endpoint="/funding-rates/"),
            "mark_price": dict(
                convert_bitnomial_product_data_price(
                    row.get("mark_price"), product_spec=spec),
                semantic_type="FUNDING_MARK",
                endpoint="/funding-rates/"),
        })
    out = {"status": "OK",
           "semantics": "ACTUAL_SETTLED_PER_8H_INTERVAL; published "
                        "after interval_end; ticks converted via live "
                        "spec; interval-anchored facts, NEVER live "
                        "spreads",
           "intervals": intervals}
    if intervals:
        pi = intervals[0]["price_index"]["canonical_value"]
        mk = intervals[0]["mark_price"]["canonical_value"]
        if pi and mk:
            out["perp_mark_minus_index_last_settled_interval"] = round(
                mk / pi - 1.0, 6)
    _FUNDING_CACHE["value"] = out
    return out


def _observe(venue: str, arrival: float) -> dict | None:
    """One venue's facts, with per-field honesty -- absent fields stay
    absent, never zero."""
    cfg = VENUES[venue]
    try:
        d = _get(cfg["url"])
    except (urllib.error.URLError, OSError, ValueError) as e:
        return {"venue": venue, "status": "FETCH_FAILED",
                "error": f"{type(e).__name__}"}
    obs = {"venue": venue, "instrument": cfg["instrument"],
           "source_semantics": cfg["semantics"], "status": "OK"}
    if venue == "DERIBIT":
        r = d.get("result", {})
        obs.update({"mark_price": r.get("mark_price"),
                    "index_price": r.get("index_price"),
                    "last_price": r.get("last_price"),
                    "best_bid": r.get("best_bid_price"),
                    "best_ask": r.get("best_ask_price"),
                    "funding_current": r.get("current_funding"),
                    "funding_8h": r.get("funding_8h"),
                    "open_interest": r.get("open_interest"),
                    "event_time_ms": r.get("timestamp")})
    elif venue == "BITNOMIAL":
        from apex.btc_sleeve.semantics import (
            VENUE_OI_SEMANTICS, convert_bitnomial_product_data_price)
        spec = _BITNOMIAL_SPEC or {}
        def _priced(field, semantic, ts_field=None):
            out = convert_bitnomial_product_data_price(
                d.get(field), product_spec=spec)
            out["endpoint"] = "/product/data/5614"
            out["field_name"] = field
            out["semantic_type"] = semantic
            out["last_update_time"] = (d.get(ts_field) if ts_field
                                       else None)
            return out
        obs.update({
            # LINEAGE LAW: the un-timestamped funding-interval value is
            # FUNDING_MARK and may never be compared to real-time
            # references; LAST_TRADE carries its own trade timestamp.
            "funding_mark": _priced("mark_price", "FUNDING_MARK"),
            "last_trade": _priced("last_price", "LAST_TRADE",
                                  "last_price_time"),
            "settlement": _priced("settlement_price", "SETTLEMENT",
                                  "settlement_time"),
            "open_interest": {"raw_value": d.get("open_interest"),
                              "unit": "CONTRACTS",
                              **VENUE_OI_SEMANTICS["BITNOMIAL"],
                              "poll_frequency_s": POLL_S},
            "funding_current": d.get("funding_rate"),
            "volume": d.get("volume"),
            "event_time_iso": d.get("last_price_time"),
            "funding_history": _bitnomial_funding(cfg, spec),
            "spec_provenance": {
                "symbol": spec.get("symbol"),
                "settlement_method": spec.get("settlement_method"),
                "price_increment": spec.get("price_increment"),
                "fetched_at": _BITNOMIAL_SPEC_FETCHED_AT}})
    elif venue == "KRAKEN_FUTURES":
        tick = next((t for t in d.get("tickers", [])
                     if t.get("symbol") == "PI_XBTUSD".lower()
                     or t.get("symbol") == "PI_XBTUSD"), None)
        if tick is None:
            return {"venue": venue, "status": "INSTRUMENT_ABSENT"}
        obs.update({"mark_price": tick.get("markPrice"),
                    "index_price": tick.get("indexPrice"),
                    "last_price": tick.get("last"),
                    "best_bid": tick.get("bid"),
                    "best_ask": tick.get("ask"),
                    "funding_current": tick.get("fundingRate"),
                    "open_interest": tick.get("openInterest"),
                    "event_time_iso": tick.get("lastTime")})
    elif venue == "OKX":
        row = (d.get("data") or [{}])[0]
        obs.update({"funding_current": row.get("fundingRate"),
                    "funding_next": row.get("nextFundingRate"),
                    "funding_time_ms": row.get("fundingTime"),
                    "event_time_ms": row.get("ts")})
    elif venue == "COINBASE_SPOT":
        obs.update({"last_price": d.get("price"),
                    "best_bid": d.get("bid"), "best_ask": d.get("ask"),
                    "volume_24h": d.get("volume"),
                    "event_time_iso": d.get("time")})
    obs["arrival_time_epoch"] = round(arrival, 3)
    return obs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=1440.0)
    a = ap.parse_args()
    from apex.governance.chain_ledger import chain_append
    import pandas as pd
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    t_end = time.time() + a.minutes * 60
    n_polls, n_ok, n_fail = 0, 0, 0
    print(f"BTC DERIVATIVES POLLER start venues={list(VENUES)} "
          f"unreachable={UNREACHABLE}", flush=True)
    _fetch_bitnomial_spec()
    while time.time() < t_end:
        arrival = time.time()
        now = pd.Timestamp.now(tz="UTC")
        rec = {"kind": "btc_derivatives_poll",
               "known_from": str(now), "venues": {}, "decision_power": "NONE"}
        for venue in VENUES:
            obs = _observe(venue, arrival)
            rec["venues"][venue] = obs
            if obs and obs.get("status") == "OK":
                n_ok += 1
            else:
                n_fail += 1
        # SAME-POLL cross-venue reconciliation, all in canonical USD
        try:
            dm = rec["venues"]["DERIBIT"].get("mark_price")
            sp = rec["venues"]["COINBASE_SPOT"].get("last_price")
            b = rec["venues"]["BITNOMIAL"]
            bn_last = (b.get("last_trade") or {}).get("canonical_value")
            bn_last_t = (b.get("last_trade") or {}).get("last_update_time")
            di = rec["venues"]["DERIBIT"].get("index_price")
            recon = {}
            if dm and sp:
                recon["deribit_mark_vs_coinbase_spot"] = round(
                    float(dm) / float(sp) - 1.0, 6)
            if dm and di:
                recon["deribit_mark_vs_deribit_index"] = round(
                    float(dm) / float(di) - 1.0, 6)
            # SEMANTIC LINEAGE LAW: only LAST_TRADE (with its own trade
            # timestamp and age) compares against real-time references;
            # FUNDING_MARK and SETTLEMENT never do.
            # STALE-LAST-TRADE LAW: a thin venue's last trade must not
            # masquerade as live basis -- age-gated by the predeclared
            # policy in semantics.py (never tuned from results).
            if bn_last and bn_last_t:
                from apex.btc_sleeve.semantics import (
                    last_trade_realtime_eligibility)
                age_s = (now - pd.Timestamp(bn_last_t)
                         ).total_seconds()
                gate = last_trade_realtime_eligibility(age_s)
                recon["bitnomial_last_trade_time"] = bn_last_t
                recon["bitnomial_last_trade_age_s"] = round(age_s, 1)
                recon["bitnomial_last_trade_gate"] = gate
                if gate["eligible"]:
                    if sp:
                        recon["bitnomial_LAST_TRADE_vs_coinbase_spot"] \
                            = round(float(bn_last) / float(sp) - 1.0, 6)
                    if dm:
                        recon["bitnomial_LAST_TRADE_vs_deribit_mark"] \
                            = round(float(bn_last) / float(dm) - 1.0, 6)
            rec["cross_venue_reconciliation_same_poll"] = recon
        except (TypeError, ValueError, KeyError):
            pass
        rec["unreachable_venues"] = UNREACHABLE
        chain_append(LEDGER, rec)
        n_polls += 1
        try:
            HEALTH.write_text(json.dumps({
                "kind": "btc_derivatives_health",
                "as_of": str(now), "polls": n_polls,
                "venue_reads_ok": n_ok, "venue_reads_failed": n_fail,
                "cadence_s": POLL_S,
                "streams_flowing": ["funding_live_estimates",
                                    "funding_settled_intervals",
                                    "open_interest", "mark", "index",
                                    "basis", "spot_reference"],
                "streams_missing": ["liquidations (NOT_AVAILABLE -- no "
                                    "legitimate source commissioned)"],
                "streams_elsewhere": ["perp_trades_ws + perp_book_ws: "
                                      "scripts/btc_ws_stream.py "
                                      "(com.apex.btc-ws)"],
                "decision_power": "NONE"}, indent=1))
        except OSError:
            pass
        if n_polls % 20 == 1:
            print(f"{now:%H:%M:%S} poll={n_polls} ok={n_ok} "
                  f"fail={n_fail}", flush=True)
        time.sleep(POLL_S)
    print("poller stopped (budget reached)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
