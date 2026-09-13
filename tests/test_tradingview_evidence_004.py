"""TRADINGVIEW-INTEGRATION-003 — the four evidence corrections demanded at review.

Each class here exists because a claim made in the first round was WEAKER THAN IT SOUNDED.

    2. EXIT INDEPENDENCE     proved before against a callback that RAISED TimeoutError. That establishes exception
                             handling and nothing more: control came back. Proved here against a provider that
                             NEVER RETURNS, with a due exit serviced while the fetch is still outstanding.
    3. USED                  set before whenever a CALLER passed a `feeds` label. That proved a label was written,
                             not that anything read the observation. USED now requires a named, implemented
                             consumer to have actually read it, and APEX registers none.
    4. ENTITLEMENT           recorded before as DELAYED_VERIFIED because the provider said "delayed 15+ minutes".
                             A provider's statement about its own feed is not a verification."""
from __future__ import annotations

import json
import pathlib
import threading
import time

import pytest

from apex.options_pilot import exit_policy as EP
from apex.options_pilot import ledger as L
from apex.options_pilot import lifecycle as LC
from apex.tradingview import consumers as CONS
from apex.tradingview import context as TVC
from apex.tradingview import normalize as N
from apex.tradingview import seam as SEAM

EVID = pathlib.Path(__file__).resolve().parents[1] / "docs/evidence/tradingview_integration_003"
T = 1_789_000_020.0
SNAP = {"snapshot_id": "snap:deadbeef", "symbol": "SPY"}


def obs(tool="get_technicals_rating", *, receipt=T - 10.0, payload=None):
    return N.observation(tool=tool, args={"symbol": "SPY"}, payload=payload if payload is not None else {"x": 1},
                         request_start=receipt - 0.5, response_receipt=receipt, symbol="SPY")


# ============================================================ 2. A PROVIDER THAT NEVER RETURNS


class TestAProviderThatNeverReturns:
    """A raised exception returns control. A hung provider does not, and no try/except can catch it."""

    @pytest.fixture()
    def hung(self):
        gate = {"entered": threading.Event(), "release": threading.Event(), "returned": threading.Event()}

        def fetch(symbol, as_of):
            gate["entered"].set()
            gate["release"].wait()                  # never set during the test: this call does not come back
            gate["returned"].set()
            return []
        gate["fetch"] = fetch
        yield gate
        gate["release"].set()                       # let the abandoned worker finish so the test leaves nothing running

    def test_the_deadline_bounds_the_wait_and_names_the_state(self, hung):
        t0 = time.time()
        ctx = TVC.external_context(symbol="SPY", as_of=T, snapshot=SNAP, fetch_fn=hung["fetch"], deadline_s=0.3)
        elapsed = time.time() - t0
        assert ctx["status"] == TVC.TIMEOUT
        assert 0.3 <= elapsed < 3.0, "the caller waited the deadline, not forever (%.2fs)" % elapsed
        assert hung["entered"].is_set(), "the provider really was entered"
        assert not hung["returned"].is_set(), "and it really never returned"

    def test_the_record_admits_the_request_is_abandoned_not_killed(self, hung):
        ctx = TVC.external_context(symbol="SPY", as_of=T, snapshot=SNAP, fetch_fn=hung["fetch"], deadline_s=0.2)
        assert "ABANDONED" in ctx["why"] and "cannot be killed" in ctx["why"]

    def test_the_abandoned_worker_is_a_daemon_and_cannot_hold_the_process_open(self, hung):
        TVC.external_context(symbol="SPY", as_of=T, snapshot=SNAP, fetch_fn=hung["fetch"], deadline_s=0.2)
        workers = [t for t in threading.enumerate() if t.name == "tradingview-external-context"]
        assert workers, "the worker is still running -- that is the honest situation"
        assert all(t.daemon for t in workers)

    def test_a_hung_provider_is_reported_differently_from_one_that_raises_TimeoutError(self, hung):
        hungctx = TVC.external_context(symbol="SPY", as_of=T, snapshot=SNAP, fetch_fn=hung["fetch"], deadline_s=0.2)

        def raiser(s, a):
            raise TimeoutError("provider raised")
        raised = TVC.external_context(symbol="SPY", as_of=T, snapshot=SNAP, fetch_fn=raiser, deadline_s=0.2)
        assert hungctx["status"] == raised["status"] == TVC.TIMEOUT
        assert "PROVIDER_DID_NOT_RETURN" in hungctx["why"] and "PROVIDER_DID_NOT_RETURN" not in raised["why"]


