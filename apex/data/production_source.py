"""The confirmatory production source: frozen Sharadar snapshot via the
slice-aware, universe-first loader.

This is the SAME construction path the production smoke test exercised. The only
differences are the two that must differ:

  * the fingerprint is the snapshot's real manifest digest, NOT `dev-` prefixed,
    so the verdict layer and the ledger will accept it;
  * `requires_signed_registration` is True, because this is real vendor data.

Nothing about universe construction, feature computation or PIT handling changes
between the smoke path and this one. If they diverged, the smoke test would not
have been evidence about this.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from apex.contracts import SECURITY_META_COLUMNS, Panel
from apex.data.snapshot_loader import (
    LoadReport,
    adjust_high_low,
    find_candidates,
    load_delist_reasons,
    load_marketcap,
    load_master,
    load_prices,
)


def build_production_panel(root: Path, config, start: str, end: str):
    """Identical to the smoke path. Returns (Panel, LoadReport)."""
    scale = float(config.get("sharadar.marketcap_scale"))
    min_mc = float(config.get("universe.min_market_cap_usd"))
    report = LoadReport()

    master = load_master(root, config)
    report.master_securities = len(master)
    report.candidates_after_category = len(master)

    keep = find_candidates(root, master, min_mc, scale, report)
    prices = adjust_high_low(load_prices(root, master, keep, start, end, report))
    reasons = load_delist_reasons(root, master, config)
    mcap = load_marketcap(root, master, keep, start, end, scale)

    dates = pd.DatetimeIndex(sorted(prices["date"].unique()))
    secs = pd.Index(sorted(prices["permaticker"].unique()), name="security_id")

    def wide(frame, column):
        return (
            frame.pivot_table(index="date", columns="permaticker", values=column, aggfunc="last")
            .reindex(index=dates, columns=secs)
            .astype("float64")
        )

    close_unadj = wide(prices, "closeunadj")
    market_cap = wide(mcap, "mcap_usd")
    with np.errstate(invalid="ignore", divide="ignore"):
        shares = market_cap / close_unadj.where(close_unadj > 0)

    meta_source = master.set_index("permaticker").loc[secs]
    delisted = meta_source["isdelisted"].eq("Y")
    meta = pd.DataFrame(
        {
            "security_id": secs,
            "ticker": meta_source["ticker"].values,
            "exchange": meta_source["exchange_apex"].values,
            "security_type": meta_source["security_type_apex"].values,
            "sector": meta_source["sector"].replace("", "UNKNOWN").values,
            "first_date": meta_source["firstpricedate"].values,
            "last_date": meta_source["lastpricedate"].values,
            "delist_date": np.where(delisted, meta_source["lastpricedate"], pd.NaT),
            "delist_reason": [reasons.get(pt) for pt in secs],
        },
        index=secs,
    )[list(SECURITY_META_COLUMNS)]

    bench = pd.read_csv(root / "raw" / "SFP" / "SFP_SPY.csv", usecols=["date", "closeadj"])
    bench["date"] = pd.to_datetime(bench["date"])
    benchmark = bench.set_index("date")["closeadj"].reindex(dates).ffill().bfill()

    panel = Panel(
        dates=dates,
        securities=secs,
        close_adj=wide(prices, "closeadj"),
        high_adj=wide(prices, "high_adj"),
        low_adj=wide(prices, "low_adj"),
        close_unadj=close_unadj,
        volume=wide(prices, "volume"),
        shares_out=shares,
        meta=meta,
        benchmark_tr=benchmark,
        # VIX is not a Sharadar product. B5 regime reporting is unavailable and
        # is NOT a pass/fail input; this satisfies the Panel contract only.
        vol_index=pd.Series(20.0, index=dates),
    )
    return panel, report


class ProductionSource:
    """PriceSource over the frozen snapshot. Confirmatory fingerprint."""

    name = "sharadar-production-snapshot"
    requires_signed_registration = True

    def __init__(self, root: Path | str, config, start: str, end: str) -> None:
        self.root = Path(root)
        manifest = json.loads((self.root / "MANIFEST.json").read_text())
        self._fingerprint = manifest["dataset_fingerprint"]
        self._panel, self.report = build_production_panel(self.root, config, start, end)

    @property
    def dataset_fingerprint(self) -> str:
        return self._fingerprint

    def load(self) -> Panel:
        return self._panel

    def exclusions(self) -> LoadReport:
        """Universe-construction exclusions, for the section 9 payload.

        INCIDENT-001 D2: `run_validation.py` called this and ProductionSource
        did not define it. Latent because the run crashed on D1 first; fixing
        D1 alone would have crashed here, after spending another credit.
        """
        return self.report
