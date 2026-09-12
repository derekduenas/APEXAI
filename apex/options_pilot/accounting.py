"""PRESERVED UNKNOWN ACCOUNTING (OPERATING-LOOP-001 item 4).

AN UNRESOLVED POSITION OR AN UNKNOWN FEE MUST NOT DISAPPEAR FROM AGGREGATE P&L.

The Book already refuses to invent a net for a single position whose fees are unknown: `realized_pnl` is None and
`net_status` says `NOT_ESTIMABLE_FEES`. The gap this module closes is the AGGREGATE. A summing loop that skips the
Nones -- `sum(p for p in nets if p is not None)` -- turns "we do not know" into a confident number, and that is
exactly what the demonstration's driver reported.

THE RULE.
    total_net_pnl is a NUMBER only when the aggregate is complete: every position closed, every fee known, no exit
    exhausted, no unfinished intent. Otherwise total_net_pnl is None and total_net_status names every missing input.

    KNOWN AMOUNTS ARE STILL REPORTED. `known_realized_pnl` is the sum over positions that DO have a net, and it is
    always accompanied by the counts of what is missing, so it can never be read as the total.

    ZERO IS A RESULT ONLY FOR AN ACTUAL NO-TRADE POLICY. A policy that opened nothing has a total of exactly 0.00 and
    says so with `zero_basis = ACTUAL_NO_TRADE_POLICY`. A zero that arises because the economics are missing is
    refused: it is reported as NOT_ESTIMABLE with reasons.

INDEPENDENT ARITHMETIC. `independent_check` recomputes cash, fees, reservations and P&L from the PRIMARY ledger
fields -- price x multiplier x quantity, fee blocks re-derived from the named schedule -- without consulting the
Book's own aggregates, and reports agreement or disagreement per line. It is a second opinion, not a restatement."""
from __future__ import annotations

from apex.organism.risk_kernel import STARTING_PAPER_CAPITAL

from .book import CONTRACT_MULTIPLIER, Book
from .clock import is_real

NOT_ESTIMABLE = "NOT_ESTIMABLE"
NET = "NET"
ZERO_NO_TRADE = "ACTUAL_NO_TRADE_POLICY"

ACCOUNTING_POLICY = (
    "UNKNOWN_ACCOUNTING_V1: an aggregate net is a number only when every position is closed, every fee is known, no "
    "exit is exhausted and no intent is unfinished. Otherwise the total is null and the reasons are named. Known "
    "realized amounts are always reported alongside the counts of what is missing. Zero is a valid total only for a "
    "policy that actually opened nothing.")


