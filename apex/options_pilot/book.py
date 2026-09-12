"""THE PILOT BOOK (M1) — reconstructed from durable records, never held in memory as truth.

    reservation   an intent whose risk envelope is approved and that is not yet finished
                  (no FILLED attempt, no terminal REFUSE attempt, no expiry/cancel record)
    position      a FILLED fill with no discharging outcome
    cash          -(debit + entry fees) at fill; +(credit - exit fees) at a RESOLVED outcome
    obligations   unfinished intents, unresolved positions, exhausted exits

Every number here is recomputed from primary fields (price x multiplier x
quantity, fee blocks re-derived from the named schedule). Disagreements
between a record's stored aggregate and the recomputation are reported as
integrity problems, never silently accepted.

Book state feeds the risk kernel: open planned risk (positions' debits +
reservation envelopes), per-underlying and per-family risk, session realized
P&L, available capital, and the certified aggregate."""
from __future__ import annotations

from apex.organism.risk_kernel import STARTING_PAPER_CAPITAL

from . import ledger as L
from .fees import FeeSchedule, recompute_fees
from .records import canonical_hash

CONTRACT_MULTIPLIER = 100.0
BETA_FAMILY = {"SPY": "US_EQUITY_INDEX", "QQQ": "US_EQUITY_INDEX", "IWM": "US_EQUITY_INDEX", "DIA": "US_EQUITY_INDEX"}


def beta_family(symbol: str) -> str:
    return BETA_FAMILY.get(symbol, "UNKNOWN")


def _fills_by_intent_seq(rows: list) -> dict:
    out: dict = {}
    for i, r in enumerate(rows):
        if r.get("kind") == "pilot_fill":
            out.setdefault((r.get("intent_ref") or {}).get("seq"), []).append((i + 1, r))
    return out


def intent_finished(attempts: list, terminal: bool) -> bool:
    """An intent is finished by a FILLED attempt, a terminal REFUSE attempt,
    or an expiry/cancellation record. WAIT attempts leave it open."""
    if terminal:
        return True
    return any(r.get("status") == "FILLED" or r.get("decision") == "REFUSE" for _s, r in attempts)


