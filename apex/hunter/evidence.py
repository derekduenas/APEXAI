"""Data evidence classes — the operator's three-way law, as code.

EODHD_FORWARD_OBSERVATION: clean forward records, frozen before outcomes.
EODHD_HISTORICAL_EXPLORATORY: engineering only; carries the survivorship
limitation flag ALWAYS; refused for graduation/calibration-certification/
Credit-5/live decisions; can never be mixed into a forward calibration
statistic. INSTITUTIONAL_HISTORICAL_INTRADAY: future, none pre-approved.
"""

from __future__ import annotations

from enum import Enum


class EvidenceClass(Enum):
    EODHD_FORWARD_OBSERVATION = "EODHD_FORWARD_OBSERVATION"
    EODHD_HISTORICAL_EXPLORATORY = "EODHD_HISTORICAL_EXPLORATORY"
    INSTITUTIONAL_HISTORICAL_INTRADAY = "INSTITUTIONAL_HISTORICAL_INTRADAY"


FORBIDDEN_FOR_HISTORICAL_EXPLORATORY = (
    "graduation", "profitability_certification",
    "survivorship_free_claim", "calibration_certification",
    "credit_5_decision", "live_capital_eligibility",
)


class EvidenceViolation(RuntimeError):
    """A data class was offered a use its law forbids."""


def stamp(record: dict, evidence_class: EvidenceClass) -> dict:
    """Every artifact carries its class; historical-exploratory carries the
    survivorship limitation flag, non-optionally."""
    out = dict(record)
    out["evidence_class"] = evidence_class.value
    if evidence_class is EvidenceClass.EODHD_HISTORICAL_EXPLORATORY:
        out["HISTORICAL_PROVIDER_SURVIVORSHIP_LIMITATION"] = True
    return out


def require_permitted(evidence_class: EvidenceClass, use: str) -> None:
    if (evidence_class is EvidenceClass.EODHD_HISTORICAL_EXPLORATORY
            and use in FORBIDDEN_FOR_HISTORICAL_EXPLORATORY):
        raise EvidenceViolation(
            f"EODHD_HISTORICAL_EXPLORATORY may not be used for {use!r}: the "
            f"frozen provider probe failed the delisted-coverage gate "
            f"(50%/0% vs the 90% bar). The laboratory is not the exam.")


def require_unmixed(classes: set) -> None:
    """A calibration statistic computed over MIXED evidence classes is
    refused: forward truth and survivorship-limited history never share a
    denominator."""
    vals = {c.value if isinstance(c, EvidenceClass) else str(c) for c in classes}
    if len(vals) > 1:
        raise EvidenceViolation(
            f"one statistic over mixed evidence classes {sorted(vals)} is "
            f"refused. Separate ledgers, separate statistics, always.")
