"""ResearchMechanism — the PROMOTION LAW: the library's own API can
never write apex_status=PROMOTED, in either the initial register or a
later evidence update.
"""
from __future__ import annotations

import pandas as pd
import pytest

from apex.research_library.mechanisms import (LIBRARY_FORBIDDEN_APEX_STATUS,
                                               MechanismError,
                                               register_mechanism,
                                               update_mechanism_evidence)

T0 = pd.Timestamp("2026-08-18T14:00:00Z")


def _register(tmp_path, monkeypatch, **overrides):
    import apex.research_library.mechanisms as mechmod
    monkeypatch.setattr(mechmod, "LEDGER", tmp_path / "mechanisms.jsonl")
    base = dict(mechanism_id="M1", name="Test Mechanism", description="d",
               market="EQUITIES", time_horizon="INTRADAY",
               claimed_mechanism="c", why_it_might_exist="w",
               expected_behavior="e", falsification="f", known_from=T0, now=T0)
    base.update(overrides)
    return register_mechanism(**base)


def test_promoted_refused_at_registration(tmp_path, monkeypatch):
    with pytest.raises(MechanismError):
        _register(tmp_path, monkeypatch, apex_status="PROMOTED")


def test_promoted_refused_on_evidence_update(tmp_path, monkeypatch):
    m = _register(tmp_path, monkeypatch)
    with pytest.raises(MechanismError):
        update_mechanism_evidence(m, now=T0, apex_status="PROMOTED")


def test_every_other_apex_status_is_allowed(tmp_path, monkeypatch):
    for status in ("UNTESTED", "OBSERVATIONAL", "DISCOVERY_TESTED",
                   "CONFIRMATORY_ELIGIBLE", "REJECTED"):
        m = _register(tmp_path, monkeypatch, mechanism_id=f"M-{status}",
                      apex_status=status)
        assert m.apex_status == status


def test_forbidden_constant_matches_promoted():
    assert LIBRARY_FORBIDDEN_APEX_STATUS == "PROMOTED"


def test_unknown_evidence_status_refused(tmp_path, monkeypatch):
    with pytest.raises(MechanismError):
        _register(tmp_path, monkeypatch, evidence_status="DEFINITELY_TRUE")


def test_evidence_update_is_a_new_ledger_row_not_a_mutation(tmp_path, monkeypatch):
    import apex.research_library.mechanisms as mechmod
    m = _register(tmp_path, monkeypatch)
    updated = update_mechanism_evidence(m, now=T0, add_supporting=("DOC1",))
    lines = (tmp_path / "mechanisms.jsonl").read_text().strip().splitlines()
    assert len(lines) == 2          # append-only: both the original and the update exist
    assert updated.supporting_documents == ("DOC1",)


def test_supporting_and_contradicting_accumulate(tmp_path, monkeypatch):
    m = _register(tmp_path, monkeypatch)
    m2 = update_mechanism_evidence(m, now=T0, add_supporting=("DOC1",))
    m3 = update_mechanism_evidence(m2, now=T0, add_supporting=("DOC2",),
                                   add_contradicting=("DOC3",))
    assert set(m3.supporting_documents) == {"DOC1", "DOC2"}
    assert m3.contradicting_documents == ("DOC3",)


def test_decision_power_stamped(tmp_path, monkeypatch):
    m = _register(tmp_path, monkeypatch)
    assert m.decision_power == "NONE_RESEARCH_MEMORY"
