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
from .book import Book, load_book
from .clock import Clock, ClockRefused, check_reading, to_utc_string
from .exit_policy import EXIT_POLICY_V1, ExitPolicy
from .fees import EXECUTION_POLICY_V1, UNVERIFIED_FEES, ExecutionPolicy, FeeSchedule
from .records import (FORECAST_FRESHNESS_S, INTENT_TTL_S, RecordRefused, assert_prospective, canonical_hash, labels_for,
                      validate_forecast, validate_intent, validate_quote)

MAX_SELECTED_QUOTE_AGE_S = 15.0
CONTRACT_MULTIPLIER = 100.0
ELIGIBILITY_POLICY = ("QUOTE_ELIGIBILITY_V2: age at receipt in [0, 15s] (receipt >= intent persisted, so provider ts is "
                      "within 15s before the intent); selected contract+side finite, uncrossed, exact-int size >= 1; "
                      "intent unexpired (TTL 120s)")
COMMIT_CHECKS = ("inside the fill transaction, from one snapshot: no existing fill; no expiry/cancellation record; session "
                 "not closed; intent + forecast history re-verified; authorization re-verified against the active "
                 "authority and provenance; forecast eligible NOW (target in the future, cutoff within 120s); clock <= "
                 "intent expiry; whole chain verifies. A time-based failure here persists the terminal transition")
ORDER_PROOF = ("ledger seq proves intent persisted BEFORE the quote was requested; it does NOT prove the provider "
               "generated the quote after the intent -- the provider timestamp is recorded as asserted")


class BoundaryRefused(RuntimeError):
    """Refused at the boundary. `.persisted` says whether the refusal record landed."""

    def __init__(self, msg: str, *, persisted: bool, receipt: dict | None = None):
        super().__init__(msg)
        self.persisted = persisted
        self.receipt = receipt


def is_real_env(env) -> bool:
    return isinstance(env, dict) and isinstance(env.get("max_entry_price"), (int, float)) and not isinstance(env.get("max_entry_price"), bool)


class _CommitRefused(L.LedgerRefused):
    """Raised inside a fill's commit transaction. `terminal_kind` names the
    terminal transition that must be persisted (expiry / cancellation) when
    the reason is a TIME-based eligibility failure; None for structural ones."""

    def __init__(self, problem: str, *, terminal_kind: str | None = None):
        super().__init__(problem)
        self.problem = problem
        self.terminal_kind = terminal_kind


