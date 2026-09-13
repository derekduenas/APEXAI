"""TRADINGVIEW-INTEGRATION-003 — the production seam, proved through the REAL pilot path.

TWO THINGS ARE PROVED HERE, and neither is provable by a unit test on the seam in isolation.

    THE JOIN     a live TradingView observation -> snapshot_id -> market state -> model inputs ->
                 candidate set -> the decision record that is actually persisted to the ledger.
                 The scan is a real `session.scan` through a real `Boundary` onto a real ledger file.

    INDEPENDENCE every TradingView failure -- no tools, timeout, auth, rate limit, budget, denial, malformed
                 payload, stale data, a raised exception, a missing snapshot -- produces a NAMED unavailable
                 state, and the scan still reaches a decision. Exits, risk, reservations and order handling
                 neither call this nor wait for it.

THE OBSERVATIONS ARE THE REAL ONES. They are normalized from the payloads recorded in the live smoke
(docs/evidence/tradingview_integration_003/), not invented for the test, so the join is proved against data the
server actually returned.

WHAT IS DELIBERATELY NOT DONE HERE: TradingView bars are never used to BUILD the market state. The twin's state
comes from the twin's own feed; TradingView is external context and never a price of record. A test that composed
a snapshot out of TradingView bars would be proving the opposite of the law this connector exists to keep."""
from __future__ import annotations

import json
import pathlib

import pytest

from apex.options_pilot import ledger as L
from apex.options_pilot import session as S
from apex.options_pilot.synthetic_harness import SyntheticHarness
from apex.pulse_options.snapshot import compose
from apex.tradingview import context as TVC
from apex.tradingview import normalize as N
from apex.tradingview import seam as SEAM

T = 1_789_000_020.0
EVID = pathlib.Path(__file__).resolve().parents[1] / "docs/evidence/tradingview_integration_003"


def live_calls() -> list:
    return json.loads((EVID / "smoke_calls_2026-09-13.json").read_text())


def live_observation(canonical_tool: str, *, known_from: float) -> dict:
    """A REAL recorded live payload, normalized, with its availability moved to `known_from` so the test can
    place it before or after a decision instant. Nothing about the payload is invented."""
    from apex.tradingview import allowlist as AL
    c = next(c for c in live_calls() if AL.canonical(c["tool"]) == canonical_tool)
    return N.observation(tool=c["tool"], args=c["args"], payload=c["payload"],
                         request_start=known_from - 0.5, response_receipt=known_from,
                         symbol=c.get("symbol"), interval=c.get("interval"), units=c.get("units"),
                         entitlement=c.get("entitlement", N.ENTITLEMENT_UNKNOWN))


def bars(n: int, *, end: float) -> list:
    out = []
    for i in range(n):
        t = end - (n - i) * 60.0
        px = 646.0 + 0.01 * i
        out.append({"event_time": t, "available": t + 60.0, "bar_complete": t + 60.0, "start": t,
                    "open": px, "high": px + 0.05, "low": px - 0.05, "close": px,
                    "volume": 1000.0 + i, "vwap": px, "source": "synthetic-feed"})
    return out


def snap_at(as_of: float, *, symbol: str = "SPY", n: int = 40, nudge: float = 0.0) -> dict:
    b = bars(n, end=as_of)
    if nudge:
        b[-1] = {**b[-1], "close": b[-1]["close"] + nudge}
    return compose(symbol=symbol, as_of=as_of, bars=b, source="synthetic-feed")


# ===================================================================== 1. the id


