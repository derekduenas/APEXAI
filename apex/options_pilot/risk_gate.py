"""RISK SELF-ATTESTATION IS NOT AUTHORIZATION.

The previous boundary accepted any intent carrying `risk={"approved": True}`.
That is a caller asserting its own approval. Here approval is an object
produced by a RiskAuthority and BOUND to the intent it approves: the
authority computes a binding hash over the intent's identifying fields, and
the boundary recomputes it at intent persistence AND at execution. An
approval copied onto a different intent, or hand-written, refuses.

    ProductionRiskAuthority   -- REFUSES every intent in this brick. Integrating
                                 apex.organism.risk_certificate.certify() and
                                 apex.organism.risk_kernel.check() (limits,
                                 reservations, session drawdown halt) is the
                                 NEXT brick. Until then the production path
                                 cannot approve, so it cannot fill.
    SyntheticRiskAuthority    -- approves under an EXPLICIT synthetic harness
                                 only, stamps risk_provenance=SYNTHETIC_FIXTURE,
                                 and can be told to refuse for tests."""
from __future__ import annotations

from .records import canonical_hash, is_real

BINDING_FIELDS = ("intent_id", "session_id", "scan_id", "contract_id", "expression", "action", "quantity",
                  "signal_used", "forecast_id")
RISK_PROVENANCE = ("SYNTHETIC_FIXTURE", "CERTIFIED_KERNEL")


class RiskRefused(RuntimeError):
    pass


class RiskIntegrationMissing(RiskRefused):
    """The production risk authority is not integrated in this brick."""


def binding_hash(intent: dict) -> str:
    missing = [k for k in BINDING_FIELDS if k not in intent]
    if missing:
        raise RiskRefused("RISK_BINDING_FIELDS_MISSING: %s" % missing)
    fid = intent.get("forecast_id") or (intent.get("forecast_ref") or {}).get("forecast_id")
    return canonical_hash({**{k: intent[k] for k in BINDING_FIELDS if k != "forecast_id"}, "forecast_id": fid})


def _binding_view(intent: dict) -> dict:
    v = dict(intent)
    v.setdefault("forecast_id", (intent.get("forecast_ref") or {}).get("forecast_id"))
    return v


FEE_IDENTITY_FIELDS = ("schedule_id", "schedule_hash", "provenance", "known", "version", "effective_date", "terms_digest")


def fee_identity_of(intent: dict) -> dict:
    """The COMPLETE fee identity as carried on the intent. Every field appears; a missing one is explicitly absent
    (not defaulted) so the binding differs from an intent that carries it. UNEXPECTED keys are included under
    `__EXTRA__` so a term smuggled into the fee block changes the binding instead of sitting there unread."""
    f = intent.get("fees") or {}
    out = {k: (f[k] if k in f else "__ABSENT__") for k in FEE_IDENTITY_FIELDS}
    extra = {k: f[k] for k in sorted(f) if k not in FEE_IDENTITY_FIELDS}
    if extra:
        out["__EXTRA__"] = extra
    return out


def envelope_binding_hash(intent: dict) -> str:
    """Binds an approval to the risk ENVELOPE and the COMPLETE FEE IDENTITY as well as the intent identity.
    Previously this committed to `fee_schedule_id` alone, so an altered hash, provenance, known status, effective
    date or fee term left the binding unchanged and a persisted approval kept verifying."""
    env = intent.get("risk_envelope") or {}
    return canonical_hash({"binding": binding_hash(_binding_view(intent)),
                           "max_entry_price": env.get("max_entry_price"), "envelope_debit": env.get("envelope_debit"),
                           "fee_identity": fee_identity_of(intent)})


