"""Incremental-information audit for EARNINGS_NEGATIVE_SURPRISE_DRIFT.

The unconditional short-every-event-day baseline is positive (+21bps
at the open), so the question that decides Alpha #1 is:

    Does NEGATIVE SURPRISE add value beyond "it is an earnings
    reaction session", at EXECUTABLE entries, within the
    timing-certifiable (PM/AMC) subset?

Computes, for cohorts {neg, pos, all} x {pm, am}: short open->close
PnL at entry open/+1m/+5m/+15m, plus the neg-minus-all and
neg-minus-pos increments with date-clustered bootstrap CIs on the
PM +5m cell (the honest executable core). Frozen parent; no tuning.
decision_power: RESEARCH_ONLY_VALIDATION.
"""
from __future__ import annotations

import json
import random
import statistics
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

DATASET = Path("exports/event_dataset.jsonl")
RAW = Path("exports/earnings_events_raw.jsonl")
SN_BARS = Path("/apex-data/history-b/pit_singlename/bars")
ETF_BARS = Path("/apex-data/history-b/etf_continuous/bars")
OUT = Path("results/event_sprint/incremental_audit.json")
NY = ZoneInfo("America/New_York")
DELAYS = {"open": None, "+1m": 571, "+5m": 575, "+15m": 585}


def load_rth(base, sym, date):
    p = base / f"{sym}_{date}.json"
    try:
        bars = json.loads(p.read_text())["bars"]
    except Exception:
        return None
    rth = []
    for b in bars:
        t = datetime.fromisoformat(
            b["event_time_utc"].replace("Z", "+00:00")).astimezone(NY)
        m = t.hour * 60 + t.minute
        if 570 <= m < 960:
            rth.append((m, b))
    return rth or None


def px_after(rth, minute):
    for m, b in rth:
        if m >= minute:
            return b["close"]
    return None


def blk(vals):
    n = len(vals)
    if n < 10:
        return {"n": n, "verdict": "INSUFFICIENT_N"}
    return {"n": n, "mean_bps": round(statistics.mean(vals), 1),
            "median_bps": round(statistics.median(vals), 1),
            "win_rate": round(sum(1 for v in vals if v > 0) / n, 3)}


def main():
    verified = {}
    for l in RAW.open():
        r = json.loads(l)
        verified[(r["symbol"], r["report_date"], r["fiscal_year"],
                  r["fiscal_quarter"])] = bool(r.get("report_verified"))

    rows = [json.loads(l) for l in DATASET.open()]
    spy_cache = {}
    per_delay = defaultdict(list)   # (cohort, timing, delay) -> vals
    events = []                     # for clustered increment test
    for r in rows:
        if r.get("r_close_res") is None:
            continue
        sym, rd = r["symbol"], r["reaction_session"]
        rth = load_rth(SN_BARS, sym, rd)
        if rd not in spy_cache:
            spy_cache[rd] = load_rth(ETF_BARS, "SPY", rd)
        s_rth = spy_cache[rd]
        if not rth or not s_rth:
            continue
        close_px, s_close = rth[-1][1]["close"], s_rth[-1][1]["close"]
        coh = ("neg" if r["sue_price"] < 0
               else "pos" if r["sue_price"] > 0 else "zero")
        ver = verified.get((sym, r["report_date"], r["fiscal_year"],
                            r["fiscal_quarter"]))
        pnl_at = {}
        for k, m in DELAYS.items():
            if m is None:
                e, se = rth[0][1]["open"], s_rth[0][1]["open"]
            else:
                e, se = px_after(rth, m), px_after(s_rth, m)
            if not e or not se or e <= 0:
                continue
            v = -((close_px / e - 1.0) - (s_close / se - 1.0)) * 1e4
            pnl_at[k] = v
            per_delay[(coh, r["timing"], k)].append(v)
            per_delay[("all", r["timing"], k)].append(v)
            per_delay[(coh, "any", k)].append(v)
            per_delay[("all", "any", k)].append(v)
        events.append({"coh": coh, "timing": r["timing"],
                       "date": rd, "verified": ver, "pnl": pnl_at})

    table = {}
    for (coh, tim, k), vals in sorted(per_delay.items()):
        table[f"{coh}|{tim}|{k}"] = blk(vals)

    # date-clustered bootstrap of the PM +5m increment (neg - pos)
    by_date = defaultdict(lambda: {"neg": [], "pos": []})
    for e in events:
        if e["timing"] != "pm" or "+5m" not in e["pnl"]:
            continue
        if e["coh"] in ("neg", "pos"):
            by_date[e["date"]][e["coh"]].append(e["pnl"]["+5m"])
    dates = [d for d, v in by_date.items() if v["neg"] or v["pos"]]
    rng = random.Random(11)
    diffs = []
    for _ in range(2000):
        neg_v, pos_v = [], []
        for d in (rng.choice(dates) for _ in dates):
            neg_v += by_date[d]["neg"]
            pos_v += by_date[d]["pos"]
        if len(neg_v) >= 5 and len(pos_v) >= 5:
            diffs.append(statistics.mean(neg_v)
                         - statistics.mean(pos_v))
    diffs.sort()
    incr = {
        "pm_5m_neg_minus_pos_mean_bps": round(
            statistics.mean(diffs), 1) if diffs else None,
        "pm_5m_neg_minus_pos_95ci": (
            round(diffs[int(0.025 * len(diffs))], 1),
            round(diffs[int(0.975 * len(diffs))], 1)) if diffs else None,
        "frac_boot_below_zero": round(
            sum(1 for d in diffs if d <= 0) / len(diffs), 4)
        if diffs else None}

    ver_counts = defaultdict(int)
    for e in events:
        ver_counts[str(e["verified"])] += 1

    report = {"kind": "incremental_audit",
              "id": "EVENT-NEG-DRIFT-INCREMENTAL-2026-08-30",
              "cohort_x_timing_x_delay": table,
              "pm_5m_clustered_increment": incr,
              "verified_flag_counts": dict(ver_counts),
              "decision_power": "RESEARCH_ONLY_VALIDATION"}
    OUT.write_text(json.dumps(report, indent=1))
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