class TestSnapshotIdIsDeterministicAndContentAddressed:
    def test_the_same_state_produces_the_same_id(self):
        assert snap_at(T)["snapshot_id"] == snap_at(T)["snapshot_id"]

    def test_the_id_agrees_with_the_one_content_digest_in_the_system(self):
        """Derived from state_hash, so a short id can never disagree with the long one."""
        s = snap_at(T)
        assert s["snapshot_id"] == "snap:" + s["state_hash"][:32]

    def test_a_different_instant_symbol_or_value_produces_a_different_id(self):
        base = snap_at(T)["snapshot_id"]
        assert snap_at(T + 60.0)["snapshot_id"] != base
        assert snap_at(T, symbol="QQQ")["snapshot_id"] != base
        assert snap_at(T, nudge=0.01)["snapshot_id"] != base, "a changed price must change the state's identity"

    def test_twin_sources_snapshot_emits_it(self):
        """The requirement is about TwinSources.snapshot(), not about compose() alone."""
        from apex.pulse_options.sources import TwinSources
        from apex.options_pilot.clock import Clock

        class Feed:
            provider = "synthetic-feed"

            def bars(self, symbol, start_epoch, end_epoch):
                return [{**b, "receipt_time": b["event_time"] + 60.0} for b in bars(40, end=end_epoch)]

        src = TwinSources(provenance="SYNTHETIC_FIXTURE", clock=Clock(lambda: T), bar_source=Feed(),
                          chain_fn=lambda s, a: [], quote_fn=None, exit_quote_fn=None,
                          fee_schedule=__import__("apex.options_pilot.fees", fromlist=["SYNTHETIC_FEES"]).SYNTHETIC_FEES)
        s1 = src.snapshot("SPY", T)
        assert s1["snapshot_id"].startswith("snap:") and len(s1["snapshot_id"]) == 37
        assert src.snapshot("SPY", T)["snapshot_id"] == s1["snapshot_id"]

    def test_the_seam_adopts_the_states_own_id_and_never_mints_a_competing_one(self):
        """THE DEFECT THIS PINS. The seam used to content-address the snapshot itself, unconditionally. Once the
        snapshot started emitting its own `snapshot_id`, that produced TWO identities for ONE market state, and a
        decision record would have named an id no snapshot carries -- a join that looks joined and is not."""
        snap = snap_at(T)
        j = SEAM.SnapshotJoin(snapshot=snap, symbol="SPY", as_of_epoch=T)
        assert j.snapshot_id == snap["snapshot_id"]
        assert j.snapshot_id_source.startswith("SNAPSHOT_OWN_ID")
        assert j.decision_record()["snapshot_id"] == snap["snapshot_id"]

    def test_a_state_with_no_id_of_its_own_is_still_content_addressed_and_says_so(self):
        legacy = {"symbol": "SPY", "fields": {"x": 1}}
        j = SEAM.SnapshotJoin(snapshot=legacy, symbol="SPY", as_of_epoch=T)
        assert j.snapshot_id and j.snapshot_id_source.startswith("SEAM_COMPUTED")

    def test_model_identities_are_stated_and_never_silently_absent(self):
        from apex.pulse_options.sources import TwinSources
        from apex.options_pilot.clock import Clock
        src = TwinSources(provenance="SYNTHETIC_FIXTURE", clock=Clock(lambda: T), bar_source=object(),
                          chain_fn=lambda s, a: [], quote_fn=None, exit_quote_fn=None,
                          fee_schedule=__import__("apex.options_pilot.fees", fromlist=["SYNTHETIC_FEES"]).SYNTHETIC_FEES)
        mi = src.model_identities()
        assert set(mi) >= {"forecast_model_id", "model_hash", "params_hash", "artifact_digest", "selection_policy"}
        assert all(v for v in mi.values()), "an identity is a value or a stated UNAVAILABLE, never None"


# ===================================================================== 2. dispositions


class TestEveryObservationRecordsWhatBecameOfIt:
    def test_an_observation_that_fed_a_field_is_USED(self):
        obs = live_observation("get_technicals_rating", known_from=T - 30.0)
        ctx = TVC.build(symbol="SPY", as_of=T, snapshot=snap_at(T),
                        observations=[(obs, SEAM.DECISION_TIME_CONTEXT, ["attention.rsi_context"])])
        assert ctx["status"] == TVC.AVAILABLE and ctx["n_used"] == 1
        assert ctx["external_inputs_used"][0]["disposition"] == "USED"
        assert ctx["external_inputs_used"][0]["feeds"] == ["attention.rsi_context"]

    def test_an_observation_that_fed_nothing_is_RETRIEVED_UNUSED_not_omitted(self):
        """Retrieval is not use. The record must distinguish 'we looked and it changed nothing' from
        'we never looked' -- otherwise a connector's contribution can never be audited."""
        obs = live_observation("get_news", known_from=T - 30.0)
        ctx = TVC.build(symbol="SPY", as_of=T, snapshot=snap_at(T),
                        observations=[(obs, SEAM.DECISION_TIME_CONTEXT, [])])
        assert ctx["n_used"] == 0 and ctx["n_retrieved_unused"] == 1
        assert ctx["external_inputs_used"][0]["disposition"] == "RETRIEVED_UNUSED"

    def test_an_observation_that_arrived_after_the_decision_is_REFUSED_LATE_ARRIVING(self):
        """Retrieving something later never makes it available earlier."""
        obs = live_observation("get_ohlcv", known_from=T + 120.0)
        ctx = TVC.build(symbol="SPY", as_of=T, snapshot=snap_at(T),
                        observations=[(obs, SEAM.DECISION_TIME_CONTEXT, ["anything"])])
        e = ctx["external_inputs_used"][0]
        assert e["disposition"] == "REFUSED_LATE_ARRIVING" and e["attached_to"] is None and e["feeds"] == []
        assert ctx["n_refused_late"] == 1 and ctx["n_used"] == 0

    def test_every_disposition_is_one_of_the_three_named_ones(self):
        assert set(SEAM.DISPOSITIONS) == {"USED", "RETRIEVED_UNUSED", "REFUSED_LATE_ARRIVING"}

    def test_stale_data_is_downgraded_and_says_why_rather_than_feeding_a_decision(self):
        obs = live_observation("get_technicals_rating", known_from=T - 5000.0)
        ctx = TVC.build(symbol="SPY", as_of=T, snapshot=snap_at(T),
                        observations=[(obs, SEAM.DECISION_TIME_CONTEXT, ["attention.trend"])], max_age_s=900.0)
        e = ctx["external_inputs_used"][0]
        assert e["disposition"] == "RETRIEVED_UNUSED" and e["feeds"] == [] and "STALE_DATA" in e["why"]
        assert ctx["status"] == TVC.STALE_DATA


