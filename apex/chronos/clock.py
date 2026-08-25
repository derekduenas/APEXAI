"""THE CAUSAL CLOCK — what was knowable at T, and nothing else.

The clock is the whole machine. Every other CHRONOS defense assumes
that when the clock says 2019-01-03 09:55, no field born later can be
consumed -- not by the genome, not by discovery, not by a world model,
not by an evaluator reaching for a convenient exit price.

TWO DISTINCT REFUSALS, never conflated:

  NOT_YET_KNOWABLE       known_from > T. Ordinary, expected, silent-ish:
                         the field simply is not served.
  POISON_CONSUMED        a field REGISTERED AS PROHIBITED FUTURE was
                         consumed. This is never ordinary. It means the
                         causal firewall has a hole, and the entire run
                         is invalidated -- HARD FAIL, incident recorded,
                         no partial credit.

THE POISON PILL. We deliberately insert fields that contain future
information (e.g. future_return_30m) and register them as prohibited.
Their only job is to be reached for. A replay that completes without
ever tripping on poison has demonstrated -- continuously, not once at
review time -- that the firewall holds. A firewall tested only by code
inspection is a firewall tested by optimism.

decision_power: NONE_RESEARCH.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

NOT_ESTIMABLE = "NOT_ESTIMABLE"

POISON_PREFIX = "PROHIBITED_FUTURE"


class ChronosViolation(RuntimeError):
    pass


class PoisonConsumed(ChronosViolation):
    """The causal firewall has a hole. The run is dead."""


def _parse(ts: str) -> datetime:
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError as e:
        raise ChronosViolation(
            f"unparseable timestamp {ts!r}: a clock cannot reason "
            f"about a time it cannot read") from e


@dataclass
class CausalClock:
    """One replay's notion of NOW. Monotonic, explicit, logged."""
    start: str
    now_utc: datetime = field(init=False)
    advances: list = field(default_factory=list)

    def __post_init__(self):
        self.now_utc = _parse(self.start)

    def advance(self, to: str, *, why: str) -> dict:
        t = _parse(to)
        if t <= self.now_utc:
            raise ChronosViolation(
                f"clock may only move forward: {to} <= "
                f"{self.now_utc.isoformat()}. Rewinding mid-replay is "
                f"how a later fact leaks into an earlier moment")
        rec = {"from": self.now_utc.isoformat(), "to": t.isoformat(),
               "why": why}
        self.advances.append(rec)
        self.now_utc = t
        return rec


@dataclass
class KnowledgeHorizon:
    """The only door data walks through into a replay.

    Fields are registered with a known_from timestamp; poison fields
    are registered separately with the reason they are prohibited.
    Reads that would violate causality are refused; reads of poison
    kill the run."""
    clock: CausalClock
    _fields: dict = field(default_factory=dict)
    _poison: dict = field(default_factory=dict)
    refusals: list = field(default_factory=list)
    served: int = 0

    def register(self, name: str, value, *, known_from: str,
                 source: str) -> None:
        if name in self._poison:
            raise ChronosViolation(
                f"{name!r} is already registered as poison; a field "
                f"cannot be both servable and prohibited")
        self._fields[name] = {"value": value,
                              "known_from": _parse(known_from),
                              "source": source}

    def register_poison(self, name: str, value, *, why: str) -> None:
        """Deliberately plant future information, labelled prohibited.

        The value is stored so the trap is real -- a poison field that
        raises on registration would never test the consumer."""
        self._poison[name] = {"value": value,
                              "why": f"{POISON_PREFIX}: {why}"}

    def get(self, name: str, *, consumer: str):
        """The one read path. Everything downstream calls this."""
        if name in self._poison:
            raise PoisonConsumed(
                f"HARD FAIL: {consumer!r} consumed poison field "
                f"{name!r} ({self._poison[name]['why']}). The causal "
                f"firewall has a hole; every artifact of this run is "
                f"invalid and no partial result survives")
        f = self._fields.get(name)
        if f is None:
            raise ChronosViolation(
                f"{name!r} is not registered; a replay may not invent "
                f"data it was never given")
        if f["known_from"] > self.clock.now_utc:
            self.refusals.append(
                {"field": name, "consumer": consumer,
                 "known_from": f["known_from"].isoformat(),
                 "now": self.clock.now_utc.isoformat(),
                 "verdict": "NOT_YET_KNOWABLE"})
            return NOT_ESTIMABLE
        self.served += 1
        return f["value"]

    def audit(self) -> dict:
        return {"kind": "knowledge_horizon_audit",
                "now": self.clock.now_utc.isoformat(),
                "fields_registered": len(self._fields),
                "poison_planted": len(self._poison),
                "reads_served": self.served,
                "causal_refusals": len(self.refusals),
                "law": "a replay that never trips on planted poison "
                       "has demonstrated its firewall continuously; "
                       "one with no poison planted has demonstrated "
                       "nothing",
                "firewall_tested": len(self._poison) > 0,
                "decision_power": "NONE_RESEARCH"}


def assert_causal(records: list, *, decision_time: str,
                  known_from_key: str = "known_from") -> list:
    """Filter a record list to what was knowable, and refuse records
    that carry no known_from at all -- an unstamped record is not
    'probably fine', it is unusable."""
    t = _parse(decision_time)
    out = []
    for r in records:
        kf = r.get(known_from_key)
        if kf is None:
            raise ChronosViolation(
                "record without known_from: unstamped data cannot "
                "enter a causal replay")
        if _parse(kf) <= t:
            out.append(r)
    return out
