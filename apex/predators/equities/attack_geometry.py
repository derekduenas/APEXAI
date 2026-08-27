"""EQUITY ATTACK GEOMETRY v1.

DATA INVENTORY FIRST (performed 2026-08-22 against the real persisted
intraday bar store; the vendor name is deliberately not written here --
this module has no broker dependency and the architecture firewall
enforces that). Available per 1m bar:
    open high low close volume trades coverage_status gap_duration_ms
    event_time_utc transport
NOT available: bid/ask, book depth, spread, NBBO history.

Therefore v1 implements ONLY primitives those bars support:

    IMPLEMENTED   ATR (true-range, local volatility unit)
                  session VWAP (price*volume cumulative)
                  extension from VWAP in ATR units  -> chase risk
                  pullback depth from swing extreme -> entry zone
                  compression (recent range / ATR)
                  swing structure (rolling extremes) -> invalidation
                  RVOL proxy (bar volume vs session mean)
                  coverage/freshness                -> data quality

    REFUSED       spread / executable liquidity -> NOT_ESTIMABLE
                  (no quotes are persisted; the liquidity law then
                  forbids a STRONG entry, by design)
                  expected MAE/MFE -> NOT_ESTIMABLE in v1 (would
                  require historical analogs; World Lab supplies them
                  later, and inventing them now would be fabrication)

PREDECLARED SEMANTICS (fixed 2026-08-22 BEFORE any profitability
measurement -- outcome data may later judge these, never author them):

    chase_risk from |close - vwap| / ATR:
        <= 0.5  LOW      <= 1.5  MODERATE
        <= 3.0  HIGH     >  3.0  EXTREME

    entry_quality:
        GOOD        pullback into the zone, chase LOW/MODERATE,
                    invalidation within 1.5 ATR, structure intact
        ACCEPTABLE  one condition soft
        POOR        chase HIGH/EXTREME, or invalidation > 3 ATR
        UNKNOWN     insufficient/stale data

    STRONG is UNREACHABLE for equities in v1 -- the liquidity law
    requires known executable liquidity, and no quotes are persisted.
    This is recorded as an honest ceiling, not a defect to route
    around: it tells us exactly which data acquisition unlocks the
    top tier.

decision_power: NONE.
"""
from __future__ import annotations

import math

from apex.predators.core.attack_geometry import (
    NOT_ESTIMABLE, AttackGeometry, AttackGeometryEngine, unknown_geometry)

MIN_BARS = 20                  # below this, geometry is UNKNOWN
ATR_WINDOW = 14
SWING_WINDOW = 20
MAX_STALENESS_S = 300.0        # predeclared freshness policy

CHASE_LOW_ATR = 0.5
CHASE_MODERATE_ATR = 1.5
CHASE_HIGH_ATR = 3.0
INVALIDATION_GOOD_ATR = 1.5
INVALIDATION_POOR_ATR = 3.0
COMPRESSION_TIGHT = 1.2        # recent range / ATR below this = coiled

# GEO-2026-08-26-A. NUMERICAL epsilon ONLY -- this exists to identify
# floating-point-zero distance, NOT to declare an economically minimum
# risk distance. Choosing a value because 0.15 ATR "performs badly"
# would be strategy tuning; this says only that a stop AT the entry is
# not a location.
DEGENERATE_ATR_EPSILON = 1e-9


def _true_ranges(bars: list) -> list:
    out = []
    for i in range(1, len(bars)):
        h, lo = bars[i]["high"], bars[i]["low"]
        pc = bars[i - 1]["close"]
        out.append(max(h - lo, abs(h - pc), abs(lo - pc)))
    return out


def atr(bars: list, window: int = ATR_WINDOW) -> float | None:
    tr = _true_ranges(bars)
    if len(tr) < window:
        return None
    w = tr[-window:]
    a = sum(w) / len(w)
    return a if a > 0 else None


def session_vwap(bars: list) -> float | None:
    num = sum(((b["high"] + b["low"] + b["close"]) / 3.0) * b["volume"]
              for b in bars)
    den = sum(b["volume"] for b in bars)
    return (num / den) if den > 0 else None


