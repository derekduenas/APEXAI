"""PATTERN INPUT QUALITY -- data quality is part of the pattern.

WHY THIS EXISTS, measured not theorised. On 2026-08-19 APEX recorded
`gap_duration_ms` on every single bar it built, lost 45.1% of the session
tape (78% in the final hour), and **no organ consumed that fact**. An
11%-loss bar and a 78%-loss bar both reached the intelligence layer
labelled exactly the same way: `LIMITED`. A grep for consumers of
`gap_duration_ms` in the decision path returned nothing.

So the Observatory's first law is that quality travels WITH the evidence,
and it travels PER FEATURE, because the damage is not uniform:

    price direction   survives heavy subsampling  -> often VALID
    OHLC              extremes still sampled      -> often VALID
    VWAP              volume-weighted             -> DEGRADED first
    volume            is the thing being lost     -> INVALID first
    RVOL              corrupt numerator + no base -> INVALID

THE ANTI-CORROBORATION LAW. Three DEGRADED inputs agreeing is not
stronger evidence than one VALID input. A pattern may never become more
confident because more low-quality inputs concur -- that is how a system
talks itself into a position using the noise in its own sensor. The
combining rules below are deliberately pessimistic: the combined verdict
can never exceed the weakest REQUIRED input.

decision_power: NONE_PATTERN_OBSERVATORY.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from apex.pattern_observatory import OBSERVATORY_POWER

# ordered worst -> best; index is the comparison key
VALID = "VALID"
LIMITED = "LIMITED"
DEGRADED = "DEGRADED"
INVALID = "INVALID"
UNKNOWN = "UNKNOWN"

# UNKNOWN is deliberately ranked BELOW INVALID for combination purposes:
# "we do not know whether this input is sound" is a weaker epistemic
# position than "we know it is broken", because a known break can be
# reasoned about and an unknown one cannot.
_RANK = {UNKNOWN: 0, INVALID: 1, DEGRADED: 2, LIMITED: 3, VALID: 4}
STATUSES = tuple(sorted(_RANK, key=lambda s: _RANK[s]))

# Feature families the Observatory reasons about separately. These are
# named after what DEGRADES DIFFERENTLY, not after modules.
FEATURES = ("price_direction", "ohlc", "vwap", "volume", "rvol",
            "opening_range", "breadth", "sector_leadership",
            "options_surface", "positioning", "propagation", "event_time")


class PatternQualityError(RuntimeError):
    pass


@dataclass(frozen=True)
class PatternInputQuality:
    """The quality of ONE input family from ONE source at ONE moment."""

    source: str
    event_time: str | None
    known_from: str | None
    freshness_s: float | None
    coverage_fraction: float | None
    gap_fraction: float | None
    missing_observations: int | None
    staleness: str
    integrity: str
    quality: str
    feature_sufficiency: dict = field(default_factory=dict)
    notes: tuple = ()

    def __post_init__(self):
        if self.quality not in _RANK:
            raise PatternQualityError(f"bad quality {self.quality!r}")
        for feat, st in self.feature_sufficiency.items():
            if feat not in FEATURES:
                raise PatternQualityError(f"unknown feature {feat!r}")
            if st not in _RANK:
                raise PatternQualityError(f"bad sufficiency {st!r} for {feat}")

    def sufficient_for(self, feature: str) -> str:
        """A feature never inherits a quality better than the overall
        input quality -- a broken source cannot host a healthy feature."""
        st = self.feature_sufficiency.get(feature, UNKNOWN)
        return st if _RANK[st] <= _RANK[self.quality] else self.quality

    def as_dict(self) -> dict:
        return {"kind": "pattern_input_quality", "source": self.source,
                "event_time": self.event_time, "known_from": self.known_from,
                "freshness_s": self.freshness_s,
                "coverage_fraction": self.coverage_fraction,
                "gap_fraction": self.gap_fraction,
                "missing_observations": self.missing_observations,
                "staleness": self.staleness, "integrity": self.integrity,
                "quality": self.quality,
                "feature_sufficiency": dict(self.feature_sufficiency),
                "notes": list(self.notes),
                "decision_power": OBSERVATORY_POWER}


# --------------------------------------------------------------------
# The thresholds below are DECLARED, not fitted. They were written from
# the 2026-08-19 damage profile before any pattern was observed, and they
# describe how much of a minute's tape must survive for a feature family
# to remain trustworthy. They are not tuned against outcomes and must not
# be.
# --------------------------------------------------------------------
GAP_LIMITED = 0.05          # >5% of the minute missing
GAP_DEGRADED = 0.25         # >25%
GAP_INVALID = 0.50          # >50% -- half the tape gone
STALE_FRESH_S = 90.0
STALE_LIMITED_S = 300.0
STALE_DEGRADED_S = 900.0


def _from_gap(gap_fraction: float | None) -> str:
    if gap_fraction is None:
        return UNKNOWN
    if gap_fraction >= GAP_INVALID:
        return INVALID
    if gap_fraction >= GAP_DEGRADED:
        return DEGRADED
    if gap_fraction >= GAP_LIMITED:
        return LIMITED
    return VALID


def _staleness_label(freshness_s: float | None) -> str:
    if freshness_s is None:
        return "UNKNOWN"
    if freshness_s < 0:
        # A source stamped in the future. Measured live on 2026-08-19:
        # 89.4% of option quotes carried a NEGATIVE age, one at -1081s,
        # and the quality model treated them as maximally fresh. Never
        # again: a negative age is a clock integrity violation, not
        # freshness.
        return "CLOCK_INTEGRITY_VIOLATION"
    if freshness_s <= STALE_FRESH_S:
        return "FRESH"
    if freshness_s <= STALE_LIMITED_S:
        return "AGING"
    if freshness_s <= STALE_DEGRADED_S:
        return "STALE"
    return "VERY_STALE"


def _from_staleness(label: str) -> str:
    return {"FRESH": VALID, "AGING": LIMITED, "STALE": DEGRADED,
            "VERY_STALE": INVALID,
            "CLOCK_INTEGRITY_VIOLATION": INVALID,
            "UNKNOWN": UNKNOWN}[label]


def assess_bar_input(*, source: str, event_time, known_from, now,
                     gap_fraction: float | None,
                     coverage_fraction: float | None = None,
                     missing_observations: int | None = None,
                     bars_observed: int | None = None) -> PatternInputQuality:
    """Quality of a canonical 1-minute bar series.

    The per-feature split is the point. On the 2026-08-19 tape the same
    series was simultaneously usable for direction and useless for
    volume, and collapsing that into one label is what let a 78%-lossy
    bar look identical to a clean one.
    """
    import pandas as pd

    fresh = None
    if event_time is not None and now is not None:
        fresh = (pd.Timestamp(now) - pd.Timestamp(event_time)).total_seconds()
    stale_label = _staleness_label(fresh)

    gap_q = _from_gap(gap_fraction)
    stale_q = _from_staleness(stale_label)
    overall = min((gap_q, stale_q), key=lambda s: _RANK[s])

    integrity = ("CLOCK_INTEGRITY_VIOLATION"
                 if stale_label == "CLOCK_INTEGRITY_VIOLATION" else "OK")

    g = gap_fraction
    if g is None:
        suff = {f: UNKNOWN for f in ("price_direction", "ohlc", "vwap",
                                     "volume", "rvol", "opening_range")}
    else:
        # DIRECTION survives subsampling: the sign of a move is robust to
        # losing ticks in the middle of it.
        direction = VALID if g < GAP_DEGRADED else (
            LIMITED if g < GAP_INVALID else DEGRADED)
        # OHLC degrades one step slower than volume: extremes are still
        # sampled, but the recorded high/low understate the true range.
        ohlc = VALID if g < GAP_LIMITED else (
            LIMITED if g < GAP_DEGRADED else (
                DEGRADED if g < GAP_INVALID else INVALID))
        # VOLUME is precisely the quantity being lost -- it is understated
        # by roughly the gap fraction, so it fails first and hardest.
        volume = VALID if g < GAP_LIMITED else (
            DEGRADED if g < GAP_DEGRADED else INVALID)
        # VWAP is volume-weighted, so it inherits volume's damage.
        vwap = min((volume, ohlc), key=lambda s: _RANK[s])
        # RVOL needs a corrupt-free numerator AND a historical baseline;
        # it can never be better than volume.
        rvol = volume
        opening_range = ohlc
        suff = {"price_direction": direction, "ohlc": ohlc, "vwap": vwap,
                "volume": volume, "rvol": rvol, "opening_range": opening_range}

    notes = []
    if integrity != "OK":
        notes.append(f"event_time is {abs(fresh):.1f}s AHEAD of the clock")
    if bars_observed is not None and bars_observed < 6:
        notes.append(f"only {bars_observed} bars observed")
        overall = min((overall, LIMITED), key=lambda s: _RANK[s])

    return PatternInputQuality(
        source=source, event_time=str(event_time) if event_time else None,
        known_from=str(known_from) if known_from else None,
        freshness_s=(round(fresh, 3) if fresh is not None else None),
        coverage_fraction=coverage_fraction, gap_fraction=gap_fraction,
        missing_observations=missing_observations, staleness=stale_label,
        integrity=integrity, quality=overall, feature_sufficiency=suff,
        notes=tuple(notes))


def assess_generic_input(*, source: str, event_time, known_from, now,
                         features: tuple, available: bool,
                         unavailable_reason: str | None = None
                         ) -> PatternInputQuality:
    """Quality for a non-bar source (options surface, positioning, an
    event feed). An UNAVAILABLE source reports UNKNOWN, never VALID."""
    import pandas as pd

    if not available:
        return PatternInputQuality(
            source=source, event_time=None, known_from=None, freshness_s=None,
            coverage_fraction=0.0, gap_fraction=None, missing_observations=None,
            staleness="UNKNOWN", integrity="NOT_ACQUIRED", quality=UNKNOWN,
            feature_sufficiency={f: UNKNOWN for f in features},
            notes=(unavailable_reason or "source not acquired",))

    fresh = None
    if event_time is not None and now is not None:
        fresh = (pd.Timestamp(now) - pd.Timestamp(event_time)).total_seconds()
    label = _staleness_label(fresh)
    q = _from_staleness(label)
    return PatternInputQuality(
        source=source, event_time=str(event_time) if event_time else None,
        known_from=str(known_from) if known_from else None,
        freshness_s=(round(fresh, 3) if fresh is not None else None),
        coverage_fraction=1.0, gap_fraction=None, missing_observations=None,
        staleness=label,
        integrity=("CLOCK_INTEGRITY_VIOLATION"
                   if label == "CLOCK_INTEGRITY_VIOLATION" else "OK"),
        quality=q, feature_sufficiency={f: q for f in features})


# --------------------------------------------------------------- combine
PATTERN_NOT_ESTIMABLE = "PATTERN_NOT_ESTIMABLE"


def combine(qualities: list, *, required_features: tuple) -> dict:
    """Combine input qualities for a pattern that REQUIRES the named
    features.

    THE ANTI-CORROBORATION LAW, in code: the result is the MINIMUM over
    required features, never a mean and never a count. Agreement among
    weak inputs cannot manufacture strength. If any required feature is
    INVALID or UNKNOWN across every source, the pattern is not estimable
    at all -- it does not merely get a lower score.
    """
    if not required_features:
        raise PatternQualityError("a pattern must declare required features")

    per_feature = {}
    for feat in required_features:
        # best available sufficiency for this feature across sources
        best = UNKNOWN
        for q in qualities:
            st = q.sufficient_for(feat)
            if _RANK[st] > _RANK[best]:
                best = st
        per_feature[feat] = best

    worst = min(per_feature.values(), key=lambda s: _RANK[s]) if per_feature \
        else UNKNOWN
    blocking = [f for f, s in per_feature.items()
                if s in (INVALID, UNKNOWN)]
    estimable = not blocking
    return {"kind": "pattern_quality_verdict",
            "per_feature": per_feature,
            "combined_quality": worst,
            "estimable": estimable,
            "status": (None if estimable else PATTERN_NOT_ESTIMABLE),
            "blocking_features": blocking,
            "n_sources": len(qualities),
            "law": "combined quality is the MINIMUM over required features; "
                   "multiple low-quality agreeing inputs never raise it",
            "decision_power": OBSERVATORY_POWER}
