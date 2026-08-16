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
    # additive (2026-08-16): the 24/7 crypto shadow arena — genuinely
    # prospective, zero capital, NEVER evidence about equity playbooks;
    # the unmixed law keeps it in its own ledgers and statistics
    COINBASE_FORWARD_OBSERVATION = "COINBASE_FORWARD_OBSERVATION"


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


def require_declared_class(rows, declared: EvidenceClass, *,
                           where: str) -> None:
    """LAB-08 -- enforcement at the POINT OF CONSUMPTION.

    `require_unmixed` guards a statistic AFTER the fact, in the scoreboard.
    That is the wrong end of the pipe for an engine that ACCEPTS rows and
    STAMPS its output with a class it was simply told. A caller offering
    exploratory rows while declaring FORWARD would previously receive a
    result stamped clean-forward -- the class would be laundered, and the
    downstream mixing guard would never see it because it inspects ledger
    records, not engine inputs.

    So: every offered row must carry `evidence_class`, and it must equal
    what the caller declared. Unstamped is refused as loudly as mismatched
    -- "I cannot verify this" and "this is wrong" get the same answer,
    because a class that cannot be checked cannot be certified.
    """
    seen, unstamped = set(), 0
    for r in rows:
        v = (r or {}).get("evidence_class")
        if v is None:
            unstamped += 1
        else:
            seen.add(v.value if isinstance(v, EvidenceClass) else str(v))
    if unstamped:
        raise EvidenceViolation(
            f"{where}: {unstamped}/{len(rows)} offered rows carry no "
            f"evidence_class. An unverifiable class cannot be stamped "
            f"{declared.value}; refusing rather than assuming.")
    if seen - {declared.value}:
        raise EvidenceViolation(
            f"{where}: caller declared {declared.value} but the rows "
            f"contain {sorted(seen)}. Evidence classes never mix, and a "
            f"declaration does not convert one into another.")


def require_unmixed(classes: set) -> None:
    """A calibration statistic computed over MIXED evidence classes is
    refused: forward truth and survivorship-limited history never share a
    denominator."""
    vals = {c.value if isinstance(c, EvidenceClass) else str(c) for c in classes}
    if len(vals) > 1:
        raise EvidenceViolation(
            f"one statistic over mixed evidence classes {sorted(vals)} is "
            f"refused. Separate ledgers, separate statistics, always.")
