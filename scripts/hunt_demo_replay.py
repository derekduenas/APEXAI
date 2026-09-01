"""ACCEPTANCE DEMO — the unified organism hunting, on one honest
replay day.

Replays AAPL 2023-02-03 (the sanctioned engineering demo event: AMC
report 2023-02-02, negative surprise, reaction session 2023-02-03)
through the FULL loop:

  Part XXVI   hunt tick at the open decision point
  Part XXVII  advance the clock -> re-underwrite -> position vs new
              opportunity competition
  Part XXVIII resolve -> attribute -> baseline comparison -> demo
              book + demo experience graph

ENGINEERING DEMO, NOT EVIDENCE. Every artifact goes to
results/organism/demo/ -- the production paper book, the Lane-A
ledgers and the experience graph are never written. The realized
outcome is quoted from exports/replay_inputs.jsonl checkpoints.

decision_power: SHADOW_REPLAY_DEMO.
"""
from __future__ import annotations

import json
from pathlib import Path

from apex.governance.chain_ledger import chain_append
from apex.organism import experience, hunt

DEMO = Path("results/organism/demo")
DEMO_BOOK = DEMO / "demo_book.jsonl"
DEMO_TICKS = DEMO / "demo_hunt_ticks.jsonl"
DEMO_GRAPH = DEMO / "demo_experience_graph.jsonl"

SYM, SESSION = "AAPL", "2023-02-03"


REPORT_DATE = "2023-02-02"


def load_event() -> dict:
    for line in Path("exports/replay_inputs.jsonl").open():
        e = json.loads(line)
        if e["symbol"] == SYM and e["session"] == SESSION:
            break
    else:
        raise SystemExit("demo event not found in replay_inputs")
    for line in Path("exports/earnings_events_raw.jsonl").open():
        r = json.loads(line)
        if r["symbol"] == SYM and r["report_date"] == REPORT_DATE:
            e["report_date"] = REPORT_DATE
            e["eps_estimate"] = float(r["eps_estimate"])
            e["eps_actual"] = float(r["eps_actual"])
            return e
    raise SystemExit("demo event not found in raw corpus")


