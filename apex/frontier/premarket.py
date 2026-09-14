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


def packets_dir() -> Path:
    """The output root. Resolved through premarket_runtime so BOTH the legacy runner and the staged production
    entry point honour exactly the same redirection -- if they did not, a parity comparison between them would be
    comparing two different filesystems. With no root declared the module constant stands, so the existing
    `monkeypatch.setattr(pm, "PACKETS", ...)` seam is unchanged."""
    import os

    from apex.frontier import premarket_runtime as RT
    return RT.root() if os.environ.get(RT.ENV_ROOT) else PACKETS

INDICES = ("SPY.US", "QQQ.US", "IWM.US", "DIA.US")

# ------------------------------------------------------------------ packet schema versions
#
# WHY A VERSION RATHER THAN A REDEFINITION. Until R5 the packet had no schema field and one timestamp,
# `as_of_time`, that was doing three jobs: downstream availability, the data cutoff, and source freshness. R5
# separates them. Silently changing what `as_of_time` means would have made every packet already on disk lie
# about itself in retrospect, so the new shape is a NEW VERSION and the old one keeps its bytes and its original
# interpretation.
PACKET_SCHEMA_V1 = "PREMARKET_CONTEXT_PACKET_V1"      # implicit; V1 packets carry no `schema` field at all
PACKET_SCHEMA_V2 = "PREMARKET_CONTEXT_PACKET_V2"

# `as_of_time` survives into V2 because real downstream readers (closing_run, mission_control, frontier_loop)
# already consume it -- but it survives WITH A MACHINE-READABLE DEFINITION attached to every packet, so no reader
# has to infer its meaning from the field name. That inference is exactly the defect being repaired.
AS_OF_TIME_SEMANTICS_V2 = {
    "field": "as_of_time",
    "means": "PACKET_SEALED_AT",
    "equals": "time.packet_sealed_at",
    "does_not_mean": ["SOURCE_FRESHNESS", "INFORMATION_CUTOFF", "LATEST_OBSERVATION_TIME"],
    "information_cutoff_field": "time.packet_data_cutoff",
    "availability_field": "time.packet_known_from",
    "per_source_freshness_field": "time.per_source_freshness_s",
}

AS_OF_TIME_SEMANTICS_V1 = {
    "field": "as_of_time",
    "means": "PACKET_SEALED_AT",
    "does_not_mean": ["SOURCE_FRESHNESS", "INFORMATION_CUTOFF"],
    "information_cutoff_field": "UNRECONSTRUCTIBLE",
    "per_source_freshness_field": "UNRECONSTRUCTIBLE",
    "note": ("a V1 packet records no source instants at all. Its downstream availability is reconstructible from "
             "as_of_time; its SOURCE FRESHNESS is not, and must be reported UNRECONSTRUCTIBLE rather than "
             "inferred from the seal clock."),
}


def packet_schema(packet: dict) -> str:
    return packet.get("schema") or PACKET_SCHEMA_V1


def interpret(packet: dict) -> dict:
    """What this packet's timestamps mean, for THIS packet's version. Readers call this instead of guessing."""
    v = packet_schema(packet)
    if v == PACKET_SCHEMA_V2:
        return {"schema": v, "as_of_time": AS_OF_TIME_SEMANTICS_V2,
                "information_cutoff": (packet.get("time") or {}).get("packet_data_cutoff", "UNAVAILABLE"),
                "packet_known_from": (packet.get("time") or {}).get("packet_known_from", "UNAVAILABLE"),
                "per_source_freshness_s": (packet.get("time") or {}).get("per_source_freshness_s", {}),
                "source_freshness": "RECONSTRUCTIBLE"}
    return {"schema": v, "as_of_time": AS_OF_TIME_SEMANTICS_V1,
            "information_cutoff": "UNRECONSTRUCTIBLE",
            "packet_known_from": packet.get("as_of_time", "UNAVAILABLE"),
            "per_source_freshness_s": {}, "source_freshness": "UNRECONSTRUCTIBLE"}

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


def _premarket_state(symbol: str, gov, day: str, prior_day: str, fetch=None) -> dict:
    """One symbol's overnight facts from EODHD extended-hours 1m bars.
    Absent fields stay absent — no fabricated VWAPs, no zero volumes."""
    import pandas as pd

    from apex.intraday.eodhd import fetch_intraday_chunk, normalize_rows
    # `fetch` is the ONE declared transport seam. None means the real network call. Passing it explicitly (rather
    # than monkeypatching a module attribute) is what lets the staged producer wrap the transport to capture raw
    # responses content-addressably without a second copy of this function existing anywhere.
    rows, _src = (fetch or fetch_intraday_chunk)(symbol, prior_day, day, gov)
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
             catalyst_lookup=None, fetch=None) -> dict:
    """Build (not yet seal) the packet. `symbols` = indices + the bounded
    watch universe; `catalyst_lookup(sym)` = the Event Eyes."""
    import pandas as pd
    from apex.frontier import premarket_runtime as RT
    now = pd.Timestamp(as_of) if as_of is not None else RT.now_utc()
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
        st = _premarket_state(s, gov, day, prior_day, fetch)
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
        "as_of_time": str(now), "created_at": str(RT.now_utc()),
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