class TestPremarketIsPriorContextOnly:
    def test_premarket_attaches_to_the_packet_not_to_the_decision_snapshot(self):
        """Knowable before the snapshot by construction: it guides attention, and the intraday snapshot decides
        whether the setup exists."""
        obs = live_observation("get_earnings_calendar", known_from=T - 7200.0)
        snap = snap_at(T)
        ctx = TVC.build(symbol="SPY", as_of=T, snapshot=snap,
                        observations=[(obs, SEAM.PRIOR_CONTEXT, ["premarket.watch"])],
                        premarket_refs={"packet_ref": "PREMARKET-2026-09-13"})
        e = ctx["external_inputs_used"][0]
        assert e["role"] == "PRIOR_CONTEXT"
        assert e["attached_to"] == "PREMARKET-2026-09-13" != snap["snapshot_id"]

    def test_premarket_is_never_refused_for_being_early_because_early_is_the_point(self):
        obs = live_observation("get_earnings_calendar", known_from=T - 86400.0)
        ctx = TVC.build(symbol="SPY", as_of=T, snapshot=snap_at(T),
                        observations=[(obs, SEAM.PRIOR_CONTEXT, ["premarket.watch"])],
                        premarket_refs={"packet_ref": "P1"}, max_age_s=900.0)
        assert ctx["external_inputs_used"][0]["disposition"] == "USED"
        assert ctx["n_refused_late"] == 0


class TestItStaysExternalContextOnly:
    def test_no_joined_observation_is_ever_calibrated_or_a_signal(self):
        ctx = TVC.build(symbol="SPY", as_of=T, snapshot=snap_at(T),
                        observations=[(live_observation(t, known_from=T - 10.0), SEAM.DECISION_TIME_CONTEXT, ["x"])
                                      for t in ("get_technicals_rating", "get_news", "get_ohlcv")])
        assert ctx["authority"] == "EXTERNAL_CONTEXT_ONLY" and ctx["calibrated"] is False
        for e in ctx["external_inputs_used"]:
            assert e["calibrated"] is False

    def test_an_observation_whose_authority_was_tampered_with_is_refused_and_the_refusal_is_visible(self):
        obs = dict(live_observation("get_news", known_from=T - 10.0))
        obs["calibrated"] = True                       # somebody promoted a headline to a probability
        ctx = TVC.build(symbol="SPY", as_of=T, snapshot=snap_at(T),
                        observations=[(obs, SEAM.DECISION_TIME_CONTEXT, ["direction"])])
        e = ctx["external_inputs_used"][0]
        assert e["disposition"] == "REFUSED_LATE_ARRIVING" and "JOIN_REFUSED" in e["why"]
        assert ctx["n_used"] == 0

    def test_a_buy_recommendation_in_live_data_is_carried_as_text_and_never_as_a_decision(self):
        """The live technicals payload literally contains recommendation "BUY". It reaches the record as an
        observation with EXTERNAL_CONTEXT_ONLY authority and nothing else."""
        obs = live_observation("get_technicals_rating", known_from=T - 10.0)
        assert obs["payload"]["data"]["summary"]["recommendation"] == "BUY"
        assert obs["authority"] == "EXTERNAL_CONTEXT_ONLY" and obs["calibrated"] is False


