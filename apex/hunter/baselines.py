"""Frozen forward baselines (protocol §6) — scored through the SAME
pipeline as playbooks, not a separate system.

Baseline records ARE decision records (kind="decision",
playbook_id="BASELINE-*"): the same dedupe, the same birth-stamped
eligibility, the same realization resolver, the same ledger. What makes
them baselines is only that their direction rules are deliberately naive.
One baseline set per watchlist symbol per session, minted at the symbol's
FIRST watchlist appearance — same first-formation-wins rule as playbooks.

Direction rules (frozen, mechanical):
  BASELINE-RANDOM        deterministic coin from sha256(date|symbol) parity
                         (reproducible by anyone, unriggable by reruns)
  BASELINE-MARKET        sign of SPY day_return at formation
  BASELINE-MOMENTUM      sign of the symbol's own r_60m
  BASELINE-RELSTRENGTH   sign of excess_market_60m
  NO-TRADE               implicit: the zero-return row, computed by the
                         scoreboard, never recorded
ALWAYS-TAKE-SCANNER-CANDIDATE is BASELINE-MOMENTUM aggregated over the
full watchlist (every candidate taken, continuation-default direction);
the scoreboard reports it as that aggregate rather than duplicating rows.

A missing input (no market state, no r_60m) skips that baseline for that
subject — fail closed, never a fabricated direction. No stops/targets:
baselines measure raw subject-horizon returns; geometry belongs to
playbooks.
"""

from __future__ import annotations

import hashlib

from apex.hunter import birth as birthlib
from apex.hunter.chartstate import ChartState
from apex.hunter.contracts import HORIZONS_MINUTES, content_hash
from apex.hunter.evidence import EvidenceClass, stamp
from apex.hunter.relstrength import RelativeStrengthState

BASELINES_VERSION = "HUNTER-BASELINES_v1"


def _sign_dir(x: float | None) -> str | None:
    if x is None or x == 0:
        return None
    return "LONG" if x > 0 else "SHORT"


def random_direction(date: str, symbol: str) -> str:
    """Deterministic 'coin': anyone can recompute it, nobody can reroll."""
    h = hashlib.sha256(f"{date}|{symbol}".encode()).digest()
    return "LONG" if h[0] % 2 == 0 else "SHORT"


def baseline_directions(date: str, symbol: str, cs: ChartState,
                        rs: RelativeStrengthState,
                        market_cs: ChartState | None) -> dict:
    return {
        "BASELINE-RANDOM": random_direction(date, symbol),
        "BASELINE-MARKET": _sign_dir(market_cs.day_return
                                     if market_cs is not None else None),
        "BASELINE-MOMENTUM": _sign_dir(cs.r_60m),
        "BASELINE-RELSTRENGTH": _sign_dir(rs.excess_market_60m),
    }


def baseline_decisions(t, date: str, watchlist_syms: tuple,
                       cs_by_symbol: dict, rs_by_symbol: dict,
                       market_cs: ChartState | None, births: dict,
                       seen_baseline_keys: set) -> list:
    """Records for every (watchlist symbol x baseline) not yet minted this
    session. Same shape as playbook decisions minus geometry."""
    deps = {n: b for n, b in births.items()
            if b["dependency_kind"] != "playbook" or n == BASELINES_VERSION}
    eligibility, reasons = birthlib.forward_eligibility(t, deps)
    bstamp = birthlib.birth_stamp(deps)
    out = []
    for sym in watchlist_syms:
        cs, rs = cs_by_symbol.get(sym), rs_by_symbol.get(sym)
        if cs is None or rs is None:
            continue
        for pid, direction in baseline_directions(
                date, sym, cs, rs, market_cs).items():
            if direction is None or (sym, pid) in seen_baseline_keys:
                continue
            seen_baseline_keys.add((sym, pid))
            out.append(stamp({
                "kind": "decision",
                "decision_id": content_hash(
                    {"t": str(t), "symbol": sym, "playbook": pid,
                     "direction": direction})[:16],
                "session_date": date, "t_utc": str(t),
                "symbol": sym, "playbook_id": pid,
                "direction": direction, "entry": cs.price,
                "stop": None, "target": None, "risk_frac": None,
                "time_stop_minutes": None,
                "invalidation": "none: baseline holds to horizon",
                "horizons_minutes": list(HORIZONS_MINUTES),
                "forward_eligibility": eligibility,
                "eligibility_reasons": list(reasons),
                **bstamp,
            }, EvidenceClass.EODHD_FORWARD_OBSERVATION))
    return out
