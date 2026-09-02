"""PULSE_BOUNDED_STATE_V1 -- bounded operational state.

THE LAW THIS ENCODES
--------------------
EVIDENCE MAY GROW WITHOUT BOUND DURING THE RETENTION HORIZON.
OPERATIONAL WORKING STATE MAY NOT.

WHY
---
PULSE_V0's minute path called RollingStore.restore() and
PremarketPath.restore(), each of which did
    for line in self.journal.read_text().splitlines()
on a journal that grew all session. Startup went 1.35s -> 57.59s
(42.6x) in ONE session, resident memory climbed into the gigabytes,
and the two consequences were:
    TIME   -> occupancy crossed 60s, systemd discarded 24 timer fires
    MEMORY -> global OOM killed the process 77 times
One defect, two resources.

So: the append-only ledger remains the AUTHORITATIVE EVIDENCE and may
grow to any size. Restart state comes from this small checkpoint
instead, whose size is a function of the CURRENT REQUIRED WINDOW and
never of session history.

A checkpoint is OPERATIONAL STATE. It is NOT canonical evidence and
must never be cited as such.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

CHECKPOINT_VERSION = "PULSE_BOUNDED_STATE_V1"
MAX_CHECKPOINT_BYTES = 8 * 1024 * 1024      # hard ceiling; see enforce
DEFAULT_ROLLING_MINUTES = 60


class CheckpointError(Exception):
    pass


class CheckpointCorrupt(CheckpointError):
    pass


class CheckpointVersionMismatch(CheckpointError):
    pass


class UnboundedStateRefused(CheckpointError):
    """Raised when a caller tries to reintroduce PULSE-005."""


@dataclass
class RollingState:
    """Bounded per-subject ring. Cardinality is a function of the
    WINDOW, never of how long the process has been alive."""
    window_minutes: int = DEFAULT_ROLLING_MINUTES
    observations: dict[str, list] = field(default_factory=dict)

    def observe(self, subject: str, at: datetime, price=None,
                volume=None) -> None:
        arr = self.observations.setdefault(subject, [])
        arr.append([at.isoformat(), price, volume])
        self.prune(subject, at)

    def prune(self, subject: str, now: datetime) -> None:
        cutoff = now - timedelta(minutes=self.window_minutes)
        arr = self.observations.get(subject) or []
        self.observations[subject] = [
            r for r in arr
            if datetime.fromisoformat(r[0]) >= cutoff]

    def prune_all(self, now: datetime) -> None:
        for s in list(self.observations):
            self.prune(s, now)
            if not self.observations[s]:
                del self.observations[s]

    def assert_bounded(self, *, per_minute: int = 1) -> None:
        """Refuse to hold more than the window can justify.

        prune() trusts a caller-supplied clock. If observations are
        stamped on a different clock than the prune cutoff, the cutoff
        never reaches them, nothing is ever evicted, and the ring grows
        without bound -- silently reproducing PULSE-005 through the
        back door. That exact mismatch occurred in the off-hours
        engineering harness, where observations carried wall-clock time
        while pruning used backdated slots.

        A bound that is only maintained by convention is not a bound.
        """
        limit = self.bound(subjects=max(1, len(self.observations)),
                           per_minute=per_minute)
        held = self.cardinality()
        if held > limit:
            raise UnboundedStateRefused(
                f"rolling state holds {held} observations but its "
                f"{self.window_minutes}-minute window over "
                f"{len(self.observations)} subjects permits at most "
                f"{limit}. The prune clock and the observation clock "
                f"have diverged.")

    def cardinality(self) -> int:
        return sum(len(v) for v in self.observations.values())

    def bound(self, subjects: int, *, per_minute: int = 1) -> int:
        """The maximum this may ever hold.

        prune() retains samples with ts >= now - window_minutes, which
        is a CLOSED interval: at one sample per minute a 60-minute
        window holds 61 samples, not 60. The bound is therefore
        (window + 1) * rate * subjects. Still O(window), never
        O(session) -- which is the property that matters.
        """
        return subjects * (self.window_minutes + 1) * per_minute


@dataclass
class Checkpoint:
    schema_version: str = CHECKPOINT_VERSION
    written_at: str = ""
    session_date: str = ""
    cycle_number: int = 0
    rolling: RollingState = field(default_factory=RollingState)
    premarket: dict = field(default_factory=dict)
    session_anchors: dict = field(default_factory=dict)
    source_cursors: dict = field(default_factory=dict)
    last_state_ids: dict = field(default_factory=dict)
    market_context_ref: str | None = None
    state_hash: str = ""

    # ---- serialisation ----------------------------------------------
    def to_dict(self) -> dict:
        d = {
            "schema_version": self.schema_version,
            "written_at": self.written_at,
            "session_date": self.session_date,
            "cycle_number": self.cycle_number,
            "rolling": {
                "window_minutes": self.rolling.window_minutes,
                "observations": self.rolling.observations},
            "premarket": self.premarket,
            "session_anchors": self.session_anchors,
            "source_cursors": self.source_cursors,
            "last_state_ids": self.last_state_ids,
            "market_context_ref": self.market_context_ref,
            "IS_NOT_EVIDENCE": "operational restart state only; the "
                               "append-only ledger is authoritative",
        }
        d["state_hash"] = hashlib.sha256(
            json.dumps(d, sort_keys=True).encode()).hexdigest()
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Checkpoint":
        got = d.get("schema_version")
        if got != CHECKPOINT_VERSION:
            raise CheckpointVersionMismatch(
                f"checkpoint schema {got!r} != {CHECKPOINT_VERSION!r}")
        claimed = d.get("state_hash")
        body = {k: v for k, v in d.items() if k != "state_hash"}
        # recompute exactly as to_dict built it
        recomputed = hashlib.sha256(
            json.dumps(body, sort_keys=True).encode()).hexdigest()
        if recomputed != claimed:
            raise CheckpointCorrupt(
                "checkpoint state_hash does not match its content")
        r = d.get("rolling") or {}
        return cls(
            schema_version=got,
            written_at=d.get("written_at", ""),
            session_date=d.get("session_date", ""),
            cycle_number=d.get("cycle_number", 0),
            rolling=RollingState(
                window_minutes=r.get("window_minutes",
                                     DEFAULT_ROLLING_MINUTES),
                observations=r.get("observations") or {}),
            premarket=d.get("premarket") or {},
            session_anchors=d.get("session_anchors") or {},
            source_cursors=d.get("source_cursors") or {},
            last_state_ids=d.get("last_state_ids") or {},
            market_context_ref=d.get("market_context_ref"),
            state_hash=claimed or "")


def write_atomic(path: Path, ck: Checkpoint, *,
                 max_bytes: int = MAX_CHECKPOINT_BYTES) -> dict:
    """Atomic replace: a torn checkpoint must never be readable.

    Refuses to write an oversized checkpoint -- an unbounded checkpoint
    is PULSE-005 wearing a different hat.
    """
    ck.written_at = datetime.now(timezone.utc).isoformat()
    d = ck.to_dict()
    payload = json.dumps(d, sort_keys=True).encode()
    if len(payload) > max_bytes:
        raise UnboundedStateRefused(
            f"checkpoint is {len(payload)} bytes (> {max_bytes}). "
            "Operational state must remain bounded; prune the window "
            "rather than raising this ceiling.")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)          # atomic within a filesystem
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return {"bytes": len(payload), "state_hash": d["state_hash"],
            "path": str(path)}


def load(path: Path) -> Checkpoint:
    if not path.exists():
        raise CheckpointError(f"no checkpoint at {path}")
    try:
        d = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        raise CheckpointCorrupt(f"checkpoint is not valid JSON: {e}")
    return Checkpoint.from_dict(d)


def recover(path: Path, *, bounded_rebuild, session_date: str,
            allow_full_history: bool = False) -> tuple[Checkpoint, str]:
    """Restart recovery. NEVER falls back to reading all history.

    On missing / corrupt / version-mismatched checkpoint we rebuild
    ONLY from a strictly bounded authoritative window. A silent
    full-history fallback would recreate PULSE-005 exactly, so it is
    refused rather than offered.
    """
    if allow_full_history:
        raise UnboundedStateRefused(
            "full-history rebuild is permanently refused in the minute "
            "path: it is the PULSE-005 defect by another name")
    try:
        ck = load(path)
    except (CheckpointError,) as e:
        ck = bounded_rebuild(session_date)
        if not isinstance(ck, Checkpoint):
            raise CheckpointError("bounded_rebuild must return a "
                                  "Checkpoint")
        return ck, f"BOUNDED_REBUILD ({type(e).__name__}: {e})"
    if ck.session_date and ck.session_date != session_date:
        ck2 = bounded_rebuild(session_date)
        return ck2, "BOUNDED_REBUILD (session_date changed)"
    return ck, "CHECKPOINT_LOADED"


def restore_complexity_probe(path: Path, ledger_bytes: int) -> dict:
    """Evidence that restore cost is independent of evidence size.

    Acceptance requires this to hold as ledger_bytes grows by orders of
    magnitude while checkpoint bytes stay flat.
    """
    size = path.stat().st_size if path.exists() else 0
    return {
        "checkpoint_bytes": size,
        "ledger_bytes": ledger_bytes,
        "ratio": (size / ledger_bytes) if ledger_bytes else None,
        "BOUNDED": size <= MAX_CHECKPOINT_BYTES,
        "law": "restore reads the checkpoint only; ledger size must "
               "not appear in restore cost",
    }