# ===================================================================== 3. THE JOIN, through the real scan


def run_scan(tmp_path, *, external_context_fn, sid="TVJOIN"):
    led = tmp_path / ("%s.jsonl" % sid)
    h = SyntheticHarness(led, session_id=sid, t0=T, risk="certified")
    snap = snap_at(T)
    base = h.base_forecast

    def forecast_fn(symbol, as_of):
        f = base(symbol, as_of)
        # the twin's own state identity travels with the forecast, exactly as TwinSources does via compose()
        return {**f, "inputs": {**f["inputs"], "state_hash": snap["state_hash"], "snapshot_id": snap["snapshot_id"]}}

    h.forecast_override = forecast_fn
    src = {k: v for k, v in h.sources().items() if k != "exit_quote_fn"}
    out = S.scan(h.bd, symbol="SPY", seq=1, external_context_fn=external_context_fn, **src)
    rows = L.read_all(led)
    dec = next(r for r in rows if r.get("kind") == "pilot_decision")
    return out, dec, snap


class TestTheJoinThroughTheRealPilotPath:
    @pytest.fixture()
    def joined(self, tmp_path):
        obs = live_observation("get_technicals_rating", known_from=T - 20.0)
        news = live_observation("get_news", known_from=T - 25.0)
        snap = snap_at(T)

        def ctx_fn(symbol, as_of):
            return TVC.external_context(
                symbol=symbol, as_of=as_of, snapshot=snap,
                model_identities={"forecast_model_id": "SYNTHETIC_FIXTURE_MODEL", "selection_policy": "PILOT_RULE_V2"},
                fetch_fn=lambda s, a: [(obs, SEAM.DECISION_TIME_CONTEXT, ["attention.trend_context"]),
                                       (news, SEAM.DECISION_TIME_CONTEXT, [])])
        return run_scan(tmp_path, external_context_fn=ctx_fn)

    def test_the_scan_reached_a_decision_and_persisted_it(self, joined):
        out, dec, _ = joined
        assert out["decision"] in ("TRADE", "WAIT", "REFUSE") and out["decision_persisted"] is True

    def test_the_decision_record_names_the_market_state_it_was_made_on(self, joined):
        _, dec, snap = joined
        assert dec["funnel_trace"]["state_snapshot"]["snapshot_id"] == snap["snapshot_id"]
        assert dec["funnel_trace"]["state_snapshot"]["state_hash"] == snap["state_hash"]

    def test_the_observation_is_bound_to_that_same_snapshot_id(self, joined):
        """THE JOIN: observation -> snapshot_id -> market state, in the record that was persisted."""
        _, dec, snap = joined
        used = [e for e in dec["external_inputs_used"] if e["disposition"] == "USED"]
        assert used, "a declared consumer must produce a USED entry"
        assert all(e["attached_to"] == snap["snapshot_id"] for e in used)
        assert dec["external_context"]["snapshot_id"] == snap["snapshot_id"]

    def test_the_chain_is_complete_from_observation_to_decision(self, joined):
        """observation -> snapshot_id -> market state -> model inputs -> candidate set -> decision record."""
        _, dec, snap = joined
        t = dec["funnel_trace"]
        assert dec["external_inputs_used"][0]["tool"] == "get_technicals_rating"        # observation
        assert t["state_snapshot"]["snapshot_id"] == snap["snapshot_id"]                # -> snapshot_id
        assert t["state_snapshot"]["state_hash"] == snap["state_hash"]                  # -> market state
        assert t["model_bundle"]["model_id"]                                            # -> model inputs
        assert "eligible_expressions" in t                                              # -> candidate set
        assert dec["kind"] == "pilot_decision" and dec["decision"]                      # -> decision record

    def test_both_dispositions_survive_into_the_persisted_record(self, joined):
        _, dec, _ = joined
        d = {e["tool"]: e["disposition"] for e in dec["external_inputs_used"]}
        assert d["get_technicals_rating"] == "USED"
        assert d["get_news"] == "RETRIEVED_UNUSED"

    def test_the_persisted_record_still_says_external_context_only(self, joined):
        _, dec, _ = joined
        assert dec["external_context"]["authority"] == "EXTERNAL_CONTEXT_ONLY"
        assert dec["external_context"]["calibrated"] is False
        assert "never a calibrated probability" in dec["external_context"]["law"]


