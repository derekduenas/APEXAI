"""CANONICAL CHAIN -> EXPRESSION ADAPTER -- the missing bridge.

THE DEFECT (living-organism diagnostic, 2026-08-21, operator-corrected
terminology): APEX HAS a live canonical option chain -- the analytics
runtime fetches real snapshots every cycle and persists per-contract
states with real bid/ask, IV, BSM Greeks, spot, and quote quality. What
did not exist was the ADAPTER: nothing ever constructed
OptionExpressionCandidate objects from that canonical feed, so
expression_engine.run() received option_candidates=() forever and
option structures could never be ranked against EQUITY / NO_TRADE.

ONE CANONICAL FEED, MULTIPLE CONSUMERS (the operator's target shape):
Analytics writes it; Surface reads it; the Pattern Observatory reads
it; and now Expression reads it -- through this adapter. No duplicate
scraping, no second chain.

WHAT THIS ADAPTER BUILDS, deliberately minimal V1:

  LONG_CALL  (direction UP)  -- nearest-liquid near-ATM call
  LONG_PUT   (direction DOWN) -- nearest-liquid near-ATM put

both tagged OPT-001-DIRECTIONAL-CONVEXITY (the one ACTIVE mechanism
that needs no analytics certification). Verticals (OPT-002) stay out
until the adversarial suite certifies the analytics, exactly as the
engine's ANALYTICS_GATED law requires. Every economic number on the
candidate is REAL (quoted mid, quoted spread, BSM Greeks from the
canonical record); nothing is modeled here.

CLOCK INTEGRITY: contracts with negative quote_age_s or stale quotes
are excluded BEFORE selection -- the 2026-08-19 lesson, applied at the
door.

decision_power: NONE -- the adapter constructs candidates; the engine's
gates and Capital decide.
"""
from __future__ import annotations

import json
from pathlib import Path

from apex.options_research import OPTIONS_RESEARCH_POWER
from apex.options_research.expression_candidate import (
    OptionExpressionCandidate,
)
from apex.options_research.surface_state import build_surface

STATES_PATH = Path("results/option_analytics/live/states.jsonl")

MAX_QUOTE_AGE_S = 120.0
MIN_DEPTH_CONTRACTS = 5          # bid_size + ask_size floor
TARGET_ABS_DELTA = 0.55          # near-ATM directional convexity
MIN_DTE = 1                      # 0DTE structurally out of scope
FEES_PER_CONTRACT = 0.65


class ChainAdapterError(RuntimeError):
    pass


def _underlying_of(occ_symbol: str) -> str:
    """OCC symbols: root + yymmdd + C/P + strike*1000. The root is the
    leading alphabetic run."""
    root = []
    for ch in occ_symbol:
        if ch.isalpha():
            root.append(ch)
        else:
            break
    return "".join(root)


def load_chain(underlying: str, *, now, path: Path | None = None,
               tail_bytes: int = 8_000_000) -> list:
    """The freshest canonical per-contract states for `underlying`,
    clock-clean and quote-fresh. Reads only the file TAIL (the ledger
    grows ~20k rows/day; the freshest cycle lives at the end)."""
    import pandas as pd
    p = path or STATES_PATH
    if not p.exists():
        return []
    size = p.stat().st_size
    with p.open("rb") as fh:
        fh.seek(max(0, size - tail_bytes))
        tail = fh.read().decode("utf-8", errors="replace")
    lines = tail.splitlines()
    if size > tail_bytes and lines:
        lines = lines[1:]

    now = pd.Timestamp(now)
    best: dict = {}                      # occ symbol -> freshest record
    for line in lines:
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        sym = d.get("symbol", "")
        if _underlying_of(sym) != underlying:
            continue
        lq = d.get("live_quality") or {}
        age = lq.get("quote_age_s")
        if age is None or age < 0 or age > MAX_QUOTE_AGE_S:
            continue                     # clock integrity at the door
        if d.get("state_quality") not in ("HIGH", "MODERATE"):
            continue
        if d.get("market_bid") is None or d.get("market_ask") is None:
            continue
        try:
            rec_time = pd.Timestamp(d.get("as_of"))
            if rec_time.tz is None:
                rec_time = rec_time.tz_localize("UTC")
        except (ValueError, TypeError):
            continue
        if (now - rec_time).total_seconds() > 15 * 60:
            continue                     # a dead feed is not a chain
        prior = best.get(sym)
        if prior is None or d.get("as_of", "") > prior.get("as_of", ""):
            best[sym] = d
    return list(best.values())


def _bsm(d: dict, greek: str) -> float | None:
    g = d.get(greek)
    if isinstance(g, dict):
        return g.get("bsm_value")
    return None


def _depth(d: dict) -> int:
    lq = d.get("live_quality") or {}
    return int(lq.get("bid_size") or 0) + int(lq.get("ask_size") or 0)


