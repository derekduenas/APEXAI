"""CATALYST CONTEXT — the causal query surface for decision-makers.

This is the change from decorative to operational: a sleeve or the
allocator asks "what did Catalyst know about X as of T?" and receives
governed evidence -- never a verdict, never a direction to trade, and
never anything first seen after T.

    CATALYST != SIGNAL.

It informs thesis support, event risk, uncertainty and capital
reservation. The specialist still decides whether its thesis survives,
and the arena still decides funding.

decision_power: ACTIVE_DECISION_INTELLIGENCE -- consulted, never
obeyed; it cannot authorize, block, size or direct anything.
"""
from __future__ import annotations

import json
from pathlib import Path

EVENT_LEDGER = Path("results/catalyst/events.jsonl")
REACTION_LEDGER = Path("results/catalyst/reactions.jsonl")

AUTHORITY = "ACTIVE_DECISION_INTELLIGENCE"

ENVIRONMENTS = ("QUIET", "NORMAL", "ELEVATED", "EVENT_HEAVY", "SHOCK")


def _rows(path: Path) -> list:
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def context(*, symbol: str, as_of: str,
            events_ledger: Path | None = None,
            reactions_ledger: Path | None = None) -> dict:
    """Everything Catalyst causally knew about `symbol` at `as_of`.

    THE CAUSAL FENCE IS THE ONLY HARD RULE HERE: an event whose
    known_from is later than as_of does not exist for this query,
    however relevant it later proves. Hindsight enters research through
    exactly this kind of doorway, so the filter is on known_from and
    nothing else.
    """
    as_of = str(as_of)
    evs = [e for e in _rows(events_ledger or EVENT_LEDGER)
           if e.get("kind") == "catalyst_event"
           and str(e.get("known_from", "9999")) <= as_of
           and symbol in (e.get("affected_symbols") or [])]

    # newest interpretation of each event wins; the ledger is append-only
    latest = {}
    for e in evs:
        latest[e["event_id"]] = e
    evs = list(latest.values())

    rx = {r["event_id"]: r for r in _rows(reactions_ledger
                                          or REACTION_LEDGER)
          if r.get("kind") == "catalyst_reaction"
          and str(r.get("known_from", "9999")) <= as_of}

    hi = [e for e in evs if e.get("importance") in ("CRITICAL", "HIGH")]
    expectations = [e.get("directional_expectation", "UNKNOWN")
                    for e in hi]
    pos = expectations.count("POSITIVE")
    neg = expectations.count("NEGATIVE")

    support = "CATALYST_UNKNOWN"
    if hi:
        if pos and not neg:
            support = "CATALYST_POSITIVE"
        elif neg and not pos:
            support = "CATALYST_NEGATIVE"
        elif pos and neg:
            support = "CATALYST_MIXED"

    disagreements = [rx[e["event_id"]] for e in evs
                     if e["event_id"] in rx
                     and rx[e["event_id"]].get("disagreement")]

    env = ("SHOCK" if any(e.get("importance") == "CRITICAL"
                          for e in evs)
           else "EVENT_HEAVY" if len(hi) >= 3
           else "ELEVATED" if len(hi) >= 1
           else "NORMAL" if evs else "QUIET")

    return {"kind": "catalyst_context", "symbol": symbol,
            "as_of": as_of,
            "events_known": len(evs),
            "high_importance": len(hi),
            "directional_support": support,
            "environment": env,
            "reaction_disagreements": len(disagreements),
            "verified_events": sum(1 for e in evs
                                   if e.get("verification") == "VERIFIED"),
            "unverified_events": sum(1 for e in evs
                                     if e.get("verification")
                                     != "VERIFIED"),
            "sample_headlines": [e["headline"][:90] for e in hi[:3]],
            "law": "consulted, never obeyed: no verdict, no direction, "
                   "no size, and nothing first known after as_of",
            "decision_power": AUTHORITY}


def alignment(*, direction: str, ctx: dict) -> str:
    """Descriptive relation between a sleeve thesis and catalyst
    support. THESIS_CONFLICT is information, not a veto: the specialist
    decides whether its thesis survives the disagreement."""
    s = ctx.get("directional_support", "CATALYST_UNKNOWN")
    if s == "CATALYST_UNKNOWN":
        return "CATALYST_UNKNOWN"
    if s == "CATALYST_MIXED":
        return "CATALYST_MIXED"
    agrees = ((direction == "LONG" and s == "CATALYST_POSITIVE")
              or (direction == "SHORT" and s == "CATALYST_NEGATIVE"))
    return "CATALYST_ALIGNED" if agrees else "CATALYST_OPPOSED"
