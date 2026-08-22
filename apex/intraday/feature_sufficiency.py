"""FEATURE-SPECIFIC DATA SUFFICIENCY -- the official cognition gate.

THE LAW (Profit Predator v1, Phase 7). Quality is FEATURE-SPECIFIC. One
session (2026-08-20) demonstrated price VALID while volume/RVOL were
LIMITED while breadth degraded through the afternoon -- a single global
quality bit would have either blocked a healthy feature or waved a
broken one through. Each feature gets its own verdict, and the verdict
gates whether the feature MAY SPEAK to the decision path:

    INVALID        cannot speak
    NOT_ESTIMABLE  cannot speak
    DEGRADED       may speak ONLY if the consumer explicitly opted in
    LIMITED        speaks, carrying a visible penalty flag
    VALID          speaks normally

UNKNOWN IS NEVER CONVERTED TO ZERO: a feature that cannot be assessed
is NOT_ESTIMABLE and silent, never a fabricated neutral value.

decision_power: this module gates INPUTS; it decides nothing itself.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

VALID, LIMITED, DEGRADED, INVALID, NOT_ESTIMABLE = (
    "VALID", "LIMITED", "DEGRADED", "INVALID", "NOT_ESTIMABLE")
VERDICTS = (VALID, LIMITED, DEGRADED, INVALID, NOT_ESTIMABLE)

# Declared floors -- same un-fitted-constant family as the repo's
# rvol>=3.0. Coverage is measured against the feature's OWN required
# window, not the whole session.
COVERAGE_VALID = 0.97
COVERAGE_LIMITED = 0.90
COVERAGE_DEGRADED = 0.75
MAX_SINGLE_GAP_VALID_S = 120.0
FRESHNESS_MAX_S = 180.0


class SufficiencyError(RuntimeError):
    pass


@dataclass(frozen=True)
class FeatureSufficiencyState:
    feature: str
    subject: str
    verdict: str
    coverage_fraction: float | None
    observed_points: int
    required_points: int
    missing_points: int
    max_single_gap_s: float | None
    freshness_s: float | None
    source_available: bool
    reasoning: tuple
    known_from: str
    as_of: str

    def __post_init__(self):
        if self.verdict not in VERDICTS:
            raise SufficiencyError(f"bad verdict {self.verdict!r}")

    def as_record(self) -> dict:
        d = asdict(self)
        d["kind"] = "feature_sufficiency_state"
        d["reasoning"] = list(self.reasoning)
        return d

    def may_speak(self, *, consumer_accepts_degraded: bool = False) -> bool:
        """THE CHECKPOINT. INVALID / NOT_ESTIMABLE never speak;
        DEGRADED requires the consumer's explicit opt-in."""
        if self.verdict in (INVALID, NOT_ESTIMABLE):
            return False
        if self.verdict == DEGRADED:
            return consumer_accepts_degraded
        return True

    def penalized(self) -> bool:
        return self.verdict in (LIMITED, DEGRADED)


def assess_points(feature: str, subject: str, points: list, *,
                  required_points: int, expected_spacing_s: float,
                  now, known_from,
                  source_available: bool = True
                  ) -> FeatureSufficiencyState:
    """Assess a chronological [(timestamp, value)] feed against its own
    requirement. `required_points` is what the downstream computation
    needs (e.g. Curve's MIN_POINTS_FOR_CURVATURE); coverage is measured
    over the trailing `required_points * expected_spacing_s` span."""
    import pandas as pd

    now = pd.Timestamp(now)
    reasoning = []

    if not source_available:
        return FeatureSufficiencyState(
            feature=feature, subject=subject, verdict=NOT_ESTIMABLE,
            coverage_fraction=None, observed_points=0,
            required_points=required_points, missing_points=required_points,
            max_single_gap_s=None, freshness_s=None, source_available=False,
            reasoning=("source unavailable -- NOT_ESTIMABLE, never zero",),
            known_from=str(known_from), as_of=str(now))

    pts = sorted(((pd.Timestamp(t), v) for t, v in points),
                 key=lambda p: p[0])
    pts = [(t, v) for t, v in pts if t <= now]
    if not pts:
        return FeatureSufficiencyState(
            feature=feature, subject=subject, verdict=NOT_ESTIMABLE,
            coverage_fraction=0.0, observed_points=0,
            required_points=required_points, missing_points=required_points,
            max_single_gap_s=None, freshness_s=None, source_available=True,
            reasoning=("no observations at or before now",),
            known_from=str(known_from), as_of=str(now))

    freshness = (now - pts[-1][0]).total_seconds()
    window_span = required_points * expected_spacing_s
    win_start = now - pd.Timedelta(seconds=window_span)
    in_win = [(t, v) for t, v in pts if t >= win_start]
    coverage = min(1.0, len(in_win) / required_points)

    gaps = [(in_win[i][0] - in_win[i - 1][0]).total_seconds()
            for i in range(1, len(in_win))]
    max_gap = max(gaps) if gaps else None

    if len(in_win) < required_points:
        reasoning.append(f"{len(in_win)}/{required_points} points in the "
                         f"required window")
    if max_gap is not None and max_gap > MAX_SINGLE_GAP_VALID_S:
        reasoning.append(f"max single gap {max_gap:.0f}s")
    if freshness > FRESHNESS_MAX_S:
        reasoning.append(f"stale: newest observation {freshness:.0f}s old")

    if freshness > FRESHNESS_MAX_S * 3:
        verdict = INVALID
    elif coverage >= COVERAGE_VALID and (
            max_gap is None or max_gap <= MAX_SINGLE_GAP_VALID_S) and (
            freshness <= FRESHNESS_MAX_S):
        verdict = VALID
    elif coverage >= COVERAGE_LIMITED and freshness <= FRESHNESS_MAX_S:
        verdict = LIMITED
    elif coverage >= COVERAGE_DEGRADED:
        verdict = DEGRADED
    else:
        verdict = INVALID
    if not reasoning:
        reasoning.append("full coverage, fresh, no material gap")

    return FeatureSufficiencyState(
        feature=feature, subject=subject, verdict=verdict,
        coverage_fraction=round(coverage, 4), observed_points=len(in_win),
        required_points=required_points,
        missing_points=max(0, required_points - len(in_win)),
        max_single_gap_s=(round(max_gap, 1) if max_gap is not None else None),
        freshness_s=round(freshness, 1), source_available=True,
        reasoning=tuple(reasoning), known_from=str(known_from),
        as_of=str(now))
