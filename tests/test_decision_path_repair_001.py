"""Decision-path repair of b9998d02 (six findings + real-integration proof). Every test here exercises the actual path
(adapter -> selector, CLI -> report, engine -> PRIME, session -> boundary -> fill -> exit -> Book); no double stands in
for a repaired gate. Synthetic inputs only."""
from __future__ import annotations

import json
import math

import pytest

from apex.decision_wb import supervision as SV
from apex.joint_wb import engine as ENG
from apex.options_pilot import ledger as L, session as S
from apex.options_pilot import expression_rule as ER
from apex.options_pilot.clock import Clock
from apex.options_pilot.records import TOLL_FORMULA_V1, DOCTRINE_FIELDS
from apex.options_pilot.risk_authority import entry_cap_price
from apex.pulse_options import sources as SRC
from apex.pulse_options.providers import LiveGate, ThetaChainAdapter
import tests.test_joint_wb as T
import tests.test_options_pilot_boundary as TB
import tests.test_options_pilot_entrypoint as TE
from tests.test_options_pilot_entrypoint import fenced  # noqa: F401  (module-local fixture, imported into this namespace)

SNAP = "2026-09-11 10:53:23"
SNAP_EPOCH = ThetaChainAdapter.et_naive_to_epoch(SNAP)
RECEIPT = SNAP_EPOCH + 5.0
GATE = LiveGate(env={"APEX_PILOT_LIVE_DATA": "ENABLED"}, secret_fn=lambda name: "present")


def _row(strike, right="C", bid="4.50", ask="4.63", bs="58", as_="139", ts=SNAP, exp="20261002"):
    return {"symbol": "SPY", "expiration": exp, "strike": strike, "right": right, "timestamp": ts, "bid": bid, "ask": ask, "bid_size": bs, "ask_size": as_}


# ================================================================ 1. POLICY IDENTITY, CLI -> REPORT
class TestPolicyIdentity:
    def _run(self, tmp_path, fenced, policy, sid):
        rc = TE.sess.main(TE._argv(tmp_path, "--pilot-boundary", "--pilot-synthetic-fixture", "--pilot-selection-policy", policy,
                                   "--pilot-session-id", sid))
        assert rc == 0
        rep = json.loads((tmp_path / "out.json").read_text())
        intents = [r for r in L.read_all(tmp_path / "led.jsonl") if r["kind"] == "pilot_intent"]
        return rep, intents

    def test_v1_and_v2_choose_different_contracts_and_each_report_names_the_rule_it_ran(self, tmp_path, fenced):
        rep1, i1 = self._run(tmp_path / "v1", fenced, "PILOT_RULE_V1", "PI-V1")
        rep2, i2 = self._run(tmp_path / "v2", fenced, "PILOT_RULE_V2", "PI-V2")
        assert rep1["selection_policy"] == "PILOT_RULE_V1" and rep2["selection_policy"] == "PILOT_RULE_V2"
        assert i1 and i2
        assert i1[0]["expression_rule"] == ER.RULE_ID_V1 and i2[0]["expression_rule"] == ER.RULE_ID_V2
        # the fixture where the two rules DISAGREE: spot 646.3, V1 -> 645 (nearest), V2 -> 650 (signal side, cap-feasible)
        assert i1[0]["contract"]["strike"] == 645.0 and i2[0]["contract"]["strike"] == 650.0
        assert rep1["policy_identity"]["consistent"] and rep2["policy_identity"]["consistent"]
        assert rep1["policy_identity"]["expected_rule_id"] == ER.RULE_ID_V1 and rep2["policy_identity"]["expected_rule_id"] == ER.RULE_ID_V2
        assert i1[0]["pins"]["expression_rule"] == ER.RULE_ID_V1 and i2[0]["pins"]["expression_rule"] == ER.RULE_ID_V2

    def test_cli_default_is_the_authorized_v2_and_matches_the_session_default(self, tmp_path, fenced):
        a = TE.sess.build_parser().parse_args(TE._argv(tmp_path))
        assert a.pilot_selection_policy == "PILOT_RULE_V2" == ER.DEFAULT_RULE

    def test_unknown_policy_is_rejected_by_the_cli_and_by_run_pilot(self, tmp_path, fenced):
        with pytest.raises(SystemExit):
            TE.sess.build_parser().parse_args(TE._argv(tmp_path, "--pilot-selection-policy", "PILOT_RULE_V9"))
        from apex.options_pilot import entrypoint as PEP
        from apex.options_pilot.synthetic_harness import make_harness
        h = make_harness(tmp_path / "led.jsonl", symbols=["SPY"])
        prov = PEP._HarnessProvider(h, selection_policy="NOT_A_POLICY")
        with pytest.raises(ValueError, match="SELECTION_POLICY_UNKNOWN"):
            PEP.run_pilot(ledger=tmp_path / "led.jsonl", out=tmp_path / "o.json", symbols=["SPY"], provider=prov, session_id="X", release="r")

    def test_a_mislabeled_run_cannot_pass_the_identity_check(self, tmp_path, fenced):
        """Provider says V1, but a tampered intent carries V2's rule id: run_pilot must refuse the report."""
        from apex.options_pilot import entrypoint as PEP
        from apex.options_pilot.synthetic_harness import make_harness
        led = tmp_path / "led.jsonl"
        h = make_harness(led, symbols=["SPY"])
        PEP.run_pilot(ledger=led, out=tmp_path / "o.json", symbols=["SPY"], provider=PEP._HarnessProvider(h, selection_policy="PILOT_RULE_V2"),
                      session_id="ML-1", release="r")
        # a second provider claiming V1 over the same session's V2 intents
        h2 = make_harness(led, symbols=["SPY"])
        h2.chain = []                                                   # no new intent; only the identity check runs on history
        with pytest.raises(RuntimeError, match="POLICY_IDENTITY_MISMATCH"):
            PEP.run_pilot(ledger=led, out=tmp_path / "o2.json", symbols=["SPY"], provider=PEP._HarnessProvider(h2, selection_policy="PILOT_RULE_V1"),
                          session_id="ML-1", release="r")


