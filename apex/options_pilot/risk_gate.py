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
RISK_PROVENANCE = ("SYNTHETIC_FIXTURE",)


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


def verify_approval(intent: dict, approval) -> dict:
    """Recompute the binding; refuse self-attestation and foreign approvals."""
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
    return approval


class RiskAuthority:
    authority_id = "ABSTRACT"

    def approve(self, intent: dict) -> dict:                             # pragma: no cover - interface
        raise NotImplementedError


class ProductionRiskAuthority(RiskAuthority):
    authority_id = "PRODUCTION_NOT_INTEGRATED"

    def approve(self, intent: dict) -> dict:
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

    def approve(self, intent: dict) -> dict:
        if self.refuse_with:
            return {"approved": False, "why": self.refuse_with, "risk_provenance": "SYNTHETIC_FIXTURE",
                    "authority_id": self.authority_id}
        return {"approved": True, "risk_provenance": "SYNTHETIC_FIXTURE", "authority_id": self.authority_id,
                "binding_hash": binding_hash(_binding_view(intent)), "certified_max_loss": self.max_loss,
                "note": "SYNTHETIC approval for orchestration tests; carries no risk certification"}
