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
from .book import intent_finished
from .clock import to_utc_string
from .expression_rule import DEFAULT_RULE, RuleRefused, choose
from .risk_authority import entry_cap_price
from .records import INTENT_TTL_S, assert_prospective, canonical_hash

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


def _payload_of(rec: dict, receipt: dict, *, reconciled: bool) -> dict:
    """The decision as PERSISTED. Whatever the caller computed is irrelevant
    once a decision record exists for the scan: the disk tells the story."""
    return {"scan_id": rec["scan_id"], "symbol": rec["symbol"], "decision": rec["decision"], "why": rec.get("why"),
            "forecast_id": rec.get("forecast_id"), "intent_id": rec.get("intent_id"), "fill_id": rec.get("fill_id"),
            "refusal_persisted": rec.get("refusal_persisted"), "decision_receipt": receipt, "decision_persisted": True,
            "reconciled": reconciled, "receipts": {}}


FUNNEL_STAGES = ("state_snapshot", "situation_regime", "model_bundle", "simulation_bundle", "eligible_expressions", "expected_economics",
                 "risk_decision", "final")


def funnel_trace(bd: B.Boundary, *, ids: dict, decision: str, why) -> dict:
    """The funnel trace persisted with every decision: each required stage names what it used or WHY it is missing."""
    rows = L.read_all(bd.ledger)
    fc = next((r for r in rows if r.get("kind") == "pilot_forecast" and r.get("forecast_id") == ids.get("forecast_id")), None) if ids.get("forecast_id") else None
    it = next((r for r in rows if r.get("kind") == "pilot_intent" and r.get("intent_id") == ids.get("intent_id")), None) if ids.get("intent_id") else None
    fn = rows[ids["funnel_seq"] - 1] if ids.get("funnel_seq") and ids["funnel_seq"] <= len(rows) and rows[ids["funnel_seq"] - 1].get("kind") == "pilot_funnel" else None
    if fn is not None:
        return _funnel_trace_from_engine(fn, seq=ids["funnel_seq"], fc=fc, it=it, decision=decision, why=why)
    t = {}
    t["state_snapshot"] = {"state_hash": (fc.get("inputs") or {}).get("state_hash")} if fc and (fc.get("inputs") or {}).get("state_hash") else \
        {"missing": "NO_STATE_HASH: forecast provider did not attach a twin state" if fc else "NO_FORECAST: %s" % (why or "refused before a forecast")}
    t["situation_regime"] = {"missing": "NOT_AVAILABLE_IN_PILOT: no regime model is activated; the heuristic direction label is recorded on the forecast",
                             "direction_signal": fc.get("direction_signal") if fc else None}
    t["model_bundle"] = ({"model_id": fc["model_id"], "params_hash": fc["params_hash"], "family": fc["family"], "validation": fc.get("validation_status")}
                         if fc else {"missing": "NO_FORECAST"})
    t["simulation_bundle"] = {"missing": "NOT_USED_IN_PILOT: the deterministic rule does not consult the Multiverse (selection authority NONE)"}
    t["eligible_expressions"] = ({"rule": it.get("expression_rule"), "chosen": it.get("expression"), "contract_id": it.get("contract_id"),
                                  "set": ["WAIT", it.get("expression")], "no_best_option_claim": it.get("no_best_option_claim")}
                                 if it else {"missing": "NO_INTENT: %s" % (why or "rule/risk refused")})
    t["expected_economics"] = {"missing": "UNESTABLISHED: no future-IV process is credibly modeled; the M4 comparison is recorded outside the decision path"}
    t["risk_decision"] = ({"provenance": (it.get("risk") or {}).get("risk_provenance"), "authority_id": (it.get("risk") or {}).get("authority_id"),
                           "certified_max_loss": (it.get("risk") or {}).get("certified_max_loss"),
                           "kernel_approved_at_commit": ((it.get("risk") or {}).get("kernel_check_at_commit") or {}).get("approved")}
                          if it else {"missing": "NO_INTENT"})
    t["final"] = {"decision": decision, "why": why}
    t["contract"] = "FUNNEL_TRACE_V1: every stage is present with a value or a named reason for its absence"
    return t


