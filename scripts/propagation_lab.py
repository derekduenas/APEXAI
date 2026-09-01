"""PROPAGATION-LAB-E-P1 -- incomplete peer propagation study.

Design sealed BEFORE this run (PROPAGATION-LAB-E-P1-2026-08-30).
Leader PM earnings events -> structural SIC-4 peers -> does the
peer's own intraday residual drift in the direction of the leader's
residual overnight gap?

Every examined cell is sealed to the lab graveyard with its search
burden. decision_power: RESEARCH_DISCOVERY_ONLY.
"""
from __future__ import annotations

import json
import statistics
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

DATASET = Path("exports/event_dataset.jsonl")
RAW = Path("exports/earnings_events_raw.jsonl")
PEERS = Path("exports/peer_map_v1.json")
MEMBERSHIP = Path("/apex-data/history-b/pit_singlename/"
                  "membership_v1.jsonl")
TOLL = Path("/apex-data/history-b/pit_singlename/"
            "movement_toll_obs.jsonl")
SN = Path("/apex-data/history-b/pit_singlename/bars")
ETF = Path("/apex-data/history-b/etf_continuous/bars")
GRAVE = Path("results/edge_atlas/propagation_e_p1.jsonl")
NY = ZoneInfo("America/New_York")
UPLIFT, FEES = 1.34, 0.05

_cache = {}


def rth(base, sym, d):
    k = (str(base), sym, d)
    if k in _cache:
        return _cache[k]
    if len(_cache) > 6000:
        _cache.clear()
    try:
        bars = json.loads((base / f"{sym}_{d}.json").read_text())["bars"]
    except Exception:
        _cache[k] = None
        return None
    out = []
    for b in bars:
        t = datetime.fromisoformat(
            b["event_time_utc"].replace("Z", "+00:00")).astimezone(NY)
        m = t.hour * 60 + t.minute
        if 570 <= m < 960:
            out.append((m, b))
    _cache[k] = out or None
    return _cache[k]


def pxa(r, minute):
    for m, b in r:
        if m >= minute:
            return b["close"]
    return None


