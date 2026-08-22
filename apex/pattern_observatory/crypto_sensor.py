"""CRYPTO SLEEVE SENSOR -- lights the Observatory's crypto facet.

THE DEFECT (living-organism diagnostic, 2026-08-21). The crypto facet
was declared DARK and the CRYPTO_DERIVATIVES evidence group starved --
while a LIVE, HEALTHY crypto capture daemon (com.apex.crypto-daemon,
Coinbase forward-observation arena) ran on this very machine: connected
book, tens of thousands of heartbeats, hash-chained scan ticks with
playbook evaluations, ~40MB/hour of raw events. A real sensor existed
and nothing consumed it. This module is the read-only adapter.

WHAT IT READS (never writes): the arena's own health artifact and the
tail of its hash-chained scan ledger. WHAT IT REPORTS: sensor liveness,
book health, bar health, and the arena's own playbook-evaluation
counters -- honest observability of the crypto sleeve's state, NOT a
market signal. Deriving crypto market features (funding, OI, basis)
remains future work and is declared as such.

decision_power: NONE_PATTERN_OBSERVATORY. The crypto arena keeps its
own (NONE_OBSERVATIONAL_EPOCH0) authority; this adapter adds none.
"""
from __future__ import annotations

import json
from pathlib import Path

from apex.pattern_observatory import OBSERVATORY_POWER

HEALTH_PATH = Path("results/crypto/crypto_health.json")
ARENA_LEDGER = Path("results/crypto/arena_ledger.jsonl")
STALE_AFTER_S = 300.0


def observe(*, now) -> dict:
    """The crypto facet's state, honestly. LIVE only when the arena's
    heartbeat is fresh and its book is healthy; DARK with a named
    reason otherwise."""
    import pandas as pd
    now = pd.Timestamp(now)

    if not HEALTH_PATH.exists():
        return {"status": "DARK",
                "reason": "crypto arena health artifact absent",
                "decision_power": OBSERVATORY_POWER}
    try:
        h = json.loads(HEALTH_PATH.read_text())
    except (json.JSONDecodeError, OSError) as e:
        return {"status": "DARK",
                "reason": f"health artifact unreadable: {type(e).__name__}",
                "decision_power": OBSERVATORY_POWER}

    hb = h.get("last_heartbeat")
    try:
        hb_ts = pd.Timestamp(hb)
        if hb_ts.tz is None:
            hb_ts = hb_ts.tz_localize("UTC")
        age = (now - hb_ts).total_seconds()
    except (ValueError, TypeError):
        age = None

    if age is None or age > STALE_AFTER_S:
        return {"status": "DARK",
                "reason": f"arena heartbeat stale "
                          f"({round(age) if age is not None else '?'}s "
                          f"> {STALE_AFTER_S:g}s)",
                "last_heartbeat": hb,
                "decision_power": OBSERVATORY_POWER}

    tick = _latest_tick()
    fh = h.get("fabric_health") or {}
    return {
        "status": "LIVE",
        "state": {
            "kind": "crypto_sleeve_state",
            # PRECISE TERMINOLOGY (operator law, 2026-08-21): what is
            # live is CONTEXT -- spot/book/arena observability. Nobody
            # reading "crypto facet = LIVE" six weeks from now may be
            # allowed to assume APEX was seeing derivatives information
            # that was not there.
            "crypto_context": "LIVE",
            "btc_perps_derivatives": _derivatives_status(),
            "as_of": str(now), "known_from": str(now),
            "source": "crypto arena (read-only adapter)",
            "evidence_class": (tick or {}).get("evidence_class"),
            "sensor": {
                "connected": fh.get("connected"),
                "book_health": h.get("book_health"),
                "reconnects": fh.get("reconnects"),
                "heartbeat_age_s": round(age, 1),
            },
            "arena": ({
                "bars_healthy": tick.get("bars_healthy"),
                "playbooks_evaluated": sorted(
                    k.split("_")[0] for k in tick
                    if k.endswith("_evaluated")),
                "matches": sum(v for k, v in tick.items()
                               if k.endswith("_matches")
                               and isinstance(v, int)),
                "scan_status": tick.get("scan_status"),
            } if tick else {"status": "NO_TICK_READ"}),
            "market_features": _derivatives_features(now),
            "decision_power": OBSERVATORY_POWER,
        },
    }


DERIVATIVES_HEALTH = Path("results/btc/derivatives_health.json")
DERIVATIVES_STALE_S = 120.0


def _derivatives_status() -> str:
    """PARTIAL since 2026-08-21 evening: the BTC-L1 poller flows real
    funding/OI/mark/index/basis from Deribit + Kraken Futures + OKX (+
    Coinbase spot reference). Trades-WS/book/liquidations still missing
    -- so PARTIAL, never LIVE, until they flow too. Stale poller ->
    honest NOT_AVAILABLE."""
    feats = _read_derivatives_health()
    if feats is None:
        return "NOT_AVAILABLE"
    return "PARTIAL"


def _read_derivatives_health() -> dict | None:
    import time as _t
    try:
        d = json.loads(DERIVATIVES_HEALTH.read_text())
        import pandas as pd
        age = (_t.time()
               - pd.Timestamp(d["as_of"]).timestamp())
        if age > DERIVATIVES_STALE_S:
            return None
        return d
    except (OSError, ValueError, KeyError):
        return None


def _derivatives_features(now) -> dict:
    h = _read_derivatives_health()
    if h is None:
        return {"funding": "NOT_AVAILABLE", "open_interest": "NOT_AVAILABLE",
                "liquidations": "NOT_AVAILABLE", "perp_basis": "NOT_AVAILABLE",
                "cross_exchange_positioning": "NOT_AVAILABLE",
                "status": "NOT_DERIVED",
                "reason": "BTC-L1 derivatives poller absent or stale"}
    return {"funding": "FLOWING (Deribit/KrakenFutures/OKX, per-venue)",
            "open_interest": "FLOWING (Deribit/KrakenFutures, per-venue)",
            "perp_basis": "FLOWING (Deribit mark vs Coinbase spot, "
                          "source-attributed)",
            "mark_index": "FLOWING",
            "liquidations": "NOT_AVAILABLE (stream not built)",
            "perp_trades_book": "NOT_AVAILABLE (WS streams not built)",
            "cross_exchange_positioning": "PARTIAL (3 reachable venues; "
                                          "Binance 451 / Bybit 403 "
                                          "geo-blocked, recorded)",
            "status": "PARTIAL",
            "source": "results/btc/derivatives_ledger.jsonl "
                      "(hash-chained, per-venue provenance)"}


def _latest_tick() -> dict | None:
    if not ARENA_LEDGER.exists():
        return None
    try:
        size = ARENA_LEDGER.stat().st_size
        with ARENA_LEDGER.open("rb") as fh:
            fh.seek(max(0, size - 65536))
            tail = fh.read().decode("utf-8", errors="replace")
        for line in reversed(tail.splitlines()):
            try:
                d = json.loads(line)
                if d.get("kind") == "crypto_scan_tick":
                    return d
            except json.JSONDecodeError:
                continue
    except OSError:
        pass
    return None
