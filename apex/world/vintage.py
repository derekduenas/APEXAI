"""The vintage store -- the central hazard of macro data, handled structurally.

Macro series are revised, often substantially, months after first release.
Using today's revised GDP as though it were knowable historically is the most
common lookahead error in macro research, and the market/fundamental PIT
firewall does not cover it. Here:

  * every value is stored AS RELEASED, with its release timestamp; each
    revision is a separate vintage row, append-only;
  * `asof(series, period, date)` returns the vintage knowable at `date`,
    never the latest;
  * a series only available in revised form is declared REVISED_ONLY at
    creation and is REFUSED by the confirmatory guard -- it may inform
    exploration as an ASSUMPTION, never evidence.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


class VintageError(ValueError):
    """A vintage-store invariant was violated."""


class RevisedOnlyRefused(RuntimeError):
    """A REVISED_ONLY series was offered where confirmatory data is required."""


class VintageStore:
    """Append-only JSONL of (series, period, value, released_at) vintages."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.meta_path = self.path.with_suffix(".meta.json")

    # -- declaration ---------------------------------------------------------

    def declare(self, series: str, source: str, revised_only: bool) -> None:
        meta = self._meta()
        if series in meta and meta[series]["revised_only"] != revised_only:
            raise VintageError(
                f"{series} already declared with revised_only="
                f"{meta[series]['revised_only']}; the flag cannot be revised")
        meta[series] = {"source": source, "revised_only": bool(revised_only)}
        self.meta_path.parent.mkdir(parents=True, exist_ok=True)
        self.meta_path.write_text(json.dumps(meta, indent=2, sort_keys=True))

    def _meta(self) -> dict:
        if not self.meta_path.exists():
            return {}
        return json.loads(self.meta_path.read_text())

    # -- writes (append-only) ------------------------------------------------

    def add(self, series: str, period: str, value: float, released_at: str) -> None:
        if series not in self._meta():
            raise VintageError(f"{series} must be declared before values are added")
        row = {"series": series, "period": period, "value": float(value),
               "released_at": released_at}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as fh:
            fh.write(json.dumps(row, sort_keys=True) + "\n")

    def _rows(self) -> list[dict]:
        if not self.path.exists():
            return []
        return [json.loads(l) for l in self.path.read_text().strip().splitlines()]

    # -- the PIT query -------------------------------------------------------

    def asof(self, series: str, period: str, date: str):
        """The vintage knowable at `date` -- the latest release AT OR BEFORE
        it. Returns None when nothing was knowable. NEVER returns a later
        revision: the release timestamp is the only admission criterion."""
        best = None
        for r in self._rows():
            if r["series"] != series or r["period"] != period:
                continue
            if pd.Timestamp(r["released_at"]) <= pd.Timestamp(date):
                if best is None or r["released_at"] > best["released_at"]:
                    best = r
        return None if best is None else best["value"]

    def latest(self, series: str, period: str):
        """The most recent vintage regardless of date -- for DISPLAY only.
        Deliberately named so a confirmatory path calling it reads wrong."""
        rows = [r for r in self._rows()
                if r["series"] == series and r["period"] == period]
        return max(rows, key=lambda r: r["released_at"])["value"] if rows else None

    # -- the confirmatory guard ----------------------------------------------

    def require_confirmatory_series(self, series: str, context: str) -> None:
        meta = self._meta().get(series)
        if meta is None:
            raise VintageError(f"{context}: {series} is undeclared")
        if meta["revised_only"]:
            raise RevisedOnlyRefused(
                f"{context}: REFUSED -- '{series}' is REVISED_ONLY. Its "
                f"first-release vintages do not exist in this store, so any "
                f"historical value is contaminated by revision. It may inform "
                f"exploration as an ASSUMPTION; it is never evidence.")
