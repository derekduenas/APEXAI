"""RELATIVE-VALUE-LAB-RV1 -- residual dislocation study.

Design sealed BEFORE this run (RELATIVE-VALUE-LAB-RV1-2026-08-30).
residual = (daily log return - trailing-60d beta * SPY return)
           - mean same-day excess of SIC-4 peers.
Trigger: |residual| >= own trailing-252d 90th pct (EXTREME: 98th).
Formation close_t (MOC convention); frozen horizons t+1/t+3/t+5/t+10
forward residuals. Splits: direction x own-earnings proximity x
severity. Both FADE and FOLLOW conventions are scored for every
cell -- one hypothesis pair, counted twice in the burden.
decision_power: RESEARCH_DISCOVERY_ONLY.
"""
from __future__ import annotations

import gzip
import json
import math
import statistics
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

CLOSES = Path("exports/daily_closes_v1.json.gz")
PEERS = Path("exports/peer_map_v1.json")
RAW = Path("exports/earnings_events_raw.jsonl")
TOLL = Path("/apex-data/history-b/pit_singlename/"
            "movement_toll_obs.jsonl")
GRAVE = Path("results/edge_atlas/rv1_cells.jsonl")
START = "2018-07-01"
UPLIFT, FEES = 1.34, 0.05


def main():
    closes = json.load(gzip.open(CLOSES, "rt"))
    spy = closes.pop("SPY")
    for etf in ("QQQ", "IWM", "DIA", "XLK", "XLF", "XLE", "XLV",
                "XLI", "XLY", "XLP", "XLU", "XLB", "XLRE", "XLC"):
        closes.pop(etf, None)
    days = sorted(spy)
    dpos = {d: i for i, d in enumerate(days)}
    spy_ret = {}
    for i in range(1, len(days)):
        spy_ret[days[i]] = math.log(spy[days[i]] / spy[days[i - 1]])

    pm = json.loads(PEERS.read_text())["map"]
    sic_of = {s: m["sic4"] for s, m in pm.items()}
    group = defaultdict(set)
    for s, m in pm.items():
        group[m["sic4"]].add(s)

    ev_dates = defaultdict(set)
    for l in RAW.open():
        r = json.loads(l)
        ev_dates[r["symbol"]].add(r["report_date"])

    def near_event(sym, d):
        d0 = datetime.strptime(d, "%Y-%m-%d").date()
        return any((d0 + timedelta(days=k)).isoformat()
                   in ev_dates[sym] for k in (-1, 0, 1))

    per, per_year = defaultdict(list), defaultdict(list)
    for l in TOLL.open():
        try:
            r = json.loads(l)
        except Exception:
            continue
        if r.get("cohort") == "SINGLE" and r.get("toll") is not None:
            per[(r["symbol"], r["day"][:4])].append(r["toll"])
            per_year[r["day"][:4]].append(r["toll"])
    surf = {k: statistics.median(v) for k, v in per.items()
            if len(v) >= 20}
    ymed = {y: statistics.median(v) for y, v in per_year.items()}

    def rt_bps(sym, y):
        t = surf.get((sym, y), ymed.get(y))
        if t is None:
            t = statistics.median(ymed.values())
        return 2 * t * UPLIFT * 1e4 + FEES

    # per-symbol daily returns and excess
    ret = defaultdict(dict)
    for s, cs in closes.items():
        sd = sorted(cs)
        for i in range(1, len(sd)):
            d0, d1 = sd[i - 1], sd[i]
            if dpos.get(d1, 0) - dpos.get(d0, 1e9) == 1 \
                    and d1 in spy_ret:
                ret[s][d1] = math.log(cs[d1] / cs[d0])

    # trailing beta (60d) then excess
    excess = defaultdict(dict)
    for s, rs in ret.items():
        sd = sorted(rs)
        for i, d in enumerate(sd):
            if i < 60:
                continue
            win = sd[i - 60:i]
            x = [spy_ret[w] for w in win]
            y = [rs[w] for w in win]
            vx = statistics.pvariance(x)
            if vx <= 0:
                continue
            mx, my = statistics.mean(x), statistics.mean(y)
            beta = sum((a - mx) * (b - my)
                       for a, b in zip(x, y)) / len(x) / vx
            excess[s][d] = rs[d] - beta * spy_ret[d]

    # residual vs peer excess
    by_day_sic = defaultdict(list)
    for s, es in excess.items():
        sic = sic_of.get(s)
        if sic:
            for d, e in es.items():
                by_day_sic[(d, sic)].append((s, e))
    residual = defaultdict(dict)
    for (d, sic), lst in by_day_sic.items():
        if len(lst) >= 3:
            tot = sum(e for _, e in lst)
            for s, e in lst:
                residual[s][d] = e - (tot - e) / (len(lst) - 1)

    # triggers: trailing own 90th/98th pct of |residual|
    events = []
    for s, rsd in residual.items():
        sd = sorted(rsd)
        hist = []
        for d in sd:
            x = abs(rsd[d])
            if len(hist) >= 120 and d >= START:
                arr = sorted(hist[-252:])
                p90 = arr[int(0.90 * len(arr))]
                p98 = arr[int(0.98 * len(arr))]
                if x >= p90:
                    fwd = {}
                    i0 = dpos[d]
                    for k in (1, 3, 5, 10):
                        j = i0 + k
                        if j < len(days):
                            dj = days[j]
                            # forward residual = sum of dailies
                            path = [residual[s].get(days[m])
                                    for m in range(i0 + 1, j + 1)]
                            if all(p is not None for p in path):
                                fwd[k] = sum(path) * 1e4
                    events.append({
                        "sym": s, "day": d, "year": d[:4],
                        "res_bps": rsd[d] * 1e4,
                        "dir": 1 if rsd[d] > 0 else -1,
                        "extreme": x >= p98,
                        "event_prox": near_event(s, d),
                        "fwd": fwd,
                        "rt": rt_bps(s, d[:4])})
            hist.append(x)

    print(json.dumps({"trigger_events": len(events),
                      "extreme": sum(1 for e in events
                                     if e["extreme"])}), flush=True)

    ledger = []

    def cell(cid, sub, k, mode):
        """mode FADE: pnl = -dir*fwd; FOLLOW: pnl = dir*fwd."""
        vals = []
        for e in sub:
            f = e["fwd"].get(k)
            if f is None:
                continue
            pnl = (-e["dir"] * f) if mode == "FADE" else e["dir"] * f
            vals.append((pnl, pnl - e["rt"], e["year"]))
        n = len(vals)
        rec = {"kind": "rv_cell", "id": cid, "horizon": f"t+{k}",
               "mode": mode, "n": n}
        if n >= 80:
            g = [v[0] for v in vals]
            nb = [v[1] for v in vals]
            yrs = defaultdict(list)
            for v in vals:
                yrs[v[2]].append(v[1])
            ym = {y: round(statistics.mean(x), 1)
                  for y, x in sorted(yrs.items()) if len(x) >= 20}
            rec.update({"gross_mean_bps": round(statistics.mean(g), 1),
                        "gross_median_bps": round(
                            statistics.median(g), 1),
                        "net_base_bps": round(statistics.mean(nb), 1),
                        "win_net": round(
                            sum(1 for x in nb if x > 0) / n, 3),
                        "pos_years": f"{sum(1 for v in ym.values() if v > 0)}"
                                     f"/{len(ym)}",
                        "by_year": ym})
        else:
            rec["verdict"] = "INSUFFICIENT_N"
        ledger.append(rec)

    splits = {
        "all": events,
        "extreme": [e for e in events if e["extreme"]],
        "event_prox": [e for e in events if e["event_prox"]],
        "non_event": [e for e in events if not e["event_prox"]],
        "extreme_non_event": [e for e in events
                              if e["extreme"] and not e["event_prox"]],
        "extreme_event": [e for e in events
                          if e["extreme"] and e["event_prox"]],
        "pos_res": [e for e in events if e["dir"] > 0],
        "neg_res": [e for e in events if e["dir"] < 0],
    }
    for name, sub in splits.items():
        for k in (1, 3, 5, 10):
            for mode in ("FADE", "FOLLOW"):
                cell(f"RV1_{name}", sub, k, mode)

    # baseline: unconditional forward residual magnitude~0 by constr.
    GRAVE.parent.mkdir(parents=True, exist_ok=True)
    with GRAVE.open("w") as g:
        g.write(json.dumps({"kind": "discovery_ledger",
                            "cells": len(ledger),
                            "trigger_events": len(events)}) + "\n")
        for rec in ledger:
            g.write(json.dumps(rec) + "\n")
    scored = [r for r in ledger if "net_base_bps" in r]
    scored.sort(key=lambda r: r["net_base_bps"], reverse=True)
    print(json.dumps({"cells": len(ledger),
                      "scored": len(scored)}), flush=True)
    for r in scored[:8]:
        print(json.dumps(r), flush=True)
    print("WORST 3:", flush=True)
    for r in scored[-3:]:
        print(json.dumps(r), flush=True)


if __name__ == "__main__":
    main()