def _funnel_trace_from_engine(fn: dict, *, seq: int, fc, it, decision: str, why) -> dict:
    """FUNNEL_TRACE_V2: the stages filled from the persisted engine trace (kind pilot_funnel) that preceded the decision."""
    tr = fn.get("trace") or {}
    t = {}
    t["state_snapshot"] = ({"state_hash": (fc.get("inputs") or {}).get("state_hash")} if fc and (fc.get("inputs") or {}).get("state_hash")
                           else {"state_hash": tr.get("state_hash")} if tr.get("state_hash") else {"missing": "NO_STATE_HASH"})
    t["situation_regime"] = {**(tr.get("regime") or {"missing": "NOT_REACHED: %s" % fn.get("why")}), "heuristic_direction": tr.get("heuristic_direction")}
    t["model_bundle"] = {"forecast": ({"model_id": fc["model_id"], "params_hash": fc["params_hash"], "family": fc["family"], "validation": fc.get("validation_status")}
                                      if fc else {"missing": "NO_FORECAST"}),
                         "variance": tr.get("variance") or {"missing": "NOT_REACHED: %s" % fn.get("why")}, "fit": tr.get("fit"),
                         "implied": tr.get("implied") or {"missing": "NOT_REACHED"}}
    t["simulation_bundle"] = tr.get("simulation") or {"missing": "NOT_REACHED: %s" % fn.get("why")}
    ew = tr.get("expression_war")
    t["eligible_expressions"] = ({"rule": fn.get("rule_id"), "set": [c["label"] for c in ew["table"]], "eligible": [c["label"] for c in ew["table"] if c.get("status") == "ELIGIBLE"],
                                  "chosen": (tr.get("selected") or {}).get("label"), "contract_id": it.get("contract_id") if it else None,
                                  "no_best_option_claim": "the selection is the best MODEL-CONDITIONAL expected value among the finite set; not a best-option claim"}
                                 if ew else {"missing": "NOT_REACHED: %s" % fn.get("why")})
    t["expected_economics"] = ({"selected": tr.get("selected"), "note": ew["expected_value_note"], "established": False, "fees": ew["fees"]}
                               if ew else {"missing": "NOT_REACHED: %s" % fn.get("why")})
    t["prime"] = tr.get("prime") or {"missing": "NOT_REACHED: %s" % fn.get("why")}
    t["risk_decision"] = ({"provenance": (it.get("risk") or {}).get("risk_provenance"), "authority_id": (it.get("risk") or {}).get("authority_id"),
                           "certified_max_loss": (it.get("risk") or {}).get("certified_max_loss"),
                           "kernel_approved_at_commit": ((it.get("risk") or {}).get("kernel_check_at_commit") or {}).get("approved")}
                          if it else {"missing": "NO_INTENT: %s" % (why or fn.get("why")), "envelope_at_selection": (tr.get("prime") or {}).get("risk")})
    t["final"] = {"decision": decision, "why": why}
    t["funnel_ref"] = {"seq": seq, "entry_hash": fn.get("entry_hash"), "engine_decision": fn.get("decision")}
    t["contract"] = "FUNNEL_TRACE_V2: every stage carries the engine's recorded value or a named reason for its absence"
    return t


