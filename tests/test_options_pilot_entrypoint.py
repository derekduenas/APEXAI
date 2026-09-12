"""OPTIONS-PILOT-001 through the REAL session entry point.

`scripts/options_paper_session.main` is invoked with `--pilot-boundary`.
These prove: the flag is off by default and the legacy loop is untouched;
with the flag on, every scan goes through the recording boundary and the
legacy geometry path (`_scan_symbol`, `seal_before_card`,
`paper_execution.simulate_entry`) is unreachable -- there is no fallback to
geometry-only fills; the production route refuses honestly (no reviewed
forecast adapter, no integrated risk authority) with persisted refusals;
the synthetic route is labelled SYNTHETIC_FIXTURE; TRADE/WAIT/REFUSE come
out with stable ids; a restart resumes without re-executing."""
import json
from pathlib import Path

import pytest

from apex.options_pilot import entrypoint as E, ledger as L, session as S
from apex.options_pilot.synthetic_harness import SyntheticHarness, T0
from scripts import options_paper_session as sess


class _Provider(E._HarnessProvider):
    pass


def _harness_provider(ledger, **kw):
    return _Provider(SyntheticHarness(Path(ledger), **kw))


@pytest.fixture
def fenced(monkeypatch):
    """Make every legacy geometry entry point explode if touched."""
    def boom(*a, **k):
        raise AssertionError("LEGACY GEOMETRY PATH CALLED ON THE PILOT ROUTE")
    monkeypatch.setattr(sess, "_scan_symbol", boom)
    monkeypatch.setattr(sess, "seal_before_card", boom)
    monkeypatch.setattr(sess.paper_execution, "simulate_entry", boom)
    monkeypatch.setattr(sess, "build_pedigree", boom)
    monkeypatch.setattr(sess, "Heartbeat", boom)
    monkeypatch.setattr(sess, "observe", boom)
    return boom


def _argv(tmp_path, *extra, symbols="SPY"):
    return ["--ledger", str(tmp_path / "led.jsonl"), "--out", str(tmp_path / "out.json"), "--symbols", symbols,
            "--dry-run", *extra]


def test_the_seam_is_off_by_default_and_routes_only_on_the_flag(tmp_path, monkeypatch):
    a = sess.build_parser().parse_args(_argv(tmp_path))
    assert a.pilot_boundary is False and E.route(a) == E.ROUTE_LEGACY
    a2 = sess.build_parser().parse_args(_argv(tmp_path, "--pilot-boundary"))
    assert E.route(a2) == E.ROUTE_PILOT
    # without the flag, main() proceeds into the legacy loop (pedigree is the first legacy step)
    class Legacy(Exception):
        pass
    monkeypatch.setattr(sess, "build_pedigree", lambda **k: (_ for _ in ()).throw(Legacy()))
    with pytest.raises(Legacy):
        sess.main(_argv(tmp_path))
    assert not (tmp_path / "led.jsonl").exists()


def test_pilot_route_calls_the_boundary_and_cannot_fall_back_to_geometry(tmp_path, fenced):
    prov = _harness_provider(tmp_path / "led.jsonl")
    rc = sess.main(_argv(tmp_path, "--pilot-boundary", "--pilot-session-id", "PS-1", "--pilot-release", "rel-x"),
                   pilot_sources=prov)
    assert rc == 0
    rows = L.read_all(tmp_path / "led.jsonl")
    kinds = [r["kind"] for r in rows]
    assert kinds == ["pilot_session_open", "pilot_forecast", "pilot_intent", "pilot_fill", "pilot_decision",
                     "pilot_outcome", "pilot_session_close"]
    assert not any(k.startswith("options_live") for k in kinds)                  # no legacy cards/attacks
    for r in rows:
        assert r["evidence_class"] == "PROSPECTIVE_PAPER" and r["decision_power"] == "NONE_PAPER"
        assert r["data_provenance"] == "SYNTHETIC_FIXTURE" and r["execution_mode"] == "PROSPECTIVE_ORCHESTRATION"
        assert r["session_id"] == "PS-1" and r["release"] == "rel-x"
    rep = json.loads((tmp_path / "out.json").read_text())
    assert rep["route"] == "PILOT_BOUNDARY" and rep["legacy_geometry_path_called"] is False
    assert rep["risk_authority"] == "SyntheticRiskAuthority" and rep["synthetic"] is True
    d = rep["decisions"][0]
    assert d["scan_id"] == "PS-1:0001:SPY" and d["decision"] == "TRADE"
    assert d["forecast_id"] and d["intent_id"] and d["fill_id"] and d["decision_persisted"] is True
    assert rep["outcomes"] == [{"fill_seq": 4, "recovery": False, "final": "RESOLVED",
                                "attempts": [{"seq": 6, "status": "RESOLVED", "attempt": 1, "reconciled": False}]}]
    L.verify_chain(tmp_path / "led.jsonl")


