#!/usr/bin/env python
"""BTC-L2 RAW-STATE CHARACTERIZATION + STREAM CONTINUITY REPORT.

Operator law: raw-state characterization ONLY -- no spread here is
"arbitrage" or "basis"; those words belong to BTC-L3, which is
NOT_AUTHORIZED. Consumes the derivatives ledger THROUGH the lineage-
eligibility gate (pre-lineage forensic rows never enter statistics).

    python scripts/btc_l2_report.py

Writes results/commissioning/btc_l2_interim_report.json and prints it.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from apex.btc_sleeve.lineage_eligibility import (  # noqa: E402
    eligible_rows, exclusion_report)

LEDGER = Path("results/btc/derivatives_ledger.jsonl")
WS_TRADES = Path("results/btc/ws_trades_ledger.jsonl")
WS_BOOK = Path("results/btc/ws_book_ledger.jsonl")
WS_HEALTH = Path("results/btc/ws_health.json")
HOST_HB = Path("results/host/host_heartbeat.json")
OUT = Path("results/commissioning/btc_l2_interim_report.json")

SPREADS = ("bitnomial_LAST_TRADE_vs_coinbase_spot",
           "bitnomial_LAST_TRADE_vs_deribit_mark",
           "deribit_mark_vs_coinbase_spot",
           "deribit_mark_vs_deribit_index")


def _stats(vals: list) -> dict | None:
    if not vals:
        return None
    import numpy as np
    a = np.array(sorted(vals))
    q = lambda p: float(np.quantile(a, p))  # noqa: E731
    return {"n": len(vals), "median": q(0.5),
            "p10": q(0.10), "p90": q(0.90),
            "p01": q(0.01), "p99": q(0.99),
            "max_abs": float(max(abs(a[0]), abs(a[-1])))}


def _jsonl(path: Path) -> list:
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text().splitlines()
            if x.strip()]


def build_report() -> dict:
    import pandas as pd
    rep = {"kind": "btc_l2_interim_report",
           "as_of": str(pd.Timestamp.now(tz="UTC")),
           "characterization_law": "raw-state characterization only; "
                                   "'basis'/'arbitrage' are BTC-L3 "
                                   "words and BTC-L3 is NOT_AUTHORIZED",
           "decision_power": "NONE"}

    # ---- lineage gate first
    rep["lineage_exclusion"] = exclusion_report(LEDGER)

    # ---- cross-venue spread characterization (eligible rows only)
    spreads = {k: [] for k in SPREADS}
    ages, gate_refusals, times = [], 0, []
    settled_marks = {}
    for row, _v in eligible_rows(LEDGER, purpose="canonical"):
        times.append(row.get("known_from"))
        rec = row.get("cross_venue_reconciliation_same_poll") or {}
        for k in SPREADS:
            if k in rec:
                spreads[k].append(rec[k])
        if "bitnomial_last_trade_age_s" in rec:
            ages.append(rec["bitnomial_last_trade_age_s"])
            if not rec.get("bitnomial_last_trade_gate",
                           {}).get("eligible", True):
                gate_refusals += 1
        fh = (row["venues"].get("BITNOMIAL") or {}).get(
            "funding_history") or {}
        for iv in fh.get("intervals", []):
            key = iv.get("interval_end")
            if key and iv.get("mark_price", {}).get("canonical_value"):
                settled_marks[key] = {
                    "PERP_MARK_MINUS_INDEX_settled_interval": round(
                        iv["mark_price"]["canonical_value"] /
                        iv["price_index"]["canonical_value"] - 1.0, 6)
                    if iv.get("price_index", {}).get("canonical_value")
                    else None,
                    "funding_rate_per_interval":
                        iv.get("funding_rate_per_interval")}
    rep["cross_venue_spreads"] = {k: _stats(v)
                                  for k, v in spreads.items()}
    rep["cross_venue_spreads_note"] = (
        "LAST_TRADE spreads include the 2026-08-21 pre-stale-gate epoch"
        " (lineage-correct but not yet age-gated); rows after the gate "
        "only contribute when the trade was fresh under the "
        "predeclared 60s policy")
    rep["bitnomial_last_trade_age_s"] = _stats(ages)
    rep["stale_gate_refusals"] = gate_refusals
    rep["funding_settled_intervals"] = dict(
        sorted(settled_marks.items())[-6:])

    # ---- poll-stream continuity (eligible window only)
    if len(times) >= 2:
        ts = pd.to_datetime(pd.Series(times))
        dt = ts.diff().dt.total_seconds().dropna()
        rep["poller_continuity"] = {
            "polls": len(times), "expected_cadence_s": 15.0,
            "observed_median_cadence_s": float(dt.median()),
            "gaps_over_60s": int((dt > 60).sum()),
            "max_gap_s": float(dt.max()),
            "note": "poll frequency != source update frequency (law)"}

    # ---- WS continuity
    if WS_HEALTH.exists():
        h = json.loads(WS_HEALTH.read_text())
        rep["ws_bitnomial"] = {
            "as_of": h.get("as_of"), "uptime_s": h.get("uptime_s"),
            "price_unit": h.get("price_unit"),
            "book_quality": h.get("book_quality"),
            "book_top": h.get("book_top"),
            "book_continuity": h.get("book_continuity"),
            "counts": h.get("counts"),
            "reconnects_recent": h.get("reconnects")}
    trades = [r for r in _jsonl(WS_TRADES) if r.get("kind") == "ws_trade"]
    rep["ws_trades_persisted"] = len(trades)
    tops = [r for r in _jsonl(WS_BOOK)
            if r.get("kind") == "ws_book_top_sample"]
    rep["ws_book_top_samples"] = len(tops)
    if tops:
        mids = [t["book_mid_usd"] for t in tops if t.get("book_mid_usd")]
        sprd = [t["spread_raw"] * 5 for t in tops
                if t.get("spread_raw") is not None]
        rep["ws_book_mid_usd_latest"] = mids[-1] if mids else None
        rep["ws_book_spread_usd"] = _stats(sprd)

    # ---- host
    if HOST_HB.exists():
        hb = json.loads(HOST_HB.read_text())
        rep["host"] = {"sleep_incidents":
                       hb.get("sleep_incidents_since_start"),
                       "as_of": hb.get("as_of")}

    rep["liquidations"] = "NOT_AVAILABLE (no legitimate source "\
                          "commissioned; no inference from large trades)"
    return rep


def main() -> int:
    rep = build_report()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rep, indent=1))
    print(json.dumps(rep, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
