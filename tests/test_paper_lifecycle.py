"""One complete paper lifecycle, accounted for -- and every way it must refuse instead.

WHERE THE PATH STOPPED BEFORE THIS. `capital.decide()` returns only WATCH or OBSERVE, so PAPER_ELIGIBLE is
unreachable by construction; `authorize_paper` was called from nothing but tests; and `apex/hunter/paper.py`
contained ZERO fee, P&L or ledger code -- `manage` tracked a qty FRACTION and an EXIT action with no exit price,
no share count and no cashflow. The components existed; the accounting did not.
"""
from __future__ import annotations

import os

import pandas as pd
import pytest

from apex.hunter import paper_lifecycle as L
from apex.hunter.paper import SyntheticTestAuthorization


class Cap:
    def __init__(self, state="PAPER_ELIGIBLE", weight=0.02):
        self.final_state, self.weight, self.decision_id = state, weight, "cap-1"


def candidate(did="d-1"):
    return {"decision_id": did, "symbol": "ABC", "direction": "LONG",
            "entry": 100.0, "stop": 98.0, "target": 106.0}


def bars(open_=99.5, high=101.0, low=99.0):
    return pd.DataFrame([{"open": open_, "high": high, "low": low, "close": 100.2,
                          "event_time_utc": pd.Timestamp("2026-09-14 14:00", tz="UTC")}])


@pytest.fixture()
def led(tmp_path):
    return tmp_path / "paper_lifecycle.jsonl"


# ======================================================= the complete sequence
class TestOneCompleteLifecycle:
    def test_candidate_to_reconciled_pnl(self, led):
        out = L.run_lifecycle(capital_decision=Cap(), candidate=candidate(), entry_bars=bars(),
                              ledger_path=led, exit_price=104.0, exit_reason="TARGET",
                              synthetic=SyntheticTestAuthorization())
        assert out["stage"] == "REALIZED", out
        r = out["realization"]
        # 2000 notional / 99.5 fill -> 20 shares; gross = (104 - 99.5) * 20
        assert out["sizing"]["shares"] == 20
        assert r["realized_gross"] == pytest.approx(90.0)
        assert r["realized_net"] == pytest.approx(90.0 - r["fees_total"])
        assert r["fees_total"] > 0, "a SELL owes SEC and TAF; zero fees would be a fabricated P&L"

    def test_every_stage_is_persisted_in_order(self, led):
        L.run_lifecycle(capital_decision=Cap(), candidate=candidate(), entry_bars=bars(),
                        ledger_path=led, exit_price=104.0, synthetic=SyntheticTestAuthorization())
        stages = [r["stage"] for r in L.read(led)]
        assert stages == ["AUTHORIZED", "FILL_ASSESSED", "POSITION_OPEN", "MANAGED", "REALIZED"], stages

    def test_independent_reconstruction_agrees(self, led):
        L.run_lifecycle(capital_decision=Cap(), candidate=candidate(), entry_bars=bars(),
                        ledger_path=led, exit_price=104.0, synthetic=SyntheticTestAuthorization())
        rec = L.reconstruct(led)
        assert rec["reconciles"], rec["disagreements"]
        d = rec["decisions"]["d-1"]
        assert d["shares"] == 20 and d["realized_gross"] == pytest.approx(90.0)
        assert rec["realized_net"] == pytest.approx(d["realized_net"])
        # cash: -20*99.5 (buy) + 20*104 (sell) - fees
        assert rec["cash"] == pytest.approx(90.0 - rec["fees_paid"])
        assert rec["open_exposure"] == []

    def test_the_reconstruction_catches_a_tampered_ledger(self, led):
        L.run_lifecycle(capital_decision=Cap(), candidate=candidate(), entry_bars=bars(),
                        ledger_path=led, exit_price=104.0, synthetic=SyntheticTestAuthorization())
        import json
        rows = L.read(led)
        for r in rows:
            if r["stage"] == "REALIZED":
                r["realization"]["realized_net"] = 9999.0
        led.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
        rec = L.reconstruct(led)
        assert not rec["reconciles"]
        assert any(d["field"] == "realized_net" for d in rec["disagreements"]), rec["disagreements"]


