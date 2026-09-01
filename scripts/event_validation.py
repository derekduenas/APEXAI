"""EARNINGS_NEGATIVE_SURPRISE_DRIFT_V1 -- adversarial validity audit.

Attacks the nominated result BEFORE any Monster authority:
  B  event-timing certification (pm = certain post-info; am = probable)
  C  execution/edge decay: entry at open, +1m, +5m, +15m (frozen
     parent hypothesis, ALL delays reported -- characterization,
     never delay-selection)
  E  cluster/concentration robustness: date-clustered bootstrap CI,
     leave-one-year-out, leave-one-name-out, top-event contributions
  F  baseline competition on the IDENTICAL cohort and horizon

The parent hypothesis is FROZEN: short every negative surprise at the
first execution observation, cover at the session close, SPY-
residualized, zero selectivity. Nothing here tunes anything.
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
SN_BARS = Path("/apex-data/history-b/pit_singlename/bars")
ETF_BARS = Path("/apex-data/history-b/etf_continuous/bars")
OUT = Path("results/event_sprint/validity_audit.json")
NY = ZoneInfo("America/New_York")
RT_FALLBACK_BPS = 10.0     # only for net figures; gross reported too


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
    """close of the first bar whose minute >= `minute` (executable
    only after that bar completes)."""
    for m, b in rth:
        if m >= minute:
            return b["close"]
    return None


def stats_block(vals, label):
    n = len(vals)
    if n < 10:
        return {"label": label, "n": n, "verdict": "INSUFFICIENT_N"}
    return {"label": label, "n": n,
            "mean_bps": round(statistics.mean(vals), 1),
            "median_bps": round(statistics.median(vals), 1),
            "win_rate": round(sum(1 for v in vals if v > 0) / n, 3),
            "stdev_bps": round(statistics.pstdev(vals), 1)}


def main():
    rows = [json.loads(l) for l in DATASET.open()]
    neg = [r for r in rows if r["sue_price"] < 0
           and r.get("r_close_res") is not None]

    # ---------- B: timing certification ---------------------------
    timing = defaultdict(list)
    for r in neg:
        cls = ("AFTER_MARKET_CLOSE" if r["timing"] == "pm"
               else "BEFORE_MARKET_OPEN" if r["timing"] == "am"
               else "TIMING_UNKNOWN")
        if not r.get("report_verified"):
            cls += "_UNVERIFIED"
        timing[cls].append(-r["r_close_res"] * 1e4)   # short PnL bps
    timing_report = {k: stats_block(v, k)
                     for k, v in sorted(timing.items())}
    certifiable = timing.get("AFTER_MARKET_CLOSE", [])

    # ---------- C: execution decay (recompute from bars) ----------
    decay = {k: [] for k in ("open", "+1m", "+5m", "+15m")}
    entry_minutes = {"open": None, "+1m": 571, "+5m": 575, "+15m": 585}
    n_bars_missing = 0
    for r in neg:
        rth = load_rth(SN_BARS, r["symbol"], r["reaction_session"])
        s_rth = load_rth(ETF_BARS, "SPY", r["reaction_session"])
        if not rth or not s_rth:
            n_bars_missing += 1
            continue
        close_px, s_close = rth[-1][1]["close"], s_rth[-1][1]["close"]
        for k, m in entry_minutes.items():
            if m is None:
                e, se = rth[0][1]["open"], s_rth[0][1]["open"]
            else:
                e, se = px_after(rth, m), px_after(s_rth, m)
            if not e or not se or e <= 0 or se <= 0:
                continue
            raw = close_px / e - 1.0
            spy = s_close / se - 1.0
            decay[k].append(-(raw - spy) * 1e4)       # short, resid
    decay_report = {k: stats_block(v, f"entry_{k}")
                    for k, v in decay.items()}

    # ---------- E: clustering / concentration ---------------------
    pnl = [(-r["r_close_res"] * 1e4, r["reaction_session"],
            r["symbol"], r["reaction_session"][:4]) for r in neg]
    base_mean = statistics.mean(p[0] for p in pnl)

    by_date = defaultdict(list)
    for p in pnl:
        by_date[p[1]].append(p[0])
    dates = list(by_date)
    rng = random.Random(7)
    boot = []
    for _ in range(2000):
        sample = [v for d in (rng.choice(dates)
                              for _ in dates) for v in by_date[d]]
        boot.append(statistics.mean(sample))
    boot.sort()
    ci = (round(boot[int(0.025 * len(boot))], 1),
          round(boot[int(0.975 * len(boot))], 1))

    loyo = {}
    for y in sorted({p[3] for p in pnl}):
        rest = [p[0] for p in pnl if p[3] != y]
        loyo[y] = round(statistics.mean(rest), 1)
    by_name = defaultdict(list)
    for p in pnl:
        by_name[p[2]].append(p[0])
    lono_means = []
    worst_name, worst_mean = None, None
    for s in by_name:
        rest = [p[0] for p in pnl if p[2] != s]
        m = statistics.mean(rest)
        lono_means.append(m)
        if worst_mean is None or m < worst_mean:
            worst_name, worst_mean = s, m
    total = sum(p[0] for p in pnl)
    ev_sorted = sorted(pnl, key=lambda p: p[0], reverse=True)
    name_tot = {s: sum(v) for s, v in by_name.items()}
    date_tot = {d: sum(v) for d, v in by_date.items()}
    yr_tot = defaultdict(float)
    for p in pnl:
        yr_tot[p[3]] += p[0]
    top_name = max(name_tot, key=name_tot.get)
    top_date = max(date_tot, key=date_tot.get)
    top_year = max(yr_tot, key=yr_tot.get)

    def contrib(x):
        return round(100 * x / total, 1) if total else None

    concentration = {
        "n_events": len(pnl), "n_distinct_dates": len(dates),
        "n_distinct_names": len(by_name),
        "mean_bps": round(base_mean, 1),
        "date_clustered_bootstrap_95ci_bps": ci,
        "boot_frac_mean_below_zero": round(
            sum(1 for b in boot if b <= 0) / len(boot), 4),
        "leave_one_year_out_mean_bps": loyo,
        "loyo_min": round(min(loyo.values()), 1),
        "lono_min_mean_bps": round(min(lono_means), 1),
        "lono_worst_excluded_name": worst_name,
        "top_name": {top_name: contrib(name_tot[top_name])},
        "top_date": {top_date: contrib(date_tot[top_date])},
        "top_year": {top_year: contrib(yr_tot[top_year])},
        "top5_events_pct_of_total": contrib(
            sum(p[0] for p in ev_sorted[:5])),
        "top10_events_pct_of_total": contrib(
            sum(p[0] for p in ev_sorted[:10])),
        "mean_excl_top5_bps": round(statistics.mean(
            [p[0] for p in ev_sorted[5:]]), 1),
        "mean_excl_top10_bps": round(statistics.mean(
            [p[0] for p in ev_sorted[10:]]), 1)}

    # ---------- F: baselines on identical timing/horizon ----------
    all_ev = [r for r in rows if r.get("r_close_res") is not None]
    baselines = {
        "cash": {"mean_bps": 0.0, "n": len(neg)},
        "short_everything_unconditional": stats_block(
            [-r["r_close_res"] * 1e4 for r in all_ev], "uncond"),
        "raw_gap_direction_follow": stats_block(
            [(1 if r["gap_res"] > 0 else -1) * r["r_close_res"] * 1e4
             for r in all_ev if r.get("gap_res")], "gapdir"),
        "post_open_momentum_30m": stats_block(
            [((1 if r["r30_res"] > 0 else -1)
              * ((1 + r["r_close_res"]) / (1 + r["r30_res"]) - 1) * 1e4)
             for r in all_ev
             if r.get("r30_res") is not None and r["r30_res"] != 0],
            "mom30_enter_1000_exit_close"),
        "note": "all SPY-residualized; sector-adjusted NOT_ESTIMABLE "
                "(no sealed PIT sector map)"}

    report = {
        "kind": "validity_audit",
        "id": "EVENT-NEG-DRIFT-VALIDITY-AUDIT-2026-08-30",
        "parent": "short all negative surprises at first execution "
                  "observation, cover at close, SPY-residualized",
        "B_timing": timing_report,
        "B_certifiable_pm_only": stats_block(
            certifiable, "AFTER_MARKET_CLOSE_all"),
        "C_execution_decay": decay_report,
        "C_bars_missing": n_bars_missing,
        "E_concentration": concentration,
        "F_baselines": baselines,
        "decision_power": "RESEARCH_ONLY_VALIDATION"}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=1))
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
