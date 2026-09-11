"""THE FUNNEL (r2): engine (pure), session wiring with the funnel binding enforced at intent/fill/recovery, end-to-end synthetic pilot."""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import numpy as np
import pytest

from apex.decision_wb.engine import FUNNEL_RULE_ID, HORIZON_15M_CALENDAR_YEARS, CALENDAR_YEAR_S, FunnelEngine
from apex.multiverse_wb.pricing import bsm_price
from apex.options_pilot import boundary as B, entrypoint as EP, ledger as L, session as S
from apex.options_pilot.fees import SYNTHETIC_FEES
from apex.options_pilot.records import assert_prospective
from apex.options_pilot.synthetic_harness import SyntheticHarness
from apex.pulse_options.sources import returns_rows, synthetic_twin_sources

T_DAY = "2026-09-10"
T_START = datetime(2026, 9, 10, 0, 0, tzinfo=timezone.utc).timestamp()
AS_OF = datetime(2026, 9, 10, 15, 0, tzinfo=timezone.utc).timestamp()          # 11:00 ET
BOOK = {"integrity_problems": [], "n_positions": 0, "kind": "TEST_BOOK"}


def _train_rows(n=2000, seed=3, sigma=2.5e-4):
    rng = np.random.default_rng(seed)
    t0 = T_START - 5 * 86400
    r = rng.standard_t(6, n) * sigma / math.sqrt(1.5)
    return [{"event_time": t0 + 60 * i, "available": t0 + 60 * i + 60, "ret_1": float(x)} for i, x in enumerate(r)]


