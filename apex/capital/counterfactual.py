"""THE SHADOW LEDGER — a counterfactual is only worth anything if it
was sealed before the outcome existed.

For every baseline ATTACK_READY event this records two things side by
side: what the incumbent Predator actually did, and what Capital Arena
would have done. Both are written BEFORE the market answers. The
outcome is APPENDED later against the sealed decision, never merged
into it.

That ordering is the entire experiment. A portfolio manager graded on
decisions it made after seeing the result is not a portfolio manager,
it is a narrator with a spreadsheet.

WHAT THIS MAY EVENTUALLY SHOW -- and only over many independent
sessions:

    did refusing redundancy avoid correlated drawdown?
    did preferring cash beat deploying it?
    did the arena give up more than it saved?

Superiority is not declarable from small n, and the comparison refuses
to summarise itself until the sample earns it.

decision_power: SHADOW_COUNTERFACTUAL_ONLY.
"""
from __future__ import annotations

import json
import statistics
from datetime import datetime, timezone
from pathlib import Path

from apex.governance.chain_ledger import chain_append

LEDGER = Path("results/capital/shadow_ledger.jsonl")

MIN_SESSIONS_FOR_COMPARISON = 10


class CounterfactualViolation(RuntimeError):
    pass


def seal_decision(*, session: str, candidate_id: str, symbol: str,
                  baseline_action: str, shadow_action: str,
                  reasons: list, declared_risk: float,
                  portfolio_snapshot: dict,
                  ledger: Path | None = None) -> dict:
    """Seal both decisions BEFORE the outcome exists."""
    if not reasons:
        raise CounterfactualViolation(
            "a shadow decision without reasons cannot be studied later")
    rec = {"kind": "shadow_capital_decision", "session": session,
           "candidate_id": candidate_id, "symbol": symbol,
           "baseline_action": baseline_action,
           "shadow_action": shadow_action, "reasons": reasons,
           "declared_risk": declared_risk,
           "portfolio_snapshot": portfolio_snapshot,
           "sealed_utc": datetime.now(timezone.utc).isoformat(),
           "outcome": "PENDING",
           "law": "sealed before the market answered",
           "decision_power": "SHADOW_COUNTERFACTUAL_ONLY"}
    return chain_append(ledger or LEDGER, rec)


def append_outcome(*, session: str, candidate_id: str,
                   baseline_pnl, baseline_r, ledger: Path | None = None
                   ) -> dict:
    """Attach the realised outcome to a sealed decision. APPEND ONLY --
    the sealed record is never edited."""
    rec = {"kind": "shadow_capital_outcome", "session": session,
           "candidate_id": candidate_id,
           "baseline_pnl": baseline_pnl, "baseline_r": baseline_r,
           "attached_utc": datetime.now(timezone.utc).isoformat(),
           "law": "outcome appended against a sealed decision, never "
                  "merged into it",
           "decision_power": "SHADOW_COUNTERFACTUAL_ONLY"}
    return chain_append(ledger or LEDGER, rec)


def _read(ledger: Path) -> list:
    if not ledger.exists():
        return []
    return [json.loads(l) for l in ledger.read_text().splitlines()
            if l.strip()]


def compare(ledger: Path | None = None) -> dict:
    """Baseline versus shadow, with an explicit refusal to conclude
    from a sample too small to mean anything."""
    rows = _read(ledger or LEDGER)
    decisions = [r for r in rows
                 if r.get("kind") == "shadow_capital_decision"]
    outcomes = {r["candidate_id"]: r for r in rows
                if r.get("kind") == "shadow_capital_outcome"}
    sessions = sorted({d["session"] for d in decisions})

    base_r, shadow_r, divergences = [], [], []
    for d in decisions:
        o = outcomes.get(d["candidate_id"])
        if not o or not isinstance(o.get("baseline_r"), (int, float)):
            continue
        r = o["baseline_r"]
        took_baseline = d["baseline_action"] in ("PAPER_ATTACKED",
                                                 "FUND")
        took_shadow = d["shadow_action"] in ("FUND", "PARTIALLY_FUND")
        if took_baseline:
            base_r.append(r)
        if took_shadow:
            shadow_r.append(r)
        if took_baseline != took_shadow:
            divergences.append({"candidate_id": d["candidate_id"],
                                "symbol": d["symbol"],
                                "baseline": d["baseline_action"],
                                "shadow": d["shadow_action"],
                                "realised_r": r,
                                "reasons": d["reasons"]})

    out = {"kind": "capital_counterfactual_comparison",
           "independent_sessions": len(sessions),
           "n_decisions": len(decisions),
           "n_resolved": len(base_r),
           "baseline_total_r": round(sum(base_r), 4) if base_r else 0.0,
           "shadow_total_r": round(sum(shadow_r), 4) if shadow_r else 0.0,
           "baseline_median_r": (round(statistics.median(base_r), 4)
                                 if base_r else "NOT_ESTIMABLE"),
           "shadow_median_r": (round(statistics.median(shadow_r), 4)
                               if shadow_r else "NOT_ESTIMABLE"),
           "divergences": divergences,
           "n_divergences": len(divergences),
           "decision_power": "SHADOW_COUNTERFACTUAL_ONLY"}

    if len(sessions) < MIN_SESSIONS_FOR_COMPARISON:
        out["verdict"] = "INSUFFICIENT_EVIDENCE"
        out["why"] = (
            f"{len(sessions)} independent session(s); the comparison "
            f"reports numbers but refuses a verdict below "
            f"{MIN_SESSIONS_FOR_COMPARISON}. A shadow manager that "
            f"looks better over two sessions has demonstrated nothing "
            f"except which way the tape went")
    else:
        out["verdict"] = "COMPARABLE"
        out["why"] = ("enough independent sessions to compare "
                      "descriptively -- still not a significance claim")
    return out