def _rt_now():
    from apex.frontier import premarket_runtime as RT
    return RT.now_utc()


def seal(packet: dict) -> dict:
    """Seal the OPENING version. Refuses to seal after the bell — a
    'premarket' packet written at 09:47 ET would be hindsight wearing a
    morning coat."""
    import pandas as pd
    et = pd.Timestamp(packet["as_of_time"]).tz_convert("America/New_York")
    # WALL-CLOCK, not midnight-plus-elapsed. `normalize() + Timedelta(hours=9, minutes=30)` lands at 10:30 on the
    # spring-forward date and 08:30 on the fall-back date, so the hindsight guard would have been an hour wrong
    # in both directions on those days. Dormant (both are Sundays in the market timezone) and fixed anyway.
    bell = pd.Timestamp("%s 09:30" % et.date(), tz="America/New_York")
    if et >= bell:
        raise PremarketViolation(
            f"refusing to seal a premarket packet at {et} — the session "
            f"is open; this would be hindsight, not context")
    body = {k: v for k, v in packet.items()}
    body["sealed"] = "SEALED_BEFORE_OPEN"

    # V2: the seal instant is STAMPED INTO the time block and then BOUND BY THE DIGEST below, so a packet cannot
    # be sealed without its complete time model being part of what the hash covers. The laws are re-checked here,
    # at the seal, because that is the last moment a violation can still be refused instead of published.
    if body.get("schema") == PACKET_SCHEMA_V2:
        from apex.frontier import premarket_time as _pt
        sealed_at = et.tz_convert("UTC").timestamp()
        t = dict(body.get("time") or {})
        # Recompute the LAWS-CHECKED fields, but do not discard instants the producer recorded that the law
        # checker does not know about (morning_started_at). Replacing the block wholesale silently dropped one.
        computed = _pt.packet_times(
            collection_started_at=t.get("packet_collection_started_at", _pt.UNAVAILABLE),
            observations=body.get("source_observations") or [],
            ai_request_time=t.get("ai_request_time"), ai_response_time=t.get("ai_response_time"),
            created_at=t.get("packet_created_at", _pt.UNAVAILABLE), sealed_at=sealed_at,
            declared_cutoff=t.get("packet_data_cutoff"))
        body["time"] = {**t, **computed}
        body["as_of_time_semantics"] = dict(AS_OF_TIME_SEMANTICS_V2)

    body["packet_sha256"] = hashlib.sha256(
        json.dumps({k: v for k, v in body.items()
                    if k != "packet_sha256"},
                   sort_keys=True, default=str).encode()).hexdigest()
    out_dir = packets_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    canonical = out_dir / f"{packet['market_date']}.json"
    canonical.write_text(json.dumps(body, indent=2, default=str))

    # MANIFEST REGISTRATION (Phase 1.1, 2026-08-18). On 2026-08-18 the
    # EOD recap could not locate a sealed Morning Prior at all and fell
    # back to guessing filenames, which found nothing. Registration
    # happens HERE, at the one real seal site, so a packet cannot be
    # sealed without becoming deterministically locatable. A manifest
    # failure must never invalidate an otherwise-good seal, so it is
    # reported and swallowed -- locate() will then honestly return None
    # rather than a false success.
    try:
        from apex.memory import morning_prior_manifest as _mpm
        _mpm.register(
            session_date=packet["market_date"], canonical_path=canonical,
            source_health={
                "source_coverage": body.get("source_coverage"),
                "blind_spots": body.get("blind_spots"),
                "packet_sha256": body["packet_sha256"],
            },
            known_from=packet["as_of_time"], now=_rt_now(),
            runtime_version="premarket_seal_v1")
    except Exception as e:                                  # noqa: BLE001
        print(f"morning prior manifest registration FAILED "
              f"({type(e).__name__}: {e}) -- packet is sealed but will NOT "
              f"be deterministically locatable at EOD")
    return body


def load_sealed(day: str) -> dict | None:
    p = packets_dir() / f"{day}.json"
    if not p.exists():
        return None
    try:
        rec = json.loads(p.read_text())
    except json.JSONDecodeError:
        return None
    return rec if rec.get("sealed") == "SEALED_BEFORE_OPEN" else None
