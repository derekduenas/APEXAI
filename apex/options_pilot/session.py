"""OPTIONS-PILOT-001 session orchestration over the recording boundary.

All external inputs are INJECTED so the same orchestration runs unchanged on
synthetic fixtures and, later, on the live feed:

    forecast_fn(symbol, as_of)      -> forecast dict (validated by the boundary)
    signal_fn(symbol, as_of)        -> "LONG" | "SHORT" | None   (heuristic label)
    chain_fn(symbol, as_of)         -> list of available contracts {expiration, strike, right}
    spot_fn(symbol, as_of)          -> float
    quote_fn(contract)              -> execution quote, obtained AFTER intent persistence
    risk_fn(intent)                 -> {"approved": bool, ...}
    clock_fn()                      -> epoch seconds

One symbol per scan. Restart safety: `resume` reads the ledger and completes
any intent that has no fill, exactly once; a second delivery of the same
intent is refused by the boundary."""
from __future__ import annotations

from pathlib import Path

from . import boundary as B, ledger as L
from .expression_rule import RuleRefused, choose
from .records import LABELS


def open_session(ledger: Path, *, session: str, symbol: str, release: str) -> dict:
    return L.append_with_receipt(ledger, {"kind": "pilot_session_open", "session": session, "symbol": symbol,
                                          "release": release, "protocol": "OPTIONS-PILOT-001", **LABELS})


def scan(ledger: Path, *, symbol: str, as_of: str, forecast_fn, signal_fn, chain_fn, spot_fn,
         quote_fn, risk_fn, clock_fn) -> dict:
    """One scan: forecast -> intent -> fill, in that order, each a receipt.
    Returns a dict describing where the scan ended; nothing is swallowed."""
    ledger = Path(ledger)
    out = {"symbol": symbol, "as_of": as_of}
    # 1. forecast persisted first, before any quote is consulted
    f_receipt = B.record_forecast(ledger, forecast_fn(symbol, as_of))
    out["forecast_receipt"] = f_receipt
    # 2. deterministic rule -> risk -> intent persisted
    try:
        proposal = choose(symbol=symbol, direction_signal=signal_fn(symbol, as_of), spot=spot_fn(symbol, as_of),
                          as_of=as_of, available=chain_fn(symbol, as_of))
    except RuleRefused as e:
        B._refuse(ledger, "rule", str(e), refs={"forecast_seq": f_receipt["seq"]})
    proposal["risk"] = risk_fn(proposal)
    i_receipt = B.record_intent(ledger, forecast_receipt=f_receipt, intent=proposal)
    out["intent_receipt"] = i_receipt
    # 3+4. quote only after the intent is on disk; fill once
    fill_receipt = B.execute_intent(ledger, intent_receipt=i_receipt, quote_fn=quote_fn, now_epoch=clock_fn())
    out["fill_receipt"] = fill_receipt
    return out


def resolve(ledger: Path, *, fill_receipt: dict, exit_quote_fn, clock_fn) -> dict:
    fl = L.verify_receipt(ledger, fill_receipt, expected_kind="pilot_fill")
    q = exit_quote_fn(fl["contract"]) if fl["status"] == "FILLED" else None
    return B.record_outcome(ledger, fill_receipt=fill_receipt, exit_quote=q, now_epoch=clock_fn())


def unfilled_intents(ledger: Path) -> list:
    """Intents on disk with no fill record referencing them."""
    rows = L.read_all(ledger)
    filled = {(r.get("intent_ref") or {}).get("seq") for r in rows if r.get("kind") == "pilot_fill"}
    return [(i + 1, r) for i, r in enumerate(rows) if r.get("kind") == "pilot_intent" and (i + 1) not in filled]


def resume(ledger: Path, *, quote_fn, clock_fn) -> list:
    """After a crash: complete every intent that has no fill, exactly once.
    Receipts are rebuilt from disk, not from memory."""
    ledger = Path(ledger)
    done = []
    for seq, rec in unfilled_intents(ledger):
        receipt = {"path": str(ledger), "seq": seq, "entry_hash": rec["entry_hash"], "kind": "pilot_intent",
                   "contract_id": rec.get("contract_id"), "receipt": "REBUILT from disk on resume"}
        done.append(B.execute_intent(ledger, intent_receipt=receipt, quote_fn=quote_fn, now_epoch=clock_fn()))
    return done


def close_session(ledger: Path, *, session: str) -> dict:
    rows = L.read_all(ledger)
    counts = {}
    for r in rows:
        counts[r.get("kind")] = counts.get(r.get("kind"), 0) + 1
    return L.append_with_receipt(ledger, {"kind": "pilot_session_close", "session": session, "record_counts": counts,
                                          "unfilled_intents_at_close": len(unfilled_intents(ledger)), **LABELS})
