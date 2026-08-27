"""ACCEPTANCE — Catalyst Intelligence + Capital Arena.

Both are SHADOW. The tests that matter most are the ones proving they
cannot touch V1, cannot see the future, and cannot turn an
interpretation into a fact.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from apex.capital import AUTHORITY as CAPITAL_AUTHORITY
from apex.capital.arena import (Candidate, CapitalViolation,
                                PortfolioState, compete, redundancy,
                                tail_dependence)
from apex.capital.counterfactual import (CounterfactualViolation,
                                         append_outcome, compare,
                                         seal_decision)
from apex.catalyst import AUTHORITY as CATALYST_AUTHORITY
from apex.catalyst.brain import (FORBIDDEN_FIELDS, PROMPT_CONTRACT_SHA,
                                 hypothesis_is_falsifiable,
                                 validate_interpretation)
from apex.catalyst.events import (CatalystEvent, CatalystViolation,
                                  SourceObservation, compute_surprise,
                                  dedup_key, verify)
from apex.catalyst.premarket import (WatchState, catalyst_environment,
                                     phase_at, pre_bell_brief)
from apex.catalyst.reaction import (classify, disagreement, measure)


# ==================================================== SOURCE PROVENANCE

def _obs(**kw):
    base = dict(source="Federal Reserve", source_authority="PRIMARY_OFFICIAL",
                source_ref="https://federalreserve.gov/x",
                headline="FOMC holds rates", published_time="2026-08-27T18:00:00Z",
                retrieval_time="2026-08-27T18:00:30Z")
    base.update(kw)
    return SourceObservation(**base)


def test_news_says_is_not_provenance():
    with pytest.raises(CatalystViolation, match="not provenance"):
        _obs(source_ref="")


def test_unknown_source_authority_is_refused():
    with pytest.raises(CatalystViolation, match="source_authority"):
        _obs(source_authority="SOME_BLOG_I_LIKE")


# ==================================================== DEDUP

def test_one_event_is_not_a_hundred_catalysts():
    """Wire furniture must not create independent observations."""
    a = dedup_key(event_type="CENTRAL_BANK", subjects=("SPY",),
                  headline="BREAKING: Fed holds rates steady",
                  day="2026-08-27")
    b = dedup_key(event_type="CENTRAL_BANK", subjects=("SPY",),
                  headline="UPDATE 2: Fed holds rates steady",
                  day="2026-08-27")
    assert a == b
    c = dedup_key(event_type="EARNINGS", subjects=("AAPL",),
                  headline="Apple beats on revenue", day="2026-08-27")
    assert c != a


def test_new_sources_update_an_event_they_do_not_clone_it():
    ev = CatalystEvent(
        event_id="EV_1", event_type="CENTRAL_BANK",
        event_time="2026-08-27T18:00:00Z",
        first_seen="2026-08-27T18:00:30Z",
        known_from="2026-08-27T18:00:30Z", scheduled=True,
        headline="FOMC holds", factual_summary="Rates unchanged.")
    u1 = ev.add_observation(_obs(source="Reuters",
                                 source_authority="WIRE",
                                 source_ref="reuters:1"))
    u2 = ev.add_observation(_obs(source="Bloomberg",
                                 source_authority="WIRE",
                                 source_ref="bbg:1"))
    assert u1["kind"] == "event_update" and u2["kind"] == "event_update"
    assert u2["observation_count"] == 2
    assert "a hundred headlines are one event" in u2["law"]


# ==================================================== CAUSALITY

def test_known_from_may_not_precede_first_seen():
    """A Fed decision at 14:00 seen at 14:03 is knowable from 14:03."""
    with pytest.raises(CatalystViolation, match="before it observed"):
        CatalystEvent(
            event_id="EV_2", event_type="CENTRAL_BANK",
            event_time="2026-08-27T18:00:00Z",
            first_seen="2026-08-27T18:03:00Z",
            known_from="2026-08-27T18:00:00Z",   # the future
            scheduled=True, headline="h", factual_summary="s")


def test_reaction_is_measured_from_known_from_not_event_time():
    kf = "2026-08-27T18:03:00Z"
    bars = [{"event_time_utc": "2026-08-27T18:01:00Z", "open": 100,
             "high": 105, "low": 100, "close": 105, "volume": 9},
            {"event_time_utc": "2026-08-27T18:05:00Z", "open": 105,
             "high": 106, "low": 104, "close": 106, "volume": 9},
            {"event_time_utc": "2026-08-27T19:00:00Z", "open": 106,
             "high": 107, "low": 105, "close": 107, "volume": 9}]
    r = measure(bars=bars, known_from=kf, atr=1.0,
                session_close="2026-08-27T20:00:00Z")
    # the 18:01 bar (between event and observation) must be excluded
    assert r["reference_price"] == 105
    assert r["n_bars"] == 2


def test_after_hours_prints_never_enter_the_reaction():
    bars = [{"event_time_utc": "2026-08-27T19:00:00Z", "open": 100,
             "high": 100, "low": 100, "close": 100, "volume": 1},
            {"event_time_utc": "2026-08-27T20:30:00Z", "open": 200,
             "high": 200, "low": 200, "close": 200, "volume": 1}]
    r = measure(bars=bars, known_from="2026-08-27T18:00:00Z", atr=1.0,
                session_close="2026-08-27T20:00:00Z")
    assert r["n_bars"] == 1


# ==================================================== THE LLM FENCE

def test_the_brain_may_not_compute_a_surprise():
    with pytest.raises(CatalystViolation, match="fabricated number"):
        validate_interpretation({"event_type": "MACRO_RELEASE",
                                 "surprise": 0.3},
                                available_source_refs=("a",))


def test_the_brain_may_not_claim_authority_or_trade():
    for field in ("authority", "verdict", "trade", "attackable",
                  "direction"):
        with pytest.raises(CatalystViolation, match="past the fence"):
            validate_interpretation({"event_type": "OTHER", field: "x"},
                                    available_source_refs=("a",))


def test_a_scalar_confidence_is_forbidden_on_purpose():
    assert "confidence_score" in FORBIDDEN_FIELDS
    with pytest.raises(CatalystViolation, match="past the fence"):
        validate_interpretation(
            {"event_type": "OTHER", "confidence_score": 0.9},
            available_source_refs=("a",))


def test_the_contract_is_a_whitelist_not_a_blocklist():
    with pytest.raises(CatalystViolation, match="undeclared"):
        validate_interpretation(
            {"event_type": "OTHER", "some_new_idea": 1},
            available_source_refs=("a",))


def test_a_summary_without_a_cited_source_is_refused():
    with pytest.raises(CatalystViolation, match="news says"):
        validate_interpretation(
            {"event_type": "OTHER", "factual_summary": "Big news."},
            available_source_refs=("a",))


def test_the_brain_cannot_cite_documents_it_was_never_given():
    """The hallucination that matters most: a plausible citation."""
    with pytest.raises(CatalystViolation, match="never retrieved"):
        validate_interpretation(
            {"event_type": "OTHER", "factual_summary": "x",
             "cited_source_refs": ["https://invented.example/story"]},
            available_source_refs=("https://real.example/1",))


def test_a_valid_interpretation_carries_its_prompt_version():
    v = validate_interpretation(
        {"event_type": "EARNINGS", "factual_summary": "Beat.",
         "cited_source_refs": ["ir:1"], "directional_expectation":
         "POSITIVE", "importance": "HIGH"},
        available_source_refs=("ir:1",))
    assert v["prompt_contract_sha"] == PROMPT_CONTRACT_SHA
    assert v["decision_power"] == "SHADOW_CONTEXT_ONLY"


def test_a_mechanism_without_a_falsifier_is_a_story():
    assert not hypothesis_is_falsifiable({"mechanism": "rates matter"})
    assert hypothesis_is_falsifiable(
        {"mechanism": "rates matter",
         "would_be_wrong_if": "yields rise and the stock rallies"})


# ==================================================== SURPRISE IS MATH

def test_surprise_is_deterministic_and_refuses_invention():
    s = compute_surprise(actual=3.1, consensus=2.8)
    assert s["surprise"] == pytest.approx(0.3)
    assert s["computed_by"] == "DETERMINISTIC_ARITHMETIC"
    n = compute_surprise(actual=3.1, consensus=None)
    assert n["surprise"] == "NOT_ESTIMABLE"
    assert "invented consensus" in n["why"]


def test_verification_requires_a_fact_bearing_source():
    ev = CatalystEvent(event_id="E", event_type="OTHER",
                       event_time="2026-08-27T18:00:00Z",
                       first_seen="2026-08-27T18:00:00Z",
                       known_from="2026-08-27T18:00:00Z",
                       scheduled=False, headline="h",
                       factual_summary="s")
    ev.add_observation(_obs(source="SomeAggregator",
                            source_authority="AGGREGATOR",
                            source_ref="agg:1"))
    assert verify(ev) == "UNVERIFIED"
    ev.add_observation(_obs(source="SEC", source_authority="PRIMARY_OFFICIAL",
                            source_ref="sec:1"))
    assert verify(ev) == "VERIFIED"
    assert verify(ev, conflicting=True) == "CONFLICTED"


# ==================================================== REACTION CLASSES

def _flat_then(bars_close):
    out, t = [], datetime(2026, 8, 27, 18, 0, tzinfo=timezone.utc)
    for i, c in enumerate(bars_close):
        tt = t + timedelta(minutes=i + 1)
        out.append({"event_time_utc": tt.isoformat().replace(
            "+00:00", "Z"), "open": c, "high": c + 0.01,
            "low": c - 0.01, "close": c, "volume": 100})
    return out


def test_good_news_that_cannot_rally_is_a_failed_positive_reaction():
    """THE PATTERN THIS PACKAGE EXISTS FOR."""
    bars = _flat_then([100.0] * 20)
    r = measure(bars=bars, known_from="2026-08-27T18:00:00Z", atr=1.0,
                session_close="2026-08-27T20:00:00Z")
    c = classify(expectation="POSITIVE", reaction=r, atr=1.0)
    assert c["reaction_class"] == "FAILED_POSITIVE_REACTION"
    d = disagreement(event=type("E", (), {"event_id": "E1",
                                          "event_type": "EARNINGS"})(),
                     reaction_class=c["reaction_class"])
    assert d["status"] == "RESEARCH_CANDIDATE"
    assert d["not_tradeable"] is True


def test_an_ordinary_confirming_move_is_not_flagged_as_interesting():
    bars = _flat_then([100 + i * 0.05 for i in range(20)])
    r = measure(bars=bars, known_from="2026-08-27T18:00:00Z", atr=1.0,
                session_close="2026-08-27T20:00:00Z")
    c = classify(expectation="POSITIVE", reaction=r, atr=1.0)
    assert disagreement(event=type("E", (), {"event_id": "E",
                                             "event_type": "OTHER"})(),
                        reaction_class=c["reaction_class"]) is None


def test_every_reaction_label_is_explicitly_non_alpha():
    bars = _flat_then([100.0] * 20)
    r = measure(bars=bars, known_from="2026-08-27T18:00:00Z", atr=1.0,
                session_close="2026-08-27T20:00:00Z")
    c = classify(expectation="POSITIVE", reaction=r, atr=1.0)
    assert "zero assumed alpha" in c["law"]


# ==================================================== PREMARKET

def _bounds(session="2026-08-27"):
    from apex.ops.orchestrator import session_bounds
    return session_bounds(session)


def test_the_catalyst_day_walks_its_phases_in_order():
    b = _bounds()
    seen = []
    t = b["open_utc"] - timedelta(hours=4)
    while t < b["close_utc"] + timedelta(hours=2):
        p = phase_at(t, "2026-08-27", open_utc=b["open_utc"],
                     close_utc=b["close_utc"], trading_day=True)["phase"]
        if not seen or seen[-1] != p:
            seen.append(p)
        t += timedelta(minutes=5)
    assert seen == ["IDLE", "OVERNIGHT_SCAN", "MACRO_UPDATE",
                    "PRE_BELL_BRIEF", "INTRADAY_WATCH",
                    "POST_CLOSE_SEAL", "IDLE"]


def test_a_holiday_never_reaches_a_catalyst_phase():
    p = phase_at(datetime(2026, 11, 26, 14, 0, tzinfo=timezone.utc),
                 "2026-11-26", open_utc=None, close_utc=None,
                 trading_day=False)
    assert p["phase"] == "IDLE"


def test_the_brain_runs_only_when_something_new_appeared():
    """Detection is cheap; interpretation is not. Polling an LLM every
    three minutes to ask 'did anything happen' is the design error."""
    w = WatchState()
    r1 = w.poll(["a", "b"])
    r2 = w.poll(["a", "b"])          # nothing new
    r3 = w.poll(["a", "b", "c"])     # one new
    assert r1["invoke_brain"] is True
    assert r2["invoke_brain"] is False and r2["n_new"] == 0
    assert r3["invoke_brain"] is True and r3["new_source_refs"] == ["c"]
    assert w.interpretations_invoked == 2 and w.polls == 3


def test_a_brief_must_state_what_it_does_not_know():
    env = catalyst_environment(scheduled_today=[], unscheduled_overnight=[])
    b = pre_bell_brief(session="2026-08-27", overnight={},
                       scheduled_today=[], universe_events={},
                       environment=env, unknowns=["overnight Asia flows"])
    assert b["changes_v1"] is False
    assert b["what_we_do_not_know"]
    assert "narrative" in b["law"]


def test_catalyst_environment_is_descriptive_only():
    e = catalyst_environment(
        scheduled_today=[{"importance": "CRITICAL"}],
        unscheduled_overnight=[])
    assert e["environment"] == "EVENT_HEAVY"
    assert "V1 never reads this" in e["law"]


# ==================================================== CAPITAL ARENA

def _cand(cid, sym, risk=300.0, direction="LONG", **kw):
    return Candidate(candidate_id=cid, symbol=sym, direction=direction,
                     expression="CALL_VERTICAL", declared_risk=risk,
                     **kw)


def test_three_tickers_can_be_one_bet():
    """THE FAILURE CAPITAL ARENA EXISTS TO CATCH."""
    pf = PortfolioState(available_capital=5000.0)
    cands = [_cand("c1", "SPY"), _cand("c2", "QQQ"), _cand("c3", "NVDA")]
    r = compete(candidates=cands, portfolio=pf, session_minutes_left=300)
    actions = {d["symbol"]: d["action"] for d in r["decisions"]}
    assert list(actions.values()).count("REFUSE_REDUNDANT") >= 1
    refused = [d for d in r["decisions"]
               if d["action"] == "REFUSE_REDUNDANT"][0]
    assert "one US_LARGE_BETA bet wearing" in " ".join(refused["reasons"])


def test_genuinely_independent_candidates_are_not_refused():
    pf = PortfolioState(available_capital=5000.0)
    r = compete(candidates=[_cand("c1", "SPY"),
                            _cand("c2", "IWM", direction="SHORT")],
                portfolio=pf, session_minutes_left=300)
    assert all(d["action"] == "FUND" for d in r["decisions"])


def test_cash_is_a_real_competitor():
    pf = PortfolioState(available_capital=100.0)
    r = compete(candidates=[_cand("c1", "SPY", risk=400.0)],
                portfolio=pf, session_minutes_left=300)
    assert r["decisions"][0]["action"] == "NO_CAPITAL"
    assert r["cash_preferred"] is True
    assert "better than doing nothing" in r["law"]


def test_zero_candidates_is_not_a_failure():
    r = compete(candidates=[], portfolio=PortfolioState(
        available_capital=5000.0), session_minutes_left=300)
    assert r["verdict"] == "NO_CANDIDATES"
    assert "not a failure" in r["law"]


def test_there_is_no_magic_capital_score():
    pf = PortfolioState(available_capital=5000.0)
    r = compete(candidates=[_cand("c1", "SPY")], portfolio=pf,
                session_minutes_left=300)
    assert r["no_magic_score"] is True
    blob = str(r)
    assert "capital_score" not in blob.lower()
    d = r["decisions"][0]
    for component in ("redundancy", "tail_dependence",
                      "opportunity_cost"):
        assert component in d


def test_declared_risk_must_be_positive():
    with pytest.raises(CapitalViolation, match="1R denominator"):
        _cand("bad", "SPY", risk=0.0)


def test_stress_convergence_is_distinguished_from_calm_correlation():
    pf = PortfolioState(available_capital=5000.0, open_positions=[
        {"symbol": "SPY", "direction": "LONG", "declared_risk": 300.0,
         "beta_family": "US_LARGE_BETA", "sector": "BROAD"}])
    t = tail_dependence(_cand("c", "MSFT"), pf)
    assert t["stress_behaviour"] == "CONVERGES_UNDER_STRESS"
    assert "stop being separate bets" in t["why"]


def test_unknown_beta_family_is_unknown_not_independent():
    pf = PortfolioState(available_capital=5000.0)
    r = redundancy(_cand("c", "SOMETHING_UNMAPPED"), pf, [])
    assert r["classification"] == "UNKNOWN"


def test_an_event_heavy_day_reserves_rather_than_stacks():
    pf = PortfolioState(available_capital=5000.0, open_positions=[
        {"symbol": "SPY", "direction": "LONG", "declared_risk": 300.0,
         "beta_family": "US_LARGE_BETA", "sector": "BROAD"}])
    r = compete(candidates=[_cand("c", "QQQ")], portfolio=pf,
                session_minutes_left=300,
                catalyst_environment="EVENT_HEAVY")
    assert r["decisions"][0]["action"] in ("CAPITAL_RESERVED",
                                           "REFUSE_RISK_CONCENTRATION")


# ==================================================== COUNTERFACTUAL

def test_a_shadow_decision_is_sealed_before_the_outcome(tmp_path):
    led = tmp_path / "shadow.jsonl"
    seal_decision(session="2026-08-27", candidate_id="c1", symbol="SPY",
                  baseline_action="PAPER_ATTACKED",
                  shadow_action="REFUSE_REDUNDANT",
                  reasons=["one beta bet"], declared_risk=300.0,
                  portfolio_snapshot={}, ledger=led)
    body = led.read_text()
    assert '"outcome": "PENDING"' in body
    append_outcome(session="2026-08-27", candidate_id="c1",
                   baseline_pnl=-50.0, baseline_r=-0.17, ledger=led)
    assert body in led.read_text(), "the sealed record was not edited"


def test_a_decision_without_reasons_cannot_be_studied(tmp_path):
    with pytest.raises(CounterfactualViolation, match="without reasons"):
        seal_decision(session="s", candidate_id="c", symbol="SPY",
                      baseline_action="x", shadow_action="y",
                      reasons=[], declared_risk=1.0,
                      portfolio_snapshot={},
                      ledger=tmp_path / "l.jsonl")


def test_the_comparison_refuses_a_verdict_on_a_tiny_sample(tmp_path):
    led = tmp_path / "shadow.jsonl"
    seal_decision(session="2026-08-27", candidate_id="c1", symbol="SPY",
                  baseline_action="PAPER_ATTACKED", shadow_action="FUND",
                  reasons=["ok"], declared_risk=300.0,
                  portfolio_snapshot={}, ledger=led)
    append_outcome(session="2026-08-27", candidate_id="c1",
                   baseline_pnl=75.0, baseline_r=0.19, ledger=led)
    c = compare(ledger=led)
    assert c["verdict"] == "INSUFFICIENT_EVIDENCE"
    assert "demonstrated nothing" in c["why"]


# ==================================================== NON-INTERFERENCE

def test_neither_component_can_touch_v1():
    """The whole point. Both are shadow, structurally."""
    assert CATALYST_AUTHORITY == "SHADOW_CONTEXT_ONLY"
    assert CAPITAL_AUTHORITY == "SHADOW_COUNTERFACTUAL_ONLY"

    v1 = [Path("scripts/options_paper_session.py"),
          Path("apex/predators/options/expression.py"),
          Path("apex/predators/options/attack_geometry.py"),
          Path("apex/predators/options/state.py"),
          Path("apex/predators/options/live_world.py"),
          Path("apex/predators/equities/attack_geometry.py")]
    # look for real COUPLING, not the English words. V1 prose is
    # allowed to discuss catalyst timing; V1 CODE may not import it.
    for p in v1:
        src = p.read_text()
        for coupling in ("import apex.catalyst", "from apex.catalyst",
                         "import apex.capital", "from apex.capital",
                         "apex.catalyst.", "apex.capital."):
            assert coupling not in src, \
                f"{p} couples to shadow research via {coupling!r}"


def test_neither_component_exposes_a_way_to_trade():
    import apex.capital.arena as ar
    import apex.catalyst.brain as br
    import apex.catalyst.reaction as rx
    for mod in (ar, br, rx):
        for banned in ("attack", "place_order", "submit", "promote",
                       "authorize_trade", "apply"):
            assert not hasattr(mod, banned), \
                f"{mod.__name__}.{banned} exists"
