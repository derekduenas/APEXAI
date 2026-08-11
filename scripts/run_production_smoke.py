#!/usr/bin/env python
"""Production-data smoke test on the frozen Sharadar snapshot. NOT validation."""
from __future__ import annotations
import json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd  # noqa: E402
from apex.config import load_config  # noqa: E402
from apex.contracts import SECURITY_META_COLUMNS, Panel  # noqa: E402
from apex.data.snapshot_loader import (LoadReport, adjust_high_low, find_candidates,  # noqa: E402
                                       load_delist_reasons, load_marketcap, load_master,
                                       load_prices)
from apex.dev.namespace import dev_fingerprint, development_banner  # noqa: E402
from apex.report.smoke import smoke_run  # noqa: E402

ROOT = Path("data/snapshots/sharadar/current")

class SnapshotSource:
    name = "sharadar-snapshot"
    requires_signed_registration = False   # in-sample only; never a locked period
    def __init__(self, panel, fp): self._p, self._fp = panel, fp
    @property
    def dataset_fingerprint(self): return self._fp
    def load(self): return self._p

def main() -> int:
    t0 = time.time()
    cfg = load_config("experiment", "costs", "synthetic", "sharadar")
    start, end = cfg.get("calendar.lake_start"), cfg.period("in_sample")["end"]
    scale = float(cfg.get("sharadar.marketcap_scale"))
    min_mc = float(cfg.get("universe.min_market_cap_usd"))
    # DRY RUN OF THE VALIDATION PATH.
    # Panel construction now goes through the SAME build_production_panel that
    # scripts/run_validation.py uses. If this smoke run and validation built
    # their panels by different code, the smoke run would be evidence about
    # something other than the thing being validated.
    from apex.data.production_source import build_production_panel

    panel, rep = build_production_panel(ROOT, cfg, start, end)
    print(f"[{time.time()-t0:6.0f}s] panel {len(panel.securities):,} securities "
          f"x {len(panel.dates):,} dates  (via build_production_panel)", flush=True)

    fp = dev_fingerprint("sharadar-prod-smoke",
                         json.loads((ROOT/"MANIFEST.json").read_text())["dataset_fingerprint"])
    report, out = smoke_run(SnapshotSource(panel, fp), cfg, "in_sample")

    # ------------------------------------------------------------------
    # DIAGNOSTICS ONLY. Reads the pipeline's own outputs and reports them.
    # Computes nothing the pipeline did not already compute, changes no
    # feature, filter, threshold or value.
    # ------------------------------------------------------------------
    diag = ["", "=" * 78, "DIAGNOSTICS (reporting only -- nothing recomputed or altered)", "=" * 78]

    elig = out.universe.eligible
    atr = out.features.components["f3_atr_over_close"].where(elig)
    vals = atr.stack().dropna()
    diag += ["", "--- A. f3_atr_over_close distribution (eligible security-dates) ---",
             f"  observations : {len(vals):,}"]
    for q in (0.50, 0.90, 0.99, 0.999):
        diag.append(f"  p{q*100:<6.3g}     : {vals.quantile(q):.4f}")
    diag.append(f"  max          : {vals.max():.4f}")
    for thresh in (1.0, 5.0, 10.0):
        n = int((vals > thresh).sum())
        diag.append(f"  > {thresh:<5.0f}      : {n:,} ({n/len(vals):.6%})")

    tick = out.panel.meta["ticker"]
    top = vals.sort_values(ascending=False).head(12)
    diag += ["", "  top offenders (date, security, ticker, atr/close, close_unadj):"]
    for (d, sid), v in top.items():
        cu = out.panel.close_unadj.loc[d, sid]
        diag.append(f"    {str(d.date())}  {sid:<8} {str(tick.get(sid,'?')):<7} "
                    f"atr/close={v:>10.3f}  close_unadj={cu:>10.4f}")

    diag += ["", "--- A2. REIT exclusion (protocol section 3) ---"]
    reits = int((out.panel.meta["security_type"] == "reit").sum())
    reit_elig = int(elig.loc[:, out.panel.meta.index[out.panel.meta["security_type"] == "reit"]]
                    .to_numpy().sum()) if reits else 0
    diag += [f"  REIT securities in panel      : {reits:,}",
             f"  REIT security-dates ELIGIBLE  : {reit_elig:,}   <-- must be 0"]

    diag += ["", "--- B. delisting path instrumentation ---"]
    reasons = out.forward_returns.exit_reason.where(elig)
    flat = reasons.stack().dropna()
    total = len(flat)
    counts = flat.value_counts()
    diag.append(f"  eligible forward-return observations: {total:,}")
    for k, v in counts.items():
        diag.append(f"    {k:<26} {v:>10,}  ({v/total:.4%})")
    perf = int(counts.get("delist_performance", 0))
    diag.append(f"  -> returns taking the -30% Shumway haircut: {perf:,} ({perf/total:.4%})")

    by_year = flat.reset_index()
    by_year.columns = ["date", "security_id", "reason"]
    by_year["year"] = by_year["date"].dt.year
    pivot = by_year.pivot_table(index="year", columns="reason", aggfunc="size", fill_value=0)
    diag += ["", "  by year:", pivot.to_string()]

    diag_text = "\n".join(diag)
    print(diag_text, flush=True)

    text = development_banner(fp) + "\n\n=== LOAD ===\n" + json.dumps(rep.as_dict(), indent=2) \
         + "\n\n" + report.render() + "\n" + diag_text
    Path("results/production_smoke.txt").write_text(text)
    print(report.render())
    print(f"\n[{time.time()-t0:6.0f}s] written results/production_smoke.txt")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