def test_production_route_refuses_honestly_with_persisted_refusals(tmp_path, fenced):
    rc = sess.main(_argv(tmp_path, "--pilot-boundary", "--pilot-session-id", "PROD-1", symbols="SPY,QQQ"))
    assert rc == 0
    rows = L.read_all(tmp_path / "led.jsonl")
    assert [r["kind"] for r in rows] == ["pilot_session_open", "pilot_refusal", "pilot_decision",
                                         "pilot_refusal", "pilot_decision", "pilot_session_close"]
    for r in rows:
        assert r["data_provenance"] == "LIVE_FEED" and r["synthetic"] is False
    rep = json.loads((tmp_path / "out.json").read_text())
    assert rep["risk_authority"] == "CertifiedRiskAuthority" and rep["data_provenance"] == "LIVE_FEED"
    assert rep["fee_schedule"]["provenance"] == "UNVERIFIED"                 # reverted: ROBINHOOD_RHF_2026 v2026-09-12b awaits review of its changed computation
    for d in rep["decisions"]:
        assert d["decision"] == "REFUSE" and "LIVE_DATA_DISABLED" in d["why"] and d["refusal_persisted"] is True
    assert not any(r["kind"] in ("pilot_forecast", "pilot_intent", "pilot_fill") for r in rows)


def test_production_risk_authority_refuses_even_if_a_forecast_is_supplied(tmp_path, fenced):
    """Inject a forecast provider but keep the PRODUCTION risk authority: intent stage refuses."""
    h = SyntheticHarness(tmp_path / "led.jsonl")
    class Prov(E._HarnessProvider):
        pass
    prov = Prov(h)
    prov.provenance = "LIVE_FEED"
    prov.fee_schedule = E.UNVERIFIED_FEES
    prov.risk_authority = E.CertifiedRiskAuthority(fee_schedule=E.UNVERIFIED_FEES, provenance="LIVE_FEED")
    rc = sess.main(_argv(tmp_path, "--pilot-boundary", "--pilot-session-id", "PROD-2"), pilot_sources=prov)
    assert rc == 0
    rows = L.read_all(tmp_path / "led.jsonl")
    assert [r["kind"] for r in rows] == ["pilot_session_open", "pilot_forecast", "pilot_refusal", "pilot_decision", "pilot_session_close"]
    assert "FEE_SCHEDULE_UNVERIFIED" in rows[2]["reason"] and rows[3]["decision"] == "REFUSE"     # an unknown cost is not zero


def test_synthetic_fixture_flag_runs_the_explicit_harness_from_the_cli(tmp_path, fenced):
    rc = sess.main(_argv(tmp_path, "--pilot-boundary", "--pilot-synthetic-fixture", "--pilot-session-id", "CLI-1"))
    assert rc == 0
    rows = L.read_all(tmp_path / "led.jsonl")
    assert all(r["data_provenance"] == "SYNTHETIC_FIXTURE" and r["synthetic"] is True for r in rows)
    assert any(r["kind"] == "pilot_fill" and r["status"] == "FILLED" for r in rows)


