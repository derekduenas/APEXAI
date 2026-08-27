"""COMMISSIONING — the wiring, not the schema.

test_catalyst_capital.py proves the models are correct. This file
proves the SYSTEM behaves: that retrieval persists before reasoning,
that a dead source is distinguishable from a quiet world, that a brain
reaching past its fence degrades one event instead of the pipeline,
and that Capital Arena judges real prospective records without ever
touching V1.
"""
from __future__ import annotations

import json

import pytest

from apex.capital.consumer import (ConsumerViolation, is_prospective,
                                   judge, load_shadow_portfolio,
                                   to_candidate)
from apex.capital.counterfactual import append_outcome, compare
from apex.catalyst import pipeline
from apex.catalyst.interpreter import ClaudeCliInterpreter, _strip_fence
from apex.catalyst.pipeline import build_events, persist_raw, run_cycle
from apex.catalyst.sources import (RawObservation, SourceUnavailable,
                                   entity_hints, fetch_all)
from apex.ops.outbox import emit


def _raw(**kw):
    base = dict(
        source_observation_id="SO_1", source="FEDERAL_RESERVE_PRESS",
        source_type="OFFICIAL_FEED", source_authority="PRIMARY_OFFICIAL",
        locator="https://federalreserve.gov/a", title="FOMC holds rates",
        published_time="2026-08-27T18:00:00Z",
        retrieved_time="2026-08-27T18:03:00Z",
        first_seen_time="2026-08-27T18:03:00Z",
        known_from="2026-08-27T18:03:00Z",
        raw_text_hash="abc", raw_excerpt="The Committee held rates.")
    base.update(kw)
    return RawObservation(**base)


def _roots(tmp_path):
    return {"raw": tmp_path / "raw.jsonl", "events": tmp_path / "ev.jsonl",
            "cycles": tmp_path / "cy.jsonl", "outbox": tmp_path / "ob.jsonl"}


# ============================================ RETRIEVAL BEFORE REASONING

def test_raw_evidence_is_persisted_before_any_interpretation(tmp_path,
                                                             monkeypatch):
    """The ordering IS the guarantee: if the brain explodes, the day's
    evidence must already be on disk."""
    r = _roots(tmp_path)
    seen = {}

    def boom(events):
        seen["raw_existed"] = r["raw"].exists() and bool(
            r["raw"].read_text().strip())
        raise RuntimeError("brain died mid-cycle")

    class Brain:
        interpret_many = staticmethod(boom)

    monkeypatch.setattr(pipeline, "fetch_all", lambda **k: {
        "observations": [_raw()], "sources_checked": 1,
        "sources_succeeded": 1, "sources_failed": 0, "coverage": "1/1",
        "succeeded": [], "failures": {}})

    rec = run_cycle(session="2026-08-27", phase="TEST",
                    interpreter=Brain(), roots=r)
    assert seen["raw_existed"] is True
    assert rec["new_observations"] == 1
    assert "brain died" in (rec["last_error"] or "")


def test_a_republished_document_is_not_new_evidence(tmp_path):
    r = _roots(tmp_path)
    o = _raw()
    assert persist_raw([o], raw_ledger=r["raw"])["new"] == 1
    again = persist_raw([o], raw_ledger=r["raw"])
    assert again["new"] == 0 and again["already_known"] == 1


def test_known_from_is_retrieval_not_publication(tmp_path):
    """A release published at 18:00 and fetched at 18:03 was not
    actionable at 18:00."""
    built = build_events([_raw()], session="2026-08-27")
    ev = built["events"][0]
    assert ev.known_from == "2026-08-27T18:03:00Z"
    assert ev.event_time == "2026-08-27T18:00:00Z"
    assert ev.known_from > ev.event_time


# ==================================================== DEDUP ACROSS WIRES

def test_the_same_event_from_many_outlets_is_one_event():
    raws = [
        _raw(source_observation_id="SO_a", source="FEDERAL_RESERVE_PRESS",
             locator="u1", title="Fed holds rates steady"),
        _raw(source_observation_id="SO_b", source="FEDERAL_RESERVE_PRESS",
             locator="u2", title="BREAKING: Fed holds rates steady"),
        _raw(source_observation_id="SO_c", source="FEDERAL_RESERVE_PRESS",
             locator="u3", title="UPDATE 2: Fed holds rates steady"),
    ]
    built = build_events(raws, session="2026-08-27")
    assert built["n_events"] == 1, "three headlines became many events"
    assert built["n_updates"] == 2
    assert len(built["events"][0].observations) == 3