class TestADueExitIsServicedWhileRetrievalIsOutstanding:
    """THE CLAIM UNDER TEST: a provider that never returns cannot stall the lifecycle scheduler.

    This runs the REAL LifecycleRunner over the exit-scheduling fixture: a scan opens a position, the exit falls
    due, and the external-context provider blocks from the moment the scan calls it and is STILL BLOCKED when the
    run ends. The exit must be serviced anyway."""

    HOLD = 900.0
    CONTRACT = "SPY|2026-10-09|650.0|CALL"

    @pytest.fixture()
    def blocking(self):
        gate = {"entered": threading.Event(), "release": threading.Event(), "returned": threading.Event(),
                "calls": []}

        def fetch(symbol, as_of):
            gate["calls"].append(as_of)
            gate["entered"].set()
            gate["release"].wait()
            gate["returned"].set()
            return []
        gate["fetch"] = fetch
        yield gate
        gate["release"].set()

    def _run(self, tmp_path, blocking):
        from apex.options_pilot.synthetic_harness import SyntheticHarness
        from tests.test_exit_scheduling_002 import Feed

        h = SyntheticHarness(tmp_path / "led.jsonl", session_id="TVHUNG", t0=T, risk="certified")
        h.chain = [{**c, "ask": 4.95} for c in h.chain]
        h.quotes.ask, h.quotes.bid = 4.95, 4.90
        lc = LC.MonotonicClock(h.now())
        h.clock = lc.clock(); h.bd.clock = h.clock; h.now = lc.now; h.advance = lc.sleep
        h.bd.exit_policy = EP.EXIT_POLICY_V2
        feed = Feed(h, arrivals=[T + self.HOLD + 0.2], quote_lag_s=0.1, bid=4.73, ask=4.78)
        src = dict(h.sources())
        src["exit_quote_fn"] = feed
        src["external_context_fn"] = lambda s, a: TVC.external_context(
            symbol=s, as_of=a, snapshot={"snapshot_id": "snap:hungtest"}, fetch_fn=blocking["fetch"], deadline_s=0.3)
        r = LC.LifecycleRunner(boundary=h.bd, sources=src, clock=lc, symbols=["SPY"],
                               selection_policy="PILOT_RULE_V2", scan_epochs=[T],
                               observation_feed=feed.feed_for(self.CONTRACT))
        rep = r.run()
        return h, rep

    def test_the_position_opened_even_though_the_provider_never_answered(self, tmp_path, blocking):
        h, rep = self._run(tmp_path, blocking)
        fill = next((x for x in L.read_all(h.bd.ledger) if x["kind"] == "pilot_fill" and x["status"] == "FILLED"), None)
        assert fill is not None, "the scan completed and opened a position despite the hung provider"
        assert blocking["entered"].is_set(), "the provider was genuinely entered"

    def test_the_due_exit_was_serviced_while_the_fetch_was_still_outstanding(self, tmp_path, blocking):
        """THE POINT. The fetch is entered during the scan and has still not returned when the run ends, and the
        due exit is serviced in between."""
        h, rep = self._run(tmp_path, blocking)
        assert blocking["entered"].is_set()
        assert not blocking["returned"].is_set(), "the retrieval is STILL outstanding at the end of the run"
        outcomes = [r for r in L.read_all(h.bd.ledger) if r["kind"] == "pilot_outcome"]
        assert outcomes, "the due exit was serviced"
        assert any(o.get("discharges_position") for o in outcomes), "and the position was discharged"

    def test_the_scan_recorded_the_provider_as_TIMEOUT_rather_than_waiting(self, tmp_path, blocking):
        h, rep = self._run(tmp_path, blocking)
        dec = next(r for r in L.read_all(h.bd.ledger) if r["kind"] == "pilot_decision")
        assert dec["external_context"]["status"] == TVC.TIMEOUT
        assert dec["external_inputs_used"] == []

    def test_no_exit_handler_consults_external_context_at_all(self):
        """Structural: the connector is reachable from the SCAN handler only. No exit, retry, window-close or
        deadline re-check path names it."""
        import ast
        src = pathlib.Path(LC.__file__).read_text()
        tree = ast.parse(src)
        for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
            if fn.name == "_on_scan":
                continue
            body = ast.get_source_segment(src, fn) or ""
            assert "external_context" not in body, "%s must not consult external context" % fn.name


# ============================================================ 3. USED REQUIRES A READER


