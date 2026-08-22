"""THE MANUAL EXECUTION DESK -- cards, confirmations, latency truth.

Expression target: BTC_PERP_KRAKEN_MANUAL
State machine:
    CANDIDATE -> CAPITAL_APPROVED -> BEFORE_CARD_SEALED ->
    MANUAL_ORDER_REQUESTED -> AWAITING_OPERATOR_FILL ->
    FILLED | NOT_EXECUTED_* | EXPIRED_BEFORE_EXECUTION

Everything is persisted to a hash-chained ledger and the desk rebuilds
its entire state from replay on restart (commissioning-tested).
"""
from __future__ import annotations

import json
from pathlib import Path

from apex.governance.chain_ledger import chain_append

EXPRESSION_TARGET = "BTC_PERP_KRAKEN_MANUAL"

STATUS_STATES = ("NOT_CONFIGURED", "ACCOUNT_UNLOCK_REQUIRED",
                 "READY_MANUAL", "MAINTENANCE", "UNAVAILABLE",
                 "OPERATOR_PAUSED")

CARD_STATES = ("CANDIDATE", "CAPITAL_APPROVED", "BEFORE_CARD_SEALED",
               "MANUAL_ORDER_REQUESTED", "AWAITING_OPERATOR_FILL",
               "FILLED", "NOT_EXECUTED", "EXPIRED")

OUTCOMES = ("FILLED_AS_REQUESTED", "FILLED_WITH_DEVIATION",
            "PARTIALLY_FILLED", "NOT_EXECUTED_PRICE_MOVED",
            "NOT_EXECUTED_OPERATOR", "NOT_EXECUTED_MAINTENANCE",
            "NOT_EXECUTED_VENUE", "EXPIRED_BEFORE_EXECUTION")

EXIT_REASONS = ("TARGET", "THESIS_INVALIDATED", "STOP", "TIME_EXIT",
                "RISK_REDUCTION", "REGIME_CHANGE", "OTHER")

# card fields that the emergency-risk law and readability law demand;
# a card missing any of these is REFUSED at sealing time
REQUIRED_CARD_FIELDS = (
    "contract", "action", "order_type", "entry", "max_acceptable_entry",
    "contracts", "btc_exposure", "usd_notional", "account_risk_usd",
    "account_risk_pct", "invalidation", "stop", "target",
    "expected_hold", "thesis", "why_now", "primary_failure_condition",
    "time_valid_s")

# Kraken Derivatives US weekly maintenance: Friday 17:00-19:00 CT
# (support.kraken.com maintenance-windows-us-perpetual-futures).
# Scheduled maintenance is VENUE_UNAVAILABLE_SCHEDULED, never a
# system failure -- and never a window to issue new cards into.
MAINT_WEEKDAY = 4               # Friday
MAINT_START_CT = 17
MAINT_END_CT = 19


def in_scheduled_maintenance(now_utc) -> bool:
    import pandas as pd
    ct = pd.Timestamp(now_utc).tz_convert("America/Chicago")
    return (ct.dayofweek == MAINT_WEEKDAY and
            MAINT_START_CT <= ct.hour < MAINT_END_CT)


class ManualExecutionRefused(RuntimeError):
    pass


