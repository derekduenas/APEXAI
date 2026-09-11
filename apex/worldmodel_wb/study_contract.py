"""What every proposed historical study must declare BEFORE any data access (M3).

A HistoricalStudyContract is a document, not permission: validating it produces a
digest that a later admission request can cite. Primary hypothesis: an improved
conditional forecast or a specified economic outcome. A planted-signal fixture
tests implementation sensitivity in that world only; a permutation control
receives inferential authority only when its transformation represents the
declared null under stated assumptions."""
from __future__ import annotations

from dataclasses import dataclass, field

from .contracts import ModelRefused, digest

REQUIRED = ("study_id", "primary_target", "primary_hypothesis", "comparator", "eligible_rows", "null_and_assumptions",
            "fitting_cadence", "parameter_budget", "selection_rule", "reporting_family", "horizon_minutes", "information_cutoff_rule",
            "dependence_inference", "search_budget")
REPORTING_FAMILIES = ("FORECAST_SCORE", "ECONOMIC_OUTCOME", "CALIBRATION")


@dataclass
class HistoricalStudyContract:
    study_id: str
    primary_target: str
    primary_hypothesis: str
    comparator: str
    eligible_rows: str
    null_and_assumptions: str
    fitting_cadence: str
    parameter_budget: int
    selection_rule: str
    reporting_family: str
    horizon_minutes: int
    information_cutoff_rule: str
    dependence_inference: str
    search_budget: int
    planned_comparisons: list = field(default_factory=list)
    planted_signal_fixture: str | None = None
    permutation_control: str | None = None
    notes: str = ""

    def validate(self) -> dict:
        missing = [k for k in REQUIRED if getattr(self, k) in (None, "", 0)]
        if missing:
            raise ModelRefused("STUDY_CONTRACT_INCOMPLETE: %s" % missing)
        if self.reporting_family not in REPORTING_FAMILIES:
            raise ModelRefused("REPORTING_FAMILY_UNKNOWN: %r" % self.reporting_family)
        if type(self.parameter_budget) is not int or self.parameter_budget <= 0 or type(self.search_budget) is not int or self.search_budget <= 0:
            raise ModelRefused("BUDGETS_MUST_BE_POSITIVE_INTS")
        if not self.planned_comparisons:
            raise ModelRefused("NO_PLANNED_COMPARISONS: every comparison is declared before access")
        body = {k: getattr(self, k) for k in REQUIRED + ("planned_comparisons", "planted_signal_fixture", "permutation_control")}
        return {"valid": True, "contract_digest": digest(body), "authorizes_data_access": False,
                "note": "a validated contract is a document a later admission request can cite; it grants nothing itself"}
