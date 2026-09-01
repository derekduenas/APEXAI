"""UNIVERSE PROVENANCE — which subjects existed, and why.

The universe is decision-relevant factual infrastructure, not a
config detail. A count is NOT provenance: `universe_observed: 290`
cannot distinguish 290 symbols from a DIFFERENT 290, so a silent swap
of the file would be invisible in the chain while changing every
observation the World Model ever trains on.

The universe may legitimately change daily. What may never happen is
that it changes INVISIBLY. Every cycle therefore records the source,
its content hash, and the full disposition of every requested subject.

decision_power: NONE_STATE.
"""
from __future__ import annotations

import gzip
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

UNIVERSE_CONTRACT = "UNIVERSE_PROVENANCE_V0"

# disposition of a requested subject
RESOLVED = "RESOLVED"
STALE = "STALE"
MISSING = "MISSING"
EXCLUDED = "EXCLUDED"


class UniverseViolation(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_universe(path, *, builder: str = "UNKNOWN") -> dict:
    """Read a universe file and describe it completely enough that a
    later reader can tell whether it is the same universe."""
    p = Path(path)
    if not p.exists():
        raise UniverseViolation(
            f"universe file {p} is absent -- PULSE will not invent a "
            f"subject list")
    raw = p.read_bytes()
    opener = gzip.open if str(p).endswith(".gz") else open
    with opener(p, "rt") as fh:
        payload = json.load(fh)
    symbols = sorted(payload) if isinstance(payload, (list, dict)) \
        else sorted(payload.keys())
    st = p.stat()
    return {
        "contract": UNIVERSE_CONTRACT,
        "source_path": str(p),
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "source_bytes": len(raw),
        "source_mtime_utc": datetime.fromtimestamp(
            st.st_mtime, timezone.utc).isoformat(),
        "builder": builder,
        "symbol_count": len(symbols),
        # the hash of the SYMBOL SET itself, so a rebuild that changes
        # bytes but not membership is distinguishable from one that
        # changes who is in the universe
        "membership_sha256": hashlib.sha256(
            "|".join(symbols).encode()).hexdigest(),
        "symbols": symbols,
        "loaded_utc": _now(),
    }


def universe_version(u: dict) -> str:
    """The short identity stamped into every packet."""
    return f"{u['membership_sha256'][:16]}"


class Disposition:
    """Every requested subject ends in exactly one bucket, with a
    reason. Silence about a dropped subject is how a universe quietly
    shrinks."""

    def __init__(self):
        self._d = {}

    def resolved(self, sym, *, as_of=None):
        self._d[sym] = {"disposition": RESOLVED, "as_of": as_of}

    def stale(self, sym, *, age_s, tolerance_s, as_of=None):
        self._d[sym] = {"disposition": STALE, "as_of": as_of,
                        "why": f"data {age_s:.1f}s old exceeds the "
                               f"{tolerance_s:.1f}s tolerance"}

    def missing(self, sym, *, why):
        self._d[sym] = {"disposition": MISSING, "why": why}

    def excluded(self, sym, *, why):
        self._d[sym] = {"disposition": EXCLUDED, "why": why}

    def record(self, requested) -> dict:
        for sym in requested:
            self._d.setdefault(sym, {
                "disposition": MISSING,
                "why": "the provider returned nothing for this "
                       "subject and no reason was recorded"})
        by = {}
        for sym, d in self._d.items():
            by.setdefault(d["disposition"], []).append(sym)
        return {
            "requested": len(requested),
            "counts": {k: len(v) for k, v in sorted(by.items())},
            "resolved": sorted(by.get(RESOLVED, [])),
            "stale": sorted(by.get(STALE, [])),
            "missing": sorted(by.get(MISSING, [])),
            "excluded": sorted(by.get(EXCLUDED, [])),
            "reasons": {s: d for s, d in sorted(self._d.items())
                        if d["disposition"] != RESOLVED},
            "law": "every requested subject is accounted for; a "
                   "subject that simply vanished is a MISSING with a "
                   "stated reason, never an absence from the record"}
