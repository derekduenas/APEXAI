"""THE FORECAST-AND-INTENT RECORDING BOUNDARY (repaired).

Enforced order, proven by ledger sequence numbers assigned on append and
re-read from disk, never by caller-supplied timestamps or hash-shaped strings:

    1. persist FORECAST                                   -> receipt
    2. persist INTENT bound to a RiskAuthority approval    -> receipt
    3. obtain the EXECUTION QUOTE only after the intent AND the history
       it references verify on disk as one chain
    4. commit the FILL atomically, exactly once per intent -> receipt
    5. commit the OUTCOME atomically, exactly once per fill -> receipt

Every refusal is a persisted record when the ledger will take one; a
refusal that cannot be persisted still raises and REPORTS that it could not
be persisted. Nothing proceeds on a dead ledger.

Freshness is measured with a clock reading taken AFTER the quote was
received (a slow provider makes its own quote stale). The provider's
timestamp is recorded as asserted. Request order is proven by ledger seq
(intent seq < fill seq); it is NOT a proof that the provider generated the
quote after the intent -- that is stated on every fill record.

QUOTE ELIGIBILITY POLICY (declared, not inferred):
    * age at receipt   = clock_after_receipt - provider_timestamp  in [0, 15 s]
      (receipt is never earlier than intent persistence, so this also bounds
      how far the provider timestamp may precede the intent: <= 15 s; the
      signed offset is recorded on every fill as quote_ts_minus_intent_persisted_s)
    * the SELECTED contract and the side that will be crossed must be present,
      finite, uncrossed, with an exact-int size >= 1
    * the intent must not have expired (TTL 120 s from its persisted clock)"""
from __future__ import annotations

from . import ledger as L
from . import risk_gate as RG
from .clock import Clock, ClockRefused, check_reading, to_utc_string
from .records import (INTENT_TTL_S, RecordRefused, assert_prospective, canonical_hash, labels_for,
                      validate_forecast, validate_intent, validate_quote)

MAX_SELECTED_QUOTE_AGE_S = 15.0
CONTRACT_MULTIPLIER = 100.0
ELIGIBILITY_POLICY = ("QUOTE_ELIGIBILITY_V2: age at receipt in [0, 15s] (receipt >= intent persisted, so provider ts is "
                      "within 15s before the intent); selected contract+side finite, uncrossed, exact-int size >= 1; "
                      "intent unexpired (TTL 120s)")
ORDER_PROOF = ("ledger seq proves intent persisted BEFORE the quote was requested; it does NOT prove the provider "
               "generated the quote after the intent -- the provider timestamp is recorded as asserted")


class BoundaryRefused(RuntimeError):
    """Refused at the boundary. `.persisted` says whether the refusal record landed."""

    def __init__(self, msg: str, *, persisted: bool, receipt: dict | None = None):
        super().__init__(msg)
        self.persisted = persisted
        self.receipt = receipt


