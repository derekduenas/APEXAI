"""THE CAPTAIN'S CONSTITUTION, as executable law.

Captain commands the desk. Capital commands the money. Risk vetoes the
Captain. The Assassin wounds its thesis. The trade manager owns the
position. The CIO advises and can never rule.
"""

from __future__ import annotations

import pytest

from apex.captain import board as boardmod
from apex.captain.cio import CIOAdvice, apply_to_kernel
from apex.captain.conviction import ConvictionState, from_pipeline
from apex.captain.kernel import CAPTAIN_VERSION, assess

CAND = {"decision_id": "d1", "symbol": "AMD", "t_utc": "2026-08-17T14:30:00Z",
        "playbook_id": "HUNTER-001_v1", "direction": "LONG",
        "risk_frac": 0.006}
BUNDLE_MONDAY = {"analog_view": {"status": "NO_VALID_ANALOGS"},
                 "ml_view": {"status": "UNTRAINED"},
                 "swarm_view": {"status": "BLOCKED_EXTERNAL_AUTH"},
                 "disagreement": {"level": "UNMEASURABLE"},
                 "distribution_source_status": "REFUSED"}
CAP_OBSERVE = {"final_state": "OBSERVE",
               "reason_codes": ["NO_CALIBRATED_FORECAST", "COST_UNKNOWN"],
               "gates": {"regime_uncertain": False}}


# ---- CONSTITUTION 1: the Captain cannot touch money
def test_captain_cannot_authorize_size_or_move_stops():
    import apex.captain.kernel as k
    src = open(k.__file__).read()
    for forbidden in ("place_order", "authorize_paper", "PAPER_ELIGIBLE =",
                      "def size", "tighten_stop", "current_stop"):
        assert forbidden not in src, f"kernel must not contain {forbidden}"
    st = assess(CAND, BUNDLE_MONDAY, {"verdict": "SURVIVED_CLEAN"},
                CAP_OBSERVE)
    rec = st.as_record()
    assert rec["capital_is_sovereign"] is True
    assert rec["decision_power"] == "NONE_OBSERVATIONAL_EPOCH1"
    assert "weight" not in rec and "stop" not in rec


def test_capital_refusal_stands_regardless_of_captain_enthusiasm():
    """Even a perfect desk state cannot survive a Capital NO_TRADE."""
    perfect = dict(BUNDLE_MONDAY, analog_view={"status": "OK"},
                   ml_view={"status": "FORWARD_EVALUATING",
                            "p_positive": 0.7},
                   disagreement={"level": "NONE"},
                   distribution_source_status="ML_UNCALIBRATED")
    killed = {"final_state": "NO_TRADE",
              "reason_codes": ["RISK_LIMIT"], "gates": {}}
    st = assess(CAND, perfect, {"verdict": "SURVIVED_CLEAN"}, killed)
    assert st.next_action == "STAND_DOWN"
    assert "re-litigate a Capital refusal" in st.do_not


def test_risk_veto_and_assassin_wound_dominate_quality():
    wounded = assess(CAND, BUNDLE_MONDAY,
                     {"verdict": "SURVIVED_WOUNDED"}, CAP_OBSERVE)
    assert wounded.opportunity_quality == "COMPROMISED"
    assert wounded.next_action == "WATCH_FOR_RE_ENTRY"
    assert wounded.recommended_intelligence_spend == "FAST_ONLY"
    assert "chase the current price" in wounded.do_not


# ---- CONSTITUTION 2: the CIO advises, never rules
def test_cio_cannot_change_a_kernel_directive():
    st = assess(CAND, BUNDLE_MONDAY, {"verdict": "SURVIVED_CLEAN"},
                CAP_OBSERVE)
    advice = CIOAdvice(decision_id="d1", status="OK",
                       synthesis="exceptional, size up immediately",
                       next_research_question="none",
                       deep_research_worthwhile=True)
    merged = apply_to_kernel(st, advice)
    assert merged["next_action"] == st.next_action
    assert merged["recommended_intelligence_spend"] == \
        st.recommended_intelligence_spend
    assert merged["cio_changed_directive"] is False
    assert merged["cio_advice"]["advisory_only"] is True


def test_cio_contract_refuses_authority_claims():
    with pytest.raises(ValueError):
        CIOAdvice(decision_id="x", status="OK", can_authorize=True)
    with pytest.raises(ValueError):
        CIOAdvice(decision_id="x", status="OK", can_size=True)
    with pytest.raises(ValueError):
        CIOAdvice(decision_id="x", status="OK", can_move_stops=True)
    with pytest.raises(ValueError):        # non-OK carries no content
        CIOAdvice(decision_id="x", status="FAILED", synthesis="but here")


# ---- CONSTITUTION 3: conviction is structured, never a magic score
def test_conviction_has_no_scalar_score_and_unknown_is_real():
    c = from_pipeline(CAND, BUNDLE_MONDAY, None, None)
    rec = c.as_record()
    assert not any(isinstance(v, (int, float)) for v in rec.values())
    assert "calibration" in c.unknowns and "ml_evidence" in c.unknowns
    with pytest.raises(ValueError):
        ConvictionState(mechanism="AMAZING")     # undeclared level


def test_exceptional_class_is_unreachable_without_calibration():
    """The rare-dislocation class cannot be claimed on a story."""
    story = ConvictionState(mechanism="STRONG", scenario_shape="ASYMMETRIC",
                            assassin="CLEAN", entry_quality="STRONG",
                            tail_risk="ACCEPTABLE", disagreement="LOW")
    cls = story.classify()
    assert cls["class"] == "ORDINARY_OPPORTUNITY"
    assert any("calibration" in u for u in cls["unmet"])
    earned = ConvictionState(mechanism="STRONG", scenario_shape="ASYMMETRIC",
                             assassin="CLEAN", entry_quality="STRONG",
                             tail_risk="ACCEPTABLE", disagreement="LOW",
                             calibration="STRONG")
    assert earned.classify()["class"] == "EXCEPTIONAL_ASYMMETRY"


