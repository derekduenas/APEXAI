"""Defect Repair and First Seal Block (2026-09-11): PILOT_RULE_V2, the registry-driven adverse block, the commissioned
live chain/quote wiring (read-only; fee default authorized 2026-09-12), and the calendar-canonical clock."""
from __future__ import annotations

import json
import subprocess
import sys

import pytest

from apex.joint_wb import engine as ENG
from apex.options_pilot import expression_rule as ER
from apex.options_pilot.fees import UNVERIFIED_FEES
from apex.options_pilot.risk_authority import entry_cap_price
from apex.pulse_options import sources as SRC
from apex.pulse_options.providers import LiveGate, ProviderUnavailable

AS_OF = "2026-09-11T14:53:23Z"
SPOT = 763.94


def _chain(exp="2026-10-02"):
    rows = []
    for k in range(740, 790):
        c_ask = max(0.05, round(SPOT - k + 9.2, 2)) if k <= SPOT else round(max(0.05, 9.2 - 0.55 * (k - SPOT)), 2)
        p_ask = round(max(0.05, 9.26 - 0.55 * (SPOT - k)), 2) if k <= SPOT else max(0.05, round(k - SPOT + 9.26, 2))
        rows.append({"expiration": exp, "strike": float(k), "right": "CALL", "ask": c_ask})
        rows.append({"expiration": exp, "strike": float(k), "right": "PUT", "ask": p_ask})
    return rows


# ------------------------------------------------------------------ item 1: the strike rule
class TestPilotRuleV2:
    def test_v1_is_refused_by_the_cap_by_construction_and_carries_the_defect_marker(self):
        v1 = ER.choose(symbol="SPY", direction_signal="LONG", spot=SPOT, as_of=AS_OF, available=_chain(), rule="PILOT_RULE_V1")
        assert v1["contract"]["strike"] == 764.0 and v1["reference_ask"] > entry_cap_price()
        assert v1["strike_selection"]["cap_consulted"] is False and "DEFECT_PTD_HARD_LAW_ONE" in v1["strike_selection"]["defect"]

    def test_v2_picks_the_nearest_feasible_strike_on_the_signal_side_and_states_what_v1_could_not(self):
        v2 = ER.choose(symbol="SPY", direction_signal="LONG", spot=SPOT, as_of=AS_OF, available=_chain(), max_entry_price=entry_cap_price())
        k = v2["contract"]["strike"]
        assert k >= SPOT and v2["reference_ask"] <= entry_cap_price() and v2["expression"] == "LONG_CALL"
        assert v2["expression_rule"] == ER.RULE_ID_V2
        sel = v2["strike_selection"]
        assert sel["rule"] == "PILOT_RULE_V2" and sel["cap_consulted"] is True and sel["strikes_from_atm"] >= 1
        assert sel["distance"] == pytest.approx(k - SPOT, abs=1e-3) and "what_v1_could_not_express" in sel
        # nothing cheaper-but-farther is preferred: every feasible strike nearer to spot would have been chosen first
        nearer = [c for c in _chain() if c["right"] == "CALL" and SPOT <= c["strike"] < k]
        assert all(c["ask"] > entry_cap_price() for c in nearer)

    def test_v2_put_side_is_at_or_below_spot(self):
        v2 = ER.choose(symbol="SPY", direction_signal="SHORT", spot=SPOT, as_of=AS_OF, available=_chain(), max_entry_price=entry_cap_price())
        assert v2["contract"]["right"] == "PUT" and v2["contract"]["strike"] <= SPOT and v2["reference_ask"] <= entry_cap_price()

    def test_v2_refuses_with_a_census_when_nothing_fits_and_when_asks_are_absent(self):
        with pytest.raises(ER.RuleRefused, match="NO_FEASIBLE_STRIKE"):
            ER.choose(symbol="SPY", direction_signal="LONG", spot=SPOT, as_of=AS_OF, available=_chain(), max_entry_price=0.01)
        bare = [{k: v for k, v in c.items() if k != "ask"} for c in _chain()]
        with pytest.raises(ER.RuleRefused, match="NO_INDICATIVE_ASKS"):
            ER.choose(symbol="SPY", direction_signal="LONG", spot=SPOT, as_of=AS_OF, available=bare, max_entry_price=5.0)
        with pytest.raises(ER.RuleRefused, match="NO_MAX_ENTRY_PRICE"):
            ER.choose(symbol="SPY", direction_signal="LONG", spot=SPOT, as_of=AS_OF, available=_chain())

    def test_the_cap_is_the_only_capital_fact_and_it_enters_in_expression_not_in_the_funnel(self):
        from apex.decision_wb import engine as FE
        import inspect
        assert entry_cap_price() == 5.0
        src = inspect.getsource(FE)
        assert "MAX_RISK_PER_TRADE" not in src and "entry_cap_price" not in src, "candidate generation must stay blind to capital"


