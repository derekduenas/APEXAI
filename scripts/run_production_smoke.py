#!/usr/bin/env python
"""Production-data smoke test on the frozen Sharadar snapshot. NOT validation."""
from __future__ import annotations
import json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd  # noqa: E402
from apex.config import load_config  # noqa: E402
from apex.contracts import SECURITY_META_COLUMNS, Panel  # noqa: E402
from apex.data.snapshot_loader import (LoadReport, find_candidates, load_marketcap,  # noqa: E402
                                       load_master, load_prices)
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
        "security_type": "common", "sector": m["sector"].replace("", "UNKNOWN").values,
        "first_date": m["firstpricedate"].values, "last_date": m["lastpricedate"].values,
        "delist_date": np.where(delisted, m["lastpricedate"], pd.NaT),
        "delist_reason": np.where(delisted, "unclassified", None),
    }, index=secs)[list(SECURITY_META_COLUMNS)]

    # C4: S&P 500 TOTAL RETURN, SPY permitted when SPXTR is unavailable.
    # SPY is NOT in SEP -- SEP is equities only; ETF prices live in SFP.
    # Discovered on real data 2026-08-11.
    bench = pd.read_csv(ROOT / "raw" / "SFP" / "SFP_SPY.csv", usecols=["ticker", "date", "closeadj"])
    bench["date"] = pd.to_datetime(bench["date"])
    bser = bench.set_index("date")["closeadj"].reindex(dates).ffill().bfill()

    panel = Panel(dates=dates, securities=secs, close_adj=close_adj,
                  high_adj=wide(prices, "high"), low_adj=wide(prices, "low"),
                  close_unadj=close_unadj, volume=wide(prices, "volume"),
                  shares_out=shares, meta=meta, benchmark_tr=bser,
                  vol_index=pd.Series(20.0, index=dates))
    print(f"[{time.time()-t0:6.0f}s] panel built", flush=True)

    fp = dev_fingerprint("sharadar-prod-smoke",
                         json.loads((ROOT/"MANIFEST.json").read_text())["dataset_fingerprint"])
    report, out = smoke_run(SnapshotSource(panel, fp), cfg, "in_sample")

    text = development_banner(fp) + "\n\n=== LOAD ===\n" + json.dumps(rep.as_dict(), indent=2) \
         + "\n\n" + report.render()
    Path("results/production_smoke.txt").write_text(text)
    print(report.render())
    print(f"\n[{time.time()-t0:6.0f}s] written results/production_smoke.txt")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
