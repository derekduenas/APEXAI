"""ALPHA DISCOVERY EXPERIMENTS — E1..E8 over the sprint dataset.

Mechanism-first, distributions-not-verdicts, every family counted in
the multiplicity ledger, negative results recorded beside winners.
Costs: OPTIMISTIC = half observed spread; BASE = observed spread +
fees + 25% adverse; STRESS = 2x BASE. Net returns computed HERE, per
row, from the dataset's spread field -- never baked into the data.

Independence discipline: raw rows are 15-min overlapping samples;
every family reports effective n as SESSION count (block unit = day)
and stability by year. Monte Carlo blocks by session.

decision_power: RESEARCH_DISCOVERY_ONLY.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402

from apex.governance.chain_ledger import chain_append  # noqa: E402

OUT = Path("results/alpha_discovery")
DS = OUT / "dataset.npz"
LEDGER = OUT / "experiments.jsonl"
FEES_BPS = 0.05


class D:
    def __init__(self):
        z = np.load(DS, allow_pickle=True)
        self.X = z["X"]
        self.day = z["day"]
        self.sym = z["sym"]
        self.fields = list(z["fields"])
        self.year = np.array([int(d[:4]) for d in self.day])
        self.i = {f: self.fields.index(f) for f in self.fields}

    def c(self, f):
        return self.X[:, self.i[f]]


def net(d: D, fwd: str, case: str) -> np.ndarray:
    """Round-trip net return for a hypothetical taker round trip in
    the SIGN of the forward move (capture framing, direction-agnostic
    at atlas level -- experiments that take sides use signed nets)."""
    sp = d.c("spread_bps") / 1e4
    base = sp + FEES_BPS / 1e4 + 0.25 * sp
    cost = {"OPT": 0.5 * sp, "BASE": base, "STRESS": 2 * base}[case]
    return d.c(fwd), cost


def _stats(vals, days):
    if len(vals) < 50:
        return None
    q = np.quantile(vals, [0.1, 0.25, 0.5, 0.75, 0.9])
    return {"n": int(len(vals)),
            "eff_n_sessions": int(len(set(days))),
            "mean_bps": round(float(vals.mean()) * 1e4, 1),
            "median_bps": round(float(q[2]) * 1e4, 1),
            "win": round(float((vals > 0).mean()), 3),
            "q10_q90_bps": [round(float(q[0]) * 1e4, 1),
                            round(float(q[4]) * 1e4, 1)]}


def yearly(vals, years):
    out = {}
    for y in sorted(set(years)):
        m = years == y
        if m.sum() >= 30:
            out[int(y)] = round(float(vals[m].mean()) * 1e4, 1)
    return out


COUNT = {"families": 0}


def family(d, name, mask, direction, fwd="f60"):
    """One tested state family. direction: +1 long the state, -1
    short it. Reports BASE and STRESS signed net economics."""
    COUNT["families"] += 1
    rec = {"family": name, "kind": "state_family"}
    raw, base_cost = net(d, fwd, "BASE")
    _, stress_cost = net(d, fwd, "STRESS")
    v = direction * raw[mask]
    days = d.day[mask]
    years = d.year[mask]
    s = _stats(v, days)
    if s is None:
        rec["verdict"] = "INSUFFICIENT_N"
        chain_append(LEDGER, rec)
        return rec
    vb = v - base_cost[mask]
    vs = v - stress_cost[mask]
    rec.update(gross=s,
               base_mean_bps=round(float(vb.mean()) * 1e4, 1),
               base_win=round(float((vb > 0).mean()), 3),
               stress_mean_bps=round(float(vs.mean()) * 1e4, 1),
               mfe_med_bps=round(float(np.median(
                   direction * d.c("mfe90" if direction > 0
                                   else "mae90")[mask])) * 1e4, 1),
               by_year_base_bps={y: round(m - float(
                   base_cost[mask][years == y].mean()) * 1e4, 1)
                   for y, m in yearly(v, years).items()},
               )
    yb = rec["by_year_base_bps"]
    pos_years = sum(1 for x in yb.values() if x > 0)
    rec["year_consistency"] = f"{pos_years}/{len(yb)}"
    rec["verdict"] = ("BASE_POSITIVE" if rec["base_mean_bps"] > 0
                      and pos_years >= len(yb) * 0.7 else
                      "BASE_POSITIVE_UNSTABLE"
                      if rec["base_mean_bps"] > 0 else "NEGATIVE")
    chain_append(LEDGER, rec)
    return rec


def q(d, f, lo=None, hi=None):
    v = d.c(f)
    m = np.ones(len(v), dtype=bool)
    if lo is not None:
        m &= v >= np.quantile(v, lo)
    if hi is not None:
        m &= v <= np.quantile(v, hi)
    return m


def run_all():
    d = D()
    print(json.dumps({"rows": len(d.X),
                      "sessions": len(set(d.day))}), flush=True)
    results = []

    # ---- E1 ATLAS: broad single-dimension surfaces (both sides)
    for f in ("resid_r30", "resid_r60", "r30_atr", "rvol",
              "vwap_dist_atr", "xsec_rank_resid30", "or_position",
              "gap_atr", "breadth_above_vwap"):
        for tail, dirn, tag in ((0.9, +1, "hi_cont"),
                                (0.9, -1, "hi_fade"),
                                (0.1, -1, "lo_cont"),
                                (0.1, +1, "lo_fade")):
            m = q(d, f, lo=tail) if tail == 0.9 else q(d, f, hi=tail)
            results.append(family(
                d, f"E1:{f}:{tag}", m, dirn))

    # ---- E4 RESIDUAL vs RAW momentum, matched construction
    for f, nm in (("resid_r30", "residual30"), ("r30", "raw30"),
                  ("spy_r30", "market30"), ("sector_r30",
                                            "sector30")):
        m = q(d, f, lo=0.9)
        results.append(family(d, f"E4:{nm}_top10_cont", m, +1))

    # ---- E2 SELECTIVITY: monotonicity on the residual rank
    sel = {}
    raw, base_cost = net(d, "f60", "BASE")
    for pct, tag in ((0.5, "top50"), (0.75, "top25"), (0.9, "top10"),
                     (0.95, "top5"), (0.99, "top1")):
        COUNT["families"] += 1
        m = d.c("xsec_rank_resid30") >= pct
        v = raw[m] - base_cost[m]
        sel[tag] = {"n": int(m.sum()),
                    "base_mean_bps": round(float(v.mean()) * 1e4, 1),
                    "win": round(float((v > 0).mean()), 3)}
        # and the short side of the bottom rank
        mb = d.c("xsec_rank_resid30") <= 1 - pct
        vb = -raw[mb] - base_cost[mb]
        sel[tag]["short_bottom_base_bps"] = round(
            float(vb.mean()) * 1e4, 1)
    chain_append(LEDGER, {"family": "E2:selectivity_ladder",
                          "ladder": sel})

    # ---- E3 CONTINUATION vs REVERSAL on extreme 30m moves
    ext = np.abs(d.c("r30_atr")) >= np.quantile(
        np.abs(d.c("r30_atr")), 0.95)
    sgn = np.sign(d.c("r30_atr"))
    cont = sgn * d.c("f60")           # + = continued
    conds = {
        "rvol_hi": d.c("rvol") >= np.quantile(d.c("rvol"), 0.8),
        "rvol_lo": d.c("rvol") <= np.quantile(d.c("rvol"), 0.2),
        "sector_confirms": np.sign(d.c("sector_r30")) == sgn,
        "sector_diverges": np.sign(d.c("sector_r30")) != sgn,
        "market_confirms": np.sign(d.c("spy_r30")) == sgn,
        "residual_dominant": np.abs(d.c("resid_r30"))
        >= 0.8 * np.abs(d.c("r30")),
        "beta_dominant": np.abs(d.c("resid_r30"))
        <= 0.3 * np.abs(d.c("r30")),
        "spread_wide": d.c("spread_bps")
        >= np.quantile(d.c("spread_bps"), 0.8),
        "morning": d.c("minute_of_day") <= 0.25,
        "afternoon": d.c("minute_of_day") >= 0.75,
    }
    e3 = {}
    for nm, cm in conds.items():
        COUNT["families"] += 1
        m = ext & cm
        if m.sum() < 200:
            continue
        v = cont[m]
        e3[nm] = {"n": int(m.sum()),
                  "mean_cont_bps": round(float(v.mean()) * 1e4, 1),
                  "cont_rate": round(float((v > 0).mean()), 3),
                  "by_year": yearly(v, d.year[m])}
    chain_append(LEDGER, {"family": "E3:continuation_map",
                          "baseline_all_ext": {
                              "n": int(ext.sum()),
                              "mean_cont_bps": round(float(
                                  cont[ext].mean()) * 1e4, 1),
                              "cont_rate": round(float(
                                  (cont[ext] > 0).mean()), 3)},
                          "conditions": e3})

    # ---- E5 OPENING DRIVE + ablations
    early = d.c("minute_of_day") <= 0.2
    drive = (np.abs(d.c("resid_r30")) >= np.quantile(
        np.abs(d.c("resid_r30")), 0.85))
    sgn_r = np.sign(d.c("resid_r30"))
    full = (early & drive
            & (d.c("rvol") >= 1.5)
            & (np.sign(d.c("sector_r30")) == sgn_r)
            & (sgn_r * d.c("vwap_dist_atr") > 0))
    cont_r = sgn_r * d.c("f60")
    ab = {}
    for nm, m in (("full", full),
                  ("no_rvol", early & drive
                   & (np.sign(d.c("sector_r30")) == sgn_r)
                   & (sgn_r * d.c("vwap_dist_atr") > 0)),
                  ("no_sector", early & drive & (d.c("rvol") >= 1.5)
                   & (sgn_r * d.c("vwap_dist_atr") > 0)),
                  ("no_vwap", early & drive & (d.c("rvol") >= 1.5)
                   & (np.sign(d.c("sector_r30")) == sgn_r)),
                  ("drive_only", early & drive)):
        COUNT["families"] += 1
        if m.sum() < 100:
            continue
        raw60, bc = net(d, "f60", "BASE")
        v = cont_r[m] - bc[m]
        ab[nm] = {"n": int(m.sum()),
                  "base_mean_bps": round(float(v.mean()) * 1e4, 1),
                  "win": round(float((v > 0).mean()), 3),
                  "by_year": yearly(cont_r[m] - bc[m], d.year[m])}
    chain_append(LEDGER, {"family": "E5:opening_drive_ablation",
                          "arms": ab})

    # ---- E6 LIQUIDITY REVERSAL: extreme residual + wide spread,
    #      fade it (v1 proxy without tick-level exhaustion signals)
    for nm, m, dirn in (
        ("E6:ext_resid_dn_wide_spread_fade",
         (d.c("resid_r30") <= np.quantile(d.c("resid_r30"), 0.05))
         & (d.c("spread_bps") >= np.quantile(d.c("spread_bps"),
                                             0.8)), +1),
        ("E6:ext_resid_up_wide_spread_fade",
         (d.c("resid_r30") >= np.quantile(d.c("resid_r30"), 0.95))
         & (d.c("spread_bps") >= np.quantile(d.c("spread_bps"),
                                             0.8)), -1),
        ("E6:ext_resid_dn_normal_spread_fade",
         (d.c("resid_r30") <= np.quantile(d.c("resid_r30"), 0.05))
         & (d.c("spread_bps") <= np.quantile(d.c("spread_bps"),
                                             0.5)), +1)):
        results.append(family(d, nm, m, dirn))

    chain_append(LEDGER, {"kind": "multiplicity_ledger",
                          "families_tested": COUNT["families"]})
    print(json.dumps({"families_tested": COUNT["families"]}))


def monte_carlo(family_mask_expr: str, direction: int,
                risk_fracs=(0.0025, 0.005, 0.0075, 0.01),
                n_paths=100_000):
    """E8: block-bootstrap by session on a family's BASE-net episode
    returns; fixed fractions; characterization only."""
    d = D()
    m = eval(family_mask_expr, {"d": d, "q": q, "np": np})  # noqa: S307
    raw, bc = net(d, "f60", "BASE")
    v = direction * raw[m] - bc[m]
    days = d.day[m]
    per_day = defaultdict(list)
    for r, dy in zip(v, days):
        per_day[dy].append(float(r))
    day_keys = sorted(per_day)
    rng = np.random.default_rng(7)
    n_days = len(day_keys)
    out = {}
    for f in risk_fracs:
        finals, dds, streaks = [], [], []
        for _ in range(n_paths // 10):      # 10k paths is plenty
            eq, peak, dd, ls, cur = 1.0, 1.0, 0.0, 0, 0
            for di in rng.integers(0, n_days, 252):
                for r in per_day[day_keys[di]]:
                    eq *= (1 + f * (r / 0.01))   # r scaled per 1% risk
                    peak = max(peak, eq)
                    dd = max(dd, 1 - eq / peak)
                    cur = cur + 1 if r <= 0 else 0
                    ls = max(ls, cur)
            finals.append(eq)
            dds.append(dd)
            streaks.append(ls)
        fin = np.array(finals)
        out[f"risk_{f}"] = {
            "median_annual": round(float(np.median(fin)) - 1, 4),
            "p10_annual": round(float(np.quantile(fin, 0.1)) - 1, 4),
            "p90_annual": round(float(np.quantile(fin, 0.9)) - 1, 4),
            "prob_negative_year": round(float((fin < 1).mean()), 3),
            "median_maxdd": round(float(np.median(dds)), 4),
            "p95_maxdd": round(float(np.quantile(dds, 0.95)), 4),
            "prob_dd_gt20": round(float((np.array(dds)
                                         > 0.2).mean()), 3),
            "max_losing_streak_p90": int(np.quantile(streaks, 0.9))}
    chain_append(LEDGER, {"kind": "monte_carlo",
                          "mask": family_mask_expr,
                          "direction": direction, "episodes": len(v),
                          "sessions": n_days, "results": out})
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-all", action="store_true")
    ap.add_argument("--mc", nargs=2, metavar=("MASK", "DIR"))
    a = ap.parse_args()
    if a.run_all:
        run_all()
    if a.mc:
        monte_carlo(a.mc[0], int(a.mc[1]))