# ================================================================ 2. NORMALIZATION AND V2 SELECTION, ADAPTER -> SELECTOR
class TestQuoteNormalization:
    def test_provider_boundary_refuses_and_records_every_malformed_row(self):
        rows = [_row("773.000"),                                           # valid
                _row("774.000", right=""), _row("775.000", right="X"), {**_row("776.000"), "right": None},
                _row("777.000", bs="1.7"), _row("778.000", as_="True"), _row("779.000", bid="inf", ask="inf"),
                _row("780.000", ask="0"), _row("781.000", ask="-1"), _row("782.000", bid="5.00", ask="4.00"),
                _row("783.000", ts="2026-09-11 10:53:40"),                 # 12 s in the future of receipt
                _row("784.000", ts="2026-09-11 10:50:00"),                 # 208 s old
                _row("785.000", exp="2026-13-40"), _row("bad")]
        out = SRC.live_chain_rows(rows, symbol="SPY", receipt_time=RECEIPT)
        assert [r["strike"] for r in out] == [773.0] and out[0]["right"] == "CALL" and out[0]["bid_size"] == 58
        reasons = sorted(x["why"].split(":")[0] for x in out.exclusions)
        assert reasons == sorted(["RIGHT_NOT_DECLARED"] * 3 + ["SIZE_INVALID"] * 2 + ["ASK_INVALID"] * 3 + ["QUOTE_CROSSED",
                                 "QUOTE_FROM_THE_FUTURE", "INDICATIVE_STALE", "EXPIRATION_INVALID", "STRIKE_INVALID"])
        assert not any(r["right"] == "PUT" for r in out), "no PUT was manufactured from a missing/unknown right"

    def test_adapter_to_selector_path_excludes_conflicting_duplicates_and_keeps_the_valid_alternative(self):
        rows = [_row("770.000", ask="4.00", bid="3.90"), _row("770.000", ask="9.00", bid="8.90"),   # conflicting duplicate
                _row("771.000", ask="4.20", bid="4.10"), _row("771.000", ask="4.20", bid="4.10"),   # identical duplicate
                _row("764.000", ask="9.20", bid="9.11")]
        chain = SRC.live_chain_rows(rows, symbol="SPY", receipt_time=RECEIPT)
        fwd = ER.choose(symbol="SPY", direction_signal="LONG", spot=763.94, as_of="2026-09-11T14:53:23Z", available=chain,
                        max_entry_price=entry_cap_price(), as_of_epoch=RECEIPT)
        rev = ER.choose(symbol="SPY", direction_signal="LONG", spot=763.94, as_of="2026-09-11T14:53:23Z", available=SRC.ChainRows(list(reversed(chain)), chain.exclusions),
                        max_entry_price=entry_cap_price(), as_of_epoch=RECEIPT)
        assert fwd["contract"]["strike"] == rev["contract"]["strike"] == 771.0 and fwd["reference_ask"] == rev["reference_ask"] == 4.2
        ex = fwd["strike_selection"]["exclusions"]
        assert any(e["why"].startswith("DUPLICATE_CONFLICT") and e["strike"] == 770.0 for e in ex["selector"])
        assert fwd["strike_selection"]["census"]["excluded_selector"] == 1

    def test_selector_boundary_refuses_bad_values_even_when_the_provider_did_not(self):
        base = [{"expiration": "2026-10-02", "strike": 780.0, "right": "CALL", "ask": 3.0, "bid": 2.9, "bid_size": 5, "ask_size": 5, "timestamp_epoch": RECEIPT - 1}]
        for bad in ({"ask": 0.0}, {"ask": -1.0}, {"ask": float("inf")}, {"ask": float("nan")}, {"bid_size": True}, {"ask_size": 1.5},
                    {"timestamp_epoch": RECEIPT + 1}, {"timestamp_epoch": RECEIPT - 200}, {"strike": -5.0}):
            row = {**base[0], "strike": 770.0, **bad}
            v = ER.choose(symbol="SPY", direction_signal="LONG", spot=763.94, as_of="2026-09-11T14:53:23Z", available=base + [row],
                          max_entry_price=5.0, as_of_epoch=RECEIPT)
            assert v["contract"]["strike"] == 780.0, bad                  # the malformed row never wins; the valid alternative is kept
            assert v["strike_selection"]["exclusions"]["n_selector"] == 1, bad

    def test_bool_is_not_a_size_and_a_size_is_an_int(self):
        assert SRC._size_int(True) is None and SRC._size_int("1.7") is None and SRC._size_int(-1) is None and SRC._size_int("58") == 58
        assert SRC._finite_float("inf") is None and SRC._finite_float("nan") is None and SRC._finite_float(True) is None and SRC._finite_float("4.63") == 4.63


