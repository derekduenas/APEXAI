#!/usr/bin/env python
"""H3 STRUCTURAL STUDY -- in-sample only, descriptive only. NO credit, NO look.

Maps how the pre-registered H3 composite (equal rank weights on
val_book_to_market + prof_gross_profitability, higher = better) BEHAVES on
the unlocked in-sample window (2005-2017), on the registered small-cap
universe. Nothing here selects, optimises, or claims profitability; nothing
touches validation or holdout; every measured quantity is reported.

Sections: decile curve shape / rank breadth / turnover & persistence /
regime slices (descriptive) / factor decomposition (incl. the 2x2
value-x-profitability quadrant, the interaction the hypothesis is ABOUT) /
raw material for extraction implications.

In-sample has no statistical standing (protocol section 7). This study
informs the HUMAN decision on Credit 5; it can never substitute for it.
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
from apex.experiments import apex003  # noqa: E402
from apex.features.factory import build_features  # noqa: E402
from apex.features.registry import built_specs  # noqa: E402

ROOT = Path("data/snapshots/sharadar/current")
OUT = Path("results/h3_structural_study.json")


def progress(msg):
    print(f"  [{time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


def main() -> int:
    cfg = load_config("experiment", "costs", "synthetic", "sharadar")
    in_start, in_end = cfg.period("in_sample")["start"], cfg.period("in_sample")["end"]
    assert pd.Timestamp(in_end) < pd.Timestamp(cfg.period("validation")["start"])

    progress("building in-sample panel (registered small-cap universe)")
    panel, _ = build_production_panel(ROOT, cfg, cfg.get("calendar.lake_start"), in_end)
    output, _ = apex003.build_gp_output(panel, cfg, ROOT)

    spec = next(x for x in built_specs() if x.feature_id == "val_book_to_market")
    values, known, _ = build_features(ROOT, panel, (spec,))
    btm = values["val_book_to_market"]
    gp_score = output.scores.apex_score

    grid = output.calendar.grid_formation_dates(in_start, in_end)
    grid = pd.DatetimeIndex([d for d in grid
                             if output.scores.apex_score.loc[d].notna().sum() >= 200])
    assert grid.max() <= pd.Timestamp(in_end)
    elig = output.universe.eligible.loc[grid]

    # H3 composite exactly as the paper track / registered packet define it.
    r_gp = gp_score.loc[grid].where(elig).rank(axis=1, ascending=True, pct=True)
    r_val = btm.loc[grid].where(elig).rank(axis=1, ascending=True, pct=True)
    comp = (r_gp + r_val) / 2

    ret = output.forward_returns.excess.loc[grid].where(elig)
    ex = ret.sub(ret.mean(axis=1), axis=0)          # excess vs universe EW; baseline cancels
    years = grid.year

    def decile_of(rank_pct):
        return np.ceil(rank_pct * 10).clip(1, 10)   # 10 = top (highest composite)

    d_comp = decile_of(comp)
    report: dict = {"window": {"start": str(grid[0].date()), "end": str(grid[-1].date()),
                               "grid_dates": len(grid)},
                    "universe": "registered small-cap band [100M, 2B)"}

    # ---- 1. decile curve --------------------------------------------------
    flat_d, flat_r = d_comp.stack(), ex.stack()
    by_dec = flat_r.groupby(flat_d).mean()
    per_year = {int(y): ex[years == y].stack().groupby(d_comp[years == y].stack()).mean()
                for y in sorted(set(years))}
    dec_year = pd.DataFrame(per_year)              # decile x year
    inversions = int(sum(by_dec.sort_index().diff().dropna() < 0))
    report["decile_curve"] = {
        "mean_excess_per_period_by_decile": {int(k): round(float(v), 6)
                                             for k, v in by_dec.sort_index().items()},
        "adjacent_inversions_of_10": inversions,
        "decile_year_stability_std": {int(k): round(float(dec_year.loc[k].std()), 6)
                                      for k in dec_year.index},
        "top_minus_universe": round(float(by_dec.loc[10.0]), 6),
        "bottom_minus_universe": round(float(by_dec.loc[1.0]), 6),
    }

    # ---- 2. rank breadth --------------------------------------------------
    ic = pd.Series({d: comp.loc[d].corr(ex.loc[d], method="spearman") for d in grid})
    # slope by rank region: mean excess in ventiles, then where the gradient lives
    vent = np.ceil(comp * 20).clip(1, 20)
    by_vent = flat_r.groupby(vent.stack()).mean()
    top_half_spread = float(by_vent.loc[20] - by_vent.loc[11])
    bot_half_spread = float(by_vent.loc[10] - by_vent.loc[1])
    report["rank_breadth"] = {
        "in_sample_mean_spearman_ic_descriptive": round(float(ic.mean()), 6),
        "ic_positive_fraction_of_dates": round(float((ic > 0).mean()), 4),
        "excess_by_ventile": {int(k): round(float(v), 6) for k, v in by_vent.items()},
        "gradient_top_half_v20_minus_v11": round(top_half_spread, 6),
        "gradient_bottom_half_v10_minus_v1": round(bot_half_spread, 6),
    }

    # ---- 3. turnover & persistence ---------------------------------------
    def rank_autocorr(lag):
        vals = [comp.loc[grid[i]].corr(comp.loc[grid[i + lag]], method="spearman")
                for i in range(len(grid) - lag)]
        return float(np.nanmean(vals))

    def top_retention(lag):
        keep = []
        for i in range(len(grid) - lag):
            a = set(d_comp.loc[grid[i]][d_comp.loc[grid[i]] == 10].index)
            b = set(d_comp.loc[grid[i + lag]][d_comp.loc[grid[i + lag]] == 10].index)
            if a:
                keep.append(len(a & b) / len(a))
        return float(np.mean(keep))

    report["persistence"] = {
        "rank_autocorr_1_period_20d": round(rank_autocorr(1), 4),
        "rank_autocorr_3_periods_quarter": round(rank_autocorr(3), 4),
        "rank_autocorr_12_periods_year": round(rank_autocorr(12), 4),
        "top_decile_retention_20d": round(top_retention(1), 4),
        "top_decile_retention_quarter": round(top_retention(3), 4),
        "top_decile_retention_year": round(top_retention(12), 4),
    }

    # ---- 4. regime slices (descriptive) ----------------------------------
    spy = pd.read_csv(ROOT / "raw" / "SFP" / "SFP_SPY.csv",
                      usecols=["date", "closeadj"], parse_dates=["date"]
                      ).set_index("date")["closeadj"].astype(float).sort_index()
    spy = spy[~spy.index.duplicated()]
    drawdown = spy / spy.cummax() - 1
    vol = spy.pct_change().rolling(60).std()
    top_ex = ex.where(d_comp == 10).mean(axis=1) - 0  # top-decile mean excess/date
    now = spy.reindex(grid, method="ffill").to_numpy()
    then = spy.reindex(grid - pd.Timedelta(days=182), method="ffill").to_numpy()
    vol_g = vol.reindex(grid, method="ffill")
    regimes = {
        "drawdown_gt_10pct": (drawdown.reindex(grid, method="ffill") < -0.10).to_numpy(),
        "trailing6m_up": now > then,
        "high_vol_top_half": (vol_g > vol_g.median()).to_numpy(),
    }
    report["regimes"] = {}
    for name, mask in regimes.items():
        m = np.nan_to_num(mask.astype(float)).astype(bool)
        report["regimes"][name] = {
            "dates_in": int(m.sum()), "dates_out": int((~m).sum()),
            "ic_in": round(float(ic[m].mean()), 6),
            "ic_out": round(float(ic[~m].mean()), 6),
            "top_decile_excess_in": round(float(top_ex[m].mean()), 6),
            "top_decile_excess_out": round(float(top_ex[~m].mean()), 6),
        }

    # ---- 5. factor decomposition -----------------------------------------
    ic_gp = pd.Series({d: r_gp.loc[d].corr(ex.loc[d], method="spearman") for d in grid})
    ic_val = pd.Series({d: r_val.loc[d].corr(ex.loc[d], method="spearman") for d in grid})
    cross = float(np.nanmean([r_gp.loc[d].corr(r_val.loc[d], method="spearman")
                              for d in grid]))
    # the 2x2 quadrant the hypothesis is about (median splits, descriptive)
    cheap, prof = r_val > 0.5, r_gp > 0.5
    quad = {
        "cheap_and_profitable": float(ex.where(cheap & prof).stack().mean()),
        "cheap_not_profitable": float(ex.where(cheap & ~prof).stack().mean()),
        "profitable_not_cheap": float(ex.where(~cheap & prof).stack().mean()),
        "neither": float(ex.where(~cheap & ~prof).stack().mean()),
    }
    top_names = d_comp == 10
    report["decomposition"] = {
        "mean_ic_h3": round(float(ic.mean()), 6),
        "mean_ic_gp_alone": round(float(ic_gp.mean()), 6),
        "mean_ic_value_alone": round(float(ic_val.mean()), 6),
        "gp_value_rank_correlation": round(cross, 4),
        "quadrant_mean_excess": {k: round(v, 6) for k, v in quad.items()},
        "h3_top_overlap_with_gp_top": round(float(
            (top_names & (decile_of(r_gp) == 10)).sum().sum()
            / top_names.sum().sum()), 4),
        "h3_top_overlap_with_value_top": round(float(
            (top_names & (decile_of(r_val) == 10)).sum().sum()
            / top_names.sum().sum()), 4),
    }

    OUT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    print(f"written: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