def test_different_events_stay_separate():
    raws = [_raw(source_observation_id="a", title="Fed holds rates"),
            _raw(source_observation_id="b", source="SEC_EDGAR",
                 source_authority="COMPANY_DIRECT",
                 title="NVDA files 8-K")]
    assert build_events(raws, session="2026-08-27")["n_events"] == 2


def test_entity_hints_are_deterministic_string_matching():
    assert "NVDA" in entity_hints("Nvidia announces new datacenter GPU")
    assert "FED" in entity_hints("The Federal Reserve said")
    assert entity_hints("a story about nothing in particular") == ()


# ================================================== FAILURE ISOLATION

def test_a_dead_source_is_not_a_quiet_world(tmp_path, monkeypatch):
    """The single most dangerous confusion in the whole subsystem."""
    r = _roots(tmp_path)
    monkeypatch.setattr(
        pipeline, "fetch_all",
        lambda **k: {"observations": [], "sources_checked": 8,
                     "sources_succeeded": 0, "sources_failed": 8,
                     "coverage": "0/8", "succeeded": [],
                     "failures": {"FED": "timeout"}})
    rec = run_cycle(session="2026-08-27", phase="TEST", roots=r)
    assert rec["coverage"] == "0/8"
    assert rec["sources_failed"] == 8
    assert rec["new_events"] == 0
    assert rec["last_error"], "total blindness recorded no error"


def test_one_dead_adapter_does_not_kill_the_sweep(monkeypatch):
    import apex.catalyst.sources as S

    def half(name, authority, stype, url, release_sha="UNKNOWN"):
        if "press_all" in url:
            raise SourceUnavailable("boom")
        return [_raw(source=name)]

    monkeypatch.setattr(S, "fetch_feed", half)
    monkeypatch.setattr(S, "fetch_sec_filings",
                        lambda *a, **k: [_raw(source="SEC_EDGAR")])
    sweep = S.fetch_all()
    assert sweep["sources_failed"] == 1
    assert sweep["sources_succeeded"] == 7
    assert sweep["observations"], "one bad source emptied the sweep"


# ======================================================= THE BRAIN FENCE

def test_a_brain_reaching_past_the_fence_degrades_one_event_only():
    """A forbidden field must cost that interpretation, not the run."""
    it = ClaudeCliInterpreter()
    ev = build_events([_raw()], session="2026-08-27")["events"][0]
    it._invoke = lambda prompt: {
        ev.event_id: {"event_type": "CENTRAL_BANK", "surprise": 0.25}}
    out = it.interpret_many([ev])
    assert out["refused"] == 1 and out["interpreted"] == 0
    assert ev.interpreter == "DETERMINISTIC_NO_LLM"


def test_a_brain_citing_documents_it_never_saw_is_refused():
    it = ClaudeCliInterpreter()
    ev = build_events([_raw()], session="2026-08-27")["events"][0]
    it._invoke = lambda prompt: {ev.event_id: {
        "event_type": "CENTRAL_BANK", "factual_summary": "invented",
        "cited_source_refs": ["https://not-retrieved.example/x"]}}
    assert it.interpret_many([ev])["refused"] == 1


def test_a_valid_interpretation_is_applied_and_stamped():
    it = ClaudeCliInterpreter(model="haiku")
    ev = build_events([_raw()], session="2026-08-27")["events"][0]
    ref = ev.observations[0].source_ref
    it._invoke = lambda prompt: {ev.event_id: {
        "event_type": "CENTRAL_BANK",
        "factual_summary": "The Committee held rates.",
        "cited_source_refs": [ref], "importance": "HIGH",
        "affected_sectors": ["FINANCIALS"]}}
    out = it.interpret_many([ev])
    assert out["interpreted"] == 1 and out["refused"] == 0
    assert ev.importance == "HIGH"
    assert ev.interpreter.startswith("CLAUDE_CLI:haiku@")


def test_no_brain_on_this_host_still_produces_events():
    it = ClaudeCliInterpreter(binary="definitely-not-installed-xyz")
    assert it.available()["available"] is False
    ev = build_events([_raw()], session="2026-08-27")["events"][0]
    out = it.interpret_many([ev])
    assert out["interpreted"] == 0
    assert "no brain" in (out["error"] or "").lower()
    assert ev.interpreter == "DETERMINISTIC_NO_LLM"


