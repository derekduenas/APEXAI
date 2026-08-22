"""OPTIONS_BEFORE_CARD — F O25/O26. Sealed BEFORE any future price is
known: opportunity id, thesis, surface state, eligible/rejected
structures, and a structural (not outcome-based) shadow ranking. This
card is append-only and is never rewritten once sealed -- outcome.py
resolves against the SAME opportunity_id in a separate, later ledger
row, never by mutating this one.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from apex.options_research import OPTIONS_RESEARCH_POWER

LEDGER = Path("results/options_research/before_cards.jsonl")

# fields that would leak future information are structurally forbidden
# from ever appearing on this dataclass -- enforced by test, not just
# by convention.
FORBIDDEN_FIELD_SUBSTRINGS = ("outcome", "realized", "pnl", "resolved", "actual_")


class BeforeCardError(RuntimeError):
    pass


@dataclass(frozen=True)
class OptionsBeforeCard:
    opportunity_id: str
    subject: str
    known_from: str
    underlying_thesis: dict
    direction_quality: str
    transition_quality: str
    horizon: dict
    surface_snapshot: dict
    cohort: str
    eligible_structures: tuple      # tuple of expression_type strings
    rejected_structures: tuple      # tuple of {"expression_type", "gate", "reason"}
    shadow_expression_ranking: tuple  # structural ranking, no outcome info
    ranking_rationale: str
    sealed_at: str
    decision_power: str = OPTIONS_RESEARCH_POWER

    def __post_init__(self):
        bad = {f for f in self.__dataclass_fields__
              if any(s in f.lower() for s in FORBIDDEN_FIELD_SUBSTRINGS)}
        if bad:
            raise BeforeCardError(
                f"OPTIONS_BEFORE_CARD may not carry future-outcome fields: {bad}")
        ranked = set(self.shadow_expression_ranking)
        eligible = set(self.eligible_structures)
        if not ranked <= eligible:
            raise BeforeCardError(
                "shadow_expression_ranking may only rank structures that "
                "are actually in eligible_structures")

    def as_record(self) -> dict:
        return {"kind": "options_before_card", **asdict(self)}


def seal(*, opportunity_id: str, subject: str, known_from,
        underlying_thesis: dict, direction_quality: str, transition_quality: str,
        horizon: dict, surface_snapshot: dict, cohort: str,
        eligible_structures: tuple, rejected_structures: tuple,
        shadow_expression_ranking: tuple, ranking_rationale: str,
        now) -> OptionsBeforeCard:
    import pandas as pd
    card = OptionsBeforeCard(
        opportunity_id=opportunity_id, subject=subject,
        known_from=str(pd.Timestamp(known_from)), underlying_thesis=underlying_thesis,
        direction_quality=direction_quality, transition_quality=transition_quality,
        horizon=horizon, surface_snapshot=surface_snapshot, cohort=cohort,
        eligible_structures=tuple(eligible_structures),
        rejected_structures=tuple(rejected_structures),
        shadow_expression_ranking=tuple(shadow_expression_ranking),
        ranking_rationale=ranking_rationale, sealed_at=str(pd.Timestamp(now)))
    from apex.governance.chain_ledger import chain_append
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    chain_append(LEDGER, card.as_record())
    return card
