"""Weekend commissioning, Brick 1: one duplicate-conflict policy shared by every consumer; explicit live wiring; runtime identity."""
from __future__ import annotations

import json

import pytest

from apex.options_pilot import expression_rule as ER, ledger as L
from apex.options_pilot.risk_authority import entry_cap_price
from apex.pulse_options import sources as SRC
from apex.pulse_options.providers import LiveGate, ProviderUnavailable, ThetaChainAdapter
from apex.options_pilot.clock import Clock

SNAP = "2026-09-11 10:53:23"
SNAP_EPOCH = ThetaChainAdapter.et_naive_to_epoch(SNAP)
RECEIPT = SNAP_EPOCH + 5.0
GATE = LiveGate(env={"APEX_PILOT_LIVE_DATA": "ENABLED"}, secret_fn=lambda n: "present")


def _row(strike, right="C", bid="4.50", ask="4.63", bs="58", as_="139", ts=SNAP):
    return {"symbol": "SPY", "expiration": "20261002", "strike": strike, "right": right, "timestamp": ts, "bid": bid, "ask": ask, "bid_size": bs, "ask_size": as_}


CONFLICT = [_row("770.000", ask="4.00", bid="3.90"), _row("770.000", ask="9.00", bid="8.90")]   # same contract, two observations
IDENTICAL = [_row("771.000", ask="4.20", bid="4.10"), _row("771.000", ask="4.20", bid="4.10")]
ALT = [_row("772.000", ask="4.40", bid="4.30")]


class TestOnePolicyThreeConsumers:
    def test_provider_boundary_collapses_identical_and_excludes_conflicts_order_independently(self):
        a = SRC.live_chain_rows(CONFLICT + IDENTICAL + ALT, symbol="SPY", receipt_time=RECEIPT)
        b = SRC.live_chain_rows(list(reversed(CONFLICT + IDENTICAL + ALT)), symbol="SPY", receipt_time=RECEIPT)
        for rows in (a, b):
            assert sorted(r["strike"] for r in rows) == [771.0, 772.0]
            assert rows.conflicted == {("2026-10-02", 770.0, "CALL")}
            ex = [x for x in rows.exclusions if x["why"].startswith("DUPLICATE_CONFLICT")]
            assert len(ex) == 1 and len(ex[0]["observations"]) == 2 and {o["ask"] for o in ex[0]["observations"]} == {4.0, 9.0}
        assert sorted(r["ask"] for r in a) == sorted(r["ask"] for r in b) == [4.2, 4.4]   # same rows, same prices, either order
        assert a.report()["duplicate_policy"] == "DUPLICATE_POLICY_V1" and a.report()["n_conflicted_contracts"] == 1

    def test_normalization_to_deterministic_selection(self):
        for order in (CONFLICT + IDENTICAL + ALT, list(reversed(CONFLICT + IDENTICAL + ALT))):
            chain = SRC.live_chain_rows(order, symbol="SPY", receipt_time=RECEIPT)
            v = ER.choose(symbol="SPY", direction_signal="LONG", spot=763.94, as_of="2026-09-11T14:53:23Z", available=chain,
                          max_entry_price=entry_cap_price(), as_of_epoch=RECEIPT)
            assert v["contract"]["strike"] == 771.0 and v["reference_ask"] == 4.2
            assert v["strike_selection"]["exclusions"]["n_provider"] == 1                  # the provider's conflict exclusion survives into the intent

    def test_normalization_to_funnel_pricing(self):
        """TwinSources._funnel_quotes must reject the conflicted contract, keep the alternative, and never fetch the
        conflicted contract again from the quote provider."""
        fetched = []

        def quote_fn(contract):
            fetched.append((contract["strike"], contract["right"]))
            raise ProviderUnavailable("should not be needed for rows already priced")
        tw = SRC.TwinSources(provenance="SYNTHETIC_FIXTURE", clock=Clock(lambda: RECEIPT), bar_source=None,
                             chain_fn=lambda s, t: None, quote_fn=quote_fn, exit_quote_fn=quote_fn, fee_schedule=SRC.SYNTHETIC_FEES,
                             selection_policy="FULL_FUNNEL_V1")
        for order in (CONFLICT + IDENTICAL + ALT, list(reversed(CONFLICT + IDENTICAL + ALT))):
            chain = SRC.live_chain_rows(order, symbol="SPY", receipt_time=RECEIPT)
            q = tw._funnel_quotes("SPY", RECEIPT, 763.94, chain)
            assert q[("2026-10-02", 771.0, "CALL")]["ask"] == 4.2 and q[("2026-10-02", 772.0, "CALL")]["ask"] == 4.4
            assert q[("2026-10-02", 770.0, "CALL")]["source"].startswith("REJECTED: DUPLICATE_CONFLICT") and "ask" not in q[("2026-10-02", 770.0, "CALL")]
            assert (770.0, "CALL") not in fetched                                          # no fallback re-admission
            assert tw.last_chain_report["SPY"]["n_conflicted_contracts"] == 1

    def test_funnel_pricing_applies_the_same_policy_to_a_plain_chain_list(self):
        tw = SRC.TwinSources(provenance="SYNTHETIC_FIXTURE", clock=Clock(lambda: RECEIPT), bar_source=None,
                             chain_fn=lambda s, t: None, quote_fn=lambda c: None, exit_quote_fn=lambda c: None, fee_schedule=SRC.SYNTHETIC_FEES,
                             selection_policy="FULL_FUNNEL_V1")
        plain = [{"expiration": "2026-10-02", "strike": 770.0, "right": "CALL", "bid": 3.9, "ask": 4.0, "bid_size": 5, "ask_size": 5, "timestamp_epoch": RECEIPT - 1},
                 {"expiration": "2026-10-02", "strike": 770.0, "right": "CALL", "bid": 8.9, "ask": 9.0, "bid_size": 5, "ask_size": 5, "timestamp_epoch": RECEIPT - 1}]
        q = tw._funnel_quotes("SPY", RECEIPT, 763.94, plain)
        assert "ask" not in q[("2026-10-02", 770.0, "CALL")] and "DUPLICATE_CONFLICT" in q[("2026-10-02", 770.0, "CALL")]["source"]

    def test_normalization_to_entry_and_exit_quote_acquisition(self):
        src = SRC.live_twin_sources(gate=GATE, expirations_fn=lambda s: ["20261002"], chain_snapshot_fn=lambda s, e: CONFLICT + IDENTICAL + ALT,
                                    clock=Clock(lambda: RECEIPT))
        with pytest.raises(ProviderUnavailable, match="QUOTE_CONFLICTED_IN_SNAPSHOT"):
            src._quote_fn({"symbol": "SPY", "expiration": "2026-10-02", "strike": 770.0, "right": "CALL"})
        with pytest.raises(ProviderUnavailable, match="QUOTE_CONFLICTED_IN_SNAPSHOT"):
            src._exit_quote_fn({"symbol": "SPY", "expiration": "2026-10-02", "strike": 770.0, "right": "CALL"})
        q = src._quote_fn({"symbol": "SPY", "expiration": "2026-10-02", "strike": 771.0, "right": "CALL"})
        assert q["ask"] == 4.2 and q["chain_report"]["n_conflicted_contracts"] == 1

    def test_all_conflicted_snapshot_is_a_named_refusal_everywhere(self):
        rows = CONFLICT + [_row("771.000", ask="4.20", bid="4.10"), _row("771.000", ask="4.25", bid="4.10")]
        chain = SRC.live_chain_rows(rows, symbol="SPY", receipt_time=RECEIPT)
        assert len(chain) == 0 and len(chain.conflicted) == 2
        with pytest.raises(ER.RuleRefused, match="NO_ELIGIBLE_EXPIRY|NO_STRIKES|NO_VALID_ROWS"):   # an empty snapshot is a named refusal
            ER.choose(symbol="SPY", direction_signal="LONG", spot=763.94, as_of="2026-09-11T14:53:23Z", available=chain,
                      max_entry_price=entry_cap_price(), as_of_epoch=RECEIPT)
        src = SRC.live_twin_sources(gate=GATE, expirations_fn=lambda s: ["20261002"], chain_snapshot_fn=lambda s, e: rows, clock=Clock(lambda: RECEIPT))
        with pytest.raises(ProviderUnavailable, match="CHAIN_EMPTY.*DUPLICATE_CONFLICT"):
            src.chain_fn("SPY", RECEIPT)


