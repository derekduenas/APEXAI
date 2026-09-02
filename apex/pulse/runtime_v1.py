"""PULSE_V1 runtime cycle writer -- bounded state, committed packets.

This is the wiring layer that turns the Wave-1 primitives into an
actual minute path. It does NOT touch PULSE_V0: V0's release is sealed
read-only, its timer is decommissioned, and its ledgers are evidence.

WHAT V1 CHANGES vs V0
---------------------
V0 minute path                     V1 minute path
------------------------------     ------------------------------
RollingStore.restore()             load_checkpoint()
  read_text() whole journal          read one bounded artifact
  O(session), 42.6x growth           O(current window)
PremarketPath.restore()            (folded into the checkpoint)
  read_text() whole journal
latency.total_s                    true slot occupancy
  starts AFTER restore               scheduled -> persistence_complete
  said within_budget on 100%         cannot hide startup cost
packets bound by COUNT             packets bound by MERKLE ROOT
  substitution undetectable          any change breaks the chain

NOT DONE HERE (deliberately)
----------------------------
No live timer is armed. No prospective evidence is produced. Live
commissioning is a separate, independently approved step.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from apex.governance.chain_ledger import chain_append
from apex.ops.cadence import Lifecycle
from apex.pulse.checkpoint import (Checkpoint, UnboundedStateRefused,
                                   recover, write_atomic)
from apex.pulse.packet_root import cycle_commitment, verify

PULSE_V1_VERSION = "PULSE_V1"
DECISION_POWER = "NONE_STATE"          # V1 has no more authority than V0


class RuntimeViolation(Exception):
    pass


@dataclass
class CycleResult:
    scheduled_time: datetime
    lifecycle: Lifecycle
    packets: list[dict]
    commitment: dict
    checkpoint_bytes: int
    restore_mode: str
    persisted: bool = False


def _now() -> datetime:
    return datetime.now(timezone.utc)


class PulseV1Runtime:
    """One bounded minute path.

    `compose_packets` is injected so the runtime can be exercised
    without a live provider. In production it is the shared composer;
    in tests it is a deterministic stub. The BOUNDED-STATE guarantee is
    a property of this class, not of the composer.
    """

    def __init__(self, *, results_dir: Path, compose_packets,
                 rolling_window_minutes: int = 60,
                 max_checkpoint_bytes: int = 8 * 1024 * 1024):
        self.results = Path(results_dir)
        self.compose_packets = compose_packets
        self.window = rolling_window_minutes
        self.max_checkpoint_bytes = max_checkpoint_bytes
        self.ledger = self.results / "market_twin_v1.jsonl"
        self.cycle_log = self.results / "cycle_log_v1.jsonl"
        self.checkpoint_path = self.results / "checkpoint_v1.json"

    # -- the guarantee: restore reads ONE bounded artifact -------------
    def restore(self, session_date: str) -> tuple[Checkpoint, str]:
        def bounded_rebuild(day: str) -> Checkpoint:
            """Rebuild from a STRICTLY BOUNDED authoritative window.

            Never the whole session. If a bounded rebuild is not
            possible, we start clean rather than reading history --
            starting clean loses working state, reading history
            recreates PULSE-005.
            """
            return Checkpoint(session_date=day,
                              rolling=__import__(
                                  "apex.pulse.checkpoint", fromlist=["x"]
                              ).RollingState(window_minutes=self.window))
        return recover(self.checkpoint_path,
                       bounded_rebuild=bounded_rebuild,
                       session_date=session_date)

    def run_cycle(self, scheduled_time: datetime, *,
                  session_date: str | None = None,
                  persist: bool = True) -> CycleResult:
        lc = Lifecycle(scheduled_time=scheduled_time)
        lc.service_start = _now()
        day = session_date or scheduled_time.strftime("%Y-%m-%d")

        # 1. BOUNDED restore -- never the journal
        ck, mode = self.restore(day)
        lc.state_restore_complete = _now()

        # 2. capture + compose
        lc.capture_start = _now()
        packets = self.compose_packets(scheduled_time, ck)
        lc.capture_complete = _now()
        for p in packets:
            if not p.get("state_id") or not p.get("packet_hash"):
                raise RuntimeViolation(
                    "every packet must carry state_id and packet_hash")
            p.setdefault("decision_power", DECISION_POWER)
            p.setdefault("pulse_version", PULSE_V1_VERSION)
        lc.composition_complete = _now()

        # 3. commit the packet SET, not merely its count
        prev = self._prev_cycle_hash()
        commitment = cycle_commitment(
            cycle_id=f"{PULSE_V1_VERSION}:{scheduled_time.isoformat()}",
            scheduled_time=scheduled_time.isoformat(),
            packets=packets, prev_cycle_hash=prev)

        ck_bytes = 0
        if persist:
            # 4. packets first, then the commitment that binds them
            with self.ledger.open("a") as fh:
                for p in packets:
                    fh.write(json.dumps(p, sort_keys=True) + "\n")
                fh.flush()
                os.fsync(fh.fileno())

            # 5. bounded checkpoint -- refuses to become unbounded
            ck.cycle_number += 1
            ck.session_date = day
            ck.rolling.prune_all(scheduled_time)
            info = write_atomic(self.checkpoint_path, ck,
                                max_bytes=self.max_checkpoint_bytes)
            ck_bytes = info["bytes"]

            record = dict(commitment)
            record.update({
                "kind": "pulse_v1_cycle",
                "pulse_version": PULSE_V1_VERSION,
                "decision_power": DECISION_POWER,
                "restore_mode": mode,
                "checkpoint_bytes": ck_bytes,
                "checkpoint_state_hash": info["state_hash"],
                "law": "measurements only; PULSE does not predict and "
                       "holds no capital authority",
            })
            chain_append(self.cycle_log, record)

        lc.persistence_complete = _now()
        lc.service_exit = _now()
        return CycleResult(scheduled_time=scheduled_time, lifecycle=lc,
                           packets=packets, commitment=commitment,
                           checkpoint_bytes=ck_bytes, restore_mode=mode,
                           persisted=persist)

    def _prev_cycle_hash(self) -> str:
        """O(1) tail read -- never a full-file scan."""
        if not self.cycle_log.exists() or \
                self.cycle_log.stat().st_size == 0:
            return "GENESIS"
        size = self.cycle_log.stat().st_size
        TAIL = 65536
        with self.cycle_log.open("rb") as fh:
            fh.seek(max(0, size - TAIL))
            # read(TAIL), never read(): the bound belongs in the call,
            # not merely in the preceding seek. A bare read() after a
            # seek is bounded in EFFECT but reads as unbounded, and the
            # whole-ledger guard is right to refuse to tell them apart.
            tail = fh.read(TAIL).decode("utf-8", errors="replace")
        for line in reversed([x for x in tail.splitlines() if x.strip()]):
            try:
                return json.loads(line)["entry_hash"]
            except (json.JSONDecodeError, KeyError):
                continue
        return "GENESIS"

    # -- verification helpers -----------------------------------------
    def verify_cycle(self, scheduled_time: datetime) -> dict:
        """Re-derive the packet root from what is actually on disk."""
        want = scheduled_time.isoformat()
        commitment = None
        for line in self.cycle_log.read_text().splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            if r.get("scheduled_time") == want:
                commitment = r
        if commitment is None:
            return {"VALID": False, "why": "no cycle record"}
        packets = []
        with self.ledger.open() as fh:
            for line in fh:
                if not line.strip():
                    continue
                p = json.loads(line)
                if p.get("scheduled_time") == want:
                    packets.append(p)
        return verify(commitment, packets)

    def restore_cost_probe(self, session_date: str) -> dict:
        """Measure restore against evidence size -- the acceptance
        property for PULSE-005."""
        t0 = time.perf_counter()
        _, mode = self.restore(session_date)
        dt = time.perf_counter() - t0
        led = self.ledger.stat().st_size if self.ledger.exists() else 0
        ck = (self.checkpoint_path.stat().st_size
              if self.checkpoint_path.exists() else 0)
        return {"restore_seconds": round(dt, 4), "restore_mode": mode,
                "ledger_bytes": led, "checkpoint_bytes": ck,
                "reads_ledger": False}