class TestEveryDecisionRecordCarriesTheFieldEvenWithNothingToSay:
    def test_a_scan_with_no_connector_at_all_still_carries_external_inputs_used(self, tmp_path):
        """An OMITTED field would let a broken connector read as a considered abstention. It never is."""
        out, dec, _ = run_scan(tmp_path, external_context_fn=None, sid="TVNONE")
        assert "external_inputs_used" in dec and dec["external_inputs_used"] == []
        assert dec["external_context"]["status"] == TVC.NOT_WIRED
        assert dec["external_context"]["why"]


# ===================================================================== 4. INDEPENDENCE


class TestARefusedScanStillReportsWhatItActuallyObtained:
    def test_a_forecast_refusal_does_not_erase_the_context_that_was_obtained(self, tmp_path):
        """The context is computed before the forecast is attempted. If the forecast provider then fails, the
        decision record must report the context it HELD -- reporting NOT_WIRED there would claim the connector
        was absent when it had in fact answered."""
        obs = live_observation("get_technicals_rating", known_from=T - 20.0)
        snap = snap_at(T)
        led = tmp_path / "refused.jsonl"
        h = SyntheticHarness(led, session_id="TVREF", t0=T, risk="certified")

        def exploding_forecast(symbol, as_of):
            raise RuntimeError("the forecast provider fell over")

        h.forecast_override = exploding_forecast
        src = {k: v for k, v in h.sources().items() if k != "exit_quote_fn"}
        out = S.scan(h.bd, symbol="SPY", seq=1,
                     external_context_fn=lambda s, a: TVC.external_context(
                         symbol=s, as_of=a, snapshot=snap,
                         fetch_fn=lambda _s, _a: [(obs, SEAM.DECISION_TIME_CONTEXT, ["attention.trend"])]),
                     **src)
        assert out["decision"] == "REFUSE"
        dec = next(r for r in L.read_all(led) if r.get("kind") == "pilot_decision")
        assert dec["external_context"]["status"] == TVC.AVAILABLE
        assert dec["external_context"]["snapshot_id"] == snap["snapshot_id"]
        assert [e["disposition"] for e in dec["external_inputs_used"]] == ["USED"]


