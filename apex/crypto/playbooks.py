"""Crypto playbooks v1 — the equity MECHANISMS re-derived for a rolling
24/7 market, with thresholds frozen BEFORE the first observation
(CRYPTO-FORWARD-EPOCH-0.md). These are NOT the equity playbooks in a
costume: no opening range, no session floor, no sector — structure is
the trailing 4h range, participation is hour-of-UTC seasonality, and
relative strength is BTC-vs-ETH.

CRYPTO-001 — ROLLING MOMENTUM CONTINUATION (symmetric LONG/SHORT):
abnormal participation + 4h-structure breakout + rolling-VWAP side +
ecosystem relative strength agreeing = continued price discovery.

CRYPTO-002 — FAILED-EXTENSION REVERSION (symmetric): a >=2.5z extension
leg vs the hour's own vol scale whose structure fails (>=50% retrace,
wrong side of rolling VWAP) = reflexive flow completing.

Coding a playbook confers no predictive standing. Shadow-only: entries
are hypothetical at the RECORDED ask (long) / bid (short) — the spread
is paid on paper from observation one.
"""

from __future__ import annotations

from apex.crypto.perception import CryptoChartState

C001_VERSION = "CRYPTO-001_v1"
C001_RVOL_MIN = 1.5
C001_ACCEL_MIN = 1.3
C001_RS_AGREE = 0.001            # BTC-ETH 60m spread agreeing with direction
C001_RISK_MIN, C001_RISK_MAX = 0.001, 0.015
C001_TARGET_R = 2.0
C001_TIME_STOP_MIN = 90

C002_VERSION = "CRYPTO-002_v1"
C002_LEG_Z = 2.5
C002_RETRACE_MIN, C002_RETRACE_MAX = 0.50, 1.00
C002_RVOL_MIN = 1.2
C002_EXTREME_WINDOW_MIN = 45
C002_RISK_MIN, C002_RISK_MAX = 0.0015, 0.03
C002_TARGET_R = 1.5
C002_TIME_STOP_MIN = 60


def _t(trace, key):
    """Observational stage counter. EPOCH-0 SAFE: writes only into a
    caller-supplied dict and returns nothing, so no branch, threshold or
    return value can depend on it. Exists so the archive can tell
    "evaluated and declined" from "never evaluated" (LAB-04's lesson,
    applied to crypto) WITHOUT duplicating these predicates in a second
    place -- two sources of truth is this repo's most-repeated bug."""
    if trace is not None:
        trace[key] = trace.get(key, 0) + 1


def match_crypto_001(cs: CryptoChartState, world: dict,
                     trace: dict | None = None) -> dict | None:
    _t(trace, "C001_evaluated")
    if None in (cs.vwap_24h, cs.rvol_hour, cs.vol_accel,
                world.get("btc_eth_rs_60m")):
        _t(trace, "C001_blocked_inputs_missing")
        return None                                  # fail closed
    rs = world["btc_eth_rs_60m"]
    for direction, breakout, above, agree in (
            ("LONG", cs.breakout_4h_up, cs.above_vwap is True,
             rs >= C001_RS_AGREE),
            ("SHORT", cs.breakout_4h_down, cs.above_vwap is False,
             rs <= -C001_RS_AGREE)):
        if not (breakout and above and agree):
            continue
        _t(trace, "C001_structure_pass")
        if cs.rvol_hour < C001_RVOL_MIN or cs.vol_accel < C001_ACCEL_MIN:
            continue
        _t(trace, "C001_volume_pass")
        entry, stop = cs.price, cs.vwap_24h
        risk = abs(entry - stop) / entry
        if not (C001_RISK_MIN <= risk <= C001_RISK_MAX):
            continue
        _t(trace, "C001_risk_band_pass")
        if (direction == "LONG") != (entry > stop):
            continue                                # geometry must agree
        _t(trace, "C001_matches")
        tgt = (entry + C001_TARGET_R * (entry - stop) if direction == "LONG"
               else entry - C001_TARGET_R * (stop - entry))
        return {"playbook_id": C001_VERSION, "direction": direction,
                "entry_ref": entry, "stop": stop, "target": tgt,
                "risk_frac": risk,
                "time_stop_minutes": C001_TIME_STOP_MIN,
                "invalidation": "loss of rolling 24h VWAP",
                "matched": {"rvol_hour": cs.rvol_hour,
                            "vol_accel": cs.vol_accel,
                            "btc_eth_rs_60m": rs,
                            "pos_in_24h_range": cs.pos_in_24h_range}}
    return None


def match_crypto_002(cs: CryptoChartState, world: dict,
                     extreme_age_min: dict,
                     trace: dict | None = None) -> dict | None:
    """extreme_age_min: {'high': minutes since 24h high last touched,
    'low': ...} computed by the caller from the same candle frame."""
    _t(trace, "C002_evaluated")
    if None in (cs.vwap_24h, cs.rvol_hour, cs.vol_scale_30m,
                cs.r_30m):
        _t(trace, "C002_blocked_inputs_missing")
        return None
    if cs.rvol_hour < C002_RVOL_MIN or cs.vol_scale_30m <= 0:
        _t(trace, "C002_blocked_volume")
        return None
    _t(trace, "C002_volume_pass")
    for side, age_key, above_req in (("up", "high", False),
                                     ("down", "low", True)):
        age = extreme_age_min.get(age_key)
        if age is None or not (5 <= age <= C002_EXTREME_WINDOW_MIN):
            continue
        # the extension leg: trailing-4h extreme vs the rolling VWAP
        extreme = cs.hi_4h if side == "up" else cs.lo_4h
        if extreme is None:
            continue
        leg = (extreme - cs.vwap_24h) if side == "up" \
            else (cs.vwap_24h - extreme)
        if leg <= 0:
            continue
        leg_z = (leg / cs.vwap_24h) / cs.vol_scale_30m
        if leg_z < C002_LEG_Z:
            continue
        _t(trace, "C002_extension_pass")
        retrace = ((extreme - cs.price) / leg if side == "up"
                   else (cs.price - extreme) / leg)
        if not (C002_RETRACE_MIN <= retrace <= C002_RETRACE_MAX):
            continue
        _t(trace, "C002_retrace_pass")
        if cs.above_vwap is not above_req:
            continue
        _t(trace, "C002_vwap_pass")
        direction = "SHORT" if side == "up" else "LONG"
        entry, stop = cs.price, extreme
        risk = abs(stop - entry) / entry
        if not (C002_RISK_MIN <= risk <= C002_RISK_MAX):
            continue
        _t(trace, "C002_risk_band_pass")
        _t(trace, "C002_matches")
        tgt = (entry - C002_TARGET_R * (stop - entry) if direction == "SHORT"
               else entry + C002_TARGET_R * (entry - stop))
        return {"playbook_id": C002_VERSION, "direction": direction,
                "entry_ref": entry, "stop": stop, "target": tgt,
                "risk_frac": risk,
                "time_stop_minutes": C002_TIME_STOP_MIN,
                "invalidation": "new extreme in the extension direction",
                "matched": {"leg_z": round(leg_z, 2),
                            "retrace": round(retrace, 3),
                            "rvol_hour": cs.rvol_hour,
                            "extreme_age_min": age}}
    return None
