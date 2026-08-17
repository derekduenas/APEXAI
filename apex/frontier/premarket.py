"""PREMARKET-1 — the desk wakes up before the market does.

PremarketContextPacket: WHAT changed overnight, WHERE capital moved,
WHY where identifiable, and — first-class — WHAT WE CANNOT SEE. Sealed
before the bell; regular-session evidence outranks it forever after.

decision_power = NONE_FRONTIER_SHADOW. Epoch-1 neither reads nor waits
on any of this.

THE COVERAGE LAW: every section states its source status. There is no
global "news coverage = good" — a Captain that assumes its information
world is complete is the failure mode this module exists to prevent.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from apex.frontier import FRONTIER_POWER

PACKETS = Path("results/frontier/premarket")

INDICES = ("SPY.US", "QQQ.US", "IWM.US", "DIA.US")

# Source coverage, stated per section. Tonight's honest matrix: EODHD
# extended-hours and SEC are live; Robinhood earnings runs through the
# child session when available; everything else is NOT_CONNECTED and the
# packet SAYS SO rather than quietly narrowing the world.
SOURCES = {
    "EODHD_PREMARKET": "CONNECTED",
    "SEC_EDGAR": "CONNECTED",
    "ROBINHOOD_EARNINGS": "CHILD_SESSION_WHEN_AVAILABLE",
    "COMPANY_NEWS": "NOT_CONNECTED",
    "ANALYST_NEWS": "NOT_CONNECTED",
    "MACRO_CALENDAR": "NOT_CONNECTED",
    "CROSS_ASSET": "NOT_CONNECTED",
}


class PremarketViolation(RuntimeError):
    pass


def _premarket_state(symbol: str, gov, day: str, prior_day: str) -> dict:
    """One symbol's overnight facts from EODHD extended-hours 1m bars.
    Absent fields stay absent — no fabricated VWAPs, no zero volumes."""
    import pandas as pd

    from apex.intraday.eodhd import fetch_intraday_chunk, normalize_rows
    rows, _src = fetch_intraday_chunk(symbol, prior_day, day, gov)
    if rows is None:
        return {"symbol": symbol, "status": "PAUSED_LAB_QUOTA"}
    f = normalize_rows(rows, symbol)
    if not len(f):
        return {"symbol": symbol, "status": "NO_BARS"}
    prior = f[f["event_time_utc"].dt.date.astype(str) == prior_day]
    today = f[f["event_time_utc"].dt.date.astype(str) == day]
    if not len(prior):
        return {"symbol": symbol, "status": "NO_PRIOR_SESSION"}
    prior_close = float(prior["close"].iloc[-1])
    out = {"symbol": symbol, "status": "OK", "prior_close": prior_close,
           "prior_close_time": str(prior["event_time_utc"].iloc[-1])}
    if len(today):
        last = float(today["close"].iloc[-1])
        vol = float(today["volume"].sum())
        out.update({
            "premarket_last": last,
            "gap_frac": round((last - prior_close) / prior_close, 5),
            "premarket_high": float(today["high"].max()),
            "premarket_low": float(today["low"].min()),
            "premarket_volume": vol,
            "premarket_bars": int(len(today)),
            "last_bar_time": str(today["event_time_utc"].iloc[-1]),
        })
    else:
        out["premarket_status"] = "NO_PREMARKET_PRINTS_YET"
    return out


def assemble(*, symbols: list, gov, as_of=None,
             catalyst_lookup=None) -> dict:
    """Build (not yet seal) the packet. `symbols` = indices + the bounded
    watch universe; `catalyst_lookup(sym)` = the Event Eyes."""
    import pandas as pd
    now = pd.Timestamp(as_of) if as_of is not None else \
        pd.Timestamp.now(tz="UTC")
    et = now.tz_convert("America/New_York")
    day = str(et.date())
    import sys
    sys.path.insert(0, "scripts")
    from nightly_pull import is_trading_day
    prior = et - pd.Timedelta(days=1)
    while not is_trading_day(str(prior.date())):
        prior -= pd.Timedelta(days=1)
    prior_day = str(prior.date())

    market, names = {}, {}
    for s in symbols:
        st = _premarket_state(s, gov, day, prior_day)
        (market if s in INDICES else names)[s] = st

    # gap/abnormality map — observational, ranked, bounded
    movers = [v for v in names.values()
              if v.get("status") == "OK" and "gap_frac" in v]
    movers.sort(key=lambda v: -abs(v["gap_frac"]))
    abnormal = []
    for v in movers[:15]:
        entry = {"symbol": v["symbol"], "gap_frac": v["gap_frac"],
                 "premarket_volume": v.get("premarket_volume"),
                 "state": "PREMARKET_ABNORMALITY"}
        if catalyst_lookup is not None:
            try:
                cat = catalyst_lookup(v["symbol"], now)
                entry["catalyst_status"] = cat.status
                if abs(v["gap_frac"]) >= 0.02 and \
                        cat.status.startswith("NO_KNOWN_CATALYST"):
                    # big move + volume + no identified explanation is
                    # ITSELF interesting — precisely labeled: not
                    # identified BY OUR ACTIVE SOURCES, not inexplicable.
                    entry["state"] = "UNKNOWN_CATALYST_DISLOCATION"
            except Exception as e:                          # noqa: BLE001
                entry["catalyst_status"] = f"UNKNOWN_{type(e).__name__}"
        abnormal.append(entry)

    # THE COGNITIVE LOOP: yesterday's DailyMarketMemory is the prior's
    # prior. Consumed read-only; absent reads NO_PRIOR_MEMORY, and
    # nothing about yesterday's TRADES arrives — knowledge, not positions.
    from apex.frontier.closing import load_memory
    mem = load_memory(prior_day)
    memory_section = ({"status": "NO_PRIOR_MEMORY"} if mem is None else
                      {"memory_sha256": mem.get("memory_sha256"),
                       "market_structure_at_close": mem.get(
                           "market_structure_at_close"),
                       "persistent_rs_leaders": mem.get(
                           "persistent_rs_leaders"),
                       "known_overnight_risks": mem.get(
                           "known_overnight_risks")})

    return {
        "kind": "premarket_context_packet",
        "yesterday_memory": memory_section,
        "market_date": day, "prior_session": prior_day,
        "as_of_time": str(now), "created_at": str(pd.Timestamp.now(tz="UTC")),
        "source_coverage": dict(SOURCES),
        "indices": market,
        "gap_map": abnormal,
        "watch_map": {
            "GAP_LEADERS": [a["symbol"] for a in abnormal
                            if a["gap_frac"] > 0][:5],
            "GAP_LAGGARDS": [a["symbol"] for a in abnormal
                             if a["gap_frac"] < 0][:5],
            "UNKNOWN_CATALYST_MOVERS": [
                a["symbol"] for a in abnormal
                if a["state"] == "UNKNOWN_CATALYST_DISLOCATION"][:5],
        },
        "blind_spots": [k for k, v in SOURCES.items()
                        if v == "NOT_CONNECTED"],
        "decision_power": FRONTIER_POWER,
    }


def seal(packet: dict) -> dict:
    """Seal the OPENING version. Refuses to seal after the bell — a
    'premarket' packet written at 09:47 ET would be hindsight wearing a
    morning coat."""
    import pandas as pd
    et = pd.Timestamp(packet["as_of_time"]).tz_convert("America/New_York")
    bell = et.normalize() + pd.Timedelta(hours=9, minutes=30)
    if et >= bell:
        raise PremarketViolation(
            f"refusing to seal a premarket packet at {et} — the session "
            f"is open; this would be hindsight, not context")
    body = {k: v for k, v in packet.items()}
    body["sealed"] = "SEALED_BEFORE_OPEN"
    body["packet_sha256"] = hashlib.sha256(
        json.dumps({k: v for k, v in body.items()
                    if k != "packet_sha256"},
                   sort_keys=True, default=str).encode()).hexdigest()
    PACKETS.mkdir(parents=True, exist_ok=True)
    (PACKETS / f"{packet['market_date']}.json").write_text(
        json.dumps(body, indent=2, default=str))
    return body


def load_sealed(day: str) -> dict | None:
    p = PACKETS / f"{day}.json"
    if not p.exists():
        return None
    try:
        rec = json.loads(p.read_text())
    except json.JSONDecodeError:
        return None
    return rec if rec.get("sealed") == "SEALED_BEFORE_OPEN" else None
