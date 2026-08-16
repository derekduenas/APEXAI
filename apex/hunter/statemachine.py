"""The trade state machine: every transition ruled, chained, and replayable.

    WATCH -> ARMED -> TRIGGERED -> ENTERED -> MANAGING -> CLOSED
                 (CANCELLED reachable before ENTERED)

Cardinal rule, enforced structurally: A STOP NEVER MOVES AWAY FROM THE
POSITION. tighten_stop() refuses any widening, whatever the narrative. The
decision ledger is hash-chained; a stop change without its (old, new, rule,
timestamp) tuple cannot exist.
"""

from __future__ import annotations

import hashlib
import json
from enum import Enum
from pathlib import Path

from apex.hunter.contracts import TradeThesis


class TradeState(Enum):
    WATCH = "WATCH"
    ARMED = "ARMED"
    TRIGGERED = "TRIGGERED"
    ENTERED = "ENTERED"
    MANAGING = "MANAGING"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


_LEGAL = {
    TradeState.WATCH: {TradeState.ARMED, TradeState.CANCELLED},
    TradeState.ARMED: {TradeState.TRIGGERED, TradeState.CANCELLED},
    TradeState.TRIGGERED: {TradeState.ENTERED, TradeState.CANCELLED},
    TradeState.ENTERED: {TradeState.MANAGING, TradeState.CLOSED},
    TradeState.MANAGING: {TradeState.MANAGING, TradeState.CLOSED},
    TradeState.CLOSED: set(),
    TradeState.CANCELLED: set(),
}

MANAGEMENT_ACTIONS = ("HOLD", "EXIT", "PARTIAL", "TIGHTEN", "TRAIL",
                      "ADD_IF_PERMITTED")


class TransitionError(ValueError):
    """An illegal or unruled transition was attempted."""


def _canon(o) -> str:
    return hashlib.sha256(json.dumps(o, sort_keys=True,
                                     separators=(",", ":"),
                                     default=str).encode()).hexdigest()


class TradeLifecycle:
    """One thesis, one lifecycle, one chained decision ledger."""

    def __init__(self, thesis: TradeThesis, ledger_path: Path):
        self.thesis = thesis
        self.state = TradeState.WATCH
        self.current_stop = float(thesis.stop)
        self.direction = 1 if thesis.targets and thesis.targets[0] > thesis.stop else -1
        self.ledger = Path(ledger_path)

    def _append(self, record: dict) -> dict:
        rows = ([json.loads(l) for l in self.ledger.read_text().strip().splitlines()]
                if self.ledger.exists() else [])
        prev = rows[-1]["entry_hash"] if rows else "GENESIS"
        body = {**record, "thesis_hash": self.thesis.thesis_hash,
                "prev_hash": prev}
        body["entry_hash"] = _canon(body)
        self.ledger.parent.mkdir(parents=True, exist_ok=True)
        with self.ledger.open("a") as fh:
            fh.write(json.dumps(body, sort_keys=True, default=str) + "\n")
        return body

    def transition(self, to: TradeState, rule: str, timestamp: str,
                   market_state: dict | None = None) -> None:
        """Every transition needs a NAMED rule. 'It felt right' is not one."""
        if not rule:
            raise TransitionError("a transition without a rule is a mood")
        if to not in _LEGAL[self.state]:
            raise TransitionError(
                f"{self.state.value} -> {to.value} is not a legal transition")
        self._append({"kind": "transition", "from": self.state.value,
                      "to": to.value, "rule": rule, "timestamp": timestamp,
                      "market_state": market_state or {}})
        self.state = to

    def tighten_stop(self, new_stop: float, rule: str, timestamp: str,
                     market_state: dict | None = None) -> None:
        """THE cardinal rule: the stop may only move TOWARD the position's
        favor. For a long (direction=+1) it may only RISE; for a short only
        FALL. Any widening is refused regardless of the narrative attached."""
        if self.state not in (TradeState.ENTERED, TradeState.MANAGING):
            raise TransitionError("no position, no stop to manage")
        widening = (new_stop < self.current_stop if self.direction > 0
                    else new_stop > self.current_stop)
        if widening:
            raise TransitionError(
                f"stop {self.current_stop} -> {new_stop} moves AWAY from the "
                f"position. A stop is never widened after adverse movement, "
                f"whatever the story. Refused.")
        self._append({"kind": "stop_change", "old_stop": self.current_stop,
                      "new_stop": new_stop, "rule": rule,
                      "timestamp": timestamp, "market_state": market_state or {}})
        self.current_stop = float(new_stop)

    def verify_ledger(self) -> int:
        """Recompute every entry_hash and check linkage. Returns the count
        of VALID records; `self.verification_damage` holds torn fragments.

        SAC1-06/07: two different things can be wrong with a ledger and
        they deserve different answers.

          TORN FRAGMENT   a crash mid-append left an unparseable line. The
                          physical world did this. It is DAMAGE: recorded,
                          counted, and stepped over -- it must not make the
                          valid records that follow disappear, and it must
                          not be silently swallowed either.
          HASH MISMATCH   a record's body no longer matches its own hash,
                          or linkage is broken between valid records.
                          Somebody did this. It is TAMPERING, and it still
                          raises.

        Previously an unparseable line raised JSONDecodeError from the list
        comprehension, so a torn tail made verification impossible rather
        than reporting the tear -- the forensic tool failed on exactly the
        condition it exists to describe.
        """
        self.verification_damage: list = []
        rows = []
        if self.ledger.exists():
            for i, line in enumerate(self.ledger.read_text().splitlines()):
                if not line.strip():
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    self.verification_damage.append(
                        {"row": i, "bytes": len(line),
                         "classification": "TORN_FRAGMENT"})
        prev = "GENESIS"
        for i, r in enumerate(rows):
            body = {k: v for k, v in r.items() if k != "entry_hash"}
            if _canon(body) != r["entry_hash"]:
                raise TransitionError(
                    f"decision ledger TAMPERED at valid-row {i}: the record "
                    f"body does not match its own entry_hash")
            if r["prev_hash"] != prev:
                # a record written after a tear legitimately links to the
                # last VALID entry; that is recovery, not tampering, and it
                # says so on the record itself.
                if not r.get("recovered_from_torn_tail"):
                    raise TransitionError(
                        f"decision ledger broken at valid-row {i}: linkage "
                        f"mismatch with no torn-tail recovery stamp")
            prev = r["entry_hash"]
        return len(rows)