# ================================================================ 3. PRIME'S SPREAD INPUT
class TestPrimeSpread:
    def _cand(self, spread):
        return {"candidates": [{"label": "X", "status": "ELIGIBLE", "expected_net_pnl": 5.0, "entry_ask": 2.0, "entry_spread_rel": spread,
                                "expected_value_established": True}], "expected_value_note": ""}

    def _sup(self, spread):
        from apex.worldmodel_wb.contracts import ForecastObject
        fo = ForecastObject(model_id="m", artifact_digest="d", horizon_minutes=15, input_cutoff_epoch=0.0, created_epoch=1.0,
                            supplies=("mean", "variance", "density"), mean=0.0, variance=1e-6,
                            density={"family": "EMPIRICAL", "sample": [0.0, 0.001, -0.001]}, meta={"p_return_gt_zero": 0.6})
        pol = SV.SupervisionPolicy(require_value_established=True, min_expected_net_pnl=0.0)
        return SV.supervise(forecast=fo, snapshot={"fields": {"last_bar_age_s": {"value": 1.0}}}, comparison=self._cand(spread),
                            risk_decision={"approved": True}, book_summary={"integrity_problems": []}, candidate_label="X", policy=pol)

    def test_missing_spread_is_not_zero_and_a_measured_zero_is_zero(self):
        assert self._sup(None)["decision"] == "ABSTAIN" and any("unknown or invalid" in r for r in self._sup(None)["reasons"])
        assert self._sup(float("nan"))["decision"] == "ABSTAIN"
        assert self._sup(0.0)["decision"] == "ACT"                                  # a measured zero passes on its merits
        assert self._sup(0.16)["decision"] == "ABSTAIN" and any("0.160 > 0.15" in r for r in self._sup(0.16)["reasons"])
        assert self._sup(0.14)["decision"] == "ACT"

    def test_wide_spread_candidate_that_clears_the_other_gates_is_abstained_through_the_real_engine(self):
        """Through JointEngine.decide with real PRIME: relative spread 0.16 on a candidate that clears rules 0-4
        (variance forecast consistent with the planted drift, v_hat = 15(mu^2 + h), so the spread state is not shocked)."""
        e = T._engine(n_paths=300, seed=11)
        drift = 0.002
        r = T._decide(e, ms=T._state(quotes=T._quotes(spread_rel=0.16)), drift=drift, v_hat=15 * (drift ** 2 + 1e-6 / 15.0), scan_id="WIDE")
        rules = r["trace"]["decision_rule"]["rules"]
        assert set(rules) >= {"0", "1", "2", "3", "4", "5"}, "rules 0-4 must have PASSED for PRIME to be the gate that fired"
        assert r["decision"] == "WAIT" and rules["5"]["decision"] == "ABSTAIN"
        assert any("QUOTE_UNCERTAINTY: relative spread" in x and "> 0.15" in x for x in rules["5"]["reasons"])
        pi = r["trace"]["prime_input"]
        assert pi["entry_spread_rel"] == pytest.approx(0.16, abs=0.01) and pi["max_spread_rel"] == 0.15
        assert {"bid", "ask", "mid", "timestamp_epoch", "age_s"} <= set(pi["quote_identity"])

    def test_narrow_spread_control_acts_through_the_real_path(self):
        e = T._engine(n_paths=300, seed=11)
        r = T._decide(e, ms=T._state(quotes=T._quotes(spread_rel=0.02)), drift=0.0005, scan_id="NARROW")
        assert r["decision"] == "TRADE" and r["trace"]["decision_rule"]["rules"]["5"]["decision"] == "ACT"
        sel = next(t for t in r["trace"]["candidates"]["table"] if t["label"] == r["trace"]["selected"]["label"])
        assert 0.0 < sel["entry_spread_rel"] < 0.15
        assert r["trace"]["prime_input"]["entry_spread_rel"] == sel["entry_spread_rel"] and r["trace"]["prime_input"]["quote_identity"] == sel["quote_identity"]


