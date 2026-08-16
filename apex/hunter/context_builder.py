"""Scan universe + DailyContext construction for the forward clock.

Universe rule (FROZEN, liquidity-ranked, never performance-ranked): from
the Sharadar snapshot's latest SEP chunks, domestic common stock, last
close >= $5, trailing median dollar volume >= $50M, ranked by median
dollar volume, top N. Liquidity ranking is deliberately boring — it cannot
smuggle in return selection. v1 LIMITATION, recorded in every scan record:
the scan universe is the top liquidity tier (~150 names), not the full
tape; widening it is a provider-upgrade question (protocol §9.5), not a
threshold to quietly relax.

DailyContext comes from PRIOR sessions only (trailing 1m history fetched
once per day through the quota governor, cache-keyed by a date range that
excludes today), so nothing in it can leak today's outcome.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd

from apex.hunter.chartstate import DailyContext
from apex.hunter.contracts import (LIQUIDITY_MIN_MEDIAN_DOLLAR_VOL,
                                   LIQUIDITY_MIN_PRICE)
from apex.intraday.eodhd import fetch_intraday_chunk, normalize_rows
from apex.intraday.sessions import Session, classify

SNAPSHOT = Path("data/snapshots/sharadar/current")
OUT_DIR = Path("results/hunter")
UNIVERSE_SIZE = 150
MIN_PRICE = LIQUIDITY_MIN_PRICE               # sovereign source (F-07)
MIN_MEDIAN_DOLLAR_VOL = LIQUIDITY_MIN_MEDIAN_DOLLAR_VOL
CONTEXT_LOOKBACK_DAYS = 30       # calendar; sessions derived from bars

SECTOR_ETF = {"Technology": "XLK.US", "Financial Services": "XLF.US",
              "Energy": "XLE.US", "Healthcare": "XLV.US",
              "Industrials": "XLI.US", "Consumer Cyclical": "XLY.US",
              "Consumer Defensive": "XLP.US", "Basic Materials": "XLB.US",
              "Utilities": "XLU.US", "Real Estate": "XLRE.US",
              "Communication Services": "XLC.US"}


def build_scan_universe(date: str, snapshot: Path = SNAPSHOT,
                        size: int = UNIVERSE_SIZE) -> dict:
    """Deterministic from the snapshot; cached per date. The snapshot's
    as-of is recorded — a stale snapshot is a visible limitation, not a
    silent one."""
    cache = OUT_DIR / f"scan_universe_{date}.json"
    if cache.exists():
        return json.loads(cache.read_text())
    ident = pd.read_csv(snapshot / "universe_candidates.csv")
    ident = ident[(ident["category"] == "Domestic Common Stock")
                  & (ident["isdelisted"] == "N")]
    sectors = ident.set_index("ticker")["sector"].to_dict()
    chunks = sorted((snapshot / "raw" / "SEP").glob("SEP_*.csv"))[-5:]
    sep = pd.concat((pd.read_csv(c, usecols=["ticker", "date", "close",
                                             "volume"]) for c in chunks),
                    ignore_index=True)
    sep = sep[sep["ticker"].isin(set(ident["ticker"]))]
    sep["dv"] = sep["close"] * sep["volume"]
    sep = sep.sort_values("date")
    g = sep.groupby("ticker")
    stats = pd.DataFrame({"med_dv": g["dv"].median(),
                          "last_close": g["close"].last(),
                          "sessions": g.size()})
    stats = stats[(stats["last_close"] >= MIN_PRICE)
                  & (stats["med_dv"] >= MIN_MEDIAN_DOLLAR_VOL)
                  & (stats["sessions"] >= 30)]
    top = stats.sort_values("med_dv", ascending=False).head(size)
    out = {"date": date, "rule": "liquidity_top_frozen_v1",
           "sep_as_of": str(sep["date"].max()),
           "universe_limitation": ("top liquidity tier only (v1); full-tape "
                                   "scan requires provider upgrade"),
           "candidates_considered": int(len(stats)),
           "symbols": {t: {"sector": sectors.get(t),
                           "sector_etf": SECTOR_ETF.get(sectors.get(t)),
                           "median_dollar_volume": float(r["med_dv"])}
                       for t, r in top.iterrows()}}
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(out, indent=1))
    return out


def context_from_history(symbol: str, hist: pd.DataFrame, today: str,
                         sector_etf: str | None,
                         median_dollar_volume: float | None) -> DailyContext:
    """Pure computation from prior-session bars (leak-proof by input:
    caller passes bars strictly BEFORE today)."""
    reg = hist[hist["event_time_utc"].map(
        lambda t: classify(t) is Session.REGULAR)].copy()
    if reg.empty:
        return DailyContext(symbol=symbol, as_of_date=today,
                            sector_etf=sector_etf,
                            median_dollar_volume=median_dollar_volume)
    reg["d"] = reg["event_time_utc"].dt.tz_convert("America/New_York").dt.date.astype(str)
    reg = reg[reg["d"] < today]
    days = sorted(reg["d"].unique())
    if not days:
        return DailyContext(symbol=symbol, as_of_date=today,
                            sector_etf=sector_etf,
                            median_dollar_volume=median_dollar_volume)
    by = {d: f for d, f in reg.groupby("d")}
    prev = by[days[-1]]
    week = reg[reg["d"].isin(days[-5:])]
    trs, ranges, cum_curves = [], [], []
    prior_close = None
    for d in days:
        f = by[d]
        hi, lo = float(f["high"].max()), float(f["low"].min())
        close = float(f["close"].iloc[-1])
        tr = (max(hi, prior_close or hi) - min(lo, prior_close or lo))
        trs.append(tr / close)
        ranges.append((hi - lo) / close)
        prior_close = close
        mins = ((f["event_time_utc"]
                 - f["event_time_utc"].iloc[0]).dt.total_seconds() // 60)
        cum = f["volume"].astype(float).cumsum()
        cum_curves.append(dict(zip(mins.astype(int), cum)))
    baseline = {}
    for m in range(390):
        vals = [c[max(k for k in c if k <= m)] for c in cum_curves
                if any(k <= m for k in c)]
        if vals:
            baseline[str(m)] = float(np.median(vals))
    return DailyContext(
        symbol=symbol, as_of_date=today,
        prev_day_high=float(prev["high"].max()),
        prev_day_low=float(prev["low"].min()),
        prev_close=float(prev["close"].iloc[-1]),
        weekly_high=float(week["high"].max()),
        weekly_low=float(week["low"].min()),
        atr_frac=float(np.mean(trs[-14:])),
        median_day_range_frac=float(np.median(ranges)),
        cum_vol_by_minute=baseline,
        median_dollar_volume=median_dollar_volume,
        sector_etf=sector_etf, sessions_observed=len(days))


def load_or_build_contexts(symbols: dict, today: str, gov,
                           extra_symbols: tuple = ()) -> dict:
    """Once per day: trailing history per symbol -> DailyContext, cached as
    JSON. `symbols`: universe dict entries; `extra_symbols`: ETFs (market/
    sector) that need contexts too."""
    cache = OUT_DIR / f"daily_context_{today}.json"
    if cache.exists():
        raw = json.loads(cache.read_text())
        loaded = {s: DailyContext(**v) for s, v in raw.items()}
        healthy = sum(1 for c in loaded.values() if c.sessions_observed > 0)
        if healthy >= 0.5 * max(len(loaded), 1):
            return loaded
        # LAB-04: a mostly-empty cache is POISON (a past fetch failure
        # frozen as fact) — quarantine and rebuild, never trust it
        cache.rename(cache.with_suffix(".poisoned"))
        print(f"context cache {today}: POISONED ({healthy}/{len(loaded)} "
              f"healthy) — quarantined, rebuilding")
    lo = str((pd.Timestamp(today) - pd.Timedelta(days=CONTEXT_LOOKBACK_DAYS)).date())
    hi = str((pd.Timestamp(today) - pd.Timedelta(days=1)).date())
    out = {}
    metas = ({s: (m.get("sector_etf"), m.get("median_dollar_volume"))
              for s, m in symbols.items()}
             | {s: (None, None) for s in extra_symbols})
    for sym, (setf, mdv) in metas.items():
        try:
            rows, _ = fetch_intraday_chunk(sym if sym.endswith(".US")
                                           else f"{sym}.US", lo, hi, gov)
            hist = normalize_rows(rows, sym)
            out[sym] = context_from_history(sym, hist, today, setf, mdv)
        except Exception as e:                          # noqa: BLE001
            out[sym] = DailyContext(symbol=sym, as_of_date=today,
                                    sector_etf=setf,
                                    median_dollar_volume=mdv)
            print(f"context {sym}: {type(e).__name__}")
    healthy = sum(1 for c in out.values() if c.sessions_observed > 0)
    if healthy >= 0.8 * max(len(out), 1):
        cache.write_text(json.dumps({s: asdict(c) for s, c in out.items()}))
    else:
        # LAB-04: do NOT freeze a failure as a cache; callers see the
        # degraded contexts this run, but no future run inherits them
        print(f"context build {today}: {healthy}/{len(out)} healthy — "
              f"NOT cached (transient failure must not become permanent)")
    return out
