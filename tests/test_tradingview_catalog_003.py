"""TRADINGVIEW-INTEGRATION-002 — the LIVE catalog reconciliation, and the live smoke's evidence.

Everything here is about one thing the earlier bricks could not test: the tools this server ACTUALLY exposes.
The connector was written in bare snake_case against the published documentation. The live server speaks
`mcp__mcp-tradingview__mcp-tv-<kebab>`. Until this was reconciled the connector refused all nine of its own
allowed tools in their live spelling, and `mcp-tv-stop-alerts` slipped the forbidden-marker belt because the
live spelling contains no underscore.

These tests pin the reconciliation, and they pin the direction of every failure: DENY."""
from __future__ import annotations

import json
import pathlib

import pytest

from apex.tradingview import allowlist as AL
from apex.tradingview import normalize as N

REPO = pathlib.Path(__file__).resolve().parents[1]
CATALOG = REPO / "docs/evidence/tradingview_integration_003/live_catalog_2026-09-12.json"
SMOKE = REPO / "docs/evidence/tradingview_integration_003/smoke_result_2026-09-13.json"


class TestTheLiveCatalogIsFullyClassified:
    def test_the_recorded_catalog_matches_the_module_and_is_not_a_stale_copy(self):
        rec = json.loads(CATALOG.read_text())
        live = {AL.canonical(t) for t in rec["tools_exposed_verbatim"]}
        assert len(rec["tools_exposed_verbatim"]) == rec["n_tools_exposed"] == 27
        assert live == set(AL.LIVE_CATALOG), "the module's LIVE_CATALOG must be the catalog that was recorded"

    def test_every_live_tool_is_classified_so_a_new_one_is_visible_not_merely_refused(self):
        r = AL.reconcile()
        assert r["unclassified_live_tools"] == [] and r["fully_classified"] is True
        assert r["n_live_allowed"] == 9 and r["n_live_denied"] == 18

    def test_nothing_is_allowed_that_the_server_does_not_expose(self):
        assert AL.reconcile()["allowed_not_in_live_catalog"] == []

    def test_the_watchlist_denials_are_documentation_only_and_say_so(self):
        r = AL.reconcile()
        assert r["no_watchlist_tool_is_live"] is True
        assert set(r["denied_not_in_live_catalog"]) == set(AL.DOCUMENTED_NOT_LIVE)
        assert r["documented_not_live_are_all_denied"] is True, "absent today is not a reason to stop denying"

    def test_the_server_exposes_no_order_execution_or_position_tool_at_all(self):
        assert AL.reconcile()["no_order_or_execution_tool_is_live"] is True


class TestBothSpellingsResolveToOneReviewedIdentity:
    @pytest.mark.parametrize("tool", AL.ALLOWED_TOOLS)
    def test_each_allowed_tool_is_permitted_bare_and_live(self, tool):
        AL.permit(tool)
        AL.permit(AL.live_name(tool))                     # the regression: these all used to raise
        assert AL.canonical(AL.live_name(tool)) == tool

    @pytest.mark.parametrize("tool", [t for t in AL.LIVE_CATALOG if t not in AL.ALLOWED_TOOLS])
    def test_each_denied_live_tool_is_refused_in_both_spellings(self, tool):
        for spelling in (tool, AL.live_name(tool)):
            with pytest.raises(AL.ToolNotAllowed):
                AL.permit(spelling)

    def test_canonicalization_is_idempotent(self):
        for t in AL.LIVE_CATALOG:
            assert AL.canonical(AL.canonical(AL.live_name(t))) == t


class TestTheMarkerBeltSurvivesTheLiveSpelling:
    def test_stop_alerts_no_longer_slips_the_belt(self):
        """The hole this closed: `stop_alerts` matches the marker `stop_`, but `mcp-tv-stop-alerts` has no
        underscore, so the raw-string match returned None and only default-deny stood between it and the wire."""
        assert AL.check_marker("mcp__mcp-tradingview__mcp-tv-stop-alerts") == "stop_"

    @pytest.mark.parametrize("name", ["mcp__mcp-tradingview__mcp-tv-create-alert",
                                      "mcp__mcp-tradingview__mcp-tv-update-alert",
                                      "mcp__mcp-tradingview__mcp-tv-delete-alert",
                                      "mcp__mcp-tradingview__mcp-tv-restart-alerts",
                                      "mcp__mcp-tradingview__mcp-tv-stop-alerts",
                                      "mcp-tv-place-order", "mcp-tv-add-to-watchlist", "MCP-TV-CREATE-ALERT"])
    def test_mutating_and_outbound_names_are_marked_in_any_spelling(self, name):
        assert AL.check_marker(name) is not None
        with pytest.raises(AL.ToolNotAllowed):
            AL.permit(name)

    def test_an_allowed_tool_is_clean_in_the_spelling_the_transport_uses(self):
        AL.assert_allowlist_is_sound()
        for t in AL.ALLOWED_TOOLS:
            assert AL.check_marker(AL.live_name(t)) is None


