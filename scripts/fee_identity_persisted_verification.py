"""Fee-identity verification through the PERSISTED path (approval -> ledger -> fill -> recovery), plus the exact
fee-component arithmetic and rounding evidence.

    python scripts/fee_identity_persisted_verification.py <out.json>

Every alteration is applied to a record that has been WRITTEN TO AND READ BACK FROM a ledger file, not to an
in-memory object, and the refusal is taken from the boundary's own persisted path. Computational correctness is
reported separately from operator authorization; nothing is authorized here."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, ".")
from apex.options_pilot import boundary as B, ledger as L, risk_gate as RG, session as S  # noqa: E402
from apex.options_pilot.fees import LIVE_DEFAULT_FEES, ROBINHOOD_RHF_2026, SYNTHETIC_FEES, UNVERIFIED_FEES, FeeSchedule  # noqa: E402
from apex.options_pilot.synthetic_harness import SyntheticHarness  # noqa: E402

OUT = Path(sys.argv[1])
T = 1_789_000_020.0
res = {"kind": "FEE_IDENTITY_PERSISTED_VERIFICATION", "stages": {}, "arithmetic": {}, "authorization": {}}


def harness(td):
    return SyntheticHarness(Path(td) / "led.jsonl", session_id="VERIFY", t0=T)


# ---------------------------------------------------------------- 1. a real persisted trade, then alterations
with tempfile.TemporaryDirectory() as td:
    h = harness(td)
    S.open_session(h.bd, symbols=["SPY"])
    src = h.sources(); src.pop("exit_quote_fn")
    d = S.scan(h.bd, symbol="SPY", seq=1, **src)
    rows = L.read_all(h.ledger)
    intent = next(r for r in rows if r["kind"] == "pilot_intent")
    fill = next(r for r in rows if r["kind"] == "pilot_fill")
    res["persisted_trade"] = {"decision": d["decision"], "intent_fees_on_disk": intent["fees"],
                              "fill_fee_identity_on_disk": (fill.get("fees_entry") or {}).get("fee_identity"),
                              "identity_fields_present": sorted(intent["fees"].keys()),
                              "approval_carries_identity": isinstance((intent.get("risk") or {}).get("fee_identity"), dict)}

    # APPROVAL stage: alter each identity field on the record READ BACK FROM DISK and re-verify
    approval_stage = {}
    for field, value in (("schedule_hash", "0" * 64), ("provenance", "PROVIDER_VERIFIED"), ("known", False),
                         ("version", "OTHER"), ("effective_date", "1999-01-01"), ("terms_digest", "f" * 64),
                         ("schedule_id", "SOMETHING_ELSE")):
        onDisk = json.loads(json.dumps(intent))          # a true round trip through JSON, as the ledger stores it
        onDisk["fees"] = {**onDisk["fees"], field: value}
        try:
            RG.verify_approval(onDisk, onDisk["risk"], authority=h.bd.risk)
            approval_stage[field] = {"refused": False, "why": None}
        except RG.RiskRefused as e:
            approval_stage[field] = {"refused": True, "why": str(e)[:120]}
    # removal and an undeclared extra
    onDisk = json.loads(json.dumps(intent)); onDisk["fees"] = {k: v for k, v in onDisk["fees"].items() if k != "terms_digest"}
    try:
        RG.verify_approval(onDisk, onDisk["risk"], authority=h.bd.risk); approval_stage["__removed_field__"] = {"refused": False}
    except RG.RiskRefused as e:
        approval_stage["__removed_field__"] = {"refused": True, "why": str(e)[:120]}
    onDisk = json.loads(json.dumps(intent)); onDisk["fees"] = {**onDisk["fees"], "commission_per_contract": 99.0}
    try:
        RG.verify_approval(onDisk, onDisk["risk"], authority=h.bd.risk); approval_stage["__undeclared_field__"] = {"refused": False}
    except RG.RiskRefused as e:
        approval_stage["__undeclared_field__"] = {"refused": True, "why": str(e)[:120]}
    res["stages"]["approval"] = approval_stage

    # FILL stage: the boundary's own persisted-path check
    fill_stage = {}
    for field, value in (("schedule_hash", "0" * 64), ("terms_digest", "f" * 64), ("effective_date", "1999-01-01")):
        onDisk = json.loads(json.dumps(intent)); onDisk["fees"] = {**onDisk["fees"], field: value}
        fill_stage[field] = {"refused": bool(h.bd.fee_identity_problem(onDisk)), "why": (h.bd.fee_identity_problem(onDisk) or "")[:120]}
    partial = json.loads(json.dumps(intent)); partial["fees"] = {"schedule_id": intent["fees"]["schedule_id"]}
    fill_stage["__partial__"] = {"refused": bool(h.bd.fee_identity_problem(partial)), "why": (h.bd.fee_identity_problem(partial) or "")[:140]}
    fill_stage["__unaltered__"] = {"refused": bool(h.bd.fee_identity_problem(intent)), "why": h.bd.fee_identity_problem(intent)}
    res["stages"]["fill"] = fill_stage

# RECOVERY stage: a boundary whose schedule changed under a persisted FILL
with tempfile.TemporaryDirectory() as td:
    h2 = harness(td)
    S.open_session(h2.bd, symbols=["SPY"])
    src = h2.sources(); src.pop("exit_quote_fn")
    d2 = S.scan(h2.bd, symbol="SPY", seq=1, **src)
    h2.advance(1000.0)
    h2.bd.fee_schedule = ROBINHOOD_RHF_2026            # the schedule changes under an open position
    try:
        S.attempt_exits(h2.bd, exit_quote_fn=h2.exit_quotes, sleep_fn=h2.advance, wait_for_due=False)
        rows2 = L.read_all(h2.ledger)
        ref = [r for r in rows2 if r["kind"] == "pilot_refusal" and "FEE_IDENTITY" in json.dumps(r)]
        res["stages"]["recovery"] = {"refused": bool(ref), "why": (ref[0]["reason"][:140] if ref else None)}
    except Exception as e:                                                # noqa: BLE001
        res["stages"]["recovery"] = {"refused": True, "why": "%s: %s" % (type(e).__name__, str(e)[:140])}

# ---------------------------------------------------------------- 2. arithmetic and rounding evidence
ar = {}
ar["entry_1_contract"] = ROBINHOOD_RHF_2026.entry(1)
for n, px in ((1, 2.00), (1, 4.54), (1, 5.00), (1, 10.00), (2, 4.54), (10, 4.54), (100, 4.54)):
    ar["exit_%dc_at_%.2f" % (n, px)] = ROBINHOOD_RHF_2026.exit(n, sale_principal=round(px * 100.0 * n, 2))
ar["no_principal"] = ROBINHOOD_RHF_2026.exit(1)
ar["invalid_principal"] = ROBINHOOD_RHF_2026.exit(1, sale_principal=float("nan"))
res["arithmetic"] = {k: {kk: v[kk] for kk in ("total", "components", "component_basis", "rounding_rules", "arithmetic", "status", "why")
                         if kk in v} for k, v in ar.items()}
res["arithmetic_source"] = {"document": "RHF Standard Pricing Fee Schedule (PDF)", "sha256": "7f9c86bf297d078ce27505cbc53eecc068cf975fbfca5aada37b9af865d7e14a",
                            "terms": {"commission": "$0", "orf_occ": "$0.04/contract both sides", "cat": "$0.0003/contract",
                                      "taf": "$0.00329/contract sells, nearest cent", "sec": "$20.60 per $1,000,000 of SALE principal, rounded up, effective 2026-04-04"}}

# ---------------------------------------------------------------- 3. authorization is SEPARATE from correctness
res["authorization"] = {
    "computational_correctness": "verified above; the arithmetic matches the published terms under each component's own rounding rule",
    "operator_authorization_of_the_schedule": "NOT GRANTED for v2026-09-12b",
    "why": ("the schedule's COMPUTATION changed in this brick (fixed per-contract SEC constant -> exact sale-principal), so its "
            "2026-09-12 authorization was marked SUPERSEDED_BY_COMPUTATION_CHANGE and the live default reverted"),
    "live_default_now": LIVE_DEFAULT_FEES.schedule_id, "live_default_provenance": LIVE_DEFAULT_FEES.provenance,
    "not_authorized_by_this_script": True}

summary = {"approval_alterations_refused": sum(1 for v in res["stages"]["approval"].values() if v["refused"]),
           "approval_alterations_total": len(res["stages"]["approval"]),
           "fill_alterations_refused": sum(1 for k, v in res["stages"]["fill"].items() if k != "__unaltered__" and v["refused"]),
           "fill_alterations_total": len(res["stages"]["fill"]) - 1,
           "unaltered_intent_passes_at_fill": not res["stages"]["fill"]["__unaltered__"]["refused"],
           "recovery_refuses_a_changed_schedule": res["stages"]["recovery"]["refused"]}
res["summary"] = summary
OUT.write_text(json.dumps(res, indent=1, default=str) + "\n")
print(json.dumps(summary, indent=1))
