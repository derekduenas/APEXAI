#!/usr/bin/env python
"""One-off P1B engineering smoke: run the FULL perception pass against the
most recent completed session's real tape (Friday), output DISCARDED —
nothing is written to the forward ledger. This is an engineering
measurement (evidence law: laboratory, not exam); its only job is to prove
the Monday-morning code path works end-to-end on real vendor data and to
show what the funnel looks like at real scale.

Universe capped via APEX_SMOKE_N (default 25) to keep quota/runtime small.
"""
from __future__ import annotations

import dataclasses
import json
import os
import sys
from pathlib import Path

_S = Path(__file__).resolve().parent
sys.path.insert(0, str(_S.parent)); sys.path.insert(0, str(_S))

import pandas as pd  # noqa: E402

from apex.hunter.context_builder import (  # noqa: E402
    SECTOR_ETF, build_scan_universe, load_or_build_contexts,
)
from apex.hunter.forward_pass import decision_pass  # noqa: E402
from apex.intraday.eodhd import (  # noqa: E402
    QuotaGovernor, fetch_intraday_chunk, normalize_rows,
)

DATE = os.environ.get("APEX_SMOKE_DATE", "2026-08-14")
N = int(os.environ.get("APEX_SMOKE_N", "25"))
T = pd.Timestamp(f"{DATE} 13:00", tz="America/New_York").tz_convert("UTC")


def main() -> int:
    gov = QuotaGovernor()
    universe = build_scan_universe(DATE)
    subset = dict(list(universe["symbols"].items())[:N])
    universe = {**universe, "symbols": subset}
    idx = ("SPY.US", "QQQ.US", "IWM.US")
    etfs = tuple(sorted({m["sector_etf"] for m in subset.values()
                         if m.get("sector_etf")}))
    contexts = load_or_build_contexts(subset, DATE, gov,
                                      extra_symbols=(*idx, *etfs))
    bars = {}
    for sym in (*idx, *etfs, *subset):
        vendor = sym if sym.endswith(".US") else f"{sym}.US"
        try:
            rows, _ = fetch_intraday_chunk(vendor, DATE, DATE, gov)
            f = normalize_rows(rows, vendor)
            f["provider_symbol"] = sym
            bars[sym] = f
        except Exception as e:                              # noqa: BLE001
            print(f"fetch {sym}: {type(e).__name__}")
    scan_record, decisions = decision_pass(T, universe, bars, contexts)
    print(json.dumps({k: scan_record[k] for k in
                      ("universe_count", "states_computed",
                       "liquidity_data_ok", "abnormal")}, indent=1))
    print("watchlist:", [w["symbol"] for w in scan_record["watchlist"]])
    for d in decisions:
        print(f"WOULD-DECIDE {d['symbol']} {d['playbook_id']} "
              f"{d['direction']} eligibility={d['forward_eligibility']} "
              f"reasons={d['eligibility_reasons'][:2]}")
    print(f"decisions: {len(decisions)}  quota_used: {gov.used}")
    print("SMOKE OK — output discarded, ledger untouched")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