def test_trade_wait_refuse_in_one_cycle_with_stable_ids(tmp_path, fenced):
    h = SyntheticHarness(tmp_path / "led.jsonl")
    def by_symbol(c):
        if c["symbol"] == "QQQ":
            age = 30.0
        else:
            age = 1.0
        return {**c, "bid": 2.4, "ask": 2.5, "bid_size": 9, "ask_size": 12, "timestamp_epoch": h.now() - age}
    h.quotes.override = by_symbol
    base = h.base_forecast
    def forecast(sym, as_of):
        if sym == "AAPL":
            raise ConnectionError("forecast provider down for AAPL")
        return base(sym, as_of)
    h.forecast_override = forecast
    rc = sess.main(_argv(tmp_path, "--pilot-boundary", "--pilot-session-id", "MIX-1", symbols="SPY,QQQ,AAPL"),
                   pilot_sources=E._HarnessProvider(h))
    assert rc == 0
    rep = json.loads((tmp_path / "out.json").read_text())
    by = {d["symbol"]: d for d in rep["decisions"]}
    assert by["SPY"]["decision"] == "TRADE" and by["SPY"]["scan_id"] == "MIX-1:0001:SPY"
    assert by["QQQ"]["decision"] == "WAIT" and by["QQQ"]["scan_id"] == "MIX-1:0002:QQQ" and "STALE_SELECTED_CONTRACT" in by["QQQ"]["why"]
    assert by["AAPL"]["decision"] == "REFUSE" and by["AAPL"]["scan_id"] == "MIX-1:0003:AAPL" and "FORECAST_PROVIDER_FAILED" in by["AAPL"]["why"]
    assert by["AAPL"]["refusal_persisted"] is True and by["AAPL"]["intent_id"] is None
    rows = L.read_all(tmp_path / "led.jsonl")
    decs = [r for r in rows if r["kind"] == "pilot_decision"]
    assert [d["decision"] for d in decs] == ["TRADE", "WAIT", "REFUSE"]
    assert len({d["scan_id"] for d in decs}) == 3
    out = rep["outcomes"]
    assert len(out) == 1 and out[0]["fill_seq"] == 4 and out[0]["recovery"] is False and out[0]["final"] == "RESOLVED"
    assert [{k: a[k] for k in ("status", "attempt", "reconciled")} for a in out[0]["attempts"]] == \
        [{"status": "RESOLVED", "attempt": 1, "reconciled": False}]
    kinds = [r["kind"] for r in rows]
    # OPERATING-LOOP-001 changed WHEN these happen, and the new order is the point. The QQQ WAIT intent is retired at
    # its own TTL -- an INTENT_EXPIRY event in the chronological stream -- not held to session close; and the SPY exit
    # is valued at its deadline, which is later than that TTL. Previously the single-cycle loop did no housekeeping at
    # all, so the intent survived until close.
    i_cancel = kinds.index("pilot_intent_cancelled")
    i_outcome = kinds.index("pilot_outcome")
    assert i_cancel < i_outcome < kinds.index("pilot_session_close")
    assert kinds[-2:] == ["pilot_outcome", "pilot_session_close"]
    cancel = [r for r in rows if r["kind"] == "pilot_intent_cancelled"][0]
    assert cancel["why"].startswith("FORECAST_STALE_BEFORE_EXECUTION"), \
        "the reservation is released at the TTL with a NAMED reason, not swept up at close"


