"""Morning Prior manifest — deterministic lookup, no filename guessing.

WHY THIS EXISTS (measured 2026-08-18): the end-of-day forensic recap
could not locate a sealed Morning Prior artifact for the session,
despite one reportedly sealing pre-open. Recovery was attempted by
searching for `*morning_prior*` across the repo -- i.e. guessing
filenames -- and found nothing. An artifact that cannot be
deterministically located at close may as well not have been sealed.

Every Morning Prior now registers here at seal time with a canonical
path, date, sealed_at, content hash, source health and known_from.
`locate(session_date)` is an exact lookup: it either returns the
registered entry or returns None. It never globs, never guesses, and
never returns a "probably this one" match.

decision_power: NONE_MEMORY.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from apex.memory import MEMORY_POWER

LEDGER = Path("results/memory/morning_prior_manifest.jsonl")


class MorningPriorManifestError(RuntimeError):
    pass


@dataclass(frozen=True)
class MorningPriorEntry:
    session_date: str
    canonical_path: str
    sealed_at: str
    content_hash: str
    source_health: dict
    known_from: str
    runtime_version: str
    decision_power: str = MEMORY_POWER

    def as_record(self) -> dict:
        return {"kind": "morning_prior_manifest_entry", **asdict(self)}


def content_hash_of(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def register(*, session_date: str, canonical_path, source_health: dict,
             known_from, now, runtime_version: str = "UNSPECIFIED"
             ) -> MorningPriorEntry:
    """Called at SEAL time by whatever produces the Morning Prior. The
    file must already exist -- registering a path that isn't there would
    reproduce the exact 2026-08-18 failure in a new form."""
    import pandas as pd
    p = Path(canonical_path)
    if not p.exists():
        raise MorningPriorManifestError(
            f"refusing to register a Morning Prior that does not exist on "
            f"disk: {p}")
    entry = MorningPriorEntry(
        session_date=session_date, canonical_path=str(p),
        sealed_at=str(pd.Timestamp(now)), content_hash=content_hash_of(p),
        source_health=dict(source_health),
        known_from=str(pd.Timestamp(known_from)),
        runtime_version=runtime_version)
    import sys
    sys.path.insert(0, "scripts")
    from nightly_pull import _chain_append
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    _chain_append(LEDGER, entry.as_record())
    return entry


def _read_all() -> list:
    if not LEDGER.exists():
        return []
    out = []
    for line in LEDGER.read_text().splitlines():
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def locate(session_date: str) -> dict | None:
    """Deterministic exact lookup. Returns the registered entry plus a
    live integrity check, or None. Never guesses a filename."""
    matches = [r for r in _read_all() if r.get("session_date") == session_date]
    if not matches:
        return None
    entry = matches[-1]
    p = Path(entry["canonical_path"])
    if not p.exists():
        return {**entry, "integrity": "REGISTERED_BUT_MISSING_ON_DISK"}
    current = content_hash_of(p)
    return {**entry,
            "integrity": ("INTACT" if current == entry["content_hash"]
                         else "CONTENT_HASH_MISMATCH"),
            "current_content_hash": current}
