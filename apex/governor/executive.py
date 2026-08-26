"""THE EXECUTIVE LOOP — diagnose, repair, propose.

Ordinary code already handles "heartbeat stale -> restart". The
Governor exists for the other thing:

    "Options isn't scanning. Its dependencies are healthy. Memory is
     fine. The release is valid. It restarted twice and exits after
     universe initialization. What changed?"

That is hypothesis formation over heterogeneous evidence, and it is
where an LLM earns its place. This module gives that reasoning a
disciplined shape: observations in, ranked hypotheses out, each with
the evidence that supports it, the observation that would falsify it,
and the Tier-1 repair it implies.

A hypothesis with no falsifier is refused. An executive that cannot
say what would prove it wrong is not diagnosing, it is narrating.

Tier-3 findings leave here as PROPOSALS -- structured documents with
assembled evidence, addressed to the operator. There is deliberately
no `apply()`.

decision_power: TIER1_OPERATIONAL.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from apex.governance.chain_ledger import chain_append
from apex.governor.authority import (AuthorityViolation, authorize,
                                     tier_of)

INCIDENTS = Path("results/governor/incidents.jsonl")
PROPOSALS = Path("results/governor/proposals.jsonl")


class ExecutiveViolation(RuntimeError):
    pass


@dataclass
class Hypothesis:
    """A candidate explanation for an operational failure."""
    statement: str
    supporting_evidence: tuple
    falsifier: str
    implied_repair: str | None = None
    confidence: str = "UNKNOWN"

    def __post_init__(self):
        if not self.falsifier:
            raise ExecutiveViolation(
                f"hypothesis {self.statement!r} has no falsifier. An "
                f"executive that cannot say what would prove it wrong "
                f"is narrating, not diagnosing")
        if not self.supporting_evidence:
            raise ExecutiveViolation(
                f"hypothesis {self.statement!r} cites no evidence")
        if self.implied_repair is not None:
            t = tier_of(self.implied_repair)
            if t != "TIER1_OPERATIONAL":
                raise ExecutiveViolation(
                    f"hypothesis implies {self.implied_repair!r} "
                    f"({t}), which the Governor may not execute. A "
                    f"diagnosis may not smuggle a trading change in "
                    f"as a repair")


@dataclass
class Diagnosis:
    subject: str
    symptom: str
    hypotheses: list = field(default_factory=list)

    def as_record(self) -> dict:
        ranked = sorted(
            self.hypotheses,
            key=lambda h: {"HIGH": 0, "MEDIUM": 1, "LOW": 2,
                           "UNKNOWN": 3}.get(h.confidence, 3))
        return {"kind": "governor_diagnosis", "subject": self.subject,
                "symptom": self.symptom,
                "hypotheses": [{"statement": h.statement,
                                "supporting_evidence":
                                    list(h.supporting_evidence),
                                "falsifier": h.falsifier,
                                "implied_repair": h.implied_repair,
                                "confidence": h.confidence}
                               for h in ranked],
                "law": "every hypothesis carries the observation that "
                       "would kill it",
                "decision_power": "TIER1_OPERATIONAL"}


def act(*, action: str, target: str, reason: str,
        diagnosis: dict | None = None, dry_run: bool = False) -> dict:
    """Take one authorized operational action, with a durable record.

    Refusals are recorded too. A Governor that quietly declines is
    indistinguishable from one that never noticed."""
    try:
        grant = authorize(action, target=target)
    except AuthorityViolation as e:
        rec = {"kind": "governor_action_refused", "action": action,
               "target": target, "reason": reason, "refusal": str(e),
               "at": datetime.now(timezone.utc).isoformat(),
               "decision_power": "TIER1_OPERATIONAL"}
        INCIDENTS.parent.mkdir(parents=True, exist_ok=True)
        chain_append(INCIDENTS, rec)
        raise
    rec = {"kind": "governor_action", "action": action,
           "target": target, "reason": reason, "grant": grant,
           "diagnosis": diagnosis, "dry_run": dry_run,
           "at": datetime.now(timezone.utc).isoformat(),
           "decision_power": grant["tier"]}
    INCIDENTS.parent.mkdir(parents=True, exist_ok=True)
    chain_append(INCIDENTS, rec)
    return rec


def propose(*, change: str, rationale: str, evidence: dict,
            expected_effect: str, risk_if_wrong: str,
            falsifier: str) -> dict:
    """Assemble a TIER-3 proposal for the operator. NEVER applies it.

    This is the Governor's only route to a trading change, and it
    ends in a document. The absence of an `apply()` in this module is
    the control -- an executive that decided to promote an edge would
    find nothing to call."""
    t = tier_of(change) if change in _known(change) else \
        "TIER3_PRODUCTION_TRADING"
    if not falsifier:
        raise ExecutiveViolation(
            "a proposal without a falsifier is advocacy")
    for field_name, val in (("rationale", rationale),
                            ("expected_effect", expected_effect),
                            ("risk_if_wrong", risk_if_wrong)):
        if not val:
            raise ExecutiveViolation(f"proposal missing {field_name}")
    rec = {"kind": "governor_proposal", "change": change, "tier": t,
           "status": "AWAITING_OPERATOR",
           "rationale": rationale, "evidence": evidence,
           "expected_effect": expected_effect,
           "risk_if_wrong": risk_if_wrong, "falsifier": falsifier,
           "applied": False,
           "law": "the Governor proposes with evidence; only the "
                  "operator disposes. There is no apply() in this "
                  "module, by construction",
           "at": datetime.now(timezone.utc).isoformat(),
           "decision_power": "NONE_PROPOSAL_ONLY"}
    PROPOSALS.parent.mkdir(parents=True, exist_ok=True)
    chain_append(PROPOSALS, rec)
    return rec


def _known(name: str) -> tuple:
    from apex.governor.authority import CATALOG
    return tuple(CATALOG) if name in CATALOG else ()


def executive_summary(*, scorecard: dict, reconciliation: dict,
                      diagnoses: list, actions: list,
                      proposals: list) -> dict:
    """What the Governor did today and what it wants from a human."""
    return {"kind": "governor_executive_summary",
            "session": scorecard.get("session"),
            "kpi_verdict": scorecard.get("verdict"),
            "kpi_failed": scorecard.get("failed"),
            "runtime_verdict": reconciliation.get("verdict"),
            "missing_services": reconciliation.get("missing"),
            "diagnoses": len(diagnoses),
            "tier1_actions": [a["action"] for a in actions],
            "proposals_awaiting_operator": [p["change"]
                                            for p in proposals],
            "nothing_was_applied_to_v1": True,
            "decision_power": "TIER1_OPERATIONAL"}
