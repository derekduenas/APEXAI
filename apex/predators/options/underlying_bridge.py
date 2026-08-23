"""UNDERLYING SETUP BRIDGE -- Options borrows the Equity brain.

APEX must not grow a second equity intelligence. The Equity Predator
already owns price structure, ATR/VWAP geometry, chase risk and
invalidation; the Curve owns transition state. This module is a THIN
ADAPTER that exposes those commissioned faculties in the shape the
Options Predator consumes -- nothing here re-derives market structure.

WHAT IT ADDS: only the joins Options specifically needs (index/sector
confirmation, volume participation, extension) computed from the SAME
causal bar slice, and only where the data legitimately supports them.

PATTERN LAW: bar/candle geometry is MEASURED (range position, body
fraction, wick asymmetry) and reported as observation. No textbook
pattern name is treated as alpha; "hammer" is not a signal, it is a
description with an unproven prior.

decision_power: NONE -- a sensor adapter.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

NOT_ESTIMABLE = "NOT_ESTIMABLE"


@dataclass(frozen=True)
class UnderlyingSetupState:
    symbol: str
    T: str
    spot: float | None
    # --- borrowed from the commissioned equity faculty
    entry_quality: str = "UNKNOWN"
    chase_risk: str = "UNKNOWN"
    invalidation: float | None = None
    invalidation_distance_atr: float | None = None
    atr: float | None = None
    reward_risk_available: float | str = NOT_ESTIMABLE
    # --- joins Options needs, computed on the same causal slice
    trend_state: str = "UNKNOWN"
    range_position: float | None = None      # 0=session low, 1=high
    vwap_relationship: str = "UNKNOWN"
    vwap_distance_atr: float | None = None
    compression_state: str = "UNKNOWN"
    extension_atr: float | None = None
    volume_participation: float | str = NOT_ESTIMABLE
    bar_geometry: dict = field(default_factory=dict)
    index_confirmation: str = NOT_ESTIMABLE
    sector_confirmation: str = NOT_ESTIMABLE
    data_quality: str = "UNKNOWN"
    source: str = "EQUITY_PREDATOR_FACULTY (borrowed, not duplicated)"
    pattern_law: str = ("bar geometry is measured observation; no "
                        "textbook pattern name is treated as alpha")
    decision_power: str = "NONE"

    def as_record(self) -> dict:
        return {"kind": "underlying_setup_state", **asdict(self)}


def build(frozen, *, direction: str, index_bars: list | None = None,
          sector_bars: list | None = None) -> UnderlyingSetupState:
    """Adapt the commissioned equity geometry + causal joins into the
    Options-facing view. `frozen` is an options ReplayWorld FrozenState
    (or any object exposing underlying_bars/spot_ref/symbol/T)."""
    import pandas as pd

    from apex.predators.equities.attack_geometry import (
        EquityAttackGeometry, atr as _atr, session_vwap)
    bars = [dict(b) for b in frozen.underlying_bars]
    spot = frozen.spot_ref
    if len(bars) < 20 or spot is None:
        return UnderlyingSetupState(symbol=frozen.symbol, T=frozen.T,
                                    spot=spot,
                                    data_quality="INSUFFICIENT")

    # the equity faculty speaks its own bar dialect
    eq_bars = [{"event_time_utc": b["t"], "open": b.get("o", b["c"]),
                "high": b.get("h", b["c"]), "low": b.get("l", b["c"]),
                "close": b["c"], "volume": b.get("v", 0),
                "coverage_status": "COMPLETE_HEALTHY"} for b in bars]
    now = pd.Timestamp(eq_bars[-1]["event_time_utc"]) + \
        pd.Timedelta(minutes=1)
    geo = EquityAttackGeometry().compute(
        subject=frozen.symbol, direction=("LONG" if direction == "LONG"
                                          else "SHORT"),
        bars=eq_bars, now=now, known_from=str(now))

    a = _atr(eq_bars)
    vwap = session_vwap(eq_bars)
    hi = max(b["high"] for b in eq_bars)
    lo = min(b["low"] for b in eq_bars)
    rng = hi - lo
    last = eq_bars[-1]

    rangepos = ((last["close"] - lo) / rng) if rng > 0 else None
    vwap_rel, vwap_dist = "UNKNOWN", None
    if vwap and a:
        vwap_dist = (last["close"] - vwap) / a
        vwap_rel = ("ABOVE" if vwap_dist > 0.25 else
                    "BELOW" if vwap_dist < -0.25 else "AT")
    compression = "UNKNOWN"
    if a and rng:
        compression = ("COMPRESSED" if rng / a <= 1.2 else
                       "EXPANDED" if rng / a >= 4.0 else "NORMAL")
    trend = "UNKNOWN"
    if len(eq_bars) >= 30:
        first = eq_bars[-30]["close"]
        if a:
            drift = (last["close"] - first) / a
            trend = ("UP" if drift > 1.0 else "DOWN" if drift < -1.0
                     else "RANGE")

    # volume participation: recent vs session mean (proxy, named so)
    vols = [b["volume"] for b in eq_bars if b["volume"]]
    vp = NOT_ESTIMABLE
    if len(vols) >= 20:
        base = sum(vols) / len(vols)
        recent = sum(vols[-5:]) / 5
        vp = round(recent / base, 3) if base else NOT_ESTIMABLE

    # bar geometry: MEASURED, unnamed
    o, h, lo_, c = (last["open"], last["high"], last["low"],
                    last["close"])
    span = h - lo_
    geometry = {"body_fraction": (abs(c - o) / span) if span else None,
                "upper_wick_fraction": ((h - max(o, c)) / span)
                if span else None,
                "lower_wick_fraction": ((min(o, c) - lo_) / span)
                if span else None,
                "close_position_in_bar": ((c - lo_) / span)
                if span else None,
                "law": "measured geometry, not a named pattern"}

    def _confirm(other_bars):
        if not other_bars or len(other_bars) < 30:
            return NOT_ESTIMABLE
        oc = [b["c"] for b in other_bars]
        sc = [b["c"] for b in bars]
        n = min(30, len(oc), len(sc))
        o_ret = oc[-1] / oc[-n] - 1.0
        s_ret = sc[-1] / sc[-n] - 1.0
        if abs(o_ret) < 1e-9:
            return "FLAT"
        same = (o_ret > 0) == (s_ret > 0)
        return "CONFIRMS" if same else "DIVERGES"

    return UnderlyingSetupState(
        symbol=frozen.symbol, T=frozen.T, spot=spot,
        entry_quality=geo.entry_quality, chase_risk=geo.chase_risk,
        invalidation=geo.invalidation,
        invalidation_distance_atr=geo.invalidation_distance_atr,
        atr=geo.local_volatility_atr,
        reward_risk_available=geo.reward_risk_available,
        trend_state=trend,
        range_position=(round(rangepos, 4) if rangepos is not None
                        else None),
        vwap_relationship=vwap_rel,
        vwap_distance_atr=(round(vwap_dist, 4) if vwap_dist is not None
                           else None),
        compression_state=compression,
        extension_atr=(round(abs(vwap_dist), 4)
                       if vwap_dist is not None else None),
        volume_participation=vp, bar_geometry=geometry,
        index_confirmation=_confirm(index_bars),
        sector_confirmation=_confirm(sector_bars),
        data_quality=geo.data_quality)