def test_the_cli_json_fence_is_unwrapped():
    assert json.loads(_strip_fence('```json\n{"a":1}\n```')) == {"a": 1}
    assert json.loads(_strip_fence('{"a":1}')) == {"a": 1}


def test_a_timeout_is_reported_not_raised(monkeypatch):
    import subprocess
    it = ClaudeCliInterpreter(binary="sh", timeout_s=1)

    def slow(*a, **k):
        raise subprocess.TimeoutExpired(cmd="claude", timeout=1)

    monkeypatch.setattr(subprocess, "run", slow)
    ev = build_events([_raw()], session="2026-08-27")["events"][0]
    out = it.interpret_many([ev])
    assert "timed out" in (out["error"] or "")
    assert ev.interpreter == "DETERMINISTIC_NO_LLM"


# ============================================ CATALYST -> EDGEFORGE

def test_events_reach_the_edgeforge_outbox_without_a_verdict(tmp_path,
                                                             monkeypatch):
    r = _roots(tmp_path)
    monkeypatch.setattr(pipeline, "fetch_all", lambda **k: {
        "observations": [_raw()], "sources_checked": 1,
        "sources_succeeded": 1, "sources_failed": 0, "coverage": "1/1",
        "succeeded": [], "failures": {}})
    run_cycle(session="2026-08-27", phase="TEST", roots=r)
    recs = [json.loads(l) for l in r["outbox"].read_text().splitlines()
            if l.strip()]
    assert recs and recs[0]["kind"] == "catalyst_observation"
    assert recs[0]["decision_power"] == "NONE_OBSERVATIONAL"
    for banned in ("verdict", "direction", "attackable", "size"):
        assert banned not in recs[0]


# ================================================ CAPITAL COMMISSIONING

def _cand_payload(**kw):
    base = dict(evaluation_id="2026-08-27:001:SPY", symbol="SPY",
                direction="LONG", expression="CALL_VERTICAL",
                declared_risk=120.0, attack_ready=True,
                action="PAPER_ATTACKED", known_from="2026-08-27T14:00:00Z")
    base.update(kw)
    return base


def test_a_record_that_already_knows_its_outcome_is_refused():
    p = _cand_payload(realized_r=-0.2)
    assert is_prospective(p)["prospective"] is False
    with pytest.raises(ConsumerViolation, match="hindsight"):
        judge(p, session="2026-08-27",
              portfolio=load_shadow_portfolio())


def test_the_consumer_does_not_invent_greeks_or_half_lives():
    c = to_candidate(_cand_payload())
    assert c.signal_half_life_min == "NOT_ESTIMABLE"
    assert c.execution_burden == "NOT_ESTIMABLE"
    assert c.catalyst_exposure == "UNKNOWN"


def test_a_candidate_without_declared_risk_is_refused():
    with pytest.raises(ConsumerViolation, match="1R denominator"):
        to_candidate(_cand_payload(declared_risk=None))


def test_three_tickers_one_bet_is_caught_on_real_records(tmp_path):
    """The failure the arena exists for."""
    led = tmp_path / "shadow.jsonl"
    s = "2026-08-27"
    first = judge(_cand_payload(), session=s,
                  portfolio=load_shadow_portfolio(led), ledger=led)
    assert first["shadow_action"] == "FUND"

    second = judge(_cand_payload(evaluation_id="e2", symbol="QQQ"),
                   session=s, portfolio=load_shadow_portfolio(led),
                   ledger=led)
    third = judge(_cand_payload(evaluation_id="e3", symbol="NVDA"),
                  session=s, portfolio=load_shadow_portfolio(led),
                  ledger=led)
    assert "REFUSE" in second["shadow_action"] + third["shadow_action"]
    assert any("US_LARGE_BETA" in r or "beta" in r.lower()
               for r in second["reasons"] + third["reasons"])


def test_cash_is_a_real_competitor(tmp_path):
    """Predator says attackable; the arena may still prefer cash."""
    led = tmp_path / "s.jsonl"
    out = judge(_cand_payload(declared_risk=50.0,
                              capital_lockup_min=350,
                              edge_pedigree="UNPROVEN"),
                session="2026-08-27", session_minutes_left=360,
                portfolio=load_shadow_portfolio(led), ledger=led)
    assert out["shadow_action"] == "DEFER_FOR_SUPERIOR_OPPORTUNITY"
    assert out["baseline_action"] == "PAPER_ATTACKED", \
        "baseline must proceed regardless of the shadow answer"


