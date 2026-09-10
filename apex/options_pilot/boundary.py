"""THE FORECAST-AND-INTENT RECORDING BOUNDARY.

Enforced order, proven by ledger sequence numbers (assigned on append and
re-read from disk), never by caller-supplied timestamps or hash-shaped strings:

    1. persist FORECAST            -> receipt
    2. persist risk-approved INTENT that references the forecast receipt
    3. obtain the EXECUTION QUOTE only after step 2 has been verified on disk
    4. simulate the FILL (one contract, filled or unfilled) -> receipt
    5. append the OUTCOME referencing the fill receipt

Every refusal is itself a persisted record. Failed persistence prevents entry.
Unknown, altered or mismatched references refuse. A second delivery of the same
intent cannot fill twice: the fill step scans the ledger for an existing fill of
that intent before it does anything.

This boundary does NOT trust `paper_execution.simulate_entry`'s own check,
which accepts any string of 32+ characters: the card is verified HERE by
re-reading the persisted intent and comparing hashes and contract identity."""
from __future__ import annotations

import time

from apex.predators.options import paper_execution as PE
from . import ledger as L
from .records import (LABELS, RecordRefused, assert_prospective, contract_id, validate_contract,
                      validate_forecast, validate_intent)

MAX_SELECTED_QUOTE_AGE_S = 15.0      # per selected contract AND side, not "newest anywhere in the chain"
CONTRACT_MULTIPLIER = 100.0


class BoundaryRefused(RuntimeError):
    """Refused at the boundary; the refusal has been persisted when possible."""


def _now_utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _refuse(ledger, stage: str, reason: str, *, refs: dict | None = None) -> None:
    """Persist the refusal if the ledger will take it, then raise. A refusal
    that cannot be persisted still raises: nothing proceeds on a dead ledger."""
    rec = {"kind": "pilot_refusal", "stage": stage, "reason": reason, "refs": refs or {},
           "refused_utc": _now_utc(), **LABELS}
    try:
        L.append_with_receipt(ledger, rec)
    except L.LedgerRefused:
        pass
    raise BoundaryRefused("%s: %s" % (stage, reason))


# ---------------------------------------------------------------- 1. forecast

def record_forecast(ledger, forecast: dict) -> dict:
    try:
        body = validate_forecast(forecast)
    except RecordRefused as e:
        _refuse(ledger, "forecast", str(e))
    assert_prospective(body)
    try:
        receipt = L.append_with_receipt(ledger, body)
    except L.LedgerRefused as e:
        _refuse(ledger, "forecast", str(e))
    receipt["forecast_hash"] = body["forecast_hash"]
    return receipt


# ---------------------------------------------------------------- 2. intent

def record_intent(ledger, *, forecast_receipt: dict, intent: dict) -> dict:
    """The forecast must be on disk, intact, unconsumed, and the intent's
    forecast_hash must match it. Risk approval is REQUIRED on the intent."""
    try:
        fr = L.verify_receipt(ledger, forecast_receipt, expected_kind="pilot_forecast")
    except L.LedgerRefused as e:
        _refuse(ledger, "intent", "FORECAST_REF_%s" % str(e), refs={"forecast_receipt": forecast_receipt})
    if fr.get("forecast_hash") != forecast_receipt.get("forecast_hash"):
        _refuse(ledger, "intent", "FORECAST_HASH_MISMATCH: receipt %r vs disk %r"
                % (str(forecast_receipt.get("forecast_hash"))[:12], str(fr.get("forecast_hash"))[:12]))
    consumed = L.find(ledger, kind="pilot_intent",
                      where=lambda r: (r.get("forecast_ref") or {}).get("seq") == forecast_receipt["seq"])
    if consumed:
        _refuse(ledger, "intent", "FORECAST_ALREADY_CONSUMED: by intent seq %d" % consumed[0][0],
                refs={"forecast_seq": forecast_receipt["seq"]})
    if intent.get("contract", {}).get("symbol") != fr.get("symbol"):
        _refuse(ledger, "intent", "INTENT_SYMBOL_MISMATCH: contract %r vs forecast %r"
                % (intent.get("contract", {}).get("symbol"), fr.get("symbol")))
    try:
        body = validate_intent(intent, forecast_receipt=forecast_receipt)
    except RecordRefused as e:
        _refuse(ledger, "intent", str(e))
    body["created_utc"] = _now_utc()
    assert_prospective(body)
    try:
        receipt = L.append_with_receipt(ledger, body)
    except L.LedgerRefused as e:
        _refuse(ledger, "intent", str(e))
    receipt["contract_id"] = body["contract_id"]
    return receipt


