"""Hunter-001 v1 and Hunter-002 v1 — the first two mechanism-backed
playbooks, deliberately OPPOSING (continuation vs exhaustion), so APEX can
learn which regime a move belongs to rather than becoming momentum-biased.

Every threshold here is frozen BEFORE any forward scoring and justified
economically/statistically in docs/HUNTER-00x-PLAYBOOK.md — never fit to
outcomes (there are no outcomes yet; that is the point). Coding a playbook
confers no predictive standing (P0 contract law). A match is a CANDIDATE
DECISION with declared geometry; whether it becomes anything more is the
forward ledger's verdict.

No ML. No probabilities. Record features + rule matches + outcomes; asking
which states separate outcomes is a question for AFTER the data exists.
"""

from __future__ import annotations

from apex.hunter.chartstate import ChartState
from apex.hunter.contracts import PlaybookDefinition
from apex.hunter.relstrength import RelativeStrengthState

# ---------------------------------------------------------------- Hunter-001
H001_VERSION = "HUNTER-001_v1"
H001_RVOL_MIN = 2.0
H001_XS_MARKET_60M = 0.0075
H001_XS_SECTOR_60M = 0.0050
H001_MARKET_FLOOR = -0.005          # SPY day return below this = prohibited
H001_RISK_MIN, H001_RISK_MAX = 0.0015, 0.015
H001_TARGET_R = 2.0
H001_TIME_STOP_MIN = 90

HUNTER_001 = PlaybookDefinition(
    playbook_id=H001_VERSION,
    mechanism=("Abnormal participation plus sustained relative strength "
               "plus a structural breakout above the opening range, in a "
               "non-hostile market, may represent continued intraday price "
               "discovery (institutional accumulation absorbing supply) "
               "rather than random movement."),
    eligible_universe="scan universe (frozen liquidity tier)",
    required_state={"market_day_return_gte": H001_MARKET_FLOOR},
    prohibited_state={"market_day_return_lt": H001_MARKET_FLOOR},
    required_data=("1m bars", "daily context", "market state",
                   "sector state"),
    setup=(f"or_complete AND above_vwap AND or_break_up AND rvol_tod >= "
           f"{H001_RVOL_MIN} AND excess_market_60m >= {H001_XS_MARKET_60M} "
           f"AND excess_sector_60m >= {H001_XS_SECTOR_60M}"),
    trigger="excess_market_15m > 0 AND excess_market_30m > 0 (agreement)",
    entry_semantics="last visible 1m close at formation",
    invalidation="price loses VWAP (close below formation VWAP)",
    stop_methodology=("structural: stop = formation VWAP; risk = entry - "
                      f"stop, required within [{H001_RISK_MIN:.2%}, "
                      f"{H001_RISK_MAX:.2%}] of price (tighter is noise, "
                      f"wider is poor geometry)"),
    target_methodology=f"entry + {H001_TARGET_R} x risk",
    time_stop_minutes=H001_TIME_STOP_MIN,
    max_holding_minutes=390,
    execution_restrictions="paper decision records only; no live orders",
    calibration_requirement="UNCALIBRATED (v1 records, never sizes)",
    known_failure_modes=("crowded momentum reversal", "index-driven squeeze",
                         "late-day liquidity fade", "news invalidation"))


def match_hunter_001(cs: ChartState, rs: RelativeStrengthState,
                     market: ChartState) -> dict | None:
    """LONG continuation candidate, or None. All predicates required."""
    if None in (cs.vwap, cs.rvol_tod, rs.excess_market_60m,
                rs.excess_sector_60m, rs.excess_market_15m,
                rs.excess_market_30m, market.day_return):
        return None                                   # fail closed on missing
    if not (cs.or_complete and cs.above_vwap and cs.or_break_up):
        return None
    if cs.rvol_tod < H001_RVOL_MIN:
        return None
    if (rs.excess_market_60m < H001_XS_MARKET_60M
            or rs.excess_sector_60m < H001_XS_SECTOR_60M):
        return None
    if not (rs.excess_market_15m > 0 and rs.excess_market_30m > 0):
        return None
    if market.day_return < H001_MARKET_FLOOR:
        return None
    entry, stop = cs.price, cs.vwap
    risk = (entry - stop) / entry
    if not (H001_RISK_MIN <= risk <= H001_RISK_MAX):
        return None
    return {"playbook_id": H001_VERSION, "direction": "LONG",
            "entry": entry, "stop": stop,
            "target": entry + H001_TARGET_R * (entry - stop),
            "risk_frac": risk, "time_stop_minutes": H001_TIME_STOP_MIN,
            "invalidation": HUNTER_001.invalidation,
            "matched": {"rvol_tod": cs.rvol_tod,
                        "excess_market_60m": rs.excess_market_60m,
                        "excess_sector_60m": rs.excess_sector_60m,
                        "position_in_or": cs.position_in_or,
                        "market_day_return": market.day_return}}


# ---------------------------------------------------------------- Hunter-002
H002_VERSION = "HUNTER-002_v1"
H002_LEG_Z = 2.5                    # extension leg vs ATR-implied 30m scale
H002_RETRACE_MIN, H002_RETRACE_MAX = 0.50, 1.00
H002_RVOL_MIN = 1.5
H002_EXTREME_WINDOW_MIN = 45
H002_RISK_MIN, H002_RISK_MAX = 0.002, 0.04
H002_TARGET_R = 1.5
H002_TIME_STOP_MIN = 60

