"""Surface physics — the layer that starts after basic Greeks: skew,
smile, term structure, forward variance, implied move, and surface
change-over-time. Cross-sectional fields (skew slope, smile curvature,
term structure slope, forward variance, implied move, IV bid/ask
uncertainty) are computed from a SINGLE point-in-time set of strikes/
expiries and are real today, needing no history.

Time-derivative fields (surface velocity/acceleration, skew change,
term-structure change, option/underlying divergence, realized-vs-
implied gap) require a real time series of snapshots that this package
does not yet have a live feed for -- build_cross_sectional() always
leaves them None, and compute_time_derivatives() only fills them in
when the caller supplies real prior snapshots, never estimating them
from a single point.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import numpy as np

from apex.option_analytics import OPTION_ANALYTICS_POWER


class SurfacePhysicsError(RuntimeError):
    pass


@dataclass(frozen=True)
class SurfacePhysicsSnapshot:
    subject: str
    local_skew_slope: float | None
    smile_curvature: float | None
    term_structure_slope: float | None
    forward_variance: float | None
    implied_move_pct: float | None
    iv_bid_ask_uncertainty: float | None
    surface_velocity: float | None
    surface_acceleration: float | None
    skew_change: float | None
    term_structure_change: float | None
    option_underlying_divergence: float | None
    realized_vs_implied_gap: float | None
    known_from: str
    decision_power: str = OPTION_ANALYTICS_POWER

    def as_record(self) -> dict:
        return {"kind": "surface_physics_snapshot", **asdict(self)}


def _fit_slope(log_moneyness: list, ivs: list) -> float | None:
    if len(log_moneyness) < 2:
        return None
    coeffs = np.polyfit(log_moneyness, ivs, 1)
    return float(coeffs[0])


def _fit_curvature(log_moneyness: list, ivs: list) -> float | None:
    if len(log_moneyness) < 3:
        return None
    coeffs = np.polyfit(log_moneyness, ivs, 2)
    return float(coeffs[0])   # quadratic coefficient


def _validate_distinct_tenors(tenor_iv_pairs: tuple) -> None:
    tenors = [t for t, _ in tenor_iv_pairs]
    if len(set(tenors)) != len(tenors):
        raise SurfacePhysicsError("tenor pairs must have distinct tenors")


def _term_structure_slope(tenor_iv_pairs: tuple) -> float | None:
    if len(tenor_iv_pairs) < 2:
        return None
    tenors = [t for t, _ in tenor_iv_pairs]
    ivs = [iv for _, iv in tenor_iv_pairs]
    return float(np.polyfit(tenors, ivs, 1)[0])


def _forward_variance(tenor_iv_pairs: tuple) -> float | None:
    """Between the two SHORTEST tenors only -- the standard forward-
    variance identity sigma_fwd^2*(T2-T1) = sigma2^2*T2 - sigma1^2*T1
    is a pairwise relationship, not something that generalizes cleanly
    to >2 points without a full term-structure model, which this
    package does not build."""
    if len(tenor_iv_pairs) < 2:
        return None
    ordered = sorted(tenor_iv_pairs, key=lambda p: p[0])
    (t1, s1), (t2, s2) = ordered[0], ordered[1]
    var_fwd = (s2 ** 2 * t2 - s1 ** 2 * t1) / (t2 - t1)
    if var_fwd < 0:
        return None   # a negative forward variance means the inputs are not internally consistent
    return var_fwd


def build_cross_sectional(subject: str, *, known_from,
                          strike_log_moneyness_iv: tuple = (),
                          tenor_iv_pairs: tuple = (),
                          atm_straddle_price: float | None = None,
                          spot: float | None = None,
                          iv_bid_ask_spreads: tuple = ()) -> SurfacePhysicsSnapshot:
    """`strike_log_moneyness_iv`: tuple of (log(strike/spot), iv) pairs
    at ONE expiry, used for skew/smile. `tenor_iv_pairs`: tuple of
    (tenor_years, atm_iv) pairs across expiries, used for term
    structure / forward variance. `iv_bid_ask_spreads`: tuple of
    (iv_ask - iv_bid) values across whatever contracts the caller has
    solved, for the uncertainty-width statistic."""
    import pandas as pd
    if tenor_iv_pairs:
        _validate_distinct_tenors(tenor_iv_pairs)
    log_m = [lm for lm, iv in strike_log_moneyness_iv if iv is not None]
    ivs = [iv for lm, iv in strike_log_moneyness_iv if iv is not None]

    implied_move = (atm_straddle_price / spot) if (atm_straddle_price is not None
                                                    and spot not in (None, 0)) else None
    uncertainty = (sum(iv_bid_ask_spreads) / len(iv_bid_ask_spreads)
                  if iv_bid_ask_spreads else None)

    return SurfacePhysicsSnapshot(
        subject=subject, local_skew_slope=_fit_slope(log_m, ivs),
        smile_curvature=_fit_curvature(log_m, ivs),
        term_structure_slope=_term_structure_slope(tenor_iv_pairs),
        forward_variance=_forward_variance(tenor_iv_pairs),
        implied_move_pct=implied_move, iv_bid_ask_uncertainty=uncertainty,
        surface_velocity=None, surface_acceleration=None, skew_change=None,
        term_structure_change=None, option_underlying_divergence=None,
        realized_vs_implied_gap=None, known_from=str(pd.Timestamp(known_from)))


def compute_time_derivatives(*, subject: str, known_from,
                             prior: SurfacePhysicsSnapshot | None,
                             current: SurfacePhysicsSnapshot,
                             prior_to_prior: SurfacePhysicsSnapshot | None = None,
                             dt_years: float | None = None,
                             realized_move_pct: float | None = None
                             ) -> SurfacePhysicsSnapshot:
    """Returns a NEW snapshot with the time-derivative fields filled in
    from real history -- `prior`/`prior_to_prior` are actual earlier
    SurfacePhysicsSnapshot objects, never invented. Any field this
    function cannot honestly compute (missing history, missing dt)
    stays None on the returned snapshot."""
    velocity = accel = skew_change = ts_change = div_gap = None

    if prior is not None and dt_years and dt_years > 0:
        if current.term_structure_slope is not None and prior.term_structure_slope is not None:
            velocity = (current.term_structure_slope - prior.term_structure_slope) / dt_years
        if current.local_skew_slope is not None and prior.local_skew_slope is not None:
            skew_change = current.local_skew_slope - prior.local_skew_slope
        if current.term_structure_slope is not None and prior.term_structure_slope is not None:
            ts_change = current.term_structure_slope - prior.term_structure_slope

    if (prior is not None and prior_to_prior is not None and dt_years and dt_years > 0
            and current.term_structure_slope is not None
            and prior.term_structure_slope is not None
            and prior_to_prior.term_structure_slope is not None):
        v1 = (prior.term_structure_slope - prior_to_prior.term_structure_slope) / dt_years
        v2 = (current.term_structure_slope - prior.term_structure_slope) / dt_years
        accel = (v2 - v1) / dt_years

    if realized_move_pct is not None and current.implied_move_pct is not None:
        div_gap = realized_move_pct - current.implied_move_pct

    import pandas as pd
    return SurfacePhysicsSnapshot(
        subject=subject, local_skew_slope=current.local_skew_slope,
        smile_curvature=current.smile_curvature,
        term_structure_slope=current.term_structure_slope,
        forward_variance=current.forward_variance,
        implied_move_pct=current.implied_move_pct,
        iv_bid_ask_uncertainty=current.iv_bid_ask_uncertainty,
        surface_velocity=velocity, surface_acceleration=accel,
        skew_change=skew_change, term_structure_change=ts_change,
        option_underlying_divergence=None, realized_vs_implied_gap=div_gap,
        known_from=str(pd.Timestamp(known_from)))
