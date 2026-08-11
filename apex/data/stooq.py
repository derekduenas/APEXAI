"""Stooq price reader -- LOCAL FILES ONLY. This module never contacts stooq.com.

DEVELOPMENT ONLY. See DATA_LIMITATIONS.md.

WHY THERE IS NO DOWNLOADER HERE

**[measured 2026-08-10]** Both the Stooq bulk archive and the per-symbol CSV
endpoint (`/q/d/l/?s=<sym>&i=d`) are behind a JavaScript proof-of-work bot
challenge: the response is an HTML page that computes a SHA-256 proof and POSTs
it to `/__verify` for a session cookie.

That is bot-detection. Solving it programmatically is out of bounds regardless
of purpose, so this module has NO network code at all -- not a disabled path, not
a flag, none. The operator downloads the data in a browser and puts it on disk.

That is also the architecturally correct answer: the authoritative artefact for
any APEX run is a frozen local snapshot, never a live endpoint.

EXPECTED LAYOUT

    <root>/
        aapl.us.csv
        msft.us.csv
        ...

Stooq's daily CSV header is:

    Date,Open,High,Low,Close,Volume

Note what is ABSENT: there is no adjusted-close column. Stooq publishes no
total-return series, so F1/F3/F4 on this data are computed over a price series
that is not dividend-adjusted. That is recorded as a limitation, not worked
around.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

# The REAL bulk format, measured 2026-08-10 against a live download. Note it is
# .txt, not .csv, and the header is angle-bracketed:
#   <TICKER>,<PER>,<DATE>,<TIME>,<OPEN>,<HIGH>,<LOW>,<CLOSE>,<VOL>,<OPENINT>
#   GPK.US,D,20050225,000000,5.26882,5.54514,5.22561,5.52804,79886.07,0
EXPECTED_COLUMNS = (
    "<TICKER>", "<PER>", "<DATE>", "<TIME>",
    "<OPEN>", "<HIGH>", "<LOW>", "<CLOSE>", "<VOL>", "<OPENINT>",
)

# Directory layout: "<exchange> <asset class>/<1|2|3>/<ticker>.us.txt".
# The exchange and asset class are carried by the PATH, not by any column --
# which is the only place this dataset states them, and both are needed by the
# section 3 filters.
EXCHANGE_FROM_DIR = {"nyse": "NYSE", "nasdaq": "NASDAQ", "nysemkt": "NYSEAMERICAN"}
COMMON_DIR_SUFFIX = "stocks"


class StooqError(ValueError):
    """The local Stooq export is missing or malformed."""


class StooqNotDownloaded(StooqError):
    """No local export exists, and this module cannot fetch one."""


@dataclass(frozen=True)
class StooqFile:
    ticker: str
    path: str
    sha256: str
    rows: int
    first_date: str
    last_date: str


def download_instructions(root: Path) -> str:
    """Exactly what the operator has to do, since the code cannot do it."""
    return (
        f"No Stooq export found at {root}.\n"
        f"\n"
        f"  This module cannot download it. Stooq serves both its bulk archive\n"
        f"  and its per-symbol CSV endpoint behind a JavaScript proof-of-work bot\n"
        f"  challenge, and solving that programmatically is out of bounds.\n"
        f"\n"
        f"  Download manually in a browser:\n"
        f"    1. https://stooq.com/db/h/  ->  'Daily' / 'US' bundle  (one zip)\n"
        f"       or, per symbol: https://stooq.com/q/d/?s=aapl.us -> 'Download data'\n"
        f"    2. unzip / place the .csv files directly under:\n"
        f"         {root}\n"
        f"    3. filenames must be <ticker>.us.csv, e.g. aapl.us.csv\n"
        f"\n"
        f"  Stooq data is licensed for PERSONAL, NON-COMMERCIAL use. The raw files\n"
        f"  are NOT committed -- only their SHA-256 hashes enter the manifest.\n"
    )


def read_local_export(root: Path | str) -> tuple[dict, list]:
    """Read every Stooq CSV under `root`. Returns (frames_by_ticker, manifest).

    Fails loudly on a missing directory, an empty directory, or a file whose
    header is not the documented Stooq daily schema. A malformed file is never
    skipped silently -- a quietly smaller universe is the failure mode this whole
    project exists to prevent.
    """
    directory = Path(root)
    if not directory.exists():
        raise StooqNotDownloaded(download_instructions(directory))

    csvs = sorted(directory.glob("*.csv"))
    if not csvs:
        raise StooqNotDownloaded(download_instructions(directory))

    frames: dict = {}
    manifest: list = []

    for path in csvs:
        payload = path.read_bytes()
        frame = pd.read_csv(path)

        missing = [c for c in EXPECTED_COLUMNS if c not in frame.columns]
        if missing:
            raise StooqError(
                f"{path.name}: missing column(s) {missing}. Expected the Stooq "
                f"daily schema {list(EXPECTED_COLUMNS)}; got {list(frame.columns)}. "
                f"This file is NOT skipped -- fix or remove it."
            )
        if frame.empty:
            raise StooqError(
                f"{path.name}: zero rows. An empty file is a failure, not an "
                f"empty security."
            )

        frame["Date"] = pd.to_datetime(frame["Date"])
        frame = frame.sort_values("Date").reset_index(drop=True)

        ticker = path.name.replace(".csv", "").upper()
        frames[ticker] = frame
        manifest.append(
            StooqFile(
                ticker=ticker,
                path=path.name,
                sha256=hashlib.sha256(payload).hexdigest(),
                rows=len(frame),
                first_date=str(frame["Date"].iloc[0].date()),
                last_date=str(frame["Date"].iloc[-1].date()),
            )
        )

    return frames, manifest


# ---------------------------------------------------------------------------
# the real bulk reader
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StooqSecurity:
    ticker: str          # bare symbol, e.g. "AAPL"
    exchange: str        # NYSE / NASDAQ / NYSEAMERICAN, from the directory
    asset_class: str     # "stocks" or "etfs", from the directory
    path: Path
    sha256: str
    rows: int
    first_date: str
    last_date: str


def scan_bulk_export(root: Path | str) -> list:
    """Index a Stooq bulk US download WITHOUT loading the price bodies.

    1.8 GB across ~13,000 files; the caller chooses a subset before anything is
    parsed. Exchange and asset class come from the directory names, which is the
    only place this dataset records them.
    """
    directory = Path(root)
    if not directory.exists():
        raise StooqNotDownloaded(download_instructions(directory))

    found: list = []
    for path in sorted(directory.rglob("*.txt")):
        parts = [p.lower() for p in path.relative_to(directory).parts]
        bucket = next((p for p in parts if " " in p), "")
        if not bucket:
            continue
        exchange_word, _, asset_class = bucket.partition(" ")
        exchange = EXCHANGE_FROM_DIR.get(exchange_word)
        if exchange is None:
            continue

        name = path.name.lower()
        if not name.endswith(".us.txt"):
            continue
        found.append(
            StooqSecurity(
                ticker=name[: -len(".us.txt")].upper(),
                exchange=exchange,
                asset_class=asset_class.strip(),
                path=path,
                sha256="",
                rows=0,
                first_date="",
                last_date="",
            )
        )

    if not found:
        raise StooqNotDownloaded(download_instructions(directory))
    return found


def read_security(security: StooqSecurity) -> tuple:
    """Parse one Stooq file. Returns (frame, StooqSecurity with hash/rows filled).

    A malformed file raises. It is never skipped -- a quietly smaller universe is
    exactly the failure this project exists to prevent.
    """
    payload = security.path.read_bytes()
    frame = pd.read_csv(security.path)

    missing = [c for c in EXPECTED_COLUMNS if c not in frame.columns]
    if missing:
        raise StooqError(
            f"{security.path.name}: missing column(s) {missing}. Expected the "
            f"Stooq bulk schema {list(EXPECTED_COLUMNS)}; got {list(frame.columns)}."
        )
    if frame.empty:
        raise StooqError(f"{security.path.name}: zero rows -- a failure, not an empty security.")

    frame = frame.rename(
        columns={
            "<DATE>": "date", "<OPEN>": "open", "<HIGH>": "high",
            "<LOW>": "low", "<CLOSE>": "close", "<VOL>": "volume",
        }
    )
    frame["date"] = pd.to_datetime(frame["date"].astype(str), format="%Y%m%d")
    frame = frame[["date", "open", "high", "low", "close", "volume"]]
    frame = frame.sort_values("date").reset_index(drop=True)

    import hashlib as _hashlib

    described = StooqSecurity(
        ticker=security.ticker,
        exchange=security.exchange,
        asset_class=security.asset_class,
        path=security.path,
        sha256=_hashlib.sha256(payload).hexdigest(),
        rows=len(frame),
        first_date=str(frame["date"].iloc[0].date()),
        last_date=str(frame["date"].iloc[-1].date()),
    )
    return frame, described
