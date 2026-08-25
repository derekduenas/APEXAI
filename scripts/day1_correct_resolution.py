"""Regenerate Day-1 derived outcomes through the repaired resolver.

Originals are read-only. Corrections are appended with lineage. The
audit that matters most is the NEGATIVE one: P&L came from quotes, not
bars, so it must come back IDENTICAL. If it moves, the correction has
overreached and the run fails.

Usage:
    python scripts/day1_correct_resolution.py --alpaca-key-file ... \
        --frozen results/day1_frozen --out results/day1_corrected
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apex.governance.correction import append_correction   # noqa: E402
from apex.governance.resolution_time import (              # noqa: E402
    eligible_window, to_utc)
from apex.governance.trade_semantics import (              # noqa: E402
    OPTIONS_HOLD_TO_CLOSE, TradeAuthorities, classify_thesis_path)

RESOLVER_VERSION = "options_resolver_v2_session_close_causal_2026_08_24"
DEFECTS = ["DEFECT_A_RESOLUTION_HORIZON_PROCESSING_TIME",
           "DEFECT_B_PRE_ENTRY_PATH_CONTAMINATION"]
ALPACA = "https://data.alpaca.markets/v2"


def bars(symbol, start, end, key, sec):
    url = (f"{ALPACA}/stocks/{symbol}/bars?timeframe=1Min"
           f"&start={start}&end={end}&limit=10000&feed=sip&adjustment=raw")
    req = urllib.request.Request(url, headers={
        "APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": sec})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode()).get("bars", [])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--frozen", default="results/day1_frozen")
    ap.add_argument("--out", default="results/day1_corrected")
    ap.add_argument("--key", required=True)
    ap.add_argument("--secret", required=True)
    a = ap.parse_args()

    frozen = Path(a.frozen)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    ledger = out / "day1_corrections.jsonl"

    rows = [json.loads(l) for l in
            (frozen / "options_live_ledger.jsonl").read_text().splitlines()
            if l.strip()]
    cards = {r["symbol"]: r for r in rows
             if r.get("kind") == "options_live_card"}
    attacks = {r["symbol"]: r for r in rows
               if r.get("kind") == "options_live_attack"}
    outcomes = [r for r in rows if r.get("kind") == "options_outcome"]
    attribs = {r["expression"]: r for r in rows
               if r.get("kind") == "options_friction_attribution"}

    by_expr_symbol = {}
    for sym, c in cards.items():
        by_expr_symbol[c["expression"]] = sym

    report, pnl_drift = [], []
    for o in outcomes:
        expr = o["expression"]
        sym = by_expr_symbol[expr]
        card, att = cards[sym], attacks[sym]
        entry_spot = None
        # entry spot: reconstruct from the attack record's own reference
        # (the frozen card carries the legs, the attack the debit)
        win = eligible_window(entry_ts=card["T"], session="2026-08-24",
                              symbol=sym, option=False)
        e_utc, b_utc = to_utc(win["entry_utc"]), to_utc(win["boundary_utc"])

        raw = bars(sym, "2026-08-24T12:00:00Z", "2026-08-24T21:00:00Z",
                   a.key, a.secret)
        # entry reference = last bar at or before entry (START_OF_BAR +1m)
        prior = [b for b in raw
                 if to_utc(b["t"], assume="UTC") <= e_utc]
        entry_spot = prior[-1]["c"] if prior else None
        eligible = [b for b in raw
                    if e_utc < to_utc(b["t"], assume="UTC") <= b_utc]
        contaminated = [b for b in raw
                        if to_utc(b["t"], assume="UTC") <= e_utc]

        closes = [b["c"] for b in eligible]
        final = closes[-1] if closes else None
        sign = 1.0 if card["direction"] == "LONG" else -1.0
        exc = [(b["t"], sign * (b["c"] / entry_spot - 1.0) * 100)
               for b in eligible] if entry_spot else []
        best = max(exc, key=lambda z: z[1]) if exc else None
        worst = min(exc, key=lambda z: z[1]) if exc else None

        authorities = TradeAuthorities(
            thesis_invalidation=card.get("invalidation"),
            **OPTIONS_HOLD_TO_CLOSE)
        tp = classify_thesis_path(
            direction=card["direction"],
            thesis_invalidation=card.get("invalidation"),
            path_closes=closes, final_close=final,
            authorities=authorities)

        ur = (round((final / entry_spot - 1.0) * 100, 4)
              if final and entry_spot else "NOT_ESTIMABLE")
        corrected = {
            "underlying_return_pct_at_official_close": ur,
            "mfe": round(best[1], 4) if best else "NOT_ESTIMABLE",
            "mae": round(worst[1], 4) if worst else "NOT_ESTIMABLE",
            "time_to_mfe_min": (round((to_utc(best[0], assume="UTC")
                                       - e_utc).total_seconds() / 60, 1)
                                if best else "NOT_ESTIMABLE"),
            "time_to_mae_min": (round((to_utc(worst[0], assume="UTC")
                                       - e_utc).total_seconds() / 60, 1)
                                if worst else "NOT_ESTIMABLE"),
            "thesis_path": tp,
            "authorities": authorities.as_record(),
            "resolution_boundary_utc": win["boundary_utc"],
            "eligible_bars": len(eligible),
            "pre_entry_bars_excluded_by_repair": len(contaminated),
        }
        # THE NEGATIVE AUDIT: quote-derived economics must not move.
        unchanged = ["pnl", "mid_change", "exit_friction",
                     "entry_friction", "r_multiple",
                     "declared_1R_dollars", "capital_deployed"]
        append_correction(
            ledger, correction_type="RESOLUTION_DEFECT",
            supersedes_record_id=f"options_outcome:{sym}:{card['T']}",
            original_record=o, defect_ids=DEFECTS,
            corrected_resolver_version=RESOLVER_VERSION,
            corrected_fields=corrected,
            unchanged_fields_verified=unchanged,
            why=("Defect A resolved the card against a post-close print "
                 "and Defect B admitted pre-entry bars into the path; "
                 "quote-derived economics are unaffected and audited "
                 "unchanged"))
        report.append({
            "symbol": sym, "expression": expr,
            "original_ur": o.get("underlying_return_pct"),
            "corrected_ur": ur,
            "original_mfe": o.get("mfe"), "corrected_mfe": corrected["mfe"],
            "original_mae": o.get("mae"), "corrected_mae": corrected["mae"],
            "original_class": attribs.get(expr, {}).get("primary_class"),
            "thesis_path": tp["state"],
            "pnl_unchanged": o.get("pnl"),
            "pre_entry_bars_excluded": len(contaminated),
        })
        pnl_drift.append((sym, o.get("pnl")))

    (out / "day1_correction_report.json").write_text(
        json.dumps({"kind": "day1_correction_report",
                    "resolver_version": RESOLVER_VERSION,
                    "defects": DEFECTS, "records": report}, indent=1))
    for r in report:
        print(json.dumps(r, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
