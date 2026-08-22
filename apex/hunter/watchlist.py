"""THE CANONICAL WATCHLIST CONTRACT — one writer, one reader.

Root cause of the 2026-08-17 FastWatch crash: apex/hunter/scanner.py's
ScanResult.as_record() has ALWAYS persisted watchlist entries as dicts
({"symbol", "signals", "rvol"}), but apex/hunter/microscope.py's
select_targets() has ALWAYS unpacked them as positional tuples
(entry[0], entry[1], entry[2]) — a dict raises KeyError on that, caught
by neither the IndexError nor TypeError the handler listed. This was
invisible until the first non-empty persisted watchlist arrived, because
nothing had ever exercised the real (dict) shape end-to-end.

This module is the single schema both sides speak. No positional
access, no hand-maintained duplicate structure, no silent "best effort"
on an unrecognized version.

RVOL HONESTY: a Scout-computed rvol can be None (SESSION INTEGRITY GATE,
apex/hunter/chartstate.py v1.2 — cs.rvol_tod is None on an invalid
session anchor). The OLD scanner code laundered that into 0.0 before
persisting it, which is indistinguishable from a genuinely-observed
near-zero relative volume. This contract keeps them apart: `rvol` is
the real value or None, `rvol_status` says why.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

ERRORS_LEDGER = Path("results/hunter/watchlist_contract_errors.jsonl")

WATCHLIST_SCHEMA_VERSION = "watchlist_schema_v1"

RVOL_VALID = "VALID"
RVOL_INVALID_SESSION = "INVALID_MISSING_SESSION_START"
RVOL_UNKNOWN = "UNKNOWN"

REFUSE_SCHEMA_VERSION = "REFUSE_SCHEMA_VERSION"


class WatchlistContractViolation(RuntimeError):
    pass


@dataclass(frozen=True)
class WatchlistEntry:
    symbol: str
    signals: tuple                     # tuple[str, ...]
    rvol: float | None
    rvol_status: str = RVOL_UNKNOWN
    created_at: str | None = None
    as_of: str | None = None
    source: str = "scout_scanner"
    quality: str = "OK"
    schema_version: str = WATCHLIST_SCHEMA_VERSION

    def as_record(self) -> dict:
        return asdict(self)

    def sort_key(self) -> tuple:
        """Deterministic priority key: signal count desc, THEN whether
        rvol is actually known (known ranks above unknown -- we trust a
        more complete observation more, at equal signal count), THEN
        rvol desc when known, THEN symbol for a total order. Never
        treats an unknown rvol as zero -- zero would wrongly outrank a
        real-but-small positive rvol AND wrongly get outranked by it,
        depending on sign; "unknown" is its own tier, always."""
        rvol_known = self.rvol is not None
        return (-len(self.signals), 0 if rvol_known else 1,
               -(self.rvol or 0.0), self.symbol)


def make_entry(symbol: str, signals, rvol: float | None, *,
              rvol_status: str | None = None, created_at: str | None = None,
              as_of: str | None = None,
              source: str = "scout_scanner") -> WatchlistEntry:
    """Producer-side constructor. rvol_status is inferred from rvol's
    presence when not given explicitly."""
    if rvol_status is None:
        rvol_status = RVOL_VALID if rvol is not None else RVOL_UNKNOWN
    return WatchlistEntry(symbol=symbol, signals=tuple(signals), rvol=rvol,
                          rvol_status=rvol_status, created_at=created_at,
                          as_of=as_of, source=source)


def parse_watchlist_entry(raw) -> tuple:
    """(entry, error). NEVER raises on malformed input -- the caller
    decides whether to skip-and-record or halt. A dict is the only
    accepted shape; anything else (a stray tuple/list from an older or
    foreign producer) is a MALFORMED refusal, not a crash."""
    if not isinstance(raw, dict):
        return None, f"MALFORMED_NOT_A_DICT:{type(raw).__name__}"

    version = raw.get("schema_version", WATCHLIST_SCHEMA_VERSION)
    if version != WATCHLIST_SCHEMA_VERSION:
        return None, f"{REFUSE_SCHEMA_VERSION}:{version}"

    sym = raw.get("symbol")
    if not sym or not isinstance(sym, str):
        return None, "MALFORMED_MISSING_OR_INVALID_SYMBOL"

    sigs = raw.get("signals")
    if not isinstance(sigs, (list, tuple)):
        return None, "MALFORMED_SIGNALS_NOT_A_LIST"
    if not all(isinstance(s, str) for s in sigs):
        return None, "MALFORMED_SIGNAL_ELEMENT_NOT_A_STRING"

    rvol = raw.get("rvol")
    if rvol is not None and not isinstance(rvol, (int, float)):
        return None, "MALFORMED_RVOL_TYPE"

    rvol_status = raw.get("rvol_status")
    if rvol_status is None:
        rvol_status = RVOL_VALID if rvol is not None else RVOL_UNKNOWN

    return WatchlistEntry(
        symbol=sym, signals=tuple(sigs),
        rvol=float(rvol) if rvol is not None else None,
        rvol_status=rvol_status,
        created_at=raw.get("created_at"), as_of=raw.get("as_of"),
        source=raw.get("source", "scout_scanner"),
        quality=raw.get("quality", "OK")), None


def record_parse_errors(errors: tuple, *, component: str,
                        input_reference: str | None = None) -> None:
    """Durable, structured error persistence (never buffered-stdout-only
    -- that is precisely how the 2026-08-17 Frontier stall hid for
    ~3 hours: the crash WAS printed, into a block-buffered pipe that
    never flushed). One row per malformed entry, chain-appended."""
    if not errors:
        return
    import sys
    sys.path.insert(0, "scripts")
    from nightly_pull import _chain_append
    import pandas as pd
    now = str(pd.Timestamp.now(tz="UTC"))
    ERRORS_LEDGER.parent.mkdir(parents=True, exist_ok=True)
    for err in errors:
        _chain_append(ERRORS_LEDGER, {
            "kind": "watchlist_contract_error", "timestamp_utc": now,
            "component": component, "exception_type": "MALFORMED_ENTRY",
            "message": err.get("error"), "input_reference": input_reference,
            "input_index": err.get("index"), "input_raw_type": err.get("raw_type"),
            "schema_version": WATCHLIST_SCHEMA_VERSION,
            "recoverable": True})


def parse_watchlist(raw_list) -> tuple:
    """(entries, errors). Every malformed entry is skipped AND recorded
    -- one bad row never costs the good ones."""
    entries, errors = [], []
    for i, raw in enumerate(raw_list or []):
        entry, err = parse_watchlist_entry(raw)
        if entry is not None:
            entries.append(entry)
        else:
            errors.append({"index": i, "error": err, "raw_type":
                          type(raw).__name__})
    return tuple(entries), tuple(errors)