def net_result(book: Book) -> dict:
    """The aggregate, with its unknowns preserved."""
    closed = book.closed
    with_net = [p for p in closed if p.get("realized_pnl") is not None]
    without_net = [p for p in closed if p.get("realized_pnl") is None]
    unresolved = list(book.positions)
    exhausted = [p for p in unresolved if p.get("exit_exhausted")]
    unfinished = list(book.unfinished_intents)
    known = round(sum(p["realized_pnl"] for p in with_net), 2)

    why: list = []
    if without_net:
        why.append("CLOSED_POSITIONS_WITHOUT_A_NET: %d (%s)"
                   % (len(without_net), ", ".join(sorted({p.get("net_status") or "UNKNOWN" for p in without_net}))))
    if unresolved:
        why.append("UNRESOLVED_POSITIONS: %d (fill seqs %s) -- open exposure with no outcome; its economics are unknown"
                   % (len(unresolved), [p["fill_seq"] for p in unresolved]))
    if exhausted:
        why.append("EXIT_EXHAUSTED_POSITIONS: %d (fill seqs %s) -- an explicit unresolved obligation, not a zero"
                   % (len(exhausted), [p["fill_seq"] for p in exhausted]))
    if unfinished:
        why.append("UNFINISHED_INTENTS: %d (ledger seqs %s) -- reserved capacity with no terminal record"
                   % (len(unfinished), unfinished))
    if book.reserved_unknown:
        why.append("RESERVATION_ENVELOPE_UNKNOWN: reserved capital is not a number, so capital usage is unknown")
    if book.fees_unknown:
        why.append("FEES_UNKNOWN: at least one cashflow has an unknown fee, so cash is not a number")

    estimable = not why
    traded = bool(closed) or bool(unresolved)
    out = {
        "policy": ACCOUNTING_POLICY,
        "known_realized_pnl": known,
        "n_closed_with_net": len(with_net),
        "n_closed_net_not_estimable": len(without_net),
        "n_unresolved_positions": len(unresolved),
        "n_exit_exhausted": len(exhausted),
        "n_unfinished_intents": len(unfinished),
        "unresolved_fill_seqs": [p["fill_seq"] for p in unresolved],
        "valuation_status": {str(p["fill_seq"]): {"attempts": p.get("valuation_attempts"),
                                                  "exit_exhausted": bool(p.get("exit_exhausted"))}
                             for p in unresolved},
        "cash": book.cash, "gross_cash": book.gross_cash, "reserved": book.reserved,
        "reserved_unknown": book.reserved_unknown, "fees_unknown": book.fees_unknown,
        "total_net_estimable": estimable,
        "total_net_status": NET if estimable else NOT_ESTIMABLE,
        "total_net_pnl": (known if estimable else None),
        "why_not_estimable": why,
        "zero_basis": None,
    }
    if estimable and not traded:
        out["zero_basis"] = ZERO_NO_TRADE
        out["total_net_pnl"] = 0.0
        out["note"] = ("this policy opened no position, so zero is the actual result and not a stand-in for missing "
                       "economics")
    elif not estimable:
        out["note"] = ("the total is NULL. The known amounts above are a partial account and must not be presented as "
                       "a result; the named reasons are what is missing.")
    return out


def assert_no_phantom_zero(agg: dict) -> None:
    """A zero total must be an actual no-trade result. Any other zero is a missing-economics zero and is refused."""
    if agg.get("total_net_pnl") == 0.0 and agg.get("zero_basis") != ZERO_NO_TRADE:
        if agg.get("n_closed_with_net", 0) == 0:
            raise ValueError("PHANTOM_ZERO_NET: a zero total with no netting trade and no no-trade basis. %r"
                             % (agg.get("why_not_estimable"),))
    if agg.get("total_net_pnl") is not None and not agg.get("total_net_estimable"):
        raise ValueError("NET_REPORTED_WHILE_NOT_ESTIMABLE: %r" % (agg.get("why_not_estimable"),))


