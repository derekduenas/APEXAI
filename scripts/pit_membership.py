"""PIT MEMBERSHIP — the HIGH-LIQUIDITY point-in-time single-name
universe (operator amendment 1: this is the high-liquidity claim
surface, never "all single names").

Mechanical rule, sealed before any economic look:
    at each month-end M, rank all listed US common stocks (active AND
    inactive/delisted directory, OTC excluded) by trailing 63-session
    median dollar volume computed as-of M from raw daily bars; the
    TOP 100 are the universe for month M+1.

Dollar volume is split-invariant and point-in-time computable. FRC is
in the January-2023 universe because January didn't know March.
Symbols are stored as-known-at-M; later fetches pass asof=M so entity
renames resolve natively (amendment 3), with the dormancy/
discontinuity detector retained as an independent check.

Provably-safe pruning (documented, not hidden): a symbol whose BEST
day never reached $50M dollar volume cannot have a 63-session MEDIAN
near the top-100 cutoff (which runs hundreds of $M) -- a median above
any threshold requires 32+ days above it. Pruned symbols are counted
in the denominator report.

decision_power: NONE_DATA_ACQUISITION.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apex.governance.chain_ledger import chain_append  # noqa: E402

OUT = Path("/apex-data/history-b/pit_singlename")
MEMBERSHIP = OUT / "membership_v1.jsonl"
START = "2015-09-01"
END = "2026-08-28"
TOP_N = 100
TRAIL = 63
PRUNE_ANYDAY_DV = 50e6

DATA = "https://data.alpaca.markets/v2/stocks/bars"
ASSETS = "https://api.alpaca.markets/v2/assets"
CORP = "https://data.alpaca.markets/v1/corporate-actions"
CACHE = OUT / "daily_dollar_volume_cache.json.gz"

# ETF/fund exclusion (mechanical, predeclared): the single-name
# universe is COMMON STOCKS; the us_equity directory also lists funds.
ETF_NAME_TOKENS = ("ETF", "ETN", "FUND", "TRUST", "SHARES", "INDEX",
                   "ISHARES", "SPDR", "VANGUARD", "PROSHARES",
                   "DIREXION", "INVESCO QQQ")
KNOWN_ETPS = {"SPY", "QQQ", "IWM", "DIA", "EEM", "EFA", "GDX", "GLD",
              "SLV", "USO", "XLB", "XLC", "XLE", "XLF", "XLI", "XLK",
              "XLP", "XLRE", "XLU", "XLV", "XLY", "SQQQ", "TQQQ",
              "SPXU", "UVXY", "VXX", "SVXY", "TLT", "HYG", "LQD",
              "SOXL", "SOXS", "SMH", "SOXX", "ARKK", "KWEB", "FXI",
              "EWZ", "XBI", "IBB", "KRE", "XOP", "GDXJ", "UNG",
              "TZA", "TNA", "SPXL", "SPXS", "SDS", "SSO", "QID",
              "QLD", "IEF", "SH", "RSP", "VTI", "VOO", "IVV"}


def _get(url: str) -> dict:
    req = urllib.request.Request(url, headers={
        "APCA-API-KEY-ID": os.environ["APCA_API_KEY_ID"],
        "APCA-API-SECRET-KEY": os.environ["APCA_API_SECRET_KEY"]})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.loads(r.read())
        except Exception:                              # noqa: BLE001
            if attempt == 4:
                raise
            time.sleep(2 ** attempt)


def _is_fundlike(name: str, symbol: str) -> bool:
    up = (name or "").upper()
    return symbol in KNOWN_ETPS or any(t in up
                                       for t in ETF_NAME_TOKENS)


def corporate_action_symbols() -> tuple:
    """Dead and renamed symbols the directory forgot -- TWTR, ATVI
    and friends live only here. Also returns rename chains
    (old->new) for entity dedupe."""
    dead, renames = set(), {}
    types = ("name_change", "cash_merger", "stock_merger",
             "stock_and_cash_merger", "redemption",
             "worthless_removal")
    y0, y1 = int(START[:4]), int(END[:4])
    for year in range(y0, y1 + 1):
        for ty in types:
            try:
                d = _get(CORP + "?" + urllib.parse.urlencode(
                    {"types": ty, "start": f"{year}-01-01",
                     "end": f"{year}-12-31", "limit": 1000}))
            except Exception:                          # noqa: BLE001
                continue
            for key, rows in (d.get("corporate_actions")
                              or {}).items():
                for r in rows:
                    for f in ("old_symbol", "symbol",
                              "acquiree_symbol", "target_symbol"):
                        v = r.get(f)
                        if v and v.isalpha() and len(v) <= 5:
                            dead.add(v)
                    if ty == "name_change" and r.get("old_symbol")                             and r.get("new_symbol"):
                        renames[r["old_symbol"]] = r["new_symbol"]
    return dead, renames


def list_symbols() -> tuple:
    syms, fundlike = set(), set()
    for status in ("active", "inactive"):
        rows = _get(f"{ASSETS}?status={status}&asset_class=us_equity")
        for a in rows:
            if a.get("exchange") in ("NYSE", "NASDAQ", "ARCA",
                                     "AMEX", "BATS", "NYSEARCA"):
                s = a.get("symbol", "")
                if s and s.isalpha() and len(s) <= 5:
                    if _is_fundlike(a.get("name", ""), s):
                        fundlike.add(s)
                    else:
                        syms.add(s)
    dead, renames = corporate_action_symbols()
    dead -= fundlike
    return sorted(syms | dead), fundlike, renames


def run() -> dict:
    import gzip
    symbols, fundlike, renames = list_symbols()
    kept: dict[str, dict] = {}          # sym -> {date: dollar_vol}
    pruned = fetched = 0
    if CACHE.exists():
        cached = json.loads(gzip.open(CACHE).read())
        kept = cached["kept"]
        pruned, fetched = cached["pruned"], cached["fetched"]
        symbols = [s for s in symbols if s not in cached["seen"]]
        print(json.dumps({"cache": "loaded",
                          "remaining_symbols": len(symbols)}),
              flush=True)
    seen = set(kept)
    B = 200
    for i in range(0, len(symbols), B):
        batch = symbols[i:i + B]
        token = None
        acc: dict[str, dict] = defaultdict(dict)
        best: dict[str, float] = defaultdict(float)
        while True:
            q = {"symbols": ",".join(batch),
                 "start": f"{START}T00:00:00Z",
                 "end": f"{END}T23:59:59Z",
                 "timeframe": "1Day", "limit": 10000,
                 "adjustment": "raw", "feed": "sip"}
            if token:
                q["page_token"] = token
            d = _get(DATA + "?" + urllib.parse.urlencode(q))
            for sym, bars in (d.get("bars") or {}).items():
                for b in bars:
                    dv = float(b["c"]) * float(b["v"])
                    acc[sym][b["t"][:10]] = dv
                    best[sym] = max(best[sym], dv)
            token = d.get("next_page_token")
            if not token:
                break
        for sym, days in acc.items():
            fetched += 1
            seen.add(sym)
            if best[sym] >= PRUNE_ANYDAY_DV:
                kept[sym] = days
            else:
                pruned += 1
        seen.update(batch)
        print(json.dumps({"batch": i // B,
                          "of": (len(symbols) + B - 1) // B,
                          "kept": len(kept), "pruned": pruned}),
              flush=True)

    import gzip
    OUT.mkdir(parents=True, exist_ok=True)
    with gzip.open(CACHE, "wt") as fh:
        fh.write(json.dumps({"kept": kept, "pruned": pruned,
                             "fetched": fetched,
                             "seen": sorted(seen)}))

    # ENTITY DEDUPE: a rename chain (FB->META) makes the same company
    # rankable under two symbols, because bars for the CURRENT symbol
    # include pre-rename history. Collapse each chain onto the OLD
    # symbol for dates before the rename by removing the new symbol's
    # pre-existence duplicates: keep the symbol whose own listing era
    # covers the date. Practical rule: if old and new both ranked,
    # drop the NEW symbol's days that exactly duplicate the OLD's.
    for old_s, new_s in renames.items():
        if old_s in kept and new_s in kept:
            dup = [d for d, v in kept[new_s].items()
                   if kept[old_s].get(d) == v]
            for d in dup:
                del kept[new_s][d]

    # session calendar = union of dates among kept symbols
    calendar = sorted({d for days in kept.values() for d in days})
    # month-ends within calendar
    month_ends = {}
    for d in calendar:
        month_ends[d[:7]] = d
    OUT.mkdir(parents=True, exist_ok=True)
    months = sorted(month_ends)
    distinct: set[str] = set()
    inactive_members: set[str] = set()
    n_rows = 0
    for mi, m in enumerate(months):
        if m < "2015-12" or m >= "2026-08":
            continue
        asof_date = month_ends[m]
        ci = calendar.index(asof_date)
        window = calendar[max(0, ci - TRAIL + 1):ci + 1]
        if len(window) < TRAIL:
            continue
        scores = {}
        for sym, days in kept.items():
            vals = sorted(days.get(d, 0.0) for d in window)
            med = vals[len(vals) // 2]
            if med > 0:
                scores[sym] = med
        top = sorted(scores, key=scores.get, reverse=True)[:TOP_N]
        member_month = months[mi + 1] if mi + 1 < len(months) else None
        if member_month is None:
            continue
        distinct.update(top)
        top = [t for t in top if t not in fundlike]
        chain_append(MEMBERSHIP, {
            "kind": "pit_membership", "member_month": member_month,
            "decided_asof": asof_date,
            "rule": f"top{TOP_N}_trailing{TRAIL}d_median_dollar_"
                    f"volume", "symbols": top,
            "cutoff_dollar_volume": round(scores[top[-1]], 0),
            "claim_scope": "HIGH_LIQUIDITY_PIT_SINGLE_NAME_UNIVERSE",
            "decision_power": "NONE_DATA_ACQUISITION"})
        n_rows += 1
    rep = {"kind": "pit_membership_summary",
           "directory_symbols": len(symbols),
           "symbols_with_bars": fetched,
           "pruned_provably_safe": pruned,
           "candidates_ranked": len(kept),
           "membership_months": n_rows,
           "distinct_member_names": len(distinct),
           "calendar_sessions": len(calendar),
           "claim_scope": "HIGH_LIQUIDITY_PIT_SINGLE_NAME_UNIVERSE "
                          "-- failure here refutes highly liquid "
                          "single names ONLY",
           "decision_power": "NONE_DATA_ACQUISITION"}
    chain_append(MEMBERSHIP, rep)
    print(json.dumps(rep, indent=1))
    return rep


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    if ap.parse_args().run:
        run()
