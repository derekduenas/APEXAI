"""FORCED-FLOW-LAB-F1 -- OPEX / dealer-hedging calendar study.

Design sealed BEFORE this run (FORCED-FLOW-LAB-F1-2026-08-30).
Conditioning variable is the deterministic option-expiry calendar
(3rd Friday monthly; expiry trading day = last trading day on or
before it). Zero lookahead by construction.

F1a  post-OPEX (next 3 trading days) and OPEX-week index returns
     vs all-days baseline. SPY + QQQ, monthly vs quarterly.
F1b  expiry-Friday afternoon (13:00-16:00 ET) pinning at index
     level: afternoon |ret|, range, and the tradeable form
     (fade the morning move) vs non-expiry Fridays.
F1c  single-name closes' distance to the $5 strike grid on expiry
     vs non-expiry Fridays. VALIDITY DIAGNOSTIC ONLY.
Regime diagnostic (prespecified direction): effects strengthen when
trailing-21d SPY vol is HIGH.
decision_power: RESEARCH_DISCOVERY_ONLY.
"""
from __future__ import annotations

import gzip
import json
import math
import statistics
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

CLOSES = Path("exports/daily_closes_v1.json.gz")
ETFBARS = Path("/apex-data/history-b/etf_continuous/bars")
GRAVE = Path("results/edge_atlas/forced_flow_f1.jsonl")
NY = ZoneInfo("America/New_York")
RT_ETF = 2.0  # bps round trip, sealed


def third_friday(y, m):
    d = date(y, m, 1)
    fridays = [d + timedelta(days=k) for k in range(31)
               if (d + timedelta(days=k)).month == m
               and (d + timedelta(days=k)).weekday() == 4]
    return fridays[2]


