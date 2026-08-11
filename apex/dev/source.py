"""DEVELOPMENT source: SEC EDGAR identity + PIT shares, Stooq prices.

NON-CONFIRMATORY. The fingerprint is `dev-` namespaced, so the verdict layer,
the ledger and the holdout gate all refuse it. See DATA_LIMITATIONS.md.

MEASURED PROPERTIES OF THE REAL DATA (2026-08-10), and how each is handled:

  PRICES ARE BACK-ADJUSTED, NOT RAW.
      AAPL closes at $0.948 on 2005-01-03 -- split AND dividend adjusted. Good
      for RATIO quantities (returns, SMA ratios, vol ratios, ATR/Close), which
      is what F1-F4 consume.
      FATAL for LEVEL quantities. CONVENTIONS section 4.4 requires the $5 close
      filter and the $1B market-cap filter to use as-of-date UNADJUSTED prices.
      Stooq publishes no unadjusted series and the adjustment factor cannot be
      recovered from it. `close_unadj` is therefore populated with the ADJUSTED
      series and the contamination is reported on every run -- it is NOT hidden,
      and the affected filters are NOT relaxed.

  ZERO DELISTED SECURITIES.
      All 9,575 stock files end on the same date. Stooq's bulk US set contains
      only currently-listed names, so the universe is 100% survivorship-biased
      and the delisting / -30% code paths cannot fire on real events.

  NO VIX.
      Not a Stooq product. B5 regime reporting is DISABLED on development data
      rather than approximated; `vol_index` carries a constant purely to satisfy
      the Panel contract, and no regime breakdown is produced.

IDENTITY, AND WHAT COULD NOT BE VERIFIED

`apex/data/identity.py` verifies a candidate match by PRICE AGREEMENT between
two price sources. EDGAR is not a price source, so that verification is
unavailable here. The join is ticker -> CIK through EDGAR's CURRENT map, with an
activity-window overlap check and outright exclusion of any ticker resolving to
more than one CIK. Every match is a hypothesis; none is price-verified.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from apex.contracts import SECURITY_META_COLUMNS, Panel
from apex.data.edgar import EdgarClient
from apex.data.stooq import read_security, scan_bulk_export
from apex.dev.namespace import dev_fingerprint

# A share count is known from its FILING date until the next filing supersedes
# it -- carrying it forward is correct point-in-time practice. Carrying it
# forward for ever is not: this caps the staleness, after which market cap
# becomes NaN and the security-date is excluded by the pit_market_cap filter.
MAX_SHARES_STALENESS_DAYS = 400

# Only the Panel contract consumes this; B5 regime reporting is disabled on dev.
VIX_PLACEHOLDER = 20.0


@dataclass
class DevBuildReport:
    """Everything requirement 9 asks for, measured rather than assumed."""

    stooq_files_indexed: int = 0
    stooq_selected: int = 0
    stooq_rows: int = 0
    edgar_requests: int = 0
    identity_matched: int = 0
    identity_no_cik: int = 0
    identity_ambiguous: int = 0
    identity_no_window_overlap: int = 0
    shares_with_data: int = 0
    shares_absent: int = 0
    shares_observations: int = 0
    delistings_detected: int = 0
    form25_but_still_listed: int = 0
    date_range: tuple = ()
    price_adjustment: str = "back-adjusted (split + dividend) -- NOT raw"
    unadjusted_available: bool = False
    vix_available: bool = False
    excluded_tickers: list = field(default_factory=list)
    failures: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


def _sector_from_sic(sic: str) -> str:
    """2-digit SIC major group. A PROXY, and not point-in-time. See §4."""
    digits = "".join(ch for ch in str(sic) if ch.isdigit())
    return f"SIC{digits[:2]}" if len(digits) >= 2 else "SIC_UNKNOWN"


def build_dev_panel(
    stooq_root,
    start: str,
    end: str,
    max_securities: int = 400,
    benchmark_ticker: str = "SPY",
) -> tuple:
    """Assemble a development Panel. Returns (Panel, DevBuildReport, fingerprint)."""
    report = DevBuildReport()

    # -- 1. index Stooq, choose a deterministic subset ----------------------
    index = scan_bulk_export(stooq_root)
    report.stooq_files_indexed = len(index)

    stocks = sorted(
        (s for s in index if s.asset_class == "stocks"), key=lambda s: s.ticker
    )
    step = max(1, len(stocks) // max_securities)
    selected = stocks[::step][:max_securities]

    benchmark = next((s for s in index if s.ticker == benchmark_ticker), None)
    if benchmark is None:
        raise RuntimeError(f"benchmark {benchmark_ticker} absent from the Stooq export")

    # -- 2. EDGAR identity ---------------------------------------------------
    client = EdgarClient()
    ticker_to_cik = client.ticker_map()

    lo, hi = pd.Timestamp(start), pd.Timestamp(end)
    frames: dict = {}
    meta_rows: list = []
    shares_series: dict = {}
    file_hashes: list = []

    for security in selected:
        cik = ticker_to_cik.get(security.ticker)
        if cik is None:
            report.identity_no_cik += 1
            report.excluded_tickers.append(f"{security.ticker}:no_cik")
            continue

        try:
            frame, described = read_security(security)
        except Exception as exc:  # noqa: BLE001
            report.failures.append(f"{security.ticker}: {type(exc).__name__}: {exc}")
            continue

        frame = frame[(frame["date"] >= lo) & (frame["date"] <= hi)]
        if frame.empty:
            report.identity_no_window_overlap += 1
            report.excluded_tickers.append(f"{security.ticker}:no_dates_in_window")
            continue

        try:
            issuer = client.issuer(cik, security.ticker)
            observations = client.shares_outstanding(cik)
        except Exception as exc:  # noqa: BLE001
            report.failures.append(f"{security.ticker} (CIK {cik}): {type(exc).__name__}")
            continue

        sid = issuer.security_id
        if sid in frames:
            # Two Stooq tickers resolving to one CIK: identity is not decidable.
            report.identity_ambiguous += 1
            report.excluded_tickers.append(f"{security.ticker}:ambiguous_cik_{sid}")
            continue

        frames[sid] = frame.set_index("date")
        file_hashes.append(described.sha256)
        report.stooq_rows += len(frame)
        report.identity_matched += 1

        if observations:
            report.shares_with_data += 1
            report.shares_observations += len(observations)
            shares_series[sid] = pd.Series(
                {pd.Timestamp(o.filed): o.value for o in observations}
            ).sort_index()
        else:
            report.shares_absent += 1

        if issuer.delist_date:
            report.delistings_detected += 1
        elif "STILL_LISTED" in issuer.delist_evidence:
            report.form25_but_still_listed += 1

        meta_rows.append(
            {
                "security_id": sid,
                "ticker": issuer.ticker or security.ticker,
                "exchange": security.exchange,
                "security_type": "common",
                "sector": _sector_from_sic(issuer.sic),
                "first_date": frame["date"].iloc[0],
                "last_date": frame["date"].iloc[-1],
                "delist_date": pd.Timestamp(issuer.delist_date) if issuer.delist_date else pd.NaT,
                "delist_reason": None if not issuer.delist_date else "unclassified",
            }
        )

    report.edgar_requests = client.finish().requests
    if not frames:
        raise RuntimeError("no securities survived identity resolution")

    # -- 3. assemble the Panel ----------------------------------------------
    bench_frame, _ = read_security(benchmark)
    bench_frame = bench_frame[(bench_frame["date"] >= lo) & (bench_frame["date"] <= hi)]

    dates = pd.DatetimeIndex(sorted(bench_frame["date"].unique()))
    securities = pd.Index(sorted(frames), name="security_id")

    def wide(column: str) -> pd.DataFrame:
        return pd.DataFrame(
            {sid: frames[sid][column] for sid in securities}, index=dates, columns=securities
        ).astype("float64")

    close = wide("close")

    # PIT shares: forward-fill from each FILING date, capped at MAX_STALENESS.
    shares = pd.DataFrame(np.nan, index=dates, columns=securities)
    for sid, series in shares_series.items():
        aligned = series.reindex(dates.union(series.index)).sort_index().ffill().reindex(dates)
        age = pd.Series(dates, index=dates).sub(
            pd.Series(series.index, index=series.index)
            .reindex(dates.union(series.index)).sort_index().ffill().reindex(dates)
        ).dt.days
        shares[sid] = aligned.where(age <= MAX_SHARES_STALENESS_DAYS)

    meta = pd.DataFrame(meta_rows).set_index("security_id")
    meta["security_id"] = meta.index
    meta = meta.loc[securities][list(SECURITY_META_COLUMNS)]

    panel = Panel(
        dates=dates,
        securities=securities,
        close_adj=close,
        high_adj=wide("high"),
        low_adj=wide("low"),
        # CONTAMINATED BY CONSTRUCTION: no unadjusted series exists in this
        # dataset. Reported on every run; the affected filters are NOT relaxed.
        close_unadj=close,
        volume=wide("volume"),
        shares_out=shares,
        meta=meta,
        benchmark_tr=bench_frame.set_index("date")["close"].reindex(dates).ffill().bfill(),
        vol_index=pd.Series(VIX_PLACEHOLDER, index=dates),
    )

    report.stooq_selected = len(securities)
    report.date_range = (str(dates[0].date()), str(dates[-1].date()))

    fingerprint = dev_fingerprint(
        "edgar+stooq",
        hashlib.sha256("|".join(sorted(file_hashes)).encode()).hexdigest(),
    )
    return panel, report, fingerprint


class DevelopmentSource:
    """PriceSource over the development stack. Always dev-fingerprinted."""

    name = "edgar+stooq-development"
    requires_signed_registration = False  # dev data never touches a locked period

    def __init__(self, stooq_root, start: str, end: str, max_securities: int = 400):
        self._panel, self.report, self._fingerprint = build_dev_panel(
            stooq_root, start, end, max_securities
        )
        self.built_at = dt.datetime.now(dt.timezone.utc).isoformat()

    @property
    def dataset_fingerprint(self) -> str:
        return self._fingerprint

    def load(self) -> Panel:
        return self._panel
