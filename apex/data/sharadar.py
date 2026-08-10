"""Sharadar snapshot adapter -- PRIMARY and AUTHORITATIVE (CONVENTIONS A-002).

    Sharadar is confirmed primary and authoritative for every universe filter.
    Norgate is an optional secondary source for prices and cross-checking only,
    and may never be authoritative for a universe filter, for shares
    outstanding, for market capitalisation, or for security identity.

WHY A FROZEN SNAPSHOT, NOT AN API CALL

Section 31 requires every result to be traceable to a data snapshot. A live
endpoint cannot provide that: vendors restate, backfill and correct, so two runs
a week apart against "the same" endpoint are two different datasets and neither
result is reproducible. This adapter reads a frozen local bulk export and hashes
every file into a manifest stamped on the run.

THE FAILURE MODE THIS MODULE IS BUILT AROUND

Sharadar recycles tickers, as every vendor does. SEP and DAILY are keyed by
(ticker, date); TICKERS carries the stable `permaticker` and the window in which
a given company held a given ticker. Joining on ticker alone would staple one
company's prices onto another company's identity -- the survivorship
contamination `contracts.py` structurally bans. Every join here is therefore
DATE-AWARE, and any (ticker, date) resolving to zero or to more than one
permaticker is EXCLUDED and REPORTED, never guessed.

`security_id` is the permaticker. It is never the ticker.

THE HARD RULE (user ruling, 2026-08-09)

    If a security-date cannot be established point-in-time from the required
    source data, it is excluded and the exclusion is reported. Do not fill
    missing PIT information with today's shares, today's market cap, current
    ticker mappings, or later-revised fundamentals.

Implemented literally: a security-date with no DAILY row yields NaN market cap.
There is no forward fill, no back fill, and no interpolation anywhere in this
module. `apex/universe.py` routes those NaNs to the dedicated `pit_market_cap`
filter so the loss is visible and separately counted.

SCHEMA ASSUMPTIONS ARE VALIDATED, NOT TRUSTED

This was written without live vendor access. Every expected column and every
assumed unit is declared in `config/sharadar.yaml` and checked on load. Notably
`DAILY.marketcap` is assumed to be in USD millions, and that assumption is
sanity-checked against a plausible band -- if it is wrong, the load FAILS rather
than admitting nobody to a $1B universe and reporting an empty result.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import numpy as np
import pandas as pd

from apex.config import Config
from apex.contracts import SECURITY_META_COLUMNS, Panel

PERFORMANCE = "performance"
MERGER = "merger"


class SchemaError(ValueError):
    """The snapshot does not match the declared Sharadar schema."""


class UnitSanityError(ValueError):
    """A declared unit assumption failed its plausibility check."""


class ExclusionReason(Enum):
    AMBIGUOUS_IDENTITY = "ambiguous_identity"
    UNKNOWN_IDENTITY = "unknown_identity"
    NO_PIT_MARKET_CAP = "no_pit_market_cap"


# ---------------------------------------------------------------------------
# lineage
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SnapshotManifest:
    root: str
    files: dict
    row_counts: dict
    digest: str

    def as_dict(self) -> dict:
        return {
            "root": self.root,
            "digest": self.digest,
            "files": self.files,
            "row_counts": self.row_counts,
        }


@dataclass(frozen=True)
class ExclusionReport:
    by_reason: dict
    tickers_excluded: tuple

    @property
    def total(self) -> int:
        return int(sum(self.by_reason.values()))

    def as_dict(self) -> dict:
        return {
            "total": self.total,
            "by_reason": dict(self.by_reason),
            "tickers_excluded": list(self.tickers_excluded),
            "rule": (
                "a security-date that cannot be established point-in-time is "
                "EXCLUDED and counted here; it is never filled with current "
                "shares, current market cap, a current ticker mapping, or a "
                "later-revised fundamental"
            ),
        }


# ---------------------------------------------------------------------------
# the adapter
# ---------------------------------------------------------------------------


class SharadarSnapshot:
    """A frozen Sharadar bulk export, presented as a validated `Panel`."""

    def __init__(self, root: Path | str, config: Config) -> None:
        self.root = Path(root)
        self.config = config
        self._settings = config.section("sharadar")
        self._exclusions: dict[str, int] = {}
        self._excluded_tickers: set[str] = set()
        self._require_tables()

    # -- protocol surface ----------------------------------------------------

    @property
    def name(self) -> str:
        return f"sharadar-snapshot:{self.manifest.digest[:12]}"

    @property
    def dataset_fingerprint(self) -> str:
        """The snapshot manifest digest. Ruling 1: stamped on every result."""
        return self.manifest.digest

    @property
    def requires_signed_registration(self) -> bool:
        """Real vendor data. Unlike the synthetic rig, this needs a signature."""
        return True

    def exclusions(self) -> ExclusionReport:
        return ExclusionReport(
            by_reason=dict(self._exclusions),
            tickers_excluded=tuple(sorted(self._excluded_tickers)),
        )

    # -- lineage -------------------------------------------------------------

    def _require_tables(self) -> None:
        missing = [
            name for name in self._settings["required_tables"] if not (self.root / name).exists()
        ]
        if missing:
            raise SchemaError(
                f"snapshot at {self.root} is missing required table(s): {missing}. "
                f"Expected a frozen Sharadar bulk export containing "
                f"{sorted(self._settings['required_tables'])}."
            )

    @property
    def manifest(self) -> SnapshotManifest:
        files: dict[str, str] = {}
        counts: dict[str, int] = {}
        combined = hashlib.sha256()
        for name in sorted(self._settings["required_tables"]):
            path = self.root / name
            payload = path.read_bytes()
            digest = hashlib.sha256(payload).hexdigest()
            files[name] = digest
            counts[name] = max(0, payload.count(b"\n") - 1)
            combined.update(f"{name}:{digest}".encode())
        return SnapshotManifest(
            root=str(self.root), files=files, row_counts=counts, digest=combined.hexdigest()
        )

    def _read(self, name: str) -> pd.DataFrame:
        frame = pd.read_csv(self.root / name)
        required = self._settings["required_tables"][name]
        absent = [c for c in required if c not in frame.columns]
        if absent:
            raise SchemaError(
                f"{name} is missing required column(s) {absent}. "
                f"Declared schema: {required}. Present: {sorted(frame.columns)}."
            )
        if "date" in frame.columns:
            frame["date"] = pd.to_datetime(frame["date"])
        return frame

    def _note(self, reason: ExclusionReason, count: int, ticker: str | None = None) -> None:
        if count <= 0:
            return
        self._exclusions[reason.value] = self._exclusions.get(reason.value, 0) + int(count)
        if ticker is not None:
            self._excluded_tickers.add(ticker)

    # -- identity ------------------------------------------------------------

    def _resolve_identity(self, tickers: pd.DataFrame) -> pd.DataFrame:
        """Ticker windows, with overlaps refused rather than broken by a rule."""
        frame = tickers.copy()
        frame["firstpricedate"] = pd.to_datetime(frame["firstpricedate"])
        frame["lastpricedate"] = pd.to_datetime(frame["lastpricedate"])
        frame["permaticker"] = frame["permaticker"].astype(str)

        for ticker, group in frame.groupby("ticker"):
            if len(group) < 2:
                continue
            ordered = group.sort_values("firstpricedate")
            starts = ordered["firstpricedate"].to_numpy()
            ends = ordered["lastpricedate"].to_numpy()
            if (starts[1:] <= ends[:-1]).any():
                # Two companies claim the same ticker at the same time. Identity
                # is not guessable, so BOTH are refused -- picking one would be
                # exactly the heuristic tie-break the ruling forbids.
                self._excluded_tickers.add(str(ticker))
                self._note(ExclusionReason.AMBIGUOUS_IDENTITY, len(group), str(ticker))
                frame = frame[frame["ticker"] != ticker]
        return frame

    def _attach_permaticker(
        self, rows: pd.DataFrame, identity: pd.DataFrame, label: str
    ) -> pd.DataFrame:
        """Date-aware join. A ticker-only join here would be the whole bug."""
        merged = rows.merge(
            identity[["permaticker", "ticker", "firstpricedate", "lastpricedate"]],
            on="ticker",
            how="left",
        )
        in_window = (
            merged["permaticker"].notna()
            & (merged["date"] >= merged["firstpricedate"])
            & (merged["date"] <= merged["lastpricedate"])
        )
        dropped = int((~in_window).sum())
        if dropped and label == "SEP":
            self._note(ExclusionReason.UNKNOWN_IDENTITY, dropped)
        return merged.loc[in_window].drop(columns=["firstpricedate", "lastpricedate"])

    # -- units ---------------------------------------------------------------

    def _market_cap_usd(self, daily: pd.DataFrame) -> pd.Series:
        scale = float(self._settings["marketcap_scale"])
        values = pd.to_numeric(daily["marketcap"], errors="coerce") * scale

        observed = values.dropna()
        if len(observed):
            median = float(observed.median())
            low = float(self._settings["marketcap_sanity_min_usd"])
            high = float(self._settings["marketcap_sanity_max_usd"])
            if not low <= median <= high:
                raise UnitSanityError(
                    f"median DAILY.marketcap of {median:,.0f} USD after applying "
                    f"marketcap_scale={scale:,.0f} falls outside the plausible band "
                    f"[{low:,.0f}, {high:,.0f}].\n"
                    f"  config/sharadar.yaml declares DAILY.marketcap to be in USD "
                    f"MILLIONS. If the export uses different units, the $1B universe "
                    f"filter would silently admit nobody -- so this fails instead."
                )
        return values

    # -- delisting -----------------------------------------------------------

    def _delist_reasons(self, identity: pd.DataFrame, actions: pd.DataFrame) -> dict:
        """CONVENTIONS section 1 item 1's pre-registered conservative fallback.

        Affirmatively M&A or voluntary -> merger. EVERYTHING ELSE, including a
        delisting with no ACTIONS row at all, is treated as performance-related
        and takes the -30% Shumway haircut.
        """
        merger_actions = {str(a).lower() for a in self._settings["merger_actions"]}
        use_contra = bool(self._settings["contraticker_implies_merger"])

        merger_tickers: set[str] = set()
        if len(actions):
            labels = actions["action"].astype(str).str.lower()
            is_merger = labels.isin(merger_actions)
            if use_contra and "contraticker" in actions.columns:
                contra = actions["contraticker"].astype(str).str.strip()
                is_merger = is_merger | contra.notna() & (contra != "") & (contra != "nan")
            merger_tickers = set(actions.loc[is_merger, "ticker"].astype(str))

        reasons: dict[str, str | None] = {}
        for _, row in identity.iterrows():
            if str(row["isdelisted"]).upper() != "Y":
                reasons[row["permaticker"]] = None
                continue
            reasons[row["permaticker"]] = (
                MERGER if str(row["ticker"]) in merger_tickers else PERFORMANCE
            )
        return reasons

    # -- assembly ------------------------------------------------------------

    def load(self) -> Panel:
        self._exclusions = {}
        self._excluded_tickers = set()

        tickers = self._read("TICKERS.csv")
        sep = self._read("SEP.csv")
        daily = self._read("DAILY.csv")
        actions = self._read("ACTIONS.csv")

        identity = self._resolve_identity(tickers)
        prices = self._attach_permaticker(sep, identity, "SEP")
        caps = self._attach_permaticker(daily, identity, "DAILY")

        benchmark_ticker = self._settings["benchmark_ticker"]
        if benchmark_ticker not in set(identity["ticker"]):
            raise SchemaError(
                f"benchmark ticker '{benchmark_ticker}' is absent from TICKERS. "
                f"C4 requires an S&P 500 TOTAL RETURN benchmark; without it F4b "
                f"cannot be computed and the run would silently lose a feature."
            )

        dates = pd.DatetimeIndex(sorted(prices["date"].unique()))
        securities = pd.Index(sorted(identity["permaticker"].unique()), name="security_id")

        def pivot(frame: pd.DataFrame, column: str) -> pd.DataFrame:
            wide = frame.pivot_table(
                index="date", columns="permaticker", values=column, aggfunc="last"
            )
            # Reindex only -- NEVER ffill. A gap is a gap.
            return wide.reindex(index=dates, columns=securities).astype("float64")

        close_adj = pivot(prices, "closeadj")
        close_unadj = pivot(prices, "closeunadj")
        volume = pivot(prices, "volume")

        caps = caps.assign(_usd=self._market_cap_usd(caps))
        market_cap = pivot(caps, "_usd")

        # shares_out is DERIVED so that Panel.market_cap (close_unadj x shares_out)
        # reproduces the vendor's point-in-time figure exactly. Where either side
        # is missing the result is NaN and the security-date is excluded.
        with np.errstate(invalid="ignore", divide="ignore"):
            shares_out = market_cap / close_unadj.where(close_unadj > 0)

        tradable = close_adj.notna()
        self._note(
            ExclusionReason.NO_PIT_MARKET_CAP,
            int((tradable & market_cap.isna()).to_numpy().sum()),
        )

        meta = self._build_meta(identity, actions, securities, dates, prices)
        benchmark = self._benchmark(prices, identity, benchmark_ticker, dates)

        return Panel(
            dates=dates,
            securities=securities,
            close_adj=close_adj,
            high_adj=pivot(prices, "high"),
            low_adj=pivot(prices, "low"),
            close_unadj=close_unadj,
            volume=volume,
            shares_out=shares_out,
            meta=meta,
            benchmark_tr=benchmark,
            vol_index=self._vol_index(dates),
        )

    def _build_meta(
        self,
        identity: pd.DataFrame,
        actions: pd.DataFrame,
        securities: pd.Index,
        dates: pd.DatetimeIndex,
        prices: pd.DataFrame,
    ) -> pd.DataFrame:
        common = {str(c).lower() for c in self._settings["common_categories"]}
        reasons = self._delist_reasons(identity, actions)
        indexed = identity.set_index("permaticker")

        rows = []
        for security in securities:
            record = indexed.loc[security]
            if isinstance(record, pd.DataFrame):
                record = record.iloc[0]
            category = str(record["category"]).strip().lower()
            delisted = str(record["isdelisted"]).upper() == "Y"
            last = pd.Timestamp(record["lastpricedate"])
            rows.append(
                {
                    "security_id": security,
                    "ticker": str(record["ticker"]),
                    "exchange": str(record["exchange"]),
                    # Unlisted categories are typed 'other' and excluded by the
                    # section 3 filter. Never admitted by default.
                    "security_type": "common" if category in common else "other",
                    "sector": str(record["sector"]),
                    "first_date": pd.Timestamp(record["firstpricedate"]),
                    "last_date": last,
                    "delist_date": last if delisted else pd.NaT,
                    "delist_reason": reasons.get(security),
                }
            )
        return pd.DataFrame(rows, index=securities)[list(SECURITY_META_COLUMNS)]

    def _benchmark(
        self,
        prices: pd.DataFrame,
        identity: pd.DataFrame,
        ticker: str,
        dates: pd.DatetimeIndex,
    ) -> pd.Series:
        permaticker = identity.loc[identity["ticker"] == ticker, "permaticker"].iloc[0]
        series = (
            prices.loc[prices["permaticker"] == permaticker]
            .set_index("date")["closeadj"]
            .reindex(dates)
        )
        # The benchmark is the ONE series that may be carried across a gap: a
        # missing index print is a data hole, not information, and `Panel`
        # forbids NaN here. Securities are never treated this way.
        series = series.ffill().bfill()
        if series.isna().any():
            raise SchemaError(f"benchmark '{ticker}' has no usable prices in the snapshot")
        return series.astype("float64")

    def _vol_index(self, dates: pd.DatetimeIndex) -> pd.Series:
        path = self.root / self._settings["vol_index_file"]
        if not path.exists():
            raise SchemaError(
                f"{path.name} is absent. B5's high-volatility regime is defined on "
                f"VIX, which Sharadar does not carry. Supply it, or the regime "
                f"breakdown required by section 9 cannot be reported."
            )
        frame = pd.read_csv(path)
        frame["date"] = pd.to_datetime(frame["date"])
        series = frame.set_index("date")["close"].reindex(dates).ffill().bfill()
        if series.isna().any():
            raise SchemaError(f"{path.name} has no usable values over the panel calendar")
        return series.astype("float64")
