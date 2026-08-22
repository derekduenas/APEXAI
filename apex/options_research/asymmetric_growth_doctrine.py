"""APEX OPTIONS -- ASYMMETRIC GROWTH DOCTRINE (operator directive,
2026-08-18, embedded before the sleeve went further into design).

The Options Research sleeve must NOT optimize for maximum win rate,
minimum variance, tiny incremental edge, passive income, cosmetic
Sharpe, or "safe" trades with poor upside asymmetry. Its objective is
to find rare, high-quality, positively asymmetric expressions that can
scale capital without creating material risk of ruin:

    AGGRESSIVE OPPORTUNITY CAPTURE
    + DEFINED / GOVERNED LOSS
    + EVIDENCE-EARNED SIZING
    = ACCOUNT SCALING

This module holds the doctrine text verbatim (for provenance and for
the Research Library) plus the ONE law this package can enforce
mechanically today: NO YOLO. Aggression means hunting real convexity
under governed loss, never the prohibited list below -- that list is
checked structurally (never trusted to a caller's self-report), the
same discipline as apex/options_research/refusal.py's REFUSE_* gates.

Every other doctrine concept (asymmetry profiling, scaling potential,
evidence-earned aggression, growth-panel research, rare-opportunity
classification) lives in its own module, per this package's one-
concept-per-file convention -- see asymmetry_profile.py,
scaling_potential.py, edge_maturity.py, growth_panel.py,
rare_opportunity.py. None of them grant sizing or Capital authority;
every one of them is decision_power=NONE_OPTIONS_RESEARCH and
hardcodes sizing_authority="NONE" wherever the concept has a sizing-
shaped field.
"""
from __future__ import annotations

from apex.options_research import OPTIONS_RESEARCH_POWER

DOCTRINE_VERSION = "APEX_OPTIONS_ASYMMETRIC_GROWTH_DOCTRINE_V1"

# NO YOLO LAW (doctrine section 9). Aggression in OPPORTUNITY CAPTURE is
# not aggression in EVIDENCE OR RISK STANDARDS -- these remain
# structurally prohibited regardless of how strong a thesis looks.
NO_YOLO_PROHIBITIONS = (
    "FAR_OTM_LOTTERY_DEFAULT",
    "ZERO_DTE_BY_DEFAULT",
    "MAXIMUM_LEVERAGE",
    "ALL_IN_SIZING",
    "AVERAGING_DOWN",
    "MARTINGALE_SIZING",
    "UNBOUNDED_SHORT_GAMMA",
    "NAKED_TAIL_RISK_SELLING",
    "CONVICTION_OVERRIDE_OF_GOVERNED_LOSS",
)

# doctrine section 4: no single metric may be optimized in isolation --
# named here so callers/tests can enumerate the full required vector
# rather than picking a favorite.
REQUIRED_EXPECTANCY_METRICS = (
    "EXPECTANCY_R", "MEDIAN_R", "WIN_RATE", "AVG_WIN_R", "AVG_LOSS_R",
    "PAYOFF_RATIO", "RIGHT_TAIL_CONTRIBUTION", "LEFT_TAIL_CONTRIBUTION",
)

# doctrine section 6: aggression may only increase as evidence increases.
EVIDENCE_EARNED_AGGRESSION_LADDER = (
    "UNPROVEN", "OBSERVATIONAL", "PROSPECTIVE_EDGE", "STABLE_EDGE",
    "SCALABLE_EDGE",
)

# doctrine section 5: research scenarios only -- Capital retains
# sovereignty over any real production sizing decision.
GROWTH_RESEARCH_RISK_TIERS_PCT = (0.25, 0.50, 0.75, 1.00, 1.50, 2.00)
GROWTH_RESEARCH_LABEL = "RESEARCH_SCENARIO_NOT_PRODUCTION_SIZING"

# doctrine primary research question (section 12) -- not "do options
# beat stock" alone, but whether an APEX information edge can be
# transformed into materially larger geometric growth without
# materially increasing risk of ruin.
PRIMARY_RESEARCH_QUESTION = (
    "When APEX is unusually right, can options transform that "
    "information advantage into materially larger geometric account "
    "growth without materially increasing risk of ruin?"
)


class DoctrineViolation(RuntimeError):
    pass


def assert_no_yolo_violation(*, claimed_practices: tuple, subject: str) -> None:
    """Mechanically refuses if ANY of the prohibited practices are
    present among `claimed_practices` -- a caller cannot self-certify
    around this the way GATE 9 (no confirmatory credit spent, no
    fabricated evidence) cannot be self-certified around elsewhere in
    this package."""
    hit = set(claimed_practices) & set(NO_YOLO_PROHIBITIONS)
    if hit:
        raise DoctrineViolation(
            f"{subject}: NO YOLO LAW violated -- prohibited practice(s) "
            f"present: {sorted(hit)}. Aggression means hunting real "
            f"convexity under governed loss, never this.")


def doctrine_stamp() -> dict:
    return {"kind": "asymmetric_growth_doctrine_reference",
           "doctrine_version": DOCTRINE_VERSION,
           "primary_research_question": PRIMARY_RESEARCH_QUESTION,
           "decision_power": OPTIONS_RESEARCH_POWER,
           "sizing_authority": "NONE", "capital_authority": "NONE"}