class TestDefaultDenyStillGoverns:
    def test_a_tool_nobody_has_reviewed_is_refused(self):
        with pytest.raises(AL.ToolNotAllowed, match="TOOL_NOT_ON_ALLOWLIST"):
            AL.permit("mcp__mcp-tradingview__mcp-tv-get-something-invented-tomorrow")

    def test_another_servers_tool_is_refused_before_anything_else_is_considered(self):
        """This allowlist reviews ONE server. It does not get to vouch for Robinhood's."""
        with pytest.raises(AL.ToolNotAllowed, match="TOOL_FOREIGN_SERVER"):
            AL.permit("mcp__robinhood-trading__place_equity_order")
        with pytest.raises(AL.ToolNotAllowed, match="TOOL_FOREIGN_SERVER"):
            AL.permit("mcp__robinhood-trading__get_equity_quotes")   # read-only there is still not ours

    @pytest.mark.parametrize("bad", ["", "   ", None, 17, b"get_ohlcv"])
    def test_a_name_that_is_not_a_name_is_refused(self, bad):
        with pytest.raises(AL.ToolNotAllowed):
            AL.permit(bad)


class TestOneToolOneIdentityInTheRecord:
    def test_a_live_spelled_context_tool_keeps_external_context_authority(self):
        """Before canonicalization reached the normalizer, a live-spelled news call was stamped
        OBSERVATION_ONLY -- the same headline carrying MORE authority merely because of how it was addressed."""
        for spelling in ("get_news", AL.live_name("get_news")):
            o = N.observation(tool=spelling, args={}, payload={"x": 1}, request_start=1.0, response_receipt=2.0)
            assert o["tool"] == "get_news"
            assert o["authority"] == N.AUTHORITY_CONTEXT and o["calibrated"] is False

    def test_the_record_keeps_the_wire_spelling_for_provenance(self):
        o = N.observation(tool=AL.live_name("get_ohlcv"), args={}, payload={}, request_start=1.0, response_receipt=2.0)
        assert o["tool"] == "get_ohlcv"
        assert o["tool_as_called"] == "mcp__mcp-tradingview__mcp-tv-get-ohlcv"
        assert o["tool_live_name"] == "mcp__mcp-tradingview__mcp-tv-get-ohlcv"

    def test_completed_bars_accepts_either_spelling_and_still_refuses_a_non_bars_observation(self):
        o = N.normalize_bars({"bars": []}, symbol="AMEX:SPY", interval="1D", request_start=1.0, response_receipt=2.0)
        assert N.completed_bars(o) == []
        with pytest.raises(N.NormalizationRefused, match="NOT_A_BARS_OBSERVATION"):
            N.completed_bars(N.observation(tool=AL.live_name("get_news"), args={}, payload={},
                                           request_start=1.0, response_receipt=2.0))


@pytest.fixture(scope="module")
def smoke():
    return json.loads(SMOKE.read_text())


class TestTheLiveSmokeEvidence:
    """Assertions about the RECORDED live run. If the evidence file is edited to say something friendlier than
    what happened, these fail."""

    def test_nine_real_calls_inside_the_ten_call_bound(self, smoke):
        assert smoke["n_calls"] == 9
        assert smoke["report"]["budget"]["used"] == 9 <= smoke["report"]["budget"]["max_calls"] == 10

    def test_every_call_succeeded_and_every_call_was_on_the_allowlist(self, smoke):
        assert {r["state"] for r in smoke["results"]} == {"OK"}
        for r in smoke["results"]:
            AL.permit(r["tool"])
            assert r["tool_canonical"] in AL.ALLOWED_TOOLS

    def test_availability_is_receipt_and_history_is_never_claimed(self, smoke):
        for r in smoke["results"]:
            o = r["observation"]
            assert o["historical_availability"] == "NOT_ESTABLISHED"
            assert o["availability_basis"] == "RESPONSE_RECEIPT_ON_THIS_CONNECTION"
            assert o["known_from_epoch"] == o["response_receipt_epoch"] >= o["request_start_epoch"]

    def test_nothing_live_came_back_calibrated_or_authorized(self, smoke):
        for r in smoke["results"]:
            assert r["observation"]["calibrated"] is False
            assert r["observation"]["authority"] in (N.AUTHORITY_CONTEXT, N.AUTHORITY_OBSERVATION)

    def test_the_three_context_tools_are_context_only_on_live_data(self, smoke):
        ctx = {r["tool_canonical"] for r in smoke["results"]
               if r["observation"]["authority"] == N.AUTHORITY_CONTEXT}
        assert ctx == {"get_technicals_rating", "get_news", "get_news_story"}

    def test_the_server_stated_a_delay_and_the_record_carries_it_rather_than_UNKNOWN(self, smoke):
        """The live bars response says 'delayed 15+ minutes'. That is a VERIFIED delay, not an unknown one."""
        bars = [r for r in smoke["results"] if r["tool_canonical"] == "get_ohlcv"][0]
        assert bars["observation"]["entitlement"] == "DELAYED_VERIFIED"
        assert bars["observation"]["delay_status"] == "DELAYED_VERIFIED"

    def test_live_bars_were_normalized_through_the_bar_contract(self, smoke):
        bars = [r for r in smoke["results"] if r["tool_canonical"] == "get_ohlcv"][0]["observation"]
        assert bars["n_complete"] == 5 and bars["n_refused"] == 0
        closes = [b["close"] for b in bars["bars_complete"]]
        assert closes == [770.19, 765.96, 762.4, 757.83, 764.29]
        for b in bars["bars_complete"]:
            assert b["window_closed"] is True and b["unknown_fields"] == []
            assert b["close_epoch"] <= bars["response_receipt_epoch"], "no bar may close after the response arrived"

    def test_an_empty_result_is_a_successful_observation_not_a_provider_error(self, smoke):
        """The economic calendar legitimately returned no high-importance US events. Empty is data."""
        econ = [r for r in smoke["results"] if r["tool_canonical"] == "get_economic_calendar"][0]
        assert econ["state"] == "OK" and econ["observation"]["quality"] == "VALID"
