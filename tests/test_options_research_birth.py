"""Options Research V1 -- five separate birth chains (F O27). Every
birth is decision_power=NONE_OPTIONS_RESEARCH / capital_authority=NONE
/ broker_authority=NONE, and minting is idempotent."""
from __future__ import annotations

import pandas as pd
import pytest

from apex.options_research import birth as birth_mod

T0 = pd.Timestamp("2026-08-18T14:40:00Z")


def test_unknown_birth_version_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(birth_mod, "LEDGER", tmp_path / "births.jsonl")
    with pytest.raises(birth_mod.BirthError):
        birth_mod.mint("MADE_UP_BIRTH", now=T0)


def test_mint_writes_decision_power_and_no_authority(tmp_path, monkeypatch):
    monkeypatch.setattr(birth_mod, "LEDGER", tmp_path / "births.jsonl")
    rec = birth_mod.mint("OPTION_MARKET_SCHEMA_V1", now=T0)
    assert rec["decision_power"] == "NONE_OPTIONS_RESEARCH"
    assert rec["capital_authority"] == "NONE"
    assert rec["broker_authority"] == "NONE"


def test_mint_all_produces_six_distinct_births(tmp_path, monkeypatch):
    monkeypatch.setattr(birth_mod, "LEDGER", tmp_path / "births.jsonl")
    minted = birth_mod.mint_all(now=T0)
    assert len(minted) == 6
    assert {r["birth_version"] for r in minted} == set(birth_mod.BIRTH_VERSIONS)


def test_mint_all_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(birth_mod, "LEDGER", tmp_path / "births.jsonl")
    birth_mod.mint_all(now=T0)
    second = birth_mod.mint_all(now=T0)
    assert second == ()
    for v in birth_mod.BIRTH_VERSIONS:
        assert birth_mod.already_minted(v)
