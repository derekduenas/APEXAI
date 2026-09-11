"""THE FUNNEL: every layer in one decision path — engine (pure), session wiring, end-to-end synthetic pilot, replay hook."""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone

import numpy as np
import pytest

from apex.decision_wb.engine import FUNNEL_RULE_ID, FunnelEngine
from apex.multiverse_wb.pricing import bsm_price
from apex.options_pilot import entrypoint as EP, ledger as L
from apex.options_pilot.clock import Clock
from apex.options_pilot.fees import SYNTHETIC_FEES
from apex.options_pilot.synthetic_harness import SyntheticHarness
from apex.pulse_options.sources import returns_rows, synthetic_twin_sources
from apex.worldmodel_wb.contracts import ModelRefused

T_DAY = "2026-09-10"
T_START = datetime(2026, 9, 10, 0, 0, tzinfo=timezone.utc).timestamp()
AS_OF = datetime(2026, 9, 10, 15, 0, tzinfo=timezone.utc).timestamp()          # 11:00 ET


def _train_rows(n=2000, seed=3, sigma=2.5e-4):
    rng = np.random.default_rng(seed)
    t0 = T_START - 5 * 86400
    r = rng.standard_t(6, n) * sigma / math.sqrt(1.5)
    return [{"event_time": t0 + 60 * i, "available": t0 + 60 * i + 60, "ret_1": float(x)} for i, x in enumerate(r)]


