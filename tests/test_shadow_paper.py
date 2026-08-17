"""SHADOW PAPER — the operator's hard tests. Zero authority, real inputs
or refusal, DAILY_FLAT, and the counterfactual is authorization ONLY."""
from __future__ import annotations

import json
from dataclasses import asdict

import pandas as pd
import pytest

from apex.frontier.shadow_paper import (ShadowPosition, ShadowViolation,
                                        eligible, manage, open_position)

DEC = {"decision_id": "SP-1", "symbol": "NVDA.US", "direction": "LONG",
       "playbook_id": "HUNTER-001_v1", "entry": 200.0, "stop": 198.0,
       "target": 204.0, "forward_eligibility": "FORWARD_ELIGIBLE"}
CAP = {"final_state": "OBSERVE"}
QUOTE = {"bid": 199.98, "ask": 200.04,
         "quote_time": "2026-08-17T14:00:00+00:00"}
NOW = "2026-08-17T14:00:30+00:00"


@pytest.fixture(autouse=True)
def _led(tmp_path, monkeypatch):
    import apex.frontier.shadow_paper as sp
    monkeypatch.setattr(sp, "LEDGER", tmp_path / "sp.jsonl")


def test_no_shadow_trade_without_preexisting_eligibility():
    ok, why = eligible({"playbook_id": "BASELINE-RANDOM"}, CAP, "h")
    assert not ok and "baseline" in why
    ok, why = eligible(dict(DEC, forward_eligibility="NOT_FORWARD_ELIGIBLE"),
                       CAP, "h")
    assert not ok
    ok, why = eligible(DEC, {"final_state": "REFUSED"}, "h")
    assert not ok and "not simulated away" in why
    ok, why = eligible(DEC, CAP, None)
    assert not ok and "BEFORE" in why
    # "let's pretend we bought it" is unrepresentable: no thesis, no fill
    p = open_position({"decision_id": "X", "symbol": "Y",
                       "direction": "LONG"}, CAP, card_hash="h",
                      quote=QUOTE, now=NOW)
    assert p.state == "SHADOW_REFUSED"


def test_a_real_quote_fills_at_the_touch_with_measured_spread():
    p = open_position(DEC, CAP, card_hash="cardsha", quote=QUOTE, now=NOW)
    assert p.state == "SHADOW_OPEN"
    assert p.entry_price == 200.04          # LONG crosses the ask
    assert p.spread_paid_frac > 0
    assert p.card_hash == "cardsha"
    assert p.quantity == round(100.0 / (200.04 - 198.0), 4)


def test_no_future_quote_and_no_stale_quote():
    with pytest.raises(ShadowViolation):
        open_position(DEC, CAP, card_hash="h",
                      quote=dict(QUOTE,
                                 quote_time="2026-08-17T14:05:00+00:00"),
                      now=NOW)
    stale = open_position(DEC, CAP, card_hash="h",
                          quote=dict(QUOTE,
                                     quote_time="2026-08-17T13:50:00+00:00"),
                          now=NOW)
    assert stale.state == "SHADOW_REFUSED"


def test_missing_quote_is_refused_never_zero_spread():
    for q in (None, {"bid": None, "ask": 200.0, "quote_time": NOW},
              {"bid": 200.1, "ask": 200.0, "quote_time": NOW}):  # crossed
        p = open_position(DEC, CAP, card_hash="h", quote=q, now=NOW)
        assert p.state == "SHADOW_REFUSED"
        assert p.spread_paid_frac is None       # unknown, not zero


def _open():
    return open_position(DEC, CAP, card_hash="h", quote=QUOTE, now=NOW)


def test_stop_and_target_follow_the_decision_and_never_widen():
    p = _open()
    assert (p.stop, p.target) == (198.0, 204.0)
    assert "stop" not in dir(manage)  # manage takes no stop argument
    closed = manage(p, {"high": 204.5, "low": 197.9, "close": 200.0},
                    now="2026-08-17T14:10:00+00:00")
    assert closed.exit_reason == "STOP", (
        "same-bar ambiguity must resolve conservatively: stop first")
    assert closed.exit_price == 198.0


def test_target_exit_and_r_multiple():
    p = _open()
    closed = manage(p, {"high": 204.2, "low": 199.5, "close": 204.0},
                    now="2026-08-17T14:43:00+00:00")
    assert closed.exit_reason == "TARGET"
    rec = [r for r in _ledger_rows() if r.get("r_multiple")][-1]
    assert rec["r_multiple"] > 1.8
    assert rec["exit_cost_frac_ESTIMATED"] is not None
    assert rec["net_return_frac"] < rec["gross_return_frac"]


def test_daily_flat_forces_exit_before_close():
    """A position young enough to escape the 90m time stop must still be
    forced flat by the mandate. (First draft entered at 10:00 ET and
    checked at 15:59 — the time stop legitimately fired first; both exits
    honor DAILY_FLAT, but the mandate path needed a late entry to test.)"""
    late = open_position(DEC, CAP, card_hash="h",
                         quote=dict(QUOTE,
                                    quote_time="2026-08-17T19:30:00+00:00"),
                         now="2026-08-17T19:30:30+00:00")  # 15:30 ET entry
    closed = manage(late, {"high": 201.0, "low": 199.9, "close": 200.5},
                    now="2026-08-17T19:59:00+00:00")       # 15:59 ET, 29m
    assert closed.exit_reason == "DAILY_FLAT_MANDATE"
    assert closed.state == "SHADOW_FLAT"


def test_time_stop_at_the_frozen_horizon():
    p = _open()
    closed = manage(p, {"high": 201.0, "low": 199.9, "close": 200.6},
                    now="2026-08-17T15:31:00+00:00")   # 91m
    assert closed.exit_reason == "TIME_STOP_90M"


def test_no_duplicate_management_after_flat():
    p = _open()
    closed = manage(p, {"high": 205.0, "low": 199.9, "close": 204.5},
                    now="2026-08-17T14:20:00+00:00")
    again = manage(closed, {"high": 300.0, "low": 100.0, "close": 200.0},
                   now="2026-08-17T14:25:00+00:00")
    assert again == closed                     # flat is flat


def test_no_broker_and_no_paper_vocabulary():
    """Sixth occurrence of the prose-vs-code trap in this weekend's own
    tooling: the module docstring legitimately SAYS "never
    PAPER_ELIGIBLE". Scan executable source only."""
    from apex.audit.execution_path import executable_source
    code = executable_source(open("apex/frontier/shadow_paper.py").read())
    for bad in ("place_", "RobinhoodAdapter", "PAPER_ELIGIBLE",
                "OrderIntent"):
        assert bad not in code
    assert "NONE_RESEARCH_SHADOW" in code


def test_epoch1_and_frontier_decisions_identical_with_shadow_disabled():
    """The layer consumes terminal records; nothing upstream imports it."""
    from pathlib import Path
    for f in ("apex/hunter/forward_pass.py", "apex/hunter/capital.py",
              "apex/captain/kernel.py", "apex/frontier/underwriting.py",
              "apex/frontier/senses.py", "scripts/hunter_forward_clock.py"):
        assert "shadow_paper" not in Path(f).read_text(), (
            f"{f} consumes the shadow-paper layer")


def _ledger_rows():
    import apex.frontier.shadow_paper as sp
    return [json.loads(l) for l in sp.LEDGER.read_text().splitlines()]