class Boundary:
    """One boundary = one ledger + one controlled clock + one provenance +
    one risk authority + one session identity."""

    def __init__(self, ledger, *, clock: Clock, provenance: str, risk_authority: RG.RiskAuthority,
                 session_id: str, release: str, fee_schedule: FeeSchedule = UNVERIFIED_FEES,
                 execution_policy: ExecutionPolicy = EXECUTION_POLICY_V1, exit_policy: ExitPolicy = EXIT_POLICY_V1):
        self.ledger = ledger
        self.clock = clock
        self.labels = labels_for(provenance)
        self.risk = risk_authority
        self.session_id = session_id
        self.release = release
        self.fee_schedule = fee_schedule
        self.execution_policy = execution_policy
        self.exit_policy = exit_policy

    def book(self, rows: list | None = None) -> Book:
        return load_book(self.ledger, session_id=self.session_id, rows=rows,
                         fee_schedules={self.fee_schedule.schedule_id: self.fee_schedule})

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
        if fr.get("data_provenance") != self.labels["data_provenance"]:
            self.refuse("intent", "PROVENANCE_INCOMPATIBLE: forecast %r vs boundary %r"
                        % (fr.get("data_provenance"), self.labels["data_provenance"]), scan_id=scan_id)
        created = self.clock.now()
        problem = self._forecast_eligibility_problem(fr, created, stage="INTENT")
        if problem:
            self.refuse("intent", problem, scan_id=scan_id)
        from .risk_authority import envelope_for
        envelope = envelope_for(reference_ask=intent.get("reference_ask"), quantity=1)
        if not envelope["feasible"]:
            self.refuse("intent", envelope["why_infeasible"], scan_id=scan_id)
        fees = {"schedule_id": self.fee_schedule.schedule_id, "schedule_hash": self.fee_schedule.schedule_hash,
                "provenance": self.fee_schedule.provenance, "known": self.fee_schedule.known}
        try:
            body = validate_intent(intent, forecast=fr, forecast_receipt=forecast_receipt, signal_used=signal_used,
                                   session_id=self.session_id, scan_id=scan_id, release=self.release, created_epoch=created,
                                   risk_envelope=envelope, fees=fees,
                                   execution_policy={"policy_id": self.execution_policy.policy_id,
                                                     "policy_hash": self.execution_policy.policy_hash,
                                                     "max_fill_attempts": self.execution_policy.max_fill_attempts})
        except RecordRefused as e:
            self.refuse("intent", str(e), scan_id=scan_id)
        try:
            approval = self.risk.approve(body, book=self.book())
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
            # ATOMIC RESERVATION: the kernel is re-run against the Book AS OF THIS SNAPSHOT, under the lock, so two
            # concurrent intents cannot both pass on a stale state. The intent record IS the reservation.
            if hasattr(self.risk, "kernel_check") and body["risk"].get("certificate"):
                fresh = self.book(rows)
                kc = self.risk.kernel_check(body, body["risk"]["certificate"], fresh)
                if not kc.get("approved"):
                    raise L.LedgerRefused("RISK_LIMIT_AT_COMMIT: " + "; ".join(kc.get("refusals") or ["no reason"]))
                body["risk"]["kernel_check_at_commit"] = kc
                body["risk"]["book_state_hash_at_commit"] = fresh.state_hash()
                body["risk"]["book_summary_at_commit"] = fresh.summary()
            body["persisted_utc"] = self.clock.now_utc()
            body["persisted_epoch"] = self.clock.now()
            return body

        try:
            receipt, fresh = L.commit_once(self.ledger, txn_id=body["txn_id"], build=build, kind="pilot_intent")
        except L.LedgerRefused as e:
            self.refuse("intent", str(e), refs={"forecast_seq": forecast_receipt["seq"]}, scan_id=scan_id)
        receipt.update(contract_id=body["contract_id"], intent_id=body["intent_id"], scan_id=scan_id)
        return receipt

    # ------------------------------------------------------------ authorization compatibility
    def authorization_problem(self, it: dict) -> str | None:
        """A stored approval is authorization only if (a) it binds to this
        intent, (b) the intent's provenance matches this boundary's, and
        (c) the ACTIVE authority honours it. A synthetic approval on a
        production boundary fails (c); a LIVE_FEED intent on a synthetic
        boundary (or the reverse) fails (b)."""
        if it.get("data_provenance") != self.labels["data_provenance"]:
            return "PROVENANCE_INCOMPATIBLE: intent %r vs boundary %r" % (it.get("data_provenance"), self.labels["data_provenance"])
        try:
            RG.verify_approval(it, it.get("risk"), authority=self.risk)
        except RG.RiskRefused as e:
            return "INTENT_RISK_ON_DISK_%s" % e
        return None

    # ------------------------------------------------------------ 3+4. quote then fill
    @staticmethod
    def _forecast_eligibility_problem(fr: dict, now: float, *, stage: str) -> str | None:
        """The COMPLETE forecast eligibility policy (FORECAST_ELIGIBILITY_V1)
        against a clock reading: target still in the future AND input cutoff
        within the freshness window. Applied at intent creation and at
        new-fill eligibility (before the quote and inside the commit)."""
        ep = fr.get("epoch") or {}
        end, cut = ep.get("target_end"), ep.get("input_cutoff")
        if not isinstance(end, (int, float)) or now >= end:
            return "FORECAST_TARGET_ENDED_BEFORE_%s: clock %s, target_end %r" % (stage, to_utc_string(now), end)
        if not isinstance(cut, (int, float)) or now - cut > FORECAST_FRESHNESS_S:
            return "FORECAST_STALE_BEFORE_%s: input cutoff %.1fs before clock > %.0fs policy" % (
                stage, now - cut if isinstance(cut, (int, float)) else float("inf"), FORECAST_FRESHNESS_S)
        return None

    def _history_problem(self, intent_receipt: dict, rows: list, *, for_new_fill: bool) -> tuple:
        """Everything that must be true of the persisted intent and the
        history it references, checked against ONE snapshot of rows.
        Returns (reason_or_None, intent_record, forecast_record, terminal_kind).

        for_new_fill=False: IDENTITY and INTEGRITY only -- receipt, contract,
            session, release, provenance, forecast reference/agreement,
            content, stored risk binding. This is what reconciling an
            EXISTING fill requires; it does not require the forecast to
            still be current.
        for_new_fill=True: additionally the ACTIVE authority must honour the
            approval, the intent must be unexpired and the forecast must be
            eligible NOW (target in the future, cutoff fresh). Time-based
            failures name the terminal transition to persist."""
        try:
            it = L.verify_receipt(self.ledger, intent_receipt, expected_kind="pilot_intent", rows=rows)
        except L.LedgerRefused as e:
            return "INTENT_REF_%s" % e, None, None, None
        if it.get("contract_id") != intent_receipt.get("contract_id"):
            return "INTENT_CONTRACT_MISMATCH: disk %r vs receipt %r" % (it.get("contract_id"), intent_receipt.get("contract_id")), it, None, None
        if it.get("session_id") != self.session_id:
            return "INTENT_FROM_OTHER_SESSION: %r vs %r" % (it.get("session_id"), self.session_id), it, None, None
        if it.get("release") != self.release:
            return "INTENT_FROM_OTHER_RELEASE: %r vs %r" % (it.get("release"), self.release), it, None, None
        if it.get("data_provenance") != self.labels["data_provenance"]:
            return "PROVENANCE_INCOMPATIBLE: intent %r vs boundary %r" % (it.get("data_provenance"), self.labels["data_provenance"]), it, None, None
        fref = it.get("forecast_ref") or {}
        f_receipt = {"path": intent_receipt["path"], "seq": fref.get("seq"), "entry_hash": fref.get("entry_hash")}
        try:
            fr = L.verify_receipt(self.ledger, f_receipt, expected_kind="pilot_forecast", rows=rows)
        except L.LedgerRefused as e:
            return "INTENT_FORECAST_%s" % e, it, None, None
        if fr.get("forecast_hash") != fref.get("forecast_hash") or fr.get("forecast_id") != fref.get("forecast_id"):
            return "INTENT_FORECAST_HASH_MISMATCH", it, fr, None
        if fr.get("symbol") != it["contract"]["symbol"] or fr.get("session_id") != it.get("session_id") \
                or fr.get("scan_id") != it.get("scan_id"):
            return "INTENT_FORECAST_DISAGREE: symbol/session/scan", it, fr, None
        if fr.get("horizon_minutes") != 15 or it.get("horizon_relationship") is None:
            return "INTENT_HORIZON_UNDECLARED", it, fr, None
        exp_right = "CALL" if it.get("signal_used") == "LONG" else "PUT" if it.get("signal_used") == "SHORT" else None
        if exp_right is None or it["contract"]["right"] != exp_right or it.get("action") != "BUY" or it.get("quantity") != 1:
            return "INTENT_CONTENT_DISAGREE: signal/right/action/quantity", it, fr, None
        try:
            RG.verify_approval(it, it.get("risk"), authority=self.risk if for_new_fill else None)
        except RG.RiskRefused as e:
            return "INTENT_RISK_ON_DISK_%s" % e, it, fr, None
        if not for_new_fill:
            return None, it, fr, None
        now = self.clock.now()
        if not isinstance(it.get("expiry_epoch"), (int, float)):
            return "INTENT_EXPIRY_MISSING", it, fr, None
        if now > it["expiry_epoch"]:
            return "INTENT_EXPIRED: clock %.3f > expiry %.3f" % (now, it["expiry_epoch"]), it, fr, "pilot_intent_expired"
        problem = self._forecast_eligibility_problem(fr, now, stage="EXECUTION")
        if problem:
            return problem, it, fr, "pilot_intent_cancelled"
        return None, it, fr, None

    def _verify_intent_identity(self, intent_receipt: dict, *, stage: str, rows: list) -> tuple:
        why, it, fr, _term = self._history_problem(intent_receipt, rows, for_new_fill=False)
        if why:
            self.refuse(stage, why, refs={"intent_receipt": intent_receipt}, scan_id=(it or {}).get("scan_id"))
        return it, fr

    def _require_new_fill_eligibility(self, intent_receipt: dict, it: dict, *, rows: list) -> None:
        """Before the quote: a time-based failure persists its terminal
        transition (mutually exclusive with fills, see expire_intent), then
        refuses; a structural failure refuses only."""
        why, _it, _fr, term = self._history_problem(intent_receipt, rows, for_new_fill=True)
        if why:
            if term:
                self.expire_intent(intent_receipt, it, why=why, kind=term)
            self.refuse("fill", why, refs={"intent_receipt": intent_receipt}, scan_id=it.get("scan_id"))

    @staticmethod
    def _terminal(rows: list, intent_id: str) -> list:
        return [(i + 1, r) for i, r in enumerate(rows)
                if r.get("kind") in ("pilot_intent_expired", "pilot_intent_cancelled") and r.get("intent_id") == intent_id]

    def _session_closed(self, rows: list) -> list:
        return [(i + 1, r) for i, r in enumerate(rows)
                if r.get("kind") == "pilot_session_close" and r.get("session_id") == self.session_id]

    def _reconcile_fill(self, seq: int, on_disk: dict, *, intent_receipt: dict, it: dict, rows: list) -> dict:
        """A fill already on disk is returned ONLY after it, its chain and its
        references verify. A matching txn_id is not enough."""
        try:
            L.verify_receipt(self.ledger, {"path": str(self.ledger), "seq": seq, "entry_hash": on_disk.get("entry_hash")},
                             expected_kind="pilot_fill", rows=rows)
            L.verify_chain(self.ledger, rows=rows)            # the WHOLE ledger: a re-hashed record breaks its successor's link
        except L.LedgerRefused as e:
            self.refuse("fill", "RECONCILE_ALTERED: existing fill seq %d: %s" % (seq, e), scan_id=it.get("scan_id"))
        ref = on_disk.get("intent_ref") or {}
        if ref.get("seq") != intent_receipt["seq"] or ref.get("entry_hash") != intent_receipt["entry_hash"] \
                or on_disk.get("contract_id") != it.get("contract_id") or on_disk.get("session_id") != self.session_id \
                or on_disk.get("intent_id") != it.get("intent_id"):
            self.refuse("fill", "RECONCILE_REFERENCES_DISAGREE: fill seq %d does not reference this intent" % seq,
                        scan_id=it.get("scan_id"))
        return {"path": str(self.ledger), "seq": seq, "entry_hash": on_disk.get("entry_hash"), "kind": "pilot_fill",
                "receipt": "RECONCILED: fill for this intent already on disk, chain- and reference-verified; no second append",
                "status": on_disk.get("status"), "decision": on_disk.get("decision"), "why": on_disk.get("why"),
                "reconciled": True, "intent_id": it.get("intent_id"), "scan_id": it.get("scan_id"), "fill_id": on_disk.get("fill_id"),
                "attempt": on_disk.get("attempt")}

    @staticmethod
    def fill_attempts(rows: list, intent_seq: int) -> list:
        return [(i + 1, r) for i, r in enumerate(rows)
                if r.get("kind") == "pilot_fill" and (r.get("intent_ref") or {}).get("seq") == intent_seq]

    @staticmethod
    def finishing_attempt(attempts: list):
        """The attempt that FINISHED the intent: FILLED, or a terminal REFUSE. WAIT attempts do not finish it."""
        for seq, r in attempts:
            if r.get("status") == "FILLED" or r.get("decision") == "REFUSE":
                return seq, r
        return None

    def execute_intent(self, *, intent_receipt: dict, quote_fn) -> dict:
        """Verify the persisted intent and its history, THEN obtain the
        quote, THEN commit ONE fill attempt exactly once. Attempts are
        numbered; a WAIT attempt leaves the intent open for a re-quote
        (bounded by the execution policy and the intent TTL); FILLED and
        REFUSE finish it. The final commit RE-CHECKS, inside the
        transaction, everything that could have changed while the quote was
        in flight."""
        with L.transaction(self.ledger):
            rows = L.read_all(self.ledger)
        it, _fr = self._verify_intent_identity(intent_receipt, stage="fill", rows=rows)
        scan_id, intent_id = it.get("scan_id"), it.get("intent_id")
        contract = it["contract"]
        attempts = self.fill_attempts(rows, intent_receipt["seq"])
        done = self.finishing_attempt(attempts)
        # 1. HISTORICAL RECEIPT RECONCILIATION comes first and needs identity + integrity only.
        if done:
            return self._reconcile_fill(done[0], done[1], intent_receipt=intent_receipt, it=it, rows=rows)
        terminal = self._terminal(rows, intent_id)
        if terminal:
            self.refuse("fill", "INTENT_TERMINAL: %s at seq %d" % (terminal[0][1]["kind"], terminal[0][0]), scan_id=scan_id)
        closed = self._session_closed(rows)
        if closed:
            self.refuse("fill", "SESSION_CLOSED: close record at seq %d" % closed[0][0], scan_id=scan_id)
        if len(attempts) >= self.execution_policy.max_fill_attempts:
            why_x = "REQUOTES_EXHAUSTED: %d attempts under %s" % (len(attempts), self.execution_policy.policy_id)
            self.expire_intent(intent_receipt, it, why=why_x, kind="pilot_intent_cancelled")
            self.refuse("fill", why_x, scan_id=scan_id)
        attempt = len(attempts) + 1
        txn_id = "fill:%s:%d" % (intent_id, attempt)
        # 2. ELIGIBILITY FOR A NEW FILL: active authority, intent unexpired, forecast eligible NOW.
        self._require_new_fill_eligibility(intent_receipt, it, rows=rows)
        t_request = self.clock.now()
        provider_error = None
        try:
            raw = quote_fn(contract)
        except Exception as e:                                             # noqa: BLE001 - provider failures fail closed
            raw, provider_error = None, "%s: %s" % (type(e).__name__, str(e)[:300])
        t_receipt = self.clock.now()                                       # freshness measured AFTER receipt
        if t_receipt > it["expiry_epoch"]:
            why_exp = "INTENT_EXPIRED_DURING_QUOTE: receipt %.3f > expiry %.3f" % (t_receipt, it["expiry_epoch"])
            self.expire_intent(intent_receipt, it, why=why_exp)
            self.refuse("fill", why_exp, scan_id=scan_id)
        why, quote, decision = None, None, None
        if provider_error:
            why, decision = "QUOTE_PROVIDER_FAILED: " + provider_error, "REFUSE"
        else:
            try:
                quote = validate_quote(raw, contract=contract)
            except RecordRefused as e:
                why, decision = str(e), "REFUSE"
        env = it.get("risk_envelope") or {}
        latency = self.execution_policy.simulated_latency_s
        t_exec = t_receipt + latency                                       # simulated execution instant
        if why is None:
            age = t_receipt - quote["timestamp_epoch"]
            age_exec = t_exec - quote["timestamp_epoch"]
            if age < 0:
                why, decision = "QUOTE_FROM_THE_FUTURE: age at receipt %.3fs" % age, "REFUSE"
            elif age_exec > MAX_SELECTED_QUOTE_AGE_S:
                why, decision = ("STALE_SELECTED_CONTRACT: ASK side %.3fs old at receipt (%.3fs at simulated execution) > %.0fs"
                                 % (age, age_exec, MAX_SELECTED_QUOTE_AGE_S)), "WAIT"
            elif quote["ask_size"] < 1:
                why, decision = "NO_SIZE_AT_ASK", "WAIT"
            elif is_real_env(env) and quote["ask"] > env["max_entry_price"]:
                why, decision = ("ASK_ABOVE_ENVELOPE: executable ask %.2f > reserved max_entry_price %.2f"
                                 % (quote["ask"], env["max_entry_price"])), "WAIT"
        fill = {"kind": "pilot_fill", "txn_id": txn_id, "attempt": attempt, "intent_id": intent_id, "scan_id": scan_id,
                "session_id": self.session_id, "release": self.release,
                "intent_ref": {"seq": intent_receipt["seq"], "entry_hash": intent_receipt["entry_hash"], "intent_id": intent_id},
                "contract": contract, "contract_id": it["contract_id"], "quantity_intended": 1,
                "quote_request_epoch": t_request, "quote_request_utc": to_utc_string(t_request),
                "quote_receipt_epoch": t_receipt, "quote_receipt_utc": to_utc_string(t_receipt),
                "simulated_execution_epoch": t_exec, "simulated_latency_s": latency,
                "provider_latency_s": t_receipt - t_request,
                "quote_observed": ({k: quote[k] for k in ("bid", "ask", "bid_size", "ask_size", "timestamp_epoch",
                                                          "timestamp_utc", "timestamp_meaning")} if quote else None),
                "quote_age_at_receipt_s": (t_receipt - quote["timestamp_epoch"]) if quote else None,
                "quote_ts_minus_intent_persisted_s": (quote["timestamp_epoch"] - it["persisted_epoch"]) if quote else None,
                "risk_envelope": env or None,
                "execution_policy": {"policy_id": self.execution_policy.policy_id, "policy_hash": self.execution_policy.policy_hash},
                "simulated": True, "fill_label": self.execution_policy.fill_label,
                "eligibility_policy": ELIGIBILITY_POLICY, "order_proof": ORDER_PROOF,
                "history_verified": "intent + referenced forecast re-read, chain-verified, content-agreed, authorization "
                                    "checked against the ACTIVE authority and provenance -- before the quote AND again "
                                    "inside the commit transaction",
                "commit_checks": COMMIT_CHECKS, **self.labels}
        if why is not None:
            fill.update(status="UNFILLED", decision=decision, why=why, quantity_filled=0, net_debit=0.0,
                        fees_entry=None, cashflow_entry=0.0)
        else:
            px = quote["ask"]
            fee = self.fee_schedule.entry(1)
            debit = round(px * CONTRACT_MULTIPLIER, 2)
            fill.update(status="FILLED", decision="TRADE", quantity_filled=1, side_crossed="ASK", price=px, net_debit=debit,
                        fees_entry=fee, cashflow_entry=(round(-(debit + fee["total"]), 2) if fee["total"] is not None else None),
                        cashflow_law="cashflow_entry = -(ask x multiplier x quantity + entry fees); fees charged exactly once here",
                        fill_law="long leg pays THAT contract's ASK; no midpoint, no model price")
        fill["fill_id"] = canonical_hash({"txn_id": txn_id, "status": fill["status"]})[:24]

        def build(rows):
            # THE STATE THE FILL CLAIMS IS ESTABLISHED HERE, UNDER THE LOCK, FROM THIS SNAPSHOT.
            again = self.finishing_attempt(self.fill_attempts(rows, intent_receipt["seq"]))
            if again:
                raise L.LedgerRefused("DUPLICATE_DELIVERY: intent seq %d already finished by fill seq %d" % (intent_receipt["seq"], again[0]))
            if len(self.fill_attempts(rows, intent_receipt["seq"])) + 1 != attempt:
                raise L.LedgerRefused("ATTEMPT_NUMBER_RACED: intent seq %d" % intent_receipt["seq"])
            term = self._terminal(rows, intent_id)
            if term:
                raise L.LedgerRefused("INTENT_TERMINAL_AT_COMMIT: %s at seq %d (cancellation/expiry won the race)"
                                      % (term[0][1]["kind"], term[0][0]))
            cl = self._session_closed(rows)
            if cl:
                raise L.LedgerRefused("SESSION_CLOSED_AT_COMMIT: close record at seq %d" % cl[0][0])
            problem, _it2, _fr2, term_kind = self._history_problem(intent_receipt, rows, for_new_fill=True)
            if problem:
                raise _CommitRefused("%s_AT_COMMIT: %s" % ("INELIGIBLE" if term_kind else "HISTORY_INVALID", problem), terminal_kind=term_kind)
            try:
                L.verify_chain(self.ledger, rows=rows)
            except L.ChainBroken as e:
                raise L.LedgerRefused("HISTORY_INVALID_AT_COMMIT: %s" % e)
            t_commit = self.clock.now()
            fill["committed_utc"] = to_utc_string(t_commit)
            fill["committed_epoch"] = t_commit
            if fill["status"] == "FILLED":
                fill["exit_schedule"] = self.exit_policy.schedule(t_commit)
            assert_prospective(fill)
            return fill

        try:
            receipt, fresh = L.commit_once(self.ledger, txn_id=txn_id, build=build, kind="pilot_fill")
        except _CommitRefused as e:
            if e.terminal_kind:
                self.expire_intent(intent_receipt, it, why=e.problem, kind=e.terminal_kind)
            self.refuse("fill", e.problem, refs={"intent_seq": intent_receipt["seq"]}, scan_id=scan_id)
        except L.LedgerRefused as e:
            self.refuse("fill", str(e), refs={"intent_seq": intent_receipt["seq"]}, scan_id=scan_id)
        if not fresh:                                                      # lost-ack reconciliation
            rows = L.read_all(self.ledger)
            return self._reconcile_fill(receipt["seq"], rows[receipt["seq"] - 1], intent_receipt=intent_receipt, it=it, rows=rows)
        receipt.update(status=fill["status"], decision=fill["decision"], why=fill.get("why"), intent_id=intent_id,
                       scan_id=scan_id, fill_id=fill["fill_id"], attempt=attempt)
        return receipt

    def expire_intent(self, intent_receipt: dict, it: dict, *, why: str, kind: str = "pilot_intent_expired") -> dict:
        """Terminal transition (expired / cancelled). Mutually exclusive with
        a fill: inside the transaction, an existing fill or terminal record
        for this intent refuses the transition."""
        rec = {"kind": kind, "txn_id": "%s:%s" % (kind, it["intent_id"]), "intent_id": it["intent_id"],
               "intent_ref": {"seq": intent_receipt["seq"], "entry_hash": intent_receipt["entry_hash"]},
               "scan_id": it.get("scan_id"), "session_id": it.get("session_id"), "release": it.get("release"),
               "terminated_by_session": self.session_id, "why": why,
               "at_utc": self.clock.now_utc(), "at_epoch": self.clock.now(), **self.labels}
        assert_prospective(rec)

        def build(rows):
            try:
                L.verify_receipt(self.ledger, intent_receipt, expected_kind="pilot_intent", rows=rows)
            except L.LedgerRefused as e:
                raise L.LedgerRefused("TERMINAL_REF_%s" % e)
            filled = self.finishing_attempt(self.fill_attempts(rows, intent_receipt["seq"]))   # a WAIT attempt is not a fill
            if filled:
                raise L.LedgerRefused("FILL_EXISTS: intent seq %d has fill seq %d; cannot %s a filled intent"
                                      % (intent_receipt["seq"], filled[0], kind))
            term = self._terminal(rows, it["intent_id"])
            if term:
                raise L.LedgerRefused("INTENT_ALREADY_TERMINAL: %s at seq %d" % (term[0][1]["kind"], term[0][0]))
            return rec

        try:
            receipt, _ = L.commit_once(self.ledger, txn_id=rec["txn_id"], build=build, kind=kind)
        except L.LedgerRefused as e:
            self.refuse("terminal", str(e), refs={"intent_seq": intent_receipt["seq"]}, scan_id=it.get("scan_id"))
        return receipt

    # ------------------------------------------------------------ 5. outcome
    @staticmethod
    def discharging_outcomes(rows: list, fill_seq: int) -> list:
        return [(i + 1, r) for i, r in enumerate(rows) if r.get("kind") == "pilot_outcome"
                and (r.get("fill_ref") or {}).get("seq") == fill_seq and r.get("discharges_position") is True]

    @staticmethod
    def valuation_attempts(rows: list, fill_seq: int) -> list:
        return [(i + 1, r) for i, r in enumerate(rows) if r.get("kind") == "pilot_outcome"
                and (r.get("fill_ref") or {}).get("seq") == fill_seq]

    def _reconcile_outcome(self, seq: int, on_disk: dict, *, fill_receipt: dict, rows: list, scan_id) -> dict:
        try:
            L.verify_receipt(self.ledger, {"path": str(self.ledger), "seq": seq, "entry_hash": on_disk.get("entry_hash")},
                             expected_kind="pilot_outcome", rows=rows)
            L.verify_chain(self.ledger, rows=rows)
        except L.LedgerRefused as e:
            self.refuse("outcome", "RECONCILE_ALTERED: existing outcome seq %d: %s" % (seq, e), scan_id=scan_id)
        if (on_disk.get("fill_ref") or {}).get("seq") != fill_receipt["seq"] \
                or (on_disk.get("fill_ref") or {}).get("entry_hash") != fill_receipt["entry_hash"]:
            self.refuse("outcome", "RECONCILE_REFERENCES_DISAGREE: outcome seq %d" % seq, scan_id=scan_id)
        return {"path": str(self.ledger), "seq": seq, "entry_hash": on_disk.get("entry_hash"), "kind": "pilot_outcome",
                "receipt": "RECONCILED: outcome already on disk, chain- and reference-verified; no second append",
                "status": on_disk.get("status"), "pnl": on_disk.get("pnl"), "reconciled": True, "scan_id": scan_id,
                "discharges_position": on_disk.get("discharges_position"), "attempt": on_disk.get("attempt")}

    def record_exit_exhausted(self, fill_receipt: dict) -> dict:
        """The AUTOMATIC exit policy stops trying. The position REMAINS an unresolved obligation."""
        rows = L.read_all(self.ledger)
        fl = L.verify_receipt(self.ledger, fill_receipt, expected_kind="pilot_fill", rows=rows)
        rec = {"kind": "pilot_exit_exhausted", "txn_id": "exit_exhausted:%s" % fl["intent_id"], "intent_id": fl["intent_id"],
               "fill_ref": {"seq": fill_receipt["seq"], "entry_hash": fill_receipt["entry_hash"]}, "scan_id": fl.get("scan_id"),
               "session_id": self.session_id, "release": self.release, "attempts": len(self.valuation_attempts(rows, fill_receipt["seq"])),
               "exit_policy": self.exit_policy.describe(), "obligation": "POSITION REMAINS UNRESOLVED; P&L UNKNOWN; exposure open",
               "at_utc": self.clock.now_utc(), **self.labels}
        assert_prospective(rec)

        def build(rows):
            if self.discharging_outcomes(rows, fill_receipt["seq"]):
                raise L.LedgerRefused("POSITION_ALREADY_DISCHARGED: fill seq %d" % fill_receipt["seq"])
            return rec
        try:
            receipt, _ = L.commit_once(self.ledger, txn_id=rec["txn_id"], build=build, kind="pilot_exit_exhausted")
        except L.LedgerRefused as e:
            self.refuse("exit", str(e), scan_id=fl.get("scan_id"))
        return receipt

    def record_outcome(self, *, fill_receipt: dict, exit_quote_fn, recovery: bool = False) -> dict:
        """One VALUATION ATTEMPT for a fill. RESOLVED and NO_POSITION discharge
        the position; NOT_ESTIMABLE (missing/stale/malformed exit, provider
        failure) is persisted as an attempt and the position REMAINS an
        unresolved obligation. A later attempt may discharge it; once
        discharged, further calls reconcile to the discharging record."""
        rows = L.read_all(self.ledger)
        try:
            fl = L.verify_receipt(self.ledger, fill_receipt, expected_kind="pilot_fill", rows=rows)
        except L.LedgerRefused as e:
            self.refuse("outcome", "FILL_REF_%s" % e, refs={"fill_receipt": fill_receipt})
        scan_id = fl.get("scan_id")
        if fl.get("session_id") != self.session_id:
            self.refuse("outcome", "FILL_FROM_OTHER_SESSION", scan_id=scan_id)
        if fl.get("data_provenance") != self.labels["data_provenance"]:
            self.refuse("outcome", "PROVENANCE_INCOMPATIBLE: fill %r vs boundary %r"
                        % (fl.get("data_provenance"), self.labels["data_provenance"]), scan_id=scan_id)
        done = self.discharging_outcomes(rows, fill_receipt["seq"])
        if done:
            return self._reconcile_outcome(done[0][0], done[0][1], fill_receipt=fill_receipt, rows=rows, scan_id=scan_id)
        attempt = len(self.valuation_attempts(rows, fill_receipt["seq"])) + 1
        txn_id = "outcome:%s:%d" % (fl["intent_id"], attempt)
        out = {"kind": "pilot_outcome", "txn_id": txn_id, "attempt": attempt, "intent_id": fl["intent_id"],
               "fill_id": fl.get("fill_id"), "scan_id": scan_id, "session_id": self.session_id, "release": self.release,
               "fill_ref": {"seq": fill_receipt["seq"], "entry_hash": fill_receipt["entry_hash"]},
               "contract_id": fl["contract_id"], **self.labels}
        if fl["status"] == "FILLED":
            # THE FROZEN EXIT POLICY governs WHEN a valuation may happen. A recovery run may attempt an exhausted or
            # late position, labelled as such; it may never value a position before it is due.
            committed = fl.get("committed_epoch")
            status = self.exit_policy.status(now=self.clock.now(), committed_epoch=committed, attempts=attempt - 1) \
                if isinstance(committed, (int, float)) else "UNSCHEDULED"
            if status == "NOT_DUE":
                self.refuse("outcome", "EXIT_NOT_DUE: clock %s < exit_due %s under %s"
                            % (self.clock.now_utc(), to_utc_string(committed + self.exit_policy.horizon_s), self.exit_policy.policy_id),
                            scan_id=scan_id)
            if status == "EXHAUSTED" and not recovery:
                self.refuse("outcome", "EXIT_WINDOW_EXHAUSTED: automatic attempts stopped; recovery attempt required", scan_id=scan_id)
            out.update(exit_policy={"policy_id": self.exit_policy.policy_id, "policy_hash": self.exit_policy.policy_hash},
                       exit_policy_status=status + ("_RECOVERY_ATTEMPT" if recovery else ""))
        if fl["status"] != "FILLED":
            out.update(status="NO_POSITION", pnl=0.0, why="intent was %s (%s)" % (fl["status"], fl.get("why")),
                       discharges_position=True)
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
                out.update(status="NOT_ESTIMABLE", pnl=None, why=why, discharges_position=False,
                           exit_law="a long leg exits at THAT contract's BID; missing/stale -> NOT_ESTIMABLE, never imputed; "
                                    "the position REMAINS an unresolved obligation until a later attempt discharges it")
            else:
                q_n = int(fl.get("quantity_filled", 1))
                fee_x = self.fee_schedule.exit(q_n)
                fee_e = (fl.get("fees_entry") or {}).get("total")
                credit = round(q["bid"] * CONTRACT_MULTIPLIER * q_n, 2)
                fees_known = fee_x["total"] is not None and fee_e is not None
                out.update(status="RESOLVED", exit_side="BID", exit_price=q["bid"], entry_price=fl["price"],
                           gross_pnl=round(credit - fl["net_debit"], 2), fees_exit=fee_x, fees_entry_ref=fee_e,
                           cashflow_exit=(round(credit - fee_x["total"], 2) if fee_x["total"] is not None else None),
                           pnl=(round(credit - fl["net_debit"] - fee_e - fee_x["total"], 2) if fees_known else None),
                           pnl_status=("NET_OF_FEES" if fees_known else "FEES_UNKNOWN"),
                           pnl_law="pnl = q x M x (exit bid - entry ask) - entry fees - exit fees; spread crossing is already in the "
                                   "quoted sides and is not subtracted again; fees charged exactly once per side",
                           discharges_position=True)
        out["resolved_utc"] = self.clock.now_utc()
        assert_prospective(out)

        def build(rows):
            if self.discharging_outcomes(rows, fill_receipt["seq"]):
                raise L.LedgerRefused("POSITION_ALREADY_DISCHARGED: fill seq %d" % fill_receipt["seq"])
            if len(self.valuation_attempts(rows, fill_receipt["seq"])) + 1 != attempt:
                raise L.LedgerRefused("ATTEMPT_NUMBER_RACED: fill seq %d" % fill_receipt["seq"])
            try:
                L.verify_receipt(self.ledger, fill_receipt, expected_kind="pilot_fill", rows=rows)
                L.verify_chain(self.ledger, rows=rows)
            except L.LedgerRefused as e:
                raise L.LedgerRefused("HISTORY_INVALID_AT_COMMIT: %s" % e)
            return out

        try:
            receipt, fresh = L.commit_once(self.ledger, txn_id=txn_id, build=build, kind="pilot_outcome")
        except L.LedgerRefused as e:
            rows = L.read_all(self.ledger)
            done = self.discharging_outcomes(rows, fill_receipt["seq"])
            if done and str(e).startswith("POSITION_ALREADY_DISCHARGED"):
                return self._reconcile_outcome(done[0][0], done[0][1], fill_receipt=fill_receipt, rows=rows, scan_id=scan_id)
            self.refuse("outcome", str(e), scan_id=scan_id)
        if not fresh:
            rows = L.read_all(self.ledger)
            return self._reconcile_outcome(receipt["seq"], rows[receipt["seq"] - 1], fill_receipt=fill_receipt, rows=rows, scan_id=scan_id)
        receipt.update(status=out["status"], pnl=out.get("pnl"), reconciled=False, scan_id=scan_id,
                       discharges_position=out["discharges_position"], attempt=attempt)
        return receipt