class TestUsedRequiresANamedImplementedConsumer:
    def test_the_production_registry_is_empty_and_that_is_the_correct_state(self):
        d = CONS.describe()
        assert d["production_registry_is_empty"] is True
        assert list(CONS.REVIEWED_PRODUCTION_CONSUMERS) == []
        CONS.assert_no_unreviewed_production_consumer()

    def test_a_production_consumer_cannot_be_registered_without_review(self):
        with pytest.raises(CONS.ConsumerRefused, match="CONSUMER_NOT_REVIEWED"):
            CONS.register("sneaky", tool="get_technicals_rating", fn=lambda o: 1, purpose="x", production=True)

    def test_a_caller_label_produces_no_consumer_read_at_all(self):
        ctx = TVC.build(symbol="SPY", as_of=T, snapshot=SNAP,
                        observations=[(obs(), SEAM.DECISION_TIME_CONTEXT, ["setup.trend"])])
        e = ctx["external_inputs_used"][0]
        assert e["disposition"] == SEAM.ATTACHED_CONTEXT
        assert e["n_consumers_read"] == 0 and e["consumed_by"] == []
        assert ctx["n_used"] == 0

    def test_a_registered_consumer_that_really_reads_produces_USED_with_reproducible_evidence(self):
        """The ONLY way to USED. The consumer below is a TEST consumer, registered for this test and removed
        after it; it is not part of APEX and nothing in the product path registers anything."""
        def read_rsi(o):
            return {"rsi": o["payload"]["data"]["oscillators"]["rsi"]}

        CONS.register("test_only_rsi_reader", tool="get_technicals_rating", fn=read_rsi, purpose="test evidence")
        try:
            payload = {"data": {"oscillators": {"rsi": 50.307310750162024}}}
            o = obs(payload=payload)
            ctx = TVC.build(symbol="SPY", as_of=T, snapshot=SNAP,
                            observations=[(o, SEAM.DECISION_TIME_CONTEXT, [])])
            e = ctx["external_inputs_used"][0]
            assert e["disposition"] == SEAM.USED and ctx["n_used"] == 1
            read = e["consumed_by"][0]
            # a NAMED consumer, its ACTUAL implementation, and WHAT IT DERIVED
            assert read["consumer"] == "test_only_rsi_reader"
            assert read["implementation"].endswith(":TestUsedRequiresANamedImplementedConsumer."
                                                   "test_a_registered_consumer_that_really_reads_produces_USED_"
                                                   "with_reproducible_evidence.<locals>.read_rsi")
            assert read["value"] == {"rsi": 50.307310750162024}
            # REPRODUCIBLE: re-running the same function on the same observation gives the same digest
            again = CONS.run(o)[0]
            assert again["value_digest"] == read["value_digest"]
        finally:
            CONS.unregister("test_only_rsi_reader")

    def test_a_consumer_that_raises_did_not_read_it_and_produces_no_USED(self):
        def boom(o):
            raise RuntimeError("reader broke")

        CONS.register("test_only_broken", tool="get_technicals_rating", fn=boom, purpose="test evidence")
        try:
            ctx = TVC.build(symbol="SPY", as_of=T, snapshot=SNAP,
                            observations=[(obs(), SEAM.DECISION_TIME_CONTEXT, ["setup.trend"])])
            e = ctx["external_inputs_used"][0]
            assert ctx["n_used"] == 0 and e["disposition"] == SEAM.ATTACHED_CONTEXT
            assert e["consumer_failures"][0]["read_ok"] is False
            assert "CONSUMER_RAISED" in e["consumer_failures"][0]["why"]
        finally:
            CONS.unregister("test_only_broken")

    def test_a_consumer_that_read_and_derived_nothing_is_still_a_read(self):
        """'Looked and found nothing' is a different fact from 'never looked', and both are recorded."""
        CONS.register("test_only_null", tool="get_technicals_rating", fn=lambda o: None, purpose="test evidence")
        try:
            ctx = TVC.build(symbol="SPY", as_of=T, snapshot=SNAP,
                            observations=[(obs(), SEAM.DECISION_TIME_CONTEXT, [])])
            e = ctx["external_inputs_used"][0]
            assert e["disposition"] == SEAM.USED and e["consumed_by"][0]["value"] is None
        finally:
            CONS.unregister("test_only_null")


# ============================================================ 4. PROVENANCE AND ENTITLEMENT


