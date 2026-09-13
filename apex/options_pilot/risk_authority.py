"""CERTIFIED RISK AUTHORITY (M1) — the real certificate and kernel, wired.

`ProductionRiskAuthority` refused everything because nothing recomputed risk.
This authority does, using the organism's actual primitives with their real
signatures:

    apex.organism.risk_certificate.certify(expression, direction, declared_risk, sleeve_payload)
    apex.organism.risk_kernel.check(declared_risk, symbol, beta_family, open_risk, same_underlying_risk,
                                    same_family_risk, session_realized_pnl, available_capital,
                                    open_certified_risk, certificate, expression, direction, sleeve_payload)

The approval binds to the exact intent (binding hash over the intent's
identifying fields), to the risk ENVELOPE (max entry price -> envelope
debit, the conservative bound reserved before any quote is seen), to the
fee schedule, and to the Book state it was computed against. The boundary
re-runs the kernel check against the FRESH Book inside the intent's commit
transaction, so concurrent intents cannot jointly exceed the limits.

It is still not operational authority: the limits are the kernel's
predeclared paper limits, the fee schedule must be PROVIDER_VERIFIED for a
LIVE_FEED boundary, and independent review decides commissioning."""
from __future__ import annotations

from apex.organism import risk_certificate as RC
from apex.organism import risk_kernel as RK

from .book import CONTRACT_MULTIPLIER, Book
from .fees import identity_problem, FeeSchedule
from .records import canonical_hash, is_real
from .risk_gate import RiskAuthority, RiskRefused, _binding_view, binding_hash, envelope_binding_hash

CERTIFIED_PROVENANCE = "CERTIFIED_KERNEL"
AUTHORITY_ID = "%s+%s" % (RC.CERTIFICATE_VERSION, RK.THRESHOLD_SET)
ENVELOPE_POLICY = ("RISK_ENVELOPE_V1: max_entry_price = min(reference_ask x (1 + 10%) when an indicative reference ask "
                   "is present, kernel max_risk_per_trade / multiplier); envelope_debit = max_entry_price x multiplier x "
                   "quantity; the executable ASK must be <= max_entry_price or the attempt is WAIT")
ENVELOPE_BUFFER = 0.10


def entry_cap_price() -> float:
    """The kernel's per-trade cap expressed per share: the ONLY capital fact the expression rule may consult."""
    return RK.MAX_RISK_PER_TRADE / CONTRACT_MULTIPLIER


def envelope_for(*, reference_ask, quantity: int = 1) -> dict:
    cap_price = RK.MAX_RISK_PER_TRADE / CONTRACT_MULTIPLIER
    feasible, why = True, None
    if is_real(reference_ask) and reference_ask > 0:
        if reference_ask > cap_price:
            price, basis = round(cap_price, 2), "REFERENCE_ABOVE_CAP"
            feasible, why = False, ("RISK_ENVELOPE_INFEASIBLE: indicative ask %.2f > kernel cap %.2f per contract "
                                    "(max_risk_per_trade %.0f / multiplier %.0f); no executable ask can fit the envelope"
                                    % (reference_ask, cap_price, RK.MAX_RISK_PER_TRADE, CONTRACT_MULTIPLIER))
        else:
            price = round(min(reference_ask * (1.0 + ENVELOPE_BUFFER), cap_price), 2)
            basis = "REFERENCE_ASK_PLUS_BUFFER" if reference_ask * (1.0 + ENVELOPE_BUFFER) <= cap_price else "KERNEL_CAP"
    else:
        price, basis = round(cap_price, 2), "KERNEL_CAP_NO_REFERENCE"
    return {"max_entry_price": price, "envelope_debit": round(price * CONTRACT_MULTIPLIER * quantity, 2),
            "reference_ask": reference_ask if is_real(reference_ask) else None, "basis": basis, "policy": ENVELOPE_POLICY,
            "feasible": feasible, "why_infeasible": why,
            "reference_note": "an indicative reference ask is NOT executable and is never a fill price"}