def _decision(bd: B.Boundary, *, scan_id: str, symbol: str, decision: str, why, ids: dict, persisted_refusal=None) -> dict:
    rec = {"kind": "pilot_decision", "txn_id": "decision:" + scan_id, "scan_id": scan_id, "symbol": symbol,
           "session_id": bd.session_id, "release": bd.release, "decision": decision, "why": why,
           "forecast_id": ids.get("forecast_id"), "intent_id": ids.get("intent_id"), "fill_id": ids.get("fill_id"),
           "funnel_trace": funnel_trace(bd, ids=ids, decision=decision, why=why),
           "refusal_persisted": persisted_refusal, "decided_utc": bd.clock.now_utc(), **bd.labels}
    assert_prospective(rec)
    out = {"scan_id": scan_id, "symbol": symbol, "decision": decision, "why": why, **ids, "receipts": ids.get("receipts", {}),
           "reconciled": False}
    try:
        receipt, fresh = L.commit_once(bd.ledger, txn_id=rec["txn_id"], build=lambda rows: rec, kind="pilot_decision")
    except L.LedgerRefused as e:
        out["decision_persisted"] = False
        out["decision_persist_error"] = str(e)[:200]
        if persisted_refusal is not None:
            out["refusal_persisted"] = persisted_refusal
        return out
    if not fresh:                                    # a decision for this scan already exists: return ITS payload
        on_disk = L.read_all(bd.ledger)[receipt["seq"] - 1]
        return {**_payload_of(on_disk, receipt, reconciled=True), "receipts": out["receipts"]}
    out["decision_receipt"] = receipt
    out["decision_persisted"] = True
    if persisted_refusal is not None:
        out["refusal_persisted"] = persisted_refusal
    return out


def _duplicate_delivery(bd: B.Boundary, *, scan_id: str, symbol: str, prior: list) -> dict:
    """A scan_id that already has a persisted DECISION: verify it and return
    the persisted payload. The duplicate delivery itself is recorded as a
    separate diagnostic record, never as a decision."""
    rows = L.read_all(bd.ledger)
    decisions = [(i + 1, r) for i, r in enumerate(rows) if r.get("kind") == "pilot_decision" and r.get("scan_id") == scan_id]
    if not decisions:
        # records exist but no decision was ever persisted: the earlier scan was interrupted. This is the
        # FIRST decision for the scan_id; any intent it left behind is the resume policy's job.
        return None
    seq, rec = decisions[0]
    receipt = {"path": str(bd.ledger), "seq": seq, "entry_hash": rec.get("entry_hash")}
    try:
        L.verify_receipt(bd.ledger, receipt, expected_kind="pilot_decision", rows=rows)
    except L.LedgerRefused as e:
        return _decision(bd, scan_id=scan_id, symbol=symbol, decision="REFUSE",
                         why="DUPLICATE_SCAN_DECISION_ALTERED: %s" % e, ids={"receipts": {}})
    diag = {"kind": "pilot_duplicate_delivery", "scan_id": scan_id, "symbol": symbol, "session_id": bd.session_id,
            "release": bd.release, "decision_ref": {"seq": seq, "entry_hash": rec.get("entry_hash")},
            "note": "a second delivery of this scan_id; the persisted decision stands and was returned unchanged",
            "at_utc": bd.clock.now_utc(), **bd.labels}
    assert_prospective(diag)
    out = _payload_of(rec, {**receipt, "kind": "pilot_decision", "receipt": "RECONCILED: persisted decision returned"}, reconciled=True)
    out["duplicate_delivery"] = True
    try:
        out["duplicate_delivery_receipt"] = L.append_with_receipt(bd.ledger, diag)
    except L.LedgerRefused as e:
        out["duplicate_delivery_receipt"] = None
        out["duplicate_delivery_persist_error"] = str(e)[:200]
    return out