def independent_check(rows: list, *, fee_schedules: dict, starting_capital: float = STARTING_PAPER_CAPITAL) -> dict:
    """A SECOND, INDEPENDENT computation of cash, fees, reservations and P&L straight from the ledger's primary
    fields. It does not read the Book's aggregates; the caller compares the two."""
    entry_fees = exit_fees = 0.0
    debits = credits = 0.0
    n_fills = n_exits = 0
    unknown_fee_sides: list = []
    discharged = {(r.get("fill_ref") or {}).get("seq") for r in rows
                  if r.get("kind") == "pilot_outcome" and r.get("discharges_position") is True}
    open_debits = 0.0
    reserved = 0.0
    reserved_unknown = False
    fills_by_intent: dict = {}
    terminal = {r.get("intent_id") for r in rows if r.get("kind") in ("pilot_intent_expired", "pilot_intent_cancelled")}
    for i, r in enumerate(rows):
        if r.get("kind") == "pilot_fill":
            fills_by_intent.setdefault((r.get("intent_ref") or {}).get("seq"), []).append(r)
    for i, r in enumerate(rows):
        seq = i + 1
        if r.get("kind") == "pilot_intent":
            att = fills_by_intent.get(seq, [])
            finished = (r.get("intent_id") in terminal) or any(a.get("status") == "FILLED" or a.get("decision") == "REFUSE"
                                                               for a in att)
            if not finished:
                env = (r.get("risk_envelope") or {}).get("envelope_debit")
                if is_real(env):
                    reserved += float(env)
                else:
                    reserved_unknown = True
        elif r.get("kind") == "pilot_fill" and r.get("status") == "FILLED":
            n_fills += 1
            qty = int(r.get("quantity_filled", 1))
            d = float(r["price"]) * CONTRACT_MULTIPLIER * qty
            debits += d
            if seq not in discharged:
                open_debits += d
            f = (r.get("fees_entry") or {}).get("total")
            if f is None:
                unknown_fee_sides.append({"seq": seq, "side": "BUY"})
            else:
                entry_fees += float(f)
        elif r.get("kind") == "pilot_outcome" and r.get("status") == "RESOLVED" and r.get("discharges_position") is True:
            n_exits += 1
            fs = (r.get("fill_ref") or {}).get("seq")
            qty = int(rows[fs - 1].get("quantity_filled", 1)) if fs and fs <= len(rows) else 1
            credits += float(r["exit_price"]) * CONTRACT_MULTIPLIER * qty
            f = (r.get("fees_exit") or {}).get("total")
            if f is None:
                unknown_fee_sides.append({"seq": seq, "side": "SELL"})
            else:
                exit_fees += float(f)
    fees_known = not unknown_fee_sides
    realized = (round(credits - (debits - open_debits) - exit_fees - _entry_fees_of_closed(rows, discharged), 2)
                if fees_known else None)
    cash = (round(starting_capital - debits - entry_fees + credits - exit_fees, 2) if fees_known else None)
    return {"source": "INDEPENDENT_RECOMPUTATION_FROM_PRIMARY_LEDGER_FIELDS",
            "n_fills": n_fills, "n_resolved_exits": n_exits,
            "gross_debits": round(debits, 2), "gross_credits": round(credits, 2),
            "entry_fees": (round(entry_fees, 2) if fees_known else None),
            "exit_fees": (round(exit_fees, 2) if fees_known else None),
            "open_position_cost": round(open_debits, 2),
            "reserved": (None if reserved_unknown else round(reserved, 2)), "reserved_unknown": reserved_unknown,
            "unknown_fee_sides": unknown_fee_sides, "fees_known": fees_known,
            "realized_pnl_closed": realized, "cash": cash,
            "formula": ("cash = start - sum(price*100*qty) - entry_fees + sum(exit_price*100*qty) - exit_fees; "
                        "realized = credits - closed_debits - closed_entry_fees - exit_fees")}


def _entry_fees_of_closed(rows: list, discharged: set) -> float:
    total = 0.0
    for i, r in enumerate(rows):
        if r.get("kind") == "pilot_fill" and r.get("status") == "FILLED" and (i + 1) in discharged:
            f = (r.get("fees_entry") or {}).get("total")
            if f is not None:
                total += float(f)
    return total


def reconcile(book: Book, rows: list, *, fee_schedules: dict) -> dict:
    """Book aggregates vs the independent recomputation, line by line. Disagreements are listed, never smoothed."""
    ind = independent_check(rows, fee_schedules=fee_schedules)
    agg = net_result(book)
    # The realized line: a closed position whose net is not estimable makes the BOOK side unknown, not smaller. Only
    # a book with no closed position at all has a realized total of exactly zero.
    if not book.closed:
        book_realized = 0.0
    elif agg["n_closed_net_not_estimable"]:
        book_realized = None
    else:
        book_realized = agg["known_realized_pnl"]
    lines = [("cash", book.cash, ind["cash"]),
             ("reserved", book.reserved, ind["reserved"]),
             ("open_position_cost", book.open_cost, ind["open_position_cost"]),
             ("realized_pnl", book_realized, ind["realized_pnl_closed"])]
    problems = []
    checked = []
    for name, a, b in lines:
        if a is None or b is None:
            checked.append({"line": name, "book": a, "independent": b,
                            "agrees": (a is None and b is None), "note": "unknown on at least one side"})
            if not (a is None and b is None):
                problems.append("%s: book %r vs independent %r" % (name, a, b))
            continue
        ok = abs(float(a) - float(b)) < 0.005
        checked.append({"line": name, "book": round(float(a), 2), "independent": round(float(b), 2), "agrees": ok})
        if not ok:
            problems.append("%s: book %.2f vs independent %.2f" % (name, a, b))
    return {"lines": checked, "problems": problems, "agrees": not problems, "aggregate": agg, "independent": ind,
            "book_integrity_problems": list(book.problems)}
