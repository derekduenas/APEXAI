"""The three-way data-evidence law (operator ruling c), fail-closed."""

import pytest

from apex.hunter.evidence import (
    EvidenceClass, EvidenceViolation, require_permitted, require_unmixed, stamp,
)


def test_historical_exploratory_always_carries_the_limitation_flag():
    r = stamp({"x": 1}, EvidenceClass.EODHD_HISTORICAL_EXPLORATORY)
    assert r["HISTORICAL_PROVIDER_SURVIVORSHIP_LIMITATION"] is True
    f = stamp({"x": 1}, EvidenceClass.EODHD_FORWARD_OBSERVATION)
    assert "HISTORICAL_PROVIDER_SURVIVORSHIP_LIMITATION" not in f


def test_every_forbidden_use_is_refused_for_historical_exploratory():
    for use in ("graduation", "profitability_certification",
                "survivorship_free_claim", "calibration_certification",
                "credit_5_decision", "live_capital_eligibility"):
        with pytest.raises(EvidenceViolation, match="laboratory is not the exam"):
            require_permitted(EvidenceClass.EODHD_HISTORICAL_EXPLORATORY, use)


def test_counterexample_engineering_uses_are_permitted():
    require_permitted(EvidenceClass.EODHD_HISTORICAL_EXPLORATORY, "engineering")
    require_permitted(EvidenceClass.EODHD_FORWARD_OBSERVATION, "graduation")


def test_mixed_evidence_classes_never_share_a_statistic():
    with pytest.raises(EvidenceViolation, match="Separate ledgers"):
        require_unmixed({EvidenceClass.EODHD_FORWARD_OBSERVATION,
                         EvidenceClass.EODHD_HISTORICAL_EXPLORATORY})
    require_unmixed({EvidenceClass.EODHD_FORWARD_OBSERVATION})