def scan(bd: B.Boundary, *, symbol: str, seq: int, forecast_fn, signal_fn, chain_fn, spot_fn, quote_fn, funnel_fn=None) -> dict:
    """One scan: forecast -> (funnel) -> intent -> fill, in that order, each a receipt;
    ends in exactly one decision: TRADE / WAIT / REFUSE. A BoundaryRefused
    becomes a REFUSE decision that says whether the refusal was persisted;
    provider exceptions fail closed the same way.

    With `funnel_fn` (FULL_FUNNEL_V1) the deterministic rule is replaced by the
    engine: its result is persisted as a `pilot_funnel` record BEFORE any intent,
    a WAIT ends the scan as a WAIT decision carrying the whole trace, a TRADE
    proposal goes through the same risk-bound intent + fill path as the rule."""
    scan_id = scan_id_for(bd.session_id, seq, symbol)
    ids: dict = {"receipts": {}}
    prior = [r for r in L.read_all(bd.ledger) if r.get("scan_id") == scan_id]
    if prior:
        dup = _duplicate_delivery(bd, scan_id=scan_id, symbol=symbol, prior=prior)
        if dup is not None:
            return dup
        try:
            bd.refuse("scan", "INCOMPLETE_SCAN: scan_id already has %d record(s) (first kind %r) but no decision; "
                      "not re-run -- unfinished intents belong to the resume policy" % (len(prior), prior[0].get("kind")),
                      scan_id=scan_id)
        except B.BoundaryRefused as e:
            return _decision(bd, scan_id=scan_id, symbol=symbol, decision="REFUSE", why=str(e), ids=ids,
                             persisted_refusal=e.persisted)
    as_of = bd.clock.now()
    try:
        # 1. forecast persisted first, before any quote is consulted
        try:
            forecast = forecast_fn(symbol, as_of)
        except Exception as e:                                             # noqa: BLE001
            bd.refuse("forecast", "FORECAST_PROVIDER_FAILED: %s: %s" % (type(e).__name__, str(e)[:300]), scan_id=scan_id)
        f_receipt = bd.record_forecast(forecast, scan_id=scan_id)
        ids["forecast_id"] = f_receipt["forecast_id"]; ids["receipts"]["forecast"] = f_receipt
        if funnel_fn is not None:
            # 2a. THE FUNNEL: every layer decides together; the engine's trace is persisted before any intent
            def _certified_risk(proposal: dict) -> dict:
                """The BOUNDARY's own certified authority answers, against the real Book. A selection engine never
                attests its own risk approval; the kernel re-checks again at intent commit."""
                from .records import contract_id as _cid
                from .risk_authority import CERTIFIED_PROVENANCE as _CP, envelope_for as _env
                env = _env(reference_ask=proposal.get("reference_ask"), quantity=1)
                c = proposal.get("contract") or {}
                body = {"expression": proposal.get("expression"), "contract": c, "quantity": proposal.get("quantity", 1),
                        "risk_envelope": env, "action": "BUY", "session_id": bd.session_id, "scan_id": scan_id,
                        "contract_id": _cid(c) if c else None,
                        "intent_id": "PRESELECTION:%s" % canonical_hash({"scan_id": scan_id, "contract": c})[:16],
                        "signal_used": ("LONG" if (proposal.get("expression") == "LONG_CALL") else "SHORT")}
                try:
                    approval = bd.risk.approve(body, book=bd.book())
                except Exception as e:                                     # noqa: BLE001 - a refusal is an answer
                    return {"approved": False, "risk_provenance": _CP, "authority_id": getattr(bd.risk, "authority_id", None),
                            "why": "RISK_AUTHORITY_REFUSED: %s: %s" % (type(e).__name__, str(e)[:160])}
                return {**approval, "envelope": env, "book_state_hash": bd.book().state_hash()}

            try:
                res = funnel_fn(symbol, as_of, forecast, book_summary=bd.book().summary(),
                                certified_risk_fn=_certified_risk, scan_id=scan_id)
            except Exception as e:                                         # noqa: BLE001
                bd.refuse("funnel", "FUNNEL_PROVIDER_FAILED: %s: %s" % (type(e).__name__, str(e)[:300]), scan_id=scan_id)
            if not isinstance(res, dict) or res.get("decision") not in ("TRADE", "WAIT") or "trace" not in res:
                bd.refuse("funnel", "FUNNEL_RESULT_MALFORMED: %r" % (type(res).__name__,), scan_id=scan_id)
            frec = {"kind": "pilot_funnel", "scan_id": scan_id, "symbol": symbol, "session_id": bd.session_id, "release": bd.release,
                    "forecast_ref": {"seq": f_receipt["seq"], "forecast_hash": f_receipt.get("forecast_hash")}, "rule_id": res.get("rule_id"),
                    "decision": res["decision"], "why": res.get("why"), "proposal": res.get("proposal"), "trace": res["trace"],
                    "engine": res.get("engine"), "at_utc": bd.clock.now_utc(), **bd.labels}
            assert_prospective(frec)
            try:
                fr_receipt = L.append_with_receipt(bd.ledger, frec)
            except L.LedgerRefused as e:
                bd.refuse("funnel", "FUNNEL_NOT_PERSISTED: %s" % str(e)[:200], scan_id=scan_id)
            ids["funnel_seq"] = fr_receipt["seq"]; ids["receipts"]["funnel"] = fr_receipt
            if res["decision"] != "TRADE":
                return _decision(bd, scan_id=scan_id, symbol=symbol, decision="WAIT", why="FUNNEL_WAIT: %s" % res.get("why"), ids=ids)
            proposal = dict(res["proposal"]); signal = proposal.pop("direction_signal", None)
            funnel_receipt = {**fr_receipt, "scan_id": scan_id}
        else:
            funnel_receipt = None
            # 2b. deterministic rule -> risk-bound intent persisted
            try:
                signal = signal_fn(symbol, as_of)
                proposal = choose(symbol=symbol, direction_signal=signal, spot=spot_fn(symbol, as_of),
                                  as_of=to_utc_string(as_of), available=chain_fn(symbol, as_of),
                                  rule=getattr(bd, "expression_rule_version", DEFAULT_RULE), max_entry_price=entry_cap_price())
            except RuleRefused as e:
                bd.refuse("rule", str(e), refs={"forecast_seq": f_receipt["seq"]}, scan_id=scan_id)
            except Exception as e:                                         # noqa: BLE001
                bd.refuse("rule", "INPUT_PROVIDER_FAILED: %s: %s" % (type(e).__name__, str(e)[:300]), scan_id=scan_id)
        i_receipt = bd.record_intent(forecast_receipt=f_receipt, intent=proposal, signal_used=signal, scan_id=scan_id, funnel_receipt=funnel_receipt)
        ids["intent_id"] = i_receipt["intent_id"]; ids["receipts"]["intent"] = i_receipt
        # 3+4. quote only after the intent is on disk; fill exactly once
        fill_receipt = bd.execute_intent(intent_receipt=i_receipt, quote_fn=quote_fn)
        ids["fill_id"] = fill_receipt["fill_id"]; ids["receipts"]["fill"] = fill_receipt
        return _decision(bd, scan_id=scan_id, symbol=symbol, decision=fill_receipt["decision"], why=fill_receipt.get("why"), ids=ids)
    except B.BoundaryRefused as e:
        return _decision(bd, scan_id=scan_id, symbol=symbol, decision="REFUSE", why=str(e), ids=ids,
                         persisted_refusal=e.persisted)


