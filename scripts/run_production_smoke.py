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
    rep = LoadReport()

    master = load_master(ROOT, cfg)
    rep.master_securities = len(master)
    rep.candidates_after_category = len(master)
    print(f"[{time.time()-t0:6.0f}s] master (common, 3 exchanges): {len(master):,}", flush=True)

    keep = find_candidates(ROOT, master, min_mc, scale, rep)
    print(f"[{time.time()-t0:6.0f}s] ever >= $1B mcap: {len(keep):,} "
          f"(scanned {rep.daily_rows_scanned:,} DAILY rows)", flush=True)

    prices = load_prices(ROOT, master, keep, start, end, rep)
    print(f"[{time.time()-t0:6.0f}s] SEP kept {rep.sep_rows_kept:,} of {rep.sep_rows_scanned:,} "
          f"(dupes dropped {rep.duplicates_dropped})", flush=True)

    prices = adjust_high_low(prices)          # FIX 1: high/low onto the adjusted scale
    reasons = load_delist_reasons(ROOT, master, cfg)   # FIX 3: ACTIONS -> merger/performance
    print(f"[{time.time()-t0:6.0f}s] delist reasons: "
          f"{sum(v=='merger' for v in reasons.values()):,} merger / "
          f"{sum(v=='performance' for v in reasons.values()):,} performance", flush=True)

    mcap = load_marketcap(ROOT, master, keep, start, end, scale)
    print(f"[{time.time()-t0:6.0f}s] marketcap rows {len(mcap):,}", flush=True)

    dates = pd.DatetimeIndex(sorted(prices["date"].unique()))
    secs = pd.Index(sorted(prices["permaticker"].unique()), name="security_id")
    print(f"[{time.time()-t0:6.0f}s] panel {len(secs):,} securities x {len(dates):,} dates", flush=True)

    def wide(df, col):
        return df.pivot_table(index="date", columns="permaticker", values=col, aggfunc="last") \
                 .reindex(index=dates, columns=secs).astype("float64")
    close_adj  = wide(prices, "closeadj")
    close_unadj= wide(prices, "closeunadj")
    mc         = wide(mcap, "mcap_usd")
    with np.errstate(invalid="ignore", divide="ignore"):
        shares = mc / close_unadj.where(close_unadj > 0)

    m = master.set_index("permaticker").loc[secs]
    delisted = m["isdelisted"].eq("Y")
    meta = pd.DataFrame({
        "security_id": secs, "ticker": m["ticker"].values, "exchange": m["exchange_apex"].values,
        "security_type": m["security_type_apex"].values,
        "sector": m["sector"].replace("", "UNKNOWN").values,
        "first_date": m["firstpricedate"].values, "last_date": m["lastpricedate"].values,
        "delist_date": np.where(delisted, m["lastpricedate"], pd.NaT),
        "delist_reason": [reasons.get(pt) for pt in secs],
    }, index=secs)[list(SECURITY_META_COLUMNS)]

    # C4: S&P 500 TOTAL RETURN, SPY permitted when SPXTR is unavailable.
    # SPY is NOT in SEP -- SEP is equities only; ETF prices live in SFP.
    # Discovered on real data 2026-08-11.
    bench = pd.read_csv(ROOT / "raw" / "SFP" / "SFP_SPY.csv", usecols=["ticker", "date", "closeadj"])
    bench["date"] = pd.to_datetime(bench["date"])
    bser = bench.set_index("date")["closeadj"].reindex(dates).ffill().bfill()

    panel = Panel(dates=dates, securities=secs, close_adj=close_adj,
                  high_adj=wide(prices, "high_adj"), low_adj=wide(prices, "low_adj"),
                  close_unadj=close_unadj, volume=wide(prices, "volume"),
                  shares_out=shares, meta=meta, benchmark_tr=bser,
                  vol_index=pd.Series(20.0, index=dates))
    print(f"[{time.time()-t0:6.0f}s] panel built", flush=True)

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
