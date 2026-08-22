"""FrontierComputeRouter — F15: which tier of Frontier-2 reasoning gets
to run, gated by material change, opportunity seriousness, uncertainty
and information value -- NEVER by trade or risk authority. Compute tier
is an attention budget, not a size or authorization signal, the same
law apex.frontier.senses.route_reasoning() already enforces for Desk B
(reimplemented independently here, per the firewall).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from apex.frontier2 import FRONTIER2_POWER
from apex.frontier2.captain_shadow import STATES as CAPTAIN_STATES

LEDGER = Path("results/frontier2/compute_router2_ledger.jsonl")

TIERS = {
    0: "health/events",
    1: "Curve / simple RS / simple transitions",
    2: "ExpectationViolation / ParticipantPressure / Propagation",
    3: "WorldLab / Visual / Analog",
    4: "CaptainFrontierShadow / deep Assassin2",
}

UNCERTAINTY_LEVELS = ("LOW", "MODERATE", "HIGH")
INFO_VALUE_LEVELS = ("LOW", "MODERATE", "HIGH")


class ComputeRouter2Error(RuntimeError):
    pass


@dataclass(frozen=True)
class ComputeRoute:
    subject: str
    tier: int
    tier_description: str
    material_change: bool
    opportunity_seriousness: str
    uncertainty: str
    information_value: str
    reasoning: tuple
    known_from: str
    as_of: str
    decision_power: str = FRONTIER2_POWER

    def __post_init__(self):
        if self.tier not in TIERS:
            raise ComputeRouter2Error(f"unknown tier {self.tier!r}")

    def as_record(self) -> dict:
        return {"kind": "frontier2_compute_route", **asdict(self),
               "note": "compute tier never implies trade or risk authority"}


def route(subject: str, *, material_change: bool = False,
         opportunity_seriousness: str = "IGNORE", uncertainty: str = "LOW",
         information_value: str = "LOW", known_from, now) -> ComputeRoute:
    import pandas as pd
    now = pd.Timestamp(now)
    if opportunity_seriousness not in CAPTAIN_STATES:
        raise ComputeRouter2Error(
            f"unknown opportunity_seriousness {opportunity_seriousness!r}")
    if uncertainty not in UNCERTAINTY_LEVELS:
        raise ComputeRouter2Error(f"unknown uncertainty {uncertainty!r}")
    if information_value not in INFO_VALUE_LEVELS:
        raise ComputeRouter2Error(f"unknown information_value {information_value!r}")

    trace = []
    if opportunity_seriousness in ("SERIOUS", "WAIT_FOR_ENTRY"):
        tier = 4
        trace.append(f"seriousness={opportunity_seriousness} -> tier 4")
    elif opportunity_seriousness == "WAIT_FOR_CONFIRMATION":
        tier = 3
        trace.append("seriousness=WAIT_FOR_CONFIRMATION -> tier 3")
    elif opportunity_seriousness == "DEVELOP":
        tier = 3 if information_value == "HIGH" else 2
        trace.append(f"seriousness=DEVELOP, information_value="
                    f"{information_value} -> tier {tier}")
    elif opportunity_seriousness in ("DEGRADE", "INVALIDATE"):
        tier = 2
        trace.append(f"seriousness={opportunity_seriousness} -- still "
                    f"worth a real check on the way down -> tier 2")
    elif opportunity_seriousness == "WATCH":
        tier = 1
        trace.append("seriousness=WATCH -> tier 1")
    elif material_change:
        tier = 1
        trace.append("material_change=True with IGNORE seriousness -> tier 1")
    else:
        tier = 0
        trace.append("no material change, no seriousness -> tier 0")

    if uncertainty == "HIGH" and tier < 2:
        trace.append(f"uncertainty=HIGH escalates tier {tier} -> 2")
        tier = 2

    return ComputeRoute(
        subject=subject, tier=tier, tier_description=TIERS[tier],
        material_change=material_change,
        opportunity_seriousness=opportunity_seriousness, uncertainty=uncertainty,
        information_value=information_value, reasoning=tuple(trace),
        known_from=str(pd.Timestamp(known_from)), as_of=str(now))


def persist(rt: ComputeRoute) -> dict:
    import sys
    sys.path.insert(0, "scripts")
    from nightly_pull import _chain_append
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    return _chain_append(LEDGER, rt.as_record())
