"""THE PROFIT SCOREBOARD — one canonical economic readout.

Reads the ledgers that already exist (paper book, allocator
decisions, Lane-A prospective ledger READ-ONLY, BTC paper ledger) and
answers the operator's Part-XXIX questions. No dashboard theater: a
metric whose counterfactual has not been recorded yet is
NOT_ESTIMABLE, not invented.

Usage: python3 scripts/organism_scoreboard.py [--root DIR]
decision_power: NONE_REPORTING.
"""
from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path


def rows(p: Path) -> list:
    if not p.exists():
        return []
    out = []
    for line in p.read_text().splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    a = ap.parse_args()
    R = Path(a.root)

    book = rows(R / "results/organism/paper_book.jsonl")
    alloc = rows(R / "results/organism/allocator_decisions.jsonl")
    lane_a = rows(R / "results/event_sprint/prospective_ledger.jsonl") \
        or rows(Path("/opt/apex-repo/results/event_sprint/"
                     "prospective_ledger.jsonl"))
    btc = rows(R / "results/btc/paper_ledger.jsonl")

    fundings = [r for r in book if r.get("kind") == "paper_funding"
                and not r.get("duplicate")]
    refusals = [r for r in book if r.get("kind") == "paper_refusal"]
    outcomes = {r["candidate_id"]: r for r in book
                if r.get("kind") == "paper_outcome"}
    voided = {r["candidate_id"] for r in book
              if r.get("kind") == "paper_funding_void"}
    fundings = [f for f in fundings
                if f["candidate_id"] not in voided]

    pnls = [outcomes[f["candidate_id"]].get("executable_pnl")
            for f in fundings if f["candidate_id"] in outcomes]
    pnls = [p for p in pnls if isinstance(p, (int, float))]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    # equity curve for drawdown (funding order)
    eq, peak, maxdd = 10_000.0, 10_000.0, 0.0
    for p in pnls:
        eq += p
        peak = max(peak, eq)
        maxdd = max(maxdd, peak - eq)

    open_risk = sum(f["funded_risk"] for f in fundings
                    if f["candidate_id"] not in outcomes)

    lane_a_watch = [r for r in lane_a
                    if r.get("kind") == "prospective_watch"]
    lane_a_resolved = [r for r in lane_a
                       if r.get("kind") == "prospective_resolution"]
    btc_windows = [r for r in btc
                   if r.get("kind") == "btc_paper_decision"]

    fam_pnl: dict = {}
    for f in fundings:
        o = outcomes.get(f["candidate_id"])
        if o and isinstance(o.get("executable_pnl"), (int, float)):
            fam_pnl[f["sleeve"]] = round(
                fam_pnl.get(f["sleeve"], 0.0)
                + o["executable_pnl"], 2)

    board = {
        "kind": "profit_scoreboard",
        "PROSPECTIVE_ALPHAS": {
            "lane_a_sealed_watches": len(lane_a_watch),
            "lane_a_resolved": len(lane_a_resolved),
            "btc_windows_sealed": len(btc_windows)},
        "ATTACKS_FUNDED": len(fundings),
        "NO_TRADES_REFUSED": len(refusals),
        "RESOLVED": len(pnls),
        "NET_PNL": round(sum(pnls), 2) if pnls else "NOT_ESTIMABLE",
        "EXPECTANCY_PER_TRADE": (round(statistics.mean(pnls), 2)
                                 if pnls else "NOT_ESTIMABLE"),
        "MEDIAN_TRADE": (round(statistics.median(pnls), 2)
                         if pnls else "NOT_ESTIMABLE"),
        "WIN_RATE": (round(len(wins) / len(pnls), 3)
                     if pnls else "NOT_ESTIMABLE"),
        "PAYOFF_RATIO": (
            round(statistics.mean(wins)
                  / abs(statistics.mean(losses)), 2)
            if wins and losses and statistics.mean(losses) != 0
            else "NOT_ESTIMABLE"),
        "MAX_DRAWDOWN": (round(maxdd, 2) if pnls
                         else "NOT_ESTIMABLE"),
        "EXPECTED_SHORTFALL": (
            round(statistics.mean(sorted(pnls)[:max(
                1, len(pnls) // 20)]), 2)
            if len(pnls) >= 20 else "NOT_ESTIMABLE"),
        "CAPITAL_UTILIZATION": {
            "open_risk": round(open_risk, 2),
            "cash_pct": round(100 * (1 - open_risk / 10_000.0), 1)},
        "ALPHA_FAMILY_CONTRIBUTION": fam_pnl or "NOT_ESTIMABLE",
        "EXPRESSION_CONTRIBUTION": "NOT_ESTIMABLE (per-expression "
            "counterfactuals accumulate via the option shadow; too "
            "few resolved)",
        "VALUE_OF_REJECTION": "NOT_ESTIMABLE prospectively "
            "(refusal counterfactuals are being recorded; historical "
            "diagnostic measured -11,832 bps for the uncertainty "
            "gate -- the successor M2 gate is on trial)",
        "VALUE_OF_SELECTION": "NOT_ESTIMABLE (needs resolved "
            "prospective cohort)",
        "VALUE_OF_EXPRESSION": "NOT_ESTIMABLE (option-vs-stock "
            "shadow pairs still accumulating)",
        "VALUE_OF_MANAGEMENT": "NOT_ESTIMABLE (no dynamic "
            "management authority exists)",
        "MONSTER_MINUS_DUMB_BASELINE": {
            "historical_sealed": "Monster $10,603 vs ALWAYS_PM_FADE "
                "$11,872 (Monster LOST by $1,269; sealed "
                "HISTORICAL-MONSTER-DIAGNOSTIC-V1-VERDICT)",
            "prospective": "PENDING -- baseline diagnostics sealed "
                "beside every allocator run since 2026-08-29"},
        "allocator_runs": len([r for r in alloc
                               if r.get("kind") == "allocation_run"]),
        "law": "these numbers decide whether APEX is becoming "
               "elite; nothing here is invented",
        "decision_power": "NONE_REPORTING",
    }
    print(json.dumps(board, indent=1))


if __name__ == "__main__":
    main()
