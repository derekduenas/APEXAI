"""Tests for the unified hunting organism wiring."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from apex.organism import expert_registry, hunt, market_state


def test_registry_no_fake_experts():
    for e in expert_registry.roster():
        if e.status.startswith("ACTIVE"):
            assert e.consult, f"{e.expert_id} active without surface"
        if e.status == "NOT_IMPLEMENTED":
            assert not e.consult
    assert expert_registry.summary()["experts"] >= 15


def test_registry_graveyard_respected():
    dead = {e.expert_id for e in expert_registry.graveyard()}
    assert "H5_STATISTICAL" in dead
    assert "OPEX_CALENDAR_FLOW" in dead
    h5 = [e for e in expert_registry.roster()
          if e.expert_id == "H5_STATISTICAL"][0]
    assert h5.status == "RETIRED"


def test_market_state_unknown_preserved():
    st = market_state.compose(as_of="2026-08-28T14:00:00Z")
    assert st["QUANT"]["status"] == "NOT_IMPLEMENTED"
    assert st["LIQUIDITY"]["status"] == "NOT_IMPLEMENTED"
    assert st["subject"] == "MARKET"
    assert st["decision_power"] == "NONE_COMPOSER"


def test_hunt_tick_no_event_is_no_trade():
    with tempfile.TemporaryDirectory() as td:
        t = hunt.tick(as_of="2026-08-28T14:00:00Z",
                      ledger=Path(td) / "ticks.jsonl")
    assert t["final"] == "NO_TRADE"
    assert t["best_physical"] is None
    assert "cash" in " ".join(t["why"]).lower()
    assert t["decision_power"] == "SHADOW_COUNTERFACTUAL_ONLY"


def test_hunt_tick_seals_record():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "ticks.jsonl"
        hunt.tick(as_of="2026-08-28T14:00:00Z", ledger=p)
        rows = [json.loads(x) for x in
                p.read_text().splitlines() if x.strip()]
    assert len(rows) == 1
    assert rows[0]["kind"] == "hunt_tick"


def test_hunt_tick_with_negative_surprise_event():
    ev = {"symbol": "TSLA", "report_date": "2023-01-25",
          "timing": "pm", "known_from": "2023-01-26T09:30:00-05:00",
          "reaction_session": "2023-01-26",
          "eps_estimate": 1.13, "eps_actual": 1.05,
          "consensus_provenance": "TEST_FIXTURE"}
    with tempfile.TemporaryDirectory() as td:
        t = hunt.tick(as_of="2023-01-26T09:35:00-05:00",
                      subject="TSLA", event=ev, rt_cost_bps=8.0,
                      short_allowed=True,
                      ledger=Path(td) / "ticks.jsonl")
    cons = t["alpha_market"]["consults"]["EVENT_INFORMATION"]
    assert cons["mechanism_agreement"] == \
        "RELATED_EXPERTS_NOT_INDEPENDENT"
    assert t["best_physical"] is not None
    assert t["final"] in ("ATTACK_READY_SHADOW", "WATCH", "NO_TRADE")


def test_render_card_contains_sections():
    with tempfile.TemporaryDirectory() as td:
        t = hunt.tick(as_of="2026-08-28T14:00:00Z",
                      ledger=Path(td) / "t.jsonl")
    card = hunt.render(t)
    for token in ("ALPHA MARKET", "FINAL:", "WHY:"):
        assert token in card
