"""THE EXECUTION GATEWAY — the only door between APEX and a venue.

    APEX -> ExecutionGateway -> <Broker>Adapter -> venue

Terminal state is ORDER_READY. There is no send path: `ReadinessState`
has no ORDER_SENT, the adapter has no placement method, and the gateway
runs the sealing tripwire before every evaluation.

THE PRE-HANDOFF KILL CHAIN — fifteen checks, every failure reason-coded,
any failure refuses. Nothing stale, duplicated, unsupported, unhealthy,
or unauthorized reaches ORDER_READY:

  kill switch · decision lineage · evidence eligibility · Capital state
  · market-state freshness · quote freshness · data health · broker
  connection · tradability · account visibility · capability · risk ·
  cost · portfolio · instrument validity · duplicate intent

IDEMPOTENCY: intent_id = hash(decision_id, expression_id,
intent_version). A restart cannot duplicate an existing ORDER_READY
intent because the ledger is consulted, not memory.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from apex.execution.contracts import (BrokerReview, ExecutionReadinessResult,
                                      OrderIntent, ReadinessState)
from apex.execution.killswitch import engaged as kill_engaged
from apex.execution.killswitch import record_check, state as kill_state
from apex.execution.sealing import assert_no_placement_surface
from apex.hunter.contracts import content_hash

GATEWAY_VERSION = "apex_execution_gateway_v1"
INTENT_LEDGER = Path("results/execution/order_intents.jsonl")
MAX_QUOTE_AGE_S = 30.0
MAX_DECISION_AGE_S = 900.0


def intent_id_for(decision_id: str, expression_id: str,
                  intent_version: int) -> str:
    return content_hash({"d": decision_id, "e": expression_id,
                         "v": intent_version})[:16]


def _ledger_rows() -> list:
    if not INTENT_LEDGER.exists():
        return []
    out = []
    for line in INTENT_LEDGER.read_text().splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def existing_ready_intents() -> set:
    return {r.get("intent", {}).get("intent_id")
            for r in _ledger_rows()
            if r.get("state") == ReadinessState.ORDER_READY.value}


class ExecutionGateway:
    """Provider-neutral. Knows adapters by interface, never by brand."""

    def __init__(self, adapter, ledger: Path = INTENT_LEDGER):
        assert_no_placement_surface(adapter, "broker adapter")
        self.adapter = adapter
        self.ledger = ledger

    # ------------------------------------------------------------ kill chain
    def _kill_chain(self, intent: OrderIntent, decision: dict,
                    capital: dict, now) -> tuple:
        checks, reasons = {}, []

        def check(name: str, ok: bool, detail: str = "") -> None:
            checks[name] = {"pass": bool(ok), "detail": detail}
            if not ok:
                reasons.append(f"{name}: {detail or 'failed'}")

        check("kill_switch", not kill_engaged(),
              "EXECUTION_KILL_SWITCH engaged" if kill_engaged() else "armed")
        check("decision_lineage",
              bool(decision.get("decision_id") and decision.get("t_utc")),
              "missing decision lineage")
        elig = decision.get("forward_eligibility")
        check("evidence_eligibility", elig == "FORWARD_ELIGIBLE",
              f"forward_eligibility={elig}")
        cap_state = (capital or {}).get("final_state")
        check("capital_state", cap_state == "PAPER_ELIGIBLE",
              f"capital says {cap_state}; only PAPER_ELIGIBLE may advance")
        age = None
        try:
            age = (pd.Timestamp(now)
                   - pd.Timestamp(decision["t_utc"])).total_seconds()
        except Exception:                                   # noqa: BLE001
            pass
        check("decision_freshness", age is not None and age
              <= MAX_DECISION_AGE_S,
              f"decision age {age}s > {MAX_DECISION_AGE_S}s"
              if age is not None else "unknown decision age")
        q = self.adapter.quote(intent.symbol)
        check("quote_available", q.status == "OK", f"quote {q.status}")
        check("quote_freshness",
              q.status == "OK" and (q.age_seconds is None
                                    or q.age_seconds <= MAX_QUOTE_AGE_S),
              f"quote age {q.age_seconds}s")
        dq = (decision.get("chart_state") or {}).get("data_quality") or ()
        check("data_health", not dq, f"data quality flags {list(dq)}")
        health = self.adapter.connection_health()
        check("broker_connection", health.get("status") == "READY",
              health.get("status", "unknown"))
        trad = self.adapter.tradability(intent.symbol)
        check("tradability", trad.status == "TRADABLE",
              f"tradability {trad.status} {trad.reason}")
        acct = self.adapter.account_state()
        check("account_visibility", acct.status == "OK",
              f"account {acct.status}")
        caps = self.adapter.capabilities()
        cap_needed = ("options_debit_spread" if intent.asset_class == "OPTION"
                      and len(intent.legs) > 1 else
                      "options_long_call" if intent.asset_class == "OPTION"
                      else {"LIMIT": "equity_limit",
                            "MARKET": "equity_market",
                            "STOP_LIMIT": "equity_stop_limit"}.get(
                                intent.order_type, "equity_limit"))
        ok_cap, cap_detail = caps.supports(cap_needed)
        check("broker_capability", ok_cap, cap_detail or cap_needed)
        gates = (capital or {}).get("gates") or {}
        check("risk_state", bool(gates.get("risk", {}).get("accepted")),
              "capital risk gate not accepted")
        check("cost_state", gates.get("cost") not in (None, "UNKNOWN"),
              "execution cost UNKNOWN")
        check("portfolio_state", "portfolio" not in str(
            (capital or {}).get("reason_codes", ())).lower(),
              "portfolio conflict recorded")
        check("instrument_validity", bool(intent.symbol) and
              intent.quantity > 0, "invalid instrument or quantity")
        dup = intent.intent_id in existing_ready_intents()
        check("duplicate_intent", not dup,
              "an ORDER_READY intent already exists for this "
              "decision/expression/version")
        return checks, tuple(reasons), dup

    # ------------------------------------------------------------ evaluation
    def evaluate(self, intent: OrderIntent, decision: dict, capital: dict,
                 now=None, record: bool = True) -> ExecutionReadinessResult:
        """The ONLY path toward ORDER_READY. Never sends anything."""
        assert_no_placement_surface(self.adapter, "broker adapter")
        now = pd.Timestamp(now) if now else pd.Timestamp.now(tz="UTC")
        record_check(f"gateway.evaluate {intent.symbol}")
        checks, reasons, dup = self._kill_chain(intent, decision, capital,
                                                now)

        if kill_engaged():
            state = ReadinessState.KILLED.value
            review = None
        elif dup:
            state = ReadinessState.DUPLICATE.value
            review = None
        elif not self.adapter.authenticated:
            state = ReadinessState.BLOCKED_BROKER_AUTH.value
            review = None
        elif any("broker_capability" in r for r in reasons):
            state = ReadinessState.CAPABILITY_UNAVAILABLE.value
            review = None
        elif any("freshness" in r for r in reasons):
            state = ReadinessState.STALE.value
            review = None
        elif reasons:
            state = ReadinessState.REFUSED.value
            review = None
        else:
            rv = self.adapter.review_order(intent)
            review = rv.as_record()
            state = (ReadinessState.ORDER_READY.value
                     if rv.review in (BrokerReview.PASS.value,
                                      BrokerReview.WARNING.value)
                     else ReadinessState.REFUSED.value)
            if state != ReadinessState.ORDER_READY.value:
                reasons = reasons + tuple(rv.reasons) + (
                    f"broker review {rv.review}",)

        result = ExecutionReadinessResult(
            state=state, intent=intent.as_record(), reasons=reasons,
            kill_chain={"checks": checks, "kill_switch": kill_state(),
                        "gateway": GATEWAY_VERSION},
            broker_review=review)
        if record:
            self._record(result)
        return result

    def _record(self, result: ExecutionReadinessResult) -> None:
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]
                               / "scripts"))
        from nightly_pull import _chain_append
        self.ledger.parent.mkdir(parents=True, exist_ok=True)
        _chain_append(self.ledger, result.as_record())
