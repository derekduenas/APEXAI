"""OPTIONS-PILOT-001 session orchestration over the recording boundary.

All external inputs are INJECTED so the same orchestration runs unchanged on
synthetic fixtures and, later, on a reviewed live adapter:

    forecast_fn(symbol, as_of_epoch) -> forecast dict (validated by the boundary)
    signal_fn(symbol, as_of_epoch)   -> "LONG" | "SHORT" | None   (heuristic label)
    chain_fn(symbol, as_of_epoch)    -> list of available contracts {expiration, strike, right}
    spot_fn(symbol, as_of_epoch)     -> float
    quote_fn(contract)               -> execution quote, obtained AFTER intent persistence
    exit_quote_fn(contract)          -> exit quote

The clock, provenance, risk authority and session identity live on the
Boundary. One symbol per scan; a scan has a STABLE id
    scan_id = f"{session_id}:{seq:04d}:{symbol}"
and every scan ends in exactly one decision record: TRADE, WAIT or REFUSE.

RESTART: `resume` completes unfinished intents of THIS session once, and
retires everything it may not execute (expired, session closed, other
release, other session, stale authorization) with a terminal record, so a
restart can never execute an old intent indefinitely."""
from __future__ import annotations

from . import boundary as B
from . import ledger as L
from .clock import to_utc_string
from .expression_rule import RuleRefused, choose
from .records import INTENT_TTL_S, assert_prospective

PROTOCOL_ID = "OPTIONS-PILOT-001"


def scan_id_for(session_id: str, seq: int, symbol: str) -> str:
    return "%s:%04d:%s" % (session_id, seq, symbol)


def open_session(bd: B.Boundary, *, symbols: list) -> dict:
    rec = {"kind": "pilot_session_open", "txn_id": "session_open:" + bd.session_id, "session_id": bd.session_id,
           "symbols": list(symbols), "release": bd.release, "protocol": PROTOCOL_ID,
           "opened_utc": bd.clock.now_utc(), "opened_epoch": bd.clock.now(), **bd.labels}
    assert_prospective(rec)
    receipt, _ = L.commit_once(bd.ledger, txn_id=rec["txn_id"], build=lambda rows: rec, kind="pilot_session_open")
    return receipt


def next_seq(ledger, *, session_id: str) -> int:
    """Next scan sequence for a session, derived from the ledger."""
    best = 0
    for r in L.read_all(ledger):
        sid = r.get("scan_id")
        if isinstance(sid, str) and sid.startswith(session_id + ":"):
            try:
                best = max(best, int(sid.split(":")[1]))
            except (IndexError, ValueError):
                continue
    return best + 1


def _decision(bd: B.Boundary, *, scan_id: str, symbol: str, decision: str, why, ids: dict, persisted_refusal=None) -> dict:
    rec = {"kind": "pilot_decision", "txn_id": "decision:" + scan_id, "scan_id": scan_id, "symbol": symbol,
           "session_id": bd.session_id, "release": bd.release, "decision": decision, "why": why,
           "forecast_id": ids.get("forecast_id"), "intent_id": ids.get("intent_id"), "fill_id": ids.get("fill_id"),
           "refusal_persisted": persisted_refusal, "decided_utc": bd.clock.now_utc(), **bd.labels}
    assert_prospective(rec)
    out = {"scan_id": scan_id, "symbol": symbol, "decision": decision, "why": why, **ids, "receipts": ids.get("receipts", {})}
    try:
        receipt, _ = L.commit_once(bd.ledger, txn_id=rec["txn_id"], build=lambda rows: rec, kind="pilot_decision")
        out["decision_receipt"] = receipt
        out["decision_persisted"] = True
    except L.LedgerRefused as e:
        out["decision_persisted"] = False
        out["decision_persist_error"] = str(e)[:200]
    if persisted_refusal is not None:
        out["refusal_persisted"] = persisted_refusal
    return out


