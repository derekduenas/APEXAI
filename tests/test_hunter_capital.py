"""Phase 4 integration proofs — the operator's ten, plus the end-to-end
spine. One pipeline: candidate -> risk -> cost -> capacity -> portfolio ->
reasoned final state, all in the same forward ledger, no execution path.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from apex.hunter.capital import (FinalState, ForecastSlot, Reason,
                                 evaluate_candidate,
                                 intraday_market_uncertain)
from apex.hunter.chartstate import compute_chart_state
from apex.hunter.forward_pass import decision_pass
from apex.portfolio.risk import PortfolioState
from tests.test_hunter_p1b import bars, ctx, failed_spike_frame

EMPTY = PortfolioState(nav=100_000.0, positions={}, sector_weights={},
                       heat=0.0, drawdown_budget_left=1.0,
                       sleeve_correlations={})


def candidate(**kw):
    base = {"decision_id": "c1", "session_date": "2026-08-17",
            "symbol": "AMD", "playbook_id": "HUNTER-001_v1",
            "direction": "LONG", "entry": 100.0, "stop": 99.5,
            "target": 101.0, "risk_frac": 0.005,
            "forward_eligibility": "FORWARD_ELIGIBLE",
            "chart_state": {"data_quality": []}}
    base.update(kw)
    return base


def run(cand=None, **kw):
    args = {"sector": "Technology", "median_dollar_volume": 500e6,
            "ann_vol": 0.35, "market_uncertain": False,
            "forecast": ForecastSlot(), "portfolio": EMPTY}
    args.update(kw)
    return evaluate_candidate(cand or candidate(), **args)


# 1. a valid Hunter candidate reaches Capital and gets a reasoned state
def test_valid_candidate_reaches_capital():
    cd = run()
    assert cd.final_state == "OBSERVE"
    assert Reason.NO_CALIBRATED_FORECAST.value in cd.reason_codes
    assert cd.weight is not None and cd.gates["risk"]["accepted"]


# 2. risk can kill it
def test_risk_kills():
    hot = PortfolioState(nav=100_000.0, positions={}, sector_weights={},
                           heat=0.999, drawdown_budget_left=1.0,
                           sleeve_correlations={})
    cd = run(portfolio=hot)
    assert cd.final_state == "NO_TRADE"
    assert Reason.RISK_LIMIT.value in cd.reason_codes


# 3. cost can kill capital authorization (unknown cost blocks, is recorded)
def test_cost_unknown_blocks_authorization():
    cd = run()                                     # no measured spread
    assert Reason.COST_UNKNOWN.value in cd.reason_codes
    assert cd.gates["cost"] == "UNKNOWN"
    cd2 = run(relative_spread=0.0004)
    assert Reason.COST_UNKNOWN.value not in cd2.reason_codes


# 4. capacity can kill it
def test_capacity_kills():
    cd = run(median_dollar_volume=1e4)             # illiquid: tiny ADDV
    assert cd.final_state == "NO_TRADE"
    assert Reason.CAPACITY_LIMIT.value in cd.reason_codes


# 5. portfolio concentration can kill it
def test_portfolio_concentration_kills():
    heavy = PortfolioState(nav=100_000.0, positions={},
                           sector_weights={"Technology": 0.99},
                           heat=0.0, drawdown_budget_left=1.0,
                           sleeve_correlations={})
    cd = run(portfolio=heavy)
    assert cd.final_state == "NO_TRADE"
    assert Reason.PORTFOLIO_CONFLICT.value in cd.reason_codes


# 6. regime uncertainty makes the decision more conservative, never less
def test_regime_uncertainty_is_conservative_only():
    calm, uncertain = run(), run(market_uncertain=True)
    assert uncertain.final_state == "WATCH" and calm.final_state == "OBSERVE"
    assert Reason.REGIME_UNCERTAIN.value in uncertain.reason_codes
    assert uncertain.weight < calm.weight          # budget halved
    mkt = compute_chart_state("SPY", bars("SPY", drift=-0.12),
                              pd.Timestamp("2026-08-10 15:00",
                                           tz="America/New_York")
                              .tz_convert("UTC"), ctx("SPY"))
    assert intraday_market_uncertain(mkt) is True  # big tape move
    assert intraday_market_uncertain(None) is True  # unknown = uncertain


# 7. a missing calibrated forecast can never become an expected return —
#    and even a PRESENT estimate is refused until Phase 3 is commissioned
def test_forecast_never_synthesized():
    cd = run()
    assert cd.forecast_status == "NOT_YET_AVAILABLE"
    flat = str(cd.as_record())
    assert "expected_return" not in flat and "expected_net" not in flat
    lit = run(forecast=ForecastSlot(status="HISTORICAL_EMPIRICAL",
                                    estimate=object()))
    assert lit.final_state == "REFUSED"
    assert Reason.GOVERNANCE_FAILURE.value in lit.reason_codes
    assert "not commissioned" in " ".join(lit.reasons_detail)


# 8. NO-TRADE is reachable (proven above) and REFUSED guards governance
def test_governance_refusals():
    ineligible = candidate(forward_eligibility="NOT_FORWARD_ELIGIBLE")
    assert run(ineligible).final_state == "REFUSED"
    baseline = candidate(playbook_id="BASELINE-MOMENTUM")
    assert run(baseline).final_state == "REFUSED"
    dirty = candidate(chart_state={"data_quality": ["STALE_BARS"]})
    cd = run(dirty)
    assert cd.final_state == "REFUSED"
    assert Reason.DATA_QUALITY.value in cd.reason_codes


# 9. every rejection is preserved for later realization comparison
def test_rejections_preserved_in_scoreboard():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    from hunter_scoreboard import build_scoreboard
    kinds = {"forward_state": [], "scan": [], "decision": [],
             "realization": [],
             "capital_decision": [
                 {"kind": "capital_decision", "final_state": "NO_TRADE",
                  "reason_codes": ["RISK_LIMIT"],
                  "evidence_class": "EODHD_FORWARD_OBSERVATION"},
                 {"kind": "capital_decision", "final_state": "OBSERVE",
                  "reason_codes": ["NO_CALIBRATED_FORECAST"],
                  "evidence_class": "EODHD_FORWARD_OBSERVATION"}]}
    cap = build_scoreboard(kinds)["capital"]
    assert cap["final_states"] == {"NO_TRADE": 1, "OBSERVE": 1}
    assert cap["reason_codes"]["RISK_LIMIT"] == 1
    assert cap["paper_eligible_n"] == 0


# 10. no execution method is reachable; LIVE_ELIGIBLE does not exist
def test_no_execution_reachable():
    import apex.hunter.capital as capmod
    src = open(capmod.__file__.replace(".pyc", ".py")).read()
    assert "from apex.hunter.broker" not in src
    assert "import broker" not in src
    assert "place_order" not in src
    assert "LIVE_ELIGIBLE" not in {s.value for s in FinalState}
    assert not any(callable(getattr(capmod, n, None)) and "order" in n.lower()
                   for n in dir(capmod))


# End-to-end: a Monday-shaped candidate flows market observation ->
# perception -> playbook -> birth gate -> capital, in ONE pass, one ledger
def test_end_to_end_spine_single_pipeline():
    f, t = failed_spike_frame()                    # real H002 textbook shape
    spy = bars("SPY", n=120, noise=5e-5)
    universe = {"symbols": {"X": {"sector": "Technology",
                                  "sector_etf": None,
                                  "median_dollar_volume": 500e6}},
                "universe_limitation": "test"}
    contexts = {"X": ctx("X"), "SPY.US": ctx("SPY")}
    bars_by = {"X": f, "SPY.US": spy}
    scan_record, records = decision_pass(t, universe, bars_by, contexts)
    kinds = {r.get("kind") for r in records}
    assert "decision" in kinds and "capital_decision" in kinds
    pb = [r for r in records if r.get("kind") == "decision"
          and not r["playbook_id"].startswith("BASELINE-")]
    cap = [r for r in records if r.get("kind") == "capital_decision"]
    assert len(pb) == 1 and pb[0]["playbook_id"] == "HUNTER-002_v1"
    assert len(cap) == 1
    assert cap[0]["decision_id"] == pb[0]["decision_id"]
    assert cap[0]["final_state"] in ("OBSERVE", "WATCH", "NO_TRADE",
                                     "REFUSED")
    assert cap[0]["forecast_status"] == "NOT_YET_AVAILABLE"
    assert cap[0]["evidence_class"] == "EODHD_FORWARD_OBSERVATION"
    assert scan_record["abnormal"] >= 1
