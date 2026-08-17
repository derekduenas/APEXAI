"""Frontier senses: the event bus, the equity fabric seam, dislocation
detectors, the opportunity board, and the reasoning router — Desk B's
working parts, in one module because they share one law:

    decision_power = NONE_FRONTIER_SHADOW, and honesty about transport.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from apex.frontier import FRONTIER_POWER

BUS_LEDGER = Path("results/frontier/event_bus.jsonl")
BOARD_LEDGER = Path("results/frontier/opportunity_board.jsonl")

TRANSPORTS = ("STREAMING", "POLLING", "MCP_REQUEST_RESPONSE")

EVENT_TYPES = (
    "FASTWATCH_OBSERVATION", "SCOUT_ABNORMALITY", "PRICE_DISPLACEMENT",
    "VOLUME_ACCELERATION", "VWAP_TRANSITION", "OPENING_RANGE_TRANSITION",
    "RS_ACCELERATION", "DISLOCATION_EVENT", "CATALYST_EVENT",
    "MICROSCOPE_UPDATE", "MARKET_HEALTH", "SYMBOL_STALE", "GAP_DETECTED")


class FrontierViolation(RuntimeError):
    pass


# ============================ EVENT BUS ====================================

def emit(event_type: str, symbol: str, *, event_time, known_from,
         source: str, transport: str, payload: dict | None = None) -> dict:
    """One typed event onto the frontier bus. Honesty is structural:
    an unknown transport or a detection that precedes its own known_from
    raises rather than records."""
    import pandas as pd
    if event_type not in EVENT_TYPES:
        raise FrontierViolation(f"unknown event type {event_type!r}")
    if transport not in TRANSPORTS:
        raise FrontierViolation(
            f"transport {transport!r} not in {TRANSPORTS}; polling market "
            f"data is never called streaming")
    et, kf = pd.Timestamp(event_time), pd.Timestamp(known_from)
    if kf < et:
        raise FrontierViolation(
            "known_from precedes event_time: an observation cannot be "
            "known before it happened")
    payload = payload or {}
    rec = {"kind": "frontier_event",
           "event_id": hashlib.sha256(
               f"{event_type}|{symbol}|{et}|{kf}".encode()).hexdigest()[:16],
           "event_type": event_type, "symbol": symbol,
           "event_time": str(et), "known_from": str(kf),
           "source": source, "transport": transport,
           "payload_hash": hashlib.sha256(
               json.dumps(payload, sort_keys=True, default=str).encode()
           ).hexdigest()[:16],
           "payload": payload, "decision_power": FRONTIER_POWER}
    import sys
    sys.path.insert(0, "scripts")
    from nightly_pull import _chain_append
    BUS_LEDGER.parent.mkdir(parents=True, exist_ok=True)
    _chain_append(BUS_LEDGER, rec)
    return rec


# ======================= EQUITY MARKET FABRIC ==============================

@dataclass(frozen=True)
class FabricHealth:
    transport: str                       # POLLING today, honestly
    source: str
    last_observation_utc: str | None
    staleness_seconds: float | None      # None = unknown, never 0
    gaps_detected: int
    status: str                          # HEALTHY | DEGRADED | UNKNOWN

    def as_record(self) -> dict:
        return asdict(self)


def equity_fabric_health() -> FabricHealth:
    """The equity seam, with crypto's discipline and POLLING's honesty.
    Health derives from the FastWatch ledger (the fastest real equity
    sense we have); absence is UNKNOWN, never quietly healthy."""
    import pandas as pd
    led = Path("results/hunter/fastwatch_ledger.jsonl")
    if not led.exists():
        return FabricHealth(transport="POLLING", source="EODHD_1M",
                            last_observation_utc=None,
                            staleness_seconds=None, gaps_detected=0,
                            status="UNKNOWN")
    last, gaps = None, 0
    for line in led.read_text().splitlines():
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r.get("kind") == "fastwatch_observation":
            last = r.get("observed_at") or last
            gaps += r.get("status") not in ("OK", "NO_BARS", None)
    if last is None:
        return FabricHealth("POLLING", "EODHD_1M", None, None, gaps,
                            "UNKNOWN")
    stale = (pd.Timestamp.now(tz="UTC") - pd.Timestamp(last)).total_seconds()
    return FabricHealth("POLLING", "EODHD_1M", str(last), round(stale, 1),
                        gaps, "HEALTHY" if stale < 300 else "DEGRADED")


# ======================== DISLOCATION ENGINE ===============================

DISLOCATION_STATE = "FRONTIER_DISLOCATION_OBSERVED"    # never SIGNAL

DETECTABLE = ("PRICE_MARKET_DIVERGENCE", "RELATIVE_STRENGTH_DISLOCATION",
              "VOLUME_DISLOCATION", "VOLATILITY_DISLOCATION",
              "FAILED_AUCTION", "EVENT_REPRICING")
NOT_YET_DETECTABLE = {         # honesty about missing senses, per class
    "PRICE_SECTOR_DIVERGENCE": "sector frame not in the fast path yet",
    "LIQUIDITY_VACUUM": "needs continuous L2; microscope is snapshot-only",
    "TRAPPED_PARTICIPANT_UNWIND": "needs acceptance-shape tracking",
    "OPTIONS_UNDERLYING_DISAGREEMENT": "needs an options surface",
    "CROSS_ASSET_CONTRADICTION": "needs a cross-asset fabric",
}


def detect_dislocations(chart_state: dict, rs: dict, market_state: dict,
                        catalyst_status: str | None = None) -> tuple:
    """Observational detectors over CANONICAL persisted fields — nothing
    is recomputed and nothing is fitted. Each observation names its
    mechanism hypothesis and its falsification, because a dislocation is
    an invitation to ask WHY, never a signal."""
    out = []

    def obs(cls, facts, mechanism, falsify, contra=()):
        out.append({"kind": "dislocation_observation", "class": cls,
                    "state": DISLOCATION_STATE, "observed_facts": facts,
                    "mechanism_hypothesis": mechanism,
                    "contradicting_measurements": list(contra),
                    "falsification_condition": falsify,
                    "decision_power": FRONTIER_POWER})

    rvol = chart_state.get("rvol_tod")
    ratr = chart_state.get("range_vs_atr")
    gap = chart_state.get("gap_frac")
    exm = (rs or {}).get("excess_market_60m")
    xpct = (rs or {}).get("cross_sectional_pct")
    day = (market_state or {}).get("day_return")

    if exm is not None and day is not None and abs(exm) >= 0.02:
        obs("PRICE_MARKET_DIVERGENCE",
            {"excess_market_60m": exm, "market_day_return": day},
            "idiosyncratic information or forced flow decoupling the "
            "symbol from its market",
            "excess reverts toward beta band within the session")
    if xpct is not None and (xpct >= 0.98 or xpct <= 0.02):
        obs("RELATIVE_STRENGTH_DISLOCATION",
            {"cross_sectional_pct": xpct},
            "sustained one-sided repositioning pinning cross-sectional RS",
            "percentile leaves the extreme decile")
    if rvol is not None and ratr is not None and rvol >= 3.0:
        mech = ("participation WITH progress: initiative repricing"
                if ratr >= 1.5 else
                "participation WITHOUT progress: absorption — someone is "
                "being paid to sit there")
        obs("VOLUME_DISLOCATION", {"rvol_tod": rvol, "range_vs_atr": ratr},
            mech, "RVOL decays to baseline without structural change")
    if ratr is not None and (ratr >= 2.5 or 0 < ratr <= 0.25):
        obs("VOLATILITY_DISLOCATION", {"range_vs_atr": ratr},
            "energy spent (serial expansion)" if ratr >= 2.5
            else "energy stored (deep compression)",
            "range context normalizes without a regime transition")
    if gap is not None and abs(gap) >= 0.03:
        obs("FAILED_AUCTION" if (chart_state.get("above_vwap") is False
                                 and gap > 0) else "PRICE_MARKET_DIVERGENCE",
            {"gap_frac": gap, "above_vwap": chart_state.get("above_vwap")},
            "overnight repricing; gap cohort positioning at risk",
            "gap edge acceptance/rejection resolves within the session")
    if catalyst_status == "KNOWN_CATALYST" and rvol is not None and rvol >= 2:
        obs("EVENT_REPRICING",
            {"catalyst": catalyst_status, "rvol_tod": rvol},
            "the market digesting a filed event",
            "volume/vol normalize with price accepting a new level")
    elif catalyst_status == "EVENT_UNCERTAIN":
        # EVENT_REPRICING is FORBIDDEN under uncertain attribution
        pass
    return tuple(out)


# ================== FRONTIER OPPORTUNITY COMPETITION =======================

RANK_ORDER = ("data_health", "candidate_class", "direction_quality",
              "entry_quality", "assassin", "world_alignment",
              "rs_persistence", "catalyst_clarity", "dislocation_clarity",
              "execution_quality", "freshness")

# lexicographic value maps: LOWER sorts FIRST. UNKNOWN is always the worst
# value in its dimension, so missingness can never outrank knowledge.
_VAL = {
    "data_health": {"HEALTHY": 0, "PARTIAL": 1, "DEGRADED": 2, "UNKNOWN": 9},
    "candidate_class": {"HUNTER": 0, "NEAR": 1, "WATCH": 2, "UNKNOWN": 9},
    "direction_quality": {"STRONG": 0, "MODERATE": 1, "WEAK": 2, "UNKNOWN": 9},
    "entry_quality": {"STRONG": 0, "MODERATE": 1, "WEAK": 2, "UNKNOWN": 9},
    "assassin": {"SURVIVED_CLEAN": 0, "SURVIVED_WOUNDED": 1, "UNKNOWN": 9},
    "world_alignment": {"ALIGNED": 0, "MIXED": 1, "CONFLICTED": 2, "UNKNOWN": 9},
    "rs_persistence": {"PERSISTENT": 0, "MIXED": 1, "FADING": 2, "UNKNOWN": 9},
    "catalyst_clarity": {"KNOWN_CATALYST": 0, "NO_KNOWN_CATALYST": 1,
                         "EVENT_UNCERTAIN": 2, "UNKNOWN": 9},
    "dislocation_clarity": {"MECHANISM_STATED": 0, "NONE": 1, "UNKNOWN": 9},
    "execution_quality": {"GOOD": 0, "ACCEPTABLE": 1, "POOR": 2, "UNKNOWN": 9},
    "freshness": {"FRESH": 0, "AGING": 1, "STALE": 2, "UNKNOWN": 9},
}


def rank_opportunities(candidates: list) -> dict:
    """Deterministic, fitted-weight-free competition. Input: dicts of
    categorical states (+ symbol, as_of). Output: a persisted board
    snapshot where every rejection stays visible and the question answered
    is opportunity COST: is this the best use of attention right now?"""
    def key(c):
        return tuple(_VAL[d].get(str(c.get(d, "UNKNOWN")), 9)
                     for d in RANK_ORDER) + (c.get("symbol", ""),
                                             str(c.get("as_of", "")))
    ranked = sorted(candidates, key=key)
    rows = []
    for i, c in enumerate(ranked):
        rows.append({**{d: c.get(d, "UNKNOWN") for d in RANK_ORDER},
                     "symbol": c.get("symbol"), "as_of": c.get("as_of"),
                     "shadow_rank": i + 1,
                     "strongest_alternative": (ranked[0].get("symbol")
                                               if i else None)})
    snap = {"kind": "frontier_opportunity_board", "ranked": rows,
            "n_competing": len(rows), "rank_order": list(RANK_ORDER),
            "decision_power": FRONTIER_POWER}
    import sys
    sys.path.insert(0, "scripts")
    from nightly_pull import _chain_append
    BOARD_LEDGER.parent.mkdir(parents=True, exist_ok=True)
    _chain_append(BOARD_LEDGER, snap)
    return snap


# ======================= REASONING ROUTER ==================================

TIERS = {0: "ordinary scan: no expensive reasoning",
         1: "watchlist: context packet only",
         2: "hunter/strong near-candidate: microscope + visual eyes",
         3: "persistent serious candidate: deep oracle/swarm/captain"}


def route_reasoning(*, is_hunter_candidate: bool, on_watchlist: bool,
                    persistence_ticks: int | None) -> dict:
    """Governs COMPUTE/ATTENTION only — the record it returns contains no
    field a sizing or authorization path could even misread as one.
    Unknown persistence does not invent expected edge; it caps at tier 2."""
    if is_hunter_candidate and (persistence_ticks or 0) >= 2:
        tier = 3
    elif is_hunter_candidate:
        tier = 2
    elif on_watchlist:
        tier = 1
    else:
        tier = 0
    return {"kind": "frontier_reasoning_route", "reasoning_tier": tier,
            "reason": TIERS[tier],
            "persistence_ticks": persistence_ticks,
            "decision_power": FRONTIER_POWER,
            "note": "more compute never means more position size"}