def test_restart_resumes_without_re_executing_and_continues_the_sequence(tmp_path, fenced):
    led = tmp_path / "led.jsonl"
    h = SyntheticHarness(led, session_id="RS-1")
    # first run dies inside the quote provider: intent on disk, no fill
    h.quotes.fail_with = KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        sess.main(_argv(tmp_path, "--pilot-boundary", "--pilot-session-id", "RS-1", "--pilot-release", "synthetic-release"),
                  pilot_sources=E._HarnessProvider(h))
    assert [r["kind"] for r in L.read_all(led)] == ["pilot_session_open", "pilot_forecast", "pilot_intent"]
    # restart: same session id + release, provider healthy, clock 5 s later
    h2 = SyntheticHarness(led, session_id="RS-1", t0=T0 + 5.0)
    rc = sess.main(_argv(tmp_path, "--pilot-boundary", "--pilot-session-id", "RS-1", "--pilot-release", "synthetic-release"),
                   pilot_sources=E._HarnessProvider(h2))
    assert rc == 0
    rep = json.loads((tmp_path / "out.json").read_text())
    assert rep["session_open"]["receipt"].startswith("RECONCILED")                 # idempotent open
    assert len(rep["resumed"]) == 1 and rep["resumed"][0]["action"] == "EXECUTED" and rep["resumed"][0]["status"] == "FILLED"
    resumed_seq = rep["resumed"][0]["receipt"]["seq"]
    assert rep["recovered_positions"] == [{"seq": resumed_seq, "intent_id": rep["resumed"][0]["intent_id"],
                                           "scan_id": "RS-1:0001:SPY", "fill_id": rep["resumed"][0]["receipt"]["fill_id"],
                                           "contract_id": "SPY|2026-10-09|650.0|CALL", "valuation_attempts": 0,
                                           "last_attempt_why": None}]
    assert rep["decisions"][0]["scan_id"] == "RS-1:0002:SPY" and rep["decisions"][0]["decision"] == "TRADE"
    new_fill_seq = [i + 1 for i, r in enumerate(L.read_all(led)) if r.get("fill_id") == rep["decisions"][0]["fill_id"]][0]
    assert sorted(o["fill_seq"] for o in rep["outcomes"]) == sorted([resumed_seq, new_fill_seq])
    assert all(o["final"] == "RESOLVED" for o in rep["outcomes"]) and rep["unresolved_positions"] == []
    assert [o["recovery"] for o in sorted(rep["outcomes"], key=lambda o: o["fill_seq"])] == [True, False]
    assert rep["completion"] == "CLOSED_CLEAN" and rep["outstanding_obligations"] == 0
    kinds = [r["kind"] for r in L.read_all(led)]
    assert kinds.count("pilot_fill") == 2 and kinds.count("pilot_forecast") == 2 and kinds.count("pilot_session_open") == 1
    assert kinds.count("pilot_outcome") == 2
    assert S.unfilled_intents(led) == [] and S.unresolved_fills(led) == []
    # a third restart after close: the closed session's nothing-to-do, and a fresh session id starts at 0001
    h3 = SyntheticHarness(led, session_id="RS-2", t0=T0 + 10.0)
    sess.main(_argv(tmp_path, "--pilot-boundary", "--pilot-session-id", "RS-2", "--pilot-release", "synthetic-release"),
              pilot_sources=E._HarnessProvider(h3))
    rep3 = json.loads((tmp_path / "out.json").read_text())
    assert rep3["resumed"] == [] and rep3["decisions"][0]["scan_id"] == "RS-2:0001:SPY"
    L.verify_chain(led)


def test_report_is_strict_json_and_names_mode_and_provenance(tmp_path, fenced):
    prov = _harness_provider(tmp_path / "led.jsonl")
    sess.main(_argv(tmp_path, "--pilot-boundary", "--pilot-session-id", "J-1"), pilot_sources=prov)
    txt = (tmp_path / "out.json").read_text()
    assert "NaN" not in txt and "Infinity" not in txt
    rep = json.loads(txt)
    assert rep["execution_mode"] == "PROSPECTIVE_ORCHESTRATION" and rep["data_provenance"] == "SYNTHETIC_FIXTURE"
    assert rep["evidence_class"] == "PROSPECTIVE_PAPER" and rep["decision_power"] == "NONE_PAPER"