# ================================================================ 4. ADVERSE IV SCENARIO
class TestAdverseIV:
    @pytest.mark.parametrize("drift,right", [(0.0005, "CALL"), (-0.001, "PUT")])
    def test_iv_down_stress_never_benefits_a_long_option(self, drift, right):
        e = T._engine(n_paths=300, seed=11)
        r = T._decide(e, ms=T._state(), drift=drift, v_hat=15 * (drift ** 2 + 1e-6 / 15.0), scan_id="ADV-%s" % right)
        adv = r["trace"]["decision_rule"]["rules"]["3"]
        sel = r["trace"]["selected"]["label"]
        assert sel.endswith("|" + right), sel
        prm = adv["parameters"]["a_iv_minus_1_cluster_robust_se"]
        assert prm["shift"] < 0 and prm["direction"].startswith("IV_DOWN") and prm["expression"] == "LONG_" + right
        base, stressed = adv["scenarios"]["BASE"], adv["scenarios"]["a_iv_minus_1_cluster_robust_se"]
        assert stressed is not None and stressed <= base + 1e-9, (right, base, stressed)

    def test_iv_shift_sign_is_checked_directly_through_pricing_holding_all_else_fixed(self):
        """Price the SAME paths with x_iv shifted down: a long call and a long put both lose value (vega > 0)."""
        from apex.joint_wb import accounting as ACC
        import numpy as np
        S = np.full(50, T.SPOT)
        for right in ("CALL", "PUT"):
            base = ACC.price_paths(S=S, x_iv=np.full(50, math.log(0.18)), x_sk=np.zeros(50), x_sp=np.full(50, math.log(0.02)), x_sz=np.full(50, math.log(26.0)),
                                   K=T.SPOT, K_atm=T.SPOT, right=right, expiry_epoch=T.ST.expiry_epoch_of(T.EXPIRY), t_eval=T.T_D + 900)
            down = ACC.price_paths(S=S, x_iv=np.full(50, math.log(0.18) - 0.05), x_sk=np.zeros(50), x_sp=np.full(50, math.log(0.02)), x_sz=np.full(50, math.log(26.0)),
                                   K=T.SPOT, K_atm=T.SPOT, right=right, expiry_epoch=T.ST.expiry_epoch_of(T.EXPIRY), t_eval=T.T_D + 900)
            assert float(down["bid"].mean()) < float(base["bid"].mean()), right

    def test_registry_completeness_and_no_silent_pass_are_preserved(self):
        e = T._engine(n_paths=200, seed=11)
        r = T._decide(e, ms=T._state(), drift=0.0005, scan_id="REG")
        adv = r["trace"]["decision_rule"]["rules"]["3"]
        assert adv["complete"] and set(adv["registered"]) == set(ENG.ADVERSE_SCENARIOS) == set(adv["scenarios"]) - {"BASE"}