# ------------------------------------------------------------------ item 2: the engine reads the registry
class TestAdverseRegistry:
    def test_engine_source_iterates_the_registry_and_has_no_second_list(self):
        import inspect
        src = inspect.getsource(ENG.JointEngine._adverse)
        assert "for name in ADVERSE_SCENARIOS" in src and "ADVERSE_REGISTRY_INTEGRITY" in src

    def test_a_registered_name_without_a_builder_fails_loudly(self, monkeypatch):
        import tests.test_joint_wb as T
        monkeypatch.setattr(ENG, "ADVERSE_SCENARIOS", ENG.ADVERSE_SCENARIOS + ("not_a_real_scenario",))
        e = T._engine(n_paths=100, seed=11)
        with pytest.raises(RuntimeError, match="ADVERSE_REGISTRY_INTEGRITY"):
            T._decide(e, ms=T._state(), drift=0.0005)

    def test_removing_a_name_from_the_registry_removes_it_from_the_evaluation(self, monkeypatch):
        import tests.test_joint_wb as T
        monkeypatch.setattr(ENG, "ADVERSE_SCENARIOS", tuple(n for n in ENG.ADVERSE_SCENARIOS if n != "size_floor_removed"))
        e = T._engine(n_paths=100, seed=11)
        r = T._decide(e, ms=T._state(), drift=0.0005)
        adv = r["trace"]["decision_rule"]["rules"]["3"]
        assert "size_floor_removed" not in adv["scenarios"] and set(adv["registered"]) == set(adv["scenarios"]) - {"BASE"}


# ------------------------------------------------------------------ item 4: commissioned live chain/quote (read-only)
from apex.pulse_options.providers import ThetaChainAdapter
from apex.options_pilot.clock import Clock
SNAP_EPOCH = ThetaChainAdapter.et_naive_to_epoch("2026-09-11 10:53:23")
RECEIPT = SNAP_EPOCH + 5.0                                       # the snapshot is 5 s old at receipt


def _clock():
    return Clock(lambda: RECEIPT)


def _snapshot_rows(symbol, expiration):
    assert symbol == "SPY" and expiration == "2026-10-02"
    return [{"symbol": "SPY", "expiration": "2026-10-02", "strike": "773.000", "right": "C", "timestamp": "2026-09-11 10:53:23",
             "bid": "4.59", "ask": "4.63", "bid_size": "58", "ask_size": "139"},
            {"symbol": "SPY", "expiration": "2026-10-02", "strike": "764.000", "right": "CALL", "timestamp": "2026-09-11 10:53:23",
             "bid": "9.11", "ask": "9.20", "bid_size": "12", "ask_size": "9"},
            {"symbol": "SPY", "expiration": "2026-10-02", "strike": "bad", "right": "P", "timestamp": "x", "bid": "1", "ask": "2"}]