class TestEveryFailureIsANamedStateAndNothingBlocks:
    @pytest.mark.parametrize("exc,expected", [
        (TimeoutError("provider timed out"), TVC.TIMEOUT),
        (RuntimeError("connection reset"), TVC.PROVIDER_RAISED),
        (KeyError("boom"), TVC.PROVIDER_RAISED),
    ])
    def test_a_raising_provider_becomes_a_named_state_and_never_propagates(self, exc, expected):
        def boom(s, a):
            raise exc
        ctx = TVC.external_context(symbol="SPY", as_of=T, snapshot=snap_at(T), fetch_fn=boom)
        assert ctx["status"] == expected and ctx["status"] in TVC.UNAVAILABLE_STATES
        assert ctx["external_inputs_used"] == [] and ctx["why"]

    def test_a_denied_tool_becomes_a_named_state(self):
        from apex.tradingview import allowlist as AL

        def denied(s, a):
            AL.permit("mcp__mcp-tradingview__mcp-tv-create-alert")
        ctx = TVC.external_context(symbol="SPY", as_of=T, snapshot=snap_at(T), fetch_fn=denied)
        assert ctx["status"] == TVC.TOOL_DENIED

    def test_missing_tools_become_a_named_state(self):
        ctx = TVC.external_context(symbol="SPY", as_of=T, snapshot=snap_at(T), fetch_fn=lambda s, a: None)
        assert ctx["status"] == TVC.TOOLS_MISSING

    def test_no_connector_becomes_NOT_WIRED_rather_than_a_silent_empty(self):
        ctx = TVC.external_context(symbol="SPY", as_of=T, snapshot=snap_at(T), fetch_fn=None)
        assert ctx["status"] == TVC.NOT_WIRED and ctx["wired"] is False

    def test_a_state_without_an_id_is_refused_rather_than_bound_to_nothing(self):
        ctx = TVC.external_context(symbol="SPY", as_of=T, snapshot={"no": "id"}, fetch_fn=lambda s, a: [])
        assert ctx["status"] == TVC.NO_SNAPSHOT_ID

    @pytest.mark.parametrize("adapter_state,expected", [
        ("RATE_LIMITED", TVC.RATE_LIMITED), ("BUDGET_EXHAUSTED", TVC.BUDGET_EXHAUSTED),
        ("AUTHENTICATION_FAILED", TVC.AUTHENTICATION_FAILED), ("MALFORMED_RESPONSE", TVC.MALFORMED_RESPONSE),
        ("PROVIDER_UNAVAILABLE", TVC.PROVIDER_UNAVAILABLE), ("TOOL_DENIED", TVC.TOOL_DENIED),
    ])
    def test_each_adapter_failure_maps_to_its_own_named_state(self, adapter_state, expected):
        env = {"tool": "get_ohlcv", "state": adapter_state, "why": "recorded"}
        ctx = TVC.external_context(symbol="SPY", as_of=T, snapshot=snap_at(T), fetch_fn=lambda s, a: env)
        assert ctx["status"] == expected

    def test_an_unrecognised_adapter_state_is_never_treated_as_success(self):
        env = {"tool": "get_ohlcv", "state": "SOMETHING_NOBODY_MAPPED", "why": "?"}
        ctx = TVC.external_context(symbol="SPY", as_of=T, snapshot=snap_at(T), fetch_fn=lambda s, a: env)
        assert ctx["status"] == TVC.PROVIDER_UNAVAILABLE

    @pytest.mark.parametrize("fetch", [
        lambda s, a: (_ for _ in ()).throw(TimeoutError("slow")),
        lambda s, a: (_ for _ in ()).throw(RuntimeError("down")),
        lambda s, a: None,
    ])
    def test_the_real_scan_still_reaches_a_decision_when_tradingview_fails(self, tmp_path, fetch):
        """THE INDEPENDENCE CLAIM, through the real path: a broken eye does not stop the desk."""
        snap = snap_at(T)
        out, dec, _ = run_scan(
            tmp_path,
            external_context_fn=lambda s, a: TVC.external_context(symbol=s, as_of=a, snapshot=snap, fetch_fn=fetch),
            sid="TVFAIL%d" % id(fetch))
        assert out["decision"] in ("TRADE", "WAIT", "REFUSE") and out["decision_persisted"] is True
        assert dec["external_context"]["status"] in TVC.UNAVAILABLE_STATES
        assert dec["external_inputs_used"] == []

    def test_a_provider_that_raises_past_the_module_is_still_caught_by_the_scan(self, tmp_path):
        """Belt to the module's braces: even a context_fn that bypasses external_context() cannot break a scan."""
        def rogue(s, a):
            raise RuntimeError("a context fn that forgot the contract")
        out, dec, _ = run_scan(tmp_path, external_context_fn=rogue, sid="TVROGUE")
        assert out["decision_persisted"] is True
        assert dec["external_context"]["status"] == TVC.PROVIDER_RAISED


class TestTheSeamCannotReachExecutionRiskOrExits:
    @pytest.mark.parametrize("mod", ["apex.tradingview.context", "apex.tradingview.seam",
                                     "apex.tradingview.adapter", "apex.tradingview.normalize",
                                     "apex.tradingview.allowlist"])
    def test_no_tradingview_module_imports_an_execution_exit_or_risk_path(self, mod):
        """Checked against the IMPORT GRAPH, not against prose -- these modules talk ABOUT exits and risk in their
        own documentation, and a substring scan would confuse saying the word with calling the thing."""
        import ast
        import importlib
        tree = ast.parse(pathlib.Path(importlib.import_module(mod).__file__).read_text())
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
                imported.update("%s.%s" % (node.module, a.name) for a in node.names)
        forbidden = ("exit_policy", "risk_authority", "risk_gate", "lifecycle", "execution", "boundary",
                     "options_pilot.book", "options_pilot.ledger")
        hits = [m for m in imported for f in forbidden if f in m]
        assert hits == [], "%s must not import %s" % (mod, hits)

    @pytest.mark.parametrize("mod", ["apex.options_pilot.exit_policy", "apex.options_pilot.risk_authority",
                                     "apex.options_pilot.risk_gate", "apex.options_pilot.book"])
    def test_no_exit_risk_or_book_module_imports_tradingview(self, mod):
        import importlib
        src = pathlib.Path(importlib.import_module(mod).__file__).read_text()
        assert "tradingview" not in src, "%s must not depend on the connector" % mod

    def test_the_contract_is_stated_on_every_packet(self):
        for ctx in (TVC.unavailable(symbol="SPY", as_of=T, status=TVC.TIMEOUT, why="x"),
                    TVC.build(symbol="SPY", as_of=T, snapshot=snap_at(T), observations=[])):
            assert "EXITS_RISK_RESERVATIONS_AND_ORDERS_ARE_INDEPENDENT" in ctx["blocks_nothing"]["contract"]