def verify_approval(intent: dict, approval, *, authority=None) -> dict:
    """Recompute the binding; refuse self-attestation and foreign approvals.
    With `authority`, ALSO require that the ACTIVE authority honours this
    approval: a stored synthetic approval is not authorization on a
    production boundary, at execution or on resume."""
    if not isinstance(approval, dict):
        raise RiskRefused("RISK_APPROVAL_NOT_A_RECORD: %r" % type(approval).__name__)
    if approval.get("approved") is not True:
        raise RiskRefused("RISK_NOT_APPROVED: %r" % (approval.get("why") or approval.get("reasons") or "no approval"))
    if approval.get("risk_provenance") not in RISK_PROVENANCE:
        raise RiskRefused("RISK_PROVENANCE_UNKNOWN: %r (a bare approved=True is self-attestation and is refused)"
                          % (approval.get("risk_provenance"),))
    if not isinstance(approval.get("authority_id"), str) or not approval["authority_id"]:
        raise RiskRefused("RISK_AUTHORITY_UNNAMED")
    expected = binding_hash(_binding_view(intent))
    if approval.get("binding_hash") != expected:
        raise RiskRefused("RISK_APPROVAL_NOT_BOUND_TO_THIS_INTENT: approval binds %r, intent is %r"
                          % (str(approval.get("binding_hash"))[:12], expected[:12]))
    if not is_real(approval.get("certified_max_loss")) or approval["certified_max_loss"] <= 0:
        raise RiskRefused("RISK_MAX_LOSS_INVALID: %r" % (approval.get("certified_max_loss"),))
    if "envelope_binding_hash" in approval and approval["envelope_binding_hash"] != envelope_binding_hash(intent):
        raise RiskRefused("RISK_APPROVAL_NOT_BOUND_TO_THIS_ENVELOPE_OR_FEE_IDENTITY: the approval commits to a different "
                          "envelope or fee identity than the intent now carries")
    # the approval's OWN recorded identity must equal the intent's, field by field: an approval whose identity block
    # was altered while its id was preserved is refused by name
    a_id, i_id = approval.get("fee_identity"), fee_identity_of(intent)
    if a_id is not None:
        if not isinstance(a_id, dict):
            raise RiskRefused("RISK_APPROVAL_FEE_IDENTITY_MALFORMED: %r" % type(a_id).__name__)
        for k in FEE_IDENTITY_FIELDS:
            if a_id.get(k, "__ABSENT__") != i_id[k]:
                raise RiskRefused("RISK_APPROVAL_FEE_IDENTITY_DISAGREES: %s approval=%r intent=%r"
                                  % (k, a_id.get(k, "__ABSENT__"), i_id[k]))
    if authority is not None:
        why = authority.accepts(approval)
        if why:
            raise RiskRefused("RISK_AUTHORITY_INCOMPATIBLE: %s" % why)
    return approval


class RiskAuthority:
    authority_id = "ABSTRACT"

    def approve(self, intent: dict, *, book=None) -> dict:               # pragma: no cover - interface
        raise NotImplementedError

    def accepts(self, approval: dict) -> str | None:                     # pragma: no cover - interface
        """None if this ACTIVE authority honours a stored approval, else the reason it does not."""
        raise NotImplementedError


class ProductionRiskAuthority(RiskAuthority):
    authority_id = "PRODUCTION_NOT_INTEGRATED"

    def accepts(self, approval: dict) -> str | None:
        return ("the production authority honours no stored approval in this brick (stored %r/%r is not production "
                "authorization; certify()/risk_kernel.check() integration is the next brick)"
                % (approval.get("risk_provenance"), approval.get("authority_id")))

    def approve(self, intent: dict, *, book=None) -> dict:
        raise RiskIntegrationMissing(
            "RISK_INTEGRATION_MISSING: the production path has no risk authority in this brick; "
            "apex.organism.risk_certificate.certify() + apex.organism.risk_kernel.check() integration "
            "(limits, reservations, drawdown halt) is the next brick. No intent can be approved here.")


class SyntheticRiskAuthority(RiskAuthority):
    """Only constructible with the explicit harness token."""
    authority_id = "SYNTHETIC_FIXTURE_AUTHORITY"

    def __init__(self, *, harness_token: str, max_loss: float = 250.0, refuse_with: str | None = None):
        if harness_token != "I_AM_A_SYNTHETIC_HARNESS":
            raise RiskRefused("SYNTHETIC_AUTHORITY_OUTSIDE_HARNESS")
        self.max_loss = float(max_loss)
        self.refuse_with = refuse_with

    def accepts(self, approval: dict) -> str | None:
        if approval.get("risk_provenance") != "SYNTHETIC_FIXTURE" or approval.get("authority_id") != self.authority_id:
            return "synthetic authority honours only its own SYNTHETIC_FIXTURE approvals, got %r/%r" % (
                approval.get("risk_provenance"), approval.get("authority_id"))
        return None

    def approve(self, intent: dict, *, book=None) -> dict:
        if self.refuse_with:
            return {"approved": False, "why": self.refuse_with, "risk_provenance": "SYNTHETIC_FIXTURE",
                    "authority_id": self.authority_id}
        return {"approved": True, "risk_provenance": "SYNTHETIC_FIXTURE", "authority_id": self.authority_id,
                "binding_hash": binding_hash(_binding_view(intent)), "certified_max_loss": self.max_loss,
                "note": "SYNTHETIC approval for orchestration tests; carries no risk certification"}
