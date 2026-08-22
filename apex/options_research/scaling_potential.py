"""AccountScalingPotential — Doctrine section 2. Whether a structure
CAN carry meaningfully larger size without breaking its own economics
(liquidity/spread/contract capacity, concentration, correlation). "No
expression receives EXCEPTIONAL based on narrative" is enforced
mechanically here: EXCEPTIONAL_UNPROVEN requires every supporting
input to be real, non-None, and above a named threshold -- a missing
or weak input caps the verdict at a lower rung, it never gets waved
through on a strong-sounding thesis.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

from apex.options_research import OPTIONS_RESEARCH_POWER

SCALING_STATUSES = ("LOW", "MODERATE", "HIGH", "EXCEPTIONAL_UNPROVEN")

# named thresholds for EXCEPTIONAL_UNPROVEN -- deliberately conservative;
# this is a research classification, not a green light for size.
EXCEPTIONAL_MIN_TAIL_PAYOFF_MULTIPLE = 5.0
EXCEPTIONAL_MAX_CONCENTRATION_RISK = 0.30
HIGH_MIN_TAIL_PAYOFF_MULTIPLE = 2.0
HIGH_MAX_CONCENTRATION_RISK = 0.50


class ScalingPotentialError(RuntimeError):
    pass


@dataclass(frozen=True)
class AccountScalingPotential:
    subject: str
    expression_type: str
    risk_unit_required: float | None
    capital_required: float | None
    maximum_loss: float | None
    expected_payoff_multiple: float | None
    tail_payoff_multiple: float | None
    liquidity_capacity: float | None
    spread_capacity: float | None
    contract_capacity: int | None
    position_scalability: str        # SUPPORTED / NO_SUPPORT, same discipline as surface features
    concentration_risk: float | None
    correlation_with_existing_risk: float | None
    scaling_status: str
    known_from: str
    decision_power: str = OPTIONS_RESEARCH_POWER

    def __post_init__(self):
        if self.scaling_status not in SCALING_STATUSES:
            raise ScalingPotentialError(f"unknown scaling_status {self.scaling_status!r}")

    def as_record(self) -> dict:
        return {"kind": "account_scaling_potential", **asdict(self)}


def classify_scaling_status(*, tail_payoff_multiple: float | None,
                            liquidity_capacity: float | None,
                            spread_capacity: float | None,
                            contract_capacity: int | None,
                            concentration_risk: float | None) -> str:
    """Mechanically conservative: any missing evidential input caps the
    result below EXCEPTIONAL_UNPROVEN/HIGH, regardless of how good the
    other inputs look."""
    evidenced = all(v is not None for v in
                    (tail_payoff_multiple, liquidity_capacity, spread_capacity,
                     contract_capacity, concentration_risk))
    if not evidenced:
        return "LOW"
    if (tail_payoff_multiple >= EXCEPTIONAL_MIN_TAIL_PAYOFF_MULTIPLE
            and concentration_risk <= EXCEPTIONAL_MAX_CONCENTRATION_RISK
            and liquidity_capacity > 0 and spread_capacity > 0 and contract_capacity > 0):
        return "EXCEPTIONAL_UNPROVEN"
    if (tail_payoff_multiple >= HIGH_MIN_TAIL_PAYOFF_MULTIPLE
            and concentration_risk <= HIGH_MAX_CONCENTRATION_RISK
            and liquidity_capacity > 0 and spread_capacity > 0 and contract_capacity > 0):
        return "HIGH"
    if liquidity_capacity > 0 and spread_capacity > 0 and contract_capacity > 0:
        return "MODERATE"
    return "LOW"


def build(*, subject: str, expression_type: str, known_from,
         risk_unit_required: float | None = None, capital_required: float | None = None,
         maximum_loss: float | None = None, expected_payoff_multiple: float | None = None,
         tail_payoff_multiple: float | None = None, liquidity_capacity: float | None = None,
         spread_capacity: float | None = None, contract_capacity: int | None = None,
         concentration_risk: float | None = None,
         correlation_with_existing_risk: float | None = None) -> AccountScalingPotential:
    import pandas as pd
    status = classify_scaling_status(
        tail_payoff_multiple=tail_payoff_multiple, liquidity_capacity=liquidity_capacity,
        spread_capacity=spread_capacity, contract_capacity=contract_capacity,
        concentration_risk=concentration_risk)
    position_scalability = "SUPPORTED" if status in ("MODERATE", "HIGH", "EXCEPTIONAL_UNPROVEN") else "NO_SUPPORT"
    return AccountScalingPotential(
        subject=subject, expression_type=expression_type,
        risk_unit_required=risk_unit_required, capital_required=capital_required,
        maximum_loss=maximum_loss, expected_payoff_multiple=expected_payoff_multiple,
        tail_payoff_multiple=tail_payoff_multiple, liquidity_capacity=liquidity_capacity,
        spread_capacity=spread_capacity, contract_capacity=contract_capacity,
        position_scalability=position_scalability, concentration_risk=concentration_risk,
        correlation_with_existing_risk=correlation_with_existing_risk,
        scaling_status=status, known_from=str(pd.Timestamp(known_from)))