class TestLiveWiring:
    def _gate(self):
        return LiveGate(env={"APEX_PILOT_LIVE_DATA": "ENABLED"}, secret_fn=lambda name: "present")

    def test_default_gate_refuses_before_any_adapter_is_called(self):
        called = []
        src = SRC.live_twin_sources(expirations_fn=lambda s: called.append(s) or ["20261002"], chain_snapshot_fn=lambda s, e: called.append(e) or [])
        with pytest.raises(ProviderUnavailable):
            src.chain_fn("SPY", 1_789_000_000.0)
        with pytest.raises(ProviderUnavailable):
            src._quote_fn({"symbol": "SPY", "expiration": "2026-10-02", "strike": 773.0, "right": "CALL"})
        assert called == []

    def test_chain_fn_returns_validator_shaped_rows_from_the_first_eligible_expiry(self):
        src = SRC.live_twin_sources(gate=self._gate(), expirations_fn=lambda s: ["20260918", "20261002", "20261016"],
                                    chain_snapshot_fn=_snapshot_rows, clock=_clock())
        rows = src.chain_fn("SPY", RECEIPT)                              # 2026-09-11
        assert [r["strike"] for r in rows] == [773.0, 764.0]             # the malformed row is dropped, nothing invented
        assert len(rows.exclusions) == 1 and rows.exclusions[0]["why"].startswith("STRIKE_INVALID")
        r = rows[0]
        assert r["expiration"] == "2026-10-02" and r["right"] == "CALL" and r["ask"] == 4.63 and r["bid_size"] == 58
        assert isinstance(r["timestamp_epoch"], float) and r["indicative"] is True and r["provider"] == "THETADATA_V3"

    def test_quote_fn_returns_the_exact_contract_or_refuses(self):
        src = SRC.live_twin_sources(gate=self._gate(), expirations_fn=lambda s: ["20261002"], chain_snapshot_fn=_snapshot_rows, clock=_clock())
        q = src._quote_fn({"symbol": "SPY", "expiration": "2026-10-02", "strike": 773.0, "right": "CALL"})
        from apex.options_pilot.records import validate_quote
        v = validate_quote(q, contract={"symbol": "SPY", "expiration": "2026-10-02", "strike": 773.0, "right": "CALL"})
        assert v["ask"] == 4.63 and v["bid"] == 4.59 and v["ask_size"] == 139
        with pytest.raises(ProviderUnavailable, match="QUOTE_NOT_IN_SNAPSHOT"):
            src._quote_fn({"symbol": "SPY", "expiration": "2026-10-02", "strike": 780.0, "right": "CALL"})

    def test_live_default_reverted_to_unverified_when_the_fee_computation_changed(self):
        """2026-09-12 morning: the operator authorized ROBINHOOD_RHF_2026 (broker PDF sha 7f9c86bf) and it became the live
        default. 2026-09-12 afternoon: the Part 1 repair brick changed its SEC component to the exact sale-principal
        computation, so the schedule returned to CANDIDATE (v2026-09-12b) and the live default REVERTED to UNVERIFIED
        pending review. A changed cost model is not an authorized one. There is still no order path."""
        from apex.options_pilot.fees import LIVE_DEFAULT_FEES, ROBINHOOD_RHF_2026, ROBINHOOD_RHF_2026_AUTHORIZATION
        src = SRC.live_twin_sources(gate=self._gate(), expirations_fn=lambda s: ["20261002"], chain_snapshot_fn=_snapshot_rows, clock=_clock())
        assert src.fee_schedule is LIVE_DEFAULT_FEES is UNVERIFIED_FEES and not src.fee_schedule.known
        va = ROBINHOOD_RHF_2026.verified_against
        assert va["document_sha256"].startswith("7f9c86bf") and va["authorization"]["authorized_by"] == "operator"
        assert "SUPERSEDED_BY_COMPUTATION_CHANGE" in ROBINHOOD_RHF_2026_AUTHORIZATION["status"] and ROBINHOOD_RHF_2026.version == "2026-09-12b"
        explicit = SRC.live_twin_sources(gate=self._gate(), expirations_fn=lambda s: ["20261002"], chain_snapshot_fn=_snapshot_rows, clock=_clock(), fee_schedule=ROBINHOOD_RHF_2026)
        assert explicit.fee_schedule is ROBINHOOD_RHF_2026
        import inspect
        text = inspect.getsource(SRC)
        for forbidden in ("place_order", "submit_order", "/orders", "order_id"):
            assert forbidden not in text


# ------------------------------------------------------------------ item 3: the clock rule is in the runner
def test_runner_scores_against_the_calendar_and_labels_the_lake_report_diagnostic():
    src = open("scripts/reality_run.py").read()
    assert "CALENDAR_CANONICAL" in src and "LAKE_DIAGNOSTIC" in src and "A-011" in src
    assert 'score_by_producer(LEDGER.predictions(), LEDGER.resolutions(), calendar_through)' in src
