"""Reproducers for the Part 1 review (five named defects + two the review did not name). Run BEFORE and AFTER.

    python scripts/part1_repair_probes.py > docs/evidence/part1_repair_reproductions.json   # before
    python scripts/part1_repair_probes.py > docs/evidence/part1_repair_after.json           # after

`reproduced: true` = the defect is present. Each probe also reports its DOLLAR MAGNITUDE on the Part 1 trade
(entry ask 4.90, exit bid 4.54, 1 contract) and its worst case at the $500 cap. Synthetic/offline only."""
from __future__ import annotations

import json
import math
import subprocess
import sys

sys.path.insert(0, ".")
from apex.options_pilot.book import Book  # noqa: E402
from apex.options_pilot.fees import ROBINHOOD_RHF_2026, UNVERIFIED_FEES  # noqa: E402
from apex.options_pilot.risk_authority import CertifiedRiskAuthority, envelope_for  # noqa: E402

OUT = {"kind": "PART1_REPAIR_REPRODUCTIONS", "trade": "SPY 2026-10-02 774 CALL, entry ask 4.90, exit bid 4.54, 1 contract",
       "head": subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip(), "findings": {}}


def rec(k, reproduced, magnitude_part1, worst_case_at_cap, detail):
    OUT["findings"][k] = {"reproduced": bool(reproduced), "magnitude_on_part1_trade_usd": magnitude_part1,
                          "worst_case_at_500_cap_usd": worst_case_at_cap, "detail": detail}


def _rows(*, fees_entry, fees_exit, envelope_debit=500.0, exit_price=4.54):
    """A minimal ledger: one intent (reservation), one fill, one resolved outcome."""
    return [
        {"kind": "pilot_intent", "seq": 1, "intent_id": "I1", "session_id": "S", "scan_id": "SC", "contract": {"symbol": "SPY", "expiration": "2026-10-02", "strike": 774.0, "right": "CALL"},
         "contract_id": "SPY|2026-10-02|774.0|CALL", "quantity": 1, "risk_envelope": {"envelope_debit": envelope_debit, "max_entry_price": 5.0, "feasible": True},
         "expiry_epoch": 2e9, "risk": {"approved": True}},
        {"kind": "pilot_fill", "seq": 2, "status": "FILLED", "intent_id": "I1", "fill_id": "F1", "session_id": "S",
         "contract": {"symbol": "SPY", "expiration": "2026-10-02", "strike": 774.0, "right": "CALL"}, "price": 4.90, "quantity_filled": 1,
         "net_debit": 490.0, "fees_entry": fees_entry, "intent_ref": {"seq": 1, "intent_id": "I1"}, "committed_epoch": 1.0},
        {"kind": "pilot_outcome", "seq": 3, "status": "RESOLVED", "intent_id": "I1", "exit_price": exit_price, "fees_exit": fees_exit,
         "fill_ref": {"seq": 2}, "discharges_position": True},
    ]


UNKNOWN_FEE = {"schedule_id": "UNVERIFIED", "total": None, "status": "UNKNOWN", "why": "fee schedule UNVERIFIED is UNVERIFIED; an unknown cost is not zero"}
KNOWN_IN, KNOWN_OUT = ROBINHOOD_RHF_2026.entry(1), ROBINHOOD_RHF_2026.exit(1)

# ---------------------------------------------------------------- 1. two fee schedules, approval anyway
try:
    auth = CertifiedRiskAuthority(fee_schedule=ROBINHOOD_RHF_2026, provenance="LIVE_FEED")
    intent = {"expression": "LONG_CALL", "action": "BUY", "quantity": 1, "signal_used": "LONG",
              "contract": {"symbol": "SPY", "expiration": "2026-10-02", "strike": 774.0, "right": "CALL"},
              "contract_id": "SPY|2026-10-02|774.0|CALL", "intent_id": "I1", "session_id": "S", "scan_id": "SC",
              "risk_envelope": envelope_for(reference_ask=4.90, quantity=1),
              # the schedule the BOUNDARY would seal on this very intent: UNVERIFIED
              "fees": {"schedule_id": UNVERIFIED_FEES.schedule_id, "schedule_hash": UNVERIFIED_FEES.schedule_hash,
                       "provenance": UNVERIFIED_FEES.provenance, "known": UNVERIFIED_FEES.known}}
    ap = auth.approve(intent, book=Book([], session_id="S", fee_schedules={}))
    rec("F1_authority_approves_against_a_different_fee_schedule_than_the_record", bool(ap.get("approved")), 0.10, 0.10,
        {"authority_schedule": ROBINHOOD_RHF_2026.schedule_id, "intent_record_schedule": intent["fees"]["schedule_id"],
         "approved": ap.get("approved"), "why": (ap.get("why") or "")[:120],
         "magnitude_note": "the approval itself is not a dollar error; the consequence is that an intent whose own record says the cost is UNKNOWN is admitted, after which every downstream figure is computed with unknown costs (F2/F3). Dollar figure = the fees the record could not state (0.0403 + 0.0636 on the Part 1 trade)."})