def resolve(bd: B.Boundary, *, fill_receipt: dict, exit_quote_fn, recovery: bool = False) -> dict:
    return bd.record_outcome(fill_receipt=fill_receipt, exit_quote_fn=exit_quote_fn, recovery=recovery)


def attempt_exits(bd: B.Boundary, *, exit_quote_fn, sleep_fn, recovery: bool = False, positions: list | None = None,
                  wait_for_due: bool = True) -> list:
    """Drive the frozen exit policy over this session's unresolved positions:
    wait until due, value, retry inside the window, record exhaustion.
    Returns one entry per position with the final state THIS run reached."""
    pol = bd.exit_policy
    out = []
    positions = recover_positions(bd)["own"] if positions is None else positions
    for pos in positions:
        rows = L.read_all(bd.ledger)
        fl = rows[pos["seq"] - 1]
        committed = fl.get("committed_epoch")
        entry = {"fill_seq": pos["seq"], "intent_id": pos.get("intent_id"), "attempts": [], "final": None}
        if pos.get("exit_exhausted") or any(x.get("kind") == "pilot_exit_exhausted" and (x.get("fill_ref") or {}).get("seq") == pos["seq"] for x in rows):
            if not recovery:
                entry["final"] = "EXIT_EXHAUSTED_UNRESOLVED"
                out.append(entry)
                continue
        while True:
            n_att = len(B.Boundary.valuation_attempts(L.read_all(bd.ledger), pos["seq"]))
            status = pol.status(now=bd.clock.now(), committed_epoch=committed, attempts=n_att)
            if status == "NOT_DUE":
                if not wait_for_due:
                    entry["final"] = "NOT_DUE"
                    break
                sleep_fn(max(0.0, committed + pol.horizon_s - bd.clock.now()))
                continue
            if status == "EXHAUSTED" and not recovery:
                bd.record_exit_exhausted(pos)
                entry["final"] = "EXIT_EXHAUSTED_UNRESOLVED"
                break
            try:
                o = bd.record_outcome(fill_receipt=pos, exit_quote_fn=exit_quote_fn, recovery=recovery or status == "EXHAUSTED")
            except B.BoundaryRefused as e:
                entry["attempts"].append({"refused": str(e)[:160]})
                entry["final"] = "REFUSED"
                break
            entry["attempts"].append({"seq": o["seq"], "status": o["status"], "attempt": o.get("attempt"), "reconciled": o.get("reconciled")})
            if o.get("discharges_position"):
                entry["final"] = o["status"]
                break
            if recovery:
                entry["final"] = "UNRESOLVED_AFTER_RECOVERY_ATTEMPT"
                break
            sleep_fn(pol.retry_spacing_s)
        out.append(entry)
    return out


