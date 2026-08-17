"""FRONTIER-1 — the two-desk law, tested.

Desk A (Epoch-1) is the control; Desk B (Frontier Shadow) is the
challenger. These tests prove Desk B cannot touch Desk A, cannot know the
future, cannot estimate early, and cannot let missingness outrank
knowledge.
"""
from __future__ import annotations

import json

import pytest

from apex.frontier import FRONTIER_POWER
from apex.frontier.decision_card import (CardViolation, attach_outcome,
                                         seal_before)
from apex.frontier.learning import (PREREGISTRATION, LearningViolation,
                                    estimate)
from apex.frontier.senses import (FrontierViolation, detect_dislocations,
                                  rank_opportunities, route_reasoning)

SECTIONS_OK = {"identity": {"symbol": "AAPL"},
               "before_statement": {
                   "what_i_see": "clean reclaim", "why_it_matters": "traps",
                   "what_could_make_me_wrong": "anchor loss",
                   "entry_attractiveness": "moderate",
                   "what_would_make_it_better": "a retest"}}


# ---- 8/9/10: the Decision Card cannot know or rewrite ---------------------

def test_before_card_refuses_future_information():
    with pytest.raises(CardViolation):
        seal_before("D1", "2026-08-17",
                    {**SECTIONS_OK, "hunter": {"ret_60m": 0.02}},
                    official_epoch_candidate=True,
                    frontier_shadow_candidate=True)


def test_outcome_references_the_exact_before_hash():
    card = seal_before("D2", "2026-08-17", SECTIONS_OK,
                       official_epoch_candidate=True,
                       frontier_shadow_candidate=True)
    out = attach_outcome(card, {"ret_60m": 0.01, "mfe": 0.02, "mae": -0.004})
    assert out["decision_card_hash"] == card["card_sha256"]


def test_an_edited_card_is_refused_at_outcome_time():
    card = seal_before("D3", "2026-08-17", SECTIONS_OK,
                       official_epoch_candidate=False,
                       frontier_shadow_candidate=True)
    doctored = dict(card)
    doctored["captain"] = {"next_action": "REWRITTEN_AFTER_THE_FACT"}
    with pytest.raises(CardViolation):
        attach_outcome(doctored, {"ret_60m": 0.09})


def test_a_card_cannot_be_resealed_differently(tmp_path, monkeypatch):
    import apex.frontier.decision_card as dc
    monkeypatch.setattr(dc, "CARDS_ROOT", tmp_path)
    a = seal_before("D4", "2026-08-17", SECTIONS_OK,
                    official_epoch_candidate=True,
                    frontier_shadow_candidate=True)
    dc.persist(a)
    b = seal_before("D4", "2026-08-17",
                    {**SECTIONS_OK, "identity": {"symbol": "MSFT"}},
                    official_epoch_candidate=True,
                    frontier_shadow_candidate=True)
    with pytest.raises(CardViolation):
        dc.persist(b)


def test_unknown_sections_are_visible_holes():
    card = seal_before("D5", "2026-08-17", SECTIONS_OK,
                       official_epoch_candidate=True,
                       frontier_shadow_candidate=True)
    assert card["microscope"] == {"status": "UNKNOWN"}
    assert card["sealed"] == "SEALED_BEFORE_OUTCOME"


# ---- 11/19: the event bus is honest ---------------------------------------

def test_detection_cannot_precede_its_known_from(tmp_path, monkeypatch):
    import apex.frontier.senses as sn
    monkeypatch.setattr(sn, "BUS_LEDGER", tmp_path / "bus.jsonl")
    with pytest.raises(FrontierViolation):
        sn.emit("SCOUT_ABNORMALITY", "AAPL",
                event_time="2026-08-17T14:00:00Z",
                known_from="2026-08-17T13:59:00Z",     # before it happened
                source="scout", transport="POLLING")


def test_polling_is_never_labeled_streaming(tmp_path, monkeypatch):
    import apex.frontier.senses as sn
    monkeypatch.setattr(sn, "BUS_LEDGER", tmp_path / "bus.jsonl")
    with pytest.raises(FrontierViolation):
        sn.emit("FASTWATCH_OBSERVATION", "AAPL",
                event_time="2026-08-17T14:00:00Z",
                known_from="2026-08-17T14:00:05Z",
                source="fastwatch", transport="LIVE_STREAMING_ISH")
    ok = sn.emit("FASTWATCH_OBSERVATION", "AAPL",
                 event_time="2026-08-17T14:00:00Z",
                 known_from="2026-08-17T14:00:05Z",
                 source="fastwatch", transport="POLLING")
    assert ok["transport"] == "POLLING"


def test_the_equity_fabric_reports_polling_honestly():
    from apex.frontier.senses import equity_fabric_health
    h = equity_fabric_health()
    assert h.transport == "POLLING"
    assert h.status in ("HEALTHY", "DEGRADED", "UNKNOWN")


# ---- 4: dislocations never originate a thesis -----------------------------

def test_dislocations_are_observations_with_mechanisms_not_signals():
    obs = detect_dislocations(
        {"rvol_tod": 4.0, "range_vs_atr": 0.2, "gap_frac": 0.0},
        {"excess_market_60m": 0.03, "cross_sectional_pct": 0.99},
        {"day_return": 0.001})
    assert obs, "a textbook dislocation set produced nothing"
    for o in obs:
        assert o["state"] == "FRONTIER_DISLOCATION_OBSERVED"
        assert "SIGNAL" not in json.dumps(o)
        assert o["mechanism_hypothesis"] and o["falsification_condition"]
        assert o["decision_power"] == FRONTIER_POWER