def test_f6_lifecycle_recovery_through_the_entry_point(tmp_path, fenced):
    """A resumed position must not vanish. The ORDINARY missing/stale-exit paths (provider returns None, then a
    stale quote) leave it an explicit outstanding obligation across restarts until a valid exit discharges it.
    Exits are driven by the FROZEN exit policy: due at +900 s, up to 5 attempts in a 120 s window, then exhausted."""
    led = tmp_path / "led.jsonl"
    h = SyntheticHarness(led, session_id="LC-1")
    h.quotes.fail_with = KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        sess.main(_argv(tmp_path, "--pilot-boundary", "--pilot-session-id", "LC-1", "--pilot-release", "synthetic-release"),
                  pilot_sources=E._HarnessProvider(h))
    # run 2: resume fills the pending intent (a RECOVERED position: one labelled recovery attempt after it is due);
    # the new scan's position is driven through the policy; the exit provider returns None for everything
    h2 = SyntheticHarness(led, session_id="LC-1", t0=T0 + 5.0)
    h2.exit_quotes.override = lambda c: None
    rc = sess.main(_argv(tmp_path, "--pilot-boundary", "--pilot-session-id", "LC-1", "--pilot-release", "synthetic-release"),
                   pilot_sources=E._HarnessProvider(h2))
    assert rc == 0
    rep = json.loads((tmp_path / "out.json").read_text())
    assert rep["mode"] == "SCAN_AND_RESOLVE" and rep["resumed"][0]["status"] == "FILLED"
    assert len(rep["recovered_positions"]) == 1 and len(rep["outcomes"]) == 2
    rec_out = [o for o in rep["outcomes"] if o["recovery"]][0]
    new_out = [o for o in rep["outcomes"] if not o["recovery"]][0]
    assert rec_out["final"] == "UNRESOLVED_AFTER_RECOVERY_ATTEMPT" and len(rec_out["attempts"]) == 1
    assert new_out["final"] == "EXIT_EXHAUSTED_UNRESOLVED" and len(new_out["attempts"]) == 5
    assert all(a["status"] == "NOT_ESTIMABLE" for a in rec_out["attempts"] + new_out["attempts"])
    assert len(rep["unresolved_positions"]) == 2 and rep["outstanding_obligations"] == 2
    assert {p["valuation_attempts"] for p in rep["unresolved_positions"]} == {1, 5}
    assert all(p["last_attempt_why"] == "EXIT_QUOTE_MISSING" for p in rep["unresolved_positions"])
    assert rep["completion"] == "CLOSED_WITH_OUTSTANDING_OBLIGATIONS"
    rows = L.read_all(led)
    close = rows[rep["session_close"]["seq"] - 1]
    assert sorted(close["unresolved_fill_seqs_at_close"]) == sorted(p["seq"] for p in rep["unresolved_positions"])
    assert len(close["exit_exhausted_fill_seqs_at_close"]) == 1 and close["failed_valuation_attempts_at_close"]
    assert any(r["kind"] == "pilot_exit_exhausted" for r in rows)
    # run 3, same (closed) session, recovery only: exit quotes are STALE -> one recovery attempt each, still outstanding
    h3 = SyntheticHarness(led, session_id="LC-1", t0=h2.now() + 5.0)
    h3.exit_quotes.age = 61.0
    sess.main(_argv(tmp_path, "--pilot-boundary", "--pilot-session-id", "LC-1", "--pilot-release", "synthetic-release"),
              pilot_sources=E._HarnessProvider(h3))
    rep3 = json.loads((tmp_path / "out.json").read_text())
    assert rep3["mode"] == "RECOVERY_ONLY" and rep3["decisions"] == [] and len(rep3["recovered_positions"]) == 2
    assert all(o["recovery"] and o["final"] == "UNRESOLVED_AFTER_RECOVERY_ATTEMPT" for o in rep3["outcomes"])
    assert {p["valuation_attempts"] for p in rep3["unresolved_positions"]} == {2, 6}
    assert rep3["completion"] == "CLOSED_WITH_OUTSTANDING_OBLIGATIONS"
    assert all(p["last_attempt_why"].startswith("STALE_SELECTED_CONTRACT") for p in rep3["unresolved_positions"])
    # run 4: valid exits discharge both; a NEW close record says clean; the Book cash identity holds
    h4 = SyntheticHarness(led, session_id="LC-1", t0=h3.now() + 5.0)
    sess.main(_argv(tmp_path, "--pilot-boundary", "--pilot-session-id", "LC-1", "--pilot-release", "synthetic-release"),
              pilot_sources=E._HarnessProvider(h4))
    rep4 = json.loads((tmp_path / "out.json").read_text())
    assert rep4["mode"] == "RECOVERY_ONLY" and all(o["final"] == "RESOLVED" for o in rep4["outcomes"])
    assert rep4["unresolved_positions"] == [] and rep4["completion"] == "CLOSED_CLEAN" and rep4["outstanding_obligations"] == 0
    assert rep4["book"]["cash_identity"]["holds"] is True and rep4["book"]["integrity_problems"] == []
    assert L.read_all(led)[rep4["session_close"]["seq"] - 1]["close_number"] == 3
    assert not any(r["kind"] == "pilot_forecast" and r["scan_id"].startswith("LC-1:0003") for r in L.read_all(led))
    # a different session reports another session's outstanding position as foreign and does not touch it
    h5 = SyntheticHarness(led, session_id="LC-2", t0=h4.now() + 5.0)
    h5.exit_quotes.override = lambda c: None
    sess.main(_argv(tmp_path, "--pilot-boundary", "--pilot-session-id", "LC-2", "--pilot-release", "synthetic-release"),
              pilot_sources=E._HarnessProvider(h5))
    h6 = SyntheticHarness(led, session_id="LC-3", t0=h5.now() + 5.0)
    sess.main(_argv(tmp_path, "--pilot-boundary", "--pilot-session-id", "LC-3", "--pilot-release", "synthetic-release"),
              pilot_sources=E._HarnessProvider(h6))
    rep6 = json.loads((tmp_path / "out.json").read_text())
    assert len(rep6["foreign_unresolved_positions"]) == 1 and rep6["foreign_unresolved_positions"][0]["session_id"] == "LC-2"
    assert rep6["unresolved_positions"] == [] and rep6["completion"] == "CLOSED_CLEAN"
    assert len(S.unresolved_fills(led)) == 1                                           # still LC-2's obligation, untouched
    L.verify_chain(led)


