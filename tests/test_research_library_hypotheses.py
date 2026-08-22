"""ResearchHypothesisCandidate — the library may only ever produce
PROPOSED_ONLY; there is no code path to any other status."""
from __future__ import annotations

import inspect

import pandas as pd
import pytest

from apex.research_library.hypotheses import (STATUSES, HypothesisError,
                                               ResearchHypothesisCandidate,
                                               propose)

T0 = pd.Timestamp("2026-08-18T14:00:00Z")


def _propose(tmp_path, monkeypatch, **overrides):
    import apex.research_library.hypotheses as hypmod
    monkeypatch.setattr(hypmod, "LEDGER", tmp_path / "hypotheses.jsonl")
    base = dict(hypothesis_id="H1", mechanism_id="M1", statement="s",
               market="EQUITIES", primary_metric="ret_60m",
               minimum_sample="n>=20", falsification="f",
               regime_requirements="any", cost_requirements="none",
               prospective_test_design="t", known_from=T0, now=T0)
    base.update(overrides)
    return propose(**base)


def test_propose_has_no_status_parameter():
    assert "status" not in inspect.signature(propose).parameters


def test_every_proposal_is_proposed_only(tmp_path, monkeypatch):
    h = _propose(tmp_path, monkeypatch)
    assert h.status == "PROPOSED_ONLY"


def test_bad_status_refused_at_construction():
    """APPROVED_FOR_DISCOVERY etc. ARE valid dataclass states (external
    governance must be able to represent them, same as ResearchMechanism
    allows PROMOTED as a value even though its own API refuses to write
    it) -- only a truly unrecognized string is refused."""
    with pytest.raises(HypothesisError):
        ResearchHypothesisCandidate(
            hypothesis_id="H1", mechanism_id="M1", statement="s", market="EQ",
            primary_metric="m", secondary_metrics=(), required_data=(),
            minimum_sample="n", falsification="f", regime_requirements="r",
            cost_requirements="c", prospective_test_design="t",
            status="NOT_A_REAL_STATUS", known_from=str(T0), as_of=str(T0))


def test_all_four_statuses_are_valid_dataclass_values_even_though_library_cant_write_them():
    assert set(STATUSES) == {"PROPOSED_ONLY", "APPROVED_FOR_DISCOVERY",
                             "APPROVED_FOR_CONFIRMATION", "REJECTED"}


def test_hypothesis_links_to_a_mechanism_id(tmp_path, monkeypatch):
    h = _propose(tmp_path, monkeypatch, mechanism_id="M-SPECIFIC")
    assert h.mechanism_id == "M-SPECIFIC"


def test_falsification_and_sample_requirements_present(tmp_path, monkeypatch):
    h = _propose(tmp_path, monkeypatch)
    assert h.falsification and h.minimum_sample


def test_decision_power_stamped(tmp_path, monkeypatch):
    h = _propose(tmp_path, monkeypatch)
    assert h.decision_power == "NONE_RESEARCH_MEMORY"


def test_ledger_writes_are_chained(tmp_path, monkeypatch):
    import json
    _propose(tmp_path, monkeypatch, hypothesis_id="H1")
    _propose(tmp_path, monkeypatch, hypothesis_id="H2")
    lines = (tmp_path / "hypotheses.jsonl").read_text().strip().splitlines()
    recs = [json.loads(l) for l in lines]
    assert recs[1]["prev_hash"] == recs[0]["entry_hash"]