class Boundary:
    """One boundary = one ledger + one controlled clock + one provenance +
    one risk authority + one session identity."""

    def __init__(self, ledger, *, clock: Clock, provenance: str, risk_authority: RG.RiskAuthority,
                 session_id: str, release: str):
        self.ledger = ledger
        self.clock = clock
        self.labels = labels_for(provenance)
        self.risk = risk_authority
        self.session_id = session_id
        self.release = release

    # ------------------------------------------------------------ refusal
    def refuse(self, stage: str, reason: str, *, refs: dict | None = None, scan_id: str | None = None):
        rec = {"kind": "pilot_refusal", "stage": stage, "reason": reason, "refs": refs or {},
               "session_id": self.session_id, "scan_id": scan_id, "release": self.release,
               "refused_utc": self.clock.now_utc(), "refused_epoch": self.clock.now(), **self.labels}
        persisted, receipt = False, None
        try:
            receipt = L.append_with_receipt(self.ledger, rec)
            persisted = True
        except L.LedgerRefused as e:
            reason = "%s [REFUSAL_NOT_PERSISTED: %s]" % (reason, str(e)[:120])
        raise BoundaryRefused("%s: %s" % (stage, reason), persisted=persisted, receipt=receipt)

    # ------------------------------------------------------------ 1. forecast
    def record_forecast(self, forecast, *, scan_id: str) -> dict:
        try:
            body = validate_forecast(forecast, now_epoch=self.clock.now(), provenance=self.labels["data_provenance"],
                                     session_id=self.session_id, scan_id=scan_id)
        except RecordRefused as e:
            self.refuse("forecast", str(e), scan_id=scan_id)
        body["persisted_utc"] = self.clock.now_utc()
        body["persisted_epoch"] = self.clock.now()
        body["release"] = self.release
        body["txn_id"] = "forecast:" + body["forecast_id"]
        assert_prospective(body)
        try:
            receipt, _ = L.commit_once(self.ledger, txn_id=body["txn_id"], build=lambda rows: body, kind="pilot_forecast")
        except L.LedgerRefused as e:
            self.refuse("forecast", str(e), scan_id=scan_id)
        receipt.update(forecast_hash=body["forecast_hash"], forecast_id=body["forecast_id"], scan_id=scan_id)
        return receipt

    # ------------------------------------------------------------ 2. intent
    def record_intent(self, *, forecast_receipt: dict, intent: dict, signal_used: str, scan_id: str) -> dict:
        """Forecast on disk, chain verified, unconsumed; intent bound to a
        RiskAuthority approval; consumption of the forecast is atomic."""
        try:
            fr = L.verify_receipt(self.ledger, forecast_receipt, expected_kind="pilot_forecast")
        except L.LedgerRefused as e:
            self.refuse("intent", "FORECAST_REF_%s" % e, refs={"forecast_receipt": forecast_receipt}, scan_id=scan_id)
        if fr.get("forecast_hash") != forecast_receipt.get("forecast_hash"):
            self.refuse("intent", "FORECAST_HASH_MISMATCH: receipt %r vs disk %r"
                        % (str(forecast_receipt.get("forecast_hash"))[:12], str(fr.get("forecast_hash"))[:12]), scan_id=scan_id)
        if fr.get("session_id") != self.session_id:
            self.refuse("intent", "FORECAST_FROM_OTHER_SESSION: %r vs %r" % (fr.get("session_id"), self.session_id), scan_id=scan_id)
        created = self.clock.now()
        try:
            body = validate_intent(intent, forecast=fr, forecast_receipt=forecast_receipt, signal_used=signal_used,
                                   session_id=self.session_id, scan_id=scan_id, release=self.release, created_epoch=created)
        except RecordRefused as e:
            self.refuse("intent", str(e), scan_id=scan_id)
        try:
            approval = self.risk.approve(body)
            body["risk"] = RG.verify_approval(body, approval)
        except RG.RiskRefused as e:
            self.refuse("intent", str(e), refs={"intent_id": body["intent_id"]}, scan_id=scan_id)
        body["txn_id"] = "intent:" + body["intent_id"]
        body.update(self.labels)
        assert_prospective(body)

        def build(rows):
            consumed = L.find(self.ledger, kind="pilot_intent", rows=rows,
                              where=lambda r: (r.get("forecast_ref") or {}).get("seq") == forecast_receipt["seq"])
            if consumed:
                raise L.LedgerRefused("FORECAST_ALREADY_CONSUMED: by intent seq %d" % consumed[0][0])
            body["persisted_utc"] = self.clock.now_utc()
            body["persisted_epoch"] = self.clock.now()
            return body

        try:
            receipt, fresh = L.commit_once(self.ledger, txn_id=body["txn_id"], build=build, kind="pilot_intent")
        except L.LedgerRefused as e:
            self.refuse("intent", str(e), refs={"forecast_seq": forecast_receipt["seq"]}, scan_id=scan_id)
        receipt.update(contract_id=body["contract_id"], intent_id=body["intent_id"], scan_id=scan_id)
        return receipt

    # ------------------------------------------------------------ 3+4. quote then fill
    def _verify_intent_history(self, intent_receipt: dict, *, stage: str) -> tuple:
        try:
            it = L.verify_receipt(self.ledger, intent_receipt, expected_kind="pilot_intent")
        except L.LedgerRefused as e:
            self.refuse(stage, "INTENT_REF_%s" % e, refs={"intent_receipt": intent_receipt})
        scan_id = it.get("scan_id")
        if it.get("contract_id") != intent_receipt.get("contract_id"):
            self.refuse(stage, "INTENT_CONTRACT_MISMATCH: disk %r vs receipt %r"
                        % (it.get("contract_id"), intent_receipt.get("contract_id")), scan_id=scan_id)
        if it.get("session_id") != self.session_id:
            self.refuse(stage, "INTENT_FROM_OTHER_SESSION: %r vs %r" % (it.get("session_id"), self.session_id), scan_id=scan_id)
        if it.get("release") != self.release:
            self.refuse(stage, "INTENT_FROM_OTHER_RELEASE: %r vs %r" % (it.get("release"), self.release), scan_id=scan_id)
        # the forecast the intent references must itself re-verify and agree
        fref = it.get("forecast_ref") or {}
        f_receipt = {"path": intent_receipt["path"], "seq": fref.get("seq"), "entry_hash": fref.get("entry_hash")}
        try:
            fr = L.verify_receipt(self.ledger, f_receipt, expected_kind="pilot_forecast")
        except L.LedgerRefused as e:
            self.refuse(stage, "INTENT_FORECAST_%s" % e, refs={"forecast_ref": fref}, scan_id=scan_id)
        if fr.get("forecast_hash") != fref.get("forecast_hash") or fr.get("forecast_id") != fref.get("forecast_id"):
            self.refuse(stage, "INTENT_FORECAST_HASH_MISMATCH", scan_id=scan_id)
        if fr.get("symbol") != it["contract"]["symbol"] or fr.get("session_id") != it.get("session_id") \
                or fr.get("scan_id") != it.get("scan_id"):
            self.refuse(stage, "INTENT_FORECAST_DISAGREE: symbol/session/scan", scan_id=scan_id)
        if fr.get("horizon_minutes") != 15 or it.get("horizon_relationship") is None:
            self.refuse(stage, "INTENT_HORIZON_UNDECLARED", scan_id=scan_id)
        exp_right = "CALL" if it.get("signal_used") == "LONG" else "PUT" if it.get("signal_used") == "SHORT" else None
        if exp_right is None or it["contract"]["right"] != exp_right or it.get("action") != "BUY" or it.get("quantity") != 1:
            self.refuse(stage, "INTENT_CONTENT_DISAGREE: signal/right/action/quantity", scan_id=scan_id)
        try:
            RG.verify_approval(it, it.get("risk"))
        except RG.RiskRefused as e:
            self.refuse(stage, "INTENT_RISK_ON_DISK_%s" % e, scan_id=scan_id)
        return it, fr

    def execute_intent(self, *, intent_receipt: dict, quote_fn) -> dict:
        """Verify the persisted intent and its history, THEN obtain the
        quote, THEN commit the fill exactly once (atomic, keyed by txn_id).
        Decision is TRADE (filled), WAIT (eligible-but-no-fill reasons that
        may clear), or REFUSE (contract/provider/expiry problems)."""
        it, _fr = self._verify_intent_history(intent_receipt, stage="fill")
        scan_id, intent_id = it.get("scan_id"), it.get("intent_id")
        contract = it["contract"]
        txn_id = "fill:" + intent_id
        # early idempotency: don't even ask for a quote if this intent already has a fill
        with L.transaction(self.ledger):
            rows = L.read_all(self.ledger)
            prior = L.find(self.ledger, kind="pilot_fill", rows=rows, where=lambda r: r.get("txn_id") == txn_id)
            terminal = L.find(self.ledger, kind="pilot_intent_expired", rows=rows,
                              where=lambda r: r.get("intent_id") == intent_id) + \
                L.find(self.ledger, kind="pilot_intent_cancelled", rows=rows, where=lambda r: r.get("intent_id") == intent_id)
        if prior:
            # DUPLICATE DELIVERY / LOST ACK: the transition already committed. Return ITS receipt; never re-quote,
            # never append. (A second fill for one intent is impossible: the fill txn_id derives from intent_id.)
            seq, on_disk = prior[0]
            return {"path": str(self.ledger), "seq": seq, "entry_hash": on_disk.get("entry_hash"), "kind": "pilot_fill",
                    "receipt": "RECONCILED: fill for this intent already on disk; duplicate delivery returned the existing receipt",
                    "status": on_disk.get("status"), "decision": on_disk.get("decision"), "why": on_disk.get("why"),
                    "reconciled": True, "intent_id": intent_id, "scan_id": scan_id, "fill_id": on_disk.get("fill_id")}
        if terminal:
            self.refuse("fill", "INTENT_TERMINAL: %s at seq %d" % (terminal[0][1]["kind"], terminal[0][0]), scan_id=scan_id)
        t_before = self.clock.now()
        if t_before > it["expiry_epoch"]:
            self.expire_intent(intent_receipt, it, why="EXPIRED_BEFORE_QUOTE: clock %.3f > expiry %.3f" % (t_before, it["expiry_epoch"]))
            self.refuse("fill", "INTENT_EXPIRED before quote request", scan_id=scan_id)
        t_request = self.clock.now()
        provider_error = None
        try:
            raw = quote_fn(contract)
        except Exception as e:                                             # noqa: BLE001 - provider failures fail closed
            raw, provider_error = None, "%s: %s" % (type(e).__name__, str(e)[:300])
        t_receipt = self.clock.now()                                       # freshness measured AFTER receipt
        why, quote, decision = None, None, None
        if provider_error:
            why, decision = "QUOTE_PROVIDER_FAILED: " + provider_error, "REFUSE"
        else:
            try:
                quote = validate_quote(raw, contract=contract)
            except RecordRefused as e:
                why, decision = str(e), "REFUSE"
        if why is None:
            age = t_receipt - quote["timestamp_epoch"]
            if age < 0:
                why, decision = "QUOTE_FROM_THE_FUTURE: age at receipt %.3fs" % age, "REFUSE"
            elif age > MAX_SELECTED_QUOTE_AGE_S:
                why, decision = "STALE_SELECTED_CONTRACT: ASK side %.3fs old at receipt > %.0fs" % (age, MAX_SELECTED_QUOTE_AGE_S), "WAIT"
            elif t_receipt > it["expiry_epoch"]:
                why, decision = "INTENT_EXPIRED_DURING_QUOTE: receipt %.3f > expiry %.3f" % (t_receipt, it["expiry_epoch"]), "REFUSE"
            elif quote["ask_size"] < 1:
                why, decision = "NO_SIZE_AT_ASK", "WAIT"
        fill = {"kind": "pilot_fill", "txn_id": txn_id, "intent_id": intent_id, "scan_id": scan_id,
                "session_id": self.session_id, "release": self.release,
                "intent_ref": {"seq": intent_receipt["seq"], "entry_hash": intent_receipt["entry_hash"], "intent_id": intent_id},
                "contract": contract, "contract_id": it["contract_id"], "quantity_intended": 1,
                "quote_request_epoch": t_request, "quote_request_utc": to_utc_string(t_request),
                "quote_receipt_epoch": t_receipt, "quote_receipt_utc": to_utc_string(t_receipt),
                "provider_latency_s": t_receipt - t_request,
                "quote_observed": ({k: quote[k] for k in ("bid", "ask", "bid_size", "ask_size", "timestamp_epoch",
                                                          "timestamp_utc", "timestamp_meaning")} if quote else None),
                "quote_age_at_receipt_s": (t_receipt - quote["timestamp_epoch"]) if quote else None,
                "quote_ts_minus_intent_persisted_s": (quote["timestamp_epoch"] - it["persisted_epoch"]) if quote else None,
                "eligibility_policy": ELIGIBILITY_POLICY, "order_proof": ORDER_PROOF,
                "history_verified": "intent + referenced forecast re-read, chain-verified, content-agreed, risk binding recomputed",
                "committed_utc": self.clock.now_utc(), **self.labels}
        if why is not None:
            fill.update(status="UNFILLED", decision=decision, why=why, quantity_filled=0, net_debit=0.0)
        else:
            px = quote["ask"]
            fill.update(status="FILLED", decision="TRADE", quantity_filled=1, side_crossed="ASK", price=px,
                        net_debit=round(px * CONTRACT_MULTIPLIER, 2),
                        fill_law="long leg pays THAT contract's ASK; no midpoint, no model price")
        fill["fill_id"] = canonical_hash({"txn_id": txn_id, "status": fill["status"]})[:24]
        assert_prospective(fill)

        def build(rows):
            again = L.find(self.ledger, kind="pilot_fill", rows=rows,
                           where=lambda r: (r.get("intent_ref") or {}).get("seq") == intent_receipt["seq"])
            if again:
                raise L.LedgerRefused("DUPLICATE_DELIVERY: intent seq %d already has fill seq %d" % (intent_receipt["seq"], again[0][0]))
            return fill

        try:
            receipt, fresh = L.commit_once(self.ledger, txn_id=txn_id, build=build, kind="pilot_fill")
        except L.LedgerRefused as e:
            self.refuse("fill", str(e), refs={"intent_seq": intent_receipt["seq"]}, scan_id=scan_id)
        if not fresh:                                                      # lost-ack reconciliation
            on_disk = L.read_all(self.ledger)[receipt["seq"] - 1]
            receipt.update(status=on_disk.get("status"), decision=on_disk.get("decision"), why=on_disk.get("why"),
                           reconciled=True, intent_id=intent_id, scan_id=scan_id, fill_id=on_disk.get("fill_id"))
            return receipt
        receipt.update(status=fill["status"], decision=fill["decision"], why=fill.get("why"), intent_id=intent_id,
                       scan_id=scan_id, fill_id=fill["fill_id"])
        return receipt

    def expire_intent(self, intent_receipt: dict, it: dict, *, why: str, kind: str = "pilot_intent_expired") -> dict:
        rec = {"kind": kind, "txn_id": "%s:%s" % (kind, it["intent_id"]), "intent_id": it["intent_id"],
               "intent_ref": {"seq": intent_receipt["seq"], "entry_hash": intent_receipt["entry_hash"]},
               "scan_id": it.get("scan_id"), "session_id": self.session_id, "release": self.release, "why": why,
               "at_utc": self.clock.now_utc(), "at_epoch": self.clock.now(), **self.labels}
        assert_prospective(rec)
        receipt, _ = L.commit_once(self.ledger, txn_id=rec["txn_id"], build=lambda rows: rec, kind=kind)
        return receipt

    # ------------------------------------------------------------ 5. outcome
    def record_outcome(self, *, fill_receipt: dict, exit_quote_fn) -> dict:
        try:
            fl = L.verify_receipt(self.ledger, fill_receipt, expected_kind="pilot_fill")
        except L.LedgerRefused as e:
            self.refuse("outcome", "FILL_REF_%s" % e, refs={"fill_receipt": fill_receipt})
        scan_id = fl.get("scan_id")
        if fl.get("session_id") != self.session_id:
            self.refuse("outcome", "FILL_FROM_OTHER_SESSION", scan_id=scan_id)
        txn_id = "outcome:" + fl["intent_id"]
        out = {"kind": "pilot_outcome", "txn_id": txn_id, "intent_id": fl["intent_id"], "fill_id": fl.get("fill_id"),
               "scan_id": scan_id, "session_id": self.session_id, "release": self.release,
               "fill_ref": {"seq": fill_receipt["seq"], "entry_hash": fill_receipt["entry_hash"]},
               "contract_id": fl["contract_id"], **self.labels}
        if fl["status"] != "FILLED":
            out.update(status="NO_POSITION", pnl=0.0, why="intent was %s (%s)" % (fl["status"], fl.get("why")))
        else:
            t_req = self.clock.now()
            err, q = None, None
            try:
                raw = exit_quote_fn(fl["contract"])
            except Exception as e:                                         # noqa: BLE001
                raw, err = None, "%s: %s" % (type(e).__name__, str(e)[:300])
            t_rcpt = self.clock.now()
            why = None
            if err:
                why = "EXIT_QUOTE_PROVIDER_FAILED: " + err
            elif raw is None:
                why = "EXIT_QUOTE_MISSING"
            else:
                try:
                    q = validate_quote(raw, contract=fl["contract"])
                    age = t_rcpt - q["timestamp_epoch"]
                    if age < 0:
                        why = "EXIT_QUOTE_FROM_THE_FUTURE: %.3fs" % age
                    elif age > MAX_SELECTED_QUOTE_AGE_S:
                        why = "STALE_SELECTED_CONTRACT: BID side %.3fs old at receipt" % age
                    elif q["bid"] <= 0:
                        why = "NO_BID"
                except RecordRefused as e:
                    why = str(e)
            out.update(exit_quote_request_epoch=t_req, exit_quote_receipt_epoch=t_rcpt,
                       exit_quote_observed=({k: q[k] for k in ("bid", "ask", "bid_size", "ask_size", "timestamp_epoch")} if q else None))
            if why:
                out.update(status="NOT_ESTIMABLE", pnl=None, why=why,
                           exit_law="a long leg exits at THAT contract's BID; missing/stale -> NOT_ESTIMABLE, never imputed")
            else:
                out.update(status="RESOLVED", exit_side="BID", exit_price=q["bid"],
                           pnl=round((q["bid"] - fl["price"]) * CONTRACT_MULTIPLIER, 2), entry_price=fl["price"],
                           fees="NOT_MODELLED_IN_THIS_BRICK")
        out["resolved_utc"] = self.clock.now_utc()
        assert_prospective(out)

        def build(rows):
            again = L.find(self.ledger, kind="pilot_outcome", rows=rows,
                           where=lambda r: (r.get("fill_ref") or {}).get("seq") == fill_receipt["seq"])
            if again:
                raise L.LedgerRefused("DUPLICATE_OUTCOME: fill seq %d already resolved at seq %d" % (fill_receipt["seq"], again[0][0]))
            return out

        try:
            receipt, fresh = L.commit_once(self.ledger, txn_id=txn_id, build=build, kind="pilot_outcome")
        except L.LedgerRefused as e:
            self.refuse("outcome", str(e), scan_id=scan_id)
        on_disk = out if fresh else L.read_all(self.ledger)[receipt["seq"] - 1]
        receipt.update(status=on_disk["status"], reconciled=not fresh, scan_id=scan_id)
        return receipt