def unfilled_intents(ledger, *, rows: list | None = None) -> list:
    """Intents on disk that are not FINISHED: no FILLED attempt, no terminal
    REFUSE attempt, no expiry/cancellation record. A WAIT attempt leaves the
    intent open for a re-quote (bounded by the execution policy and TTL)."""
    rows = L.read_all(ledger) if rows is None else rows
    attempts: dict = {}
    terminal = set()
    for i, r in enumerate(rows):
        if r.get("kind") == "pilot_fill":
            attempts.setdefault((r.get("intent_ref") or {}).get("seq"), []).append((i + 1, r))
        if r.get("kind") in ("pilot_intent_expired", "pilot_intent_cancelled"):
            terminal.add((r.get("intent_ref") or {}).get("seq"))
    return [(i + 1, r) for i, r in enumerate(rows) if r.get("kind") == "pilot_intent"
            and not intent_finished(attempts.get(i + 1, []), (i + 1) in terminal)]


def unresolved_fills(ledger, *, rows: list | None = None) -> list:
    """FILLED fills (positions) with no outcome record referencing them.
    These are OUTSTANDING OBLIGATIONS: a session is not complete while any
    exist, whatever the intent side of the ledger says."""
    rows = L.read_all(ledger) if rows is None else rows
    # ONLY a discharging outcome (RESOLVED / NO_POSITION) resolves a position. A NOT_ESTIMABLE valuation attempt is
    # persisted evidence that an exit was unavailable; it does not discharge anything.
    discharged = {(r.get("fill_ref") or {}).get("seq") for r in rows
                  if r.get("kind") == "pilot_outcome" and r.get("discharges_position") is True}
    return [(i + 1, r) for i, r in enumerate(rows)
            if r.get("kind") == "pilot_fill" and r.get("status") == "FILLED" and (i + 1) not in discharged]


