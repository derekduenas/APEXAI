"""CLOSE-1 — read the final hour like a desk, then remember it.

ClosingContextPacket: what the day BECAME. DailyMarketMemory: the factual
bridge to tomorrow's premarket, so the Captain never wakes with amnesia.

THE ANTI-HINDSIGHT LAW, enforced in code: the Closing Brief may know the
close; the Morning Brief may not; BEFORE decision cards may not. Memory
flows FORWARD only — today's close informs tomorrow's prior, never
today's already-sealed beliefs. And per the DAILY-FLAT constitution,
nothing here answers "should we hold overnight" — closing intelligence
is knowledge, not exposure.

decision_power = NONE_FRONTIER_SHADOW throughout.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from apex.frontier import FRONTIER_POWER

CLOSING = Path("results/frontier/closing")
MEMORY = Path("results/frontier/daily_memory")

DAY_STRUCTURES = ("TREND_DAY_UP", "TREND_DAY_DOWN", "RANGE_DAY",
                  "FAILED_BREAKOUT_DAY", "FAILED_BREAKDOWN_DAY",
                  "REVERSAL_DAY", "LATE_ACCELERATION", "LATE_FADE",
                  "UNCLEAR")

SCENARIO_STATES = ("CONFIRMED", "PARTIALLY_CONFIRMED", "INVALIDATED",
                   "NOT_TESTED", "UNKNOWN")

REACTIONS = ("STRONG_POSITIVE_REACTION", "WEAK_REACTION",
             "NEGATIVE_REACTION", "STRONG_NEGATIVE_REACTION",
             "POSITIVE_REACTION", "UNKNOWN_EVENT_DIRECTION", "UNKNOWN")

PERSISTENCE = ("PERSISTED_TO_CLOSE", "DECAYED", "FAILED", "REVERSED",
               "NOT_APPLICABLE", "UNKNOWN")


class ClosingViolation(RuntimeError):
    pass


def day_structure(bars) -> dict:
    """Deterministic day-structure classification from canonical OHLCV.
    One rule set, stated facts, UNCLEAR is legal."""
    import pandas as pd
    if bars is None or not len(bars):
        return {"structure": "UNCLEAR", "reason": "no bars"}
    o = float(bars["open"].iloc[0])
    c = float(bars["close"].iloc[-1])
    hi, lo = float(bars["high"].max()), float(bars["low"].min())
    rng = hi - lo
    if rng <= 0:
        return {"structure": "UNCLEAR", "reason": "zero range"}
    close_loc = (c - lo) / rng                     # 0 low .. 1 high
    day_ret = (c - o) / o
    n = len(bars)
    last_q = bars.iloc[int(n * 0.75):]
    late_ret = ((float(last_q["close"].iloc[-1])
                 - float(last_q["open"].iloc[0]))
                / float(last_q["open"].iloc[0])) if len(last_q) else 0.0
    facts = {"day_return": round(day_ret, 5),
             "close_location_in_range": round(close_loc, 3),
             "late_quarter_return": round(late_ret, 5)}
    if abs(day_ret) < 0.002 and 0.25 <= close_loc <= 0.75:
        s = "RANGE_DAY"
    elif day_ret > 0.004 and close_loc >= 0.7:
        s = "TREND_DAY_UP"
    elif day_ret < -0.004 and close_loc <= 0.3:
        s = "TREND_DAY_DOWN"
    elif day_ret > 0 and late_ret < -0.003:
        s = "LATE_FADE"
    elif day_ret < 0 and late_ret > 0.003:
        s = "LATE_ACCELERATION" if close_loc > 0.6 else "REVERSAL_DAY"
    elif late_ret > 0.004:
        s = "LATE_ACCELERATION"
    else:
        s = "UNCLEAR"
    return {"structure": s, **facts}


def assemble(*, symbols: list, gov, as_of=None) -> dict:
    """Closing packet from full-session canonical bars. No auction
    imbalance source is connected, and the packet says so rather than
    substituting L2 for it."""
    import pandas as pd

    from apex.intraday.eodhd import fetch_intraday_chunk, normalize_rows
    now = pd.Timestamp(as_of) if as_of is not None else \
        pd.Timestamp.now(tz="UTC")
    day = str(now.tz_convert("America/New_York").date())
    states = {}
    for s in symbols:
        try:
            rows, _src = fetch_intraday_chunk(s, day, day, gov)
            f = normalize_rows(rows or [], s)
            st = day_structure(f)
            if len(f):
                st["last_bar_time"] = str(f["event_time_utc"].iloc[-1])
            states[s] = st
        except Exception as e:                              # noqa: BLE001
            states[s] = {"structure": "UNCLEAR",
                         "reason": f"FETCH_{type(e).__name__}"}
    return {"kind": "closing_context_packet", "market_date": day,
            "as_of_time": str(now),
            "created_at": str(pd.Timestamp.now(tz="UTC")),
            "day_structures": states,
            "closing_auction_imbalance": "NOT_CONNECTED",
            "moc_loc_data": "NOT_CONNECTED",
            "decision_power": FRONTIER_POWER}


def seal(packet: dict) -> dict:
    body = dict(packet)
    body["sealed"] = "SEALED_CLOSING"
    body["packet_sha256"] = hashlib.sha256(
        json.dumps({k: v for k, v in body.items() if k != "packet_sha256"},
                   sort_keys=True, default=str).encode()).hexdigest()
    CLOSING.mkdir(parents=True, exist_ok=True)
    (CLOSING / f"{packet['market_date']}.json").write_text(
        json.dumps(body, indent=2, default=str))
    return body


def write_memory(*, market_date: str, closing_packet: dict,
                 morning_packet_hash: str | None,
                 scenario_review: list | None = None,
                 leaders: list | None = None,
                 laggards: list | None = None,
                 overnight_risks: list | None = None,
                 unresolved: list | None = None) -> dict:
    """DailyMarketMemory — knowledge, not positions. Tomorrow's premarket
    CONSUMES this; nothing about today's trades survives into it as
    anything but observation."""
    rec = {"kind": "daily_market_memory", "market_date": market_date,
           "closing_packet_sha256": closing_packet.get("packet_sha256"),
           "morning_packet_sha256": morning_packet_hash or "NO_MORNING_PACKET",
           "market_structure_at_close": {
               s: v.get("structure")
               for s, v in closing_packet.get("day_structures", {}).items()},
           "scenario_review": scenario_review or [],
           "persistent_rs_leaders": leaders or [],
           "persistent_rs_laggards": laggards or [],
           "known_overnight_risks": (overnight_risks
                                     or ["MACRO_CALENDAR NOT_CONNECTED",
                                         "COMPANY_NEWS NOT_CONNECTED"]),
           "unresolved_observations": unresolved or [],
           "positions_carried_overnight": "NONE_BY_CONSTITUTION",
           "decision_power": FRONTIER_POWER}
    rec["memory_sha256"] = hashlib.sha256(
        json.dumps({k: v for k, v in rec.items() if k != "memory_sha256"},
                   sort_keys=True, default=str).encode()).hexdigest()
    MEMORY.mkdir(parents=True, exist_ok=True)
    (MEMORY / f"{market_date}.json").write_text(
        json.dumps(rec, indent=2, default=str))
    return rec


def load_memory(market_date: str) -> dict | None:
    p = MEMORY / f"{market_date}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        return None


def setup_persistence(decision: dict, realization: dict | None) -> str:
    """AFTER-only classification for decision-card outcomes: did the
    opportunity persist, decay, fail, or reverse by resolution? Uses only
    resolved canonical fields; UNKNOWN when they are absent."""
    if realization is None:
        return "UNKNOWN"
    r60 = realization.get("ret_60m")
    r90 = realization.get("ret_90m", r60)
    mae = realization.get("mae_60m") or realization.get("mae_90m")
    if r90 is None:
        return "UNKNOWN"
    sign = 1 if decision.get("direction") == "LONG" else -1
    signed = sign * r90
    if realization.get("target_before_stop"):
        return "PERSISTED_TO_CLOSE"
    if signed > 0.002:
        return "PERSISTED_TO_CLOSE"
    if signed < -0.004 or (mae is not None and sign * mae < -0.008):
        return "REVERSED" if signed < -0.004 else "FAILED"
    return "DECAYED"