def select_directional(chain: list, direction: str, *, now) -> dict | None:
    """The nearest-liquid near-ATM contract of the right type on the
    front eligible expiry. Deterministic; refuses (None) rather than
    stretching when nothing qualifies."""
    import pandas as pd
    want = "call" if direction == "UP" else "put"
    today = pd.Timestamp(now).tz_convert("UTC").date()
    usable = []
    for d in chain:
        if d.get("option_type") != want:
            continue
        try:
            dte = (pd.Timestamp(d["expiry_date"]).date() - today).days
        except (KeyError, ValueError, TypeError):
            continue
        if dte < MIN_DTE:
            continue
        if _depth(d) < MIN_DEPTH_CONTRACTS:
            continue
        delta = _bsm(d, "delta")
        if delta is None:
            continue
        usable.append((dte, abs(abs(delta) - TARGET_ABS_DELTA), d))
    if not usable:
        return None
    front = min(u[0] for u in usable)
    on_front = [u for u in usable if u[0] == front]
    return min(on_front, key=lambda u: (u[1], u[2]["strike"]))[2]


def build_candidate(underlying: str, direction: str, *, thesis_id: str,
                    now, known_from, chain: list | None = None
                    ) -> OptionExpressionCandidate | None:
    """One real, fully-priced directional candidate -- or None, with the
    engine left to record why nothing was offered."""
    import pandas as pd
    chain = chain if chain is not None else load_chain(underlying, now=now)
    pick = select_directional(chain, direction, now=now)
    if pick is None:
        return None

    bid, ask = float(pick["market_bid"]), float(pick["market_ask"])
    mid = (bid + ask) / 2.0
    spread = ask - bid
    strike = float(pick["strike"])
    is_call = pick["option_type"] == "call"
    expr_type = "LONG_CALL" if is_call else "LONG_PUT"
    breakeven = strike + mid if is_call else strike - mid
    dte = (pd.Timestamp(pick["expiry_date"]).date()
           - pd.Timestamp(now).tz_convert("UTC").date()).days

    return OptionExpressionCandidate(
        expression_type=expr_type,
        underlying_thesis_id=thesis_id,
        known_from=str(pd.Timestamp(known_from)),
        entry_structure=f"BUY 1x {underlying} {pick['expiry_date']} "
                        f"{strike:g} {'C' if is_call else 'P'} @ mid",
        expiry=pick["expiry_date"],
        strikes=(strike,),
        legs=((expr_type, 1, pick["symbol"]),),
        net_debit_or_credit=round(-mid, 4),
        max_loss=round(mid * 100 + FEES_PER_CONTRACT, 2),
        max_gain_if_defined=None,        # long single: unbounded/undefined
        initial_delta=_bsm(pick, "delta"),
        gamma=_bsm(pick, "gamma"),
        theta=_bsm(pick, "theta"),
        vega=_bsm(pick, "vega"),
        spread_cost=round(spread * 100, 2),
        estimated_slippage=round(spread * 100 / 2, 2),
        fees=FEES_PER_CONTRACT,
        capital_required=round(mid * 100 + FEES_PER_CONTRACT, 2),
        risk_capital_required=round(mid * 100 + FEES_PER_CONTRACT, 2),
        thesis_horizon=f"{dte}DTE",
        break_even=(round(breakeven, 4),),
        surface_context=f"iv_mid={((pick.get('iv') or {}).get('iv_mid'))}",
        liquidity_context=f"depth={_depth(pick)} "
                          f"spread_pct={round(spread / mid, 4) if mid else None}",
        data_quality=pick.get("state_quality", "UNKNOWN"),
        research_mechanism_ids=("OPT-001-DIRECTIONAL-CONVEXITY",),
        as_of=str(pd.Timestamp(now)))


def build_surface_for(underlying: str, pick: dict, chain: list, *,
                      now, known_from):
    """A real OptionSurfaceState for the picked contract's expiry, from
    the same canonical records: quoted spread, size-based depth, ATM IV.
    volume/open_interest are honestly NO_SUPPORT -- the canonical feed
    does not carry them (yet); depth alone satisfies the engine's
    liquidity gate when genuinely present."""
    bid, ask = float(pick["market_bid"]), float(pick["market_ask"])
    mid = (bid + ask) / 2.0
    spot = pick.get("spot")
    same_exp = [d for d in chain
                if d.get("expiry_date") == pick.get("expiry_date")
                and isinstance(d.get("iv"), dict)
                and d["iv"].get("iv_mid") is not None and spot]
    atm = min(same_exp,
              key=lambda d: abs(float(d["strike"]) / float(spot) - 1.0)
              ) if same_exp else None
    lq = pick.get("live_quality") or {}
    return build_surface(
        underlying, pick["expiry_date"], known_from=known_from, now=now,
        values={
            "atm_iv": (atm["iv"]["iv_mid"] if atm else None),
            "spread_dollars": round(ask - bid, 4),
            "spread_pct": (round((ask - bid) / mid, 4) if mid else None),
            "depth": _depth(pick) or None,
        })
