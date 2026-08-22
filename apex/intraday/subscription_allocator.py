"""THE 50-SYMBOL RESOURCE LAW — deterministic realtime subscription
allocation under the EODHD entitlement (measured 2026-08-17: default
plan = 50 simultaneous realtime symbols per channel).

ROLE (Phase 0.4, FULL-UNIVERSE SENSORY ARCHITECTURE): this module is the
DEEP SENSOR allocator, not the broad-discovery mechanism. A dynamic
reallocator cannot solve broad discovery on its own -- a symbol must be
observed to become interesting, but cannot become interesting if it is
never observed (P4's "remaining universe fill" is a best-effort sample
of the un-covered 114, not coverage of them). Broad, continuous, full-
universe observation is a SEPARATE, larger architecture question --
apex/intraday/universe_coverage.py + apex/intraday/provider_interface.py
+ the DATA-2 decision. Until that lands, this allocator's job is: given
a fixed, small, entitlement-bounded budget, spend it on the highest-
value names (real candidates first, then watchlist, then a deterministic
universe sample) for DEEP realtime sensing -- not to claim broad
coverage it structurally cannot provide.

No LLM ever selects a subscription. Priority is pure code over
already-persisted canonical artifacts:

    P1  market/world     INDEXES + SECTOR_ETF proxies (fixed, always in)
    P2  serious Frontier candidates (OpportunityState in SERIOUS /
        WAITING_FOR_ENTRY / CAPITAL_REVIEW — read from loop_state.json)
    P3  Scout/watchlist  (today's abnormality-scanner watchlist, read
        from the latest scan_record in forward_ledger.jsonl)
    P4  remaining frozen scan-universe fill, deterministic (sorted)
        order, until the budget is exhausted

Ties within a tier never depend on wall-clock arrival order — P2/P3 sort
by symbol name so the same inputs always produce the same allocation.

REALTIME_UNIVERSE_COVERAGE = len(streamed) / len(intended universe) is
first-class and must be reported everywhere the live feed is read — a
50/164 stream must never be described as full-universe live sensing.
"""
from __future__ import annotations

import json
from pathlib import Path

MAX_SYMBOLS = 50

FORWARD_LEDGER = Path("results/hunter/forward_ledger.jsonl")
LOOP_STATE = Path("results/frontier/loop_state.json")
SUB_LEDGER = Path("results/intraday/equity_subscription_ledger.jsonl")

SERIOUS_STATES = ("SERIOUS", "WAITING_FOR_ENTRY", "CAPITAL_REVIEW")


def _p1_market_world() -> list:
    import sys
    sys.path.insert(0, "scripts")
    from hunter_forward_clock import INDEXES, SECTOR_ETF
    syms = {s.replace(".US", "") for s in INDEXES}
    syms |= {s.replace(".US", "") for s in SECTOR_ETF.values()}
    return sorted(syms)


def _p2_serious_candidates() -> list:
    if not LOOP_STATE.exists():
        return []
    try:
        d = json.loads(LOOP_STATE.read_text())
    except json.JSONDecodeError:
        return []
    out = set()
    for cid, st in (d.get("opportunity_states") or {}).items():
        if isinstance(st, dict) and st.get("state") in SERIOUS_STATES:
            sym = st.get("symbol")
            if sym:
                out.add(sym.replace(".US", ""))
    return sorted(out)


def _p3_scout_watchlist() -> list:
    """Last watchlist from today's scan_record, tail-read only (the
    ledger can be large; we need the newest, not a full walk)."""
    if not FORWARD_LEDGER.exists():
        return []
    try:
        with open(FORWARD_LEDGER, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 300_000))
            tail = f.read().decode("utf-8", errors="ignore")
    except OSError:
        return []
    out = set()
    for line in tail.splitlines():
        line = line.strip()
        if not line or '"watchlist"' not in line:
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        for w in d.get("watchlist") or []:
            sym = w.get("symbol") if isinstance(w, dict) else None
            if sym:
                out.add(str(sym).replace(".US", ""))
    return sorted(out)


def _p4_universe_fill(exclude: set, budget: int) -> list:
    uni = sorted(Path("results/hunter").glob("scan_universe_*.json"))
    if not uni or budget <= 0:
        return []
    try:
        d = json.loads(uni[-1].read_text())
    except json.JSONDecodeError:
        return []
    syms = sorted(s for s in d.get("symbols", {}) if s not in exclude)
    return syms[:budget]


def allocate(max_symbols: int = MAX_SYMBOLS) -> dict:
    """Return {symbols, tiers, intended_universe_size, coverage}."""
    p1 = _p1_market_world()
    p2 = [s for s in _p2_serious_candidates() if s not in p1]
    p3 = [s for s in _p3_scout_watchlist() if s not in p1 and s not in p2]
    used = set(p1) | set(p2) | set(p3)
    remaining = max_symbols - len(used)
    p4 = _p4_universe_fill(exclude=used, budget=remaining) \
        if remaining > 0 else []

    ordered = p1 + p2 + p3 + p4
    if len(ordered) > max_symbols:
        # P1 is never dropped (market/world context is load-bearing for
        # every downstream candidate); trim lowest priority first
        ordered = ordered[:max_symbols]

    uni_path = sorted(Path("results/hunter").glob("scan_universe_*.json"))
    intended = len(p1)
    if uni_path:
        try:
            intended = len(json.loads(uni_path[-1].read_text())
                          .get("symbols", {})) + len(p1)
        except json.JSONDecodeError:
            pass

    return {
        "symbols": ordered,
        "tiers": {"P1_market_world": p1, "P2_serious_candidates": p2,
                 "P3_scout_watchlist": p3, "P4_universe_fill": p4},
        "intended_universe_size": intended,
        "streamed_count": len(ordered),
        "coverage_frac": (round(len(ordered) / intended, 4)
                          if intended else 0.0),
    }


def persist_change(prior: list, new: dict) -> dict:
    """Append-only record of every subscription change. No LLM in this
    path; the diff itself is the audit trail."""
    import sys
    sys.path.insert(0, "scripts")
    from nightly_pull import _chain_append
    added = sorted(set(new["symbols"]) - set(prior))
    dropped = sorted(set(prior) - set(new["symbols"]))
    rec = {"kind": "equity_subscription_change",
          "symbols": new["symbols"], "tiers": new["tiers"],
          "added": added, "dropped": dropped,
          "streamed_count": new["streamed_count"],
          "intended_universe_size": new["intended_universe_size"],
          "coverage_frac": new["coverage_frac"],
          "max_symbols": MAX_SYMBOLS,
          "selection_method": "DETERMINISTIC_CODE_NO_LLM"}
    SUB_LEDGER.parent.mkdir(parents=True, exist_ok=True)
    return _chain_append(SUB_LEDGER, rec)