class CertifiedRiskAuthority(RiskAuthority):
    authority_id = AUTHORITY_ID

    def __init__(self, *, fee_schedule: FeeSchedule, provenance: str):
        self.fee_schedule = fee_schedule
        self.provenance = provenance

    # -------------------------------------------------- what this authority honours
    def accepts(self, approval: dict) -> str | None:
        if approval.get("risk_provenance") != CERTIFIED_PROVENANCE or approval.get("authority_id") != self.authority_id:
            return "certified authority honours only %s/%s approvals, got %r/%r" % (
                CERTIFIED_PROVENANCE, self.authority_id, approval.get("risk_provenance"), approval.get("authority_id"))
        # COMPLETE identity, through the ONE comparison. This used to carry its own seven-field tuple and so kept
        # honouring approvals after the identity grew to twelve -- including approvals issued under a DIFFERENT
        # operator authorization.
        return identity_problem(self.fee_schedule.identity(), approval.get("fee_identity"),
                                what="this approval")

    # -------------------------------------------------- certificate + kernel
    def _sleeve(self, intent: dict) -> dict:
        env = intent["risk_envelope"]
        c = intent["contract"]
        return {"legs": [("BUY", c["right"], float(c["strike"]), float(env["max_entry_price"]))],
                "multiplier": CONTRACT_MULTIPLIER, "contracts": int(intent["quantity"]),
                "net_debit": float(env["envelope_debit"]), "expiration": c["expiration"]}

    def kernel_check(self, intent: dict, certificate: dict, book: Book) -> dict:
        env = intent["risk_envelope"]
        c = intent["contract"]
        ri = book.risk_inputs(symbol=c["symbol"])
        return RK.check(declared_risk=float(env["envelope_debit"]), symbol=c["symbol"], beta_family=ri["beta_family"],
                        open_risk=ri["open_risk"], same_underlying_risk=ri["same_underlying_risk"],
                        same_family_risk=ri["same_family_risk"], session_realized_pnl=ri["session_realized_pnl"],
                        available_capital=ri["available_capital"], open_certified_risk=ri["open_certified_risk"],
                        certificate=certificate, expression=intent["expression"], direction=self._direction(intent),
                        sleeve_payload=self._sleeve(intent))

    @staticmethod
    def _direction(intent: dict) -> str:
        return "LONG" if intent["expression"] == "LONG_CALL" else "SHORT"

    def fee_identity(self) -> dict:
        """The COMPLETE canonical identity of the schedule THIS authority gates on. Sealed on every approval and
        committed to by the envelope binding."""
        return self.fee_schedule.identity()

    def fee_identity_problem(self, intent: dict) -> str | None:
        """The intent must CARRY the fee identity the boundary will seal, and it must be this authority's schedule,
        matched on id, hash, provenance and known-ness. Missing or mismatched REFUSES."""
        return identity_problem(self.fee_identity(), intent.get("fees"),
                                what="the intent's fee block (authority holds %s)" % self.fee_schedule.schedule_id)

    def approve(self, intent: dict, *, book: Book | None = None) -> dict:
        if book is None:
            raise RiskRefused("BOOK_STATE_REQUIRED: the certified authority approves only against a Book")
        # ONE FEE SCHEDULE IDENTITY (Part 1 finding A). The authority used to gate on ITS OWN schedule while the
        # boundary sealed a different one on the very intent being approved, and nothing compared them: an intent
        # whose record said the cost was UNKNOWN could be APPROVED as LIVE_FEED. The identity carried on the intent
        # is now verified against this authority's schedule BY HASH before anything else.
        problem = self.fee_identity_problem(intent)
        if problem:
            return {"approved": False, "risk_provenance": CERTIFIED_PROVENANCE, "authority_id": self.authority_id,
                    "why": problem, "fee_identity": self.fee_identity()}
        if self.provenance == "LIVE_FEED" and self.fee_schedule.provenance != "PROVIDER_VERIFIED":
            return {"approved": False, "risk_provenance": CERTIFIED_PROVENANCE, "authority_id": self.authority_id,
                    "why": "FEE_SCHEDULE_UNVERIFIED: %s (%s); an unknown cost is not zero, so no LIVE_FEED intent is approved"
                           % (self.fee_schedule.schedule_id, self.fee_schedule.provenance)}
        if not self.fee_schedule.known:
            return {"approved": False, "risk_provenance": CERTIFIED_PROVENANCE, "authority_id": self.authority_id,
                    "why": "FEE_SCHEDULE_UNKNOWN: %s" % self.fee_schedule.schedule_id, "fee_identity": self.fee_identity()}
        # SOURCE VERIFIED IS NOT OPERATOR AUTHORIZED. Checked here, before the certificate, the kernel, the
        # envelope and any quote -- an unauthorized cost model never reaches an intent, however it was supplied.
        _auth = self.fee_schedule.authorization_state()
        if _auth["status"] != "AUTHORIZED":
            return {"approved": False, "risk_provenance": CERTIFIED_PROVENANCE, "authority_id": self.authority_id,
                    "why": "FEE_SCHEDULE_NOT_AUTHORIZED: %s -- %s" % (_auth["status"], _auth["why"]),
                    "authorization_status": _auth["status"], "fee_identity": self.fee_identity()}
        env = intent.get("risk_envelope") or {}
        _fee_identity = self.fee_identity()
        if not is_real(env.get("max_entry_price")) or env["max_entry_price"] <= 0:
            return {"approved": False, "risk_provenance": CERTIFIED_PROVENANCE, "authority_id": self.authority_id,
                    "why": "RISK_ENVELOPE_MISSING"}
        cert = RC.certify(expression=intent["expression"], direction=self._direction(intent),
                          declared_risk=float(env["envelope_debit"]), sleeve_payload=self._sleeve(intent))
        if cert.get("risk_class") != RC.DEFINED_MAX_LOSS:
            return {"approved": False, "risk_provenance": CERTIFIED_PROVENANCE, "authority_id": self.authority_id,
                    "why": "CERTIFICATE_REFUSED: %s" % "; ".join(cert.get("refusals") or ["no bound"]), "certificate": cert}
        kc = self.kernel_check(intent, cert, book)
        out = {"approved": bool(kc.get("approved")), "risk_provenance": CERTIFIED_PROVENANCE, "authority_id": self.authority_id,
               "binding_hash": binding_hash(_binding_view(intent)), "envelope_binding_hash": envelope_binding_hash(intent),
               "certified_max_loss": cert["certified_max_loss"], "certificate": cert, "kernel_check": kc,
               "book_state_hash": book.state_hash(), "book_summary": book.summary(),
               "fee_schedule_id": self.fee_schedule.schedule_id, "fee_schedule_hash": self.fee_schedule.schedule_hash,
               "fee_identity": _fee_identity, "fee_identity_verified_against_intent": True,
               "limits": dict(RK.LIMITS), "note": ("certificate recomputed from legs; kernel checked against the Book at approval "
                                                    "and re-checked against the FRESH Book inside the intent commit")}
        if not out["approved"]:
            out["why"] = "KERNEL_REFUSED: " + "; ".join(kc.get("refusals") or ["no reason"])
        return out
