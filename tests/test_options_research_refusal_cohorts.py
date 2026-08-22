"""Refusal gates (F O16) and Hunter/Frontier cohort classification
(F O19) -- NO TRADE / a refusal is successful behavior, and
HUNTER_REFUSED_INSUFFICIENT_STATE must never collapse into NO_MATCH.
"""
from __future__ import annotations

import pandas as pd
import pytest

from apex.options_research.cohorts import (COHORTS,
                                            HUNTER_REFUSED_INSUFFICIENT_STATE,
                                            CohortError, classify_cohort)
from apex.options_research.refusal import (REFUSAL_GATES, RefusalError,
                                            refuse)

T0 = pd.Timestamp("2026-08-18T14:40:00Z")


def test_all_thirteen_gates_named():
    assert len(REFUSAL_GATES) == 13
    assert len(set(REFUSAL_GATES)) == 13


def test_refuse_constructs_valid_verdict():
    v = refuse("REFUSE_HORIZON_MISMATCH", subject="AAPL", known_from=T0)
    assert v.gate == "REFUSE_HORIZON_MISMATCH"
    assert v.decision_power == "NONE_OPTIONS_RESEARCH"
    assert v.reason


def test_unknown_gate_refused():
    with pytest.raises(RefusalError):
        refuse("REFUSE_MADE_UP_GATE", subject="AAPL", known_from=T0)


def test_refusal_is_scoped_to_one_candidate_not_the_subject():
    v = refuse("REFUSE_ILLIQUID_SURFACE", subject="AAPL", known_from=T0,
              candidate_expression_type="LONG_STRADDLE")
    assert v.candidate_expression_type == "LONG_STRADDLE"
    assert v.subject == "AAPL"


def test_hunter_refused_insufficient_state_is_its_own_cohort():
    v = classify_cohort(subject="AAPL", hunter_present=True,
                        frontier_present=False, known_from=T0,
                        hunter_state_sufficient=False)
    assert v.cohort == HUNTER_REFUSED_INSUFFICIENT_STATE
    assert v.cohort != "COHORT_D_HUNTER_SILENT_FRONTIER_SILENT"


def test_cohort_a_both_active():
    v = classify_cohort(subject="SPY", hunter_present=True, frontier_present=True,
                        known_from=T0, hunter_state_sufficient=True)
    assert v.cohort == "COHORT_A_HUNTER_ACTIVE_FRONTIER_CONFIRMING"


def test_cohort_d_neither_active():
    v = classify_cohort(subject="XYZ", hunter_present=False, frontier_present=False,
                        known_from=T0)
    assert v.cohort == "COHORT_D_HUNTER_SILENT_FRONTIER_SILENT"


def test_cohort_c_frontier_only():
    v = classify_cohort(subject="QQQ", hunter_present=False, frontier_present=True,
                        known_from=T0)
    assert v.cohort == "COHORT_C_HUNTER_SILENT_FRONTIER_ACTIVE"


def test_unknown_cohort_refused():
    with pytest.raises(CohortError):
        from apex.options_research.cohorts import CohortVerdict
        CohortVerdict(cohort="MADE_UP", subject="AAPL", hunter_present=True,
                     hunter_state_sufficient=True, frontier_present=True,
                     known_from=str(T0))


def test_five_cohort_classes_total():
    assert len(COHORTS) == 5