# ---- CONSTITUTION 4: anti-paralysis is a duty
def test_captain_proceeds_when_evidence_genuinely_aligns():
    aligned = dict(BUNDLE_MONDAY, analog_view={"status": "OK"},
                   ml_view={"status": "FORWARD_EVALUATING",
                            "p_positive": 0.68},
                   disagreement={"level": "NONE"},
                   distribution_source_status="ML_UNCALIBRATED")
    cap = {"final_state": "OBSERVE", "reason_codes": [],
           "gates": {"regime_uncertain": False}}
    cand = dict(CAND, risk_frac=0.004)
    st = assess(cand, aligned, {"verdict": "SURVIVED_CLEAN"}, cap,
                persistence={"status": "PERSISTENCE_MEASURED",
                             "edge_persistence_horizon_minutes": 60})
    assert st.next_action == "PROCEED_TO_CAPITAL"
    assert "exceed Capital's verdict" in st.do_not     # still not money


def test_intelligence_spend_follows_persistence_and_only_shrinks():
    # an ASSESSABLE candidate (Monday-state candidates are unassessable
    # and correctly never buy deep thought — that is asserted below)
    ok_bundle = dict(BUNDLE_MONDAY, analog_view={"status": "OK"},
                     ml_view={"status": "FORWARD_EVALUATING"},
                     disagreement={"level": "NONE"},
                     distribution_source_status="ML_UNCALIBRATED")
    fast = assess(CAND, ok_bundle, {"verdict": "SURVIVED_CLEAN"},
                  CAP_OBSERVE,
                  persistence={"status": "PERSISTENCE_MEASURED",
                               "edge_persistence_horizon_minutes": 20})
    deep = assess(CAND, ok_bundle, {"verdict": "SURVIVED_CLEAN"},
                  CAP_OBSERVE,
                  persistence={"status": "PERSISTENCE_MEASURED",
                               "edge_persistence_horizon_minutes": 90})
    monday = assess(CAND, BUNDLE_MONDAY, {"verdict": "SURVIVED_CLEAN"},
                    CAP_OBSERVE,
                    persistence={"status": "PERSISTENCE_MEASURED",
                                 "edge_persistence_horizon_minutes": 240})
    assert monday.opportunity_quality == \
        "UNASSESSABLE_INSUFFICIENT_EVIDENCE"
    assert monday.recommended_intelligence_spend == "FAST_ONLY"
    unknown = assess(CAND, BUNDLE_MONDAY, {"verdict": "SURVIVED_CLEAN"},
                     CAP_OBSERVE)
    assert fast.recommended_intelligence_spend == "FAST_ONLY"
    assert deep.recommended_intelligence_spend == "DEEP_ELIGIBLE"
    assert unknown.alpha_persistence == "NOT_YET_ESTIMABLE"
    # a compromised thesis never buys deep thought, whatever the horizon
    comp = assess(CAND, ok_bundle, {"verdict": "SURVIVED_WOUNDED"},
                  CAP_OBSERVE,
                  persistence={"status": "PERSISTENCE_MEASURED",
                               "edge_persistence_horizon_minutes": 240})
    assert comp.recommended_intelligence_spend == "FAST_ONLY"


# ---- CONSTITUTION 5: the board ranks, Capital allocates
def test_board_ranks_and_retains_rejects_without_allocating():
    good = assess(dict(CAND, decision_id="a", symbol="AMD",
                       risk_frac=0.004),
                  dict(BUNDLE_MONDAY, analog_view={"status": "OK"},
                       disagreement={"level": "NONE"}),
                  {"verdict": "SURVIVED_CLEAN"}, CAP_OBSERVE)
    wounded = assess(dict(CAND, decision_id="b", symbol="META"),
                     BUNDLE_MONDAY, {"verdict": "SURVIVED_WOUNDED"},
                     CAP_OBSERVE)
    thin = assess(dict(CAND, decision_id="c", symbol="TSLA"),
                  BUNDLE_MONDAY, {"verdict": "SURVIVED_CLEAN"},
                  CAP_OBSERVE)
    b = boardmod.build([wounded, thin, good], t_utc="2026-08-17T14:30:00Z")
    ranks = [e.symbol for e in b.entries]
    assert ranks[0] == "AMD"                    # clean+supported first
    assert "META" in ranks                      # rejects RETAINED
    assert b.n_candidates == 3
    rec = b.as_record()
    assert "ALLOCATION IS MONEY" in rec["allocation_note"]
    assert not any("weight" in str(e) or "notional" in str(e)
                   for e in rec["entries"])     # board never sizes


def test_board_ordering_is_deterministic():
    states = [assess(dict(CAND, decision_id=i, symbol=f"S{i}"),
                     BUNDLE_MONDAY, {"verdict": "SURVIVED_CLEAN"},
                     CAP_OBSERVE) for i in ("x", "y", "z")]
    a = boardmod.build(states)
    b = boardmod.build(list(reversed(states)))
    assert [e.decision_id for e in a.entries] == \
        [e.decision_id for e in b.entries]


def test_captain_version_is_stamped():
    st = assess(CAND, BUNDLE_MONDAY, None, None)
    assert st.as_record()["version"] == CAPTAIN_VERSION
    assert st.as_record()["kind"] == "captain_state"
