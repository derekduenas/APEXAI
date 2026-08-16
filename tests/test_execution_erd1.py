"""ERD-1: the vault stays sealed, the kill chain bites, expressions stay
honest. Every test here is a barrier, not a feature demo."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from apex.execution import killswitch
from apex.execution.contracts import (BrokerCapabilities, OrderIntent,
                                      ReadinessState)
from apex.execution.expression_v2 import (EXPRESSIONS, OptionSnapshot,
                                          evaluate as expr_eval,
                                          payoff_grid)
from apex.execution.gateway import ExecutionGateway, intent_id_for
from apex.execution.robinhood import (ALLOWED_TOOLS, BrokerAuthRequired,
                                      RobinhoodAdapter)
from apex.execution.sealing import (LiveExecutionAuthorization,
                                    LiveExecutionSealed,
                                    assert_no_placement_surface,
                                    scan_package_for_placement)

READY_DECISION = {"decision_id": "d1", "t_utc": str(pd.Timestamp.now(tz="UTC")),
                  "symbol": "AAPL", "direction": "LONG",
                  "forward_eligibility": "FORWARD_ELIGIBLE",
                  "chart_state": {"data_quality": []}}
READY_CAPITAL = {"final_state": "PAPER_ELIGIBLE", "reason_codes": [],
                 "gates": {"risk": {"accepted": True},
                           "cost": {"relative_spread": 0.0004}}}


def _intent(**kw):
    base = dict(decision_id="d1", expression_id="e1", intent_version=1,
                symbol="AAPL", side="BUY", quantity=10,
                order_type="LIMIT", limit_price=200.0, stop_price=None,
                time_in_force="DAY", asset_class="EQUITY")
    base.update(kw)
    return OrderIntent(intent_id=intent_id_for(base["decision_id"],
                                               base["expression_id"],
                                               base["intent_version"]),
                       **base)


def _fake_mcp(**overrides):
    def call(tool, **kwargs):
        data = {
            "get_account_info": {"options_level": 3, "cash": 5000,
                                 "as_of": "2026-08-16T15:00:00Z"},
            "get_buying_power": {"buying_power": 5000},
            "get_positions": {"positions": []},
            "get_open_orders": {"orders": []},
            "get_stock_quote": {"bid": 199.98, "ask": 200.02,
                                "last": 200.0, "age_seconds": 1.0},
            "get_stock_info": {"tradable": True, "state": "active"},
            "review_equity_order": {"estimated_cost": 2000.0,
                                    "estimated_fees": 0.0},
            "review_option_order": {"estimated_cost": 250.0},
        }
        data.update(overrides)
        return data.get(tool, {})
    return call


# ============================ A4: THE SEAL (P0) ============================
def test_adapter_has_no_placement_method_at_all():
    a = RobinhoodAdapter(_fake_mcp())
    for name in ("place_equity_order", "place_option_order", "place_order",
                 "submit_order", "execute_order", "send_order"):
        assert not hasattr(a, name), f"{name} must not exist"
    assert_no_placement_surface(a, "robinhood adapter")   # tripwire clean


def test_adapter_refuses_any_tool_outside_read_review_allowlist():
    a = RobinhoodAdapter(_fake_mcp())
    for tool in ("place_equity_order", "place_option_order", "submit_order",
                 "cancel_all_orders"):
        with pytest.raises(PermissionError):
            a._call(tool)
    assert not any("place" in t for t in ALLOWED_TOOLS)


def test_live_authorization_cannot_be_constructed():
    with pytest.raises(LiveExecutionSealed):
        LiveExecutionAuthorization()
    with pytest.raises(LiveExecutionSealed):
        LiveExecutionAuthorization(token="please")


def test_tripwire_catches_a_smuggled_placement_surface():
    class Smuggler:
        def place_equity_order(self, *a, **k):            # noqa: D401
            return "boom"
    with pytest.raises(LiveExecutionSealed):
        assert_no_placement_surface(Smuggler(), "smuggler")
    with pytest.raises(LiveExecutionSealed):
        ExecutionGateway(Smuggler())      # gateway refuses at construction


def test_package_defines_no_placement_functions():
    scan = scan_package_for_placement("apex")
    assert scan["clean"], f"placement surface found: {scan['offenders']}"


def test_readiness_has_no_order_sent_state_and_seal_is_immutable():
    assert not any("SENT" in s.value for s in ReadinessState)
    from apex.execution.contracts import ExecutionReadinessResult
    with pytest.raises(ValueError):
        ExecutionReadinessResult(state="ORDER_READY", intent=None,
                                 reasons=(), kill_chain={},
                                 broker_review=None,
                                 live_placement="UNSEALED")


# ======================= A5: THE PRE-HANDOFF KILL CHAIN ====================
def test_full_chain_reaches_order_ready_only_when_everything_passes(tmp_path):
    g = ExecutionGateway(RobinhoodAdapter(_fake_mcp()),
                         ledger=tmp_path / "i.jsonl")
    r = g.evaluate(_intent(), READY_DECISION, READY_CAPITAL)
    assert r.state == ReadinessState.ORDER_READY.value, r.reasons
    assert r.live_placement == "SEALED"
    assert r.authorization_power == "NONE_ERD1"
    assert all(c["pass"] for c in r.kill_chain["checks"].values())


@pytest.mark.parametrize("mutate,expect_reason", [
    ({"forward_eligibility": "NOT_FORWARD_ELIGIBLE"}, "evidence_eligibility"),
    ({"chart_state": {"data_quality": ["STALE_BARS"]}}, "data_health"),
    ({"t_utc": "2020-01-01T00:00:00+00:00"}, "decision_freshness"),
])
def test_kill_chain_refuses_bad_decisions(tmp_path, mutate, expect_reason):
    g = ExecutionGateway(RobinhoodAdapter(_fake_mcp()),
                         ledger=tmp_path / "i.jsonl")
    r = g.evaluate(_intent(), {**READY_DECISION, **mutate}, READY_CAPITAL)
    assert r.state != ReadinessState.ORDER_READY.value
    assert any(expect_reason in x for x in r.reasons)


def test_capital_must_say_paper_eligible(tmp_path):
    g = ExecutionGateway(RobinhoodAdapter(_fake_mcp()),
                         ledger=tmp_path / "i.jsonl")
    for state in ("OBSERVE", "WATCH", "NO_TRADE", "REFUSED"):
        r = g.evaluate(_intent(), READY_DECISION,
                       {**READY_CAPITAL, "final_state": state})
        assert r.state != ReadinessState.ORDER_READY.value
        assert any("capital_state" in x for x in r.reasons)


def test_unauthenticated_broker_blocks_and_never_fabricates(tmp_path):
    a = RobinhoodAdapter(None)                 # registered, not authed
    assert a.authenticated is False
    assert a.connection_health()["status"] == "BLOCKED_BROKER_AUTH"
    assert a.account_state().status == "BLOCKED_AUTH"
    assert a.quote("AAPL").status == "UNAVAILABLE"
    assert a.review_order(_intent()).review == "BROKER_REVIEW_UNAVAILABLE"
    with pytest.raises(BrokerAuthRequired):
        a._call("get_account_info")
    g = ExecutionGateway(a, ledger=tmp_path / "i.jsonl")
    r = g.evaluate(_intent(), READY_DECISION, READY_CAPITAL)
    assert r.state == ReadinessState.BLOCKED_BROKER_AUTH.value


def test_missing_capability_is_named_never_emulated(tmp_path):
    caps = BrokerCapabilities(broker="x", source="PROBED")
    ok, why = caps.supports("equity_native_bracket")
    assert not ok and "BROKER_CAPABILITY_UNAVAILABLE" in why
    class NoOptions(RobinhoodAdapter):
        def capabilities(self):
            return BrokerCapabilities(broker="robinhood", source="PROBED",
                                      equity_limit=True,
                                      options_long_call=False)
    g = ExecutionGateway(NoOptions(_fake_mcp()), ledger=tmp_path / "i.jsonl")
    r = g.evaluate(_intent(asset_class="OPTION", symbol="AAPL240119C200"),
                   READY_DECISION, READY_CAPITAL)
    assert r.state == ReadinessState.CAPABILITY_UNAVAILABLE.value


# ============================ A6: IDEMPOTENCY =============================
def test_duplicate_intent_refused_across_a_restart(tmp_path):
    led = tmp_path / "i.jsonl"
    g1 = ExecutionGateway(RobinhoodAdapter(_fake_mcp()), ledger=led)
    import apex.execution.gateway as gw
    gw.INTENT_LEDGER = led                     # simulate process ledger
    r1 = g1.evaluate(_intent(), READY_DECISION, READY_CAPITAL)
    assert r1.state == ReadinessState.ORDER_READY.value
    g2 = ExecutionGateway(RobinhoodAdapter(_fake_mcp()), ledger=led)
    r2 = g2.evaluate(_intent(), READY_DECISION, READY_CAPITAL)
    assert r2.state == ReadinessState.DUPLICATE.value
    # a NEW intent version is a different intent and may proceed
    r3 = g2.evaluate(_intent(intent_version=2), READY_DECISION,
                     READY_CAPITAL)
    assert r3.state == ReadinessState.ORDER_READY.value
    gw.INTENT_LEDGER = Path("results/execution/order_intents.jsonl")


def test_intent_id_is_deterministic():
    assert intent_id_for("d", "e", 1) == intent_id_for("d", "e", 1)
    assert intent_id_for("d", "e", 1) != intent_id_for("d", "e", 2)


# ============================= A7: KILL SWITCH ============================
def test_kill_switch_halts_everything_and_is_file_backed(tmp_path,
                                                         monkeypatch):
    marker = tmp_path / "EXECUTION_KILLED"
    monkeypatch.setattr(killswitch, "KILL_MARKER", marker)
    monkeypatch.setattr(killswitch, "KILL_LEDGER", tmp_path / "k.jsonl")
    import apex.execution.gateway as gw
    monkeypatch.setattr(gw, "kill_engaged", killswitch.engaged)
    monkeypatch.setattr(gw, "kill_state", killswitch.state)
    assert killswitch.state()["kill_switch"] == "ARMED_NOT_ENGAGED"
    killswitch.engage("operator halt")
    assert killswitch.engaged() is True
    g = ExecutionGateway(RobinhoodAdapter(_fake_mcp()),
                         ledger=tmp_path / "i.jsonl")
    r = g.evaluate(_intent(), READY_DECISION, READY_CAPITAL)
    assert r.state == ReadinessState.KILLED.value
    assert r.kill_chain["kill_switch"]["engaged"] is True
    killswitch.release("test over")
    assert killswitch.engaged() is False


# ==================== C: OPTIONS EXPRESSION HONESTY =======================
def _chain(spot=200.0):
    out = []
    for k in (190, 195, 200, 205, 210):
        for cp in ("CALL", "PUT"):
            mid = max(0.5, abs(spot - k) * 0.5 + 3)
            out.append(OptionSnapshot(
                symbol=f"AAPL_{k}{cp[0]}", underlying="AAPL",
                expiration="2026-09-18", strike=float(k), call_put=cp,
                bid=round(mid - 0.05, 2), ask=round(mid + 0.05, 2),
                open_interest=5000, volume=800, quote_age_s=2.0,
                tradability="TRADABLE", greeks_status="UNKNOWN_NOT_SOURCED"))
    return out


CAPS_FULL = BrokerCapabilities(broker="robinhood", source="PROBED",
                               equity_limit=True, options_long_call=True,
                               options_long_put=True,
                               options_debit_spread=True,
                               options_multi_leg=True)


def test_expression_refuses_to_originate_a_thesis_from_a_chain():
    with pytest.raises(ValueError):
        expr_eval({}, 200.0, _chain(), CAPS_FULL, "REFUSED")


def test_uncalibrated_forecast_yields_diagnostic_only_never_fake_ev():
    d = expr_eval(READY_DECISION, 200.0, _chain(), CAPS_FULL,
                  forecast_status="REFUSED")
    assert d.mode == "EXPRESSION_DIAGNOSTIC_ONLY"
    assert d.authorization_power == "NONE"
    assert "NOT an expected value" in d.payoff_summary["note"]
    flat = str(d.as_record())
    assert "expected_value" not in flat and "expected_return" not in flat
    assert d.expression_type == "STOCK"        # honest default
    assert "UNCALIBRATED" in d.rationale.upper()


def test_missing_option_capability_appears_as_unavailable_candidate():
    caps = BrokerCapabilities(broker="robinhood", source="PROBED",
                              equity_limit=True, options_long_call=False,
                              options_debit_spread=False)
    d = expr_eval(READY_DECISION, 200.0, _chain(), caps, "REFUSED")
    kinds = {c["expression_type"]: c for c in d.candidates_considered}
    assert kinds["LONG_CALL"]["liquidity_status"] == "UNAVAILABLE"
    assert "BROKER_CAPABILITY_UNAVAILABLE" in \
        kinds["LONG_CALL"]["data_quality"]


def test_illiquid_chain_pushes_to_stock():
    wide = [OptionSnapshot(symbol="X", underlying="AAPL",
                           expiration="2026-09-18", strike=200.0,
                           call_put="CALL", bid=1.0, ask=9.0,
                           open_interest=5, quote_age_s=300.0,
                           tradability="TRADABLE")]
    d = expr_eval(READY_DECISION, 200.0, wide, CAPS_FULL, "REFUSED")
    assert d.expression_type == "STOCK"
    assert "impaired" in d.rationale.lower() or "uncalibrated" in \
        d.rationale.lower()


def test_payoff_grid_is_deterministic_and_bounded():
    legs = [{"action": "BUY", "call_put": "CALL", "strike": 200.0},
            {"action": "SELL", "call_put": "CALL", "strike": 205.0}]
    g1 = payoff_grid("CALL_DEBIT_SPREAD", legs, 200.0, 200.0)
    g2 = payoff_grid("CALL_DEBIT_SPREAD", legs, 200.0, 200.0)
    assert g1 == g2
    worst = min(r.net_payoff_usd for r in g1)
    best = max(r.net_payoff_usd for r in g1)
    assert worst == -200.0                      # max loss = debit paid
    assert best <= 5 * 100 - 200.0 + 1e-9       # capped by width - debit
    assert all(isinstance(r.underlying_return, float) for r in g1)


def test_greeks_are_never_invented():
    s = OptionSnapshot(symbol="X", underlying="A", expiration="e",
                       strike=1.0, call_put="CALL")
    assert s.delta is None and s.iv is None
    assert s.greeks_status == "UNKNOWN_NOT_SOURCED"
    assert set(EXPRESSIONS) >= {"NO_TRADE", "STOCK", "LONG_CALL",
                                "CALL_DEBIT_SPREAD"}