# ---------------------------------------------------------------- 3+4. quote then fill

def _quote_ok(q: dict, *, contract: dict, side: str, now_epoch: float) -> str | None:
    """Freshness and identity for the SELECTED contract and the side that
    will be crossed. Returns a refusal reason or None."""
    if not isinstance(q, dict):
        return "QUOTE_NOT_A_RECORD"
    try:
        qc = validate_contract({k: q.get(k) for k in ("symbol", "expiration", "strike", "right")})
    except RecordRefused as e:
        return "QUOTE_CONTRACT_INVALID: %s" % e
    if contract_id(qc) != contract_id(contract):
        return "CONTRACT_MISMATCH: quote is for %s, intent is for %s" % (contract_id(qc), contract_id(contract))
    px = q.get("ask" if side == "ASK" else "bid")
    sz = q.get("ask_size" if side == "ASK" else "bid_size")
    ts = q.get("timestamp_epoch")
    if not isinstance(px, (int, float)) or not px > 0:
        return "QUOTE_SIDE_MISSING: %s=%r" % (side, px)
    if not isinstance(ts, (int, float)):
        return "QUOTE_TIMESTAMP_MISSING"
    age = now_epoch - ts
    if age < 0:
        return "QUOTE_FROM_THE_FUTURE: age %.1fs" % age
    if age > MAX_SELECTED_QUOTE_AGE_S:
        return "STALE_SELECTED_CONTRACT: %s side %.1fs old > %.0fs" % (side, age, MAX_SELECTED_QUOTE_AGE_S)
    if not isinstance(sz, (int, float)) or sz < 0:
        return "QUOTE_SIZE_MISSING: %s_size=%r" % (side.lower(), sz)
    return None


