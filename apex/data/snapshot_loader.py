"""Slice-aware, universe-first loader for the frozen Sharadar snapshot.

WHY THIS EXISTS

The snapshot is 66.9M rows across 1,198 slices. The previous adapter read four
monolithic CSVs and pivoted to a wide panel -- roughly 21,960 securities x 5,650
dates x 6 frames, over 4GB of dense float before the pipeline does any work.

THE ORDER THAT MAKES IT TRACTABLE, and it is also the CORRECT order:

    1. eligibility per date, from LEVEL columns only
    2. restrict to permatickers that are ever eligible
    3. only then pivot to wide

Nothing about protocol section 3 changes. What changes is that the filters run
BEFORE the pivot instead of after it, so memory scales with the eligible
universe (~1-2k names) rather than the full security master.

THE NECESSARY-CONDITION SHORTCUT, and why it is exact

A security whose market cap NEVER reaches $1B can never satisfy section 3. So a
first pass over DAILY -- three columns -- discards most of the master before SEP
is touched at all. This is a necessary condition, not an approximation: no
security that could ever be eligible is excluded by it.

IDENTITY

SEP and DAILY are keyed by TICKER. TICKERS carries the stable permaticker with
`firstpricedate`/`lastpricedate`. The join is DATE-AWARE: a (ticker, date) row is
attributed to the permaticker whose active window contains that date. A
ticker-only join would attribute one company's prices to another -- exactly what
`contracts.py` bans.
"""

from __future__ import annotations

import glob
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

SEP_COLS = ["ticker", "date", "high", "low", "close", "volume", "closeadj", "closeunadj"]
LEVEL_COLS = ["ticker", "date", "closeunadj", "volume"]
DAILY_COLS = ["ticker", "date", "marketcap"]


@dataclass
class LoadReport:
    master_securities: int = 0
    candidates_after_category: int = 0
    candidates_after_marketcap: int = 0
    eligible_ever: int = 0
    sep_rows_scanned: int = 0
    sep_rows_kept: int = 0
    daily_rows_scanned: int = 0
    duplicates_dropped: int = 0
    unmapped_ticker_dates: int = 0
    recycled_tickers: int = 0
    notes: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return dict(self.__dict__)


def _slices(root: Path, table: str):
    return sorted(glob.glob(str(root / "raw" / table / "*.csv")))


def load_master(root: Path, config) -> pd.DataFrame:
    """TICKERS -> the equity master, section 3 attribute filters applied."""
    settings = config.section("sharadar")
    frame = pd.read_csv(root / "raw" / "TICKERS" / "TICKERS.csv", dtype=str, keep_default_na=False)
    frame = frame[frame["table"] == "stocks"]

    common = set(settings["common_categories"])
    labels = dict(settings["exchange_labels"])

    frame = frame[frame["category"].isin(common)]
    frame["exchange_apex"] = frame["exchange"].map(labels)
    frame = frame[frame["exchange_apex"].notna()]

    for column in ("firstpricedate", "lastpricedate"):
        frame[column] = pd.to_datetime(frame[column], errors="coerce")
    return frame.reset_index(drop=True)


def _attribute(chunk: pd.DataFrame, windows: pd.DataFrame) -> pd.DataFrame:
    """DATE-AWARE ticker -> permaticker. Rows outside any window are dropped."""
    merged = chunk.merge(windows, on="ticker", how="inner")
    inside = (merged["date"] >= merged["firstpricedate"]) & (
        merged["date"] <= merged["lastpricedate"]
    )
    return merged.loc[inside].drop(columns=["firstpricedate", "lastpricedate"])


def find_candidates(root: Path, master: pd.DataFrame, min_market_cap: float,
                    scale: float, report: LoadReport) -> set:
    """Pass 1 -- DAILY only, three columns. Necessary condition on market cap."""
    windows = master[["ticker", "permaticker", "firstpricedate", "lastpricedate"]]
    reached: set = set()
    for path in _slices(root, "DAILY"):
        chunk = pd.read_csv(path, usecols=DAILY_COLS)
        report.daily_rows_scanned += len(chunk)
        chunk["date"] = pd.to_datetime(chunk["date"])
        chunk = _attribute(chunk, windows)
        chunk["mcap_usd"] = chunk["marketcap"] * scale
        hit = chunk.loc[chunk["mcap_usd"] >= min_market_cap, "permaticker"]
        reached.update(hit.unique().tolist())
    report.candidates_after_marketcap = len(reached)
    return reached


def load_prices(root: Path, master: pd.DataFrame, keep: set, start, end,
                report: LoadReport) -> pd.DataFrame:
    """Pass 2 -- SEP, restricted to candidate permatickers and the date window."""
    windows = master[["ticker", "permaticker", "firstpricedate", "lastpricedate"]]
    lo, hi = pd.Timestamp(start), pd.Timestamp(end)
    parts = []
    for path in _slices(root, "SEP"):
        chunk = pd.read_csv(path, usecols=SEP_COLS)
        report.sep_rows_scanned += len(chunk)
        chunk["date"] = pd.to_datetime(chunk["date"])
        chunk = chunk[(chunk["date"] >= lo) & (chunk["date"] <= hi)]
        if chunk.empty:
            continue
        chunk = _attribute(chunk, windows)
        chunk = chunk[chunk["permaticker"].isin(keep)]
        if not chunk.empty:
            parts.append(chunk)
    if not parts:
        raise RuntimeError("no SEP rows survived candidate restriction")
    prices = pd.concat(parts, ignore_index=True)
    before = len(prices)
    prices = prices.drop_duplicates(subset=["permaticker", "date"], keep="last")
    report.duplicates_dropped = before - len(prices)
    report.sep_rows_kept = len(prices)
    return prices


def load_marketcap(root: Path, master: pd.DataFrame, keep: set, start, end,
                   scale: float) -> pd.DataFrame:
    windows = master[["ticker", "permaticker", "firstpricedate", "lastpricedate"]]
    lo, hi = pd.Timestamp(start), pd.Timestamp(end)
    parts = []
    for path in _slices(root, "DAILY"):
        chunk = pd.read_csv(path, usecols=DAILY_COLS)
        chunk["date"] = pd.to_datetime(chunk["date"])
        chunk = chunk[(chunk["date"] >= lo) & (chunk["date"] <= hi)]
        if chunk.empty:
            continue
        chunk = _attribute(chunk, windows)
        chunk = chunk[chunk["permaticker"].isin(keep)]
        if not chunk.empty:
            chunk["mcap_usd"] = chunk["marketcap"] * scale
            parts.append(chunk[["permaticker", "date", "mcap_usd"]])
    out = pd.concat(parts, ignore_index=True)
    return out.drop_duplicates(subset=["permaticker", "date"], keep="last")