def recover_positions(bd: B.Boundary) -> dict:
    """Rebuild fill receipts FROM DISK for every unresolved position. Own
    (this session + release + provenance) positions are returned as
    resolvable receipts; foreign ones are reported, not touched."""
    rows = L.read_all(bd.ledger)
    own, foreign = [], []
    for seq, r in unresolved_fills(bd.ledger, rows=rows):
        attempts = [x for x in rows if x.get("kind") == "pilot_outcome" and (x.get("fill_ref") or {}).get("seq") == seq]
        receipt = {"path": str(bd.ledger), "seq": seq, "entry_hash": r.get("entry_hash"), "kind": "pilot_fill",
                   "intent_id": r.get("intent_id"), "scan_id": r.get("scan_id"), "fill_id": r.get("fill_id"),
                   "contract_id": r.get("contract_id"), "valuation_attempts": len(attempts),
                   "last_attempt_why": (attempts[-1].get("why") if attempts else None),
                   "receipt": "REBUILT from disk (unresolved position)"}
        if r.get("session_id") == bd.session_id and r.get("release") == bd.release \
                and r.get("data_provenance") == bd.labels["data_provenance"]:
            own.append(receipt)
        else:
            foreign.append({**receipt, "session_id": r.get("session_id"), "release": r.get("release"),
                            "data_provenance": r.get("data_provenance"),
                            "why_not_resolved_here": "belongs to another session/release/provenance; reported, not touched"})
    return {"own": own, "foreign": foreign}


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
            problem = bd.authorization_problem(rec)          # active authority + provenance, not just the stored binding
            if problem:
                why = "STALE_AUTHORIZATION: %s" % problem
        try:
            if why:
                r = bd.expire_intent(receipt, rec, why=why, kind="pilot_intent_cancelled")
                actions.append({"seq": seq, "intent_id": rec.get("intent_id"), "action": "CANCELLED", "why": why, "receipt": r})
                continue
            if bd.clock.now() > rec.get("expiry_epoch", rec.get("created_epoch", 0) + INTENT_TTL_S):
                why = "EXPIRED: clock %.3f > expiry %.3f" % (bd.clock.now(), rec.get("expiry_epoch"))
                r = bd.expire_intent(receipt, rec, why=why, kind="pilot_intent_expired")
                actions.append({"seq": seq, "intent_id": rec.get("intent_id"), "action": "EXPIRED", "why": why, "receipt": r})
                continue
        except B.BoundaryRefused as e:
            actions.append({"seq": seq, "intent_id": rec.get("intent_id"), "action": "REFUSED", "why": str(e),
                            "refusal_persisted": e.persisted})
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
    # An open (unfilled) paper intent of THIS session carries no exposure: it is CANCELLED at close, as a terminal record
    # (exclusive with fills under the transaction), so nothing can fill against a closed session and nothing dangles.
    cancelled = []
    for seq, r in unfilled_intents(bd.ledger, rows=rows):
        if r.get("session_id") != bd.session_id:
            continue
        receipt = {"path": str(bd.ledger), "seq": seq, "entry_hash": r["entry_hash"], "kind": "pilot_intent"}
        try:
            bd.expire_intent(receipt, r, why="SESSION_CLOSE: unfilled at close", kind="pilot_intent_cancelled")
            cancelled.append(seq)
        except B.BoundaryRefused as e:                       # e.g. a fill won the race: it stays a position
            cancelled.append({"seq": seq, "refused": str(e)[:120]})
    rows = L.read_all(bd.ledger)
    open_ = [seq for seq, r in unfilled_intents(bd.ledger, rows=rows) if r.get("session_id") == bd.session_id]
    positions = [seq for seq, r in unresolved_fills(bd.ledger, rows=rows) if r.get("session_id") == bd.session_id]
    exhausted = [seq for seq in positions if any(x.get("kind") == "pilot_exit_exhausted" and (x.get("fill_ref") or {}).get("seq") == seq for x in rows)]
    book = bd.book(rows)
    n_prior = sum(1 for r in rows if r.get("kind") == "pilot_session_close" and r.get("session_id") == bd.session_id)
    rec = {"kind": "pilot_session_close", "txn_id": "session_close:%s:%d" % (bd.session_id, n_prior + 1),
           "close_number": n_prior + 1, "session_id": bd.session_id,
           "release": bd.release, "record_counts": counts, "unfinished_intent_seqs_at_close": open_,
           "intents_cancelled_at_close": cancelled, "unresolved_fill_seqs_at_close": positions,
           "exit_exhausted_fill_seqs_at_close": exhausted,
           "failed_valuation_attempts_at_close": {str(seq): len(B.Boundary.valuation_attempts(rows, seq)) for seq in positions},
           "book": book.summary(),
           "outstanding_obligations": len(open_) + len(positions),
           "completion": "CLOSED_CLEAN" if not open_ and not positions else "CLOSED_WITH_OUTSTANDING_OBLIGATIONS",
           "closed_utc": bd.clock.now_utc(), **bd.labels}
    assert_prospective(rec)
    receipt, _ = L.commit_once(bd.ledger, txn_id=rec["txn_id"], build=lambda rows: rec, kind="pilot_session_close")
    return receipt
