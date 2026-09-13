"""THE SNAPSHOT JOIN SEAM — acceptance.

The seam binds an external observation to the exact decision that used it:
`snapshot_id → market state → model inputs → candidate set → decision record`.

It is tested in isolation because it is NOT wired into the live decision path, and these tests assert that it says
so rather than implying otherwise. No provider is called; every observation here is built from recorded arguments
and payloads through the real normalizer."""
from __future__ import annotations

import pytest

from apex.tradingview import normalize as N
from apex.tradingview import seam as SM

T = 1_789_000_000.0
SNAP = {"symbol": "SPY", "last_bar_close": 651.22, "ret_15": 0.0013, "bars_used": 390}


def obs(tool="get_ohlcv", *, receipt=T - 30.0, args=None, payload=None, symbol="SPY"):
    return N.observation(tool=tool, args=args if args is not None else {"symbol": "NASDAQ:SPY", "interval": "5m"},
                         payload=payload if payload is not None else [{"time": T - 300, "close": 651.0}],
                         request_start=receipt - 0.4, response_receipt=receipt, symbol=symbol)


def join(**kw):
    return SM.SnapshotJoin(snapshot=SNAP, symbol="SPY", as_of_epoch=T, **kw)


# ==================================================== snapshot_id


class TestSnapshotId:

    def test_the_same_state_at_the_same_instant_is_the_same_id(self):
        a = SM.snapshot_id(SNAP, symbol="SPY", as_of_epoch=T)
        b = SM.snapshot_id(dict(SNAP), symbol="SPY", as_of_epoch=T)
        assert a == b and len(a) == 32

    def test_a_changed_value_a_changed_instant_or_a_changed_symbol_changes_the_id(self):
        base = SM.snapshot_id(SNAP, symbol="SPY", as_of_epoch=T)
        assert SM.snapshot_id({**SNAP, "last_bar_close": 651.23}, symbol="SPY", as_of_epoch=T) != base
        assert SM.snapshot_id(SNAP, symbol="SPY", as_of_epoch=T + 0.000001) != base
        assert SM.snapshot_id(SNAP, symbol="QQQ", as_of_epoch=T) != base

    def test_the_id_is_falsifiable_from_the_snapshot_itself(self):
        j = join()
        assert j.market_state_digest == SM.market_state_digest(SNAP)
        assert j.snapshot_id == SM.snapshot_id(SNAP, symbol="SPY", as_of_epoch=T)

    def test_a_decision_cannot_name_a_market_state_it_does_not_have(self):
        with pytest.raises(SM.JoinRefused, match="SNAPSHOT_REQUIRED"):
            SM.snapshot_id(None, symbol="SPY", as_of_epoch=T)
        with pytest.raises(SM.JoinRefused, match="SYMBOL_REQUIRED"):
            SM.snapshot_id(SNAP, symbol="", as_of_epoch=T)
        with pytest.raises(SM.JoinRefused, match="AS_OF_REQUIRED"):
            SM.snapshot_id(SNAP, symbol="SPY", as_of_epoch=None)


# ==================================================== the join


