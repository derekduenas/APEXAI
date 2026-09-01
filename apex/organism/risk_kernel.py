"""THE RISK KERNEL — the survival instinct. It sits BELOW the arena.

Capital Arena decides which opportunity deserves the next paper
dollar. This kernel decides whether the book can AFFORD it, and the
arena cannot override a kernel refusal -- allocation intelligence and
survival constraints are different organs on purpose.

Limits are PREDECLARED, dollar-denominated, and not tuned in this
project or from any observed outcome. Changing one is a dated,
operator-approved decision.

TWO DENOMINATIONS, DELIBERATELY SEPARATE.

  PLANNED RISK (declared_1R) -- what a sleeve intended to lose. The
  incumbent dollar caps below are denominated in this. They are SIZING
  constraints and remain ENGINEERING / PAPER limits. They are not
  ratified as live-capital percentages and they are not ruin
  constraints.

  CERTIFIED LOSS -- what the expression's structure actually makes
  possible. The semantically correct basis for aggregate exposure is
  the sum of INDEPENDENTLY VERIFIED certified_max_loss, never a sum of
  labels. That check is applied here for every position that carries
  certified authority, and becomes the primary basis once every funded
  class is certifiable.

CERTIFIED-RISK AUTHORITY IS NOT GRANTED BY A NUMBER. RISK-004 was not
answered with an invented notional or leverage cap: an unbounded short
does not become bounded by wearing a smaller label. Only
DEFINED_MAX_LOSS carries a certified budget. STOP_DEFINED and
UNBOUNDED remain research / paper observation, governed by the
engineering caps but never represented as finite certified risk.
NOT_ESTIMABLE refuses.

UPSTREAM CERTIFICATE GENERATION IS NOT AUTHORITY. The kernel receives
the position's PRIMARY FACTS and recomputes the certificate itself,
refusing on any disagreement. A certificate is evidence to inspect,
never a number to trust.

decision_power: STRUCTURAL_VETO_ONLY -- the kernel can only say no.
"""
from __future__ import annotations

from apex.organism.numeric_integrity import (RISK_CONTRACT,
                                             validate_risk_inputs,
                                             why_invalid, NON_NEGATIVE)
from apex.organism.risk_certificate import (CERTIFICATE_VERSION,
                                            NOT_ESTIMABLE, UNBOUNDED,
                                            verify)

THRESHOLD_SET = "ORGANISM_PAPER_V1"

STARTING_PAPER_CAPITAL = 10_000.0
MAX_RISK_PER_TRADE = 500.0        # covers every incumbent declared_1R
MAX_AGGREGATE_OPEN_RISK = 1_500.0  # three concurrent full-size stakes
MAX_SAME_UNDERLYING_RISK = 600.0
MAX_SAME_FAMILY_RISK = 1_000.0    # one beta family is one bet
SESSION_DRAWDOWN_HALT = 1_000.0   # -10 percent of start = stop funding

LIMITS = {"max_risk_per_trade": MAX_RISK_PER_TRADE,
          "max_aggregate_open_risk": MAX_AGGREGATE_OPEN_RISK,
          "max_same_underlying_risk": MAX_SAME_UNDERLYING_RISK,
          "max_same_family_risk": MAX_SAME_FAMILY_RISK,
          "session_drawdown_halt": SESSION_DRAWDOWN_HALT}

LIMIT_DENOMINATION = "PLANNED_RISK_DECLARED_1R"
CERTIFIED_AGGREGATE_BASIS = "SUM_OF_VERIFIED_CERTIFIED_MAX_LOSS"

LAW = ("the kernel only says no; allocation intelligence lives above "
       "it and cannot override it")


def _summary(certificate) -> dict:
    """What the Book seals alongside the funding: the bound, not the
    label. An absent certificate is stated, never omitted."""
    if not isinstance(certificate, dict):
        return {"certificate": "ABSENT"}
    return {k: certificate.get(k) for k in
            ("certificate_version", "certificate_hash", "risk_class",
             "certified_max_loss", "certified_risk_authority",
             "prime_v0_eligible", "research_observation_only",
             "planned_risk_amount", "planned_risk_basis",
             "gross_notional", "gap_exposed", "label_equals_bound",
             "upstream_declared_risk")}


def _refused(reasons: list, certificate=None) -> dict:
    return {"kind": "risk_kernel_check",
            "threshold_set": THRESHOLD_SET,
            "limit_denomination": LIMIT_DENOMINATION,
            "approved": False, "refusals": reasons, "warnings": [],
            "economic_risk": _summary(certificate),
            "law": LAW, "decision_power": "STRUCTURAL_VETO_ONLY"}