def execute_intent(ledger, *, intent_receipt: dict, quote_fn, now_epoch: float) -> dict:
    """Verify the persisted intent, THEN obtain the quote, THEN fill once.

    `quote_fn(contract) -> quote dict` is called only after the intent is
    proven on disk, so the execution quote is necessarily later than the
    intent in ledger order. A prior fill for this intent refuses."""
    try:
        it = L.verify_receipt(ledger, intent_receipt, expected_kind="pilot_intent")
    except L.LedgerRefused as e:
        _refuse(ledger, "fill", "INTENT_REF_%s" % str(e), refs={"intent_receipt": intent_receipt})
    if it.get("contract_id") != intent_receipt.get("contract_id"):
        _refuse(ledger, "fill", "INTENT_CONTRACT_MISMATCH: disk %r vs receipt %r"
                % (it.get("contract_id"), intent_receipt.get("contract_id")))
    if not (isinstance(it.get("risk"), dict) and it["risk"].get("approved") is True):
        _refuse(ledger, "fill", "INTENT_NOT_RISK_APPROVED_ON_DISK")
    prior = L.find(ledger, kind="pilot_fill",
                   where=lambda r: (r.get("intent_ref") or {}).get("seq") == intent_receipt["seq"])
    if prior:
        _refuse(ledger, "fill", "DUPLICATE_DELIVERY: intent seq %d already has fill seq %d"
                % (intent_receipt["seq"], prior[0][0]), refs={"intent_seq": intent_receipt["seq"]})
    contract = it["contract"]
    side = "ASK"                                       # the pilot rule only BUYs
    quote = quote_fn(contract)                         # obtained strictly AFTER verification
    why = _quote_ok(quote, contract=contract, side=side, now_epoch=now_epoch)
    fill = {"kind": "pilot_fill", "intent_ref": {"seq": intent_receipt["seq"], "entry_hash": intent_receipt["entry_hash"]},
            "contract": contract, "contract_id": it["contract_id"], "quantity_intended": 1,
            "quote_observed": {k: quote.get(k) for k in ("bid", "ask", "bid_size", "ask_size", "timestamp_epoch")}
            if isinstance(quote, dict) else None,
            "filled_utc": _now_utc(), **LABELS}
    if why is not None:
        fill.update(status="UNFILLED", why=why, quantity_filled=0, net_debit=0.0)
    else:
        size = quote.get("ask_size")
        if size is not None and size < 1:
            fill.update(status="UNFILLED", why="NO_SIZE_AT_ASK", quantity_filled=0, net_debit=0.0)
        else:
            px = float(quote["ask"])
            fill.update(status="FILLED", quantity_filled=1, side_crossed="ASK", price=px,
                        net_debit=round(px * CONTRACT_MULTIPLIER, 2),
                        fill_law="long leg pays THAT contract's ASK; no midpoint, no model price",
                        seal_verification="intent re-read from disk and hash-verified by the boundary; "
                                          "simulate_entry's own 32-char check is NOT relied upon")
    assert_prospective(fill)
    try:
        receipt = L.append_with_receipt(ledger, fill)
    except L.LedgerRefused as e:
        _refuse(ledger, "fill", str(e))
    receipt["status"] = fill["status"]
    return receipt


# ---------------------------------------------------------------- 5. outcome

def record_outcome(ledger, *, fill_receipt: dict, exit_quote: dict | None, now_epoch: float) -> dict:
    try:
        fl = L.verify_receipt(ledger, fill_receipt, expected_kind="pilot_fill")
    except L.LedgerRefused as e:
        _refuse(ledger, "outcome", "FILL_REF_%s" % str(e), refs={"fill_receipt": fill_receipt})
    prior = L.find(ledger, kind="pilot_outcome",
                   where=lambda r: (r.get("fill_ref") or {}).get("seq") == fill_receipt["seq"])
    if prior:
        _refuse(ledger, "outcome", "DUPLICATE_OUTCOME: fill seq %d already resolved at seq %d"
                % (fill_receipt["seq"], prior[0][0]))
    out = {"kind": "pilot_outcome", "fill_ref": {"seq": fill_receipt["seq"], "entry_hash": fill_receipt["entry_hash"]},
           "contract_id": fl["contract_id"], "resolved_utc": _now_utc(), **LABELS}
    if fl["status"] != "FILLED":
        out.update(status="NO_POSITION", pnl=0.0, why="intent was %s" % fl["status"])
    else:
        why = _quote_ok(exit_quote, contract=fl["contract"], side="BID", now_epoch=now_epoch) if exit_quote else "EXIT_QUOTE_MISSING"
        if why:
            out.update(status="NOT_ESTIMABLE", pnl=None, why=why, exit_law="a long leg exits at THAT contract's BID; missing -> NOT_ESTIMABLE, never imputed")
        else:
            exit_px = float(exit_quote["bid"])
            out.update(status="RESOLVED", exit_side="BID", exit_price=exit_px,
                       pnl=round((exit_px - fl["price"]) * CONTRACT_MULTIPLIER, 2),
                       entry_price=fl["price"], fees="NOT_MODELLED_IN_THIS_BRICK")
    assert_prospective(out)
    try:
        receipt = L.append_with_receipt(ledger, out)
    except L.LedgerRefused as e:
        _refuse(ledger, "outcome", str(e))
    receipt["status"] = out["status"]
    return receipt