# ================================================================ 5. TWO-STAGE FRESHNESS THROUGH THE SESSION
class TestFreshnessTwoStage:
    def test_30s_indicative_chain_quote_supports_an_intent_and_a_fresh_executable_quote_fills(self, tmp_path):
        h = TB._h(tmp_path)
        h.chain_age = 30.0                                              # indicative rows 30 s old at the scan
        h.quotes.age = 1.0                                              # the executable quote at the boundary is fresh
        d = TB._scan(h)
        assert d["decision"] == "TRADE"
        it = TB._rec(h, d["receipts"]["intent"])
        assert it["reference_quote"]["timestamp_epoch"] == pytest.approx(h.now() - 30.0 - 0.25, abs=1.0)
        fl = TB._rec(h, d["receipts"]["fill"])
        assert fl["status"] == "FILLED"

    def test_stale_executable_quote_cannot_fill_even_with_a_fresh_chain(self, tmp_path):
        h = TB._h(tmp_path)
        h.chain_age = 1.0
        h.quotes.age = 16.0
        d = TB._scan(h)
        assert d["decision"] == "WAIT" and d["why"].startswith("STALE_SELECTED_CONTRACT")
        assert not h.bd.book().positions

    def test_an_indicative_chain_row_older_than_120s_cannot_be_selected(self, tmp_path):
        h = TB._h(tmp_path)
        h.chain_age = 121.0
        d = TB._scan(h)
        assert d["decision"] == "REFUSE" and "NO_VALID_ROWS" in d["why"] and "INDICATIVE_STALE" in d["why"]