def check(*, declared_risk: float, symbol: str, beta_family: str,
          open_risk: float, same_underlying_risk: float,
          same_family_risk: float, session_realized_pnl: float,
          available_capital: float, open_certified_risk: float,
          certificate: dict, expression: str, direction: str,
          sleeve_payload: dict | None) -> dict:
    """One candidate against every survival constraint.

    `certificate` and the position's primary facts are all REQUIRED and
    have no defaults. A default would be a fail-open bypass of the law
    that a position has no recognized risk budget until its expression
    produces an auditable economic bound -- and every fail-open found
    in this money path so far has been a default nobody passed."""
    # 1. INPUT INTEGRITY (RISK_INPUT_INTEGRITY_V2). NaN defeats every
    # ">" comparison silently and a negative size passes all of them,
    # so a malformed input was APPROVED with zero refusals. The kernel
    # owns the survival veto, so it validates EVERY quantity its
    # comparisons depend on rather than trusting an upstream module.
    violations = validate_risk_inputs(
        declared_risk=declared_risk, open_risk=open_risk,
        same_underlying_risk=same_underlying_risk,
        same_family_risk=same_family_risk,
        session_realized_pnl=session_realized_pnl,
        available_capital=available_capital)
    bad_cert_agg = why_invalid("open_certified_risk",
                               open_certified_risk, NON_NEGATIVE)
    if bad_cert_agg:
        violations.append(bad_cert_agg)
    if violations:
        return _refused([f"{RISK_CONTRACT}: {v}" for v in violations],
                        certificate)

    # 2. THE CERTIFICATE IS RECOMPUTED, NOT TRUSTED.
    if not isinstance(certificate, dict) or \
            certificate.get("certificate_version") != \
            CERTIFICATE_VERSION:
        return _refused(
            [f"NO_RISK_CERTIFICATE: a {CERTIFICATE_VERSION} is "
             f"required before any risk budget is recognized"],
            certificate)
    disagreements = verify(certificate, expression=expression,
                           direction=direction,
                           declared_risk=declared_risk,
                           sleeve_payload=sleeve_payload)
    if disagreements:
        return _refused(
            [f"CERTIFICATE_NOT_INDEPENDENTLY_VERIFIED: {d}"
             for d in disagreements], certificate)

    # 3. ECONOMIC RISK SEMANTICS. A label is not a risk bound.
    if certificate.get("risk_class") == NOT_ESTIMABLE:
        return _refused(
            ["UNCERTIFIABLE_ECONOMIC_RISK: "
             + "; ".join(certificate.get("refusals") or ["no reason"])
             + " -- absence of a bound refuses, it does not approve"],
            certificate)

    refusals, warnings = [], []
    certified = certificate.get("certified_max_loss")
    has_authority = bool(certificate.get("certified_risk_authority"))

    # 4. PLANNED-RISK CAPS. Unchanged, and unchanged on purpose: these
    # remain engineering / paper limits and are not ratified as
    # live-capital percentages.
    if declared_risk > MAX_RISK_PER_TRADE:
        refusals.append(f"declared_risk {declared_risk:.2f} exceeds "
                        f"max_risk_per_trade {MAX_RISK_PER_TRADE:.2f}")
    if open_risk + declared_risk > MAX_AGGREGATE_OPEN_RISK:
        refusals.append(f"aggregate open risk would reach "
                        f"{open_risk + declared_risk:.2f} > "
                        f"{MAX_AGGREGATE_OPEN_RISK:.2f}")
    if same_underlying_risk + declared_risk > MAX_SAME_UNDERLYING_RISK:
        refusals.append(f"{symbol} risk would reach "
                        f"{same_underlying_risk + declared_risk:.2f} > "
                        f"{MAX_SAME_UNDERLYING_RISK:.2f}")
    if beta_family != "UNKNOWN" and \
            same_family_risk + declared_risk > MAX_SAME_FAMILY_RISK:
        refusals.append(f"{beta_family} family risk would reach "
                        f"{same_family_risk + declared_risk:.2f} > "
                        f"{MAX_SAME_FAMILY_RISK:.2f}")
    if session_realized_pnl <= -SESSION_DRAWDOWN_HALT:
        refusals.append(f"session drawdown "
                        f"{session_realized_pnl:.2f} has breached the "
                        f"halt {-SESSION_DRAWDOWN_HALT:.2f}: no new "
                        f"funding this session")
    if declared_risk > available_capital:
        refusals.append(f"declared_risk {declared_risk:.2f} exceeds "
                        f"available capital {available_capital:.2f}")

    # 5. CERTIFIED AGGREGATE. The semantically correct basis: a sum of
    # verified bounds, not a sum of labels. Applies only where a bound
    # exists, because a bound is the only thing that can be summed.
    if has_authority and isinstance(certified, (int, float)):
        total = open_certified_risk + certified
        if total > MAX_AGGREGATE_OPEN_RISK:
            refusals.append(
                f"aggregate CERTIFIED loss would reach {total:.2f} > "
                f"{MAX_AGGREGATE_OPEN_RISK:.2f} "
                f"({CERTIFIED_AGGREGATE_BASIS})")

    # 6. UNCERTIFIED CLASSES. Recorded, never silently promoted. No
    # invented notional cap converts an unbounded position into a
    # bounded one, so the honest action is to fund it in the research
    # lane with its status stamped into the chain.
    if not has_authority:
        warnings.append(
            f"NO_CERTIFIED_RISK_AUTHORITY: {symbol} {expression} "
            f"{direction} is risk_class "
            f"{certificate.get('risk_class')} -- RESEARCH / PAPER "
            f"OBSERVATION ONLY, not PRIME-V0 eligible, and may never "
            f"be represented as carrying a finite certified max loss. "
            f"Gross notional {certificate.get('gross_notional')} is "
            f"governed by no certified limit.")
        if certificate.get("risk_class") == UNBOUNDED:
            warnings.append(
                "UNBOUNDED_STRUCTURAL_LOSS: no upper bound on the "
                "repurchase price exists; admission to certified risk "
                "requires STOP_DEFINED_RISK_MODEL_V1 earned on real "
                "gap and slippage evidence, never a relabelling")

    return {"kind": "risk_kernel_check",
            "threshold_set": THRESHOLD_SET,
            "limit_denomination": LIMIT_DENOMINATION,
            "certified_aggregate_basis": CERTIFIED_AGGREGATE_BASIS,
            "approved": not refusals,
            "refusals": refusals,
            "warnings": warnings,
            "economic_risk": _summary(certificate),
            "law": LAW,
            "decision_power": "STRUCTURAL_VETO_ONLY"}
