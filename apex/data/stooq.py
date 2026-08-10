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

EXPECTED_COLUMNS = ("Date", "Open", "High", "Low", "Close", "Volume")


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
