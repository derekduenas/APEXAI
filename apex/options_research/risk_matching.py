"""Risk/Delta/Capital-matched comparison panels — F O14. Superiority is
never declared from raw return-on-premium; every comparison happens
inside one of these three matched panels.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

from apex.options_research import OPTIONS_RESEARCH_POWER

PANELS = ("RISK_MATCHED", "DELTA_MATCHED", "CAPITAL_MATCHED")


class RiskMatchingError(RuntimeError):
    pass


@dataclass(frozen=True)
class MatchedComparison:
    panel: str
    candidates: tuple            # expression_type per candidate, in the comparison
    matched_quantity: str        # what was held equal, in words
    matched_values: dict         # candidate -> the matched quantity's value
    decision_power: str = OPTIONS_RESEARCH_POWER

    def __post_init__(self):
        if self.panel not in PANELS:
            raise RiskMatchingError(f"unknown panel {self.panel!r}")

    def as_record(self) -> dict:
        return asdict(self)


def risk_matched_panel(candidates: dict) -> MatchedComparison:
    """`candidates`: {expression_type: max_loss}. Scales nothing --
    this is a DIAGNOSTIC record of what each candidate's own governed
    max loss already is, for the caller to compare like-for-like."""
    return MatchedComparison(panel="RISK_MATCHED", candidates=tuple(candidates),
                             matched_quantity="maximum / stop-defined dollar loss",
                             matched_values=dict(candidates))


def delta_matched_panel(candidates: dict) -> MatchedComparison:
    return MatchedComparison(panel="DELTA_MATCHED", candidates=tuple(candidates),
                             matched_quantity="initial underlying-equivalent delta",
                             matched_values=dict(candidates))


def capital_matched_panel(candidates: dict) -> MatchedComparison:
    return MatchedComparison(panel="CAPITAL_MATCHED", candidates=tuple(candidates),
                             matched_quantity="deployed cash/margin",
                             matched_values=dict(candidates))


def all_three_panels(*, max_loss: dict, delta: dict, capital: dict) -> tuple:
    """Runs all three matching schemes -- callers must not use only one
    and declare a winner."""
    return (risk_matched_panel(max_loss), delta_matched_panel(delta),
           capital_matched_panel(capital))