def scan(bd: B.Boundary, *, symbol: str, seq: int, forecast_fn, signal_fn, chain_fn, spot_fn, quote_fn) -> dict:
    """One scan: forecast -> intent -> fill, in that order, each a receipt;
    ends in exactly one decision: TRADE / WAIT / REFUSE. A BoundaryRefused
    becomes a REFUSE decision that says whether the refusal was persisted;
    provider exceptions fail closed the same way."""
    scan_id = scan_id_for(bd.session_id, seq, symbol)
    ids: dict = {"receipts": {}}
    prior = [r for r in L.read_all(bd.ledger) if r.get("scan_id") == scan_id]
    if prior:
        return _decision(bd, scan_id=scan_id, symbol=symbol, decision="REFUSE",
                         why="DUPLICATE_SCAN: scan_id already has %d record(s), first kind %r" % (len(prior), prior[0].get("kind")), ids=ids)
    as_of = bd.clock.now()
    try:
        # 1. forecast persisted first, before any quote is consulted
        try:
            forecast = forecast_fn(symbol, as_of)
        except Exception as e:                                             # noqa: BLE001
            bd.refuse("forecast", "FORECAST_PROVIDER_FAILED: %s: %s" % (type(e).__name__, str(e)[:300]), scan_id=scan_id)
        f_receipt = bd.record_forecast(forecast, scan_id=scan_id)
        ids["forecast_id"] = f_receipt["forecast_id"]; ids["receipts"]["forecast"] = f_receipt
        # 2. deterministic rule -> risk-bound intent persisted
        try:
            signal = signal_fn(symbol, as_of)
            proposal = choose(symbol=symbol, direction_signal=signal, spot=spot_fn(symbol, as_of),
                              as_of=to_utc_string(as_of), available=chain_fn(symbol, as_of))
        except RuleRefused as e:
            bd.refuse("rule", str(e), refs={"forecast_seq": f_receipt["seq"]}, scan_id=scan_id)
        except Exception as e:                                             # noqa: BLE001
            bd.refuse("rule", "INPUT_PROVIDER_FAILED: %s: %s" % (type(e).__name__, str(e)[:300]), scan_id=scan_id)
        i_receipt = bd.record_intent(forecast_receipt=f_receipt, intent=proposal, signal_used=signal, scan_id=scan_id)
        ids["intent_id"] = i_receipt["intent_id"]; ids["receipts"]["intent"] = i_receipt
        # 3+4. quote only after the intent is on disk; fill exactly once
        fill_receipt = bd.execute_intent(intent_receipt=i_receipt, quote_fn=quote_fn)
        ids["fill_id"] = fill_receipt["fill_id"]; ids["receipts"]["fill"] = fill_receipt
        return _decision(bd, scan_id=scan_id, symbol=symbol, decision=fill_receipt["decision"], why=fill_receipt.get("why"), ids=ids)
    except B.BoundaryRefused as e:
        return _decision(bd, scan_id=scan_id, symbol=symbol, decision="REFUSE", why=str(e), ids=ids,
                         persisted_refusal=e.persisted)


def resolve(bd: B.Boundary, *, fill_receipt: dict, exit_quote_fn) -> dict:
    return bd.record_outcome(fill_receipt=fill_receipt, exit_quote_fn=exit_quote_fn)


def unfilled_intents(ledger, *, rows: list | None = None) -> list:
    """Intents on disk with no fill and no terminal record referencing them."""
    rows = L.read_all(ledger) if rows is None else rows
    done = set()
    for r in rows:
        if r.get("kind") == "pilot_fill":
            done.add((r.get("intent_ref") or {}).get("seq"))
        if r.get("kind") in ("pilot_intent_expired", "pilot_intent_cancelled"):
            done.add((r.get("intent_ref") or {}).get("seq"))
    return [(i + 1, r) for i, r in enumerate(rows) if r.get("kind") == "pilot_intent" and (i + 1) not in done]


def closed_sessions(rows: list) -> set:
    return {r.get("session_id") for r in rows if r.get("kind") == "pilot_session_close"}


