"""Trial accounting: every fit is a trial, and the denominator is visible.

A model selected from 500 configurations and reported as one result is the
definition of the failure mode the research budget was written against. The
TrialLedger is append-only and hash-chained (the house pattern); a sweep
cannot report as a single trial because each fit writes its own row, and a
candidate whose claimed trial count is below the ledger's count for its
family is REFUSED at emission.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


def _canon(obj) -> str:
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


class TrialLedger:
    """Append-only chained record of every model fit in a family."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def _rows(self) -> list[dict]:
        if not self.path.exists():
            return []
        return [json.loads(l) for l in self.path.read_text().strip().splitlines()]

    def record(self, family: str, config: dict, score: float,
               fold_scheme: str) -> dict:
        rows = self._rows()
        prev = rows[-1]["entry_hash"] if rows else "GENESIS"
        body = {"family": family, "config_hash": _canon(config)[:16],
                "config": config, "score": float(score),
                "fold_scheme": fold_scheme, "prev_hash": prev}
        body["entry_hash"] = _canon(body)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as fh:
            fh.write(json.dumps(body, sort_keys=True) + "\n")
        return body

    def verify(self) -> int:
        prev = "GENESIS"
        for i, r in enumerate(self._rows()):
            body = {k: v for k, v in r.items() if k != "entry_hash"}
            if r["prev_hash"] != prev or _canon(body) != r["entry_hash"]:
                raise ValueError(f"trial ledger broken at row {i}")
            prev = r["entry_hash"]
        return len(self._rows())

    def denominator(self, family: str) -> int:
        """The number that must accompany every reported result."""
        return sum(1 for r in self._rows() if r["family"] == family)

    def scores(self, family: str) -> list[float]:
        return [r["score"] for r in self._rows() if r["family"] == family]

    def families(self) -> dict:
        out: dict = {}
        for r in self._rows():
            out[r["family"]] = out.get(r["family"], 0) + 1
        return out
