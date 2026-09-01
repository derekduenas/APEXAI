"""REGIME ATLAS V1 -- daily causal environment state.

Every field is computed from TRAILING data only (knowable at that
session's open) and attached descriptively to lab outcomes. Regime
holds ZERO decision authority (sealed in the Edge Atlas
constitution).

DECLARED binning rules (fixed before any outcome is examined):
  trend        SPY close[t-1] vs close[t-61]:
               <-6% STRONG_DOWN, <-2% WEAK_DOWN, <=+2% NEUTRAL,
               <=+6% WEAK_UP, else STRONG_UP
  vol          SPY 20d realized (annualized):
               <10% COMPRESSED, <20% NORMAL, <35% ELEVATED,
               else CRISIS
  dispersion   cross-sectional stdev of PIT members' daily returns,
               binned by its own TRAILING-252d percentile:
               <20th LOW, <80th NORMAL, else HIGH
  correlation  median 20d correlation of members to SPY, trailing-
               percentile bins as above (HIGH = index-dominated)
  breadth      fraction of members above their own 20d mean close:
               <0.35 NARROW, <0.65 MIXED, else BROAD
  event_density  count of calendar earnings events that session,
               trailing-252d percentile: QUIET/NORMAL/HEAVY

Output: exports/regime_atlas_v1.jsonl (one row per session).
decision_power: NONE_DESCRIPTIVE_STATE.
"""
from __future__ import annotations

import json
import math
import statistics
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ETF = Path("/apex-data/history-b/etf_continuous/bars")
SN = Path("/apex-data/history-b/pit_singlename/bars")
RAW = Path("exports/earnings_events_raw.jsonl")
OUT = Path("exports/regime_atlas_v1.jsonl")
NY = ZoneInfo("America/New_York")


def close_of(base, sym, d):
    try:
        bars = json.loads((base / f"{sym}_{d}.json").read_text())["bars"]
    except Exception:
        return None
    last = None
    for b in bars:
        t = datetime.fromisoformat(
            b["event_time_utc"].replace("Z", "+00:00")).astimezone(NY)
        m = t.hour * 60 + t.minute
        if 570 <= m < 960:
            last = b["close"]
    return last


def trailing_pct(hist, x):
    if len(hist) < 60:
        return None
    n = sum(1 for h in hist if h <= x)
    return n / len(hist)


def main():
    import os
    spy_days = sorted(f[4:-5] for f in os.listdir(ETF)
                      if f.startswith("SPY_"))
    spy_close = {}
    for d in spy_days:
        c = close_of(ETF, "SPY", d)
        if c:
            spy_close[d] = c
    days = [d for d in spy_days if d in spy_close]

    # member daily closes by session (from bar-file index)
    sym_days = defaultdict(set)
    for f in os.listdir(SN):
        if f.endswith(".json") and "_" in f:
            sym, _, d = f[:-5].rpartition("_")
            sym_days[d].add(sym)

    ev_count = defaultdict(int)
    for l in RAW.open():
        r = json.loads(l)
        ev_count[r["report_date"]] += 1

    closes_cache = {}          # (sym, day) -> close

    def cget(sym, d):
        k = (sym, d)
        if k not in closes_cache:
            if len(closes_cache) > 300_000:
                closes_cache.clear()
            closes_cache[k] = close_of(SN, sym, d)
        return closes_cache[k]

    disp_hist, corr_hist, dens_hist = [], [], []
    out = OUT.open("w")
    n = 0
    for i, d in enumerate(days):
        if i < 61:
            continue
        # trend / vol from SPY trailing
        c1, c61 = spy_close[days[i - 1]], spy_close[days[i - 61]]
        tr = c1 / c61 - 1
        trend = ("STRONG_DOWN" if tr < -0.06 else
                 "WEAK_DOWN" if tr < -0.02 else
                 "NEUTRAL" if tr <= 0.02 else
                 "WEAK_UP" if tr <= 0.06 else "STRONG_UP")
        rets = [math.log(spy_close[days[j]] / spy_close[days[j - 1]])
                for j in range(i - 20, i)]
        vol_ann = statistics.pstdev(rets) * math.sqrt(252)
        vol = ("COMPRESSED" if vol_ann < 0.10 else
               "NORMAL" if vol_ann < 0.20 else
               "ELEVATED" if vol_ann < 0.35 else "CRISIS")

        # cross-section from yesterday's members (sampled: cap 60)
        prev = days[i - 1]
        members = sorted(sym_days.get(prev, set()))[:60]
        day_rets, breadth_num, breadth_den, corrs = [], 0, 0, []
        for s in members:
            c_now = cget(s, prev)
            c_b = cget(s, days[i - 2]) if i >= 2 else None
            if c_now and c_b:
                day_rets.append(c_now / c_b - 1)
            hist = []
            for j in range(i - 21, i):
                cc = cget(s, days[j])
                if cc:
                    hist.append(cc)
            if len(hist) >= 15 and c_now:
                breadth_den += 1
                if c_now > statistics.mean(hist):
                    breadth_num += 1
                sr = [math.log(hist[k] / hist[k - 1])
                      for k in range(1, len(hist))]
                mr = [math.log(spy_close[days[j]]
                               / spy_close[days[j - 1]])
                      for j in range(i - len(sr), i)]
                if len(sr) == len(mr) and statistics.pstdev(sr) > 0 \
                        and statistics.pstdev(mr) > 0:
                    mu_s, mu_m = (statistics.mean(sr),
                                  statistics.mean(mr))
                    cov = sum((a - mu_s) * (b - mu_m)
                              for a, b in zip(sr, mr)) / len(sr)
                    corrs.append(cov / (statistics.pstdev(sr)
                                        * statistics.pstdev(mr)))
        disp = statistics.pstdev(day_rets) if len(day_rets) > 10 \
            else None
        corr = statistics.median(corrs) if len(corrs) > 10 else None
        breadth = (breadth_num / breadth_den) if breadth_den > 10 \
            else None
        dens = ev_count.get(d, 0)

        def binp(hist, x, lo=0.2, hi=0.8,
                 names=("LOW", "NORMAL", "HIGH")):
            if x is None:
                return "UNKNOWN"
            p = trailing_pct(hist, x)
            if p is None:
                return "WARMUP"
            return (names[0] if p < lo else
                    names[1] if p < hi else names[2])

        row = {"session": d, "trend": trend,
               "trend_60d": round(tr, 4),
               "vol": vol, "vol_ann": round(vol_ann, 4),
               "dispersion": binp(disp_hist, disp),
               "correlation": binp(
                   corr_hist, corr,
                   names=("STOCK_PICKING", "NORMAL",
                          "INDEX_DOMINATED")),
               "breadth": ("UNKNOWN" if breadth is None else
                           "NARROW" if breadth < 0.35 else
                           "MIXED" if breadth < 0.65 else "BROAD"),
               "event_density": binp(
                   dens_hist, dens,
                   names=("QUIET", "NORMAL", "HEAVY"))}
        out.write(json.dumps(row) + "\n")
        n += 1
        if disp is not None:
            disp_hist.append(disp)
            disp_hist[:] = disp_hist[-252:]
        if corr is not None:
            corr_hist.append(corr)
            corr_hist[:] = corr_hist[-252:]
        dens_hist.append(dens)
        dens_hist[:] = dens_hist[-252:]
        if n % 250 == 0:
            print(json.dumps({"done": n, "session": d}), flush=True)
    out.close()
    print(json.dumps({"sessions": n, "out": str(OUT)}))


if __name__ == "__main__":
    main()
