"""Risk-free rate curve — F "use actual risk-free curve input", never
a silently-assumed constant. Callers supply real (tenor_years, rate)
points; this module only interpolates between them. With no curve
supplied, rate_for_tenor() returns None (UNKNOWN) rather than
defaulting to 0% or any other invented number.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

from apex.option_analytics import OPTION_ANALYTICS_POWER


class RateCurveError(RuntimeError):
    pass


@dataclass(frozen=True)
class RiskFreeCurve:
    points: tuple            # tuple of (tenor_years: float, rate: float), sorted by tenor
    source: str               # e.g. "UST_PAR_YIELD_CURVE" -- never "ASSUMED"
    as_of: str
    decision_power: str = OPTION_ANALYTICS_POWER

    def __post_init__(self):
        if not self.points:
            raise RateCurveError("a RiskFreeCurve must carry at least one point")
        tenors = [p[0] for p in self.points]
        if tenors != sorted(tenors):
            raise RateCurveError("curve points must be sorted by tenor_years")
        if self.source.upper() == "ASSUMED":
            raise RateCurveError(
                "a rate curve may not be sourced as 'ASSUMED' -- that is "
                "exactly the silent-default this module refuses to allow")

    def as_record(self) -> dict:
        return asdict(self)


def rate_for_tenor(curve: RiskFreeCurve | None, tenor_years: float) -> float | None:
    """Linear interpolation within the curve's own range; returns None
    for a tenor outside the curve's coverage rather than extrapolating
    silently, and None outright when no curve was supplied."""
    if curve is None:
        return None
    points = curve.points
    if tenor_years < points[0][0] or tenor_years > points[-1][0]:
        return None
    for (t0, r0), (t1, r1) in zip(points, points[1:]):
        if t0 <= tenor_years <= t1:
            if t1 == t0:
                return r0
            w = (tenor_years - t0) / (t1 - t0)
            return r0 + w * (r1 - r0)
    return points[-1][1]