def test_event_repricing_is_forbidden_under_uncertain_attribution():
    with_cat = detect_dislocations({"rvol_tod": 5.0, "range_vs_atr": 2.0},
                                   {}, {}, catalyst_status="KNOWN_CATALYST")
    uncertain = detect_dislocations({"rvol_tod": 5.0, "range_vs_atr": 2.0},
                                    {}, {}, catalyst_status="EVENT_UNCERTAIN")
    assert any(o["class"] == "EVENT_REPRICING" for o in with_cat)
    assert not any(o["class"] == "EVENT_REPRICING" for o in uncertain)


# ---- 15: the board fails closed on UNKNOWN --------------------------------

def test_unknown_never_outranks_known_good(tmp_path, monkeypatch):
    import apex.frontier.senses as sn
    monkeypatch.setattr(sn, "BOARD_LEDGER", tmp_path / "board.jsonl")
    known = {"symbol": "NVDA", "data_health": "HEALTHY",
             "candidate_class": "HUNTER", "direction_quality": "STRONG",
             "entry_quality": "MODERATE", "assassin": "SURVIVED_CLEAN"}
    mystery = {"symbol": "XXXX"}                    # everything UNKNOWN
    snap = rank_opportunities([mystery, known])
    assert snap["ranked"][0]["symbol"] == "NVDA"
    assert snap["ranked"][1]["symbol"] == "XXXX"
    assert snap["decision_power"] == FRONTIER_POWER
    # rejections stay visible
    assert snap["n_competing"] == 2


def test_the_board_is_deterministic(tmp_path, monkeypatch):
    import apex.frontier.senses as sn
    monkeypatch.setattr(sn, "BOARD_LEDGER", tmp_path / "b.jsonl")
    cands = [{"symbol": s, "candidate_class": "NEAR"} for s in
             ("B", "A", "C")]
    a = rank_opportunities(list(cands))
    b = rank_opportunities(list(reversed(cands)))
    assert [r["symbol"] for r in a["ranked"]] == \
        [r["symbol"] for r in b["ranked"]] == ["A", "B", "C"]


# ---- 16/17/18: the router has no hands ------------------------------------

def test_the_reasoning_router_touches_only_compute():
    r = route_reasoning(is_hunter_candidate=True, on_watchlist=True,
                        persistence_ticks=3)
    assert r["reasoning_tier"] == 3
    blob = json.dumps(r).lower()
    for forbidden in ("size", "weight", "stop", "authorize", "notional",
                      "paper_eligible"):
        assert forbidden not in blob or forbidden in ("size",) and \
            "position size" in blob   # the prohibition note itself
    assert "never means more position size" in r["note"]


def test_unknown_persistence_caps_the_tier():
    r = route_reasoning(is_hunter_candidate=True, on_watchlist=True,
                        persistence_ticks=None)
    assert r["reasoning_tier"] == 2, "unknown persistence invented an edge"


# ---- 5/6/7: learning cannot run early -------------------------------------

def test_all_three_registries_are_not_yet_estimable():
    for h in ("H_VISUAL", "H_ASSASSIN", "H_CATALYST"):
        r = estimate(h)
        assert r["status"] == "NOT_YET_ESTIMABLE", h
        assert r["decision_power"] == FRONTIER_POWER


def test_post_hoc_hypotheses_are_refused():
    with pytest.raises(LearningViolation):
        estimate("H_WHATEVER_LOOKED_GOOD_TUESDAY")


def test_the_preregistration_is_pinned():
    assert PREREGISTRATION["min_n_per_group"] == 20
    assert PREREGISTRATION["min_distinct_dates"] == 10
    assert "no historical LLM replay" in PREREGISTRATION["rule_17"]


# ---- 1/2/3/20: Desk B cannot reach Desk A ---------------------------------

def test_no_frozen_module_imports_the_frontier_package():
    from pathlib import Path
    frozen = ("apex/hunter/forward_pass.py", "apex/hunter/playbooks_v1.py",
              "apex/hunter/capital.py", "apex/hunter/scanner.py",
              "apex/captain/kernel.py", "apex/captain/board.py",
              "scripts/hunter_forward_clock.py")
    for f in frozen:
        src = Path(f).read_text()
        assert "apex.frontier" not in src, (
            f"{f} imports the frontier package — Desk B reached Desk A")


def test_the_frontier_package_never_writes_official_ledgers():
    from pathlib import Path
    for f in Path("apex/frontier").rglob("*.py"):
        src = f.read_text()
        for official in ("forward_ledger.jsonl", "birth_registry.jsonl",
                         "screen_log.jsonl"):
            assert official not in src, (
                f"{f} names an official ledger — the shadow desk writes "
                f"only to results/frontier/ and results/decision_cards/")


def test_frontier_power_is_the_only_power_in_the_package():
    from pathlib import Path
    for f in Path("apex/frontier").rglob("*.py"):
        src = f.read_text()
        assert "PAPER_ELIGIBLE" not in src
        assert "LIVE_ELIGIBLE" not in src
