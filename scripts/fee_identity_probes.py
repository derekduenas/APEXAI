"""Reproducers for the RESIDUAL fee-identity gap at 4e8164c. Run BEFORE and AFTER.

    python scripts/fee_identity_probes.py > docs/evidence/fee_identity_reproductions.json

`reproduced: true` = the alteration is NOT caught. The previous brick compared the identity the AUTHORITY holds
against the identity the INTENT carries at approval time; it did not make the identity part of the persisted
CRYPTOGRAPHIC binding, so an identity altered after approval (or an authority swapped under a persisted approval)
still verifies as long as `schedule_id` is unchanged. Offline only; no provider, no service, no burned artifact."""
from __future__ import annotations

import copy
import json
import subprocess
import sys

sys.path.insert(0, ".")
from apex.options_pilot import risk_gate as RG  # noqa: E402
from apex.options_pilot.book import Book  # noqa: E402
from apex.options_pilot.fees import ROBINHOOD_RHF_2026, SYNTHETIC_FEES, UNVERIFIED_FEES, FeeSchedule  # noqa: E402
from apex.options_pilot.risk_authority import CertifiedRiskAuthority, envelope_for  # noqa: E402

OUT = {"kind": "FEE_IDENTITY_REPRODUCTIONS", "at": "residual gap after 4e8164c",
       "head": subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip(), "findings": {}}


def rec(k, reproduced, detail):
    OUT["findings"][k] = {"reproduced": bool(reproduced), "detail": detail}


def fees_block(s: FeeSchedule) -> dict:
    """AFTER the repair this is the COMPLETE canonical identity; BEFORE it, only the four fields the binding used."""
    return s.identity() if hasattr(s, "identity") else {"schedule_id": s.schedule_id, "schedule_hash": s.schedule_hash,
                                                        "provenance": s.provenance, "known": s.known}


def intent_with(fb: dict) -> dict:
    return {"expression": "LONG_CALL", "action": "BUY", "quantity": 1, "signal_used": "LONG",
            "contract": {"symbol": "SPY", "expiration": "2026-10-02", "strike": 774.0, "right": "CALL"},
            "contract_id": "SPY|2026-10-02|774.0|CALL", "intent_id": "I1", "session_id": "S", "scan_id": "SC",
            "risk_envelope": envelope_for(reference_ask=4.90, quantity=1), "fees": fb,
            "data_provenance": "SYNTHETIC_FIXTURE"}


AUTH = CertifiedRiskAuthority(fee_schedule=SYNTHETIC_FEES, provenance="SYNTHETIC_FIXTURE")
GOOD = intent_with(fees_block(SYNTHETIC_FEES))
APPROVAL = AUTH.approve(GOOD, book=Book([], session_id="S", fee_schedules={}))
assert APPROVAL.get("approved"), APPROVAL.get("why")
GOOD["risk"] = RG.verify_approval(GOOD, APPROVAL)

# ---- the persisted approval is re-verified against an ALTERED intent; does the binding notice?
ALTERATIONS = {
    "A1_schedule_hash_altered_id_unchanged": {"schedule_hash": "0" * 64},
    "A2_provenance_altered_id_and_hash_unchanged": {"provenance": "PROVIDER_VERIFIED"},
    "A3_known_status_altered": {"known": False},
    "A4_effective_date_or_version_altered": {"version": "SOMETHING_ELSE", "effective_date": "1999-01-01"},
    "A5_fee_terms_altered": {"commission_per_contract": 99.0, "exchange_fee_per_contract": 99.0},
}
for name, delta in ALTERATIONS.items():
    it = copy.deepcopy(GOOD)
    it["fees"].update(delta)
    caught = None
    try:
        RG.verify_approval(it, it["risk"], authority=AUTH)
    except RG.RiskRefused as e:
        caught = str(e)[:140]
    rec(name, caught is None, {"altered": delta, "refusal": caught,
                               "binding_commits_to": "binding_hash(intent) + max_entry_price + envelope_debit + fee_schedule_id ONLY"})