def resume(bd: B.Boundary, *, quote_fn) -> list:
    """After a crash. For every unfinished intent, in ledger order:
        session closed          -> pilot_intent_cancelled (SESSION_CLOSED)
        other release           -> pilot_intent_cancelled (WRONG_RELEASE)
        other session           -> pilot_intent_cancelled (STALE_AUTHORIZATION: not this session's intent)
        risk binding fails      -> pilot_intent_cancelled (STALE_AUTHORIZATION: risk approval does not verify)
        expired                 -> pilot_intent_expired
        else                    -> execute_intent ONCE (idempotent by txn_id)
    Receipts are rebuilt from disk, not from memory. Returns the actions."""
    rows = L.read_all(bd.ledger)
    closed = closed_sessions(rows)
    actions = []
    for seq, rec in unfilled_intents(bd.ledger, rows=rows):
        receipt = {"path": str(bd.ledger), "seq": seq, "entry_hash": rec["entry_hash"], "kind": "pilot_intent",
                   "contract_id": rec.get("contract_id"), "intent_id": rec.get("intent_id"),
                   "receipt": "REBUILT from disk on resume"}
        why = None
        if rec.get("session_id") in closed:
            why = "SESSION_CLOSED: %s" % rec.get("session_id")
        elif rec.get("release") != bd.release:
            why = "WRONG_RELEASE: intent %r, running %r" % (rec.get("release"), bd.release)
        elif rec.get("session_id") != bd.session_id:
            why = "STALE_AUTHORIZATION: intent belongs to session %r, resuming %r" % (rec.get("session_id"), bd.session_id)
        else:
            try:
                B.RG.verify_approval(rec, rec.get("risk"))
            except B.RG.RiskRefused as e:
                why = "STALE_AUTHORIZATION: %s" % e
        if why:
            r = bd.expire_intent(receipt, rec, why=why, kind="pilot_intent_cancelled")
            actions.append({"seq": seq, "intent_id": rec.get("intent_id"), "action": "CANCELLED", "why": why, "receipt": r})
            continue
        if bd.clock.now() > rec.get("expiry_epoch", rec.get("created_epoch", 0) + INTENT_TTL_S):
            why = "EXPIRED: clock %.3f > expiry %.3f" % (bd.clock.now(), rec.get("expiry_epoch"))
            r = bd.expire_intent(receipt, rec, why=why, kind="pilot_intent_expired")
            actions.append({"seq": seq, "intent_id": rec.get("intent_id"), "action": "EXPIRED", "why": why, "receipt": r})
            continue
        try:
            fr = bd.execute_intent(intent_receipt=receipt, quote_fn=quote_fn)
            actions.append({"seq": seq, "intent_id": rec.get("intent_id"), "action": "EXECUTED", "decision": fr["decision"],
                            "status": fr["status"], "reconciled": fr.get("reconciled", False), "receipt": fr})
        except B.BoundaryRefused as e:
            actions.append({"seq": seq, "intent_id": rec.get("intent_id"), "action": "REFUSED", "why": str(e),
                            "refusal_persisted": e.persisted})
    return actions


def close_session(bd: B.Boundary) -> dict:
    rows = L.read_all(bd.ledger)
    counts: dict = {}
    for r in rows:
        if r.get("session_id") == bd.session_id:
            counts[r.get("kind")] = counts.get(r.get("kind"), 0) + 1
    open_ = [seq for seq, r in unfilled_intents(bd.ledger, rows=rows) if r.get("session_id") == bd.session_id]
    rec = {"kind": "pilot_session_close", "txn_id": "session_close:" + bd.session_id, "session_id": bd.session_id,
           "release": bd.release, "record_counts": counts, "unfinished_intent_seqs_at_close": open_,
           "closed_utc": bd.clock.now_utc(), **bd.labels}
    assert_prospective(rec)
    receipt, _ = L.commit_once(bd.ledger, txn_id=rec["txn_id"], build=lambda rows: rec, kind="pilot_session_close")
    return receipt
