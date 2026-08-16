#!/usr/bin/env python
"""EXECUTION_REHEARSAL_SYNTHETIC — the closest possible rehearsal to live
trading without crossing the capital boundary.

    python scripts/execution_rehearsal_synthetic.py [--symbol SPY]

    real Robinhood quote
            v
    synthetic qualified APEX opportunity   <- clearly labeled, never real
            v
    Captain -> Capital rehearsal fixture -> Expression Engine
            v
    real option chain (if the broker offers one)
            v
    OrderIntent -> real Robinhood broker review
            v
    ORDER_READY
            v
    STOP

The market data is REAL. The opportunity is SYNTHETIC and stamped so on
every record. The stop at the end is structural, not disciplinary: there
is no next step in the codebase.

Distinct from erd1_rehearsal.py, which proves the plumbing with a mock
read surface. This one uses the live broker and therefore only produces
meaningful rows after the operator authenticates.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_S = Path(__file__).resolve().parent
sys.path.insert(0, str(_S.parent)); sys.path.insert(0, str(_S))

import pandas as pd  # noqa: E402

FIXTURE_TAG = "EXECUTION_REHEARSAL_SYNTHETIC"
LEDGER = Path("results/execution/rehearsal_synthetic.jsonl")


def _append(rec: dict) -> None:
    from nightly_pull import _chain_append
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    _chain_append(LEDGER, {**rec, "rehearsal": True, "fixture": FIXTURE_TAG,
                           "production_evidence": False,
                           "evidence_class": "REHEARSAL_NOT_EVIDENCE"})


def real_quote(adapter, symbol: str) -> dict:
    """The one genuinely live input. No synthetic fallback: a rehearsal
    that quietly invents a price is a simulation wearing a rehearsal's
    clothes."""
    from apex.execution.robinhood import BrokerAuthRequired
    try:
        q = adapter._call("get_stock_quote", symbol=symbol)
    except BrokerAuthRequired:
        return {"status": "BLOCKED_BROKER_AUTH"}
    except Exception as e:                                  # noqa: BLE001
        return {"status": "QUOTE_FAILED", "error": type(e).__name__}
    return {"status": "OK", **q}


def synthetic_opportunity(symbol: str, spot: float) -> dict:
    """A qualified opportunity that is honestly fake. Geometry is derived
    from the REAL spot so the downstream arithmetic is realistic."""
    stop = round(spot * 0.993, 2)
    return {
        "kind": "decision", "decision_id": f"SYNTH-{symbol}-001",
        "t_utc": str(pd.Timestamp.now(tz="UTC")), "symbol": symbol,
        "playbook_id": "HUNTER-001_v1", "direction": "LONG",
        "entry": spot, "stop": stop, "target": round(spot * 1.014, 2),
        "risk_frac": round((spot - stop) / spot, 5),
        "forward_eligibility": "FORWARD_ELIGIBLE",
        "chart_state": {"data_quality": [], "rvol_tod": 2.4,
                        "realized_vol_ann": 0.22},
        "relative_strength": {"excess_market_60m": 0.006},
        "market_state": {"day_return": 0.002, "above_vwap": True},
        "synthetic": True, "spot_source": "ROBINHOOD_LIVE_QUOTE"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="SPY",
                    help="liquid name: this rehearses PLUMBING, not a view")
    a = ap.parse_args()

    from apex.captain.kernel import assess
    from apex.execution.contracts import OrderIntent
    from apex.execution.expression_v2 import evaluate as expr_eval
    from apex.execution.gateway import ExecutionGateway, intent_id_for
    from apex.execution.robinhood import BrokerAuthRequired, RobinhoodAdapter
    try:
        from apex.execution.mcp_transport import transport
    except ImportError:
        transport = None

    adapter = RobinhoodAdapter(transport)
    print("=" * 68)
    print("EXECUTION_REHEARSAL_SYNTHETIC — real quote, fake opportunity, "
          "sealed vault")
    print("=" * 68)

    q = real_quote(adapter, a.symbol)
    if q["status"] != "OK":
        print(f"\nSTOPPED AT STEP 1: {q['status']}")
        print("The rehearsal refuses to invent a price. Authenticate the "
              "broker (/mcp -> robinhood-trading), then re-run.")
        _append({"kind": "rehearsal_stopped", "stage": "real_quote",
                 "status": q["status"], "symbol": a.symbol})
        return 2

    spot = float(q.get("last") or q.get("ask") or 0.0)
    print(f"\n1. REAL QUOTE      {a.symbol} last={spot} "
          f"bid={q.get('bid')} ask={q.get('ask')} age={q.get('age_seconds')}s")

    d = synthetic_opportunity(a.symbol, spot)
    _append(d)
    print(f"2. SYNTHETIC OPP   {d['decision_id']} LONG entry={d['entry']} "
          f"stop={d['stop']} (SYNTHETIC, labeled on every record)")

    cap = {"kind": "capital_decision", "final_state": "PAPER_ELIGIBLE",
           "fixture": FIXTURE_TAG, "reason_codes": [], "weight": 0.02,
           "target_notional_usd": round(spot * 10, 2),
           "gates": {"risk": {"accepted": True},
                     "cost": {"relative_spread": 0.0002}},
           "note": "FIXTURE ONLY — production Capital cannot emit "
                   "PAPER_ELIGIBLE while the forecast slot is uncommissioned"}
    _append(cap)

    st = assess(d, {"analog_view": {"status": "NO_VALID_ANALOGS"},
                    "ml_view": {"status": "UNTRAINED"},
                    "swarm_view": {"status": "BLOCKED_EXTERNAL_AUTH"},
                    "disagreement": {"level": "UNMEASURABLE"},
                    "distribution_source_status": "REFUSED"},
                {"verdict": "SURVIVED_CLEAN"}, cap)
    _append(st.as_record())
    print(f"3. CAPTAIN         {st.next_action} "
          f"(decision_power={st.as_record()['decision_power']})")
    print(f"4. CAPITAL         {cap['final_state']} (FIXTURE) "
          f"notional=${cap['target_notional_usd']}")

    chain, chain_src = [], "NONE"
    try:
        raw = adapter._call("get_options_chains", symbol=a.symbol)
        chain_src = "ROBINHOOD_LIVE_CHAIN" if raw else "EMPTY"
    except BrokerAuthRequired:
        chain_src = "BLOCKED_BROKER_AUTH"
    except Exception as e:                                  # noqa: BLE001
        chain_src = f"UNAVAILABLE_{type(e).__name__}"

    dec = expr_eval(d, spot=spot, chain=chain,
                    capabilities=adapter.capabilities(),
                    forecast_status="REFUSED", shares=10)
    rec = dec.as_record(); rec["chain_source"] = chain_src
    _append(rec)
    print(f"5. EXPRESSION      {dec.expression_type} ({dec.mode}) "
          f"chain={chain_src} max_loss={dec.maximum_loss} "
          f"authorization={dec.authorization_power}")

    intent = OrderIntent(
        intent_id=intent_id_for(d["decision_id"], "SYNTH-EQ", 1),
        decision_id=d["decision_id"], expression_id="SYNTH-EQ",
        intent_version=1, symbol=a.symbol, side="BUY", quantity=10,
        order_type="LIMIT", limit_price=spot, stop_price=None,
        time_in_force="DAY", asset_class="EQUITY",
        lineage={"captain": st.next_action, "fixture": FIXTURE_TAG,
                 "spot_source": "ROBINHOOD_LIVE_QUOTE"})
    g = ExecutionGateway(adapter, ledger=LEDGER)
    res = g.evaluate(intent, d, cap, record=False)
    _append(res.as_record())
    passed = sum(1 for c in res.kill_chain["checks"].values() if c["pass"])
    total = len(res.kill_chain["checks"])
    print(f"6. BROKER REVIEW   kill chain {passed}/{total}")
    for r in list(res.reasons)[:5]:
        print(f"                   refusal: {r}")
    print(f"7. GATEWAY         {res.state} "
          f"(live_placement={res.as_record().get('live_placement')})")
    print("8. STOP            no further step exists in the codebase")

    from apex.execution.killswitch import state as kstate
    print(f"\nLIVE PLACEMENT: SEALED | KILL SWITCH: {kstate()['kill_switch']}")
    print(f"records -> {LEDGER} (rehearsal=True, production_evidence=False)")
    return 0 if res.state == "ORDER_READY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
