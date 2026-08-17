"""CLOSE-1 — the anti-hindsight law and the cognitive loop.

The Closing Brief may know the close. The Morning Brief may not. BEFORE
cards may not. Memory flows forward only.
"""
from __future__ import annotations

import json

import pandas as pd
import pytest

from apex.frontier.closing import (DAY_STRUCTURES, day_structure,
                                   load_memory, setup_persistence,
                                   write_memory)


def _bars(closes, opens=None):
    idx = pd.date_range("2026-08-17T13:30:00Z", periods=len(closes),
                        freq="1min")
    o = opens or [closes[0]] + closes[:-1]
    return pd.DataFrame({"event_time_utc": idx, "open": o,
                         "high": [max(a, b) + 0.1 for a, b in zip(o, closes)],
                         "low": [min(a, b) - 0.1 for a, b in zip(o, closes)],
                         "close": closes, "volume": 1000.0})


def test_day_structure_is_deterministic_and_admits_unclear():
    up = _bars([100 + i * 0.03 for i in range(60)])
    s = day_structure(up)
    assert s["structure"] == "TREND_DAY_UP"
    assert s["structure"] in DAY_STRUCTURES
    assert day_structure(None)["structure"] == "UNCLEAR"
    assert day_structure(up)["structure"] == s["structure"]   # same in, same out


def test_late_fade_is_distinguished_from_trend():
    closes = [100 + i * 0.05 for i in range(45)] + \
             [102.2 - i * 0.06 for i in range(15)]
    assert day_structure(_bars(closes))["structure"] in (
        "LATE_FADE", "REVERSAL_DAY")


def test_memory_carries_knowledge_never_positions(tmp_path, monkeypatch):
    import apex.frontier.closing as cl
    monkeypatch.setattr(cl, "MEMORY", tmp_path)
    mem = write_memory(market_date="2026-08-17",
                       closing_packet={"packet_sha256": "abc",
                                       "day_structures": {"SPY.US": {
                                           "structure": "TREND_DAY_UP"}}},
                       morning_packet_hash="def")
    assert mem["positions_carried_overnight"] == "NONE_BY_CONSTITUTION"
    assert mem["memory_sha256"]
    blob = json.dumps(mem).lower()
    for bad in ("hold_overnight", "order", "weight", "paper_eligible"):
        assert bad not in blob
    again = load_memory("2026-08-17")
    assert again["memory_sha256"] == mem["memory_sha256"]


def test_anti_hindsight_the_morning_seal_cannot_know_the_close():
    """The premarket seal refuses post-bell timestamps (tested in
    PREMARKET-1); here: the closing module must never be importable FROM
    the morning path, so close facts cannot ride into a morning packet."""
    src = open("scripts/premarket_run.py").read()
    assert "closing_run" not in src
    assert "SEALED_CLOSING" not in src
    # premarket may read yesterday's MEMORY only — via load_memory
    pm = open("apex/frontier/premarket.py").read()
    assert "load_memory(prior_day)" in pm
    assert "load_memory(day)" not in pm, (
        "the morning packet loaded TODAY's memory — hindsight loop")


def test_before_cards_cannot_carry_setup_persistence():
    """SETUP_PERSISTENCE is an AFTER-only field; a BEFORE card carrying it
    would be a card that knows how the day ends."""
    from apex.frontier.decision_card import CardViolation, seal_before
    with pytest.raises(CardViolation):
        seal_before("C1", "2026-08-17", {
            "identity": {"symbol": "X"},
            "hunter": {"setup_persistence_outcome_note": "x",
                       "mfe": 0.02},
            "before_statement": {"what_i_see": "x", "why_it_matters": "x",
                                 "what_could_make_me_wrong": "x",
                                 "entry_attractiveness": "x",
                                 "what_would_make_it_better": "x"}},
            official_epoch_candidate=False, frontier_shadow_candidate=True)


def test_setup_persistence_classifies_from_resolved_fields_only():
    d = {"direction": "LONG"}
    assert setup_persistence(d, None) == "UNKNOWN"
    assert setup_persistence(d, {"ret_90m": 0.01}) == "PERSISTED_TO_CLOSE"
    assert setup_persistence(d, {"ret_90m": -0.01}) == "REVERSED"
    assert setup_persistence(d, {"ret_90m": 0.0005}) == "DECAYED"
    assert setup_persistence(
        d, {"ret_90m": 0.001, "target_before_stop": True}) \
        == "PERSISTED_TO_CLOSE"


def test_closing_auction_data_is_not_connected_not_fabricated():
    src = open("apex/frontier/closing.py").read()
    assert '"closing_auction_imbalance": "NOT_CONNECTED"' in src
    assert "substituting L2" in src or "substitute" in src.lower()


def test_h_close_persistence_preregistered_not_estimable():
    from apex.frontier.learning import PREREGISTRATION, estimate
    assert "H_CLOSE_PERSISTENCE" in PREREGISTRATION["hypotheses"]
    assert estimate("H_CLOSE_PERSISTENCE")["status"] == "NOT_YET_ESTIMABLE"


def test_the_closing_brief_firewall_blocks_holding_language():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path("scripts").resolve()))
    import closing_run
    assert "hold overnight" in closing_run.FORBIDDEN_IN_BRIEF
    assert "NEVER a holding decision" in open(
        "scripts/closing_run.py").read()
