"""PREMARKET_JOURNAL_V1 -- durable, append-only, hash-chained state for a premarket morning that is now many
processes instead of one.

WHAT THE OLD RUNNER ACTUALLY KEPT IN MEMORY, measured rather than assumed: not an accumulating builder. Each of
its four absorptions called `assemble()` and rebuilt the WHOLE packet from scratch; the only thing carried across
the hour was the local name `last`, holding the most recent packet, and the three earlier packets were
discarded unrecorded. (It also built a fresh QuotaGovernor per absorption, so its "daily" budget was really a
per-stage budget.) So "reconstruct the builder" means: recover the newest COMPLETED stage's packet, byte for
byte, from durable evidence -- and, unlike the old runner, keep the earlier ones.

THE SHAPE. One directory per trading date. One append-only `events.jsonl` whose every line is hash-chained to
its predecessor. Content-addressed blobs for captured source bytes, normalized observations and packets, so a
resumed stage reuses the ORIGINAL bytes instead of refetching. Sequence numbers are allocated under an exclusive
file lock, so two processes cannot both take one. JSON only -- never pickle, which would make the record
readable by exactly one interpreter version.

WHAT A LATER STAGE MUST DO BEFORE IT TRUSTS AN EARLIER ONE: verify the chain and re-hash every referenced blob.
An altered predecessor that kept its old digest is detected, named, and refused -- not silently ignored.
"""
from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import pathlib
import socket
import time

SCHEMA = "PREMARKET_JOURNAL_V1"

# ------------------------------------------------------------------ state vocabulary
PROGRESS = ("PENDING", "STARTED", "CAPTURED", "NORMALIZED", "ABSORBED", "COMPLETED")

# Terminal alternatives to COMPLETED.
#
# DECLARED NARROWING: the brick lists LATE_START among the terminal alternatives. It is recorded here as a start
# DISPOSITION, not a terminal state, because a stage that starts inside the acceptance window still absorbs and
# still completes. Making LATE_START terminal would throw away a stage the window policy accepts. The disposition
# is recorded on the STARTED event either way, so nothing is lost -- only the classification differs, and this
# note exists so the difference is not discovered later as a surprise.
TERMINAL = ("COMPLETED", "TOO_EARLY", "MISSED_WINDOW", "SOURCE_UNAVAILABLE", "REFUSED_INPUT", "FAILED",
            "RECONCILED_DUPLICATE")

# DECISIVE terminal states -- the ones that mean THIS STAGE REACHED AN OUTCOME.
#
# RECONCILED_DUPLICATE is deliberately NOT one of them, and the reason is a defect the R5 concurrency flight
# caught. RECONCILED_DUPLICATE means "some other invocation was also here"; it is a note about a RACE, not an
# outcome for the stage. While it counted as terminal, a LOSING racer could append its own duplicate marker
# before the winner reached its work, the winner would then read that marker, conclude the stage was already
# done, and abandon it -- and the stage was lost entirely. Three concurrent processes produced ZERO absorptions.
#
# R4's version of this test passed, but it passed on TIMING: the winner happened to finish before the losers
# wrote their markers. It was never correct.
DECISIVE = ("COMPLETED", "TOO_EARLY", "MISSED_WINDOW", "SOURCE_UNAVAILABLE", "REFUSED_INPUT", "FAILED")
DISPOSITIONS = ("ON_TIME", "LATE_START", "TOO_EARLY", "MISSED_WINDOW")

# A rehearsal, recorded but NOT an outcome. It must never be decisive: a `--dry-run` at 08:15 that wrote a
# decisive state would make the real 08:15 stage look like a duplicate and the morning would lose the stage --
# the same shape as the racer-poisoning defect, from a different direction.
DRY_RUN = "DRY_RUN"

STATES = tuple(dict.fromkeys(PROGRESS + TERMINAL + (DRY_RUN,)))


class JournalRefused(RuntimeError):
    """A journal operation that cannot be performed honestly. Named, never silent."""


class ChainBroken(JournalRefused):
    pass


def canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def digest(obj) -> str:
    return hashlib.sha256(canonical(obj).encode()).hexdigest()


def _pid_alive(pid) -> bool:
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except Exception:                                           # noqa: BLE001
        return False


