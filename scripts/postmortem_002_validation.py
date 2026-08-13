#!/usr/bin/env python
"""APEX-002 validation post-mortem. DIAGNOSIS ONLY.

Asks one question: why is the mean IC positive (+0.0116548) while the primary
t-statistic is weak (+0.6538)?

WHAT THIS IS NOT
----------------
Not a re-evaluation. The APEX-002 validation verdict is recorded, closed, and
unaffected by anything here: no ledger write, no credit, no unlock token, no
holdout access, no new verdict. Nothing in the repository is modified.

Not a search. No parameter is varied, no threshold is moved, no alternative
formulation is tried. A diagnostic that reports "the result improves if X"
converts a clean failed experiment into researcher's degrees of freedom, which
is the specific thing a pre-registered protocol exists to prevent. Every
statistic below decomposes the recorded number; none replaces it.

REPRODUCTION GATE
-----------------
The daily IC series is recomputed from the same frozen snapshot through the
same production path. If the recomputed mean IC and t-statistic do not match
the recorded artifact to 1e-12, the script ABORTS -- a decomposition of a
series that differs from the one that produced the verdict would be a
post-mortem of the wrong patient.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from apex.config import load_config  # noqa: E402
from apex.data.production_source import build_production_panel  # noqa: E402
from apex.evaluate.ic import cross_sectional_ic, newey_west_tstat, simple_tstat  # noqa: E402
from apex.experiments import apex002  # noqa: E402

ROOT = Path("data/snapshots/sharadar/current")
ARTIFACT = Path("results/validation_APEX-002.json")
OUT = Path("results/002_postmortem.txt")
PERIOD = "validation"


def main() -> int:  # noqa: C901
    t0 = time.time()
    log: list[str] = []

    def say(line: str = "") -> None:
        log.append(line)
        print(line, flush=True)

    def head(title: str) -> None:
        say("=" * 78)
        say(title)
        say("=" * 78)

    cfg = load_config("experiment", "costs", "synthetic", "sharadar")
    recorded = json.loads(ARTIFACT.read_text())
    rec_daily = recorded["raw"]["ic_daily_newey_west"]
    rec_grid = recorded["raw"]["ic_non_overlapping"]

    head("APEX-002 VALIDATION POST-MORTEM -- DIAGNOSIS ONLY")
    say("  recorded verdict : FAILURE (unchanged; this script records nothing)")
    say(f"  period           : {cfg.period(PERIOD)['start']} .. {cfg.period(PERIOD)['end']}")
    say("  no ledger write, no credit, no unlock, no holdout, no new verdict")
    say()

    # -- rebuild the exact series the verdict came from ---------------------
    print(f"  [{time.time()-t0:5.0f}s] building panel ...", file=sys.stderr, flush=True)
    panel, _ = build_production_panel(
        ROOT, cfg, cfg.get("calendar.lake_start"), cfg.period(PERIOD)["end"]
    )
    print(f"  [{time.time()-t0:5.0f}s] running production signal path ...",
          file=sys.stderr, flush=True)
    output, _ = apex002.build_nsi_output(panel, cfg, ROOT)

    start, end = cfg.period(PERIOD)["start"], cfg.period(PERIOD)["end"]
    daily_dates = output.calendar.daily_formation_dates(start, end)
    grid_dates = output.calendar.grid_formation_dates(start, end)
    min_names = int(cfg.get("evaluation.min_names_for_ic"))
    lag = int(cfg.get("evaluation.newey_west_lag"))

    score = output.scores.apex_score
    excess = output.forward_returns.excess
    eligible = output.universe.eligible

    ic, count = cross_sectional_ic(
        score.loc[daily_dates], excess.loc[daily_dates],
        eligible.loc[daily_dates], min_names,
    )
    ic = ic.dropna()
    count = count.reindex(ic.index)
    t_stat, p_value = newey_west_tstat(ic, lag)

    ic_g, _ = cross_sectional_ic(
        score.loc[grid_dates], excess.loc[grid_dates],
        eligible.loc[grid_dates], min_names,
    )
    ic_g = ic_g.dropna()
    t_g, p_g = simple_tstat(ic_g)

    head("REPRODUCTION GATE")
    checks = [
        ("mean IC", float(ic.mean()), rec_daily["mean_ic"]),
        ("std IC", float(ic.std(ddof=1)), rec_daily["std_ic"]),
        ("t-statistic", float(t_stat), rec_daily["t_stat"]),
        ("p-value", float(p_value), rec_daily["p_value"]),
        ("n_periods", float(len(ic)), float(rec_daily["n_periods"])),
        ("robustness t", float(t_g), rec_grid["t_stat"]),
    ]
    ok = True
    for name, got, want in checks:
        match = abs(got - want) < 1e-12
        ok &= match
        say(f"  {name:<14} recomputed {got:+.12f}   recorded {want:+.12f}   "
            f"{'MATCH' if match else 'DIFFERS'}")
    say()
    if not ok:
        say("  ABORT: the recomputed series is not the one that produced the")
        say("  verdict. Any decomposition below would describe a different")
        say("  object. Nothing further is reported.")
        OUT.write_text("\n".join(log) + "\n")
        return 1
    say("  The series below IS the series the recorded verdict came from.")
    say()

    n = len(ic)
    mean_ic = float(ic.mean())

    # === 1. DISTRIBUTION OF DAILY ICs =====================================
    head("1. DISTRIBUTION OF DAILY ICs")
    for q in (1, 5, 10, 25, 50, 75, 90, 95, 99):
        say(f"  p{q:<3}                        {ic.quantile(q/100):+.6f}")
    say(f"  {'mean':<28} {mean_ic:+.6f}")
    say(f"  {'std':<28} {ic.std(ddof=1):+.6f}")
    say(f"  {'min / max':<28} {ic.min():+.6f} / {ic.max():+.6f}")
    say(f"  {'skew':<28} {ic.skew():+.6f}")
    say(f"  {'kurtosis (excess)':<28} {ic.kurtosis():+.6f}")
    say()
    say(f"  mean / std (information ratio) : {mean_ic/ic.std(ddof=1):+.6f}")
    say(f"  observations                   : {n}")
    say()

    # === 2. CONCENTRATION =================================================
    head("2. IS THE POSITIVE MEAN CONCENTRATED IN A FEW DATES?")
    total = ic.sum()
    ranked = ic.sort_values(ascending=False)
    say(f"  sum of all daily ICs           : {total:+.6f}")
    say()
    say(f"  {'top-k dates':<18} {'sum':>12} {'share of total':>16}")
    for k in (1, 5, 10, 25, 50, 100):
        s = ranked.head(k).sum()
        say(f"  {'top ' + str(k):<18} {s:>+12.6f} {s/total:>15.1%}")
    say()
    say(f"  {'bottom-k dates':<18} {'sum':>12} {'share of total':>16}")
    for k in (1, 5, 10, 25, 50, 100):
        s = ranked.tail(k).sum()
        say(f"  {'bottom ' + str(k):<18} {s:>+12.6f} {s/total:>15.1%}")
    say()
    # How many of the largest dates must be removed to erase the mean?
    running = 0.0
    removed = 0
    for v in ranked:
        if total - running <= 0:
            break
        running += v
        removed += 1
    say(f"  dates that must be removed for the mean to reach zero: {removed}"
        f"  ({removed/n:.1%} of {n})")
    say()

    # === 3. SIGN STABILITY ================================================
    head("3. SIGN STABILITY ACROSS THE VALIDATION PERIODS")
    pos, neg, zero = int((ic > 0).sum()), int((ic < 0).sum()), int((ic == 0).sum())
    say(f"  positive IC dates              : {pos:>5}  ({pos/n:.2%})")
    say(f"  negative IC dates              : {neg:>5}  ({neg/n:.2%})")
    say(f"  exactly zero                   : {zero:>5}  ({zero/n:.2%})")
    say(f"  mean of positive dates         : {ic[ic > 0].mean():+.6f}")
    say(f"  mean of negative dates         : {ic[ic < 0].mean():+.6f}")
    say()
    flips = int((np.sign(ic.to_numpy()[1:]) != np.sign(ic.to_numpy()[:-1])).sum())
    say(f"  sign changes between consecutive dates : {flips} of {n-1}"
        f"  ({flips/(n-1):.1%})")
    say(f"  lag-1 autocorrelation of IC            : {ic.autocorr(1):+.6f}")
    say(f"  lag-20 autocorrelation of IC           : {ic.autocorr(20):+.6f}")
    say()

    # === 4. YEAR BY YEAR ==================================================
    head("4. YEAR BY YEAR")
    say(f"  {'year':<6} {'n':>5} {'mean IC':>11} {'std':>10} {'t (NW-25)':>11} "
        f"{'p':>9} {'% pos':>8}")
    yearly = {}
    for year, idx in sorted(ic.groupby(ic.index.year).groups.items()):
        sub = ic.loc[idx]
        ty, py = newey_west_tstat(sub, lag)
        say(f"  {year:<6} {len(sub):>5} {sub.mean():>+11.6f} {sub.std(ddof=1):>10.6f} "
            f"{ty:>+11.4f} {py:>9.4f} {(sub > 0).mean():>7.1%}")
        yearly[year] = (len(sub), float(sub.mean()), float(ty))
    say()
    say("  contribution to the full-period mean:")
    for year, (ny, my, _) in yearly.items():
        say(f"    {year}  {ny * my / (n * mean_ic):>7.1%} of the total")
    say()

    # === 5. CALENDAR / REGIME =============================================
    head("5. CALENDAR AND REGIME CONCENTRATION")
    say("  by quarter:")
    say(f"    {'quarter':<10} {'n':>5} {'mean IC':>11} {'% pos':>8}")
    q_index = ic.index.to_period("Q")
    for quarter, idx in sorted(ic.groupby(q_index).groups.items()):
        sub = ic.loc[idx]
        say(f"    {str(quarter):<10} {len(sub):>5} {sub.mean():>+11.6f} "
            f"{(sub > 0).mean():>7.1%}")
    say()
    say("  by calendar month (pooled across years):")
    say(f"    {'month':<6} {'n':>5} {'mean IC':>11}")
    for month, idx in sorted(ic.groupby(ic.index.month).groups.items()):
        sub = ic.loc[idx]
        say(f"    {month:<6} {len(sub):>5} {sub.mean():>+11.6f}")
    say()
    # Benchmark-based regime split, using data already in the panel.
    bench = output.panel.benchmark_tr.reindex(ic.index)
    bench_ret = bench.pct_change(20)
    up = bench_ret > 0
    say("  by trailing 20-day benchmark direction:")
    for label, mask in (("benchmark up", up), ("benchmark down", ~up)):
        sub = ic[mask.reindex(ic.index).fillna(False)]
        if len(sub) > 1:
            tt, _ = newey_west_tstat(sub, lag)
            say(f"    {label:<16} n={len(sub):>4}  mean {sub.mean():>+.6f}  "
                f"t {tt:>+.4f}")
    say()

    # === 6. BREADTH =======================================================
    head("6. CROSS-SECTIONAL BREADTH vs IC MAGNITUDE")
    say(f"  names per date  min/median/max : {int(count.min())} / "
        f"{int(count.median())} / {int(count.max())}")
    say(f"  correlation(count, IC)         : {count.corr(ic):+.6f}")
    say(f"  correlation(count, |IC|)       : {count.corr(ic.abs()):+.6f}")
    say()
    say(f"  {'breadth quintile':<20} {'n':>5} {'mean names':>12} {'mean IC':>11} {'std IC':>10}")
    quintile = pd.qcut(count, 5, labels=False, duplicates="drop")
    for qi, idx in sorted(pd.Series(quintile, index=count.index).groupby(quintile).groups.items()):
        sub = ic.loc[idx]
        say(f"  {'Q' + str(int(qi) + 1):<20} {len(sub):>5} "
            f"{count.loc[idx].mean():>12.1f} {sub.mean():>+11.6f} "
            f"{sub.std(ddof=1):>10.6f}")
    say()
    say("  1/sqrt(breadth) reference: a cross-sectional correlation on N names")
    say("  has sampling standard error near 1/sqrt(N).")
    say(f"    median N                     : {int(count.median())}")
    say(f"    1/sqrt(median N)             : {1/np.sqrt(count.median()):.6f}")
    say(f"    observed std of daily IC     : {ic.std(ddof=1):.6f}")
    say()

    # === 7. PRIMARY vs ROBUSTNESS =========================================
    head("7. PRIMARY (DAILY) vs ROBUSTNESS (NON-OVERLAPPING)")
    say(f"  {'':<22} {'daily':>14} {'non-overlapping':>18}")
    say(f"  {'n periods':<22} {len(ic):>14} {len(ic_g):>18}")
    say(f"  {'mean IC':<22} {ic.mean():>+14.6f} {ic_g.mean():>+18.6f}")
    say(f"  {'std IC':<22} {ic.std(ddof=1):>14.6f} {ic_g.std(ddof=1):>18.6f}")
    say(f"  {'t-statistic':<22} {t_stat:>+14.4f} {t_g:>+18.4f}")
    say(f"  {'p-value':<22} {p_value:>14.4f} {p_g:>18.4f}")
    say(f"  {'% positive':<22} {(ic > 0).mean():>13.1%} {(ic_g > 0).mean():>17.1%}")
    say()
    diff = ic_g.mean() - ic.mean()
    say(f"  difference in mean IC          : {diff:+.6f}")
    say(f"  daily std / sqrt(n_daily)      : {ic.std(ddof=1)/np.sqrt(len(ic)):.6f}")
    say(f"  the grid dates are a subset of the daily dates: "
        f"{set(ic_g.index).issubset(set(ic.index))}")
    say()

    # === 8. STRUCTURE vs NOISE ============================================
    head("8. STRUCTURE, NOISE, OR SUBPERIOD CONCENTRATION -- OBSERVATIONS")
    say("  Observations only. Interpretation is reported separately below.")
    say()
    half = n // 2
    for label, sub in (("first half", ic.iloc[:half]), ("second half", ic.iloc[half:])):
        tt, pp = newey_west_tstat(sub, lag)
        say(f"    {label:<14} n={len(sub):>4}  mean {sub.mean():>+.6f}  "
            f"t {tt:>+.4f}  p {pp:.4f}")
    say()
    years_positive = sum(1 for _, (_, m, _) in yearly.items() if m > 0)
    say(f"  years with positive mean IC    : {years_positive} of {len(yearly)}")
    say(f"  years with t >= 2.92           : "
        f"{sum(1 for _, (_, _, ty) in yearly.items() if ty >= 2.92)} of {len(yearly)}")
    say(f"  HAC inflation factor (std of t under null, recorded) : "
        f"{recorded['raw']['estimator_disclosure']['sd_of_t_under_null']}")
    say()

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(log) + "\n")
    print(f"\n  [{time.time()-t0:5.0f}s] wrote {OUT}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
