"""APEX_RESEARCH_LIBRARY_V1 birth, and the empty OPTIONS/BTC_PERPS
program placeholders."""
from __future__ import annotations

import pandas as pd
import pytest

from apex.research_library.birth import LIBRARY_VERSION, already_minted, mint
from apex.research_library.programs import (PROGRAMS, register_program,
                                            update_program_status)

T0 = pd.Timestamp("2026-08-18T14:00:00Z")


def test_mint_writes_a_chained_record(tmp_path, monkeypatch):
    import apex.research_library.birth as birthmod
    monkeypatch.setattr(birthmod, "LEDGER", tmp_path / "birth.jsonl")
    rec1 = mint(now=T0)
    rec2 = mint(now=T0)
    assert rec1["library_version"] == LIBRARY_VERSION
    assert rec1["decision_power"] == "NONE_RESEARCH_MEMORY"
    assert rec1["capital_authority"] == "NONE"
    assert rec1["broker_authority"] == "NONE"
    assert rec2["prev_hash"] == rec1["entry_hash"]


def test_already_minted_reflects_real_state(tmp_path, monkeypatch):
    import apex.research_library.birth as birthmod
    monkeypatch.setattr(birthmod, "LEDGER", tmp_path / "birth.jsonl")
    assert already_minted() is False
    mint(now=T0)
    assert already_minted() is True


def test_programs_are_named_correctly():
    assert set(PROGRAMS) == {"APEX_OPTIONS_RESEARCH_V1", "APEX_BTC_PERPS_RESEARCH_V1"}


def test_register_program_only_accepts_not_started(tmp_path, monkeypatch):
    import apex.research_library.programs as progmod
    monkeypatch.setattr(progmod, "LEDGER", tmp_path / "programs.jsonl")
    with pytest.raises(RuntimeError):
        register_program("APEX_OPTIONS_RESEARCH_V1", now=T0, status="IN_PROGRESS")


def test_register_program_writes_not_started(tmp_path, monkeypatch):
    import apex.research_library.programs as progmod
    monkeypatch.setattr(progmod, "LEDGER", tmp_path / "programs.jsonl")
    rec = register_program("APEX_OPTIONS_RESEARCH_V1", now=T0)
    assert rec["status"] == "NOT_STARTED"
    assert rec["document_count"] == 0
    assert rec["decision_power"] == "NONE_RESEARCH_MEMORY"


def test_update_program_status_requires_prior_registration(tmp_path, monkeypatch):
    import apex.research_library.programs as progmod
    monkeypatch.setattr(progmod, "LEDGER", tmp_path / "programs.jsonl")
    with pytest.raises(RuntimeError):
        update_program_status("APEX_OPTIONS_RESEARCH_V1", now=T0,
                              status="RESEARCH_INGESTED")


def test_update_program_status_moves_to_research_ingested(tmp_path, monkeypatch):
    import apex.research_library.programs as progmod
    monkeypatch.setattr(progmod, "LEDGER", tmp_path / "programs.jsonl")
    register_program("APEX_OPTIONS_RESEARCH_V1", now=T0)
    rec = update_program_status("APEX_OPTIONS_RESEARCH_V1", now=T0,
                                status="RESEARCH_INGESTED", document_count=1)
    assert rec["status"] == "RESEARCH_INGESTED"
    assert rec["document_count"] == 1


def test_update_program_status_document_count_never_decreases(tmp_path, monkeypatch):
    import apex.research_library.programs as progmod
    monkeypatch.setattr(progmod, "LEDGER", tmp_path / "programs.jsonl")
    register_program("APEX_OPTIONS_RESEARCH_V1", now=T0)
    update_program_status("APEX_OPTIONS_RESEARCH_V1", now=T0,
                          status="RESEARCH_INGESTED", document_count=1)
    with pytest.raises(RuntimeError):
        update_program_status("APEX_OPTIONS_RESEARCH_V1", now=T0,
                              status="IN_PROGRESS", document_count=0)


def test_update_program_status_rejects_unknown_status(tmp_path, monkeypatch):
    import apex.research_library.programs as progmod
    monkeypatch.setattr(progmod, "LEDGER", tmp_path / "programs.jsonl")
    register_program("APEX_OPTIONS_RESEARCH_V1", now=T0)
    with pytest.raises(RuntimeError):
        update_program_status("APEX_OPTIONS_RESEARCH_V1", now=T0, status="MADE_UP")
