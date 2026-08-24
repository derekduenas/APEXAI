"""PATH INTELLIGENCE — output contract + realized-path recorder (V2 #2).

MISSION: stop treating a trade's future as only an endpoint. What
happens BETWEEN entry and exit -- how far against before how far in
favour, how long to invalidation, whether the target arrives before
theta or exhaustion does -- is a distribution, and that distribution is
what should eventually inform stops, targets, horizons, expressions and
sizing.

WHAT EXISTS TODAY, AND WHAT DELIBERATELY DOES NOT.

  THE CONTRACT exists: `PathForecast`, the shape every future path
  estimator must emit, with a pedigree on every field.

  THE RECORDER exists: `realized_path()` extracts what ACTUALLY
  happened from resolved outcomes -- append-only observation, the raw
  material calibration will one day be fitted against.

  THE ESTIMATOR does not exist. No prospective outcome data means any
  P(+2R before -1R) we wrote today would be an invented number wearing
  probability's clothes. The contract therefore refuses construction of
  a forecast whose numbers outrun its pedigree.

PATH INTELLIGENCE LAW. Pedigree is NOT_ESTIMABLE ->
ESTIMABLE_UNCALIBRATED -> CALIBRATED, and path probabilities receive no
decision authority below CALIBRATED. Until then: SHADOW.

decision_power: NONE_SHADOW.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

NOT_ESTIMABLE = "NOT_ESTIMABLE"

FORECAST_PEDIGREES = ("NOT_ESTIMABLE", "ESTIMABLE_UNCALIBRATED",
                      "CALIBRATED")

# The quantities every path estimator must eventually speak. Declared
# once, here, so estimators and calibrators cannot drift apart.
PATH_QUANTITIES = (
    "p_plus1R_before_minus1R",
    "p_plus2R_before_minus1R",
    "p_plus3R_before_minus1R",
    "p_invalidation_before_target",
    "expected_mae_R", "expected_mfe_R",
    "mae_quantiles_R", "mfe_quantiles_R",
    "time_to_invalidation_min", "time_to_1R_min",
    "p_unresolved_at_horizon",
    # options-specific
    "p_underlying_reaches_breakeven",
    "p_target_before_theta_dominates",
    "p_move_before_iv_normalization",
    # btc-specific
    "p_continuation_before_exhaustion",
    "p_exhaustion_before_invalidation",
)


class PedigreeViolation(RuntimeError):
    """A forecast tried to carry numbers its pedigree cannot support."""


@dataclass(frozen=True)
class PathForecast:
    """The contract. Numbers may not outrun pedigree."""
    subject: str
    T: str
    setup_family: str = NOT_ESTIMABLE
    pedigree: str = "NOT_ESTIMABLE"
    quantities: dict = field(default_factory=dict)
    estimator: str = "NONE_EXISTS"
    training_boundary: str | None = None
    evidence_class: str = "SHADOW_OBSERVATION"
    decision_power: str = "NONE_SHADOW"
    law: str = ("path probabilities receive no decision authority "
                "below CALIBRATED pedigree")

    def __post_init__(self):
        if self.pedigree not in FORECAST_PEDIGREES:
            raise PedigreeViolation(f"unknown pedigree {self.pedigree!r}")
        numeric = {k: v for k, v in self.quantities.items()
                   if isinstance(v, (int, float, list, tuple))}
        if self.pedigree == "NOT_ESTIMABLE" and numeric:
            raise PedigreeViolation(
                f"pedigree NOT_ESTIMABLE may not carry numeric path "
                f"quantities ({sorted(numeric)}): an invented number "
                f"wearing probability's clothes is worse than an "
                f"honest refusal")
        unknown = set(self.quantities) - set(PATH_QUANTITIES)
        if unknown:
            raise PedigreeViolation(
                f"undeclared path quantities {sorted(unknown)} -- the "
                f"contract is the contract")

    def as_record(self) -> dict:
        return {"kind": "path_forecast", **asdict(self)}


def realized_path(*, outcome_record: dict, declared_1R: float | None
                  ) -> dict:
    """What ACTUALLY happened, in R units -- the raw material that
    calibration will one day be fitted against. Append-only
    observation; refuses to normalize without a declared 1R because
    dividing by an undeclared denominator manufactures precision."""
    out = {"kind": "realized_path",
           "source_kind": outcome_record.get("kind"),
           "exit_reason": outcome_record.get("exit_reason",
                                             NOT_ESTIMABLE),
           "evidence_class": outcome_record.get("evidence_class",
                                                NOT_ESTIMABLE),
           "decision_power": "NONE_SHADOW"}

    pnl = outcome_record.get("pnl_usd", outcome_record.get("pnl"))
    mfe = outcome_record.get("mfe_ticks", outcome_record.get("mfe"))
    mae = outcome_record.get("mae_ticks", outcome_record.get("mae"))

    if not isinstance(declared_1R, (int, float)) or declared_1R <= 0:
        out.update({"pnl_R": NOT_ESTIMABLE, "mfe_R": NOT_ESTIMABLE,
                    "mae_R": NOT_ESTIMABLE,
                    "refusal": "no declared 1R -- R-normalization "
                               "without a declared denominator "
                               "manufactures precision"})
        return out

    def _r(x):
        return (round(x / declared_1R, 4)
                if isinstance(x, (int, float)) else NOT_ESTIMABLE)

    # tick-denominated excursions need the fill's tick value; when the
    # outcome carries USD pnl and tick excursions, callers must convert
    # upstream -- this recorder never guesses a multiplier.
    out.update({"pnl_R": _r(pnl),
                "mfe_raw": mfe if mfe is not None else NOT_ESTIMABLE,
                "mae_raw": mae if mae is not None else NOT_ESTIMABLE,
                "declared_1R": declared_1R})
    if isinstance(pnl, (int, float)):
        out["reached_plus1R"] = pnl >= declared_1R
        out["reached_minus1R"] = pnl <= -declared_1R
    return out