class ManualExecutionDesk:
    """All state is derived from the ledger -- restart-safe by
    construction. `now_fn` is injectable for off-market tests."""

    def __init__(self, ledger: Path, now_fn=None) -> None:
        import pandas as pd
        self.ledger = Path(ledger)
        self._now = now_fn or (lambda: pd.Timestamp.now(tz="UTC"))
        self.cards: dict = {}
        self.attestation: dict | None = None
        self.operator_paused = False
        self._replay()

    # ------------------------------------------------ replay recovery
    def _replay(self) -> None:
        if not self.ledger.exists():
            return
        for line in self.ledger.read_text().splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            self._apply(rec)

    def _apply(self, rec: dict) -> None:
        k = rec.get("kind")
        if k == "operator_attestation":
            self.attestation = rec
        elif k == "operator_pause":
            self.operator_paused = rec["paused"]
        elif k == "manual_card":
            self.cards[rec["trade_id"]] = rec
        elif k in ("card_event", "fill_confirmation",
                   "exit_card", "exit_confirmation",
                   "position_mark"):
            c = self.cards.get(rec["trade_id"])
            if c is not None:
                c.setdefault("events", []).append(rec)
                if "state" in rec:
                    c["state"] = rec["state"]
                if "outcome" in rec:
                    c["outcome"] = rec["outcome"]

    def _append(self, rec: dict) -> dict:
        rec = dict(rec, decision_power="NONE",
                   expression_target=EXPRESSION_TARGET)
        chain_append(self.ledger, rec)
        self._apply(rec)
        return rec

    # ------------------------------------------------ operator gate
    def record_attestation(self, *, account_verified: bool,
                           us_futures_unlocked: bool,
                           btc_perp_visible: bool,
                           account_funded: bool,
                           contract_understood: str,
                           operator_statement: str) -> dict:
        """One-time operator confirmation. NO SECRETS -- booleans and
        the operator's own words only."""
        return self._append({
            "kind": "operator_attestation",
            "known_from": str(self._now()),
            "account_verified": account_verified,
            "us_futures_unlocked": us_futures_unlocked,
            "btc_perp_visible": btc_perp_visible,
            "account_funded": account_funded,
            "contract_understood": contract_understood,
            "operator_statement": operator_statement})

    def set_paused(self, paused: bool) -> None:
        self._append({"kind": "operator_pause", "paused": paused,
                      "known_from": str(self._now())})

    def status(self) -> str:
        if self.operator_paused:
            return "OPERATOR_PAUSED"
        if in_scheduled_maintenance(self._now()):
            return "MAINTENANCE"
        a = self.attestation
        if a is None:
            return "NOT_CONFIGURED"
        if not (a["account_verified"] and a["us_futures_unlocked"]):
            return "ACCOUNT_UNLOCK_REQUIRED"
        if not (a["btc_perp_visible"] and a["account_funded"]):
            return "ACCOUNT_UNLOCK_REQUIRED"
        return "READY_MANUAL"

    # ------------------------------------------------ card lifecycle
    def seal_card(self, trade: dict, *, commissioning_test: bool,
                  authority_level: str) -> dict:
        """BEFORE_CARD_SEALED + MANUAL_ORDER_REQUESTED in one atomic
        record. Refuses: missing fields (emergency law included),
        non-test cards below PAPER authority, maintenance windows."""
        missing = [f for f in REQUIRED_CARD_FIELDS
                   if trade.get(f) in (None, "")]
        if missing:
            raise ManualExecutionRefused(
                f"card refused -- missing fields {missing} (the "
                f"emergency-risk law requires stop + invalidation "
                f"BEFORE entry; the readability law requires the rest)")
        if authority_level == "OBSERVE" and not commissioning_test:
            raise ManualExecutionRefused(
                "at OBSERVE authority only COMMISSIONING_TEST cards "
                "may exist -- no actionable live-card generation")
        if in_scheduled_maintenance(self._now()):
            raise ManualExecutionRefused(
                "VENUE_UNAVAILABLE_SCHEDULED -- no new execution "
                "requests during known maintenance (Fri 17-19 CT)")
        if trade["action"] not in ("LONG", "SHORT"):
            raise ManualExecutionRefused("action must be LONG or SHORT")
        now = self._now()
        trade_id = trade.get("trade_id") or \
            f"MKX-{now.strftime('%Y%m%d-%H%M%S')}-{len(self.cards)}"
        card = {
            "kind": "manual_card", "trade_id": trade_id,
            "state": "AWAITING_OPERATOR_FILL",
            "commissioning_test": commissioning_test,
            "venue": "KRAKEN PRO -- US PERPETUAL FUTURES",
            "decision_at": trade.get("decision_at") or str(now),
            "card_sealed_at": str(now),
            "decision_reference_price":
                trade.get("decision_reference_price"),
            "if_not_filled_by": str(
                now + __import__("pandas").Timedelta(
                    seconds=trade["time_valid_s"])),
            "expiry_action": trade.get("expiry_action",
                                       "CANCEL / RE-UNDERWRITE"),
            **{f: trade[f] for f in REQUIRED_CARD_FIELDS}}
        if commissioning_test:
            card["tag"] = "COMMISSIONING_TEST"
            card["banner"] = "TEST CARD -- NOT ELIGIBLE FOR EXECUTION"
        return self._append(card)

    def render_card(self, trade_id: str) -> str:
        c = self.cards[trade_id]
        lines = ["-" * 60, "APEX BTC MANUAL EXECUTION"]
        if c.get("banner"):
            lines.append(f"*** {c['banner']} ***")
        lines += ["-" * 60,
                  f"TRADE ID: {c['trade_id']}",
                  f"DECISION TIME: {c['decision_at']}",
                  f"CARD SEALED: {c['card_sealed_at']}",
                  f"VENUE: {c['venue']}",
                  f"CONTRACT: {c['contract']}",
                  f"ACTION: {c['action']}",
                  f"ORDER: {c['order_type']}",
                  f"ENTRY: {c['entry']}",
                  f"MAX ACCEPTABLE ENTRY: {c['max_acceptable_entry']}",
                  f"CONTRACTS: {c['contracts']}",
                  f"BTC EXPOSURE: {c['btc_exposure']}",
                  f"USD NOTIONAL: {c['usd_notional']}",
                  f"ACCOUNT RISK: ${c['account_risk_usd']} "
                  f"({c['account_risk_pct']}%)",
                  f"INVALIDATION: {c['invalidation']}",
                  f"STOP: {c['stop']}",
                  f"TARGET / PROFIT MANAGEMENT: {c['target']}",
                  f"EXPECTED HOLD: {c['expected_hold']}",
                  f"THESIS: {c['thesis']}",
                  f"WHY NOW: {c['why_now']}",
                  f"PRIMARY FAILURE CONDITION: "
                  f"{c['primary_failure_condition']}",
                  f"TIME VALID: {c['time_valid_s']}s",
                  f"IF NOT FILLED BY: {c['if_not_filled_by']}",
                  f"ACTION ON EXPIRY: {c['expiry_action']}",
                  "-" * 60]
        return "\n".join(lines)

    def mark_presented(self, trade_id: str) -> None:
        self._append({"kind": "card_event", "trade_id": trade_id,
                      "event": "card_presented_at",
                      "at": str(self._now())})

    def mark_operator_ack(self, trade_id: str) -> None:
        self._append({"kind": "card_event", "trade_id": trade_id,
                      "event": "operator_ack_at",
                      "at": str(self._now())})

    def mark_submitted(self, trade_id: str,
                       price_when_submitted=None) -> None:
        self._append({"kind": "card_event", "trade_id": trade_id,
                      "event": "order_submitted_at",
                      "at": str(self._now()),
                      "price_when_operator_submitted":
                          price_when_submitted})

    # ------------------------------------------------ confirmation
    def confirm_fill(self, trade_id: str, *, actual_entry: float,
                     contracts: float, fill_at: str | None = None,
                     fees=None) -> dict:
        """The ONLY path to FILLED. Duplicate confirmations are
        refused; deviation beyond the card's own tolerance is flagged,
        and the intended price is never substituted for the actual."""
        c = self.cards.get(trade_id)
        if c is None:
            raise ManualExecutionRefused(f"unknown trade_id {trade_id}")
        if c.get("outcome") or c["state"] in ("FILLED", "NOT_EXECUTED",
                                              "EXPIRED"):
            raise ManualExecutionRefused(
                f"REFUSED_DUPLICATE_CONFIRMATION -- {trade_id} already "
                f"terminal ({c.get('outcome')})")
        deviation = False
        if c["action"] == "LONG":
            deviation = actual_entry > float(c["max_acceptable_entry"])
        else:
            deviation = actual_entry < float(c["max_acceptable_entry"])
        partial = float(contracts) < float(c["contracts"])
        outcome = ("PARTIALLY_FILLED" if partial else
                   "FILLED_WITH_DEVIATION" if deviation else
                   "FILLED_AS_REQUESTED")
        rec = self._append({
            "kind": "fill_confirmation", "trade_id": trade_id,
            "state": "FILLED", "outcome": outcome,
            "fill_at": fill_at or str(self._now()),
            "actual_entry": actual_entry,
            "contracts_filled": contracts,
            "contracts_requested": c["contracts"],
            "fees": fees,
            "execution_deviation_flag": deviation,
            "slippage_from_decision":
                round(actual_entry -
                      float(c["decision_reference_price"]), 6)
                if c.get("decision_reference_price") else None,
            "latency": self.latency(trade_id,
                fill_at=fill_at or str(self._now()))})
        return rec

    def record_not_executed(self, trade_id: str, outcome: str) -> dict:
        if outcome not in OUTCOMES or not outcome.startswith(
                ("NOT_EXECUTED", "EXPIRED")):
            raise ManualExecutionRefused(f"bad outcome {outcome}")
        c = self.cards.get(trade_id)
        if c is None or c.get("outcome"):
            raise ManualExecutionRefused(
                "unknown or already-terminal card")
        return self._append({
            "kind": "card_event", "trade_id": trade_id,
            "state": ("EXPIRED" if outcome.startswith("EXPIRED")
                      else "NOT_EXECUTED"),
            "outcome": outcome, "at": str(self._now()),
            "hypothetical_tracking": True,
            "note": "NOT_EXECUTED is legitimate; hypothetical outcome "
                    "resolves separately and never counts as a trade"})

    def sweep_expired(self) -> list:
        """Cards past if_not_filled_by with no fill -> EXPIRED."""
        import pandas as pd
        out = []
        for tid, c in list(self.cards.items()):
            if c["state"] == "AWAITING_OPERATOR_FILL" and \
                    not c.get("outcome") and \
                    self._now() > pd.Timestamp(c["if_not_filled_by"]):
                out.append(self.record_not_executed(
                    tid, "EXPIRED_BEFORE_EXECUTION"))
        return out

    # ------------------------------------------------ latency truth
    def latency(self, trade_id: str, fill_at: str | None = None
                ) -> dict:
        import pandas as pd
        c = self.cards[trade_id]
        t = {"decision_at": c.get("decision_at"),
             "card_sealed_at": c.get("card_sealed_at"),
             "fill_at": fill_at}
        for ev in c.get("events", []):
            if ev.get("kind") == "card_event" and "event" in ev and \
                    ev["event"].endswith("_at"):
                t[ev["event"]] = ev["at"]
            if ev.get("kind") == "fill_confirmation":
                t["fill_at"] = ev["fill_at"]

        def ms(a, b):
            if t.get(a) is None or t.get(b) is None:
                return None
            return round((pd.Timestamp(t[b]) - pd.Timestamp(t[a]))
                         .total_seconds() * 1000.0, 1)
        return {**t,
                "decision_to_operator_ms":
                    ms("decision_at", "card_presented_at"),
                "operator_reaction_ms":
                    ms("card_presented_at", "order_submitted_at"),
                "order_to_fill_ms":
                    ms("order_submitted_at", "fill_at"),
                "total_execution_latency_ms":
                    ms("decision_at", "fill_at")}

    # ------------------------------------------------ position + exit
    def position(self, trade_id: str) -> dict:
        c = self.cards[trade_id]
        fill = next((e for e in c.get("events", [])
                     if e.get("kind") == "fill_confirmation"), None)
        if fill is None:
            raise ManualExecutionRefused(
                "no position without operator-confirmed fill")
        marks = [e for e in c.get("events", [])
                 if e.get("kind") == "position_mark"]
        entry = fill["actual_entry"]
        qty = fill["contracts_filled"]
        sign = 1.0 if c["action"] == "LONG" else -1.0
        risk = abs(entry - float(c["stop"])) or None
        pnls = [(m["mark"] - entry) * sign for m in marks]
        return {"trade_id": trade_id, "entry": entry, "contracts": qty,
                "action": c["action"], "stop": c["stop"],
                "invalidation": c["invalidation"],
                "target": c["target"], "thesis": c["thesis"],
                "unrealized_per_unit": pnls[-1] if pnls else None,
                "mfe_per_unit": max(pnls) if pnls else None,
                "mae_per_unit": min(pnls) if pnls else None,
                "mfe_r": (max(pnls) / risk) if pnls and risk else None,
                "mae_r": (min(pnls) / risk) if pnls and risk else None,
                "marks": len(marks)}

    def record_mark(self, trade_id: str, mark: float) -> None:
        self._append({"kind": "position_mark", "trade_id": trade_id,
                      "mark": float(mark), "at": str(self._now())})

    def maintenance_exposure_check(self, trade_id: str,
                                   horizon_h: float = 12.0) -> dict:
        """Surface (never auto-close) an open position approaching a
        maintenance window the operator cannot act inside."""
        import pandas as pd
        now = self._now()
        for h in range(int(horizon_h * 4)):
            t = now + pd.Timedelta(minutes=15 * h)
            if in_scheduled_maintenance(t):
                return {"trade_id": trade_id,
                        "exposure": "OPEN_POSITION_APPROACHES_"
                                    "SCHEDULED_MAINTENANCE",
                        "window_starts_by": str(t),
                        "prescription": "NONE -- operator decides"}
        return {"trade_id": trade_id, "exposure": "NONE_IN_HORIZON"}

    def issue_exit_card(self, trade_id: str, *, reason: str,
                        order_type: str, execute_by: str) -> dict:
        if reason not in EXIT_REASONS:
            raise ManualExecutionRefused(f"bad exit reason {reason}")
        pos = self.position(trade_id)          # refuses if no fill
        rec = self._append({
            "kind": "exit_card", "trade_id": trade_id,
            "at": str(self._now()), "reason": reason,
            "action": f"CLOSE {pos['action']}",
            "contracts": pos["contracts"], "order_type": order_type,
            "current_unrealized_per_unit": pos["unrealized_per_unit"],
            "mfe_r": pos["mfe_r"], "mae_r": pos["mae_r"],
            "execute_by": execute_by,
            "law": "EXIT_REQUESTED != EXITED -- operator must confirm"})
        return rec

    def confirm_exit(self, trade_id: str, *, actual_exit: float,
                     contracts: float, fees=None) -> dict:
        c = self.cards[trade_id]
        if any(e.get("kind") == "exit_confirmation"
               for e in c.get("events", [])):
            raise ManualExecutionRefused(
                "REFUSED_DUPLICATE_CONFIRMATION -- exit already "
                "confirmed")
        if not any(e.get("kind") == "exit_card"
                   for e in c.get("events", [])):
            raise ManualExecutionRefused(
                "no exit card issued -- confirmation refused")
        pos = self.position(trade_id)
        sign = 1.0 if c["action"] == "LONG" else -1.0
        pnl_per_unit = (actual_exit - pos["entry"]) * sign
        return self._append({
            "kind": "exit_confirmation", "trade_id": trade_id,
            "state": "FILLED", "at": str(self._now()),
            "actual_exit": actual_exit, "contracts": contracts,
            "fees": fees,
            "realized_per_unit": round(pnl_per_unit, 6),
            "closed_trade_reconciliation": {
                "entry_actual": pos["entry"],
                "exit_actual": actual_exit,
                "accounting_law": "THEORETICAL_DECISION_PRICE, "
                                  "MANUAL_PAPER_FILL and "
                                  "ACTUAL_KRAKEN_FILL stay separate"}})
