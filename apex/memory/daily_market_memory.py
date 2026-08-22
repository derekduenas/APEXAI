"""ENRICHED_RESEARCH_MEMORY_SIDECAR — a richer, forensic record of what
a single session looked like and what APEX did/didn't see.

*** NOT CANONICAL. decision_power = NONE. ***

OPERATOR RULING 2026-08-18, after the full-system audit found TWO
competing DailyMarketMemory implementations:

    CANONICAL (unchanged, operationally proven end-to-end):
        apex/frontier/closing.py::write_memory
            -> results/frontier/daily_memory/{date}.json
            -> apex/frontier/premarket.py::load_memory

    THIS MODULE: a research/forensic sidecar only.

This module was built in Phase 1.0 without checking for the existing
implementation, and its output was an ORPHANED WRITE -- sealed nightly
and read by nobody in the live path. Richer + orphaned is worse than
simpler + proven, so the legacy path stays canonical for the 2026-08-19
natural acceptance session.

DO NOT point premarket at this module. DO NOT schedule it as a second
production memory writer. One canonical memory, no competing writers.
After acceptance, the two schemas get compared and merged into a single
DailyMarketMemory V2 -- not maintained as two brains.

READ AS YESTERDAY_STATE, NEVER AS CURRENT_TRUTH. `load_as_yesterday_state()`
is the only retrieval function, and it stamps every returned record with
`read_as="YESTERDAY_STATE"` plus the age in sessions -- a caller cannot
accidentally treat a stale memory as a live belief without deliberately
stripping that label.

NO HINDSIGHT RULES. This dataclass has fields for OBSERVATIONS and for
UNKNOWNS. It has no field for a rule, threshold, weight, or
recommendation, so a hindsight-derived trading rule structurally cannot
be stored here.

Append-only and content-addressed: sealing the same session twice with
identical content is a DUPLICATE (no new row); sealing DIFFERENT content
for an already-sealed session mints a new version that supersedes the
prior one, which is never rewritten.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from apex.memory import MEMORY_POWER

LEDGER = Path("results/memory/daily_market_memory.jsonl")

# Explicit role marker so no consumer can mistake this for canonical.
ROLE = "ENRICHED_RESEARCH_MEMORY_SIDECAR"
CANONICAL_MEMORY_PATH = "results/frontier/daily_memory/{date}.json"
CANONICAL_MEMORY_WRITER = "apex.frontier.closing.write_memory"

POSITIONS_LAW = "NONE_BY_CONSTITUTION"

# fields whose presence would turn a memory into a hindsight rule --
# checked structurally at construction, never left to reviewer vigilance.
FORBIDDEN_FIELD_SUBSTRINGS = ("rule", "threshold", "weight", "recommend",
                              "should_", "tune", "optimi")


class DailyMarketMemoryError(RuntimeError):
    pass


@dataclass(frozen=True)
class DailyMarketMemory:
    session_date: str
    day_classification: str
    regime: dict                     # {symbol: session_return_pct, ...}
    leadership: tuple                # ((symbol, return_pct), ...)
    laggards: tuple
    breadth: str
    volatility: str
    important_transitions: tuple
    persistent_relative_strength: tuple
    persistent_weakness: tuple
    failed_breakouts: tuple
    failed_breakdowns: tuple
    traps: tuple
    late_day_changes: tuple
    hunter_matches: tuple            # ({symbol, playbook, outcome...}, ...)
    fastwatch_observations: dict
    frontier2_limitations: tuple
    data_fabric_limitations: tuple
    options_limitations: tuple
    system_blind_spots: tuple
    important_unknowns: tuple
    positions_carried_overnight: str
    sealed_at: str
    known_from: str
    content_hash: str
    version: int = 1
    supersedes: str | None = None
    decision_power: str = MEMORY_POWER

    def __post_init__(self):
        if self.positions_carried_overnight != POSITIONS_LAW:
            raise DailyMarketMemoryError(
                f"positions_carried_overnight must be {POSITIONS_LAW!r}")
        bad = {f for f in self.__dataclass_fields__
              if any(s in f.lower() for s in FORBIDDEN_FIELD_SUBSTRINGS)}
        if bad:
            raise DailyMarketMemoryError(
                f"a DailyMarketMemory may not carry rule-shaped fields: {bad}")
        if self.version < 1:
            raise DailyMarketMemoryError("version must be >= 1")

    def as_record(self) -> dict:
        return {"kind": "daily_market_memory", **asdict(self)}


def _content_hash(payload: dict) -> str:
    scrubbed = {k: v for k, v in payload.items()
                if k not in ("sealed_at", "content_hash", "version", "supersedes")}
    return hashlib.sha256(
        json.dumps(scrubbed, sort_keys=True, default=str).encode()).hexdigest()


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


def latest_for(session_date: str) -> dict | None:
    matches = [r for r in _read_all() if r.get("session_date") == session_date]
    if not matches:
        return None
    return max(matches, key=lambda r: r.get("version", 0))


def seal(*, session_date: str, known_from, now, **fields) -> tuple:
    """Returns (DailyMarketMemory, verdict) where verdict is one of
    SEALED / DUPLICATE / NEW_VERSION."""
    import pandas as pd
    payload = dict(session_date=session_date, **fields)
    payload["positions_carried_overnight"] = POSITIONS_LAW
    chash = _content_hash(payload)

    prior = latest_for(session_date)
    if prior is not None and prior.get("content_hash") == chash:
        return _from_record(prior), "DUPLICATE"

    version = (prior.get("version", 0) + 1) if prior else 1
    mem = DailyMarketMemory(
        **payload, sealed_at=str(pd.Timestamp(now)),
        known_from=str(pd.Timestamp(known_from)), content_hash=chash,
        version=version,
        supersedes=(f"{session_date}:v{prior['version']}" if prior else None))

    import sys
    sys.path.insert(0, "scripts")
    from nightly_pull import _chain_append
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    _chain_append(LEDGER, mem.as_record())
    return mem, ("NEW_VERSION" if prior is not None else "SEALED")


def _from_record(rec: dict) -> DailyMarketMemory:
    fields = {f: rec.get(f) for f in DailyMarketMemory.__dataclass_fields__}
    for tf, val in list(fields.items()):
        if isinstance(val, list):
            fields[tf] = tuple(val)
    return DailyMarketMemory(**fields)


def load_as_yesterday_state(*, before_session_date: str) -> dict | None:
    """THE ONLY retrieval entry point. Returns the most recent sealed
    memory STRICTLY BEFORE `before_session_date`, wrapped with an
    explicit YESTERDAY_STATE label and its age -- never returned bare,
    so a consumer cannot mistake it for current truth."""
    candidates = [r for r in _read_all()
                 if r.get("session_date", "") < before_session_date]
    if not candidates:
        return None
    latest_date = max(r["session_date"] for r in candidates)
    same_day = [r for r in candidates if r["session_date"] == latest_date]
    rec = max(same_day, key=lambda r: r.get("version", 0))
    return {
        "read_as": "YESTERDAY_STATE",
        "not": "CURRENT_TRUTH",
        "memory_session_date": rec["session_date"],
        "requested_for_session": before_session_date,
        "caveat": ("this describes a PAST session's observations and "
                  "unknowns; it is not a belief about the requested "
                  "session and carries no rule, threshold, or bias"),
        "memory": rec,
    }