def main():
    closes = json.load(gzip.open(CLOSES, "rt"))
    spy = closes["SPY"]
    days = sorted(spy)
    dpos = {d: i for i, d in enumerate(days)}
    dayset = set(days)

    def logret(sym_closes, d1):
        i = dpos[d1]
        if i == 0:
            return None
        d0 = days[i - 1]
        if d0 in sym_closes and d1 in sym_closes:
            return math.log(sym_closes[d1] / sym_closes[d0]) * 1e4
        return None

    # expiry trading days
    expiries = []
    for y in range(2016, 2027):
        for m in range(1, 13):
            tf = third_friday(y, m)
            e = tf
            while e.isoformat() not in dayset:
                e -= timedelta(days=1)
                if (tf - e).days > 5:
                    e = None
                    break
            if e and days[0] <= e.isoformat() <= days[-1]:
                expiries.append({"day": e.isoformat(),
                                 "quarterly": m in (3, 6, 9, 12)})
    print(json.dumps({"expiries": len(expiries),
                      "first": expiries[0]["day"],
                      "last": expiries[-1]["day"]}), flush=True)

    # trailing 21d SPY vol for regime split
    spyret = {}
    for d in days:
        r = logret(spy, d)
        if r is not None:
            spyret[d] = r
    vol = {}
    rs = [spyret.get(d) for d in days]
    for i, d in enumerate(days):
        win = [x for x in rs[max(0, i - 21):i] if x is not None]
        if len(win) >= 15:
            vol[d] = statistics.pstdev(win)
    vmed = statistics.median(vol.values())

    ledger = []

    def cell(cid, vals_by_year, note=""):
        """vals_by_year: list[(value_bps, year)]"""
        n = len(vals_by_year)
        rec = {"kind": "f1_cell", "id": cid, "n": n, "note": note}
        if n >= 30:
            g = [v for v, _ in vals_by_year]
            yrs = defaultdict(list)
            for v, y in vals_by_year:
                yrs[y].append(v)
            ym = {y: round(statistics.mean(x), 1)
                  for y, x in sorted(yrs.items()) if len(x) >= 4}
            rec.update({"mean_bps": round(statistics.mean(g), 1),
                        "median_bps": round(statistics.median(g), 1),
                        "win": round(
                            sum(1 for v in g if v > 0) / n, 3),
                        "pos_years": f"{sum(1 for v in ym.values() if v > 0)}"
                                     f"/{len(ym)}",
                        "by_year": ym})
        else:
            rec["verdict"] = "INSUFFICIENT_N"
        ledger.append(rec)
        return rec

    # ---- F1a: window returns around expiry ----
    for symname in ("SPY", "QQQ"):
        cs = closes[symname]
        for qual, sub in (("monthly_all", expiries),
                          ("quarterly", [e for e in expiries
                                         if e["quarterly"]])):
            post, week = [], []
            for e in sub:
                i = dpos[e["day"]]
                y = e["day"][:4]
                # post-OPEX: next 3 trading days, gross sum - RT
                nxt = [logret(cs, days[j])
                       for j in range(i + 1, min(i + 4, len(days)))]
                if len(nxt) == 3 and all(x is not None for x in nxt):
                    post.append((sum(nxt) - RT_ETF, y))
                # OPEX week: Monday..expiry-day of that week
                wk = []
                j = i
                while j >= 0 and days[j] >= (
                        datetime.strptime(e["day"], "%Y-%m-%d")
                        - timedelta(days=datetime.strptime(
                            e["day"], "%Y-%m-%d").weekday())
                ).strftime("%Y-%m-%d"):
                    r = logret(cs, days[j])
                    if r is not None:
                        wk.append(r)
                    j -= 1
                if len(wk) >= 3:
                    week.append((sum(wk) - RT_ETF, y))
            cell(f"F1a_{symname}_post_opex_{qual}", post)
            cell(f"F1a_{symname}_opex_week_{qual}", week)
        # baseline: ALL overlapping 3-day windows, gross - RT
        base = []
        for i in range(1, len(days) - 3):
            nxt = [logret(cs, days[j]) for j in range(i + 1, i + 4)]
            if all(x is not None for x in nxt):
                base.append((sum(nxt) - RT_ETF, days[i][:4]))
        cell(f"F1a_{symname}_BASELINE_all_3d_windows", base,
             note="contemporaneous dumb baseline")

    # ---- F1b: expiry-Friday afternoon pinning (SPY minutes) ----
    exp_days = {e["day"] for e in expiries}
    fridays = [d for d in days
               if datetime.strptime(d, "%Y-%m-%d").weekday() == 4]

    def sess(dstr):
        f = ETFBARS / f"SPY_{dstr}.json"
        if not f.exists():
            return None
        try:
            bars = json.loads(f.read_text())["bars"]
        except Exception:
            return None
        px = {}
        for b in bars:
            t = datetime.fromisoformat(
                b["event_time_utc"].replace("Z", "+00:00")
            ).astimezone(NY)
            m = t.hour * 60 + t.minute
            if 570 <= m < 960:
                px[m] = b["close"]
        if not px:
            return None
        keys = sorted(px)
        def near(target):
            best = min(keys, key=lambda k: abs(k - target))
            return px[best] if abs(best - target) <= 10 else None
        o, mid, c = near(571), near(780), near(959)
        if None in (o, mid, c):
            return None
        pm = [v for k, v in px.items() if k >= 780]
        return {"morning": math.log(mid / o) * 1e4,
                "afternoon": math.log(c / mid) * 1e4,
                "pm_range": (max(pm) - min(pm)) / mid * 1e4}

    groups = {"expiry": [], "nonexp": []}
    for d in fridays:
        s = sess(d)
        if s is None:
            continue
        s["day"] = d
        s["hivol"] = vol.get(d, vmed) > vmed
        groups["expiry" if d in exp_days else "nonexp"].append(s)
    print(json.dumps({"fridays_scored":
                      {k: len(v) for k, v in groups.items()}}),
          flush=True)

    for gname, g in groups.items():
        # descriptive pinning stats
        ledger.append({
            "kind": "f1_descriptive",
            "id": f"F1b_{gname}_afternoon_stats",
            "n": len(g),
            "mean_abs_afternoon_bps": round(statistics.mean(
                [abs(s["afternoon"]) for s in g]), 1),
            "median_pm_range_bps": round(statistics.median(
                [s["pm_range"] for s in g]), 1)})
        # tradeable: fade the morning move into the afternoon
        fade = [(-math.copysign(1, s["morning"]) * s["afternoon"]
                 - RT_ETF, s["day"][:4]) for s in g
                if abs(s["morning"]) > 5]
        cell(f"F1b_{gname}_fade_morning", fade)
        for regime, flag in (("hivol", True), ("lovol", False)):
            fr = [(-math.copysign(1, s["morning"]) * s["afternoon"]
                   - RT_ETF, s["day"][:4]) for s in g
                  if abs(s["morning"]) > 5 and s["hivol"] == flag]
            cell(f"F1b_{gname}_fade_morning_{regime}", fr,
                 note="prespecified: dealer effects stronger hivol")

    # ---- F1c: strike-grid pinning diagnostic ----
    dist = {"expiry": [], "nonexp": []}
    for symname, cs in closes.items():
        if symname in ("SPY", "QQQ", "IWM") or symname.startswith(
                "XL"):
            continue
        for d, c in cs.items():
            if d not in dayset or not (25 <= c <= 500):
                continue
            wd = datetime.strptime(d, "%Y-%m-%d").weekday()
            if wd != 4:
                continue
            x = abs(c / 5 - round(c / 5))  # 0..0.5 of grid
            dist["expiry" if d in exp_days else "nonexp"].append(x)
    for k, v in dist.items():
        ledger.append({"kind": "f1_descriptive",
                       "id": f"F1c_grid_distance_{k}",
                       "n": len(v),
                       "mean_dist_frac_of_grid": round(
                           statistics.mean(v), 4),
                       "note": "uniform (no pinning) -> 0.25"})

    GRAVE.parent.mkdir(parents=True, exist_ok=True)
    with GRAVE.open("w") as g:
        for rec in ledger:
            g.write(json.dumps(rec) + "\n")
    for rec in ledger:
        print(json.dumps(rec), flush=True)


if __name__ == "__main__":
    main()
