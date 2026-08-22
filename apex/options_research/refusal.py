"""Fail-closed refusal gates — F O16. NO TRADE is successful behavior:
every gate below is a legitimate, expected terminus, not an exception
path and not a failure of the engine. A RefusalVerdict carries no
trade authority and blocks nothing except the ONE structure/subject it
names -- refusing one candidate never implies refusing the others.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

from apex.options_research import OPTIONS_RESEARCH_POWER

REFUSAL_GATES = (
    "REFUSE_INSUFFICIENT_UNDERLYING_THESIS",
    "REFUSE_HORIZON_MISMATCH",
    "REFUSE_ZERO_DTE_OUT_OF_SCOPE",
    "REFUSE_NO_OPTION_ADVANTAGE_MECHANISM",
    "REFUSE_MECHANISM_OUT_OF_SCOPE",
    "REFUSE_INSUFFICIENT_SURFACE_DATA",
    "REFUSE_UNKNOWN_GREEKS_REQUIRED_STRUCTURE",
    "REFUSE_STALE_SURFACE_DATA",
    "REFUSE_EXCESSIVE_SPREAD_COST",
    "REFUSE_ILLIQUID_SURFACE",
    "REFUSE_HUNTER_INSUFFICIENT_STATE",
    "REFUSE_CAPITAL_MATCHED_INFERIOR",
    "REFUSE_ANALYTICS_NOT_VALIDATED",
)

GATE_DESCRIPTIONS = {
    "REFUSE_INSUFFICIENT_UNDERLYING_THESIS":
        "no legitimate forward distribution -- Curve/CaptainShadow/Assassin2 "
        "carry no usable state for this subject",
    "REFUSE_HORIZON_MISMATCH":
        "no available DTE satisfies DTE_REQUIRED > horizon + timing + buffer",
    "REFUSE_ZERO_DTE_OUT_OF_SCOPE":
        "0DTE is a separate research bucket, not active in v1",
    "REFUSE_NO_OPTION_ADVANTAGE_MECHANISM":
        "no active mechanism (OPT-001/002/003) applies to this thesis",
    "REFUSE_MECHANISM_OUT_OF_SCOPE":
        "the only applicable mechanism is OPT-004..010, REGISTERED_NOT_ACTIVE",
    "REFUSE_INSUFFICIENT_SURFACE_DATA":
        "too many required surface features are NO_SUPPORT",
    "REFUSE_UNKNOWN_GREEKS_REQUIRED_STRUCTURE":
        "structure needs a Greek the current entitlement does not provide",
    "REFUSE_STALE_SURFACE_DATA":
        "surface feature freshness exceeds the structure's tolerance",
    "REFUSE_EXCESSIVE_SPREAD_COST":
        "conservative-taker spread cost consumes the thesis's expected edge",
    "REFUSE_ILLIQUID_SURFACE":
        "depth/volume/open_interest below the structure's liquidity floor",
    "REFUSE_HUNTER_INSUFFICIENT_STATE":
        "Hunter carries insufficient per-symbol state -- distinct from silence",
    "REFUSE_CAPITAL_MATCHED_INFERIOR":
        "STOCK or NO_TRADE Pareto-dominates this structure on a matched panel",
    "REFUSE_ANALYTICS_NOT_VALIDATED":
        "OPT-002/OPT-003 require apex.option_analytics's own APEX-computed "
        "surface pricing, which stays refused until its adversarial "
        "validation suite has been run and certified on the CURRENT code",
}


class RefusalError(RuntimeError):
    pass


@dataclass(frozen=True)
class RefusalVerdict:
    gate: str
    reason: str
    subject: str
    candidate_expression_type: str | None
    known_from: str
    decision_power: str = OPTIONS_RESEARCH_POWER

    def __post_init__(self):
        if self.gate not in REFUSAL_GATES:
            raise RefusalError(f"unknown refusal gate {self.gate!r}")

    def as_record(self) -> dict:
        return {"kind": "option_refusal_verdict", **asdict(self)}


def refuse(gate: str, *, subject: str, known_from, reason: str | None = None,
          candidate_expression_type: str | None = None) -> RefusalVerdict:
    import pandas as pd
    return RefusalVerdict(
        gate=gate, reason=(reason or GATE_DESCRIPTIONS.get(gate, "")),
        subject=subject, candidate_expression_type=candidate_expression_type,
        known_from=str(pd.Timestamp(known_from)))