def test_every_decision_carries_a_funnel_trace_with_named_missing_stages(tmp_path, fenced):
    h = SyntheticHarness(tmp_path / "led.jsonl", session_id="FT-1", risk="certified")
    h.quotes.override = lambda c: {**c, "bid": 2.4, "ask": 2.5, "bid_size": 9, "ask_size": 12, "timestamp_epoch": h.now() - (30.0 if c["symbol"] == "QQQ" else 1.0)}
    base = h.base_forecast
    h.forecast_override = lambda s, t: (_ for _ in ()).throw(ConnectionError("down")) if s == "AAPL" else base(s, t)
    sess.main(_argv(tmp_path, "--pilot-boundary", "--pilot-session-id", "FT-1", symbols="SPY,QQQ,AAPL"), pilot_sources=E._HarnessProvider(h))
    rows = L.read_all(tmp_path / "led.jsonl")
    decs = {r["symbol"]: r for r in rows if r["kind"] == "pilot_decision"}
    for r in decs.values():
        tr = r["funnel_trace"]
        assert set(S.FUNNEL_STAGES) <= set(tr) and tr["contract"].startswith("FUNNEL_TRACE_V1")
        assert "missing" in tr["simulation_bundle"] and "missing" in tr["expected_economics"] and "missing" in tr["situation_regime"]
    assert decs["SPY"]["funnel_trace"]["final"]["decision"] == "TRADE" and decs["SPY"]["funnel_trace"]["risk_decision"]["kernel_approved_at_commit"] is True
    assert decs["SPY"]["funnel_trace"]["model_bundle"]["params_hash"].startswith("SYNTHETIC:") and decs["SPY"]["funnel_trace"]["eligible_expressions"]["set"] == ["WAIT", "LONG_CALL"]
    assert decs["QQQ"]["funnel_trace"]["final"]["decision"] == "WAIT"
    assert decs["AAPL"]["funnel_trace"]["state_snapshot"]["missing"].startswith("NO_FORECAST") and decs["AAPL"]["funnel_trace"]["eligible_expressions"]["missing"].startswith("NO_INTENT")
