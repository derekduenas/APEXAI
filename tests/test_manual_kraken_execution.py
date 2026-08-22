"""MANUAL KRAKEN EXECUTION -- off-market commissioning (§16 of the
operator directive). Synthetic COMMISSIONING_TEST scenarios only: no
real orders, no Kraken credentials, no live execution."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from apex.execution_manual.kraken_manual import (  # noqa: E402
    ManualExecutionDesk, ManualExecutionRefused,
    in_scheduled_maintenance)

# a quiet Tuesday, far from the Friday 17-19 CT maintenance window
T0 = pd.Timestamp("2026-08-25 14:00:00", tz="UTC")


class Clock:
    def __init__(self, t=T0):
        self.t = t

    def __call__(self):
        return self.t

    def tick(self, seconds):
        self.t = self.t + pd.Timedelta(seconds=seconds)


def _trade(**over):
    base = {"contract": "BTC Perpetual (PBTCUC) -- Kraken Pro Perps",
            "action": "SHORT", "order_type": "LIMIT",
            "entry": 79125.0, "max_acceptable_entry": 79020.0,
            "contracts": 4, "btc_exposure": "0.04 BTC",
            "usd_notional": 3165.0, "account_risk_usd": 90.0,
            "account_risk_pct": 0.9, "invalidation": 79690.0,
            "stop": 79650.0, "target": "scale 1/2 at +2R, trail rest",
            "expected_hold": "20-90 min",
            "thesis": "leveraged-long pressure + OI expansion + book "
                      "deterioration",
            "why_now": "COMMISSIONING_TEST synthetic scenario",
            "primary_failure_condition": "short squeeze through 79690",
            "time_valid_s": 90,
            "decision_reference_price": 79140.0}
    base.update(over)
    return base


def _desk(tmp_path, clock=None):
    return ManualExecutionDesk(tmp_path / "manual.jsonl",
                               now_fn=clock or Clock())


# ------------------------------------------------ operator gate

def test_status_ladder(tmp_path):
    d = _desk(tmp_path)
    assert d.status() == "NOT_CONFIGURED"
    d.record_attestation(account_verified=True,
                         us_futures_unlocked=False,
                         btc_perp_visible=True, account_funded=True,
                         contract_understood="PBTCUC 0.01 BTC cash",
                         operator_statement="test")
    assert d.status() == "ACCOUNT_UNLOCK_REQUIRED"
    d.record_attestation(account_verified=True,
                         us_futures_unlocked=True,
                         btc_perp_visible=True, account_funded=True,
                         contract_understood="PBTCUC 0.01 BTC cash",
                         operator_statement="test")
    assert d.status() == "READY_MANUAL"
    d.set_paused(True)
    assert d.status() == "OPERATOR_PAUSED"


def test_maintenance_window_math():
    fri = pd.Timestamp("2026-08-28 17:30",
                       tz="America/Chicago").tz_convert("UTC")
    assert in_scheduled_maintenance(fri)
    assert not in_scheduled_maintenance(fri + pd.Timedelta(hours=2))
    assert not in_scheduled_maintenance(T0)


def test_maintenance_blocks_new_cards(tmp_path):
    fri = pd.Timestamp("2026-08-28 17:30",
                       tz="America/Chicago").tz_convert("UTC")
    d = _desk(tmp_path, Clock(fri))
    with pytest.raises(ManualExecutionRefused, match="SCHEDULED"):
        d.seal_card(_trade(), commissioning_test=True,
                    authority_level="OBSERVE")


# ------------------------------------------------ card sealing laws

def test_long_and_short_market_and_limit_cards_render(tmp_path):
    d = _desk(tmp_path)
    for action, otype in (("LONG", "MARKET"), ("SHORT", "LIMIT")):
        c = d.seal_card(_trade(action=action, order_type=otype,
                               max_acceptable_entry=79300.0
                               if action == "LONG" else 79020.0),
                        commissioning_test=True,
                        authority_level="OBSERVE")
        txt = d.render_card(c["trade_id"])
        assert f"ACTION: {action}" in txt
        assert f"ORDER: {otype}" in txt
        assert "TEST CARD -- NOT ELIGIBLE FOR EXECUTION" in txt
        assert "INVALIDATION:" in txt and "STOP:" in txt
        assert "ACCOUNT RISK: $90.0 (0.9%)" in txt


def test_emergency_law_refuses_card_without_stop(tmp_path):
    d = _desk(tmp_path)
    with pytest.raises(ManualExecutionRefused, match="emergency-risk"):
        d.seal_card(_trade(stop=None), commissioning_test=True,
                    authority_level="OBSERVE")
    with pytest.raises(ManualExecutionRefused):
        d.seal_card(_trade(invalidation=""), commissioning_test=True,
                    authority_level="OBSERVE")


def test_observe_authority_refuses_live_cards(tmp_path):
    d = _desk(tmp_path)
    with pytest.raises(ManualExecutionRefused, match="OBSERVE"):
        d.seal_card(_trade(), commissioning_test=False,
                    authority_level="OBSERVE")


# ------------------------------------------------ fill + latency

def test_confirmation_path_and_latency_capture(tmp_path):
    clock = Clock()
    d = _desk(tmp_path, clock)
    c = d.seal_card(_trade(), commissioning_test=True,
                    authority_level="OBSERVE")
    tid = c["trade_id"]
    clock.tick(2)
    d.mark_presented(tid)
    clock.tick(8)
    d.mark_operator_ack(tid)
    clock.tick(15)
    d.mark_submitted(tid, price_when_submitted=79122.0)
    clock.tick(3)
    fill = d.confirm_fill(tid, actual_entry=79118.0, contracts=4)
    assert fill["outcome"] == "FILLED_AS_REQUESTED"
    assert fill["execution_deviation_flag"] is False
    assert fill["slippage_from_decision"] == round(79118.0 - 79140.0, 6)
    lat = fill["latency"]
    assert lat["decision_to_operator_ms"] == 2000.0
    assert lat["operator_reaction_ms"] == 23000.0
    assert lat["order_to_fill_ms"] == 3000.0
    assert lat["total_execution_latency_ms"] == 28000.0


def test_no_filled_state_without_confirmation(tmp_path):
    d = _desk(tmp_path)
    c = d.seal_card(_trade(), commissioning_test=True,
                    authority_level="OBSERVE")
    assert d.cards[c["trade_id"]]["state"] == "AWAITING_OPERATOR_FILL"
    with pytest.raises(ManualExecutionRefused):
        d.position(c["trade_id"])       # no position without a fill


def test_partial_fill_and_execution_deviation(tmp_path):
    d = _desk(tmp_path)
    c1 = d.seal_card(_trade(), commissioning_test=True,
                     authority_level="OBSERVE")
    f1 = d.confirm_fill(c1["trade_id"], actual_entry=79118.0,
                        contracts=2)
    assert f1["outcome"] == "PARTIALLY_FILLED"
    # SHORT entered BELOW max acceptable = deviation
    c2 = d.seal_card(_trade(), commissioning_test=True,
                     authority_level="OBSERVE")
    f2 = d.confirm_fill(c2["trade_id"], actual_entry=78990.0,
                        contracts=4)
    assert f2["outcome"] == "FILLED_WITH_DEVIATION"
    assert f2["execution_deviation_flag"] is True
    assert f2["actual_entry"] == 78990.0    # never the intended price


def test_duplicate_confirmation_rejected(tmp_path):
    d = _desk(tmp_path)
    c = d.seal_card(_trade(), commissioning_test=True,
                    authority_level="OBSERVE")
    d.confirm_fill(c["trade_id"], actual_entry=79118.0, contracts=4)
    with pytest.raises(ManualExecutionRefused, match="DUPLICATE"):
        d.confirm_fill(c["trade_id"], actual_entry=79118.0,
                       contracts=4)


def test_expiration_sweep(tmp_path):
    clock = Clock()
    d = _desk(tmp_path, clock)
    c = d.seal_card(_trade(time_valid_s=90), commissioning_test=True,
                    authority_level="OBSERVE")
    assert d.sweep_expired() == []
    clock.tick(120)
    swept = d.sweep_expired()
    assert len(swept) == 1
    assert swept[0]["outcome"] == "EXPIRED_BEFORE_EXECUTION"
    assert swept[0]["hypothetical_tracking"] is True
    with pytest.raises(ManualExecutionRefused):
        d.confirm_fill(c["trade_id"], actual_entry=1.0, contracts=4)


def test_not_executed_is_legitimate_and_tracked(tmp_path):
    d = _desk(tmp_path)
    c = d.seal_card(_trade(), commissioning_test=True,
                    authority_level="OBSERVE")
    r = d.record_not_executed(c["trade_id"],
                              "NOT_EXECUTED_PRICE_MOVED")
    assert r["hypothetical_tracking"] is True
    assert d.cards[c["trade_id"]]["state"] == "NOT_EXECUTED"


# ------------------------------------------------ position + exit

def test_position_tracking_mfe_mae_and_exit_flow(tmp_path):
    clock = Clock()
    d = _desk(tmp_path, clock)
    c = d.seal_card(_trade(), commissioning_test=True,
                    authority_level="OBSERVE")
    tid = c["trade_id"]
    d.confirm_fill(tid, actual_entry=79118.0, contracts=4)
    for mark in (79050.0, 78800.0, 79200.0):   # short: down = profit
        d.record_mark(tid, mark)
    pos = d.position(tid)
    assert pos["mfe_per_unit"] == 79118.0 - 78800.0
    assert pos["mae_per_unit"] == 79118.0 - 79200.0
    risk = abs(79118.0 - 79650.0)
    assert abs(pos["mfe_r"] - (318.0 / risk)) < 1e-9
    ex = d.issue_exit_card(tid, reason="THESIS_INVALIDATED",
                           order_type="MARKET",
                           execute_by=str(clock() +
                                          pd.Timedelta(seconds=60)))
    assert ex["action"] == "CLOSE SHORT"
    assert "EXIT_REQUESTED != EXITED" in ex["law"]
    done = d.confirm_exit(tid, actual_exit=79180.0, contracts=4)
    assert done["realized_per_unit"] == round(79118.0 - 79180.0, 6)
    with pytest.raises(ManualExecutionRefused, match="DUPLICATE"):
        d.confirm_exit(tid, actual_exit=79180.0, contracts=4)


def test_exit_confirmation_requires_exit_card(tmp_path):
    d = _desk(tmp_path)
    c = d.seal_card(_trade(), commissioning_test=True,
                    authority_level="OBSERVE")
    d.confirm_fill(c["trade_id"], actual_entry=79118.0, contracts=4)
    with pytest.raises(ManualExecutionRefused, match="no exit card"):
        d.confirm_exit(c["trade_id"], actual_exit=79000.0, contracts=4)


def test_maintenance_exposure_surfaced_never_prescribed(tmp_path):
    thu = pd.Timestamp("2026-08-27 20:00",
                       tz="America/Chicago").tz_convert("UTC")
    d = _desk(tmp_path, Clock(thu))
    c = d.seal_card(_trade(), commissioning_test=True,
                    authority_level="OBSERVE")
    d.confirm_fill(c["trade_id"], actual_entry=79118.0, contracts=4)
    near = ManualExecutionDesk(d.ledger, now_fn=Clock(
        pd.Timestamp("2026-08-28 10:00",
                     tz="America/Chicago").tz_convert("UTC")))
    exp = near.maintenance_exposure_check(c["trade_id"])
    assert exp["exposure"].startswith("OPEN_POSITION_APPROACHES")
    assert exp["prescription"] == "NONE -- operator decides"


# ------------------------------------------------ restart recovery

def test_restart_recovery_full_replay(tmp_path):
    clock = Clock()
    d = _desk(tmp_path, clock)
    c = d.seal_card(_trade(), commissioning_test=True,
                    authority_level="OBSERVE")
    tid = c["trade_id"]
    d.mark_presented(tid)
    d.confirm_fill(tid, actual_entry=79118.0, contracts=4)
    d.record_mark(tid, 78900.0)
    # process death -> fresh desk from the same ledger
    d2 = ManualExecutionDesk(d.ledger, now_fn=clock)
    assert d2.cards[tid]["state"] == "FILLED"
    assert d2.cards[tid]["outcome"] == "FILLED_AS_REQUESTED"
    pos = d2.position(tid)
    assert pos["entry"] == 79118.0 and pos["marks"] == 1
    with pytest.raises(ManualExecutionRefused, match="DUPLICATE"):
        d2.confirm_fill(tid, actual_entry=79118.0, contracts=4)


def test_ledger_is_hash_chained(tmp_path):
    import json
    d = _desk(tmp_path)
    d.seal_card(_trade(), commissioning_test=True,
                authority_level="OBSERVE")
    rows = [json.loads(x) for x in
            d.ledger.read_text().splitlines()]
    for i in range(1, len(rows)):
        assert rows[i]["prev_hash"] == rows[i - 1]["entry_hash"]
