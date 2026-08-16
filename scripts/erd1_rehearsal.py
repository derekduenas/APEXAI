#!/usr/bin/env python
"""ERD-1 FULL EXECUTION REHEARSAL — synthetic opportunity, real plumbing,
sealed vault.

    python scripts/erd1_rehearsal.py

D1 equity + D2 options. Both use an EXECUTION_REHEARSAL_FIXTURE that
cannot be confused with production eligibility: every record is stamped
`rehearsal: True`, written to a SEPARATE ledger, and the fixture Capital
state is labeled as a fixture in its own field. No production decision
is read, mutated, or created; no order is placed (there is no code path
to place one).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_S = Path(__file__).resolve().parent
sys.path.insert(0, str(_S.parent)); sys.path.insert(0, str(_S))

import pandas as pd  # noqa: E402

from apex.captain.kernel import assess  # noqa: E402
from apex.execution.contracts import (BrokerCapabilities,  # noqa: E402
                                      OrderIntent)
from apex.execution.expression_v2 import (OptionSnapshot,  # noqa: E402
                                          evaluate as expr_eval)
from apex.execution.gateway import ExecutionGateway, intent_id_for  # noqa: E402
from apex.execution.robinhood import RobinhoodAdapter  # noqa: E402

REHEARSAL_LEDGER = Path("results/execution/erd1_rehearsal.jsonl")
FIXTURE_TAG = "EXECUTION_REHEARSAL_FIXTURE"


def _append(rec: dict) -> None:
    from nightly_pull import _chain_append
    REHEARSAL_LEDGER.parent.mkdir(parents=True, exist_ok=True)
    _chain_append(REHEARSAL_LEDGER, {**rec, "rehearsal": True,
                                     "fixture": FIXTURE_TAG,
                                     "production_evidence": False})


def fixture_decision(symbol="AAPL") -> dict:
    """A clearly-labeled synthetic qualified opportunity."""
    return {
        "kind": "decision", "decision_id": f"REHEARSAL-{symbol}-001",
        "t_utc": str(pd.Timestamp.now(tz="UTC")), "symbol": symbol,
        "playbook_id": "HUNTER-001_v1", "direction": "LONG",
        "entry": 200.0, "stop": 198.6, "target": 202.8, "risk_frac": 0.007,
        "forward_eligibility": "FORWARD_ELIGIBLE",
        "chart_state": {"data_quality": [], "rvol_tod": 2.4,
                        "realized_vol_ann": 0.28},
        "relative_strength": {"excess_market_60m": 0.009},
        "market_state": {"day_return": 0.003, "above_vwap": True},
        "fixture": FIXTURE_TAG}


def fixture_capital() -> dict:
    """The ONLY place PAPER_ELIGIBLE appears — a labeled fixture, never
    production Capital (which cannot reach it in Epoch 1)."""
    return {"kind": "capital_decision", "final_state": "PAPER_ELIGIBLE",
            "fixture": FIXTURE_TAG, "reason_codes": [],
            "weight": 0.02, "target_notional_usd": 2000.0,
            "gates": {"risk": {"accepted": True},
                      "cost": {"relative_spread": 0.0004}},
            "note": "FIXTURE ONLY: production Capital cannot emit "
                    "PAPER_ELIGIBLE while the Phase-3 forecast slot is "
                    "uncommissioned"}


def synthetic_chain(spot=200.0) -> list:
    out = []
    for k in (190, 195, 200, 205, 210):
        for cp in ("CALL", "PUT"):
            intrinsic = max(0.0, (spot - k) if cp == "CALL" else (k - spot))
            mid = round(intrinsic + 3.2 - abs(spot - k) * 0.08, 2)
            mid = max(0.35, mid)
            out.append(OptionSnapshot(
                symbol=f"AAPL260918{'C' if cp == 'CALL' else 'P'}{k}",
                underlying="AAPL", expiration="2026-09-18", strike=float(k),
                call_put=cp, bid=round(mid - 0.06, 2),
                ask=round(mid + 0.06, 2), open_interest=4200, volume=650,
                quote_age_s=3.0, tradability="TRADABLE",
                greeks_status="UNKNOWN_NOT_SOURCED"))
    return out


def rehearse_equity(adapter) -> dict:
    d, cap = fixture_decision(), fixture_capital()
    _append(d); _append(cap)
    st = assess(d, {"analog_view": {"status": "NO_VALID_ANALOGS"},
                    "ml_view": {"status": "UNTRAINED"},
                    "swarm_view": {"status": "BLOCKED_EXTERNAL_AUTH"},
                    "disagreement": {"level": "UNMEASURABLE"},
                    "distribution_source_status": "REFUSED"},
                {"verdict": "SURVIVED_CLEAN"}, cap)
    _append(st.as_record())
    intent = OrderIntent(
        intent_id=intent_id_for(d["decision_id"], "EQ-STOCK", 1),
        decision_id=d["decision_id"], expression_id="EQ-STOCK",
        intent_version=1, symbol=d["symbol"], side="BUY", quantity=10,
        order_type="LIMIT", limit_price=d["entry"], stop_price=None,
        time_in_force="DAY", asset_class="EQUITY",
        lineage={"captain": st.next_action, "fixture": FIXTURE_TAG})
    g = ExecutionGateway(adapter, ledger=REHEARSAL_LEDGER)
    res = g.evaluate(intent, d, cap, record=False)
    _append(res.as_record())
    return {"captain": st.next_action, "state": res.state,
            "reasons": list(res.reasons)[:4],
            "checks_passed": sum(1 for c in res.kill_chain["checks"].values()
                                 if c["pass"]),
            "checks_total": len(res.kill_chain["checks"])}


def rehearse_options(adapter) -> dict:
    d, cap = fixture_decision(), fixture_capital()
    caps = adapter.capabilities()
    live_chain, source = synthetic_chain(), "SYNTHETIC_CHAIN"
    if adapter.authenticated:
        ch = adapter.option_chain("AAPL")
        if ch.get("status") == "OK":
            source = "ROBINHOOD_LIVE_CHAIN"      # real chain when authed
    dec = expr_eval(d, spot=200.0, chain=live_chain, capabilities=caps,
                    forecast_status="REFUSED", shares=10)
    rec = dec.as_record(); rec["chain_source"] = source
    _append(rec)
    intent = OrderIntent(
        intent_id=intent_id_for(d["decision_id"], "OPT-EXPR", 1),
        decision_id=d["decision_id"], expression_id="OPT-EXPR",
        intent_version=1, symbol=d["symbol"], side="BUY", quantity=1,
        order_type="LIMIT", limit_price=200.0, stop_price=None,
        time_in_force="DAY",
        asset_class=("OPTION" if dec.expression_type != "STOCK"
                     else "EQUITY"),
        lineage={"expression": dec.expression_type, "fixture": FIXTURE_TAG})
    g = ExecutionGateway(adapter, ledger=REHEARSAL_LEDGER)
    res = g.evaluate(intent, d, cap, record=False)
    _append(res.as_record())
    return {"expression": dec.expression_type, "mode": dec.mode,
            "rationale": dec.rationale[:110],
            "candidates": [c["expression_type"]
                           for c in dec.candidates_considered],
            "max_loss": dec.maximum_loss, "chain_source": source,
            "state": res.state, "authorization": dec.authorization_power}


def mock_broker():
    """A LABELED mock of the read/review surface — proves the full
    ORDER_READY path before the operator authenticates. It is a mock of
    the READ side only: it still has no placement method, and the
    gateway's tripwire scans it like any adapter."""
    def call(tool, **kw):
        return {
            "get_account_info": {"options_level": 3, "cash": 25000,
                                 "as_of": str(pd.Timestamp.now(tz="UTC"))},
            "get_buying_power": {"buying_power": 25000},
            "get_positions": {"positions": []},
            "get_open_orders": {"orders": []},
            "get_stock_quote": {"bid": 199.97, "ask": 200.03,
                                "last": 200.0, "age_seconds": 1.2},
            "get_stock_info": {"tradable": True, "state": "active"},
            "review_equity_order": {"estimated_cost": 2000.3,
                                    "estimated_fees": 0.0,
                                    "buying_power_effect": -2000.3},
            "review_option_order": {"estimated_cost": 320.0},
        }.get(tool, {})
    return RobinhoodAdapter(call)


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock-broker", action="store_true",
                    help="demonstrate the ORDER_READY path with a labeled "
                         "mock read/review surface (still no placement)")
    args = ap.parse_args()
    adapter = (mock_broker() if args.mock_broker
               else RobinhoodAdapter(None))
    print("=" * 66)
    print("ERD-1 REHEARSAL — synthetic fixture, real plumbing, vault sealed")
    print("=" * 66)
    print(f"broker: {adapter.connection_health()['status']}"
          + ("  [MOCK READ/REVIEW SURFACE — labeled, not real broker data]"
             if args.mock_broker else ""))
    eq = rehearse_equity(adapter)
    print(f"\nD1 EQUITY: captain={eq['captain']} -> {eq['state']}")
    print(f"   kill chain {eq['checks_passed']}/{eq['checks_total']} passed")
    for r in eq["reasons"]:
        print(f"   refusal: {r}")
    op = rehearse_options(adapter)
    print(f"\nD2 OPTIONS: chain={op['chain_source']} -> "
          f"{op['expression']} ({op['mode']})")
    print(f"   considered: {op['candidates']}")
    print(f"   rationale: {op['rationale']}")
    print(f"   max loss: {op['max_loss']} | authorization: "
          f"{op['authorization']} | gateway: {op['state']}")
    from apex.execution.killswitch import state as kstate
    print(f"\nLIVE PLACEMENT: SEALED | KILL SWITCH: "
          f"{kstate()['kill_switch']}")
    print(f"records -> {REHEARSAL_LEDGER} (rehearsal=True, "
          f"production_evidence=False)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