class TestTheJoin:

    def test_an_observation_knowable_at_the_instant_attaches_to_the_snapshot(self):
        """CORRECTED: a caller-supplied `feeds` label is a DECLARED INTEREST, not a read. It attaches the
        observation to the snapshot and yields ATTACHED_CONTEXT -- it does NOT yield USED, which now requires a
        named, implemented consumer to have actually read the observation."""
        j = join()
        e = j.attach(obs(), role=SM.DECISION_TIME_CONTEXT, feeds=["premarket_context.external_context"])
        assert e["disposition"] == SM.ATTACHED_CONTEXT
        assert e["attached_to"] == j.snapshot_id
        assert e["declared_feeds"] == ["premarket_context.external_context"]
        assert e["consumed_by"] == [] and e["n_consumers_read"] == 0
        assert j.decision_record()["n_external_used"] == 0, "a label must never produce USED"

    def test_late_arriving_information_is_refused_not_attached(self):
        """Retrieving something after the decision instant does not make it available earlier."""
        j = join()
        e = j.attach(obs(receipt=T + 60.0), role=SM.DECISION_TIME_CONTEXT, feeds=["anything"])
        assert e["disposition"] == SM.REFUSED_LATE
        assert e["attached_to"] is None and e["declared_feeds"] == []
        assert "LATE_ARRIVING_INFORMATION" in e["why"]
        assert j.decision_record()["n_external_refused_late"] == 1
        assert j.decision_record()["n_external_used"] == 0

    def test_an_observation_that_fed_nothing_says_so(self):
        j = join()
        e = j.attach(obs(tool="get_news"), role=SM.DECISION_TIME_CONTEXT)
        assert e["disposition"] == SM.RETRIEVED_UNUSED and e["declared_feeds"] == []
        assert j.decision_record()["n_external_retrieved_unused"] == 1

    def test_a_premarket_observation_is_prior_context_and_never_decision_time_evidence(self):
        j = join(premarket_packet_ref="PMK-2026-09-12-SPY")
        e = j.attach(obs(receipt=T - 7200.0), role=SM.PRIOR_CONTEXT, feeds=["attention_rank"])
        assert e["role"] == SM.PRIOR_CONTEXT
        assert e["attached_to"] == "PMK-2026-09-12-SPY" != j.snapshot_id
        assert "prior context" in e["note"]

    def test_a_premarket_observation_is_not_subjected_to_the_decision_instant_test(self):
        """Prior context is knowable before the snapshot by construction; that is what makes it prior."""
        j = join(premarket_packet_ref="PMK-1")
        e = j.attach(obs(receipt=T - 20000.0), role=SM.PRIOR_CONTEXT, feeds=["attention_rank"])
        assert e["disposition"] == SM.ATTACHED_CONTEXT      # attached, and still nothing read it
        assert e["role"] == SM.PRIOR_CONTEXT

    def test_an_unrecognised_role_is_refused(self):
        j = join()
        with pytest.raises(SM.JoinRefused, match="ROLE_NOT_RECOGNISED"):
            j.attach(obs(), role="WHATEVER")


# ==================================================== external context, and nothing more


class TestExternalContextOnly:

    def test_a_record_claiming_calibration_is_refused(self):
        j = join()
        with pytest.raises(SM.JoinRefused, match="CALIBRATION_CLAIMED"):
            j.attach({**obs(), "calibrated": True}, role=SM.DECISION_TIME_CONTEXT, feeds=["x"])

    def test_a_record_with_an_altered_authority_or_source_class_is_refused(self):
        j = join()
        with pytest.raises(SM.JoinRefused, match="AUTHORITY_NOT_RECOGNISED"):
            j.attach({**obs(), "authority": "PRIME_ELIGIBLE_SIGNAL"}, role=SM.DECISION_TIME_CONTEXT, feeds=["x"])
        with pytest.raises(SM.JoinRefused, match="SOURCE_CLASS_ALTERED"):
            j.attach({**obs(), "source_class": "PRICE_OF_RECORD"}, role=SM.DECISION_TIME_CONTEXT, feeds=["x"])

    def test_a_record_from_another_provider_is_refused(self):
        j = join()
        with pytest.raises(SM.JoinRefused, match="NOT_A_TRADINGVIEW_OBSERVATION"):
            j.attach({**obs(), "provider": "SOMETHING_ELSE"}, role=SM.DECISION_TIME_CONTEXT, feeds=["x"])

    def test_the_rating_tools_carry_external_context_only_through_the_join(self):
        j = join()
        e = j.attach(obs(tool="get_technicals_rating", payload={"rating": "STRONG_BUY"}),
                     role=SM.DECISION_TIME_CONTEXT, feeds=["premarket_context.external_context"])
        assert e["authority"] == "EXTERNAL_CONTEXT_ONLY" and e["calibrated"] is False

    def test_the_record_states_the_four_things_an_observation_never_becomes(self):
        law = SM.AUTHORITY_LAW
        for phrase in ("never a calibrated probability", "never a trading signal by itself",
                       "never a model promotion", "never an order authorization"):
            assert phrase in law, phrase
        assert SM.AUTHORITY_LAW in join().decision_record()["authority_law"]