def main():
    import os
    pm = json.loads(PEERS.read_text())["map"]
    sic_groups = defaultdict(set)
    for s, m in pm.items():
        sic_groups[m["sic4"]].add(s)

    membership = defaultdict(set)
    for l in MEMBERSHIP.read_text().splitlines():
        try:
            r = json.loads(l)
        except Exception:
            continue
        if r.get("kind") == "pit_membership":
            membership[r["member_month"]].update(r["symbols"])

    # every symbol's earnings dates (to exclude peers reporting +/-2d)
    ev_dates = defaultdict(set)
    for l in RAW.open():
        r = json.loads(l)
        ev_dates[r["symbol"]].add(r["report_date"])

    def peer_reports_near(sym, date):
        d0 = datetime.strptime(date, "%Y-%m-%d").date()
        for k in range(-2, 3):
            if (d0 + timedelta(days=k)).isoformat() in ev_dates[sym]:
                return True
        return False

    # toll surface (same convention as event experiments)
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

    spy_days = sorted(f[4:-5] for f in os.listdir(ETF)
                      if f.startswith("SPY_"))
    spos = {d: i for i, d in enumerate(spy_days)}

    def close_res(sym, d0, k):
        """residual close(d0)->close(d0+k sessions)."""
        i = spos.get(d0)
        if i is None or i + k >= len(spy_days):
            return None
        d1 = spy_days[i + k]
        a0, a1 = rth(SN, sym, d0), rth(SN, sym, d1)
        s0, s1 = rth(ETF, "SPY", d0), rth(ETF, "SPY", d1)
        if not all((a0, a1, s0, s1)):
            return None
        return ((a1[-1][1]["close"] / a0[-1][1]["close"] - 1)
                - (s1[-1][1]["close"] / s0[-1][1]["close"] - 1)) * 1e4

    leaders = [json.loads(l) for l in DATASET.open()]
    leaders = [r for r in leaders if r["timing"] == "pm"
               and r.get("gap_res") is not None]

    rows = []
    for ld in leaders:
        sic = pm.get(ld["symbol"], {}).get("sic4")
        if not sic:
            continue
        sess = ld["reaction_session"]
        month = sess[:7]
        peers = (sic_groups[sic] & membership.get(month, set())) \
            - {ld["symbol"]}
        for p in sorted(peers):
            if peer_reports_near(p, ld["report_date"]):
                continue
            pr = rth(SN, p, sess)
            sr = rth(ETF, "SPY", sess)
            if not pr or not sr:
                continue
            e, se = pxa(pr, 575), pxa(sr, 575)
            if not e or not se:
                continue
            intr = ((pr[-1][1]["close"] / e - 1)
                    - (sr[-1][1]["close"] / se - 1)) * 1e4
            sign = 1 if ld["gap_res"] > 0 else -1
            rows.append({
                "leader": ld["symbol"], "peer": p, "session": sess,
                "year": sess[:4], "sic4": sic,
                "leader_gap_bps": ld["gap_res"] * 1e4,
                "leader_dir": sign,
                "follow_intraday_bps": sign * intr,
                "raw_intraday_bps": intr,
                "follow_1s": None, "follow_3s": None,
                "follow_5s": None,
                "rt_bps": rt_bps(p, sess[:4])})
            for k, key in ((1, "follow_1s"), (3, "follow_3s"),
                           (5, "follow_5s")):
                cr = close_res(p, sess, k)
                if cr is not None:
                    rows[-1][key] = sign * cr

    print(json.dumps({"peer_event_rows": len(rows),
                      "leaders_used": len({(r['leader'], r['session'])
                                           for r in rows})}),
          flush=True)

    ledger = []

    def cell(cid, sub, field, note=""):
        vals = [(r[field], r[field] - r["rt_bps"],
                 r[field] - 2 * r["rt_bps"], r["year"])
                for r in sub if r.get(field) is not None]
        n = len(vals)
        rec = {"kind": "prop_cell", "id": cid, "field": field,
               "n": n, "note": note}
        if n >= 50:
            g = [v[0] for v in vals]
            nb = [v[1] for v in vals]
            ns = [v[2] for v in vals]
            yrs = defaultdict(list)
            for v in vals:
                yrs[v[3]].append(v[1])
            ym = {y: round(statistics.mean(x), 1)
                  for y, x in sorted(yrs.items()) if len(x) >= 15}
            rec.update({
                "gross_mean_bps": round(statistics.mean(g), 1),
                "gross_median_bps": round(statistics.median(g), 1),
                "net_base_bps": round(statistics.mean(nb), 1),
                "net_stress_bps": round(statistics.mean(ns), 1),
                "win_net_base": round(
                    sum(1 for x in nb if x > 0) / n, 3),
                "pos_years_base": f"{sum(1 for v in ym.values() if v > 0)}"
                                  f"/{len(ym)}",
                "by_year": ym})
        else:
            rec["verdict"] = "INSUFFICIENT_N"
        ledger.append(rec)
        return rec

    ranked = sorted(rows, key=lambda r: abs(r["leader_gap_bps"]),
                    reverse=True)
    for frac, tag in ((1.0, "all"), (0.5, "top50"), (0.25, "top25"),
                      (0.1, "top10")):
        sub = ranked[:max(1, int(frac * len(ranked)))]
        for f in ("follow_intraday_bps", "follow_1s", "follow_3s",
                  "follow_5s"):
            cell(f"EP1_follow_{tag}", sub, f)
        for tail, keep in (("leaderdown", -1), ("leaderup", 1)):
            tsub = [r for r in sub if r["leader_dir"] == keep]
            for f in ("follow_intraday_bps", "follow_1s",
                      "follow_3s", "follow_5s"):
                cell(f"EP1_follow_{tag}_{tail}", tsub, f)
    # baselines
    cell("BASE_peer_unconditional_drift", rows, "raw_intraday_bps",
         "no direction knowledge: raw peer intraday residual")

    GRAVE.parent.mkdir(parents=True, exist_ok=True)
    with GRAVE.open("w") as g:
        g.write(json.dumps({"kind": "discovery_ledger",
                            "cells_examined": len(ledger),
                            "peer_event_rows": len(rows)}) + "\n")
        for rec in ledger:
            g.write(json.dumps(rec) + "\n")
    scored = [r for r in ledger if "net_base_bps" in r]
    scored.sort(key=lambda r: r["net_base_bps"], reverse=True)
    print(json.dumps({"cells": len(ledger)}), flush=True)
    for r in scored[:8]:
        print(json.dumps(r), flush=True)
    print("WORST 2:", flush=True)
    for r in scored[-2:]:
        print(json.dumps(r), flush=True)


if __name__ == "__main__":
    main()