except Exception as e:                                                   # noqa: BLE001
    rec("F1_authority_approves_against_a_different_fee_schedule_than_the_record", False, 0.10, 0.10, {"refused": "%s: %s" % (type(e).__name__, str(e)[:140])})

# ---------------------------------------------------------------- 2. P&L through (fee or 0.0)
b = Book(_rows(fees_entry=UNKNOWN_FEE, fees_exit=UNKNOWN_FEE), session_id="S", fee_schedules={})
known = Book(_rows(fees_entry=KNOWN_IN, fees_exit=KNOWN_OUT), session_id="S", fee_schedules={ROBINHOOD_RHF_2026.schedule_id: ROBINHOOD_RHF_2026})
pnl_unknown = b.closed[0].get("realized_pnl") if b.closed else None
pnl_known = known.closed[0].get("realized_pnl") if known.closed else None
rec("F2_book_computes_net_pnl_with_unknown_fees_as_zero", pnl_unknown is not None, abs((pnl_known or 0) - (pnl_unknown or 0)), 0.10,
    {"pnl_with_unknown_fees": pnl_unknown, "pnl_with_known_fees": pnl_known, "fees_unknown_flag": b.fees_unknown,
     "book_line": "book.py:110 pnl = credit - debit - (fee_total or 0.0) - (fx or 0.0)",
     "sharp_point": "book.py:94 records fees_known=False for the same cashflow and line 91/110 discard it",
     "worst_case_note": "bounded by the true fee total, ~$0.10 per round trip at 1 contract under ROBINHOOD_RHF_2026"})

# ---------------------------------------------------------------- 3. reserved capital through (envelope_debit or 0.0)  [RISK PATH]
rows_bad = _rows(fees_entry=KNOWN_IN, fees_exit=KNOWN_OUT, envelope_debit=None)
rows_bad = [r for r in rows_bad if r["kind"] != "pilot_fill" and r["kind"] != "pilot_outcome"]   # an OPEN intent = a live reservation
b3 = Book(rows_bad, session_id="S", fee_schedules={})
ri = b3.risk_inputs(symbol="SPY")
rec("F3_reserved_capital_counts_an_unknown_envelope_debit_as_zero", b3.reserved == 0.0 and len(b3.reservations) == 1, 500.0, 1500.0,
    {"reservations": len(b3.reservations), "reserved": b3.reserved, "risk_inputs_open_risk": ri.get("open_risk"),
     "book_lines": ["book.py:122 self.reserved = sum(float(x['envelope_debit'] or 0.0) ...)",
                    "book.py:143 risk_inputs planned() uses the SAME idiom per symbol/family (NOT named in the review)"],
     "why_it_outranks_f2": "these feed risk_inputs -> risk_kernel open_planned_risk / same_underlying / family caps; an unknown reservation reads as FREE CAPACITY, so the kernel may admit a position it should refuse",
     "worst_case_note": "one unreserved position = up to the $500 per-trade cap of hidden exposure; at the $1,500 aggregate cap, up to 3 positions could be admitted against an apparent 0 reserved"})

# ---------------------------------------------------------------- 4. fixed SEC fee at exit premiums above/below $5
exits = {}
for px in (2.00, 4.54, 5.00, 10.00):
    r = ROBINHOOD_RHF_2026.exit(1, sale_principal=px * 100.0)
    exits["%.2f" % px] = {"schedule_total": r.get("total"),
                          "exact_sec": math.ceil(px * 100.0 * 20.60 / 1e6 * 100.0) / 100.0,
                          "schedule_sec_component": (r.get("component_basis") or {}).get("sec_component")}