# ==================================================== the full chain


class TestTheChainIsRepresentable:

    def _full(self):
        j = join(model_identities={"forecast": "EXP002_L", "params_hash": "ca04fc6e713e1a5c",
                                   "variance": "GARCH-t", "regime": "MarkovSwitching2"},
                 premarket_packet_ref="PMK-2026-09-12-SPY")
        j.attach(obs(tool="get_earnings_calendar", receipt=T - 9000.0), role=SM.PRIOR_CONTEXT,
                 feeds=["attention_rank"])
        j.attach(obs(tool="get_ohlcv", receipt=T - 12.0), role=SM.DECISION_TIME_CONTEXT,
                 feeds=["premarket_context.external_context", "setup.features.cross_check"])
        j.attach(obs(tool="get_news", receipt=T - 40.0), role=SM.DECISION_TIME_CONTEXT)
        return j.decision_record(
            candidate_set=[{"expression": "LONG_CALL", "eligibility": "PRIME_ELIGIBLE"},
                           {"expression": "STOCK", "eligibility": "RESEARCH_OBSERVATION_ONLY"}],
            decision={"decision": "WAIT", "why": "NO_ELIGIBLE_CANDIDATE"})

    def test_snapshot_id_market_state_models_candidates_and_decision_are_all_present(self):
        r = self._full()
        assert r["snapshot_id"] and r["market_state_digest"]
        assert r["model_identities"]["forecast"] == "EXP002_L"
        assert len(r["candidate_set"]) == 2
        assert r["decision"]["decision"] == "WAIT"
        # CORRECTED: two observations carry declared interests and one does not. NOTHING read any of them, so
        # nothing is USED -- the honest counts are 2 attached-context and 1 retrieved-unused.
        assert r["n_external_used"] == 0
        assert r["n_external_attached_context"] == 2 and r["n_external_retrieved_unused"] == 1

    def test_the_record_says_which_observation_fed_which_field(self):
        r = self._full()
        ohlcv = [e for e in r["external_inputs_used"] if e["tool"] == "get_ohlcv"][0]
        assert "setup.features.cross_check" in ohlcv["declared_feeds"]
        assert ohlcv["disposition"] == SM.ATTACHED_CONTEXT and ohlcv["consumed_by"] == []
        assert "not evidence that anything read" in ohlcv["declared_feeds_note"]
        news = [e for e in r["external_inputs_used"] if e["tool"] == "get_news"][0]
        assert news["disposition"] == SM.RETRIEVED_UNUSED

    def test_missing_candidates_or_decision_are_named_unavailable_not_omitted(self):
        r = join().decision_record()
        assert "UNAVAILABLE" in r["candidate_set"]["status"]
        assert "UNAVAILABLE" in r["decision"]["status"]

    def test_a_join_with_no_model_identity_says_so(self):
        assert "UNAVAILABLE" in join().decision_record()["model_identities"]["status"]

    def test_the_record_declares_that_production_wiring_is_not_complete(self):
        r = self._full()
        assert "SEAM_NOT_WIRED" in r["wiring_status"]
        assert "NOT complete" in r["wiring_status"]


# ==================================================== the seam touches no execution path


def test_the_seam_imports_nothing_from_execution_risk_exits_or_orders():
    """Checked on the IMPORT GRAPH, not on the prose: the docstring names these paths precisely because it
    promises not to touch them, so a text search would fail on its own explanation."""
    import ast
    import inspect
    tree = ast.parse(inspect.getsource(SM))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
            imported.update("%s.%s" % (node.module or "", a.name) for a in node.names)
    assert imported == {"__future__", "__future__.annotations", "hashlib", "json", "", ".normalize"}, imported
    for banned in ("options_pilot", "execution", "risk", "lifecycle", "exit", "boundary", "order",
                   "requests", "urllib", "httpx", "socket"):
        assert not any(banned in m for m in imported), (banned, imported)