# ================================================================ 6. BEFORE RECORD
class TestBeforeRecord:
    def test_intent_seals_expected_toll_doctrine_and_pins_from_intent_time_information_only(self, tmp_path):
        h = TB._h(tmp_path)
        d = TB._scan(h)
        it = TB._rec(h, d["receipts"]["intent"])
        et = it["expected_toll"]
        assert et["formula"] == "TOLL_FORMULA_V1" and et["formula_hash"] == TOLL_FORMULA_V1["hash"] and et["status"] == "ESTIMATED_AT_INTENT_TIME"
        assert et["inputs"]["ask_ref"] == it["reference_quote"]["ask"] and et["inputs"]["bid_ref"] == it["reference_quote"]["bid"]
        assert et["value"] == pytest.approx(100.0 * (et["inputs"]["ask_ref"] - et["inputs"]["bid_ref"]) + et["inputs"]["fee_in"] + et["inputs"]["fee_out"])
        doc = it["doctrine"]["fields"]
        assert set(DOCTRINE_FIELDS) | {"tail_asymmetry"} <= set(doc)
        assert sum(1 for f in DOCTRINE_FIELDS if doc[f]["value"] == "NOT_MEASURED") == 5 and doc["tail_asymmetry"]["value"] == "UNKNOWN"
        assert doc["our_expected_footprint"]["value"] == pytest.approx(1.0 / it["reference_quote"]["ask_size"], abs=1e-6)
        pins = it["pins"]
        assert pins["expression_rule"] == ER.RULE_ID_V2 and pins["toll_formula_hash"] == TOLL_FORMULA_V1["hash"] and pins["exit_policy_id"] == "EXIT_AT_HORIZON_15M_V1"
        assert pins["fee_schedule_id"] and pins["release"] == h.release
        fl = TB._rec(h, d["receipts"]["fill"])
        upd = fl["entry_cost_update"]
        assert upd["formula"] == "TOLL_FORMULA_V1" and upd["intent_expected_toll_ref"]["value"] == et["value"]
        assert upd["entry_half_spread_$"] == pytest.approx(100.0 * (fl["quote_observed"]["ask"] - 0.5 * (fl["quote_observed"]["bid"] + fl["quote_observed"]["ask"])))

    def test_unknown_fees_make_the_toll_not_estimable_and_nothing_is_fabricated(self, tmp_path):
        from apex.options_pilot.fees import UNVERIFIED_FEES
        from apex.options_pilot.records import expected_toll
        et = expected_toll({"bid": 4.5, "ask": 4.6}, UNVERIFIED_FEES.entry(1)["total"], UNVERIFIED_FEES.exit(1)["total"])
        assert et["status"] == "NOT_ESTIMABLE" and et["value"] is None and "unknown cost is not zero" in et["why"]

    def test_quote_callback_observes_every_prerequisite_already_persisted(self, tmp_path):
        h = TB._h(tmp_path)
        seen = {}

        def quote(contract):
            rows = L.read_all(h.ledger)
            seen["kinds"] = [r["kind"] for r in rows]
            it = [r for r in rows if r["kind"] == "pilot_intent"][-1]
            seen["intent_has_before_fields"] = all(k in it for k in ("expected_toll", "doctrine", "pins", "reference_quote", "strike_selection"))
            return {**contract, "bid": 2.4, "ask": 2.5, "bid_size": 9, "ask_size": 12, "timestamp_epoch": h.now() - 1.0}
        h.quotes.override = quote
        d = TB._scan(h)
        assert d["decision"] == "TRADE"
        assert seen["kinds"][-2:] == ["pilot_forecast", "pilot_intent"] and seen["intent_has_before_fields"]

    def test_the_fill_does_not_rewrite_the_intent(self, tmp_path):
        h = TB._h(tmp_path)
        d = TB._scan(h)
        it_before = TB._rec(h, d["receipts"]["intent"])
        L.verify_chain(h.ledger)
        it_after = [r for r in L.read_all(h.ledger) if r["kind"] == "pilot_intent"][0]
        assert it_after["entry_hash"] == it_before["entry_hash"] and it_after["expected_toll"] == it_before["expected_toll"]


# ================================================================ 7. REAL INTEGRATION, TRADE AND MANDATORY WAIT
class TestRealIntegration:
    def test_unconditional_trade_path_to_reconciled_book(self, tmp_path):
        h = TB._h(tmp_path)
        S.open_session(h.bd, symbols=["SPY"])
        d = TB._scan(h)
        assert d["decision"] == "TRADE"
        fl = TB._rec(h, d["receipts"]["fill"])
        assert fl["status"] == "FILLED" and fl["price"] == 2.50
        book_open = h.bd.book()
        assert len(book_open.positions) == 1
        out = TB._exit(h, d["receipts"]["fill"])
        assert out["status"] == "DISCHARGED" or out.get("kind") == "pilot_outcome" or out.get("realized_pnl") is not None
        book = h.bd.book()
        assert not book.positions and book.closed and book.closed[0]["realized_pnl"] is not None
        assert book.summary()["integrity_problems"] == []
        L.verify_chain(h.ledger)
        kinds = [r["kind"] for r in L.read_all(h.ledger)]
        assert kinds[:5] == ["pilot_session_open", "pilot_forecast", "pilot_intent", "pilot_fill", "pilot_decision"] and "pilot_outcome" in kinds

    def test_mandatory_wait_path_leaves_no_position_and_no_reservation(self, tmp_path):
        h = TB._h(tmp_path)
        S.open_session(h.bd, symbols=["SPY"])
        h.quotes.age = 16.0
        d = TB._scan(h)
        assert d["decision"] == "WAIT"
        kinds = [r["kind"] for r in L.read_all(h.ledger)]
        assert "pilot_intent" in kinds and "pilot_fill" in kinds and "pilot_outcome" not in kinds
        book = h.bd.book()
        assert not book.positions and book.summary()["integrity_problems"] == []