class TestEntitlementSeparatesClaimFromVerification:
    DELAY_NOTICE = "Market data notice: bars are delayed 15+ minutes depending on the exchange"

    def test_a_verified_entitlement_cannot_be_claimed_without_evidence(self):
        for state in N.VERIFIED_STATES:
            with pytest.raises(N.NormalizationRefused, match="ENTITLEMENT_NOT_VERIFIED"):
                N.observation(tool="get_ohlcv", args={}, payload={}, request_start=1.0, response_receipt=2.0,
                              entitlement=state)

    def test_a_provider_statement_becomes_PROVIDER_STATED_DELAY_not_a_verified_label(self):
        o = obs(tool="get_ohlcv", payload={"notice": self.DELAY_NOTICE})
        assert o["entitlement"] == N.ENTITLEMENT_PROVIDER_STATED_DELAY
        assert o["provider_delay_statement"] == self.DELAY_NOTICE

    def test_the_three_facts_are_kept_apart(self):
        o = obs(tool="get_ohlcv", payload={"notice": self.DELAY_NOTICE})
        assert "NOT_MEASURED" in o["latency_measurement"]
        assert "NOT_ESTABLISHED" in o["account_entitlement"]
        assert o["entitlement_verification"] is None

    def test_entitlement_is_derived_from_the_payload_not_asserted_by_a_caller(self):
        """A response that says nothing about delay stays UNKNOWN however much a caller would like otherwise."""
        assert obs(tool="get_ohlcv", payload={"bars": []})["entitlement"] == N.ENTITLEMENT_UNKNOWN

    def test_a_verified_label_is_possible_only_with_stated_evidence(self):
        o = N.observation(tool="get_ohlcv", args={}, payload={}, request_start=1.0, response_receipt=2.0,
                          entitlement="DELAYED_VERIFIED",
                          verification_evidence="compared against an independent feed on 2026-XX-XX (hypothetical)")
        assert o["entitlement"] == "DELAYED_VERIFIED" and o["entitlement_verification"]


class TestTheSmokeArtifactsAreLabelledAndPreserved:
    def test_the_original_artifacts_still_exist_unchanged_including_the_wrong_label(self):
        """The first run is EVIDENCE, including its mistake. It is not rewritten."""
        calls = json.loads((EVID / "smoke_calls_2026-09-13.json").read_text())
        original = json.loads((EVID / "smoke_result_2026-09-13.json").read_text())
        bars_call = next(c for c in calls if c["tool"].endswith("get-ohlcv"))
        assert bars_call["entitlement"] == "DELAYED_VERIFIED", "the original recording is preserved as captured"
        assert original["n_calls"] == 9

    def test_the_relabelled_run_discards_the_recorded_claim_and_derives_entitlement(self):
        r = json.loads((EVID / "smoke_result_2026-09-13_relabelled.json").read_text())
        bars = [x for x in r["results"] if x["tool_canonical"] == "get_ohlcv"][0]
        assert bars["recorded_entitlement_claim"] == "DELAYED_VERIFIED"
        assert "DISCARDED_NOT_EVIDENCE" in bars["recorded_entitlement_claim_status"]
        assert bars["observation"]["entitlement"] == N.ENTITLEMENT_PROVIDER_STATED_DELAY
        assert bars["observation"]["provider_delay_statement"]

    def test_no_new_live_calls_were_made_for_the_relabelled_run(self):
        """Same nine recordings, same instants. The relabelling is a replay, not a re-fetch."""
        calls = json.loads((EVID / "smoke_calls_2026-09-13.json").read_text())
        r = json.loads((EVID / "smoke_result_2026-09-13_relabelled.json").read_text())
        assert r["n_calls"] == len(calls) == 9
        for c, res in zip(calls, r["results"]):
            assert res["tool"] == c["tool"]
            assert res["observation"]["response_receipt_epoch"] == c["response_receipt"]

    def test_the_run_declares_its_capture_and_timing_methods(self):
        r = json.loads((EVID / "smoke_result_2026-09-13_relabelled.json").read_text())
        p = r["provenance"]
        assert p["capture_method"] == "AGENT_TRANSCRIPTION"
        assert "not a byte-exact transport capture" in p["what_that_means"].lower()
        assert p["timing_method"] == "CLOCK_BRACKET_BOUNDS_NOT_TRANSPORT_INSTANTS"
        assert "NOT_MEASURED" in p["latency"] and "NOT_ESTABLISHED" in p["entitlement"]

    def test_the_provenance_document_exists_and_names_the_limits(self):
        t = (EVID / "PROVENANCE.md").read_text()
        for phrase in ("AGENT TRANSCRIPTION", "no packet trace", "containing interval",
                       "shares one bracket", "not a verification"):
            assert phrase in t, phrase