def _quotes(spot, iv=0.18, exp="2026-10-09", spread=0.04, strikes=None):
    strikes = strikes or tuple(round(spot // 5 * 5 + d, 1) for d in (-10, -5, 0, 5, 10))
    T = (datetime.fromisoformat(exp) - datetime.fromisoformat(T_DAY)).days / 365.0
    q = {}
    for k in strikes:
        for right in ("CALL", "PUT"):
            mid = bsm_price(S=spot, K=float(k), T=T, sigma=iv, right=right)
            q[(exp, float(k), right)] = {"bid": round(mid - spread / 2, 2), "ask": round(mid + spread / 2, 2), "bid_size": 20, "ask_size": 20, "timestamp_epoch": AS_OF}
    return q


def _snapshot(spot):
    return {"symbol": "SPY", "state_hash": "abc", "fields": {"last_bar_age_s": {"value": 30.0, "quality": "VALID"}, "last_bar_close": {"value": spot, "quality": "VALID"}}}


def _forecast(loc, scale=6e-4):
    return {"symbol": "SPY", "location": loc, "scale": scale, "nu": 5.0, "model_id": "EXP002_L", "params_hash": "ca04fc6e713e1a5c", "direction_signal": None}


def _prefix(n=90, seed=5):
    return list(np.random.default_rng(seed).standard_normal(n) * 2.0e-4)


@pytest.fixture(scope="module")
def engine():
    e = FunnelEngine(n_paths=1500, seed=11)
    info = e.fit(_train_rows(), cutoff_epoch=T_START, label="fixture")
    assert info["status"] == "READY", info
    return e


def _decide(engine, loc, **kw):
    spot = kw.pop("spot", 200.2)                     # a $200 underlying: ATM asks (~$4) fit the $5 kernel cap; SPY at $645 does not
    quotes = kw.pop("quotes", None)
    if quotes is None:
        quotes = _quotes(spot)
    return engine.decide(symbol="SPY", as_of=AS_OF, day=T_DAY, snapshot=_snapshot(spot), forecast=_forecast(loc), spot=spot, quotes=quotes,
                         prefix_returns=_prefix(), fee_schedule=SYNTHETIC_FEES, heuristic_direction="LONG", **kw)


class TestEngine:
    def test_planted_drift_selects_the_matching_right_and_zero_drift_waits(self, engine):
        up = _decide(engine, +0.006)                 # +60 bps over 15 minutes: a planted, absurdly strong location
        dn = _decide(engine, -0.006)
        flat = _decide(engine, 0.0)
        assert up["decision"] == "TRADE" and up["proposal"]["contract"]["right"] == "CALL" and up["proposal"]["direction_signal"] == "LONG"
        assert dn["decision"] == "TRADE" and dn["proposal"]["contract"]["right"] == "PUT" and dn["proposal"]["direction_signal"] == "SHORT"
        assert flat["decision"] == "WAIT" and flat["why"].startswith("PRIME_ABSTAIN")           # spread + fees beat a zero-drift expectation
        assert up["proposal"]["expression_rule"] == FUNNEL_RULE_ID and up["proposal"]["expected_value_established"] is False
        assert up["proposal"]["reference_ask"] == _quotes(200.2)[(up["proposal"]["contract"]["expiration"], up["proposal"]["contract"]["strike"], "CALL")]["ask"]

    def test_trace_names_every_layer(self, engine):
        r = _decide(engine, +0.006)
        tr = r["trace"]
        for k in ("fit", "regime", "variance", "implied", "simulation", "expression_war", "prime", "selected", "final"):
            assert k in tr, k
        assert tr["variance"]["model"].startswith("GARCH") and tr["implied"]["iv0"] == pytest.approx(0.18, abs=0.01)
        assert "IV held fixed" in " ".join(tr["simulation"]["restrictions"]) and tr["simulation"]["n_paths"] == 1500
        labels = [c["label"] for c in tr["expression_war"]["table"]]
        assert labels[0] == "WAIT" and len(labels) == 1 + 2 * 5                                   # WAIT + 5 strikes x 2 rights
        assert tr["expression_war"]["expected_value_note"].startswith("UNESTABLISHED")
        assert tr["prime"]["decision"] == "ACT" and tr["selected"]["trace_digest"]
        assert tr["implied"]["physical_vs_implied"]["risk_premium_disclosed"] is True
        json.dumps(r, allow_nan=False)                                                             # strict JSON, no NaN anywhere

    def test_selected_candidate_is_the_max_expected_value_among_eligible(self, engine):
        r = _decide(engine, +0.006)
        elig = [c for c in r["trace"]["expression_war"]["table"] if c["status"] == "ELIGIBLE" and c["label"] != "WAIT"]
        assert r["trace"]["selected"]["label"] == max(elig, key=lambda c: c["expected_net_pnl"])["label"]

    def test_envelope_rejects_inside_the_candidate_set(self, engine):
        r = _decide(engine, +0.006, spot=645.2)                                                   # SPY-scale: every near-ATM ask > $5 cap
        assert r["decision"] == "WAIT" and r["why"].startswith("NO_ELIGIBLE_CANDIDATE") and "RISK_ENVELOPE" in r["why"]
        tbl = r["trace"]["expression_war"]["table"]
        assert r["trace"]["expression_war"]["rejected_by_risk_envelope"] == 10
        assert all(c["status"] == "REJECTED" and c["why"].startswith("RISK_ENVELOPE") and c["expected_net_pnl_if_unconstrained"] is not None for c in tbl if c["label"] != "WAIT")
        # a feasible cheaper strike among infeasible ones is selected over the (unconstrained-better) expensive one
        q = _quotes(200.2)
        for k in list(q):
            if k[1] <= 200.0 and k[2] == "CALL":
                q[k] = {**q[k], "bid": 6.0, "ask": 6.1}                                          # ITM/ATM calls priced out of the envelope
        r2 = _decide(engine, +0.006, quotes=q)
        assert r2["decision"] == "TRADE" and r2["proposal"]["contract"]["strike"] > 200.0 and r2["proposal"]["contract"]["right"] == "CALL"

    def test_stale_snapshot_abstains(self, engine):
        spot = 200.2
        snap = _snapshot(spot); snap["fields"]["last_bar_age_s"]["value"] = 900.0
        r = engine.decide(symbol="SPY", as_of=AS_OF, day=T_DAY, snapshot=snap, forecast=_forecast(0.006), spot=spot, quotes=_quotes(spot),
                          prefix_returns=_prefix(), fee_schedule=SYNTHETIC_FEES)
        assert r["decision"] == "WAIT" and "STALE_DATA" in r["why"]

    def test_no_eligible_expiry_or_missing_spot_waits_with_reason(self, engine):
        r = _decide(engine, +0.006, quotes=_quotes(200.2, exp="2026-09-18"))                     # 8 DTE < 21
        assert r["decision"] == "WAIT" and "no expiry with DTE" in r["why"]
        r2 = _decide(engine, +0.006, spot=None, quotes=_quotes(200.2))
        assert r2["decision"] == "WAIT" and "spot" in r2["why"]

    def test_unfitted_engine_waits_and_fit_firewall_holds(self):
        e = FunnelEngine(n_paths=200)
        r = e.decide(symbol="SPY", as_of=AS_OF, day=T_DAY, snapshot=_snapshot(200.0), forecast=_forecast(0.006), spot=200.0, quotes=_quotes(200.0),
                     prefix_returns=_prefix(), fee_schedule=SYNTHETIC_FEES)
        assert r["decision"] == "WAIT" and "UNSUPPORTED_STATE" in r["why"] and "NOT_FITTED" in r["why"]
        rows = _train_rows()
        rows[-1]["available"] = T_START + 1                                                       # one row after the cutoff
        info = e.fit(rows, cutoff_epoch=T_START)
        assert "FIREWALL" in info["garch"] and "FIREWALL" in info["regime"] and "ewma_fallback" not in info   # no fallback past a firewall violation
        assert info["status"] == "VARIANCE_UNAVAILABLE" and not e.ready
        r = e.decide(symbol="SPY", as_of=AS_OF, day=T_DAY, snapshot=_snapshot(200.0), forecast=_forecast(0.006), spot=200.0, quotes=_quotes(200.0),
                     prefix_returns=_prefix(), fee_schedule=SYNTHETIC_FEES)
        assert r["decision"] == "WAIT" and "VARIANCE_UNAVAILABLE" in r["why"]

    def test_gaussian_data_falls_back_to_ewma_and_says_so(self):
        e = FunnelEngine(n_paths=300)
        rows = _train_rows(n=3000, seed=9)
        for r in rows:                                                                            # thin tails: GARCH-t's nu runs to its bound
            r["ret_1"] = float(np.random.default_rng(int(r["event_time"]) % 100000).standard_normal() * 2e-4)
        info = e.fit(rows, cutoff_epoch=T_START)
        assert e.ready and info["variance_kind"].startswith("EWMA_FALLBACK") and "garch" in info
        r = e.decide(symbol="SPY", as_of=AS_OF, day=T_DAY, snapshot=_snapshot(200.2), forecast=_forecast(0.006), spot=200.2, quotes=_quotes(200.2),
                     prefix_returns=_prefix(), fee_schedule=SYNTHETIC_FEES)
        assert r["trace"]["variance"]["model"].startswith("EWMA_FALLBACK") and r["trace"]["variance"]["innovations"] == "GAUSSIAN"
        assert "constant conditional variance" in " ".join(r["trace"]["simulation"]["restrictions"])

    def test_insufficient_history_is_named(self):
        e = FunnelEngine()
        info = e.fit(_train_rows(n=50), cutoff_epoch=T_START)
        assert info["status"].startswith("INSUFFICIENT_HISTORY") and e.fits == 0

    def test_deterministic_given_seed(self, engine):
        a = _decide(engine, +0.006); b = _decide(engine, +0.006)
        # decisions counter changes the seed per call by design; same inputs + same counter => same result
        e2 = FunnelEngine(n_paths=1500, seed=11); e2.fit(_train_rows(), cutoff_epoch=T_START)
        e2.decisions = engine.decisions - 2
        c = e2.decide(symbol="SPY", as_of=AS_OF, day=T_DAY, snapshot=_snapshot(200.2), forecast=_forecast(0.006), spot=200.2, quotes=_quotes(200.2),
                      prefix_returns=_prefix(), fee_schedule=SYNTHETIC_FEES, heuristic_direction="LONG")
        assert c["trace"]["selected"]["expected_net_pnl"] == a["trace"]["selected"]["expected_net_pnl"]
        assert a["trace"]["simulation"]["seed"] != b["trace"]["simulation"]["seed"]


def test_returns_rows_skip_calendar_gaps():
    bars = [{"event_time": 0.0, "available": 60.0, "close": 100.0}, {"event_time": 60.0, "available": 120.0, "close": 101.0},
            {"event_time": 600.0, "available": 660.0, "close": 90.0}, {"event_time": 660.0, "available": 720.0, "close": 91.0}]
    rows = returns_rows(bars)
    assert [round(r["ret_1"], 6) for r in rows] == [round(math.log(1.01), 6), round(math.log(91 / 90), 6)]


# ------------------------------------------------------------------ session wiring: the funnel record precedes any intent
REG = datetime(2026, 9, 10, 14, 30, tzinfo=timezone.utc).timestamp() + 1.0


def _funnel_stub(decision, proposal=None, why="stub"):
    def fn(symbol, as_of, forecast):
        return {"decision": decision, "why": why, "proposal": proposal, "rule_id": FUNNEL_RULE_ID,
                "trace": {"engine": "STUB", "regime": {"probabilities": [0.7, 0.3], "abstain": False}, "variance": {"model": "GARCH-t (stub)"},
                          "simulation": {"n_paths": 10, "restrictions": ["IV held fixed"]},
                          "expression_war": {"table": [{"label": "WAIT", "status": "ELIGIBLE"}, {"label": "SPY|2026-10-09|645.0|CALL", "status": "ELIGIBLE", "expected_net_pnl": 3.0}],
                                             "expected_value_note": "UNESTABLISHED: stub", "fees": {"entry": 0.97, "exit": 0.05}},
                          "prime": {"decision": "ACT" if decision == "TRADE" else "ABSTAIN", "reasons": []},
                          "selected": {"label": "SPY|2026-10-09|645.0|CALL", "expected_net_pnl": 3.0} if decision == "TRADE" else None,
                          "final": {"decision": decision, "why": why}}}
    return fn


class TestSessionWiring:
    def _run(self, tmp_path, funnel_fn):
        from apex.options_pilot import session as S
        led = tmp_path / "led.jsonl"
        h = SyntheticHarness(led, session_id="FUN-1", t0=REG)
        bd = EP.build_boundary(led, provider=EP._HarnessProvider(h), session_id="FUN-1", release="synthetic-release")
        S.open_session(bd, symbols=["SPY"])
        src = h.sources()
        h.signal = None                                                       # the forecast carries no heuristic label under the funnel
        d = S.scan(bd, symbol="SPY", seq=1, forecast_fn=src["forecast_fn"], signal_fn=src["signal_fn"], chain_fn=src["chain_fn"],
                   spot_fn=src["spot_fn"], quote_fn=src["quote_fn"], funnel_fn=funnel_fn)
        return d, L.read_all(led)

    def test_trade_proposal_goes_through_the_intent_and_fill_path(self, tmp_path):
        prop = {"expression": "LONG_CALL", "action": "BUY", "contract": {"symbol": "SPY", "expiration": "2026-10-09", "strike": 645.0, "right": "CALL"},
                "quantity": 1, "expression_rule": FUNNEL_RULE_ID, "reference_ask": 2.45, "direction_signal": "LONG"}
        d, rows = self._run(tmp_path, _funnel_stub("TRADE", prop))
        kinds = [r["kind"] for r in rows]
        assert d["decision"] == "TRADE" and d["decision_persisted"] is True and "funnel" in d["receipts"]
        assert kinds.index("pilot_funnel") < kinds.index("pilot_intent") < kinds.index("pilot_fill") < kinds.index("pilot_decision")
        it = next(r for r in rows if r["kind"] == "pilot_intent")
        assert it["expression_rule"] == FUNNEL_RULE_ID and it["signal_used"] == "LONG" and it["no_best_option_claim"] is True
        dec = next(r for r in rows if r["kind"] == "pilot_decision")
        ft = dec["funnel_trace"]
        assert ft["contract"].startswith("FUNNEL_TRACE_V2")
        assert ft["simulation_bundle"]["n_paths"] == 10 and ft["situation_regime"]["probabilities"] == [0.7, 0.3]
        assert ft["eligible_expressions"]["chosen"] == "SPY|2026-10-09|645.0|CALL" and ft["expected_economics"]["established"] is False
        assert ft["risk_decision"]["provenance"] and ft["funnel_ref"]["seq"] == kinds.index("pilot_funnel") + 1
        L.verify_chain(tmp_path / "led.jsonl", rows=rows)

    def test_wait_is_a_decision_with_the_full_trace_and_no_intent(self, tmp_path):
        d, rows = self._run(tmp_path, _funnel_stub("WAIT", why="PRIME_ABSTAIN: STALE_DATA"))
        kinds = [r["kind"] for r in rows]
        assert d["decision"] == "WAIT" and d["why"].startswith("FUNNEL_WAIT: PRIME_ABSTAIN") and "pilot_intent" not in kinds
        dec = next(r for r in rows if r["kind"] == "pilot_decision")
        assert dec["funnel_trace"]["risk_decision"]["missing"].startswith("NO_INTENT") and dec["funnel_trace"]["prime"]["decision"] == "ABSTAIN"
        assert next(r for r in rows if r["kind"] == "pilot_funnel")["decision"] == "WAIT"

    def test_funnel_failure_and_malformed_result_fail_closed(self, tmp_path):
        def boom(symbol, as_of, forecast):
            raise RuntimeError("engine exploded")
        d, rows = self._run(tmp_path, boom)
        assert d["decision"] == "REFUSE" and "FUNNEL_PROVIDER_FAILED" in d["why"] and d["refusal_persisted"] is True
        d2, rows2 = self._run(tmp_path / "b", lambda s, t, f: {"decision": "MAYBE"})
        assert d2["decision"] == "REFUSE" and "FUNNEL_RESULT_MALFORMED" in d2["why"]

    def test_proposal_disagreeing_with_a_labelled_forecast_is_refused_by_the_record(self, tmp_path):
        from apex.options_pilot import session as S
        led = tmp_path / "led.jsonl"
        h = SyntheticHarness(led, session_id="FUN-2", t0=REG)
        bd = EP.build_boundary(led, provider=EP._HarnessProvider(h), session_id="FUN-2", release="synthetic-release")
        S.open_session(bd, symbols=["SPY"])
        h.signal = "SHORT"                                                    # forecast says SHORT, the funnel proposes a CALL
        prop = {"expression": "LONG_CALL", "action": "BUY", "contract": {"symbol": "SPY", "expiration": "2026-10-09", "strike": 645.0, "right": "CALL"},
                "quantity": 1, "expression_rule": FUNNEL_RULE_ID, "reference_ask": 2.45, "direction_signal": "LONG"}
        src = h.sources()
        d = S.scan(bd, symbol="SPY", seq=1, forecast_fn=src["forecast_fn"], signal_fn=src["signal_fn"], chain_fn=src["chain_fn"],
                   spot_fn=src["spot_fn"], quote_fn=src["quote_fn"], funnel_fn=_funnel_stub("TRADE", prop))
        assert d["decision"] == "REFUSE" and "SIGNAL_DISAGREES_WITH_FORECAST_RECORD" in d["why"]


# ------------------------------------------------------------------ end to end: synthetic twin + real engine through run_pilot
def test_full_funnel_end_to_end_on_the_synthetic_twin(tmp_path):
    led = tmp_path / "led.jsonl"
    h = SyntheticHarness(led, session_id="FUN-E2E", t0=REG)
    engine = FunnelEngine(n_paths=400, seed=3)
    twin = synthetic_twin_sources(clock=h.clock, quote_fn=h.quotes, exit_quote_fn=h.exit_quotes, chain_fn=h.chain_fn, sleep_fn=h.advance,
                                  selection_policy="FULL_FUNNEL_V1", funnel_engine=engine)
    rep = EP.run_pilot(ledger=led, out=tmp_path / "out.json", symbols=["SPY"], provider=EP.TwinProvider(twin), session_id="FUN-E2E",
                       release="synthetic-release", cycles=1)
    rows = L.read_all(led)
    kinds = [r["kind"] for r in rows]
    assert rep["selection_policy"] == "FULL_FUNNEL_V1" and rep["funnel_engine"]["rule_id"] == FUNNEL_RULE_ID
    assert engine.fit_info["status"] == "READY", engine.fit_info                               # 7 calendar days of synthetic (Gaussian) bars -> EWMA fallback declared
    assert "pilot_funnel" in kinds
    fc = next(r for r in rows if r["kind"] == "pilot_forecast")
    assert fc["direction_signal"] is None                                                       # the heuristic is not the selector under the funnel
    fn = next(r for r in rows if r["kind"] == "pilot_funnel")
    assert fn["trace"]["variance"]["model"] == engine.variance_kind and fn["trace"]["inputs"]["n_quotes"] >= 2
    assert fn["trace"]["heuristic_direction"] in ("LONG", "SHORT", None)
    d = rep["decisions"][0]
    assert d["decision"] in ("TRADE", "WAIT") and d["decision_persisted"] is True
    dec = next(r for r in rows if r["kind"] == "pilot_decision")
    assert dec["funnel_trace"]["contract"].startswith("FUNNEL_TRACE_V2")
    assert "missing" not in dec["funnel_trace"]["simulation_bundle"] or dec["funnel_trace"]["simulation_bundle"]["missing"].startswith("NOT_REACHED")
    L.verify_chain(led, rows=rows)
    json.dumps(rep, allow_nan=False)
