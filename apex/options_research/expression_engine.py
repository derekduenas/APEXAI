"""OptionExpressionEngine — F O17: the orchestrator. Produces an
ExpressionResearchDecision, never a trade. Composes forward_distribution
+ horizon + cohorts + refusal + expression_candidate -- invents no new
physics, fetches no data itself, and never sets decision_power to
anything other than NONE_OPTIONS_RESEARCH.

MECHANISM TAGGING LAW (F O18): every option candidate that survives to
`candidates` must carry a real active mechanism id -- one with no
mechanism id, or only NO_OPTION_ADVANTAGE_MECHANISM, is refused via
REFUSE_NO_OPTION_ADVANTAGE_MECHANISM, never silently admitted.

Gate 12 (REFUSE_CAPITAL_MATCHED_INFERIOR) is NOT applied here: Pareto
dominance requires resolved outcome data this engine does not have
synchronously. It belongs to whatever consumes OptionExpressionOutcome
after prospective resolution, not to this eligibility pass.

ANALYTICS CERTIFICATION LAW: OPT-002/OPT-003 depend on APEX's own
computed surface pricing (apex.option_analytics), which stays refused
via REFUSE_ANALYTICS_NOT_VALIDATED until that package's adversarial
validation suite has been run and certified on its CURRENT source (see
apex.option_analytics.validation_registry -- code drift after
certification silently re-closes the gate, it is never left trusted
stale). OPT-001 needs no Greeks/IV and is not gated by this check.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

from apex.option_analytics.validation_registry import \
    is_adversarial_suite_certified
from apex.options_research import OPTIONS_RESEARCH_POWER
from apex.options_research import forward_distribution as forward_distribution_mod
from apex.options_research.cohorts import (HUNTER_REFUSED_INSUFFICIENT_STATE,
                                            classify_cohort)
from apex.options_research.expression_candidate import (NO_OPTION_ADVANTAGE,
                                                          no_trade_candidate,
                                                          stock_candidate)
from apex.options_research.horizon import horizon_eligible
from apex.options_research.refusal import refuse
from apex.options_research.surface_state import NO_SUPPORT, SUPPORTED

ANALYTICS_GATED_MECHANISM_IDS = ("OPT-002-RICH-WING-VERTICALIZATION",
                                 "OPT-003-APEX-FORWARD-VOL-GAP")


class ExpressionEngineError(RuntimeError):
    pass


@dataclass(frozen=True)
class ExpressionResearchDecision:
    subject: str
    known_from: str
    as_of: str
    cohort: str
    thesis: dict                 # UnderlyingForwardDistribution.as_record()
    horizon_check: dict | None
    candidates: tuple            # accepted OptionExpressionCandidate.as_record()s
    refusals: tuple              # RefusalVerdict.as_record()s
    decision_power: str = OPTIONS_RESEARCH_POWER

    def as_record(self) -> dict:
        return {"kind": "expression_research_decision", **asdict(self)}


def _surface_gate_checks(candidate, surface_state, *, subject, known_from,
                         max_no_support_features: int, max_spread_pct: float,
                         max_surface_freshness_s: float):
    """Returns a RefusalVerdict, or None if the surface passes every gate."""
    if surface_state is None:
        return refuse("REFUSE_INSUFFICIENT_SURFACE_DATA", subject=subject,
                      known_from=known_from,
                      candidate_expression_type=candidate.expression_type,
                      reason="no OptionSurfaceState supplied for this candidate")

    features = surface_state.features
    no_support = sum(1 for f in features.values() if f.get("status") == NO_SUPPORT)
    if no_support > max_no_support_features:
        return refuse("REFUSE_INSUFFICIENT_SURFACE_DATA", subject=subject,
                      known_from=known_from,
                      candidate_expression_type=candidate.expression_type,
                      reason=f"{no_support} surface features NO_SUPPORT")

    depth_liquid = any(features.get(k, {}).get("status") == SUPPORTED
                       for k in ("depth", "volume", "open_interest"))
    if not depth_liquid:
        return refuse("REFUSE_ILLIQUID_SURFACE", subject=subject, known_from=known_from,
                      candidate_expression_type=candidate.expression_type)

    spread_pct = features.get("spread_pct", {})
    if spread_pct.get("status") == SUPPORTED and spread_pct.get("value") is not None \
            and spread_pct["value"] > max_spread_pct:
        return refuse("REFUSE_EXCESSIVE_SPREAD_COST", subject=subject, known_from=known_from,
                      candidate_expression_type=candidate.expression_type,
                      reason=f"spread_pct={spread_pct['value']} > {max_spread_pct}")

    stale = [f["name"] for f in features.values()
            if f.get("status") == SUPPORTED and f.get("freshness_s") is not None
            and f["freshness_s"] > max_surface_freshness_s]
    if stale:
        return refuse("REFUSE_STALE_SURFACE_DATA", subject=subject, known_from=known_from,
                      candidate_expression_type=candidate.expression_type,
                      reason=f"stale features: {stale}")
    return None


def run(*, subject: str, now, known_from,
       hunter_present: bool, frontier_present: bool,
       hunter_state_sufficient: bool | None = None,
       candidate_dte: int | None = None,
       expected_realization_minutes: float | None = None,
       timing_uncertainty_minutes: float | None = None,
       stock_entry_price: float | None = None, stock_shares: int = 100,
       option_candidates: tuple = (), surface_state=None,
       max_no_support_features: int = 10, max_spread_pct: float = 0.15,
       max_surface_freshness_s: float = 120.0) -> ExpressionResearchDecision:
    """`max_no_support_features` defaults to 10 (of 15) -- the current
    market-data vendor's OPRA entitlement structurally cannot populate
    the IV/skew/smile/term-structure features (F O24), so a stricter
    default would refuse every real candidate tonight regardless of
    liquidity; illiquidity itself is still caught by the dedicated
    depth/volume/open_interest check below, independent of this count.
    `option_candidates`: OptionExpressionCandidate instances the
    caller has already constructed (real strikes/mechanism ids come
    from wherever that caller sources live chain data -- this engine
    fetches none of it). Each is admitted into `candidates` only if it
    clears every eligibility gate below; otherwise it is refused, never
    silently dropped."""
    import pandas as pd
    now = pd.Timestamp(now)
    kf = str(pd.Timestamp(known_from))

    thesis = forward_distribution_mod.build(subject, now=now, known_from=known_from)
    cohort_v = classify_cohort(subject=subject, hunter_present=hunter_present,
                               frontier_present=frontier_present, known_from=known_from,
                               hunter_state_sufficient=hunter_state_sufficient)

    candidates = [no_trade_candidate(subject, known_from=known_from, now=now,
                                     reason="baseline first-class candidate, always present")]
    if stock_entry_price is not None:
        candidates.append(stock_candidate(subject, known_from=known_from, now=now,
                                          entry_price=stock_entry_price, shares=stock_shares))

    refusals = []

    thesis_ok = thesis.has_legitimate_thesis()
    if not thesis_ok:
        refusals.append(refuse("REFUSE_INSUFFICIENT_UNDERLYING_THESIS", subject=subject,
                               known_from=known_from))

    horizon_check = None
    horizon_ok = False
    if candidate_dte is not None:
        horizon_check = horizon_eligible(
            dte=candidate_dte, expected_realization_minutes=expected_realization_minutes,
            timing_uncertainty_minutes=timing_uncertainty_minutes)
        horizon_ok = horizon_check["eligible"]
        if not horizon_ok:
            gate = ("REFUSE_ZERO_DTE_OUT_OF_SCOPE"
                    if horizon_check["reason"] == "SEPARATE_RESEARCH_BUCKET_NOT_ACTIVE_V1"
                    else "REFUSE_HORIZON_MISMATCH")
            refusals.append(refuse(gate, subject=subject, known_from=known_from,
                                   reason=horizon_check["reason"]))
    else:
        refusals.append(refuse("REFUSE_HORIZON_MISMATCH", subject=subject, known_from=known_from,
                               reason="no candidate expiry offered"))

    hunter_blocks_options = cohort_v.cohort == HUNTER_REFUSED_INSUFFICIENT_STATE

    for cand in option_candidates:
        if hunter_blocks_options:
            refusals.append(refuse("REFUSE_HUNTER_INSUFFICIENT_STATE", subject=subject,
                                   known_from=known_from,
                                   candidate_expression_type=cand.expression_type))
            continue
        if not thesis_ok:
            refusals.append(refuse("REFUSE_INSUFFICIENT_UNDERLYING_THESIS", subject=subject,
                                   known_from=known_from,
                                   candidate_expression_type=cand.expression_type))
            continue
        if not horizon_ok:
            gate = ("REFUSE_ZERO_DTE_OUT_OF_SCOPE"
                    if horizon_check and horizon_check["reason"] == "SEPARATE_RESEARCH_BUCKET_NOT_ACTIVE_V1"
                    else "REFUSE_HORIZON_MISMATCH")
            refusals.append(refuse(gate, subject=subject, known_from=known_from,
                                   candidate_expression_type=cand.expression_type))
            continue
        mech_ids = set(cand.research_mechanism_ids) - {NO_OPTION_ADVANTAGE}
        if not mech_ids:
            refusals.append(refuse("REFUSE_NO_OPTION_ADVANTAGE_MECHANISM", subject=subject,
                                   known_from=known_from,
                                   candidate_expression_type=cand.expression_type))
            continue
        if (mech_ids & set(ANALYTICS_GATED_MECHANISM_IDS)
                and not is_adversarial_suite_certified()):
            refusals.append(refuse("REFUSE_ANALYTICS_NOT_VALIDATED", subject=subject,
                                   known_from=known_from,
                                   candidate_expression_type=cand.expression_type))
            continue
        surface_refusal = _surface_gate_checks(
            cand, surface_state, subject=subject, known_from=known_from,
            max_no_support_features=max_no_support_features,
            max_spread_pct=max_spread_pct, max_surface_freshness_s=max_surface_freshness_s)
        if surface_refusal is not None:
            refusals.append(surface_refusal)
            continue
        candidates.append(cand)

    return ExpressionResearchDecision(
        subject=subject, known_from=kf, as_of=str(now), cohort=cohort_v.cohort,
        thesis=thesis.as_record(), horizon_check=horizon_check,
        candidates=tuple(c.as_record() for c in candidates),
        refusals=tuple(r.as_record() for r in refusals))
