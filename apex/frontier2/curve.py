"""MarketCurvatureState — F1: detect emerging market-state transitions
before price fully expresses them.

THE ARCHITECTURAL CHOICE THIS MODULE MAKES: it is a derivative stack,
not an indicator. Every dimension gets the SAME four honest numbers --

    LEVEL        the latest value
    VELOCITY     d(value)/dt, a linear-fit slope over the last
                 VELOCITY_WINDOW_POINTS bars (per hour) -- direction only
    ACCELERATION d(velocity)/dt, the slope of the velocity series itself
                 (legacy diagnostic; nothing derives state from it)
    CURVATURE    V2 (2026-08-20): the return-normalized second
                 difference z-score -- dimensionless, ~N(0,1) under the
                 iid null, judged against a longer trailing return
                 distribution. See the V2 MATH block below for the
                 formula, the V1 defect it replaced, and the
                 pre-registered constants.

-- computed identically for every dimension, so the high-level classifier
below is a deterministic LOOKUP over these ten already-computed numbers,
never a fitted weighted sum. A dimension APEX cannot honestly measure
tonight (breadth, correlation, cross_asset, event_reaction,
sector_leadership -- see FRONTIER_NEXTGEN_BUILD_MAP.md's "what current
data cannot support honestly") reports NO_SUPPORT and contributes
nothing to the verdict, rather than a fabricated number.

TRANSITION_LIKELIHOOD, TRANSITION_DIRECTION and EXPRESSION are kept as
three SEPARATE fields (the directive's explicit law): a valid output is
TRANSITION_RISK_HIGH / DIRECTION_UNKNOWN / NO_EXPRESSION. No probability
is ever emitted -- these are ordinal states until a prospective
calibration exists (F16's H_CURVE_* hypotheses, currently
NOT_YET_ESTIMABLE).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

from apex.frontier2 import FRONTIER2_POWER
from apex.frontier2.observation_integrity import ObservationIntegrityState

LEDGER = Path("results/frontier2/curve_ledger.jsonl")

DIMENSIONS = ("price", "breadth", "relative_strength", "sector_leadership",
             "volatility", "correlation", "liquidity", "flow",
             "cross_asset", "event_reaction")

DIRECTIONAL_DIMENSIONS = ("price", "relative_strength")

SUPPORTED, INSUFFICIENT_HISTORY, NO_SUPPORT = (
    "SUPPORTED", "INSUFFICIENT_HISTORY", "NO_SUPPORT")

HIGH_LEVEL_STATES = (
    "NO_INFLECTION", "EARLY_POSITIVE_CURVATURE", "POSITIVE_TRANSITION",
    "EARLY_NEGATIVE_CURVATURE", "NEGATIVE_TRANSITION",
    "VOLATILITY_EXPANSION", "VOLATILITY_COMPRESSION",
    "ROTATION_TRANSITION", "LIQUIDITY_TRANSITION", "CORRELATION_BREAK",
    "UNKNOWN")

LIKELIHOODS = ("NONE", "LOW", "MODERATE", "HIGH", "UNKNOWN")
DIRECTIONS = ("UP", "DOWN", "MIXED", "UNKNOWN")
EXPRESSIONS = ("NO_EXPRESSION", "EARLY_EXPRESSION", "CONFIRMED_EXPRESSION",
              "UNKNOWN")

# ---------------------------------------------------------------- V2 MATH
# THE V1 DEFECT (proven on 17,322 live states 2026-08-20 + direct
# reproduction). V1 was curvature = OLS_acceleration / std(raw LEVELS).
# Its units are hour^-2, NOT dimensionless: for a window spanning T
# hours, any bend comparable to the window's own level variation s gives
# acceleration ~ s/T^2, so curvature ~ 1/T^2 ~ 100+ for the live
# 6-minute window BY CONSTRUCTION. The magnitude was set by the window
# length, not the data -- which is why a 2-millionths-of-a-dollar wobble
# produced |curvature| > 4 and price fired "elevated" on 99.9% of a full
# session while being perfectly scale- and shift-invariant. The
# threshold 1.0 was being compared against a statistic whose natural
# floor was ~100.
#
# THE V2 STATISTIC (return-normalized second difference against a
# longer pre-specified trailing distribution -- directive Candidate C):
#
#     r_i = ln(y_i) - ln(y_{i-1})        per-bar log return  (log mode)
#           y_i - y_{i-1}                per-bar difference  (diff mode,
#                                        for signed level series such as
#                                        RS excess-return, where min<=0)
#     z   = (r_n - r_{n-1}) / (sigma_hat * sqrt(2))
#
# sigma_hat = sample std (ddof=1) of the TRAILING returns r_1..r_{n-1}
# -- the newest return is EXCLUDED. This is load-bearing: a first draft
# used a self-inclusive sigma over the 5 returns the old 6-bar feed
# provides, and the property tests immediately proved that a single-bar
# break then has a mathematical MAXIMUM |z| of sqrt(n/2) ~ 1.58 < 2.0:
# the break inflates its own denominator enough that elevation was
# STRUCTURALLY UNREACHABLE for exactly the events the statistic exists
# to catch -- the same class of defect being repaired. With the newest
# return excluded, a genuine break is judged against the trailing
# distribution it actually broke from (unbounded z, correct), while a
# single bad tick still cannot dominate FOR LONG: the spike's return
# joins the trailing sigma for the next SIGMA_MAX_RETURNS windows and
# suppresses them, then ages out entirely.
#
# sigma stability comes from LENGTH, not self-inclusion: up to
# SIGMA_MAX_RETURNS=30 trailing returns, at least MIN_SIGMA_RETURNS=8
# (a ddof=1 std over fewer than 8 samples has sampling error the
# threshold cannot survive). Both fixed a priori for estimator degrees
# of freedom -- neither was replayed against any session before being
# written here. sqrt(2) calibrates the null: under iid noise
# r_n - r_{n-1} has std sigma*sqrt(2), so z ~ N(0,1).
#
# UNITS: dimensionless (a z-score). Scale x10 and split-adjustment are
# exactly invariant (returns); shift +100000 is invariant to O((dp/p)^2)
# in log mode and exactly invariant in diff mode. Exact flat -> 0.0
# (neutral: numerator and sigma both exactly zero). A jump out of
# PERFECT flatness (sigma_hat == 0, numerator != 0) has no defined z
# and is REFUSED (None), never fabricated as infinity.
#
# ELEVATED_Z = 2.0 is the pre-registered two-sigma convention (same
# family as this repo's rvol >= 3.0): under the iid null it admits ~4.6%
# of pure noise, the textbook false-positive rate. It was NOT derived
# from, or checked against, any session's firing-rate distribution
# before being fixed here.
CURVE_FORMULA_VERSION = "v2_return_normalized_second_difference"
ELEVATED_Z = 2.0
SIGMA_MAX_RETURNS = 30
MIN_SIGMA_RETURNS = 8
MIN_POINTS_FOR_VELOCITY = 2
# 10 points -> 9 returns -> 8 trailing for sigma after excluding the
# newest. Below that: INSUFFICIENT_HISTORY, never a guess.
MIN_POINTS_FOR_CURVATURE = 10
# velocity keeps its original short-horizon semantics (direction sign
# over the most recent bars) regardless of how much history the caller
# supplies for sigma.
VELOCITY_WINDOW_POINTS = 6

# V1's constant, retained ONLY so ledger archaeology on pre-V2 records
# can reconstruct what "elevated" meant then. Nothing live reads it.
ELEVATED_CURVATURE_V1_RETIRED = 1.0


def _formula_hash() -> str:
    """Hash of the semantic formula definition, stamped on every record
    so V1 and V2 states can never be silently mixed in analysis."""
    import hashlib
    payload = (f"{CURVE_FORMULA_VERSION}|z=(r_n-r_(n-1))/(std_ddof1*sqrt2)"
               f"|elevated=|z|>={ELEVATED_Z}"
               f"|min_points={MIN_POINTS_FOR_CURVATURE}")
    return hashlib.sha256(payload.encode()).hexdigest()[:12]

BREADTH_DIMENSIONS = ("breadth", "sector_leadership", "correlation")

# DEPENDENCY GROUPS (Phase 5, 2026-08-20). price and relative_strength
# are two transformations of the same underlying price process;
# sector_leadership/breadth/correlation are all cross-sectional reads
# of the same 11-ETF panel. "4 dimensions elevated" is NOT four
# independent proofs when three of them share a mechanism. Declared
# here, never fitted.
DEPENDENCY_GROUPS = {
    "price": "PRICE_DERIVED", "relative_strength": "PRICE_DERIVED",
    "sector_leadership": "CROSS_SECTIONAL", "breadth": "CROSS_SECTIONAL",
    "correlation": "CROSS_SECTIONAL",
    "volatility": "VOLATILITY",
    "liquidity": "LIQUIDITY_FLOW", "flow": "LIQUIDITY_FLOW",
    "cross_asset": "EXTERNAL", "event_reaction": "EXTERNAL",
}


class CurveViolation(RuntimeError):
    pass


@dataclass(frozen=True)
class DimensionCurvature:
    dimension: str
    value: float | None
    velocity: float | None
    acceleration: float | None
    curvature: float | None                # V2: dimensionless z-score
    status: str
    support: int
    coverage: str
    freshness_s: float | None
    known_from: str
    as_of: str
    formula_version: str = CURVE_FORMULA_VERSION
    formula_hash: str = field(default_factory=_formula_hash)
    curvature_units: str = "Z_SCORE_DIMENSIONLESS"
    return_mode: str | None = None         # "log" | "diff" | None

    def __post_init__(self):
        if self.dimension not in DIMENSIONS:
            raise CurveViolation(f"unknown dimension {self.dimension!r}")
        if self.status not in (SUPPORTED, INSUFFICIENT_HISTORY, NO_SUPPORT):
            raise CurveViolation(f"unknown status {self.status!r}")

    def as_record(self) -> dict:
        return asdict(self)

    def elevated(self) -> bool:
        return (self.status == SUPPORTED and self.curvature is not None
               and abs(self.curvature) >= ELEVATED_Z)


@dataclass(frozen=True)
class MarketCurvatureState:
    subject: str
    as_of: str
    known_from: str
    dimensions: dict                     # name -> DimensionCurvature.as_record()
    high_level_state: str
    transition_likelihood: str
    transition_direction: str
    expression: str
    curve_breadth_status: str            # FULL_COVERAGE | LIMITED_COVERAGE
    observation_quality: str
    reasoning: tuple = ()                # human-readable trace of the lookup
    decision_power: str = FRONTIER2_POWER
    formula_version: str = CURVE_FORMULA_VERSION
    formula_hash: str = field(default_factory=_formula_hash)
    supported_dimension_count: int = 0
    elevated_dimension_count: int = 0
    independent_elevated_groups: tuple = ()

    def __post_init__(self):
        if self.high_level_state not in HIGH_LEVEL_STATES:
            raise CurveViolation(f"unknown state {self.high_level_state!r}")
        if self.transition_likelihood not in LIKELIHOODS:
            raise CurveViolation("bad transition_likelihood")
        if self.transition_direction not in DIRECTIONS:
            raise CurveViolation("bad transition_direction")
        if self.expression not in EXPRESSIONS:
            raise CurveViolation("bad expression")

    def as_record(self) -> dict:
        return {"kind": "market_curvature_state", **asdict(self)}


def _linear_slope(xs: list, ys: list) -> float | None:
    """Least-squares slope, ys per unit of xs. None if degenerate
    (all xs identical, or fewer than 2 points)."""
    import numpy as np
    if len(xs) < 2 or len(set(xs)) < 2:
        return None
    coeffs = np.polyfit(np.array(xs, dtype=float), np.array(ys, dtype=float), 1)
    return float(coeffs[0])


def compute_dimension(dimension: str, points: list, *, now, known_from,
                      reason_unsupported: str | None = None
                      ) -> DimensionCurvature:
    """`points`: chronological [(pd.Timestamp, float), ...] for ONE
    dimension. Empty/None -> NO_SUPPORT, with `reason_unsupported` naming
    WHY (e.g. 'no constituent map' for sector_leadership) rather than a
    bare absence."""
    import numpy as np
    import pandas as pd

    now = pd.Timestamp(now)
    known_from = pd.Timestamp(known_from)
    if not points:
        return DimensionCurvature(
            dimension=dimension, value=None, velocity=None, acceleration=None,
            curvature=None, status=NO_SUPPORT, support=0,
            coverage=reason_unsupported or "NOT_AVAILABLE",
            freshness_s=None, known_from=str(known_from), as_of=str(now))

    pts = sorted(points, key=lambda p: p[0])
    pts = [(pd.Timestamp(t), float(v)) for t, v in pts if t <= now]
    if not pts:
        return DimensionCurvature(
            dimension=dimension, value=None, velocity=None, acceleration=None,
            curvature=None, status=NO_SUPPORT, support=0,
            coverage="ALL_POINTS_FUTURE_DATED_EXCLUDED",
            freshness_s=None, known_from=str(known_from), as_of=str(now))

    value = pts[-1][1]
    freshness = (now - pts[-1][0]).total_seconds()
    t0 = pts[0][0]
    xs_h = [(t - t0).total_seconds() / 3600.0 for t, _ in pts]
    ys = [v for _, v in pts]

    if len(pts) < MIN_POINTS_FOR_VELOCITY:
        return DimensionCurvature(
            dimension=dimension, value=value, velocity=None, acceleration=None,
            curvature=None, status=INSUFFICIENT_HISTORY, support=len(pts),
            coverage=f"{len(pts)}/{MIN_POINTS_FOR_VELOCITY} points for velocity",
            freshness_s=round(freshness, 1), known_from=str(known_from),
            as_of=str(now))

    # velocity: short-horizon direction semantics, unchanged from V1 --
    # the most recent VELOCITY_WINDOW_POINTS bars, however much history
    # the caller supplied for the sigma window.
    vk = min(len(pts), VELOCITY_WINDOW_POINTS)
    velocity = _linear_slope(xs_h[-vk:], ys[-vk:])

    if len(pts) < MIN_POINTS_FOR_CURVATURE:
        return DimensionCurvature(
            dimension=dimension, value=value, velocity=velocity,
            acceleration=None, curvature=None, status=INSUFFICIENT_HISTORY,
            support=len(pts),
            coverage=f"{len(pts)}/{MIN_POINTS_FOR_CURVATURE} points for curvature",
            freshness_s=round(freshness, 1), known_from=str(known_from),
            as_of=str(now))

    # velocity series (V1 diagnostic, retained over the same short
    # window as velocity): nothing reads `acceleration` for state.
    vel_xs, vel_ys = [], []
    for i in range(len(pts) - vk + 1, len(pts)):
        if i < 1:
            continue
        dt_h = (pts[i][0] - pts[i - 1][0]).total_seconds() / 3600.0
        if dt_h <= 0:
            continue
        vel_ys.append((pts[i][1] - pts[i - 1][1]) / dt_h)
        vel_xs.append((xs_h[i] + xs_h[i - 1]) / 2)
    acceleration = _linear_slope(vel_xs, vel_ys) if len(vel_xs) >= 2 else None

    # ---- V2 CURVATURE: return-normalized second difference (z-score).
    # Mode is deterministic from the data: log returns when every level
    # is strictly positive (price-like), arithmetic differences
    # otherwise (signed level series -- RS excess return starts at 0).
    import math
    if min(ys) > 0:
        mode = "log"
        rets = [math.log(ys[i] / ys[i - 1]) for i in range(1, len(ys))]
    else:
        mode = "diff"
        rets = [ys[i] - ys[i - 1] for i in range(1, len(ys))]

    curvature = None
    trailing = rets[:-1][-SIGMA_MAX_RETURNS:]     # newest return EXCLUDED
    if len(trailing) >= MIN_SIGMA_RETURNS:
        second_diff = rets[-1] - rets[-2]
        sd = float(np.std(trailing, ddof=1))
        if sd > 0:
            curvature = round(second_diff / (sd * math.sqrt(2)), 4)
        elif second_diff == 0:
            curvature = 0.0            # exact flat / exact trend: neutral
        # else: jump out of perfect flatness -- z undefined, REFUSED

    return DimensionCurvature(
        dimension=dimension, value=round(value, 6), velocity=round(velocity, 6),
        acceleration=(round(acceleration, 6) if acceleration is not None else None),
        curvature=curvature, return_mode=mode,
        status=SUPPORTED, support=len(pts),
        coverage=f"{len(pts)} points over {xs_h[-1]:.2f}h",
        freshness_s=round(freshness, 1), known_from=str(known_from),
        as_of=str(now))


def _classify(dims: dict, breadth_usable: bool) -> dict:
    trace = []
    supported = {k: d for k, d in dims.items() if d.status == SUPPORTED}
    elevated = {k: d for k, d in supported.items() if d.elevated()}

    n_elev = len(elevated)
    elev_groups = sorted({DEPENDENCY_GROUPS[k] for k in elevated})
    # DEPENDENCY-AWARE LIKELIHOOD (Phase 5): HIGH demands both breadth
    # of evidence (>=3 elevated dims) AND mechanism diversity (>=2
    # independent groups). Three price transformations bending together
    # is MODERATE conviction about one mechanism, not HIGH conviction
    # about the market.
    likelihood = ("UNKNOWN" if not supported else
                 "NONE" if n_elev == 0 else
                 "LOW" if n_elev == 1 else
                 "HIGH" if (n_elev >= 3 and len(elev_groups) >= 2) else
                 "MODERATE")
    trace.append(f"{n_elev} elevated dims of {len(supported)} supported, "
                f"{len(elev_groups)} independent groups {elev_groups} "
                f"-> likelihood={likelihood}")

    # A FLAT (zero-velocity) dimension ABSTAINS, it does not OPPOSE: RS
    # curving up while price sits dead flat is exactly "an early signal
    # with no confirmation yet", not a contradiction. Only genuinely
    # opposite-signed velocities count as MIXED.
    dir_signs = []
    for k in DIRECTIONAL_DIMENSIONS:
        d = supported.get(k)
        if d is not None and d.velocity is not None:
            dir_signs.append(1 if d.velocity > 0 else (-1 if d.velocity < 0 else 0))
    nonzero = [s for s in dir_signs if s != 0]
    if not dir_signs or not nonzero:
        direction = "UNKNOWN"
    elif all(s == nonzero[0] for s in nonzero):
        direction = "UP" if nonzero[0] > 0 else "DOWN"
    else:
        direction = "MIXED"
    trace.append(f"directional signs {dir_signs} (nonzero {nonzero}) "
                f"-> direction={direction}")

    price = supported.get("price")
    price_confirms = (price is not None and price.elevated()
                      and direction in ("UP", "DOWN")
                      and price.velocity is not None
                      and ((price.velocity > 0) == (direction == "UP")))
    other_elevated_non_price = any(k != "price" for k in elevated)
    if price is None:
        expression = "UNKNOWN"
    elif price_confirms:
        expression = "CONFIRMED_EXPRESSION"
    elif other_elevated_non_price:
        expression = "EARLY_EXPRESSION"
    else:
        expression = "NO_EXPRESSION"
    trace.append(f"price_confirms={price_confirms} "
                f"other_elevated_non_price={other_elevated_non_price} "
                f"-> expression={expression}")

    # Deterministic priority lookup -- documented order, not a score.
    vol = supported.get("volatility")
    liq = supported.get("liquidity")
    corr = supported.get("correlation")
    sector = supported.get("sector_leadership")

    if not breadth_usable:
        trace.append("breadth NOT usable -> breadth-scoped states suppressed")

    if likelihood == "UNKNOWN":
        state = "UNKNOWN"
    elif direction in ("UP", "DOWN") and n_elev >= 1 and (
            price in elevated.values() or
            supported.get("relative_strength") in elevated.values()):
        if direction == "UP":
            state = ("POSITIVE_TRANSITION" if expression == "CONFIRMED_EXPRESSION"
                     else "EARLY_POSITIVE_CURVATURE")
        else:
            state = ("NEGATIVE_TRANSITION" if expression == "CONFIRMED_EXPRESSION"
                     else "EARLY_NEGATIVE_CURVATURE")
    elif vol is not None and vol.elevated():
        state = "VOLATILITY_EXPANSION" if (vol.velocity or 0) > 0 else "VOLATILITY_COMPRESSION"
    elif breadth_usable and sector is not None and sector.elevated():
        state = "ROTATION_TRANSITION"
    elif liq is not None and liq.elevated():
        state = "LIQUIDITY_TRANSITION"
    elif breadth_usable and corr is not None and corr.elevated():
        state = "CORRELATION_BREAK"
    else:
        state = "NO_INFLECTION"
    trace.append(f"-> high_level_state={state}")

    return {"high_level_state": state, "transition_likelihood": likelihood,
           "transition_direction": direction, "expression": expression,
           "supported_dimension_count": len(supported),
           "elevated_dimension_count": n_elev,
           "independent_elevated_groups": tuple(elev_groups),
           "reasoning": tuple(trace)}


def compute(subject: str, dimension_points: dict, *,
           observation_integrity: ObservationIntegrityState, now,
           known_from, unsupported_reasons: dict | None = None
           ) -> MarketCurvatureState:
    """`dimension_points`: {dimension_name: [(t, value), ...]} for
    whichever dimensions the caller can actually supply tonight; any
    DIMENSIONS name absent from the dict is computed as NO_SUPPORT.
    `unsupported_reasons`: optional {dimension_name: reason string} for
    honest coverage text on dimensions the caller knows it cannot
    supply (e.g. {'sector_leadership': 'DORMANT_NO_CONSTITUENT_MAP'})."""
    unsupported_reasons = unsupported_reasons or {}
    dims = {}
    for dname in DIMENSIONS:
        pts = dimension_points.get(dname)
        dims[dname] = compute_dimension(
            dname, pts, now=now, known_from=known_from,
            reason_unsupported=unsupported_reasons.get(dname))

    breadth_usable = observation_integrity.breadth_usable()
    verdict = _classify(dims, breadth_usable)

    import pandas as pd
    return MarketCurvatureState(
        subject=subject, as_of=str(pd.Timestamp(now)),
        known_from=str(pd.Timestamp(known_from)),
        dimensions={k: v.as_record() for k, v in dims.items()},
        curve_breadth_status=("FULL_COVERAGE" if breadth_usable
                              else "LIMITED_COVERAGE"),
        observation_quality=observation_integrity.quality,
        **verdict)


def persist(state: MarketCurvatureState) -> dict:
    from apex.governance.chain_ledger import chain_append as _chain_append
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    return _chain_append(LEDGER, state.as_record())