err = {k: (None if v["schedule_sec_component"] is None else round(v["schedule_sec_component"] - v["exact_sec"], 4)) for k, v in exits.items()}
rec("F4_sec_fee_is_a_fixed_per_contract_constant_not_sale_principal", any(e is None or abs(e) > 1e-9 for e in err.values()),
    err["4.54"], max((abs(e) for e in err.values() if e is not None), default=None),
    {"per_exit_premium": exits, "error_usd_schedule_minus_exact": err,
     "declared": "fees.py sec_fee_principal_dependence already declares this, bounds it at $0.01 and OVERSTATES cost",
     "direction": "CONSERVATIVE (overstates) for every premium at or below $5.00; at $10.00 the fixed 0.02 UNDERSTATES the exact 0.03 by $0.01 — outside the pilot's cap but not outside the schedule's reach"})

# ---------------------------------------------------------------- 5. the -36.00 / -36.10 report inconsistency
b5_unknown = Book(_rows(fees_entry=UNKNOWN_FEE, fees_exit=UNKNOWN_FEE), session_id="S", fee_schedules={})
b5_known = Book(_rows(fees_entry=KNOWN_IN, fees_exit=KNOWN_OUT), session_id="S", fee_schedules={ROBINHOOD_RHF_2026.schedule_id: ROBINHOOD_RHF_2026})
rec("F5_part1_report_inconsistency_36_00_vs_36_10", b5_unknown.session_realized_pnl != b5_known.session_realized_pnl,
    abs(b5_known.session_realized_pnl - b5_unknown.session_realized_pnl), 0.10,
    {"first_run_pnl": b5_unknown.session_realized_pnl, "second_run_pnl": b5_known.session_realized_pnl,
     "root_cause": ("NOT a rounding or reporting bug: the two runs used DIFFERENT fee schedules. Run 1's boundary defaulted to "
                    "UNVERIFIED (driver defect) so both fee totals were None and F2 turned them into 0.00 -> -36.00 = gross. "
                    "Run 2's boundary carried ROBINHOOD_RHF_2026 -> -36.10 = gross - 0.0403 - 0.0636 rounded. The difference IS "
                    "the fees, and run 1 only produced a number at all because of F2."),
     "correct_figure": "-36.10 net under ROBINHOOD_RHF_2026; -36.00 is the GROSS figure and must never be labelled net"})

# ---------------------------------------------------------------- 6/7. the class, beyond the named instances
import pathlib  # noqa: E402
import re  # noqa: E402
PAT = re.compile(r"\bor 0(?:\.0)?\b(?!\s*#\s*UNKNOWN_TO_ZERO_EXEMPT)")
PATHS = ["apex/options_pilot", "apex/pulse_options", "apex/decision_wb", "apex/organism/risk_certificate.py", "apex/organism/risk_kernel.py"]
hits = []
for p in PATHS:
    pp = pathlib.Path(p)
    for f in ([pp] if pp.is_file() else sorted(pp.rglob("*.py"))):
        for n, line in enumerate(f.read_text().splitlines(), 1):
            if PAT.search(line) and not line.strip().startswith("#"):
                hits.append({"file": str(f), "line": n, "text": line.strip()[:110]})
rec("F6_unknown_to_zero_idiom_is_a_class_not_instances", bool(hits), None, None,
    {"n_occurrences": len(hits), "occurrences": hits,
     "not_named_in_the_review": [h for h in hits if h["file"].endswith("book.py") and h["line"] in (143, 169, 171, 172)]
                                 + [h for h in hits if "risk_certificate" in h["file"] or "experience" in h["file"]]})
from apex.options_pilot.records import canonical_json  # noqa: E402
_nan_ok = True
try:
    canonical_json({"x": float("nan")}); _nan_ok = False
except ValueError:
    pass
rec("F7_strict_json_accepts_nan_and_infinity", not _nan_ok, None, None,
    {"probe": "the RECORD serializer records.canonical_json, not the stdlib default",
     "detail": "canonical_json already used allow_nan=False before this brick; the defect as stated does not exist on the record path",
     "stdlib_note": "bare json.dumps still emits NaN, which is why every record goes through canonical_json"})

print(json.dumps(OUT, indent=1, default=str))