class Journal:
    """One trading date's durable record."""

    def __init__(self, trading_date: str, *, root=None):
        from apex.frontier import premarket_runtime as RT
        base = pathlib.Path(root) if root is not None else RT.root()
        self.trading_date = trading_date
        self.dir = base / "journal" / trading_date
        self.events_path = self.dir / "events.jsonl"
        self.blobs = self.dir / "blobs"
        self.claims = self.dir / "claims"
        self.lock_path = self.dir / "journal.lock"
        for d in (self.dir, self.blobs, self.claims):
            d.mkdir(parents=True, exist_ok=True)

    # -------------------------------------------------------------- blobs
    def put_blob(self, obj) -> str:
        """Content-addressed, write-once, idempotent. Writing the same content twice is a no-op, which is what
        makes a crashed stage resumable without losing or duplicating the original bytes."""
        body = canonical(obj)
        sha = hashlib.sha256(body.encode()).hexdigest()
        p = self.blobs / ("%s.json" % sha)
        if not p.exists():
            tmp = p.with_suffix(".tmp.%d" % os.getpid())
            tmp.write_text(body)
            os.replace(tmp, p)
        return sha

    def get_blob(self, sha: str):
        p = self.blobs / ("%s.json" % sha)
        if not p.exists():
            raise ChainBroken("BLOB_MISSING: %s" % sha)
        body = p.read_text()
        actual = hashlib.sha256(body.encode()).hexdigest()
        if actual != sha:
            raise ChainBroken("BLOB_DIGEST_MISMATCH: %s stored under %s -- content was altered after recording"
                              % (actual, sha))
        return json.loads(body)

    # -------------------------------------------------------------- the append-only log
    @contextlib.contextmanager
    def _exclusive(self):
        self.lock_path.touch(exist_ok=True)
        fh = open(self.lock_path, "r+")
        try:
            fcntl.flock(fh, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)
            fh.close()

    def events(self) -> list:
        if not self.events_path.exists():
            return []
        out = []
        for line in self.events_path.read_text().splitlines():
            line = line.strip()
            if line:
                out.append(json.loads(line))
        return out

    def append(self, *, stage: str, state: str, now=None, **payload) -> dict:
        """Allocate a sequence number and append one chained event. Transactional: the read of the tail and the
        write of the new line happen under one exclusive lock, so two concurrent stage processes cannot be given
        the same sequence number or fork the chain."""
        if state not in STATES:
            raise JournalRefused("UNKNOWN_STATE: %r" % state)
        from apex.frontier import premarket_runtime as RT
        # ONE CLOCK. This used to be `time.time()` while the packet's instants came from the runtime clock, so a
        # run under a controlled clock produced a journal whose event times disagreed with the packet they were
        # describing -- the record and the thing recorded gave different answers to "when". In production the two
        # are the same reading; the point is that they are now the same READING, not merely usually equal.
        at = float(now if now is not None else RT.now_utc().timestamp())
        with self._exclusive():
            existing = self.events()
            prev = existing[-1]["digest"] if existing else None
            ev = {"schema": SCHEMA, "seq": len(existing), "trading_date": self.trading_date,
                  "stage": stage, "state": state, "at": at, "prev": prev,
                  "pid": os.getpid(), "host": socket.gethostname(),
                  "substitutions": RT.substitutions(), "payload": payload}
            ev["digest"] = digest(ev)
            with open(self.events_path, "a") as fh:
                fh.write(json.dumps(ev, default=str) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
        return ev

    # -------------------------------------------------------------- verification
    def verify(self, *, check_blobs=True) -> dict:
        """Re-derive the whole chain. Every event's digest is recomputed from its own content and every link is
        checked against its predecessor; every blob referenced by a `*_blob` payload field is re-hashed."""
        evs = self.events()
        prev = None
        for i, ev in enumerate(evs):
            body = {k: v for k, v in ev.items() if k != "digest"}
            recomputed = digest(body)
            if recomputed != ev.get("digest"):
                raise ChainBroken("EVENT_DIGEST_MISMATCH at seq %d: recorded %s, recomputed %s -- the event was "
                                  "altered after it was written" % (i, ev.get("digest"), recomputed))
            if ev.get("seq") != i:
                raise ChainBroken("EVENT_SEQ_MISMATCH at position %d: event claims seq %r" % (i, ev.get("seq")))
            if ev.get("prev") != prev:
                raise ChainBroken("CHAIN_LINK_BROKEN at seq %d: prev=%r but predecessor digest is %r"
                                  % (i, ev.get("prev"), prev))
            prev = ev["digest"]
        checked = 0
        if check_blobs:
            for ev in evs:
                for k, v in (ev.get("payload") or {}).items():
                    if k.endswith("_blob") and isinstance(v, str):
                        self.get_blob(v)          # re-hashes; raises on mismatch
                        checked += 1
                    elif k.endswith("_blobs") and isinstance(v, list):
                        for sha in v:
                            if isinstance(sha, str):
                                self.get_blob(sha)
                                checked += 1
        return {"events": len(evs), "blobs_checked": checked, "head": prev, "verdict": "CHAIN_INTACT"}

    # -------------------------------------------------------------- stage views
    def stage_events(self, stage: str) -> list:
        return [e for e in self.events() if e["stage"] == stage]

    def stage_state(self, stage: str) -> str:
        """The most recent state recorded for this stage. Use `stage_outcome` to ask whether it is DONE."""
        evs = self.stage_events(stage)
        return evs[-1]["state"] if evs else "PENDING"

    def stage_outcome(self, stage: str) -> str:
        """The FIRST decisive terminal state this stage ever reached, or PENDING.

        First, not last, and decisive, not merely terminal. Reading the LAST state would let a duplicate marker
        appended after a COMPLETED make a finished stage look unfinished; counting RECONCILED_DUPLICATE as an
        outcome lets a losing racer make an unfinished stage look finished. Both were live: the second one lost
        a whole stage under concurrency."""
        for e in self.stage_events(stage):
            if e["state"] in DECISIVE:
                return e["state"]
        return "PENDING"

    def last_event(self, stage: str, state: str):
        for e in reversed(self.stage_events(stage)):
            if e["state"] == state:
                return e
        return None

    def resume_point(self, stage: str) -> dict:
        """The furthest progress state this stage reached, with its payload. This is what makes a crash between
        two states recoverable: the resumed invocation reuses the ORIGINAL captured bytes instead of refetching."""
        reached, payload = "PENDING", {}
        for e in self.stage_events(stage):
            if e["state"] in PROGRESS and PROGRESS.index(e["state"]) >= PROGRESS.index(reached):
                reached, payload = e["state"], e.get("payload") or {}
        return {"state": reached, "payload": payload}

    def sealed_event(self):
        for e in reversed(self.events()):
            if e["stage"] == "seal" and e["state"] == "COMPLETED":
                return e
        return None

    # -------------------------------------------------------------- exactly-once claims
    def claim(self, stage: str, *, holder: str) -> dict:
        """The exactly-once gate for absorption. An O_EXCL create, which is atomic in a way that the advisory
        check-then-write of RunLock and RunRecord is not -- those can both be passed by two processes racing.

        THREE OUTCOMES, because two are not enough:
          GRANTED   nobody held it;
          HELD      somebody holds it and their process is ALIVE -> a genuine concurrent invocation, refused;
          TAKEOVER  somebody holds it, their process is GONE, and this stage has no terminal state -> the holder
                    crashed mid-stage and this is the recovery. It is RECORDED with the dead holder's identity,
                    never taken silently. An unreadable claim is treated as HELD, because a claim being written
                    right now looks exactly like one that was abandoned."""
        p = self.claims / ("%s.claim" % stage)
        body = {"stage": stage, "holder": holder, "pid": os.getpid(), "at": time.time()}
        try:
            fd = os.open(str(p), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            held = self.claim_holder(stage)
            pid = (held or {}).get("pid")
            if not pid or _pid_alive(pid):
                return {"status": "HELD", "holder": held}
            if self.stage_outcome(stage) in DECISIVE:
                return {"status": "HELD", "holder": held}
            tmp = p.with_suffix(".claim.tmp.%d" % os.getpid())
            tmp.write_text(json.dumps({**body, "took_over_from": held}))
            os.replace(tmp, p)
            return {"status": "TAKEOVER", "holder": held}
        with os.fdopen(fd, "w") as fh:
            fh.write(json.dumps(body))
        return {"status": "GRANTED", "holder": None}

    def claim_holder(self, stage: str):
        p = self.claims / ("%s.claim" % stage)
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text())
        except json.JSONDecodeError:
            return {"holder": "UNREADABLE"}

    # -------------------------------------------------------------- reconstruction
    def completed_absorptions(self) -> list:
        """Every stage that reached COMPLETED with a packet, oldest first, with its packet blob digest."""
        out = []
        for e in self.events():
            if e["state"] == "COMPLETED" and (e.get("payload") or {}).get("packet_blob"):
                out.append({"stage": e["stage"], "seq": e["seq"], "at": e["at"],
                            "packet_blob": e["payload"]["packet_blob"],
                            "capture_blobs": e["payload"].get("capture_blobs", []),
                            "normalized_blob": e["payload"].get("normalized_blob")})
        return out

    def reconstruct(self) -> dict:
        """Rebuild the state a finalizer needs, from persisted evidence only. Never refetches, never substitutes
        current data, never trusts a caller-supplied 'stage complete' flag -- it reads the chain and re-hashes."""
        self.verify()
        done = [d for d in self.completed_absorptions() if d["stage"] != "seal"]
        if not done:
            return {"status": "NO_COMPLETED_ABSORPTION", "packet": None, "provenance": [], "missing": None}
        newest = done[-1]
        packet = self.get_blob(newest["packet_blob"])
        return {"status": "RECONSTRUCTED", "packet": packet, "from_stage": newest["stage"],
                "packet_blob": newest["packet_blob"], "provenance": done}


def open_journal(trading_date: str, *, root=None) -> Journal:
    return Journal(trading_date, root=root)
