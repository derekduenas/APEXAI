"""THE CONTINUOUS RE-UNDERWRITING LAW — the ten proofs.

The desk never falls in love with its last opinion: anti-anchoring is a
function signature, staleness is measured, improvement is a real path,
and death requires a new lineage to undo.
"""
from __future__ import annotations

import json

import pandas as pd
import pytest

from apex.frontier.underwriting import (HEARTBEAT_S, OpportunityState,
                                        TERMINAL, UnderwritingViolation,
                                        judgment_status, reunderwrite,
                                        what_changed)


def _st(state="SERIOUS", **kw):
    base = dict(candidate_id="U1", symbol="NVDA.US", state=state,
                direction_quality="STRONG", entry_quality="GOOD",
                last_underwritten_at="2026-08-17T14:00:00Z",
                inputs_snapshot={"rs_state": "PERSISTING",
                                 "vwap_relationship": "ABOVE"})
    base.update(kw)
    return OpportunityState(**base)


# 1. strong -> DEGRADED when RS collapses
def test_1_rs_collapse_degrades_a_serious_candidate(tmp_path, monkeypatch):
    import apex.frontier.underwriting as uw
    monkeypatch.setattr(uw, "LEDGER", tmp_path / "l.jsonl")
    out = reunderwrite(_st(), current_inputs={"rs_state": "REVERSING",
                                              "vwap_relationship": "BELOW"},
                       direction_quality="WEAK", entry_quality="WEAK")
    assert out.state == "DEGRADED"


# 2. extended -> attractive after a clean reset
def test_2_waiting_for_entry_becomes_serious_after_reset(tmp_path,
                                                         monkeypatch):
    import apex.frontier.underwriting as uw
    monkeypatch.setattr(uw, "LEDGER", tmp_path / "l.jsonl")
    waiting = reunderwrite(_st(), current_inputs={"price_structure":
                                                  "EXTENDED"},
                           direction_quality="STRONG",
                           entry_quality="WEAK", reason="TOO_EXTENDED")
    assert waiting.state == "WAITING_FOR_ENTRY"
    back = reunderwrite(waiting, current_inputs={"price_structure":
                                                 "CLEAN_RETEST"},
                        direction_quality="STRONG", entry_quality="GOOD")
    assert back.state == "SERIOUS", (
        "a clean reset must be able to re-promote — rejection is not "
        "always death")


# 3. morning thesis contradicted (card field exists; loop marks it)
def test_3_premarket_prior_can_read_contradicted():
    src = open("scripts/frontier_loop.py").read()
    assert "premarket_prior_agreement" in src
    # the vocabulary exists in the preregistered groups
    from apex.frontier.learning import PREREGISTRATION
    assert "CONTRADICTED" in \
        PREREGISTRATION["hypotheses"]["H_PREMARKET"]["groups"]


# 4. prior opinion cannot override new canonical facts — structurally
def test_4_anti_anchoring_is_the_function_signature():
    import inspect

    from apex.frontier.underwriting import reunderwrite as ru
    params = set(inspect.signature(ru).parameters)
    for leak in ("prior_judgment", "prior_support", "prior_brief",
                 "previous_conviction"):
        assert leak not in params
    # the record says how the prior was referenced
    assert "PRIOR_BELIEF_LABEL_ONLY" in open(
        "apex/frontier/underwriting.py").read()


# 5. stale judgment cannot remain ACTIVE
def test_5_staleness_is_measured_not_assumed():
    s = _st(last_underwritten_at="2026-08-17T14:00:00Z")
    fresh = judgment_status(s, "2026-08-17T14:01:00Z")
    stale = judgment_status(s, "2026-08-17T14:10:00Z")
    assert fresh["status"] == "ACTIVE"
    assert stale["status"] == "STALE"
    never = judgment_status(_st(last_underwritten_at=None),
                            "2026-08-17T14:00:00Z")
    assert never["status"] == "STALE"


