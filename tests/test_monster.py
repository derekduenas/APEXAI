"""Monster V1 -- contract and shadow-authority tests."""
from apex.monster.consult import consult
from apex.monster.event_expert import EventRecord, evaluate


def ev(**kw):
    base = dict(symbol="XYZ", report_date="2026-09-01", timing="pm",
                eps_estimate=1.00, eps_actual=0.80,
                consensus_provenance="BROKER_REPORTED_CONSENSUS_RH_MCP",
                known_from="2026-09-01T21:05:00Z",
                reaction_session="2026-09-02")
    base.update(kw)
    return EventRecord(**base)


def test_positive_surprise_refused_and_recorded():
    opp, opinion = evaluate(ev(eps_actual=1.20))
    assert opp is None
    assert opinion["refusal"] == "NOT_NEGATIVE_SURPRISE"
    assert opinion["surprise_class"] == "POSITIVE"


def test_missing_estimate_is_unknown_not_zero():
    opp, opinion = evaluate(ev(eps_estimate=None))
    assert opp is None
    assert opinion["refusal"] == "NO_ESTIMATE"
    assert opinion["surprise_class"] == "UNKNOWN_NO_ESTIMATE"


def test_am_timing_refused_not_assumed_post_information():
    opp, opinion = evaluate(ev(timing="am"))
    assert opp is None
    assert opinion["refusal"] == "TIMING_NOT_CERTIFIABLE_AM"


def test_valid_negative_pm_emits_shadow_only_opportunity():
    opp, opinion = evaluate(ev(), rt_cost_bps=12.0)
    assert opinion["emitted"]
    assert opp.direction == "SHORT"
    assert opp.attack_class == "NO_TRADE"
    assert opp.authority_eligibility == "OBSERVE_ONLY"
    assert opp.forecast_pedigree[
        "incremental_information_value"] == "UNPROVEN"
    assert opp.forecast_pedigree["expected_net_bps"] == 38.6 - 12.0


def test_unknown_cost_stays_not_estimable():
    opp, _ = evaluate(ev())
    assert opp.forecast_pedigree["rt_cost_bps"] == "NOT_ESTIMABLE"
    assert opp.forecast_pedigree["expected_net_bps"] == "NOT_ESTIMABLE"


def test_consult_preserves_honest_expert_states():
    rec = consult(ev(), rt_cost_bps=12.0)
    states = {n: e["state"] for n, e in rec["experts"].items()}
    assert states["EVENT_PM_FADE"] == "ACTIVE"
    assert states["EVENT_NEG_SURPRISE_INCREMENT"] == "ACTIVE"
    assert states["CONTINUATION"] == "NOT_IMPLEMENTED"
    assert states["STATISTICAL_H5"] == "NOT_CONSULTED"
    assert rec["mechanism_agreement"] == \
        "RELATED_EXPERTS_NOT_INDEPENDENT"
    assert rec["decision_power"] == "SHADOW"


def test_a2_never_inherits_a1_credit():
    rec = consult(ev(), rt_cost_bps=12.0)
    th = rec["physical_thesis"]
    assert th["base_pm_fade_gross_bps"] == 19.6
    assert th["neg_surprise_incremental_gross_bps"] == 23.4
    assert th["incremental_status"] == "UNPROVEN"
    assert th["combined_gross_bps"] == 19.6 + 23.4


def test_positive_surprise_still_gets_a1_fade_only():
    rec = consult(ev(eps_actual=1.20), rt_cost_bps=12.0)
    states = {n: e["state"] for n, e in rec["experts"].items()}
    assert states["EVENT_PM_FADE"] == "ACTIVE"
    assert states["EVENT_NEG_SURPRISE_INCREMENT"] == "REFUSED"
    th = rec["physical_thesis"]
    assert th["base_pm_fade_gross_bps"] == 19.6
    assert th["neg_surprise_incremental_gross_bps"] == \
        "NOT_APPLICABLE"


def test_am_event_no_thesis_from_either_expert():
    rec = consult(ev(timing="am"), rt_cost_bps=12.0)
    assert rec["physical_thesis"] == "NONE"
    assert rec["final"] == "NO_TRADE"


def test_consult_final_capped_at_watch_without_authority():
    rec = consult(ev(), rt_cost_bps=12.0)
    assert rec["final"] in ("WATCH", "NO_TRADE")
    assert rec["final"] != "ATTACK"


def test_cash_wins_when_costs_eat_the_edge():
    rec = consult(ev(), rt_cost_bps=60.0)   # cost > gross 38.6
    assert rec["best_expression"] == "CASH"
    assert rec["final"] == "NO_TRADE"


def test_no_shorting_broker_forces_cash_without_option_quotes():
    rec = consult(ev(), rt_cost_bps=12.0, short_allowed=False)
    # short-stock is benchmark-only; puts have no quotes -> CASH
    assert rec["best_expression"] == "CASH"
    assert rec["expressions"]["LONG_PUT"]["status"] == "NOT_ESTIMABLE"


def test_short_allowed_makes_short_best_when_net_positive():
    rec = consult(ev(), rt_cost_bps=12.0, short_allowed=True)
    assert rec["best_expression"] == "SHORT_STOCK_BENCHMARK"
    assert rec["final"] == "WATCH"
    assert rec["arena"]["decisions"][0]["edge_pedigree"] == "REPLAY_ONLY"
