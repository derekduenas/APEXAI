"""BASELINE ARENA — complexity earns nothing on its own.

Phase 20. Every discovery competes against deliberately stupid
alternatives on the identical world set. A sophisticated candidate that
cannot beat VWAP continuation has discovered VWAP continuation with
extra steps, and the arena's job is to say so before anyone becomes
attached to it.

The most important baseline is NO_TRADE. A candidate that cannot beat
sitting still has not earned the risk, the attention, or the capital
lockup -- and flat is always available, at zero friction, with no
capacity limit.

decision_power: NONE_RESEARCH.
"""
from __future__ import annotations

import statistics

NOT_ESTIMABLE = "NOT_ESTIMABLE"

BASELINE_NAMES = ("NO_TRADE", "RANDOM_ELIGIBLE", "SIMPLE_MOMENTUM",
                  "SIMPLE_RELATIVE_STRENGTH", "VWAP_CONTINUATION",
                  "BASIC_TREND", "INCUMBENT_APEX", "STOCK_EQUIVALENT",
                  "SIMPLE_OPTION_DELTA")


class BaselineViolation(RuntimeError):
    pass


def build_baselines(*, entry: float, shares: int = 100,
                    direction: str = "LONG", seed: int = 0,
                    include: tuple = ()) -> list:
    """Construct the comparison set. Each is intentionally naive."""
    from apex.edgeforge.attack_lab import CandidateAttack
    want = include or ("NO_TRADE", "RANDOM_ELIGIBLE", "SIMPLE_MOMENTUM",
                       "VWAP_CONTINUATION", "STOCK_EQUIVALENT")
    out = []
    for name in want:
        if name not in BASELINE_NAMES:
            raise BaselineViolation(f"undeclared baseline {name!r}")
        if name == "NO_TRADE":
            out.append(CandidateAttack(
                attack_id="baseline_NO_TRADE", kind="SYNTHETIC",
                expression="NO_TRADE", params={},
                evaluator_name="no_trade", execution_pedigree="NONE"))
        elif name == "RANDOM_ELIGIBLE":
            d = "LONG" if (seed % 2 == 0) else "SHORT"
            out.append(CandidateAttack(
                attack_id="baseline_RANDOM_ELIGIBLE", kind="SYNTHETIC",
                expression="STOCK",
                params={"direction": d, "entry": entry,
                        "shares": shares},
                evaluator_name="stock",
                execution_pedigree="MODELLED_EXECUTION",
                declared_1R=entry * shares * 0.01))
        else:
            # momentum / vwap-continuation / stock-equivalent all reduce
            # to a directional stock hold at this horizon; they are kept
            # NAMED so the report says which naive idea was beaten
            out.append(CandidateAttack(
                attack_id=f"baseline_{name}", kind="SYNTHETIC",
                expression="STOCK",
                params={"direction": direction, "entry": entry,
                        "shares": shares},
                evaluator_name="stock",
                execution_pedigree="MODELLED_EXECUTION",
                declared_1R=entry * shares * 0.01))
    return out


def arena(*, candidate, baselines: list, worlds: list,
          evaluate_common, summarize_attack) -> dict:
    """Candidate vs every baseline on identical worlds."""
    run = evaluate_common(attacks=[candidate] + baselines, worlds=worlds)
    cand = summarize_attack(run, candidate)
    rows = {b.attack_id: summarize_attack(run, b) for b in baselines}

    beaten, lost_to = [], []
    cm = cand.get("median_pnl")
    cf = cand.get("favorable_world_fraction")
    for bid, s in rows.items():
        bm = s.get("median_pnl")
        if not isinstance(cm, (int, float)) or not isinstance(bm, (int, float)):
            continue
        (beaten if cm > bm else lost_to).append(bid)

    no_trade = rows.get("baseline_NO_TRADE", {})
    beats_flat = (isinstance(cm, (int, float))
                  and cm > no_trade.get("median_pnl", 0.0))

    return {"kind": "baseline_arena",
            "candidate": cand, "baselines": rows,
            "beaten": sorted(beaten), "lost_to": sorted(lost_to),
            "beats_no_trade": beats_flat,
            "verdict": ("BEATS_ALL_TESTED_BASELINES" if not lost_to
                        else "INFERIOR_TO_A_SIMPLE_BASELINE"),
            "law": "a complicated model that cannot beat a simple "
                   "baseline has not earned respect for being "
                   "complicated; failing to beat NO_TRADE means the "
                   "risk was never worth taking",
            "note": ("candidate favorable world fraction "
                     f"{cf}; flat is always available at zero friction "
                     f"with no capacity limit"),
            "decision_power": "NONE_RESEARCH"}