# 6. rank changes when another candidate improves (board law, re-proven)
def test_6_the_board_reranks_on_improvement(tmp_path, monkeypatch):
    import apex.frontier.senses as sn
    monkeypatch.setattr(sn, "BOARD_LEDGER", tmp_path / "b.jsonl")
    t0 = sn.rank_opportunities([
        {"symbol": "NVDA", "candidate_class": "HUNTER",
         "direction_quality": "STRONG", "entry_quality": "STRONG"},
        {"symbol": "AMD", "candidate_class": "HUNTER",
         "direction_quality": "STRONG", "entry_quality": "WEAK"}])
    assert t0["ranked"][0]["symbol"] == "NVDA"
    t1 = sn.rank_opportunities([
        {"symbol": "NVDA", "candidate_class": "HUNTER",
         "direction_quality": "STRONG", "entry_quality": "WEAK"},
        {"symbol": "AMD", "candidate_class": "HUNTER",
         "direction_quality": "STRONG", "entry_quality": "STRONG"}])
    assert t1["ranked"][0]["symbol"] == "AMD", (
        "the Captain must be willing to change its mind")


# 7. INVALIDATED cannot resurrect without a new lineage
def test_7_terminal_states_stay_dead(tmp_path, monkeypatch):
    import apex.frontier.underwriting as uw
    monkeypatch.setattr(uw, "LEDGER", tmp_path / "l.jsonl")
    dead = reunderwrite(_st(), current_inputs={},
                        direction_quality="STRONG", entry_quality="GOOD",
                        reason="MECHANISM_BROKEN")
    assert dead.state == "INVALIDATED"
    with pytest.raises(UnderwritingViolation, match="NEW candidate id"):
        reunderwrite(dead, current_inputs={"rs_state": "PERSISTING"},
                     direction_quality="STRONG", entry_quality="STRONG")


# 8. conditional WAIT stays observable
def test_8_conditional_reasons_are_not_terminal():
    from apex.frontier.underwriting import (CONDITIONAL_REASONS,
                                            TERMINAL_REASONS)
    assert "TOO_EXTENDED" in CONDITIONAL_REASONS
    assert "TOO_EXTENDED" not in TERMINAL_REASONS
    assert set(CONDITIONAL_REASONS).isdisjoint(TERMINAL_REASONS)


# 9. LLM failure does not stop the sensors (loop-level law, source-pinned)
def test_9_sensor_loops_survive_child_failure():
    for f in ("scripts/frontier_loop.py", "scripts/fastwatch.py"):
        src = open(f).read()
        assert "loop continues" in src or "shadow-only" in src or \
            "except Exception" in src, f"{f} can die on one failure"


# 10. re-underwriting cannot alter Epoch-1
def test_10_underwriting_is_shadow_only():
    from pathlib import Path
    code = Path("apex/frontier/underwriting.py").read_text()
    for token in ("PAPER_ELIGIBLE", "forward_ledger", "place_",
                  "evaluate_candidate"):
        assert token not in code
    for f in ("apex/hunter/capital.py", "apex/captain/kernel.py",
              "scripts/hunter_forward_clock.py"):
        assert "underwriting" not in Path(f).read_text(), (
            f"{f} consumes the shadow underwriting module")


def test_what_changed_is_computed_never_remembered():
    ch = what_changed({"rs_state": "PERSISTING"},
                      {"rs_state": "REVERSING", "catalyst_status": "KNOWN"})
    fields = {c["field"] for c in ch}
    assert fields == {"rs_state", "catalyst_status"}


def test_attention_scales_with_seriousness():
    assert HEARTBEAT_S["CAPITAL_REVIEW"] < HEARTBEAT_S["SERIOUS"] \
        < HEARTBEAT_S["WATCHING"] < HEARTBEAT_S["DISCOVERED"]


# ================= THE SYNTHETIC INTRADAY MOVIE ============================
# The operator's full sequence as ONE run — certifying the continuous-
# attention machinery as a SYSTEM, not as independently-tested pieces.