def _quotes(spot, iv=0.18, exp="2026-10-09", spread=0.04, strikes=None, ts=AS_OF):
    strikes = strikes or tuple(round(spot // 5 * 5 + d, 1) for d in (-10, -5, 0, 5, 10))
    T = (datetime.fromisoformat(exp + "T16:00:00").replace(tzinfo=ZoneInfo("America/New_York")).timestamp() - AS_OF) / CALENDAR_YEAR_S
    q = {}
    for k in strikes:
        for right in ("CALL", "PUT"):
            mid = bsm_price(S=spot, K=float(k), T=T, sigma=iv, right=right)
            q[(exp, float(k), right)] = {"bid": round(mid - spread / 2, 2), "ask": round(mid + spread / 2, 2), "bid_size": 20, "ask_size": 20, "timestamp_epoch": ts}
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
    kw.setdefault("book_summary", BOOK)
    return engine.decide(symbol="SPY", as_of=AS_OF, day=T_DAY, snapshot=kw.pop("snapshot", _snapshot(spot)), forecast=_forecast(loc), spot=spot, quotes=quotes,
                         prefix_returns=kw.pop("prefix_returns", _prefix()), fee_schedule=SYNTHETIC_FEES, heuristic_direction="LONG", **kw)


class TestEngine:
    def test_planted_drift_selects_the_matching_right_and_zero_drift_waits(self, engine):
        up = _decide(engine, +0.006)                 # +60 bps over 15 minutes: a planted, absurdly strong location
        dn = _decide(engine, -0.006)
        flat = _decide(engine, 0.0)
        assert up["decision"] == "TRADE" and up["proposal"]["contract"]["right"] == "CALL" and up["proposal"]["direction_signal"] == "LONG"
        assert dn["decision"] == "TRADE" and dn["proposal"]["contract"]["right"] == "PUT" and dn["proposal"]["direction_signal"] == "SHORT"
        assert flat["decision"] == "WAIT" and flat["why"].startswith("PRIME_ABSTAIN")           # spread + fees beat a zero-drift expectation
        assert up["proposal"]["expression_rule"] == FUNNEL_RULE_ID and up["proposal"]["expected_value_established"] is False

    def test_trace_names_every_layer_and_the_layers_not_invoked(self, engine):
        r = _decide(engine, +0.006)
        tr = r["trace"]
        for k in ("fit", "regime", "variance", "quotes", "implied", "simulation", "expression_war", "tail_sensitivity", "prime", "selected", "final", "mandatory_inputs"):
            assert k in tr, k
        assert tr["layers_not_invoked"]["svi_surface"].startswith("NOT_INVOKED") and tr["layers_not_invoked"]["fusion"].startswith("NOT_INVOKED")
        assert tr["variance"]["model"].startswith("GARCH") and tr["implied"]["iv0"] == pytest.approx(0.18, abs=0.01)
        assert tr["simulation"]["innovations"]["family"] == "TRUNCATED_T" and tr["simulation"]["innovations"]["finite_exponential_moments"] is True
        labels = [c["label"] for c in tr["expression_war"]["table"]]
        assert labels[0] == "WAIT" and len(labels) == 1 + 2 * 5
        assert tr["expression_war"]["expected_value_note"].startswith("UNESTABLISHED")
        assert tr["prime"]["decision"] == "ACT" and tr["selected"]["trace_digest"]
        assert tr["prime"]["affordability"]["kind"].startswith("PRELIMINARY_AFFORDABILITY") and tr["prime"]["kernel_approval"].startswith("NOT_HERE")
        assert tr["prime"]["regime_supplied"] is True and tr["prime"]["book_summary_supplied"] is True
        json.dumps(r, allow_nan=False)

    # ---- F2: one variance-state convention
    def test_simulator_first_bar_variance_equals_the_forecast_exactly(self, engine):
        r = _decide(engine, +0.006)
        tr = r["trace"]
        gf = engine.variance.forecast(cutoff_epoch=AS_OF, created_epoch=AS_OF, horizon_bars=15, recent=_prefix())
        assert tr["simulation"]["h_next"] == gf.meta["next_bar_variance"] == tr["variance"]["next_bar_variance"]
        assert tr["simulation"]["first_bar_variance_equals_forecast"] is True

    # ---- F1: finite payoff expectation is an explicit, checked model choice
    def test_tail_truncation_is_declared_with_sensitivity(self, engine):
        r = _decide(engine, +0.006)
        ts = r["trace"]["tail_sensitivity"]
        assert ts["cap_sd_used"] == 8.0 and set(ts["by_cap_sd"]) == {"6.0", "12.0"} and all(isinstance(v, float) for v in ts["by_cap_sd"].values())
        assert any("TRUNCATED" in x for x in r["trace"]["simulation"]["restrictions"])

    # ---- F4: two clocks kept apart
    def test_expiry_decay_is_calendar_time_from_timestamps(self, engine):
        r = _decide(engine, +0.006)
        im = r["trace"]["implied"]
        expiry = datetime.fromisoformat("2026-10-09T16:00:00").replace(tzinfo=ZoneInfo("America/New_York")).timestamp()
        assert im["expiry_epoch"] == expiry and im["T_entry_years"] == (expiry - AS_OF) / CALENDAR_YEAR_S
        assert im["T_exit_years"] == (expiry - (AS_OF + 900.0)) / CALENDAR_YEAR_S
        assert abs(im["T_entry_years"] - HORIZON_15M_CALENDAR_YEARS - im["T_exit_years"]) < 1e-12 and r["trace"]["expression_war"]["exit_T_identity"] is True
        assert HORIZON_15M_CALENDAR_YEARS == 900.0 / (365.0 * 86400.0)
        pvi = im["physical_vs_implied"]
        assert pvi["convention"].startswith("iv^2 * T_calendar") and pvi["implied_var_15m"] == pytest.approx(im["iv0"] ** 2 * im["T_entry_years"] * 15.0 / im["time_conventions"]["trading_minutes_to_expiry"])

    # ---- F3: quote freshness is validated before any price is read
    def test_quotes_without_timestamps_are_rejected_not_defaulted(self, engine):
        q = {k: {kk: vv for kk, vv in v.items() if kk != "timestamp_epoch"} for k, v in _quotes(200.2).items()}
        r = _decide(engine, +0.006, quotes=q)
        assert r["decision"] == "WAIT" and "no valid quote" in r["why"]
        assert r["trace"]["quotes"]["valid"] == 0 and all("QUOTE_FIELD_MISSING: timestamp_epoch" in v for v in r["trace"]["quotes"]["rejection_reasons"].values())

    def test_stale_atm_quotes_cannot_supply_the_iv(self, engine):
        q = _quotes(200.2)
        for k in list(q):
            if k[1] == 200.0:
                q[k] = {**q[k], "timestamp_epoch": AS_OF - 86400.0}                                # ATM quotes a day old
        r = _decide(engine, +0.006, quotes=q)
        assert r["trace"]["quotes"]["rejected"] == 2 and r["trace"]["quotes"]["valid"] == 8
        assert r["trace"]["implied"]["atm_strike"] != 200.0                                        # the IV came from the nearest VALID strike, never the stale one
        assert all(c["label"] != "SPY|2026-10-09|200.0|CALL" for c in r["trace"]["expression_war"]["table"])   # and the stale contract is not a candidate
        q2 = {k: v for k, v in _quotes(200.2).items()}
        for k in list(q2):                                                                          # every quote stale -> nothing can supply the IV
            q2[k] = {**q2[k], "timestamp_epoch": AS_OF - 86400.0}
        r2 = _decide(engine, +0.006, quotes=q2)
        assert r2["decision"] == "WAIT" and "no valid quote" in r2["why"] and "QUOTE_STALE_OR_FUTURE" in str(r2["trace"]["quotes"]["rejection_reasons"])

    def test_crossed_or_sizeless_quotes_are_rejected(self, engine):
        q = _quotes(200.2)
        k0 = ("2026-10-09", 205.0, "CALL")
        q[k0] = {**q[k0], "bid": q[k0]["ask"] + 1.0}
        k1 = ("2026-10-09", 205.0, "PUT")
        q[k1] = {**q[k1], "ask_size": 0}
        r = _decide(engine, +0.006, quotes=q)
        rr = r["trace"]["quotes"]["rejection_reasons"]
        assert "QUOTE_CROSSED" in rr[str(k0)] and "QUOTE_SIZE_INVALID" in rr[str(k1)] and r["trace"]["quotes"]["valid"] == 8

    # ---- F5: mandatory inputs, named reduced mode, affordability vs kernel
    def test_missing_regime_cannot_act_in_full_mode(self):
        e = FunnelEngine(n_paths=300)
        e.fit(_train_rows(), cutoff_epoch=T_START)
        e.regime = None; e.fit_info = {**e.fit_info, "status": "REGIME_UNAVAILABLE (FULL mode requires the regime model; ...)"}
        r = _decide(e, +0.006)
        assert r["decision"] == "WAIT" and "REGIME_UNAVAILABLE" in r["why"]

    def test_short_prefix_blocks_the_regime_filter_in_full_mode(self, engine):
        r = _decide(engine, +0.006, prefix_returns=_prefix(3))
        assert r["decision"] == "WAIT" and "regime filter needs >= 5 prefix bars" in r["why"]

    def test_reduced_mode_is_selected_by_name_and_labelled(self):
        e = FunnelEngine(n_paths=300, mode="REDUCED_NO_REGIME")
        e.fit(_train_rows(), cutoff_epoch=T_START)
        e.regime = None
        assert e.ready
        r = _decide(e, +0.006)
        assert r["trace"]["mode"] == "REDUCED_NO_REGIME" and r["trace"]["regime"]["missing"].startswith("REGIME_NOT_USED: mode REDUCED_NO_REGIME")
        assert r["trace"]["prime"]["regime_supplied"] is False
        with pytest.raises(ValueError, match="MODE_UNKNOWN"):
            FunnelEngine(mode="WHATEVER")

    def test_book_summary_is_mandatory_and_integrity_problems_abstain(self, engine):
        r = _decide(engine, +0.006, book_summary=None)
        assert r["decision"] == "WAIT" and "book summary" in r["why"] and r["trace"]["mandatory_inputs"]["book_summary"] is False
        r2 = _decide(engine, +0.006, book_summary={"integrity_problems": ["CASH_IDENTITY_BROKEN"]})
        assert r2["decision"] == "WAIT" and "BOOK_INTEGRITY" in r2["why"]

    def test_selected_candidate_is_the_max_expected_value_among_eligible(self, engine):
        r = _decide(engine, +0.006)
        elig = [c for c in r["trace"]["expression_war"]["table"] if c["status"] == "ELIGIBLE" and c["label"] != "WAIT"]
        assert r["trace"]["selected"]["label"] == max(elig, key=lambda c: c["expected_net_pnl"])["label"]

    def test_envelope_rejects_inside_the_candidate_set(self, engine):
        r = _decide(engine, +0.006, spot=645.2)                                                   # SPY-scale: every near-ATM ask > $5 cap
        assert r["decision"] == "WAIT" and r["why"].startswith("NO_ELIGIBLE_CANDIDATE") and "RISK_ENVELOPE" in r["why"]
        assert r["trace"]["expression_war"]["rejected_by_risk_envelope"] == 10
        q = _quotes(200.2)
        for k in list(q):
            if k[1] <= 200.0 and k[2] == "CALL":
                q[k] = {**q[k], "bid": 6.0, "ask": 6.1}
        r2 = _decide(engine, +0.006, quotes=q)
        assert r2["decision"] == "TRADE" and r2["proposal"]["contract"]["strike"] > 200.0 and r2["proposal"]["contract"]["right"] == "CALL"

    def test_stale_snapshot_abstains(self, engine):
        snap = _snapshot(200.2); snap["fields"]["last_bar_age_s"]["value"] = 900.0
        r = _decide(engine, +0.006, snapshot=snap)
        assert r["decision"] == "WAIT" and "STALE_DATA" in r["why"]

    def test_no_eligible_expiry_or_missing_spot_waits_with_reason(self, engine):
        r = _decide(engine, +0.006, quotes=_quotes(200.2, exp="2026-09-18"))
        assert r["decision"] == "WAIT" and "DTE >=" in r["why"]
        r2 = _decide(engine, +0.006, spot=None, quotes=_quotes(200.2))
        assert r2["decision"] == "WAIT" and "spot" in r2["why"]

    def test_unfitted_engine_waits_and_fit_firewall_holds(self):
        e = FunnelEngine(n_paths=200)
        r = _decide(e, +0.006)
        assert r["decision"] == "WAIT" and "UNSUPPORTED_STATE" in r["why"] and "NOT_FITTED" in r["why"]
        rows = _train_rows()
        rows[-1]["available"] = T_START + 1
        info = e.fit(rows, cutoff_epoch=T_START)
        assert "FIREWALL" in info["garch"] and "FIREWALL" in info["regime"] and "ewma_fallback" not in info
        assert info["status"] == "VARIANCE_UNAVAILABLE" and not e.ready

    def test_gaussian_data_falls_back_to_ewma_and_says_so(self):
        e = FunnelEngine(n_paths=300)
        rows = _train_rows(n=3000, seed=9)
        for r in rows:
            r["ret_1"] = float(np.random.default_rng(int(r["event_time"]) % 100000).standard_normal() * 2e-4)
        info = e.fit(rows, cutoff_epoch=T_START)
        assert e.ready and info["variance_kind"].startswith("EWMA_FALLBACK")
        r = _decide(e, +0.006)
        assert r["trace"]["variance"]["model"].startswith("EWMA_FALLBACK") and r["trace"]["variance"]["innovations"] == "GAUSSIAN"
        assert r["trace"]["simulation"]["innovations"]["family"] == "GAUSSIAN" and r["trace"]["tail_sensitivity"]["by_cap_sd"] == {}

    def test_insufficient_history_is_named(self):
        e = FunnelEngine()
        info = e.fit(_train_rows(n=50), cutoff_epoch=T_START)
        assert info["status"].startswith("INSUFFICIENT_HISTORY") and e.fits == 0


def test_returns_rows_skip_calendar_gaps():
    bars = [{"event_time": 0.0, "available": 60.0, "close": 100.0}, {"event_time": 60.0, "available": 120.0, "close": 101.0},
            {"event_time": 600.0, "available": 660.0, "close": 90.0}, {"event_time": 660.0, "available": 720.0, "close": 91.0}]
    assert [round(r["ret_1"], 6) for r in returns_rows(bars)] == [round(math.log(1.01), 6), round(math.log(91 / 90), 6)]


# ------------------------------------------------------------------ session wiring: the persisted funnel authorizes exactly this intent
REG = datetime(2026, 9, 10, 14, 30, tzinfo=timezone.utc).timestamp() + 1.0
CONTRACT = {"symbol": "SPY", "expiration": "2026-10-09", "strike": 645.0, "right": "CALL"}
PROPOSAL = {"expression": "LONG_CALL", "action": "BUY", "contract": CONTRACT, "quantity": 1, "expression_rule": FUNNEL_RULE_ID, "reference_ask": 2.45,
            "direction_signal": "LONG"}


def _funnel_stub(decision, proposal=None, why="stub", rule_id=FUNNEL_RULE_ID):
    def fn(symbol, as_of, forecast, book_summary=None):
        assert book_summary is not None and "integrity_problems" in book_summary                # the session passes the real book summary
        return {"decision": decision, "why": why, "proposal": proposal, "rule_id": rule_id,
                "trace": {"engine": "STUB", "regime": {"probabilities": [0.7, 0.3], "abstain": False}, "variance": {"model": "GARCH-t (stub)"},
                          "simulation": {"n_paths": 10, "restrictions": ["IV held fixed"]},
                          "expression_war": {"table": [{"label": "WAIT", "status": "ELIGIBLE"}, {"label": "SPY|2026-10-09|645.0|CALL", "status": "ELIGIBLE", "expected_net_pnl": 3.0}],
                                             "expected_value_note": "UNESTABLISHED: stub", "fees": {"entry": 0.97, "exit": 0.05}},
                          "prime": {"decision": "ACT" if decision == "TRADE" else "ABSTAIN", "reasons": []},
                          "selected": {"label": "SPY|2026-10-09|645.0|CALL", "expected_net_pnl": 3.0, "trace_digest": "d1"} if decision == "TRADE" else None,
                          "final": {"decision": decision, "why": why}}}
    return fn


def _session(tmp_path, session_id="FUN-1", signal=None):
    led = tmp_path / "led.jsonl"
    h = SyntheticHarness(led, session_id=session_id, t0=REG)
    bd = EP.build_boundary(led, provider=EP._HarnessProvider(h), session_id=session_id, release="synthetic-release")
    S.open_session(bd, symbols=["SPY"])
    h.signal = signal
    return led, h, bd


def _scan(h, bd, funnel_fn, seq=1):
    src = h.sources()
    return S.scan(bd, symbol="SPY", seq=seq, forecast_fn=src["forecast_fn"], signal_fn=src["signal_fn"], chain_fn=src["chain_fn"],
                  spot_fn=src["spot_fn"], quote_fn=src["quote_fn"], funnel_fn=funnel_fn)


class TestSessionWiring:
    def test_trade_proposal_goes_through_the_intent_and_fill_path_with_the_binding(self, tmp_path):
        led, h, bd = _session(tmp_path)
        d = _scan(h, bd, _funnel_stub("TRADE", PROPOSAL))
        rows = L.read_all(led); kinds = [r["kind"] for r in rows]
        assert d["decision"] == "TRADE" and d["decision_persisted"] is True and "funnel" in d["receipts"]
        assert kinds.index("pilot_funnel") < kinds.index("pilot_intent") < kinds.index("pilot_fill") < kinds.index("pilot_decision")
        it = next(r for r in rows if r["kind"] == "pilot_intent")
        assert it["expression_rule"] == FUNNEL_RULE_ID and it["signal_used"] == "LONG" and it["no_best_option_claim"] is True
        assert it["funnel_ref"]["seq"] == kinds.index("pilot_funnel") + 1 and it["funnel_ref"]["entry_hash"] == rows[it["funnel_ref"]["seq"] - 1]["entry_hash"]
        assert it["funnel_ref"]["trace_digest"] == "d1"
        dec = next(r for r in rows if r["kind"] == "pilot_decision")
        ft = dec["funnel_trace"]
        assert ft["contract"].startswith("FUNNEL_TRACE_V2") and ft["eligible_expressions"]["chosen"] == "SPY|2026-10-09|645.0|CALL"
        assert ft["risk_decision"]["provenance"] and ft["funnel_ref"]["seq"] == it["funnel_ref"]["seq"]
        L.verify_chain(led, rows=rows)

    def test_wait_is_a_decision_with_the_full_trace_and_no_intent(self, tmp_path):
        led, h, bd = _session(tmp_path)
        d = _scan(h, bd, _funnel_stub("WAIT", why="PRIME_ABSTAIN: STALE_DATA"))
        rows = L.read_all(led); kinds = [r["kind"] for r in rows]
        assert d["decision"] == "WAIT" and d["why"].startswith("FUNNEL_WAIT: PRIME_ABSTAIN") and "pilot_intent" not in kinds
        dec = next(r for r in rows if r["kind"] == "pilot_decision")
        assert dec["funnel_trace"]["risk_decision"]["missing"].startswith("NO_INTENT") and dec["funnel_trace"]["prime"]["decision"] == "ABSTAIN"

    def test_funnel_failure_and_malformed_result_fail_closed(self, tmp_path):
        led, h, bd = _session(tmp_path)

        def boom(symbol, as_of, forecast, book_summary=None):
            raise RuntimeError("engine exploded")
        d = _scan(h, bd, boom)
        assert d["decision"] == "REFUSE" and "FUNNEL_PROVIDER_FAILED" in d["why"] and d["refusal_persisted"] is True
        d2 = _scan(h, bd, lambda s, t, f, book_summary=None: {"decision": "MAYBE"}, seq=2)
        assert d2["decision"] == "REFUSE" and "FUNNEL_RESULT_MALFORMED" in d2["why"]

    def test_proposal_disagreeing_with_a_labelled_forecast_is_refused_by_the_record(self, tmp_path):
        led, h, bd = _session(tmp_path, "FUN-2", signal="SHORT")
        d = _scan(h, bd, _funnel_stub("TRADE", PROPOSAL))
        assert d["decision"] == "REFUSE" and "SIGNAL_DISAGREES_WITH_FORECAST_RECORD" in d["why"]


class TestFunnelBinding:
    """F6: the persisted funnel is an EXECUTION dependency. Negative cases drive the boundary directly."""

    def _forecast_receipt(self, h, bd, scan_id):
        src = h.sources()
        return bd.record_forecast(src["forecast_fn"]("SPY", bd.clock.now()), scan_id=scan_id)

    def _funnel_record(self, bd, *, scan_id, f_receipt, decision="TRADE", proposal=PROPOSAL, rule_id=FUNNEL_RULE_ID, session_id=None):
        rec = {"kind": "pilot_funnel", "scan_id": scan_id, "symbol": "SPY", "session_id": session_id or bd.session_id, "release": bd.release,
               "forecast_ref": {"seq": f_receipt["seq"], "forecast_hash": f_receipt.get("forecast_hash")}, "rule_id": rule_id, "decision": decision,
               "why": None, "proposal": proposal, "trace": {"selected": {"trace_digest": "d1"}}, "at_utc": bd.clock.now_utc(), **bd.labels}
        assert_prospective(rec)
        return L.append_with_receipt(bd.ledger, rec)

    @staticmethod
    def _intent(p=PROPOSAL):
        return {k: v for k, v in p.items() if k != "direction_signal"}

    def test_missing_persistence_is_refused(self, tmp_path):
        led, h, bd = _session(tmp_path)
        fr = self._forecast_receipt(h, bd, "FUN-1:0001:SPY")
        with pytest.raises(B.BoundaryRefused, match="FUNNEL_REQUIRED"):
            bd.record_intent(forecast_receipt=fr, intent=self._intent(), signal_used="LONG", scan_id="FUN-1:0001:SPY")

    def test_wait_funnel_cannot_authorize_an_intent(self, tmp_path):
        led, h, bd = _session(tmp_path)
        fr = self._forecast_receipt(h, bd, "FUN-1:0001:SPY")
        fn = self._funnel_record(bd, scan_id="FUN-1:0001:SPY", f_receipt=fr, decision="WAIT", proposal=None)
        with pytest.raises(B.BoundaryRefused, match="FUNNEL_NOT_TRADE"):
            bd.record_intent(forecast_receipt=fr, intent=self._intent(), signal_used="LONG", scan_id="FUN-1:0001:SPY", funnel_receipt=fn)

    def test_another_scans_funnel_is_refused(self, tmp_path):
        led, h, bd = _session(tmp_path)
        fr = self._forecast_receipt(h, bd, "FUN-1:0001:SPY")
        fn = self._funnel_record(bd, scan_id="FUN-1:0002:SPY", f_receipt=fr)
        with pytest.raises(B.BoundaryRefused, match="FUNNEL_SCAN_MISMATCH"):
            bd.record_intent(forecast_receipt=fr, intent=self._intent(), signal_used="LONG", scan_id="FUN-1:0001:SPY", funnel_receipt=fn)

    def test_changed_proposal_or_policy_is_refused(self, tmp_path):
        led, h, bd = _session(tmp_path)
        fr = self._forecast_receipt(h, bd, "FUN-1:0001:SPY")
        fn = self._funnel_record(bd, scan_id="FUN-1:0001:SPY", f_receipt=fr)
        changed = {**PROPOSAL, "contract": {**CONTRACT, "strike": 650.0}}
        with pytest.raises(B.BoundaryRefused, match="FUNNEL_PROPOSAL_MISMATCH"):
            bd.record_intent(forecast_receipt=fr, intent=self._intent(changed), signal_used="LONG", scan_id="FUN-1:0001:SPY", funnel_receipt=fn)
        other_rule = {**PROPOSAL, "expression_rule": "FULL_FUNNEL_V9: something else"}
        with pytest.raises(B.BoundaryRefused, match="FUNNEL_POLICY_MISMATCH"):
            bd.record_intent(forecast_receipt=fr, intent=self._intent(other_rule), signal_used="LONG", scan_id="FUN-1:0001:SPY", funnel_receipt=fn)
        rows = L.read_all(led)
        assert not any(r["kind"] == "pilot_intent" for r in rows) and sum(1 for r in rows if r["kind"] == "pilot_refusal") == 2

    def test_altered_funnel_record_blocks_execution_and_recovery(self, tmp_path):
        led, h, bd = _session(tmp_path)
        fr = self._forecast_receipt(h, bd, "FUN-1:0001:SPY")
        fn = self._funnel_record(bd, scan_id="FUN-1:0001:SPY", f_receipt=fr)
        ir = bd.record_intent(forecast_receipt=fr, intent=self._intent(), signal_used="LONG", scan_id="FUN-1:0001:SPY", funnel_receipt=fn)
        # the fill re-verifies the binding: alter the funnel's proposal on disk -> chain hash breaks -> INTENT_FUNNEL_REF refusal, no fill
        lines = led.read_text().splitlines()
        rec = json.loads(lines[fn["seq"] - 1]); rec["proposal"]["contract"]["strike"] = 650.0
        lines[fn["seq"] - 1] = json.dumps(rec, sort_keys=True, separators=(",", ":"))
        led.write_text("\n".join(lines) + "\n")
        with pytest.raises(B.BoundaryRefused, match="INTENT_REF_CHAIN_RECORD_ALTERED|FUNNEL"):    # the hash chain catches the alteration first
            bd.execute_intent(intent_receipt=ir, quote_fn=h.quotes)
        assert not any(r["kind"] == "pilot_fill" for r in L.read_all(led))

    def test_execution_rechecks_the_binding_independently_of_intent_time(self, tmp_path, monkeypatch):
        """An intent whose recorded binding points at a funnel that does NOT authorize it (record-time check bypassed, as an older release
        or another writer could) is refused at the fill and on recovery: the binding is an execution dependency."""
        led, h, bd = _session(tmp_path)
        fr = self._forecast_receipt(h, bd, "FUN-1:0001:SPY")
        fn = self._funnel_record(bd, scan_id="FUN-1:0001:SPY", f_receipt=fr, decision="WAIT", proposal=None)
        monkeypatch.setattr(B.Boundary, "_funnel_binding_problem", staticmethod(lambda *a, **k: None))
        ir = bd.record_intent(forecast_receipt=fr, intent=self._intent(), signal_used="LONG", scan_id="FUN-1:0001:SPY", funnel_receipt=fn)
        monkeypatch.undo()
        with pytest.raises(B.BoundaryRefused, match="INTENT_FUNNEL_BINDING_FUNNEL_NOT_TRADE"):
            bd.execute_intent(intent_receipt=ir, quote_fn=h.quotes)
        assert not any(r["kind"] == "pilot_fill" for r in L.read_all(led))
        acts = S.resume(bd, quote_fn=h.quotes)
        assert len(acts) == 1 and acts[0]["action"] == "REFUSED" and "INTENT_FUNNEL_BINDING_FUNNEL_NOT_TRADE" in acts[0]["why"]

    def test_binding_rechecked_on_recovery_of_a_healthy_intent(self, tmp_path):
        led, h, bd = _session(tmp_path)
        fr = self._forecast_receipt(h, bd, "FUN-1:0001:SPY")
        fn = self._funnel_record(bd, scan_id="FUN-1:0001:SPY", f_receipt=fr)
        bd.record_intent(forecast_receipt=fr, intent=self._intent(), signal_used="LONG", scan_id="FUN-1:0001:SPY", funnel_receipt=fn)
        acts = S.resume(bd, quote_fn=h.quotes)                                                     # a crash before the fill: recovery executes ONCE
        assert len(acts) == 1 and acts[0]["action"] == "EXECUTED", acts
        it = next(r for r in L.read_all(led) if r["kind"] == "pilot_intent")
        assert it["funnel_ref"]["seq"] == fn["seq"]


# ------------------------------------------------------------------ end to end: synthetic twin + real engine through run_pilot
def test_full_funnel_end_to_end_on_the_synthetic_twin(tmp_path):
    led = tmp_path / "led.jsonl"
    h = SyntheticHarness(led, session_id="FUN-E2E", t0=REG)
    engine = FunnelEngine(n_paths=400, seed=3, mode="REDUCED_NO_REGIME")     # synthetic Gaussian bars: GARCH-t refuses (EWMA fallback declared); regime named optional
    twin = synthetic_twin_sources(clock=h.clock, quote_fn=h.quotes, exit_quote_fn=h.exit_quotes, chain_fn=h.chain_fn, sleep_fn=h.advance,
                                  selection_policy="FULL_FUNNEL_V1", funnel_engine=engine)
    rep = EP.run_pilot(ledger=led, out=tmp_path / "out.json", symbols=["SPY"], provider=EP.TwinProvider(twin), session_id="FUN-E2E",
                       release="synthetic-release", cycles=1)
    rows = L.read_all(led); kinds = [r["kind"] for r in rows]
    assert rep["selection_policy"] == "FULL_FUNNEL_V1" and rep["funnel_engine"]["rule_id"] == FUNNEL_RULE_ID and rep["funnel_engine"]["mode"] == "REDUCED_NO_REGIME"
    assert engine.fit_info["status"] == "READY", engine.fit_info
    assert "pilot_funnel" in kinds
    fc = next(r for r in rows if r["kind"] == "pilot_forecast")
    assert fc["direction_signal"] is None
    fn = next(r for r in rows if r["kind"] == "pilot_funnel")
    assert fn["trace"]["variance"]["model"] == engine.variance_kind and fn["trace"]["inputs"]["n_quotes"] >= 2 and fn["trace"]["mandatory_inputs"]["book_summary"] is True
    d = rep["decisions"][0]
    assert d["decision"] in ("TRADE", "WAIT") and d["decision_persisted"] is True
    dec = next(r for r in rows if r["kind"] == "pilot_decision")
    assert dec["funnel_trace"]["contract"].startswith("FUNNEL_TRACE_V2")
    if d["decision"] == "TRADE":
        it = next(r for r in rows if r["kind"] == "pilot_intent")
        assert it["funnel_ref"]["seq"] == kinds.index("pilot_funnel") + 1
    L.verify_chain(led, rows=rows)
    json.dumps(rep, allow_nan=False)
