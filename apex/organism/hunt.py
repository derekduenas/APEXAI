"""THE HUNT — one tick of the unified hunting organism.

    STATE -> ALPHA MARKET -> BEST PHYSICAL -> EXPRESSIONS
          -> ARENA (vs CASH) -> RISK KERNEL -> DECISION
          -> OPEN-POSITION COMPETITION -> SEALED TICK

WHAT THIS IS: the organism's perception-decision cycle made callable
as one function. It COMPOSES organs that already exist -- expert
registry, universal state, Monster consult, Capital Arena, Risk
Kernel, paper book -- and seals what it saw and decided.

WHAT THIS IS NOT: a funding path. The live allocator
(organism_service -> allocator.allocate) remains the ONLY road to the
paper book, and the frozen Lane-A combat experiment is consulted
READ-ONLY: this module never writes to any Lane-A ledger. Constant
attention is not constant trading; TRADES = 0 is a correct output.

decision_power: SHADOW_COUNTERFACTUAL_ONLY.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from apex.capital.arena import (INDEX_FAMILY, PortfolioState, compete)
from apex.governance.chain_ledger import chain_append
from apex.organism import book, expert_registry, market_state
from apex.organism import risk_kernel
from apex.organism.risk_certificate import certify
from apex.organism.candidate import arena_candidate

TICKS = Path("results/organism/hunt_ticks.jsonl")

FINAL_STATES = ("ATTACK_READY_SHADOW", "WATCH", "NO_TRADE")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _alpha_market(*, as_of, event=None, rt_cost_bps=None,
                  put_quotes=None, short_allowed=False) -> dict:
    """Query every family. ACTIVE experts with a consult surface are
    consulted; everything else reports its honest status. The Lane-A
    event experts are PURE functions -- consulting them writes
    nothing."""
    table, consults = {}, {}
    for e in expert_registry.roster():
        row = {"status": e.status, "job": e.economic_job,
               "note": e.note}
        table.setdefault(e.family, {})[e.expert_id] = row

    if event is not None:
        try:
            from apex.monster import consult as monster_consult
            from apex.monster.event_expert import EventRecord
            ev = EventRecord(**{"consensus_provenance":
                                "CALLER_SUPPLIED", **event})
            consults["EVENT_INFORMATION"] = monster_consult.consult(
                ev, rt_cost_bps=rt_cost_bps,
                short_allowed=short_allowed, put_quotes=put_quotes)
        except Exception as err:                        # noqa: BLE001
            consults["EVENT_INFORMATION"] = {
                "status": "CONSULT_FAILED",
                "why": f"{type(err).__name__}: {err}"}
    else:
        consults["EVENT_INFORMATION"] = {
            "status": "NO_EVENT_IN_SCOPE",
            "why": "no causally valid event supplied at this tick"}

    consults["FORCED_FLOW_BTC"] = {
        "status": "SLEEVE_AUTONOMOUS",
        "why": "BTC predator decides inside its own live paper loop; "
               "its attacks reach capital via the allocator drain"}
    return {"table": table, "consults": consults}


def _open_position_competition(st: dict, *, as_of: str) -> list:
    """Open capital must keep competing. For each open position ask:
    expected REMAINING after-cost edge vs exit-to-cash. Where the
    owning expert cannot re-quote remaining edge, the honest answer is
    NOT_ESTIMABLE + the static invalidation/horizon rules -- never an
    invented number. Static catastrophe stops remain untouched."""
    out = []
    for p in st.get("positions", []):
        payload = p.get("sleeve_payload") or {}
        out.append({
            "candidate_id": p["candidate_id"],
            "sleeve": p["sleeve"], "symbol": p["symbol"],
            "remaining_edge_bps": "NOT_ESTIMABLE",
            "why": "no governed re-quote surface for this sleeve at "
                   "tick time; position is governed by its sealed "
                   "horizon/invalidation, not by a fresh opinion",
            "horizon": payload.get("horizon",
                                   payload.get("expected_horizon",
                                               "UNKNOWN")),
            "action": "HOLD_PER_SEALED_RULES",
            "law": "a position is not protected because it exists; "
                   "it is held only while its sealed rules say so"})
    return out


def tick(*, as_of: str, subject: str | None = None, event=None,
         rt_cost_bps=None, put_quotes=None, short_allowed=False,
         declared_risk: float = 300.0,
         ledger: Path | None = None, seal: bool = True) -> dict:
    """One full hunting cycle. Pure read + one sealed tick record."""
    state = market_state.compose(as_of=as_of, symbol=subject)
    market = _alpha_market(as_of=as_of, event=event,
                           rt_cost_bps=rt_cost_bps,
                           put_quotes=put_quotes,
                           short_allowed=short_allowed)

    # ---- best physical opportunity from the consults
    best, final, why = None, "NO_TRADE", []
    ev_consult = market["consults"].get("EVENT_INFORMATION", {})
    thesis = ev_consult.get("physical_thesis") if isinstance(
        ev_consult, dict) else None
    best_expr = ev_consult.get("best_expression", "CASH") \
        if isinstance(ev_consult, dict) else "CASH"
    arena_out, kernel_out = None, None
    if isinstance(thesis, dict) and best_expr != "CASH":
        best = {"mechanism": "EVENT_INFORMATION",
                "subject": ev_consult.get("subject"),
                "direction": thesis.get("direction", "UNKNOWN"),
                "best_expression": best_expr, **thesis}
        # counterfactual arena vs the REAL book state (read-only)
        try:
            st = book.state()
            env = {"kind": "opportunity_candidate", "sleeve": "HUNT",
                   "candidate_id": f"hunt_{subject}_{as_of[:19]}",
                   "symbol": best.get("subject") or subject
                   or "UNKNOWN",
                   "direction": best.get("direction", "UNKNOWN"),
                   "expression": best_expr,
                   "declared_risk": declared_risk,
                   "known_from": as_of, "event_time": as_of,
                   "prospective": True,
                   "sleeve_payload": {"edge_pedigree":
                                      "PROSPECTIVE_THIN",
                                      "entry_quality": "GOOD"},
                   "decision_power": "NONE"}
            pf = PortfolioState(
                available_capital=st["available_capital"],
                open_positions=[{**p, "declared_risk":
                                 p["funded_risk"],
                                 "beta_family": INDEX_FAMILY.get(
                                     p["symbol"], "UNKNOWN")}
                                for p in st["positions"]])
            arena_out = compete(candidates=[arena_candidate(env)],
                                portfolio=pf)
            d = arena_out["decisions"][0]
            if d["action"] in ("FUND", "PARTIALLY_FUND"):
                fam = INDEX_FAMILY.get(env["symbol"], "UNKNOWN")
                kernel_out = risk_kernel.check(
                    certificate=certify(
                        expression=env["expression"],
                        direction=env["direction"],
                        declared_risk=declared_risk,
                        sleeve_payload=env.get("sleeve_payload")),
                    expression=env["expression"],
                    direction=env["direction"],
                    sleeve_payload=env.get("sleeve_payload"),
                    open_certified_risk=st["open_certified_risk"],
                    declared_risk=declared_risk,
                    symbol=env["symbol"], beta_family=fam,
                    open_risk=st["open_risk"],
                    same_underlying_risk=st["risk_by_symbol"].get(
                        env["symbol"], 0.0),
                    same_family_risk=st["risk_by_family"].get(
                        fam, 0.0),
                    session_realized_pnl=st["session_realized_pnl"],
                    available_capital=st["available_capital"])
                if kernel_out["approved"]:
                    final = ("ATTACK_READY_SHADOW"
                             if env["expression"] != "CASH"
                             else "WATCH")
                    why.append(f"arena {d['action']}; kernel "
                               f"approved; expression "
                               f"{env['expression']}")
                else:
                    final = "NO_TRADE"
                    why += kernel_out["refusals"]
            else:
                final = "NO_TRADE"
                why += d["reasons"]
        except Exception as err:                        # noqa: BLE001
            final = "NO_TRADE"
            why.append(f"FAIL_CLOSED: {type(err).__name__}: {err}")
    else:
        why.append("no expert produced an attack-class opportunity "
                   "at this tick; cash has zero loss, zero friction "
                   "and full optionality")

    try:
        open_comp = _open_position_competition(book.state(),
                                               as_of=as_of)
    except Exception as err:                            # noqa: BLE001
        open_comp = [{"status": "UNKNOWN",
                      "why": f"book unavailable: "
                             f"{type(err).__name__}"}]

    rec = {"kind": "hunt_tick", "as_of": as_of,
           "subject": subject or "MARKET",
           "tick_utc": _now(),
           "state": state,
           "alpha_market": market,
           "best_physical": best,
           "arena": arena_out, "risk_kernel": kernel_out,
           "final": final, "why": why,
           "open_position_competition": open_comp,
           "law": "TRADES = 0 is a correct output; this tick funds "
                  "nothing and touches no Lane-A ledger",
           "decision_power": "SHADOW_COUNTERFACTUAL_ONLY"}
    if seal:
        chain_append(ledger or TICKS, rec)
    return rec


def render(t: dict) -> str:
    """The operator's hunt card (Part XXVI shape), from one tick."""
    s = t["state"]
    reg = s["REGIME"].get("value", s["REGIME"])
    lines = [f"TIME: {t['as_of']}",
             f"SUBJECT: {t['subject']}",
             f"MARKET / REGIME: {json.dumps(reg)}",
             "ALPHA MARKET:"]
    for fam, experts in sorted(t["alpha_market"]["table"].items()):
        for eid, row in experts.items():
            lines.append(f"  {fam:22s} {eid:32s} {row['status']}")
    cons = t["alpha_market"]["consults"].get("EVENT_INFORMATION", {})
    if isinstance(cons, dict) and cons.get("experts"):
        lines.append("EVENT CONSULT:")
        for name, ex in cons["experts"].items():
            lines.append(f"  {name}: {ex.get('state', ex)}")
        lines.append(f"  agreement: "
                     f"{cons.get('mechanism_agreement')}")
    bp = t.get("best_physical")
    if bp:
        lines.append(f"BEST PHYSICAL: {bp.get('mechanism')} "
                     f"{bp.get('direction')} net "
                     f"{bp.get('expected_net_bps')} bps")
    elif isinstance(cons, dict) and isinstance(
            cons.get("physical_thesis"), dict):
        th = cons["physical_thesis"]
        lines.append(f"BEST PHYSICAL: thesis exists "
                     f"({th.get('direction')} net "
                     f"{th.get('expected_net_bps')} bps) but NO "
                     f"executable expression preserved it -> CASH")
    else:
        lines.append("BEST PHYSICAL: NONE")
    if t.get("arena"):
        d = t["arena"]["decisions"][0]
        lines.append(f"ARENA: {d['action']} "
                     f"({'; '.join(d['reasons'][:1])})")
    if t.get("risk_kernel"):
        lines.append(f"RISK KERNEL: approved="
                     f"{t['risk_kernel']['approved']}")
    lines.append("OPEN POSITIONS:")
    for p in t["open_position_competition"]:
        lines.append(f"  {p.get('symbol', '?')}: "
                     f"{p.get('action', p.get('status'))}")
    lines.append(f"FINAL: {t['final']}")
    lines.append(f"WHY: {'; '.join(t['why'])}")
    return "\n".join(lines)