HUNTER_002 = PlaybookDefinition(
    playbook_id=H002_VERSION,
    mechanism=("An extreme short-horizon displacement that then LOSES its "
               "structural confirmation (retraces half the extension leg, "
               "loses VWAP, loses relative strength) may represent "
               "exhaustion — forced/reflexive flows completing — and revert "
               "toward intraday equilibrium rather than continue."),
    eligible_universe="scan universe (frozen liquidity tier)",
    required_state={"extension_leg_z_gte": H002_LEG_Z},
    prohibited_state={"fresh_extreme_within_min": 5},
    required_data=("1m bars", "daily context", "market state"),
    setup=(f"extension leg (extreme vs min/max close in the 60m before its "
           f"last touch) >= {H002_LEG_Z}x the ATR-implied 30m scale AND the "
           f"extreme's last touch within [5, {H002_EXTREME_WINDOW_MIN}]m AND "
           f"rvol_tod >= {H002_RVOL_MIN}"),
    trigger=(f"retraced [{H002_RETRACE_MIN:.0%}, {H002_RETRACE_MAX:.0%}] of "
             f"the leg (beyond {H002_RETRACE_MAX:.0%} the reversion already "
             f"happened) AND on the wrong side of VWAP AND "
             f"excess_market_15m sign against the extension"),
    entry_semantics="last visible 1m close at formation",
    invalidation="a new session extreme in the extension direction",
    stop_methodology=("structural: stop = the session extreme; risk within "
                      f"[{H002_RISK_MIN:.2%}, {H002_RISK_MAX:.2%}] of price "
                      f"(an extreme leg's stop is naturally a multiple of "
                      f"the 30m scale; ~2x daily ATR caps it)"),
    target_methodology=f"entry -/+ {H002_TARGET_R} x risk (declared R)",
    time_stop_minutes=H002_TIME_STOP_MIN,
    max_holding_minutes=390,
    execution_restrictions="paper decision records only; no live orders",
    calibration_requirement="UNCALIBRATED (v1 records, never sizes)",
    known_failure_modes=("genuine-news trend continues", "short squeeze "
                         "through the extreme", "V-shaped reclaim",
                         "catalyst arriving mid-trade"))


def _leg_z(leg_frac: float, atr_frac: float | None) -> float | None:
    """Extension leg magnitude in units of the ATR-implied 30m scale
    (atr_frac / sqrt(13)); prior-day scale only."""
    if not atr_frac:
        return None
    import numpy as np
    return float(leg_frac / (atr_frac / np.sqrt(13)))


def match_hunter_002(cs: ChartState, rs: RelativeStrengthState,
                     geo: dict) -> dict | None:
    """Failed-extension reversion, or None. SHORT against a failed
    up-extension; LONG against a failed down-extension (symmetric). `geo`
    from forward_pass.extension_geometry — the SAME visible-bars frame
    (as-of inherited). The up side is evaluated first; the predicates make
    both sides matching simultaneously geometrically impossible (a name
    cannot be below VWAP with excess<0 and above VWAP with excess>0)."""
    if None in (cs.vwap, cs.rvol_tod, rs.excess_market_15m):
        return None
    if cs.rvol_tod < H002_RVOL_MIN:
        return None
    for side in ("up", "down"):
        extreme = geo.get("session_high" if side == "up" else "session_low")
        age = geo.get(f"session_{'high' if side == 'up' else 'low'}_age_min")
        leg_start = geo.get(f"leg_start_{side}")
        if None in (extreme, age, leg_start):
            continue
        if not 5 <= age <= H002_EXTREME_WINDOW_MIN:    # fresh = knife; old = stale
            continue
        leg = (extreme - leg_start) if side == "up" else (leg_start - extreme)
        if leg <= 0:
            continue
        z = _leg_z(leg / leg_start, cs.atr_frac)
        if z is None or z < H002_LEG_Z:
            continue
        retrace = ((extreme - cs.price) / leg if side == "up"
                   else (cs.price - extreme) / leg)
        if not (H002_RETRACE_MIN <= retrace <= H002_RETRACE_MAX):
            continue
        if side == "up":
            if cs.above_vwap is not False or rs.excess_market_15m >= 0:
                continue
            entry, stop, direction = cs.price, extreme, "SHORT"
            risk = (stop - entry) / entry
            target = entry - H002_TARGET_R * (stop - entry)
        else:
            if cs.above_vwap is not True or rs.excess_market_15m <= 0:
                continue
            entry, stop, direction = cs.price, extreme, "LONG"
            risk = (entry - stop) / entry
            target = entry + H002_TARGET_R * (entry - stop)
        if not (H002_RISK_MIN <= risk <= H002_RISK_MAX):
            continue
        return {"playbook_id": H002_VERSION, "direction": direction,
                "entry": entry, "stop": stop, "target": target,
                "risk_frac": risk, "time_stop_minutes": H002_TIME_STOP_MIN,
                "invalidation": HUNTER_002.invalidation,
                "matched": {"leg_z": z, "retrace": retrace,
                            "extreme_age_min": age,
                            "rvol_tod": cs.rvol_tod,
                            "excess_market_15m": rs.excess_market_15m}}
    return None
