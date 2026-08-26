"""THE AUTHORITY SURFACE — what the Governor can actually reach.

An action that is not in this catalog cannot be taken, and the
catalog is a whitelist rather than a blocklist on purpose: a
blocklist protects against the failures someone already imagined.

Every Tier-1 action is reversible, bounded, and leaves an incident
record. Anything touching sealed evidence is refused outright, so a
disk-pressure repair can never delete the research it exists to
protect.

decision_power: TIER1_OPERATIONAL.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from apex.governor import AUTONOMOUS_TIERS, TIERS


class AuthorityViolation(RuntimeError):
    """Raised when something reaches past the Governor's ceiling."""


@dataclass(frozen=True)
class Action:
    name: str
    tier: str
    reversible: bool
    description: str
    bounded_by: str


# ------------------------------------------------------------ TIER 1
_T1 = [
    Action("restart_service", "TIER1_OPERATIONAL", True,
           "restart a supervised service that is absent or stalled",
           "max 3 attempts per phase, then SESSION_MISSED_START"),
    Action("start_missing_service", "TIER1_OPERATIONAL", True,
           "start a service the calendar says should be running",
           "roster membership; never a service off-roster"),
    Action("rotate_disposable_logs", "TIER1_OPERATIONAL", True,
           "rotate or delete logs and caches marked DISPOSABLE",
           "PROTECTED_EVIDENCE paths are refused"),
    Action("rebuild_stale_cache", "TIER1_OPERATIONAL", True,
           "rebuild a derived cache from its source of truth",
           "derived data only; never a sealed ledger"),
    Action("resume_durable_consumer", "TIER1_OPERATIONAL", True,
           "resume a shadow consumer from its checkpointed cursor",
           "cursor only moves forward"),
    Action("retry_provider", "TIER1_OPERATIONAL", True,
           "retry a failed provider call with backoff",
           "bounded retries; no credential changes"),
    Action("failover_authorized_backup", "TIER1_OPERATIONAL", True,
           "switch to a PRE-AUTHORIZED backup source or host",
           "only targets on the authorized list; no split-brain"),
    Action("isolate_resource_hog", "TIER1_OPERATIONAL", True,
           "cap or stop a non-trading process starving the host",
           "may never stop a service required by the current phase"),
    Action("record_incident", "TIER1_OPERATIONAL", True,
           "write a durable incident with evidence", "append-only"),
]

# ------------------------------------------------------------ TIER 2
_T2 = [
    Action("register_hypothesis", "TIER2_RESEARCH", True,
           "register a research hypothesis with a birth time",
           "preregistration is immutable once written"),
    Action("run_chronos_campaign", "TIER2_RESEARCH", True,
           "run a historical replay campaign",
           "HISTORICAL_REPLAY label; lockbox stays sealed"),
    Action("spawn_shadow_challenger", "TIER2_RESEARCH", True,
           "run a challenger in shadow against sealed worlds",
           "ladder ends at PAPER_REVIEW"),
    Action("run_falsification", "TIER2_RESEARCH", True,
           "attack an existing candidate", "may kill, never promote"),
    Action("request_boundary_instrumentation", "TIER2_RESEARCH", True,
           "ask V1 to RECORD an additional observation",
           "recording only; may not change any decision"),
]

# ------------------------------------------------------------ TIER 3
# Present ONLY so the catalog can name what is forbidden. None of
# these has an implementation anywhere in this package.
_T3 = [
    Action("change_gate_threshold", "TIER3_PRODUCTION_TRADING", False,
           "alter a WAIT/GOOD/geometry threshold", "PROPOSAL ONLY"),
    Action("change_position_sizing", "TIER3_PRODUCTION_TRADING", False,
           "alter risk per trade or capital allocation",
           "PROPOSAL ONLY"),
    Action("change_exit_rule", "TIER3_PRODUCTION_TRADING", False,
           "alter stop, target or resolution horizon",
           "PROPOSAL ONLY"),
    Action("add_trading_signal", "TIER3_PRODUCTION_TRADING", False,
           "introduce a new input to a live decision",
           "PROPOSAL ONLY"),
    Action("promote_edge_dna", "TIER3_PRODUCTION_TRADING", False,
           "grant a research candidate trading authority",
           "PROPOSAL ONLY"),
    Action("grant_capital_authority", "TIER3_PRODUCTION_TRADING",
           False, "move any real money", "PROPOSAL ONLY"),
]

CATALOG = {a.name: a for a in (_T1 + _T2 + _T3)}

PROTECTED_EVIDENCE = (
    "results/chronos", "results/edgeforge", "results/day1_frozen",
    "results/day1_corrected", "results/governance", "results/btc",
    "results/decision_cards", "results/commissioning",
)


def authorize(action_name: str, *, target: str = "",
              operator_approval: str | None = None) -> dict:
    """The single gate. Everything the Governor does passes here.

    Tier 3 is refused even WITH an approval string, because approval
    is the operator's act performed through their own tools -- not a
    parameter the executive can supply to itself."""
    a = CATALOG.get(action_name)
    if a is None:
        raise AuthorityViolation(
            f"{action_name!r} is not in the authority catalog. The "
            f"catalog is a whitelist: an action nobody authorized is "
            f"not available merely because nobody forbade it")
    if a.tier == "TIER3_PRODUCTION_TRADING":
        raise AuthorityViolation(
            f"{action_name!r} is TIER3_PRODUCTION_TRADING and is "
            f"LOCKED. The Governor may propose it with evidence; it "
            f"may not execute it"
            + (". An operator_approval argument does not unlock it -- "
               "approval is the operator's act, not a parameter the "
               "executive supplies to itself"
               if operator_approval else "."))
    if a.tier not in AUTONOMOUS_TIERS:
        raise AuthorityViolation(f"unknown tier {a.tier!r}")
    if action_name in ("rotate_disposable_logs", "rebuild_stale_cache",
                       "isolate_resource_hog"):
        for p in PROTECTED_EVIDENCE:
            if target and (target.startswith(p) or p in target):
                raise AuthorityViolation(
                    f"{action_name!r} refused on {target!r}: sealed "
                    f"evidence is never disposable. A disk-pressure "
                    f"repair may not delete the research it exists to "
                    f"protect")
    return {"kind": "authority_grant", "action": action_name,
            "tier": a.tier, "target": target,
            "reversible": a.reversible, "bounded_by": a.bounded_by,
            "granted_utc": datetime.now(timezone.utc).isoformat(),
            "decision_power": a.tier}


def tier_of(action_name: str) -> str:
    a = CATALOG.get(action_name)
    if a is None:
        raise AuthorityViolation(f"unknown action {action_name!r}")
    return a.tier


def catalog_report() -> dict:
    return {"kind": "authority_catalog",
            "tiers": {t: sorted(n for n, a in CATALOG.items()
                                if a.tier == t) for t in TIERS},
            "autonomous": list(AUTONOMOUS_TIERS),
            "locked": "TIER3_PRODUCTION_TRADING",
            "law": "the Tier 3 lock is structural: no function in this "
                   "package mutates a trading rule, so an executive "
                   "that decided to would find nothing to call",
            "decision_power": "TIER1_OPERATIONAL"}