class TestLiveWiring:
    def test_default_production_sources_report_the_unattached_client_and_v2(self):
        from apex.options_pilot import entrypoint as PEP
        p = PEP.ProductionSources()
        d = p.describe()
        assert d["selection_policy"] == "PILOT_RULE_V2" and d["wiring"]["attach_market_data_http"] is False
        assert "NOT ATTACHED" in d["wiring"]["bars_nbbo_client"] and d["fee_schedule"]["provenance"] == "UNVERIFIED"

    def test_joint_without_engine_and_context_is_refused_by_the_preserved_guard(self):
        from apex.options_pilot import entrypoint as PEP
        with pytest.raises(ValueError, match="JOINT_FUNNEL_V1 requires joint_engine and joint_context_fn"):
            PEP.ProductionSources(selection_policy="JOINT_FUNNEL_V1")
        with pytest.raises(ValueError, match="JOINT_FUNNEL_V1 requires"):
            PEP.ProductionSources(selection_policy="JOINT_FUNNEL_V1", wiring=PEP.LiveWiring(attach_market_data_http=True))

    def test_full_with_attached_client_still_refuses_before_any_network_without_the_gate(self):
        from apex.options_pilot import entrypoint as PEP
        p = PEP.ProductionSources(selection_policy="FULL_FUNNEL_V1", wiring=PEP.LiveWiring(attach_market_data_http=True))
        assert "guarded_get" in p.describe()["wiring"]["bars_nbbo_client"] and "HTTP_POLICY_V1" in p.describe()["wiring"]["bars_nbbo_client"]
        with pytest.raises(ProviderUnavailable):
            p.sources()["chain_fn"]("SPY", RECEIPT)                        # LiveGate refuses: switch not set in this process
        assert p.funnel_engine is not None and p.selection_policy == "FULL_FUNNEL_V1"

    def test_runtime_identity_is_measured_and_recorded_on_the_report_and_session_open(self, tmp_path):
        from apex.options_pilot import entrypoint as PEP
        from apex.options_pilot.synthetic_harness import make_harness
        led = tmp_path / "led.jsonl"
        h = make_harness(led, symbols=["SPY"])
        rep = PEP.run_pilot(ledger=led, out=tmp_path / "o.json", symbols=["SPY"], provider=PEP._HarnessProvider(h), session_id="RI-1", release="r")
        ri = rep["runtime_identity"]
        assert ri["kind"] == "RUNTIME_IDENTITY" and len(ri["git_commit"]) == 40 and ri["git_dirty"] in (True, False)
        assert "apex.joint_wb.engine" in ri["decision_path_module_digests"] and ri["dependencies"]["numpy"]
        assert "does not prove the host installed" in ri["scope"]
        so = next(r for r in L.read_all(led) if r["kind"] == "pilot_session_open")
        assert so["runtime_identity"]["decision_path_tree_digest"] == ri["decision_path_tree_digest"]