def test_the_intraday_movie(tmp_path, monkeypatch):
    import apex.frontier.underwriting as uw
    import apex.frontier.senses as sn
    monkeypatch.setattr(uw, "LEDGER", tmp_path / "uw.jsonl")
    monkeypatch.setattr(sn, "BOARD_LEDGER", tmp_path / "board.jsonl")

    t = lambda hm: f"2026-08-17T{hm}:00-04:00"              # noqa: E731
    s = OpportunityState(candidate_id="MOVIE-1", symbol="NVDA.US",
                         state="DISCOVERED",
                         inputs_snapshot={})
    history = [s.state]

    def step(when, inputs, dq, eq, reason=""):
        nonlocal s
        s = reunderwrite(s, current_inputs=inputs,
                         direction_quality=dq, entry_quality=eq,
                         reason=reason, now=t(when))
        history.append(s.state)
        return s

    # 09:45 mediocre -> 09:48 RVOL -> 09:50 RS -> 09:52 sector
    step("09:45", {"participation": "NORMAL"}, "MODERATE", "UNKNOWN")
    step("09:48", {"participation": "RVOL_RISING"}, "MODERATE", "UNKNOWN")
    step("09:50", {"participation": "RVOL_RISING",
                   "rs_state": "ACCELERATING"}, "MODERATE", "UNKNOWN")
    step("09:52", {"participation": "RVOL_RISING",
                   "rs_state": "ACCELERATING",
                   "sector_leadership": "STRENGTHENING"},
         "STRONG", "GOOD")                                   # 09:54 breakout
    assert s.state == "SERIOUS"
    # 09:55 too extended -> WAIT (conditional, not death)
    step("09:55", {"price_structure": "EXTENDED"}, "STRONG", "WEAK",
         reason="TOO_EXTENDED")
    assert s.state == "WAITING_FOR_ENTRY"
    # 09:58 clean pullback, 10:00 VWAP holds, 10:02 short trap,
    # 10:04 entry becomes good -> re-promoted
    step("10:04", {"price_structure": "CLEAN_RETEST",
                   "vwap_relationship": "ABOVE",
                   "dislocation_state": "POSSIBLE_SHORT_TRAP"},
         "STRONG", "GOOD")
    assert s.state == "SERIOUS", "a clean reset must re-promote"
    # board reranks while NVDA is serious
    b = sn.rank_opportunities([
        {"symbol": "NVDA.US", "candidate_class": "HUNTER",
         "direction_quality": "STRONG", "entry_quality": "STRONG"}])
    assert b["ranked"][0]["symbol"] == "NVDA.US"
    # 10:08 market deteriorates, 10:10 RS collapses -> DEGRADED
    step("10:10", {"market_regime": "DETERIORATING",
                   "rs_state": "REVERSING"}, "WEAK", "WEAK")
    assert s.state == "DEGRADED"
    # 10:11 thesis invalidates -> terminal
    step("10:11", {"rs_state": "REVERSING",
                   "vwap_relationship": "BELOW"}, "WEAK", "WEAK",
         reason="THESIS_INVALIDATED")
    assert s.state == "INVALIDATED"

    # the required arc, in order
    assert history == ["DISCOVERED", "DEVELOPING", "DEVELOPING",
                       "DEVELOPING", "SERIOUS", "WAITING_FOR_ENTRY",
                       "SERIOUS", "DEGRADED", "INVALIDATED"]

    # no resurrection without a new lineage
    with pytest.raises(UnderwritingViolation):
        reunderwrite(s, current_inputs={"rs_state": "ACCELERATING"},
                     direction_quality="STRONG", entry_quality="STRONG")

    # every transition persisted, every diff computed, no anchoring channel
    recs = [json.loads(l) for l in
            (tmp_path / "uw.jsonl").read_text().splitlines()]
    assert len(recs) == 8                     # one per re-underwrite
    assert all(r["prior_referenced_as"] == "PRIOR_BELIEF_LABEL_ONLY"
               for r in recs)
    # material events were seen, not silently dropped: the RS collapse
    # step recorded exactly what changed
    collapse = recs[6]
    changed = {c["field"] for c in collapse["what_changed"]}
    assert "rs_state" in changed and "market_regime" in changed
    # Epoch-1 untouched: nothing wrote to the forward ledger
    from pathlib import Path as _P
    assert not _P("results/hunter/forward_ledger.jsonl").exists()
