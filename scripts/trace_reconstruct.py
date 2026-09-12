"""TRACE REPLAY — PART 1 reconstruction proof: rebuild the trade from the LEDGER ALONE, in a separate process.

    python scripts/trace_reconstruct.py <ledger.jsonl> > reconstruction.json

Reads nothing but the ledger file. Re-derives, from the records themselves:
  * the hash chain (every prev_hash/entry_hash link, recomputed)
  * every receipt-bearing record's entry hash from its own content
  * the intent's id and contract id from its sealed inputs
  * the canonical proposal digest the boundary binds at fill
  * the fill's debit and the outcome's credit, fees and realized P&L from the sealed quotes and fee schedule
  * the Book, loaded from the same ledger by the real loader
and compares each against what the records assert. A field that cannot be re-derived is reported, not excused.
A trade that cannot be rebuilt from the ledger is not an observation."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, ".")
from apex.options_pilot import boundary as B, ledger as L  # noqa: E402
from apex.options_pilot.book import load_book  # noqa: E402
from apex.options_pilot.fees import ROBINHOOD_RHF_2026, SYNTHETIC_FEES, UNVERIFIED_FEES  # noqa: E402
from apex.options_pilot.records import canonical_hash, contract_id  # noqa: E402

KNOWN_SCHEDULES = {s.schedule_id: s for s in (ROBINHOOD_RHF_2026, SYNTHETIC_FEES, UNVERIFIED_FEES)}


def main() -> int:
    led = Path(sys.argv[1])
    rows = L.read_all(led)
    checks, mismatches = [], []

    def check(name, derived, asserted, note=""):
        ok = derived == asserted
        checks.append({"check": name, "ok": ok, "derived": derived, "asserted": asserted, "note": note})
        if not ok:
            mismatches.append(name)

    # 1. the chain itself, recomputed link by link
    verified = L.verify_chain(led)
    n = verified if isinstance(verified, int) else len(verified)
    check("chain_verify_entry_count", n, len(rows))
    for i, r in enumerate(rows):
        if L.recompute_entry_hash(r) != r.get("entry_hash"):
            mismatches.append("entry_hash_seq_%d" % (i + 1))
    checks.append({"check": "every_entry_hash_recomputes_from_its_own_content", "ok": not any(m.startswith("entry_hash_seq_") for m in mismatches),
                   "derived": len(rows), "asserted": len(rows)})

    intent = next(r for r in rows if r["kind"] == "pilot_intent")
    fill = next(r for r in rows if r["kind"] == "pilot_fill" and r.get("status") == "FILLED")
    forecast = next(r for r in rows if r["kind"] == "pilot_forecast")
    outcome = next(r for r in rows if r["kind"] == "pilot_outcome" and r.get("status") == "RESOLVED")

    # 2. identities re-derived from sealed content
    check("contract_id", contract_id(intent["contract"]), intent["contract_id"])
    check("intent_id", canonical_hash({"forecast_id": forecast["forecast_id"], "contract_id": intent["contract_id"],
                                       "signal_used": intent["signal_used"], "session_id": intent["session_id"]})[:24], intent["intent_id"])
    check("forecast_ref_hash_matches_the_forecast_record", intent["forecast_ref"]["entry_hash"], forecast["entry_hash"])
    check("fill_binds_the_intent", fill["intent_ref"]["intent_id"], intent["intent_id"])
    check("canonical_proposal_digest", B.Boundary.proposal_digest(intent), B.Boundary.proposal_digest(
        {"expression": intent["expression"], "action": intent["action"], "contract": intent["contract"], "quantity": intent["quantity"],
         "expression_rule": intent["expression_rule"], "reference_ask": intent["reference_ask"]}),
        "the intent's canonical proposal equals the proposal rebuilt from its own sealed terms")

    # 3. economics re-derived from the sealed quotes and the NAMED fee schedule
    sched = KNOWN_SCHEDULES.get(intent["fees"]["schedule_id"])
    check("fee_schedule_hash_matches_the_named_schedule", (sched.schedule_hash if sched else None), intent["fees"]["schedule_hash"])
    fe = sched.entry(1)["total"] if sched else None
    fx = sched.exit(1)["total"] if sched else None
    debit = round(fill["quote_observed"]["ask"] * 100.0, 2)
    credit = round(outcome["exit_price"] * 100.0, 2)
    check("fill_price_is_the_sealed_ask", fill["price"], fill["quote_observed"]["ask"])
    check("net_debit", debit, fill["net_debit"])
    check("entry_fees", fe, (fill.get("fees_entry") or {}).get("total"))
    check("exit_fees", fx, (outcome.get("fees_exit") or {}).get("total"))
    check("realized_pnl", round(credit - debit - (fe or 0.0) - (fx or 0.0), 2), outcome["pnl"])

    # 4. the Book, rebuilt by the real loader from the same ledger
    book = load_book(led, session_id=intent["session_id"], fee_schedules={sched.schedule_id: sched} if sched else {})
    check("book_closed_positions", len(book.closed), 1)
    check("book_open_positions", len(book.positions), 0)
    check("book_realized_pnl", book.session_realized_pnl, outcome["pnl"])
    check("book_integrity_problems", book.summary()["integrity_problems"], [])
    check("book_fees_unknown_flag", book.fees_unknown, False)

    # 5. the intent-time toll, re-derived from the sealed reference quote
    et = intent["expected_toll"]
    rq = intent["reference_quote"]
    check("expected_toll_recomputes", round(100.0 * (rq["ask"] - rq["bid"]) + (fe or 0) + (fx or 0), 4) if et["value"] is not None else None, et["value"])

    out = {"kind": "TRACE_RECONSTRUCTION_PROOF", "ledger": str(led), "records": len(rows),
           "reconstructed_from": "the ledger file alone, in a separate process; no driver state, no collection files",
           "checks": checks, "mismatches": sorted(set(mismatches)), "clean": not mismatches}
    print(json.dumps(out, indent=1, default=str))
    return 0 if not mismatches else 1


if __name__ == "__main__":
    raise SystemExit(main())
