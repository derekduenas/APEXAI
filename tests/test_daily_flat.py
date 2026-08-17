"""THE DAILY-FLAT CONSTITUTION — ten proofs that no component owns
overnight authority. Scans are for EXECUTABLE consumption/definition,
never vocabulary (the collision trap's standing lesson)."""
from __future__ import annotations

from pathlib import Path

import pytest

FORBIDDEN_STATES = ("HOLD_OVERNIGHT", "OVERNIGHT_POSITION", "SWING",
                    "HOLD_FOR_TOMORROW", "CARRY_OVERNIGHT")


def _executable(path):
    from apex.audit.execution_path import executable_source
    return executable_source(Path(path).read_text())


def test_1_captain_cannot_recommend_hold_overnight():
    for f in ("apex/captain/kernel.py", "apex/captain/cio.py",
              "apex/captain/board.py"):
        code = _executable(f)
        for s in FORBIDDEN_STATES:
            assert s not in code, f"{f} can express {s}"


def test_2_visual_eyes_cannot_create_overnight_authority():
    from apex.vision.challenger import ALLOWED
    joined = " ".join(v for vals in ALLOWED.values() for v in vals)
    for s in FORBIDDEN_STATES:
        assert s not in joined


def test_3_catalyst_cannot_create_overnight_authority():
    code = _executable("apex/events/catalyst.py")
    for s in FORBIDDEN_STATES:
        assert s not in code


def test_4_frontier_board_cannot_rank_into_overnight():
    from apex.frontier.senses import RANK_ORDER, _VAL
    assert "overnight" not in " ".join(RANK_ORDER).lower()
    joined = " ".join(k for d in _VAL.values() for k in d)
    for s in FORBIDDEN_STATES:
        assert s not in joined


def test_5_expression_cannot_transform_intraday_into_overnight():
    code = _executable("apex/execution/expression_v2.py")
    for s in FORBIDDEN_STATES:
        assert s not in code


def test_6_trade_manager_has_no_overnight_state():
    from apex.hunter.statemachine import TradeState
    names = {m.name for m in TradeState}
    for s in FORBIDDEN_STATES:
        assert s not in names
    assert not any("OVERNIGHT" in n or "SWING" in n for n in names)


def test_7_no_lifecycle_state_survives_a_session_boundary_as_authorized():
    """Restart law: the paper module's production gate re-derives
    eligibility from the CURRENT capital decision; a stale prior-session
    position state is not an authorization."""
    code = _executable("apex/hunter/paper.py")
    assert "PAPER_ELIGIBLE" in code            # the gate exists
    for s in FORBIDDEN_STATES:
        assert s not in code


def test_8_premarket_reads_memory_but_cannot_resurrect_trades():
    code = _executable("apex/frontier/premarket.py")
    for token in ("place_", "OrderIntent", "PAPER_ELIGIBLE",
                  "evaluate_candidate"):
        assert token not in code, (
            f"premarket touches {token} — memory is knowledge, not "
            f"positions")


def test_9_decision_cards_cannot_specify_overnight_authorization():
    from apex.frontier.decision_card import seal_before, CardViolation
    card = seal_before("DF-1", "2026-08-17", {
        "identity": {"symbol": "X"},
        "hunter": {"holding_intent": "HOLD_OVERNIGHT"},
        "before_statement": {"what_i_see": "x", "why_it_matters": "x",
                            "what_could_make_me_wrong": "x",
                            "entry_attractiveness": "x",
                            "what_would_make_it_better": "x"}},
        official_epoch_candidate=False, frontier_shadow_candidate=True)
    # a card may RECORD such text as data, but authority fields are fixed:
    assert card["decision_power"] == "NONE_FRONTIER_SHADOW"
    import json
    assert '"OVERNIGHT_POSITION_AUTHORITY"' not in json.dumps(card)


def test_10_no_component_owns_overnight_position_authority():
    """The grep that matters: no executable file GRANTS the authority."""
    hits = []
    for f in list(Path("apex").rglob("*.py")) + \
            list(Path("scripts").rglob("*.py")):
        if "__pycache__" in str(f):
            continue
        code = _executable(f)
        if "OVERNIGHT_POSITION_AUTHORITY" in code and \
                '"NONE"' not in code and "'NONE'" not in code:
            hits.append(str(f))
    assert not hits, f"overnight authority granted in: {hits}"
    assert Path("docs/DAILY-FLAT-CONSTITUTION.md").exists()