class Book:
    def __init__(self, rows: list, *, session_id: str | None, fee_schedules: dict | None = None):
        self.rows = rows
        self.session_id = session_id
        self.fee_schedules = fee_schedules or {}
        self.problems: list = []
        self._build()

    # ------------------------------------------------------------ construction
    def _build(self):
        rows = self.rows
        fills = _fills_by_intent_seq(rows)
        terminal_intents = {r.get("intent_id") for r in rows if r.get("kind") in ("pilot_intent_expired", "pilot_intent_cancelled")}
        discharging = {}
        attempts_by_fill: dict = {}
        for i, r in enumerate(rows):
            if r.get("kind") == "pilot_outcome":
                fs = (r.get("fill_ref") or {}).get("seq")
                attempts_by_fill.setdefault(fs, []).append((i + 1, r))
                if r.get("discharges_position") is True and fs not in discharging:
                    discharging[fs] = (i + 1, r)
        self.reservations, self.positions, self.closed, self.unfinished_intents = [], [], [], []
        self.cashflows: list = []
        for i, r in enumerate(rows):
            seq = i + 1
            if r.get("kind") == "pilot_intent":
                att = fills.get(seq, [])
                fin = intent_finished(att, r.get("intent_id") in terminal_intents)
                env = r.get("risk_envelope") or {}
                if not fin:
                    self.reservations.append({"intent_seq": seq, "intent_id": r.get("intent_id"), "symbol": r["contract"]["symbol"],
                                              "session_id": r.get("session_id"), "envelope_debit": env.get("envelope_debit"),
                                              "certified_max_loss": (r.get("risk") or {}).get("certified_max_loss"),
                                              "expiry_epoch": r.get("expiry_epoch"), "attempts": len(att)})
                    self.unfinished_intents.append(seq)
            elif r.get("kind") == "pilot_fill" and r.get("status") == "FILLED":
                debit = round(float(r["price"]) * CONTRACT_MULTIPLIER * int(r.get("quantity_filled", 1)), 2)
                if r.get("net_debit") != debit:
                    self.problems.append("FILL_DEBIT_DISAGREES seq %d: stored %r vs recomputed %r" % (seq, r.get("net_debit"), debit))
                fee = r.get("fees_entry") or {}
                self._check_fee(seq, fee, r.get("quantity_filled", 1), "BUY")
                fee_total = fee.get("total")
                cash = -(debit + (fee_total or 0.0))
                if r.get("cashflow_entry") is not None and round(r["cashflow_entry"], 2) != round(cash, 2):
                    self.problems.append("FILL_CASHFLOW_DISAGREES seq %d" % seq)
                self.cashflows.append({"seq": seq, "kind": "ENTRY", "amount": round(cash, 2), "fees_known": fee_total is not None})
                pos = {"fill_seq": seq, "intent_id": r.get("intent_id"), "fill_id": r.get("fill_id"), "symbol": r["contract"]["symbol"],
                       "session_id": r.get("session_id"), "release": r.get("release"), "data_provenance": r.get("data_provenance"),
                       "debit": debit, "fees_entry": fee_total, "committed_epoch": r.get("committed_epoch"),
                       "exit_schedule": r.get("exit_schedule"), "quantity": int(r.get("quantity_filled", 1)),
                       "valuation_attempts": len(attempts_by_fill.get(seq, [])),
                       "exit_exhausted": any(x.get("kind") == "pilot_exit_exhausted" and (x.get("fill_ref") or {}).get("seq") == seq for x in rows)}
                if seq in discharging:
                    oseq, o = discharging[seq]
                    pos.update(outcome_seq=oseq, outcome_status=o.get("status"))
                    if o.get("status") == "RESOLVED":
                        credit = round(float(o["exit_price"]) * CONTRACT_MULTIPLIER * pos["quantity"], 2)
                        fee_x = o.get("fees_exit") or {}
                        self._check_fee(oseq, fee_x, pos["quantity"], "SELL")
                        fx = fee_x.get("total")
                        cash_x = credit - (fx or 0.0)
                        pnl = round(credit - debit - (fee_total or 0.0) - (fx or 0.0), 2)
                        if o.get("pnl") is not None and round(o["pnl"], 2) != pnl:
                            self.problems.append("OUTCOME_PNL_DISAGREES seq %d: stored %r vs recomputed %r" % (oseq, o.get("pnl"), pnl))
                        self.cashflows.append({"seq": oseq, "kind": "EXIT", "amount": round(cash_x, 2), "fees_known": fx is not None})
                        pos.update(credit=credit, fees_exit=fx, realized_pnl=pnl)
                    self.closed.append(pos)
                else:
                    self.positions.append(pos)
        self.session_realized_pnl = round(sum(p["realized_pnl"] for p in self.closed
                                              if p.get("realized_pnl") is not None and p.get("session_id") == self.session_id), 2)
        self.total_realized_pnl = round(sum(p["realized_pnl"] for p in self.closed if p.get("realized_pnl") is not None), 2)
        self.open_cost = round(sum(p["debit"] for p in self.positions), 2)
        self.reserved = round(sum(float(x["envelope_debit"] or 0.0) for x in self.reservations), 2)
        self.cash = round(STARTING_PAPER_CAPITAL + sum(c["amount"] for c in self.cashflows), 2)
        self.fees_unknown = any(not c["fees_known"] for c in self.cashflows)
        self.outstanding = {"unfinished_intents": list(self.unfinished_intents),
                            "unresolved_positions": [p["fill_seq"] for p in self.positions],
                            "exit_exhausted_positions": [p["fill_seq"] for p in self.positions if p["exit_exhausted"]]}

    def _check_fee(self, seq, block, contracts, side):
        sched: FeeSchedule | None = self.fee_schedules.get(block.get("schedule_id")) if isinstance(block, dict) else None
        if sched is None:
            if not isinstance(block, dict) or block.get("total") is None:
                self.problems.append("FEES_UNKNOWN seq %d (%s)" % (seq, side))
            return
        for p in recompute_fees(block, sched, contracts=int(contracts), side=side):
            self.problems.append("seq %d: %s" % (seq, p))

    # ------------------------------------------------------------ kernel inputs
    def risk_inputs(self, *, symbol: str) -> dict:
        fam = beta_family(symbol)
        def planned(pred):
            return round(sum(p["debit"] for p in self.positions if pred(p["symbol"]))
                         + sum(float(x["envelope_debit"] or 0.0) for x in self.reservations if pred(x["symbol"])), 2)
        open_risk = planned(lambda s: True)
        return {"open_risk": open_risk,
                "same_underlying_risk": planned(lambda s: s == symbol),
                "same_family_risk": planned(lambda s: beta_family(s) == fam) if fam != "UNKNOWN" else 0.0,
                "session_realized_pnl": self.session_realized_pnl,
                "available_capital": round(self.cash - self.reserved, 2),
                "open_certified_risk": open_risk,
                "beta_family": fam}

    def summary(self) -> dict:
        return {"session_id": self.session_id, "cash": self.cash, "reserved": self.reserved, "open_cost": self.open_cost,
                "session_realized_pnl": self.session_realized_pnl, "total_realized_pnl": self.total_realized_pnl,
                "n_reservations": len(self.reservations), "n_positions": len(self.positions), "n_closed": len(self.closed),
                "outstanding": self.outstanding, "fees_unknown": self.fees_unknown, "integrity_problems": list(self.problems),
                "cash_identity": self.cash_identity()}

    def state_hash(self) -> str:
        s = self.summary()
        return canonical_hash({k: s[k] for k in ("cash", "reserved", "open_cost", "session_realized_pnl", "n_reservations",
                                                  "n_positions", "n_closed")})

    def cash_identity(self) -> dict:
        """starting + sum(cashflows) == cash; and cash == starting - open_cost - fees_paid + realized_pnl_total (when fees known)."""
        fees_paid = 0.0
        for p in self.positions + self.closed:
            fees_paid += (p.get("fees_entry") or 0.0)
        for p in self.closed:
            fees_paid += (p.get("fees_exit") or 0.0)
        open_positions_fees = sum((p.get("fees_entry") or 0.0) for p in self.positions)
        rhs = round(STARTING_PAPER_CAPITAL - self.open_cost - open_positions_fees + self.total_realized_pnl, 2)
        return {"lhs_cash": self.cash, "rhs": rhs, "holds": (not self.fees_unknown) and abs(self.cash - rhs) < 0.005,
                "formula": "cash == start - open_cost - open_entry_fees + total_realized_pnl (realized already net of both fees)"}


def load_book(ledger, *, session_id: str | None, fee_schedules: dict | None = None, rows: list | None = None) -> Book:
    return Book(L.read_all(ledger) if rows is None else rows, session_id=session_id, fee_schedules=fee_schedules)