def rvol_proxy(bars: list, window: int = 5) -> float | None:
    if len(bars) < window * 2:
        return None
    recent = sum(b["volume"] for b in bars[-window:]) / window
    base = sum(b["volume"] for b in bars) / len(bars)
    return (recent / base) if base > 0 else None


def _chase(extension_atr: float) -> str:
    if extension_atr <= CHASE_LOW_ATR:
        return "LOW"
    if extension_atr <= CHASE_MODERATE_ATR:
        return "MODERATE"
    if extension_atr <= CHASE_HIGH_ATR:
        return "HIGH"
    return "EXTREME"


class EquityAttackGeometry(AttackGeometryEngine):
    sleeve = "EQUITIES_INTRADAY"

    def compute(self, *, subject: str, direction: str, bars: list,
                now, known_from: str,
                liquidity_quality: str = NOT_ESTIMABLE) -> AttackGeometry:
        """`bars` must be ascending 1m bars whose event_time <= now.
        The caller is responsible for that slice; this method asserts
        it rather than trusting it (no-future-bars law)."""
        import pandas as pd
        now = pd.Timestamp(now)

        if not bars or len(bars) < MIN_BARS:
            return unknown_geometry(
                self.sleeve, subject, direction, known_from,
                f"insufficient bars ({len(bars)} < {MIN_BARS})")

        last_t = pd.Timestamp(bars[-1]["event_time_utc"])
        if last_t > now:
            raise ValueError(
                "NO-FUTURE-BARS VIOLATION: bar at "
                f"{last_t} is after now={now}")
        stale_s = (now - last_t).total_seconds()
        if stale_s > MAX_STALENESS_S:
            return unknown_geometry(
                self.sleeve, subject, direction, known_from,
                f"stale tape ({stale_s:.0f}s > {MAX_STALENESS_S:.0f}s)")

        a = atr(bars)
        vwap = session_vwap(bars)
        if a is None or vwap is None:
            return unknown_geometry(
                self.sleeve, subject, direction, known_from,
                "ATR or VWAP not computable")

        close = bars[-1]["close"]
        window = bars[-SWING_WINDOW:]
        swing_hi = max(b["high"] for b in window)
        swing_lo = min(b["low"] for b in window)

        extension_atr = abs(close - vwap) / a
        chase = _chase(extension_atr)

        # invalidation: the structural level whose loss kills the thesis
        if direction == "LONG":
            invalidation = swing_lo
            adverse = close - invalidation
            objective = swing_hi
        else:
            invalidation = swing_hi
            adverse = invalidation - close
            objective = swing_lo
        inval_atr = abs(adverse) / a

        # ---- DEGENERATE GEOMETRY INVARIANT (GEO-2026-08-26-A)
        # A P1 defect found by the 2026-08-26 causal audit: reward/risk
        # was guarded against adverse == 0, but inval_atr was not, so a
        # ZERO invalidation distance satisfied `inval_atr <=
        # INVALIDATION_GOOD_ATR` and scored as the BEST possible
        # location. AAPL 12:01:57 that session recorded inval_atr = 0.0
        # exactly (close == 20-bar swing low) and was blocked only by
        # chase == EXTREME -- by luck, not by law.
        #
        # A stop at the entry is not bounded risk; it is no room at all,
        # and a declared 1R computed from it is meaningless. This is a
        # SEMANTIC correction, not an economic threshold: mathematically
        # defined, economically untradeable.
        degenerate = (not math.isfinite(inval_atr)
                      or not math.isfinite(adverse)
                      or abs(adverse) <= DEGENERATE_ATR_EPSILON
                      or inval_atr <= DEGENERATE_ATR_EPSILON)

        # pullback: how far back from the extreme we are, in ATR
        if direction == "LONG":
            pullback_atr = (swing_hi - close) / a
        else:
            pullback_atr = (close - swing_lo) / a

        rng = (swing_hi - swing_lo) / a
        compressed = rng <= COMPRESSION_TIGHT
        rvol = rvol_proxy(bars)

        reward = abs(objective - close)
        rr = (reward / adverse) if adverse > 0 else None

        coverage_ok = all(
            b.get("coverage_status") in (None, "COMPLETE_HEALTHY",
                                         "COMPLETE_WITH_GAP")
            for b in bars[-SWING_WINDOW:])
        data_quality = "FULL" if coverage_ok else "PARTIAL"

        # --- the predeclared entry rules
        reasons = [
            f"extension {extension_atr:.2f} ATR from VWAP -> chase {chase}",
            f"invalidation {inval_atr:.2f} ATR away",
            f"pullback {pullback_atr:.2f} ATR from swing extreme",
            f"range/ATR {rng:.2f}{' (compressed)' if compressed else ''}",
        ]
        if degenerate:
            eq = "DEGENERATE_GEOMETRY"
            reasons.append(
                f"invalidation sits at the entry (adverse room "
                f"{adverse:.6g}, {inval_atr:.6g} ATR): there is no "
                f"room to be wrong, so this is not a location -- "
                f"never attackable, and never GOOD")
        elif chase in ("HIGH", "EXTREME"):
            eq = "POOR"
            reasons.append("chase forbids attack regardless of thesis")
        elif inval_atr > INVALIDATION_POOR_ATR:
            eq = "POOR"
            reasons.append("invalidation too distant to bound risk")
        elif (chase in ("LOW", "MODERATE")
              and inval_atr <= INVALIDATION_GOOD_ATR
              and pullback_atr > 0.0):
            eq = "GOOD"
            reasons.append("pullback into structure with bounded risk")
        else:
            eq = "ACCEPTABLE"
            reasons.append("one geometric condition soft")

        # THE CEILING: no persisted quotes -> liquidity unknown ->
        # STRONG unreachable. Recorded, never routed around.
        if eq == "GOOD" and liquidity_quality in ("UNKNOWN",
                                                  NOT_ESTIMABLE):
            reasons.append(
                "STRONG withheld: executable liquidity unknown "
                "(no quotes persisted) -- v1 ceiling is GOOD")

        return AttackGeometry(
            sleeve=self.sleeve, subject=subject, direction=direction,
            entry_quality=eq,
            # geometry_quality is the vocabulary SHARED with Captain, so
            # the new DEGENERATE state is not pushed into it: a
            # degenerate location grades POOR on the shared scale while
            # entry_quality carries the precise reason. Widening a
            # shared enum to describe one sleeve's edge case would make
            # every other consumer handle a state it never asked for.
            geometry_quality=("POOR" if eq == "DEGENERATE_GEOMETRY"
                              else eq if data_quality == "FULL"
                              else "UNKNOWN" if eq == "UNKNOWN"
                              else "ACCEPTABLE"),
            entry_zone=(round(min(close, vwap), 4),
                        round(max(close, vwap), 4)),
            invalidation=round(invalidation, 4),
            invalidation_distance_atr=round(inval_atr, 4),
            chase_risk=chase,
            local_volatility_atr=round(a, 6),
            liquidity_quality=liquidity_quality,
            expected_mae_r=NOT_ESTIMABLE,
            expected_mfe_r=NOT_ESTIMABLE,
            time_to_move=NOT_ESTIMABLE,
            reward_risk_available=round(rr, 3) if rr else NOT_ESTIMABLE,
            data_quality=data_quality,
            known_from=known_from,
            pedigree={"primitives": ["ATR", "session_VWAP",
                                     "swing_structure", "extension",
                                     "pullback", "compression",
                                     "rvol_proxy"],
                      "atr_window": ATR_WINDOW,
                      "swing_window": SWING_WINDOW,
                      "bars_used": len(bars),
                      "rvol_proxy": round(rvol, 3) if rvol else None,
                      "compressed": compressed,
                      "rules_predeclared": "2026-08-22 before any "
                                           "profitability measurement",
                      "not_outcome_tuned": True},
            reasoning=tuple(reasons))
