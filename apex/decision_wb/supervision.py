"""PRIME-late decision supervision (M5): ACT or ABSTAIN with named reasons; production authority NONE.

Prerequisites (each must be present and satisfied, else ABSTAIN PREREQUISITE_MISSING):
    forecast (a ForecastObject with a density), snapshot (twin state with field ages), expression
    comparison (M4 record), risk decision (kernel check), book summary; regime and simulation are
    optional inputs that, when present, may trigger abstention.

Abstention reasons: STALE_DATA, UNSUPPORTED_STATE, MODEL_DISAGREEMENT, QUOTE_UNCERTAINTY,
INSUFFICIENT_MARGIN, VALUE_UNESTABLISHED, RISK_LIMIT, PREREQUISITE_MISSING. "Confidence" is never
a universal percentage: the record carries p_return_gt_zero with its definition."""
from __future__ import annotations

from dataclasses import dataclass, field

from apex.worldmodel_wb.contracts import ForecastObject, UnsupportedOutput, digest

POLICY_ID = "PRIME_SUPERVISION_V0_SYNTHETIC"


@dataclass(frozen=True)
class SupervisionPolicy:
    max_bar_age_s: float = 120.0
    max_disagreement_ratio: float = 0.5
    max_spread_rel: float = 0.15
    min_expected_net_pnl: float = 0.0
    require_value_established: bool = True
    fields: tuple = field(default=("max_bar_age_s", "max_disagreement_ratio", "max_spread_rel", "min_expected_net_pnl", "require_value_established"))

    def describe(self) -> dict:
        d = {k: getattr(self, k) for k in self.fields}
        return {**d, "policy_id": POLICY_ID, "policy_digest": digest(d)}


def supervise(*, forecast: ForecastObject | None, snapshot: dict | None, comparison: dict | None, risk_decision: dict | None,
              book_summary: dict | None, regime: dict | None = None, candidate_label: str | None = None,
              policy: SupervisionPolicy = SupervisionPolicy()) -> dict:
    reasons = []
    missing = [n for n, v in (("forecast", forecast), ("snapshot", snapshot), ("comparison", comparison), ("risk_decision", risk_decision),
                              ("book_summary", book_summary)) if v is None]
    if missing:
        return _out("ABSTAIN", ["PREREQUISITE_MISSING: %s" % missing], policy, None, candidate_label)
    try:
        dens = forecast.density()
    except UnsupportedOutput as e:
        return _out("ABSTAIN", ["PREREQUISITE_MISSING: forecast supplies no density (%s)" % e], policy, None, candidate_label)
    age = (snapshot.get("fields", {}).get("last_bar_age_s") or {}).get("value")
    if age is None or age > policy.max_bar_age_s:
        reasons.append("STALE_DATA: last bar age %r > %.0fs" % (age, policy.max_bar_age_s))
    if regime and regime.get("abstain"):
        reasons.append("UNSUPPORTED_STATE: %s" % regime.get("abstain_why"))
    dis = forecast.meta.get("model_disagreement_ratio")
    if dis is not None and dis > policy.max_disagreement_ratio:
        reasons.append("MODEL_DISAGREEMENT: ratio %.3f > %.2f" % (dis, policy.max_disagreement_ratio))
    cand = next((c for c in comparison.get("candidates", []) if c.get("label") == candidate_label), None) if candidate_label else None
    if candidate_label and cand is None:
        reasons.append("PREREQUISITE_MISSING: candidate %r not in the comparison" % candidate_label)
    if cand:
        if cand.get("status") != "ELIGIBLE":
            reasons.append("QUOTE_UNCERTAINTY: candidate rejected (%s)" % cand.get("why"))
        else:
            if (cand.get("entry_spread_rel") or 0) > policy.max_spread_rel:
                reasons.append("QUOTE_UNCERTAINTY: relative spread %.3f > %.2f" % (cand["entry_spread_rel"], policy.max_spread_rel))
            if policy.require_value_established and not cand.get("expected_value_established"):
                reasons.append("VALUE_UNESTABLISHED: %s" % comparison.get("expected_value_note"))
            elif cand.get("expected_net_pnl", 0.0) <= policy.min_expected_net_pnl:
                reasons.append("INSUFFICIENT_MARGIN: expected net %.2f <= %.2f" % (cand.get("expected_net_pnl", 0.0), policy.min_expected_net_pnl))
    if not risk_decision.get("approved"):
        reasons.append("RISK_LIMIT: %s" % (risk_decision.get("refusals") or risk_decision.get("why")))
    if book_summary.get("integrity_problems"):
        reasons.append("PREREQUISITE_MISSING: book integrity problems %s" % book_summary["integrity_problems"][:2])
    p_up = forecast.meta.get("p_return_gt_zero")
    return _out("ABSTAIN" if reasons else "ACT", reasons, policy, {"p_return_gt_zero": p_up, "meaning": forecast.meta.get("p_meaning", "P(target return > 0) under the forecast density"),
                                                                     "density_family": dens.get("family")}, candidate_label)


def _out(decision, reasons, policy, confidence, candidate_label) -> dict:
    return {"kind": "prime_supervision", "decision": decision, "reasons": reasons, "candidate": candidate_label,
            "confidence": confidence, "policy": policy.describe(), "authority": "NONE: a proposal record; no order, no funding, no override of Risk",
            "layer": "PRIME-late: after forecasts, simulation, expression economics, Arena, Risk and Book"}