def test_the_shadow_book_rebuilds_from_its_own_sealed_decisions(tmp_path):
    led = tmp_path / "s.jsonl"
    before = load_shadow_portfolio(led).available_capital
    judge(_cand_payload(), session="2026-08-27",
          portfolio=load_shadow_portfolio(led), ledger=led)
    after = load_shadow_portfolio(led)
    assert after.available_capital == before - 120.0
    assert len(after.open_positions) == 1


def test_outcome_is_appended_never_merged_into_the_seal(tmp_path):
    led = tmp_path / "s.jsonl"
    judge(_cand_payload(), session="2026-08-27",
          portfolio=load_shadow_portfolio(led), ledger=led)
    append_outcome(session="2026-08-27",
                   candidate_id="2026-08-27:001:SPY",
                   baseline_pnl=-25.0, baseline_r=-0.2, ledger=led)
    rows = [json.loads(l) for l in led.read_text().splitlines()
            if l.strip()]
    sealed = [r for r in rows if r["kind"] == "shadow_capital_decision"]
    assert sealed[0]["outcome"] == "PENDING", "the seal was rewritten"
    assert compare(led)["verdict"] == "INSUFFICIENT_EVIDENCE"


def test_the_consumer_drains_a_real_v1_outbox(tmp_path):
    """End to end on the actual outbox contract V1 writes."""
    from apex.capital import consumer as C
    ob = tmp_path / "v1.jsonl"
    emit(ob, kind="options_evaluation", session="2026-08-27",
         source="scripts/options_paper_session._scan_symbol",
         known_from="2026-08-27T14:00:00Z", payload=_cand_payload())
    emit(ob, kind="options_evaluation", session="2026-08-27",
         source="scripts/options_paper_session._scan_symbol",
         known_from="2026-08-27T14:05:00Z",
         payload=_cand_payload(evaluation_id="e9", attack_ready=False))

    out = C.run(session="2026-08-27", outbox=ob,
                cursor_path=tmp_path / "cur.json",
                ledger=tmp_path / "s.jsonl")
    assert out["records_consumed"] == 2
    assert out["judged"] == 1, "attack_ready record was not judged"
    assert out["skipped_not_candidates"] == 1
    assert not out["errors"]


# ============================================== FEED DIALECT REGRESSION

RDF_FEED = b"""<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns="http://purl.org/rss/1.0/">
  <channel><title>H.15</title></channel>
  <item><title>Selected Interest Rates</title>
        <link>https://federalreserve.gov/h15</link>
        <description>Daily rates.</description>
        <date>2026-08-26</date></item>
</rdf:RDF>"""

ATOM_FEED = b"""<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry><title>Apple files 8-K</title>
         <link href="https://example.gov/a"/>
         <updated>2026-08-26T12:00:00Z</updated>
         <summary>A filing.</summary></entry>
</feed>"""


@pytest.mark.parametrize("body,expect", [(RDF_FEED, "Selected Interest"),
                                         (ATOM_FEED, "Apple files")])
def test_every_feed_dialect_parses(body, expect):
    """RSS 1.0/RDF namespaces its items, and matching qualified names
    made the Fed's H.15 feed parse to zero while reporting success --
    a blind source behind a green light. Caught only by live traffic."""
    from apex.catalyst.sources import _parse_feed
    got = _parse_feed(body, source="S", source_type="OFFICIAL_FEED",
                      authority="PRIMARY_OFFICIAL", release_sha="x")
    assert len(got) == 1
    assert expect in got[0].title
    assert got[0].locator.startswith("https://")


def test_a_source_that_yields_nothing_is_named(monkeypatch):
    import apex.catalyst.sources as S
    monkeypatch.setattr(S, "fetch_feed", lambda *a, **k: [])
    monkeypatch.setattr(S, "fetch_sec_filings", lambda *a, **k: [])
    sweep = S.fetch_all()
    assert sweep["sources_succeeded"] == 8
    assert len(sweep["sources_yielding_nothing"]) == 8, \
        "eight blind sources reported as healthy"
