"""SHADOW RESOLUTION — one predeclared policy, fixed before outcomes.

Horizons and the exit rule are declared here and never chosen per
trade. Selecting a horizon after seeing the path is how a losing
strategy becomes a winning backtest.

Outcomes are APPENDED against a sealed decision. The decision is never
rewritten.

decision_power: SHADOW_ONLY.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

HORIZONS_MIN = (15, 30, 60)
EXIT_RULE = ("hold to the official regular-session close, or to the "
             "structural stop if it trades through first; whichever "
             "comes first. One fixed pre-declared policy, not tuned "
             "per trade")


def _t(b):
    return datetime.fromisoformat(b["event_time_utc"].replace("Z", "+00:00"))


def resolve(*, decision: dict, bars: list, close_utc) -> dict:
    """Measure the shadow trade. Only horizons that have MATURED are
    reported; an unmatured horizon is NOT_ESTIMABLE, never zero."""
    d = decision
    if d.get("decision") != "ATTACK_READY_SHADOW":
        return {"kind": "equity_shadow_outcome",
                "decision_id": d.get("decision_id"),
                "resolvable": False,
                "why": "only sealed shadow attacks resolve"}

    kf = datetime.fromisoformat(str(d["known_from"]).replace("Z", "+00:00"))
    if kf.tzinfo is None:
        kf = kf.replace(tzinfo=timezone.utc)
    close = (datetime.fromisoformat(str(close_utc).replace("Z", "+00:00"))
             if isinstance(close_utc, str) else close_utc)

    fut = sorted((_t(b), b) for b in bars if _t(b) > kf and _t(b) <= close)
    if not fut:
        return {"kind": "equity_shadow_outcome",
                "decision_id": d["decision_id"], "resolvable": False,
                "why": "no bars after known_from: unmeasurable, not flat"}

    entry = d["entry_fill"]
    stop = d["stop"]
    qty = d["quantity"]
    long_ = d["direction"] == "LONG"
    sign = 1.0 if long_ else -1.0
    fps = d.get("friction_per_share") or 0.0

    # structural stop first -- it can only trigger after entry
    stopped_at = None
    for t, b in fut:
        if (long_ and b["low"] <= stop) or (not long_ and b["high"] >= stop):
            stopped_at = (t, stop)
            break

    horizons = {}
    for h in HORIZONS_MIN:
        end = kf + timedelta(minutes=h)
        if end > close:
            horizons[f"{h}m"] = "NOT_ESTIMABLE_BEYOND_CLOSE"
            continue
        w = [(t, b) for t, b in fut if t <= end]
        if not w:
            horizons[f"{h}m"] = "NOT_ESTIMABLE"
            continue
        horizons[f"{h}m"] = round(
            sign * (w[-1][1]["close"] - entry) / entry, 6)

    hi = [sign * (b["high"] - entry) / entry for _, b in fut]
    lo = [sign * (b["low"] - entry) / entry for _, b in fut]
    mfe_v = max(hi + lo)
    mae_v = min(hi + lo)
    t_mfe = next((t for t, b in fut
                  if sign * (b["high"] - entry) / entry >= mfe_v
                  or sign * (b["low"] - entry) / entry >= mfe_v), None)
    t_mae = next((t for t, b in fut
                  if sign * (b["low"] - entry) / entry <= mae_v
                  or sign * (b["high"] - entry) / entry <= mae_v), None)

    if stopped_at:
        exit_px, exit_t, why = stop, stopped_at[0], "STRUCTURAL_STOP"
    else:
        exit_px, exit_t, why = fut[-1][1]["close"], fut[-1][0], \
            "OFFICIAL_CLOSE"

    time_to_stop = (round((exit_t - kf).total_seconds() / 60, 1)
                    if why == "STRUCTURAL_STOP" else "NOT_APPLICABLE")
    gross = sign * (exit_px - entry) * qty
    # RISK-005 (2026-09-01). This was `fps * qty * 2`. `gross` is
    # measured from `entry` = entry_fill, the EXECUTABLE fill, which
    # ALREADY crossed the spread on the way in -- so only the EXIT
    # crossing may be charged here. The old x2 billed the entry
    # crossing twice, exactly as the sizer did; because the same
    # phantom crossing sat in both the realized loss and declared_1R,
    # R cancelled to ~-1.0 and the pair of defects hid each other.
    friction = fps * qty                       # EXIT crossing only
    return {"kind": "equity_shadow_outcome",
            "decision_id": d["decision_id"], "symbol": d["symbol"],
            "resolvable": True, "exit_reason": why,
            "exit_price": round(exit_px, 6),
            "exit_time": exit_t.isoformat(),
            "signed_horizons": horizons,
            "mfe_pct": round(mfe_v, 6), "mae_pct": round(mae_v, 6),
            "time_to_mfe_min": (round((t_mfe - kf).total_seconds() / 60, 1)
                                if t_mfe else "NOT_ESTIMABLE"),
            "time_to_mae_min": (round((t_mae - kf).total_seconds() / 60, 1)
                                if t_mae else "NOT_ESTIMABLE"),
            "time_to_stop_min": time_to_stop,
            "declared_1R": d.get("declared_1R"),
            "stop_distance_atr": d.get("invalidation_distance_atr"),
            "gross_pnl": round(gross, 2),
            "friction": round(friction, 2),
            "executable_pnl": round(gross - friction, 2),
            "R": (round((gross - friction) / d["declared_1R"], 4)
                  if d.get("declared_1R") else "NOT_ESTIMABLE"),
            "exit_rule": EXIT_RULE,
            "law": "appended against a sealed decision, never merged",
            "decision_power": "SHADOW_ONLY"}
