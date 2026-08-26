"""DURABLE SHADOW OUTBOX — a research day survives a crashed consumer.

Tuesday's EdgeForge Observatory did not run, and because observation
was live-only, the day is gone forever. No prospective boundary state
from 2026-08-25 will ever exist. That is the loss this module makes
structurally impossible.

    V1  ->  append-only OUTBOX  ->  checkpointed CURSOR  ->  EDGEFORGE

V1 writes sealed observations and never waits. The consumer keeps a
durable cursor and, on restart, resumes from the last CONFIRMED
record. A thirty-minute outage costs thirty minutes of latency, not a
day of evidence.

GUARANTEES, each enforced by test:
  append-only          records are never edited or reordered
  idempotent           re-consuming a record commits nothing twice
  replay-safe          a crash between read and commit re-delivers,
                       it does not skip
  lineage preserved    every record keeps source pedigree + hash
  no fabrication       a field V1 never recorded stays absent; the
                       consumer may not invent it to fill a gap

DIRECTION IS ABSOLUTE: V1 -> EDGEFORGE. The consumer never writes
back, and nothing in this module offers a path for it to.

decision_power: NONE_OBSERVATIONAL.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from apex.governance.chain_ledger import chain_append

CURSOR_KIND = "outbox_cursor"


class OutboxViolation(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def emit(outbox: Path, *, kind: str, session: str, payload: dict,
         source: str, known_from: str) -> dict:
    """V1 seals one observation. Hash-chained; never blocks on a
    consumer, and never learns whether one exists."""
    if not kind or not session or not source:
        raise OutboxViolation(
            "an observation without kind/session/source has no lineage "
            "and cannot be research evidence")
    rec = {"kind": "outbox_record", "record_kind": kind,
           "session": session, "source": source,
           "known_from": known_from, "emitted_utc": _now(),
           "payload": payload}
    return chain_append(outbox, rec)


def read_records(outbox: Path) -> list:
    if not outbox.exists():
        return []
    out = []
    for i, line in enumerate(outbox.read_text().splitlines()):
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("kind") == "outbox_record":
            r["_seq"] = i
            out.append(r)
    return out


@dataclass
class Cursor:
    """A durable position. Written atomically, so a crash mid-write
    leaves the OLD cursor intact and the record is simply redelivered
    -- at-least-once, which idempotent commits turn into exactly-once
    in effect."""
    path: Path
    consumer: str

    def load(self) -> dict:
        if not self.path.exists():
            return {"kind": CURSOR_KIND, "consumer": self.consumer,
                    "last_consumed_seq": -1, "last_consumed_hash": None,
                    "events_processed": 0, "writes_committed": 0}
        d = json.loads(self.path.read_text())
        if d.get("consumer") != self.consumer:
            raise OutboxViolation(
                f"cursor belongs to {d.get('consumer')!r}, not "
                f"{self.consumer!r}: two consumers sharing one cursor "
                f"would silently skip each other's records")
        return d

    def commit(self, *, seq: int, record_hash: str | None,
               writes: int) -> dict:
        cur = self.load()
        if seq <= cur["last_consumed_seq"]:
            # IDEMPOTENT: replay of an already-committed record is a
            # no-op, not a duplicate observation.
            return cur
        cur.update({"last_consumed_seq": seq,
                    "last_consumed_hash": record_hash,
                    "events_processed": cur["events_processed"] + 1,
                    "writes_committed": cur["writes_committed"] + writes,
                    "updated_utc": _now()})
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent))
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(cur, f, indent=1)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        return cur


def pending(outbox: Path, cursor: Cursor) -> list:
    cur = cursor.load()
    return [r for r in read_records(outbox)
            if r["_seq"] > cur["last_consumed_seq"]]


def consume(outbox: Path, cursor: Cursor, handler,
            *, max_records: int | None = None) -> dict:
    """Drain the outbox from the cursor forward.

    The handler returns the number of writes it committed. A handler
    exception STOPS the drain at that record without advancing the
    cursor, so the failed record is retried rather than skipped --
    losing an observation is worse than processing it late."""
    todo = pending(outbox, cursor)
    if max_records is not None:
        todo = todo[:max_records]
    processed, failed = 0, None
    for r in todo:
        try:
            writes = handler(r) or 0
        except Exception as e:                          # noqa: BLE001
            failed = {"seq": r["_seq"], "error": repr(e)}
            break
        cursor.commit(seq=r["_seq"], record_hash=r.get("hash"),
                      writes=int(writes))
        processed += 1
    cur = cursor.load()
    return {"kind": "outbox_drain", "consumer": cursor.consumer,
            "records_processed": processed,
            "records_remaining": len(pending(outbox, cursor)),
            "failed_at": failed,
            "cursor": {k: cur[k] for k in
                       ("last_consumed_seq", "events_processed",
                        "writes_committed")},
            "law": "a failed record is retried, never skipped",
            "decision_power": "NONE_OBSERVATIONAL"}


def consumer_health(outbox: Path, cursor: Cursor, *,
                    session_active: bool,
                    lag_threshold: int = 50) -> dict:
    """PROGRESS, not liveness. A consumer that is alive while V1
    produces eligible records and its cursor does not move is stalled,
    and during a session that is the whole failure."""
    recs = read_records(outbox)
    cur = cursor.load()
    lag = len([r for r in recs if r["_seq"] > cur["last_consumed_seq"]])
    last_src = recs[-1].get("emitted_utc") if recs else None
    if not recs:
        state = "NO_SOURCE_EVENTS"
    elif lag == 0:
        state = "CAUGHT_UP"
    elif session_active and lag > lag_threshold:
        state = "EDGEFORGE_CONSUMER_STALLED"
    else:
        state = "CATCHING_UP"
    return {"kind": "consumer_health", "consumer": cursor.consumer,
            "events_seen": len(recs),
            "events_processed": cur["events_processed"],
            "last_source_event_time": last_src,
            "last_consumed_id": cur["last_consumed_seq"],
            "consumer_lag": lag,
            "writes_committed": cur["writes_committed"],
            "state": state,
            "severity": ("CRITICAL"
                         if state == "EDGEFORGE_CONSUMER_STALLED"
                         else "OK"),
            "decision_power": "NONE_OBSERVATIONAL"}