# ---- A6: the approval's own binding altered while keeping its authority id
it6 = copy.deepcopy(GOOD)
it6["risk"] = {**it6["risk"], "fee_schedule_hash": "0" * 64, "fee_identity": {"schedule_id": SYNTHETIC_FEES.schedule_id, "schedule_hash": "0" * 64}}
caught6 = None
try:
    RG.verify_approval(it6, it6["risk"], authority=AUTH)
except RG.RiskRefused as e:
    caught6 = str(e)[:140]
rec("A6_approval_identity_fields_altered_id_preserved", caught6 is None,
    {"altered": "approval.fee_schedule_hash and approval.fee_identity", "refusal": caught6,
     "note": "verify_approval never reads the approval's own fee identity"})

# ---- A7: the ACTIVE authority swapped for one with the same schedule_id but different terms
SAME_ID_DIFFERENT_TERMS = FeeSchedule(
    schedule_id=SYNTHETIC_FEES.schedule_id, version="TAMPERED", provenance="SYNTHETIC_FIXTURE",
    commission_per_contract=9.99, exchange_fee_per_contract=9.99,
    regulatory_fee_per_contract_buy=9.99, regulatory_fee_per_contract_sell=9.99,
    note="same schedule_id, entirely different terms")
AUTH7 = CertifiedRiskAuthority(fee_schedule=SAME_ID_DIFFERENT_TERMS, provenance="SYNTHETIC_FIXTURE")
caught7 = AUTH7.accepts(APPROVAL)
rec("A7_active_authority_same_id_different_terms_accepts_the_approval", caught7 is None,
    {"accepts_returned": caught7, "authority_compares": "approval['fee_schedule_id'] == self.fee_schedule.schedule_id ONLY",
     "consequence": "a persisted approval is honoured by an authority whose fee terms differ entirely"})

# ---- A8: a filled intent with a PARTIAL identity on disk
rows = [{"kind": "pilot_intent", "intent_id": "I1", "session_id": "S", "contract": GOOD["contract"], "contract_id": GOOD["contract_id"],
         "quantity": 1, "risk_envelope": GOOD["risk_envelope"], "expiry_epoch": 2e9, "risk": {"approved": True},
         "fees": {"schedule_id": SYNTHETIC_FEES.schedule_id}},                      # PARTIAL: id only
        {"kind": "pilot_fill", "status": "FILLED", "intent_id": "I1", "fill_id": "F1", "session_id": "S", "contract": GOOD["contract"],
         "price": 4.90, "quantity_filled": 1, "net_debit": 490.0, "fees_entry": {"schedule_id": SYNTHETIC_FEES.schedule_id, "total": 0.97},
         "intent_ref": {"seq": 1, "intent_id": "I1"}, "committed_epoch": 1.0}]
b = Book(rows, session_id="S", fee_schedules={SYNTHETIC_FEES.schedule_id: SYNTHETIC_FEES})
probs = b.summary()["integrity_problems"]
from apex.options_pilot import boundary as B  # noqa: E402
_named = None
try:
    _bd = B.Boundary.__new__(B.Boundary); _bd.fee_schedule = SYNTHETIC_FEES
    _named = B.Boundary.fee_identity_problem(_bd, rows[0])
except Exception as e:                                                   # noqa: BLE001
    _named = "PROBE_ERROR: %s" % type(e).__name__
rec("A8_filled_intent_with_a_partial_fee_identity_is_not_refused",
    not (_named and "INCOMPLETE" in str(_named)),
    {"boundary_refusal": _named, "book_integrity_problems": probs,
     "expected": "a named integrity refusal at the BOUNDARY naming the incomplete identity, never a fallback"})

# ---- A9: binary floating point in the fee arithmetic
r10 = ROBINHOOD_RHF_2026.exit(10, sale_principal=4540.0)
decimal_declared = r10.get("arithmetic") == "DECIMAL_CENTS"
has_rules = bool(r10.get("rounding_rules"))
rec("A9_fee_arithmetic_is_not_declared_decimal_with_per_component_rounding", not (decimal_declared and has_rules),
    {"arithmetic": r10.get("arithmetic"), "rounding_rules": r10.get("rounding_rules"),
     "requirement": "explicit decimal/integer-cent arithmetic with each component rounded under its own published rule before totalling"})

print(json.dumps(OUT, indent=1, default=str))