# ======================================================= refusals
class TestItRefusesRatherThanInvents:
    @pytest.mark.parametrize("state", ["WATCH", "OBSERVE", "NO_TRADE"])
    def test_a_non_eligible_capital_verdict_is_not_authorized(self, led, state):
        out = L.run_lifecycle(capital_decision=Cap(state), candidate=candidate(),
                              entry_bars=bars(), ledger_path=led, exit_price=104.0)
        assert out["stage"] == "NOT_AUTHORIZED"
        assert state in out["reason"]
        assert [r["stage"] for r in L.read(led)] == ["NOT_AUTHORIZED"], "nothing was filled or charged"

    def test_an_ambiguous_fill_produces_no_position_and_no_pnl(self, led):
        # touched the limit but never traded through it
        out = L.run_lifecycle(capital_decision=Cap(), candidate=candidate(),
                              entry_bars=bars(open_=100.5, high=101.0, low=100.0),
                              ledger_path=led, exit_price=104.0,
                              synthetic=SyntheticTestAuthorization())
        assert out["stage"] == "NO_FILL"
        assert not any(r["stage"] == "POSITION_OPEN" for r in L.read(led))

    def test_an_unavailable_exit_leaves_exposure_visible_not_flat(self, led):
        out = L.run_lifecycle(capital_decision=Cap(), candidate=candidate(), entry_bars=bars(),
                              ledger_path=led, exit_price=None, exit_reason="EXIT_DATA_UNAVAILABLE",
                              synthetic=SyntheticTestAuthorization())
        assert out["stage"] == "OPEN_UNRESOLVED"
        assert out["realization"]["realized_net"] == L.UNKNOWN
        assert out["realization"]["remaining_exposure"]["shares"] == 20
        rec = L.reconstruct(led)
        assert rec["open_exposure"] and rec["open_exposure"][0]["shares"] == 20
        assert rec["decisions"]["d-1"]["realized_net"] == L.UNKNOWN, "an unresolved exit is never 0.0"

    def test_an_unknown_fee_poisons_net_but_not_gross(self, led):
        sched = L.EquityFeeSchedule(taf_per_share=None)
        out = L.run_lifecycle(capital_decision=Cap(), candidate=candidate(), entry_bars=bars(),
                              ledger_path=led, exit_price=104.0, schedule=sched,
                              synthetic=SyntheticTestAuthorization())
        assert out["stage"] == "FEES_UNKNOWN"
        assert out["realization"]["realized_gross"] == pytest.approx(90.0)
        assert out["realization"]["realized_net"] == L.UNKNOWN
        assert "finra_taf" in out["realization"]["unknown_components"]

    def test_a_buy_owes_no_sec_fee_and_that_is_zero_not_unknown(self):
        f = L.compute_fees("BUY", 20, 100.0, L.EquityFeeSchedule())
        assert f["components"]["sec_fee"] == 0.0 and f["unknown_components"] == []
        assert "not applicable" in f["basis"]["sec_fee"]


# ======================================================= delivery and restart
class TestDeliveryAndRestart:
    def test_duplicate_delivery_neither_refills_nor_recharges(self, led):
        a = L.run_lifecycle(capital_decision=Cap(), candidate=candidate(), entry_bars=bars(),
                            ledger_path=led, exit_price=104.0, synthetic=SyntheticTestAuthorization())
        b = L.run_lifecycle(capital_decision=Cap(), candidate=candidate(), entry_bars=bars(),
                            ledger_path=led, exit_price=104.0, synthetic=SyntheticTestAuthorization())
        assert a["stage"] == "REALIZED" and b["stage"] == "RECONCILED_DUPLICATE"
        stages = [r["stage"] for r in L.read(led)]
        assert stages.count("POSITION_OPEN") == 1 and stages.count("REALIZED") == 1
        rec = L.reconstruct(led)
        assert rec["realized_net"] == pytest.approx(a["realization"]["realized_net"])

    def test_restart_reconstructs_the_same_book_from_the_ledger_alone(self, led):
        L.run_lifecycle(capital_decision=Cap(), candidate=candidate("d-1"), entry_bars=bars(),
                        ledger_path=led, exit_price=104.0, synthetic=SyntheticTestAuthorization())
        L.run_lifecycle(capital_decision=Cap(), candidate=candidate("d-2"), entry_bars=bars(),
                        ledger_path=led, exit_price=None, synthetic=SyntheticTestAuthorization())
        before = L.reconstruct(led)
        after = L.reconstruct(led)          # a restart reads the same persisted bytes
        assert before == after
        assert before["realized_net"] == pytest.approx(before["decisions"]["d-1"]["realized_net"])
        assert [e["decision_id"] for e in before["open_exposure"]] == ["d-2"], \
            "the unresolved one stays open; the realized one does not leak into it"


# ======================================================= the live route
class TestSyntheticAdmissionCannotReachProduction:
    def test_synthetic_authorization_refuses_outside_pytest(self, monkeypatch):
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        from apex.hunter.paper import PaperAuthorizationError
        with pytest.raises(PaperAuthorizationError):
            SyntheticTestAuthorization()

    def test_the_live_route_has_no_synthetic_argument(self):
        """Nothing in apex/ or scripts/ constructs a SyntheticTestAuthorization."""
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[1]
        for sub in ("apex", "scripts"):
            for f in (root / sub).rglob("*.py"):
                assert "SyntheticTestAuthorization()" not in f.read_text(), f

    def test_capital_still_cannot_reach_PAPER_ELIGIBLE(self):
        """This brick does NOT light the capital gate. SIMULATED_UNCALIBRATED stays refused."""
        import inspect

        from apex.hunter import capital
        src = inspect.getsource(capital.decide) if hasattr(capital, "decide") else \
            inspect.getsource(capital)
        assert "FinalState.PAPER_ELIGIBLE" not in src, \
            "no branch may return PAPER_ELIGIBLE until a commissioned forecast exists"
