"""Shared schemas for canonical cross-sectional state.

Every series/state this package emits carries the full provenance the
Phase-4 law requires: value, sufficient, quality, source, source_time,
known_from, formula_version. A dimension without adequate coverage is
NO_SUPPORT at the consumer -- never a fabricated neutral.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

from apex.market_state import MARKET_STATE_POWER

VALID, LIMITED, DEGRADED, INVALID, NOT_ESTIMABLE = (
    "VALID", "LIMITED", "DEGRADED", "INVALID", "NOT_ESTIMABLE")
QUALITIES = (VALID, LIMITED, DEGRADED, INVALID, NOT_ESTIMABLE)


class MarketStateError(RuntimeError):
    pass


@dataclass(frozen=True)
class CrossSectionalSeries:
    """A canonical scalar time series over one session, ready to feed a
    derivative stack. `points` are chronological (timestamp, value)
    pairs; every point's value was computed from bars whose
    event_time <= that point's timestamp (no forward information)."""
    name: str
    points: tuple                       # ((pd.Timestamp, float), ...)
    sufficient: bool
    quality: str
    members_observed: int
    members_expected: int
    source: str
    source_time: str | None             # newest bar time that entered
    known_from: str
    formula_version: str
    reasoning: tuple = ()
    decision_power: str = MARKET_STATE_POWER

    def __post_init__(self):
        if self.quality not in QUALITIES:
            raise MarketStateError(f"bad quality {self.quality!r}")

    def as_record(self) -> dict:
        d = asdict(self)
        d["kind"] = "cross_sectional_series"
        d["points"] = [(str(t), v) for t, v in self.points]
        d["reasoning"] = list(self.reasoning)
        return d