def main() -> None:
    DEMO.mkdir(parents=True, exist_ok=True)
    for p in (DEMO_BOOK, DEMO_TICKS, DEMO_GRAPH):
        if p.exists():
            p.unlink()
    e = load_event()
    rt = e.get("observed_rt_bps") or 10.0

    event = {"symbol": SYM, "report_date": e["report_date"],
             "timing": "pm", "known_from": f"{SESSION}T09:30:00-05:00",
             "reaction_session": SESSION,
             "eps_estimate": e.get("eps_estimate"),
             "eps_actual": e.get("eps_actual")}

    # ---------------- Part XXVI: the opening hunt tick
    t1 = hunt.tick(as_of=f"{SESSION}T09:35:00-05:00", subject=SYM,
                   event=event, rt_cost_bps=rt,
                   short_allowed=False, ledger=DEMO_TICKS)
    print("=" * 64)
    print("PART XXVI -- OPENING HUNT TICK")
    print("=" * 64)
    print(hunt.render(t1))

    # demo funding decision mirrors the tick (demo book only)
    decision = t1["final"]
    chain_append(DEMO_BOOK, {
        "kind": "demo_decision", "session": SESSION, "symbol": SYM,
        "decision": decision, "why": t1["why"],
        "expression": (t1.get("best_physical") or {}).get(
            "best_expression", "CASH"),
        "expected_net_bps": (t1.get("best_physical") or {}).get(
            "expected_net_bps", "NOT_ESTIMABLE"),
        "known_from": t1["as_of"],
        "decision_power": "SHADOW_REPLAY_DEMO"})

    # ---------------- Part XXVII: advance clock, re-underwrite
    print()
    print("=" * 64)
    print("PART XXVII -- RE-UNDERWRITE AT +5m AND +15m")
    print("=" * 64)
    for cp in ("+5m", "+15m"):
        realized = e["short_pnl_bps"].get(cp)
        remaining = (43.9 - 38.6) if cp == "+5m" else "NOT_ESTIMABLE"
        rec = {"kind": "demo_reunderwrite", "checkpoint": cp,
               "session": SESSION, "symbol": SYM,
               "short_pnl_so_far_bps": realized,
               "sealed_decay_note": "sealed decay curve: open 84.3 "
                   "-> +1m 52.2 -> +5m 38.6 -> +15m 43.9 gross "
                   "(cohort means, not this event)",
               "expected_remaining_edge_bps": remaining,
               "new_opportunities_at_tick": 0,
               "competition": "position vs CASH only (no rival "
                              "opportunity arrived)",
               "management": "HOLD_PER_SEALED_RULES -- static "
                             "horizon; no dynamic authority exists",
               "decision_power": "SHADOW_REPLAY_DEMO"}
        chain_append(DEMO_BOOK, rec)
        print(f"{cp}: short P&L so far {realized} bps gross; "
              f"management: HOLD_PER_SEALED_RULES; no stale opinion "
              f"kept authority -- the sealed horizon rule is the "
              f"authority")

    # ---------------- Part XXVIII: resolve, attribute, learn
    print()
    print("=" * 64)
    print("PART XXVIII -- RESOLUTION, ATTRIBUTION, LEARNING")
    print("=" * 64)
    # this corpus's deepest checkpoint is +15m; labeled honestly
    close_gross = e["short_pnl_bps"].get("+15m")
    net = (close_gross - rt) if isinstance(close_gross,
                                           (int, float)) else None
    dumb_always_fade_net = net  # the dumb rule takes the same trade
    was_attack = decision == "ATTACK_READY_SHADOW"
    monster_net = net if was_attack else 0.0

    thesis_dir = (t1.get("best_physical") or {}).get("direction")
    failure = ("THESIS_WRONG" if isinstance(net, (int, float))
               and net < 0 and thesis_dir == "SHORT"
               else "NONE" if isinstance(net, (int, float))
               else "NOT_ESTIMABLE")
    outcome = {"kind": "demo_outcome", "session": SESSION,
               "symbol": SYM,
               "short_gross_bps_at_plus15m": close_gross,
               "resolution_note": "corpus carries open/+1m/+5m/"
                                  "+15m/10:00; +15m is the deepest",
               "rt_cost_bps": rt, "short_net_bps": net,
               "monster_decision": decision,
               "monster_net_bps": monster_net,
               "dumb_ALWAYS_PM_FADE_net_bps": dumb_always_fade_net,
               "monster_minus_dumb_bps": round(
                   monster_net - dumb_always_fade_net, 1)
               if isinstance(net, (int, float)) else "NOT_ESTIMABLE",
               "failure_class": failure,
               "attribution": {
                   "physical_thesis": ("WRONG (stock rallied)"
                                       if isinstance(net, (int,
                                                           float))
                                       and net < 0 else "RIGHT"),
                   "expression": "SHORT unavailable at broker; "
                                 "option quotes absent historically "
                                 "-> CASH was the executable truth",
                   "arena_rank": "consistent with realized outcome"
                   if (isinstance(net, (int, float)) and net < 0
                       and not was_attack) else "see monster_net"},
               "law": "the original decision is never rewritten",
               "decision_power": "SHADOW_REPLAY_DEMO"}
    chain_append(DEMO_BOOK, outcome)
    print(json.dumps({k: outcome[k] for k in
                      ("short_gross_bps_at_plus15m", "short_net_bps",
                       "monster_decision", "monster_net_bps",
                       "dumb_ALWAYS_PM_FADE_net_bps",
                       "monster_minus_dumb_bps", "failure_class")},
                     indent=1))

    # experience graph (DEMO graph; production untouched)
    res = experience.rebuild(
        sources={"demo_book": DEMO_BOOK, "demo_ticks": DEMO_TICKS},
        graph=DEMO_GRAPH)
    print(f"experience graph: {res['nodes']} nodes -> {DEMO_GRAPH}")
    known = experience.as_known_at(
        f"{SESSION}T12:00:00-05:00", symbol=SYM, graph=DEMO_GRAPH)
    print(f"as_known_at 12:00 ET returns {len(known)} node(s) -- "
          f"the close outcome is NOT among them"
          if not any(n["record"].get("kind") == "demo_outcome"
                     for n in known)
          else "FENCE VIOLATION -- outcome visible before close")


if __name__ == "__main__":
    main()
