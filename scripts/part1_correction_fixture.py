"""PART 1 CORRECTION (D): re-run the reconstruction against a CORRECTED FIXTURE, never against the burned record.

    python scripts/part1_correction_fixture.py <burned_ledger.jsonl> <out_dir>

The burned Part 1 ledger is immutable evidence and is not touched. This builds a SEPARATE corrected fixture by
re-deriving the two figures the repairs change — the exit fee (now from the actual sale principal) and the net
result (now null whenever a fee is unknown) — and runs the independent reconstruction against it, plus a NEGATIVE
test proving an unknown fee cannot produce a realized net P&L."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, ".")
from apex.options_pilot.book import Book  # noqa: E402
from apex.options_pilot.fees import ROBINHOOD_RHF_2026  # noqa: E402

UNKNOWN_FEE = {"schedule_id": "UNVERIFIED", "total": None, "status": "UNKNOWN", "why": "an unknown cost is not zero"}


def main() -> int:
    burned, out = Path(sys.argv[1]), Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    rows = [json.loads(l) for l in burned.read_text().splitlines() if l.strip()]
    fill = next(r for r in rows if r["kind"] == "pilot_fill" and r.get("status") == "FILLED")
    outcome = next(r for r in rows if r["kind"] == "pilot_outcome" and r.get("status") == "RESOLVED")
    q = int(fill.get("quantity_filled", 1))
    sale_principal = round(outcome["exit_price"] * 100.0 * q, 2)
    fee_in = ROBINHOOD_RHF_2026.entry(q)
    fee_out_exact = ROBINHOOD_RHF_2026.exit(q, sale_principal=sale_principal)
    debit, credit = fill["net_debit"], round(outcome["exit_price"] * 100.0 * q, 2)

    def book_for(fe, fx):
        return Book([
            {"kind": "pilot_intent", "intent_id": "I1", "session_id": "S", "contract": fill["contract"], "contract_id": fill["contract_id"],
             "quantity": q, "risk_envelope": {"envelope_debit": 500.0, "max_entry_price": 5.0, "feasible": True}, "expiry_epoch": 2e9,
             "risk": {"approved": True}},
            {"kind": "pilot_fill", "status": "FILLED", "intent_id": "I1", "fill_id": "F1", "session_id": "S", "contract": fill["contract"],
             "price": fill["price"], "quantity_filled": q, "net_debit": debit, "fees_entry": fe, "intent_ref": {"seq": 1, "intent_id": "I1"},
             "committed_epoch": 1.0},
            {"kind": "pilot_outcome", "status": "RESOLVED", "intent_id": "I1", "exit_price": outcome["exit_price"], "fees_exit": fx,
             "fill_ref": {"seq": 2}, "discharges_position": True},
        ], session_id="S", fee_schedules={ROBINHOOD_RHF_2026.schedule_id: ROBINHOOD_RHF_2026})

    corrected = book_for(fee_in, fee_out_exact).closed[0]
    unknown = book_for(fee_in, UNKNOWN_FEE).closed[0]
    rec = {
        "kind": "PART1_CORRECTION", "burned_ledger": str(burned), "burned_record_untouched": True,
        "trade": {"contract": fill["contract_id"], "entry_ask": fill["price"], "exit_bid": outcome["exit_price"], "contracts": q},
        "as_burned": {"figures_reported": ["-36.00 (first run)", "-36.10 (second run)"],
                      "root_cause": ("the two runs used DIFFERENT fee schedules, not different arithmetic on the same one. Run 1's "
                                     "boundary defaulted to UNVERIFIED because the driver passed the authorized schedule only to the "
                                     "risk authority (finding A), so both fee totals were None and the Book's (fee or 0.0) turned them "
                                     "into 0.00 (finding B): -36.00 is the GROSS figure. Run 2's boundary carried the schedule, so the "
                                     "fees were real: -36.10. Under the repairs run 1 would produce NO net figure at all."),
                      "what_was_wrong_with_each": {"-36.00": "a GROSS result labelled as a realized net; producible only because of finding B",
                                                   "-36.10": "net, but with the SEC component taken from a fixed per-contract constant (finding C)"}},
        "corrected": {"gross_pnl": corrected["gross_pnl"], "fees_entry": corrected["fees_entry"], "fees_exit": corrected["fees_exit"],
                      "sale_principal": sale_principal, "sec_component": (fee_out_exact.get("component_basis") or {}).get("sec_component"),
                      "realized_pnl": corrected["realized_pnl"], "net_status": corrected["net_status"],
                      "is_gross_only_or_net_estimable": "NET_ESTIMABLE: both fee sides are known under ROBINHOOD_RHF_2026 v2026-09-12b"},
        "negative_test_unknown_fee_cannot_produce_a_net": {
            "realized_pnl": unknown["realized_pnl"], "net_status": unknown["net_status"], "gross_pnl": unknown["gross_pnl"],
            "passes": unknown["realized_pnl"] is None and unknown["net_status"] == "NOT_ESTIMABLE_FEES"},
        "status_of_the_run": ["REPLAY", "QUARANTINED", "NOT_PROSPECTIVE_EVIDENCE", "NOT_A_MODEL_PERFORMANCE_RESULT",
                              "NOT_ELIGIBLE_FOR_LEARNING_OR_PROMOTION", "MECHANISM_VALIDATION_ONLY"],
        "caveat": ("the corrected figure is priced under a schedule that RETURNED TO CANDIDATE in this brick (its computation "
                   "changed); it is an arithmetic correction, not an authorized economic result"),
    }
    (out / "part1_correction.json").write_text(json.dumps(rec, indent=1, default=str) + "\n")
    print(json.dumps({k: rec[k] for k in ("corrected", "negative_test_unknown_fee_cannot_produce_a_net")}, indent=1, default=str))
    return 0 if rec["negative_test_unknown_fee_cannot_produce_a_net"]["passes"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
