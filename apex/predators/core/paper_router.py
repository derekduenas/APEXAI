"""PAPER_EXPLORATORY ROUTER -- plumbing only, authority unchanged.

Routes a canonical PredatorOpportunity to one of the terminal decisions
below. At OBSERVE authority every real actionable route REFUSES;
COMMISSIONING_TEST opportunities may exercise the plumbing so the path
is proven before it is ever needed.

    PIPELINE_STOP               upstream could not speak (data/quality)
    NO_TRADE                    a positive decision, not a failure
    PAPER_EXPLORATORY_CANDIDATE meets structure, awaiting authority
    PAPER_EXPLORATORY_APPROVED  authority granted (never at OBSERVE)
    PAPER_AUTHORIZED            separate, stronger cohort
    LIVE_INELIGIBLE             explicit: never live-promotable

THE COHORT LAW: PAPER_EXPLORATORY and PAPER_AUTHORIZED never merge.
Exploratory trades are real sealed decisions tracked like real trades,
and they are NOT edge-proof and NOT live-promotion evidence -- ever.
"""
from __future__ import annotations

from apex.predators.core.opportunity import PredatorOpportunity

ROUTES = ("PIPELINE_STOP", "NO_TRADE", "PAPER_EXPLORATORY_CANDIDATE",
          "PAPER_EXPLORATORY_APPROVED", "PAPER_AUTHORIZED",
          "LIVE_INELIGIBLE")

# the eligibility law -- PREPARED, not activated
EXPLORATORY_REQUIREMENTS = (
    "trusted upstream foundation (sleeve foundation commissioned)",
    "coherent mechanism (named, not 'unknown')",
    "supported direction (LONG or SHORT, not UNKNOWN)",
    "acceptable Attack Geometry (entry_quality GOOD or STRONG)",
    "Assassin survival (no lethal contradiction)",
    "bounded simulated loss (invalidation present)",
    "BEFORE card sealed",
    "explicit exploratory pedigree stamped",
)


class RouterRefused(RuntimeError):
    pass


def route(opp: PredatorOpportunity, *, authority_level: str,
          sleeve_foundation_commissioned: bool,
          commissioning_test: bool = False) -> dict:
    """Pure function: same inputs -> same route, no hidden state."""
    unmet = []

    if opp.data_quality in ("INVALID", "INSUFFICIENT"):
        return _r("PIPELINE_STOP", opp,
                  ["upstream data quality " + opp.data_quality],
                  commissioning_test)

    if not sleeve_foundation_commissioned:
        unmet.append("sleeve foundation not commissioned")
    if opp.mechanism in ("", "UNKNOWN", None):
        unmet.append("mechanism not named")
    if opp.direction == "UNKNOWN":
        unmet.append("direction unsupported")
    if opp.entry_quality not in ("GOOD", "STRONG"):
        unmet.append(f"entry_quality {opp.entry_quality} not attackable")
    if opp.invalidation is None:
        unmet.append("no invalidation -> loss not bounded")
    if "LETHAL" in " ".join(opp.contradictions).upper():
        unmet.append("assassin lethal contradiction")

    if unmet:
        # NO_TRADE is a positive decision; it is not an error state
        return _r("NO_TRADE", opp, unmet, commissioning_test)

    if authority_level == "OBSERVE":
        if not commissioning_test:
            return _r("PAPER_EXPLORATORY_CANDIDATE", opp,
                      ["authority OBSERVE -- approval withheld; "
                       "candidate recorded, no card issued"],
                      commissioning_test)
        return _r("PAPER_EXPLORATORY_CANDIDATE", opp,
                  ["COMMISSIONING_TEST -- plumbing exercised only"],
                  commissioning_test)

    if authority_level == "PAPER_EXPLORATORY":
        return _r("PAPER_EXPLORATORY_APPROVED", opp,
                  ["exploratory authority granted"], commissioning_test)
    if authority_level in ("PAPER_AUTHORIZED", "TINY_LIVE",
                           "LIVE_SCALE"):
        return _r("PAPER_AUTHORIZED", opp, ["authorized cohort"],
                  commissioning_test)
    raise RouterRefused(f"unknown authority {authority_level!r}")


def _r(route_name: str, opp: PredatorOpportunity, reasons: list,
       test: bool) -> dict:
    return {"kind": "paper_route", "route": route_name,
            "opportunity_id": opp.opportunity_id, "sleeve": opp.sleeve,
            "subject": opp.subject, "state": opp.state,
            "attack_class": opp.attack_class,
            "reasons": tuple(reasons),
            "commissioning_test": test,
            "live_promotion_eligible": False,
            "cohort_law": "PAPER_EXPLORATORY is never edge-proof and "
                          "never live-promotion evidence",
            "decision_power": "NONE"}
