"""Success criteria, read from the registered experiment. Never hardcoded.

INCIDENT-001 D3
---------------
`run_validation.py` passed `min_mean_ic=0.015, min_t_stat=2.5,
min_robustness_t=2.0` as literals. Those are APEX-001's hurdles. APEX-002 §13
registers different ones -- mean IC POSITIVE, t at or above the one-sided
alpha=1% critical value, robustness AGREES IN SIGN -- and the runner would have
applied #001's anyway, producing a valid-looking verdict computed against the
wrong experiment's criteria. Only an unrelated crash stopped it.

This module removes the possibility. Criteria come from configuration,
expressed as named RULES rather than magic numbers, and nothing here knows an
experiment id. There is deliberately no

    if experiment == "APEX-001": ...

anywhere: a per-experiment branch is the same defect with a lookup table, and
it fails the same way the moment a third experiment is registered.

RELATIONSHIP TO CONVENTIONS A-001
---------------------------------
A-001 bars the simulated null reference from the DECISION path; the reference
exists for calibration and disclosure. APEX-002 §13 names a null-derived
critical value as its threshold, and also states it numerically ("≈2.92
validation, ≈2.88 holdout").

Those numbers are used as registered per-period constants, so the decision
stays a function of the frozen document and nothing computed at runtime. The
simulated null is still reported alongside, as disclosure, so a divergence
between the registered constant and the null at the ACTUAL observation count
is visible rather than silently absorbed. Reversing that -- computing the
threshold live -- would put the reference on the decision path and contradict
A-001, and is not done here.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from apex.config import Config


class CriteriaError(ValueError):
    """The registered criteria are missing, unknown, or inapplicable."""


@dataclass(frozen=True)
class Criterion:
    name: str
    rule: str
    threshold: float | None = None

    def describe(self) -> str:
        if self.rule == "positive":
            return f"{self.name} > 0"
        if self.rule == "at_least":
            return f"{self.name} >= {self.threshold}"
        if self.rule == "same_sign":
            return f"{self.name} agrees in sign with the primary statistic"
        raise CriteriaError(f"unknown rule {self.rule!r} for {self.name}")


@dataclass(frozen=True)
class CriteriaVerdict:
    verdict: str
    failures: tuple[str, ...] = ()
    applied: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "failures": list(self.failures),
            "criteria_applied": list(self.applied),
        }


@dataclass(frozen=True)
class SuccessCriteria:
    """The registered pass/fail rules for one experiment and one period."""

    experiment_id: str
    period: str
    mean_ic: Criterion
    t_stat: Criterion
    robustness: Criterion
    source: str = field(default="config/experiment.yaml: success_criteria")

    @classmethod
    def from_config(cls, config: Config, period: str) -> "SuccessCriteria":
        spec = config.section("success_criteria")

        def build(name: str) -> Criterion:
            if name not in spec:
                raise CriteriaError(
                    f"no registered success criterion for {name!r}. The runner "
                    f"must not supply a default: an unregistered threshold is "
                    f"how INCIDENT-001 D3 applied another experiment's hurdles."
                )
            entry = spec[name]
            rule = entry["rule"]
            threshold = None
            if rule == "at_least":
                by_period = entry.get("by_period")
                if by_period is not None:
                    if period not in by_period:
                        raise CriteriaError(
                            f"criterion {name!r} registers no threshold for "
                            f"period {period!r}; refusing to substitute one"
                        )
                    threshold = float(by_period[period])
                else:
                    threshold = float(entry["value"])
            return Criterion(name=name, rule=rule, threshold=threshold)

        return cls(
            experiment_id=config.get("experiment.id"),
            period=period,
            mean_ic=build("mean_ic"),
            t_stat=build("t_stat"),
            robustness=build("robustness"),
        )

    # -- evaluation ---------------------------------------------------------

    def evaluate(
        self, *, mean_ic: float, t_stat: float, robustness_t: float
    ) -> CriteriaVerdict:
        """Apply the registered rules. Takes no reference, no ledger, no alpha.

        The decision cannot be a function of anything learned after the
        experiment was registered, so nothing computed at runtime enters here.
        """
        failures: list[str] = []

        if not self._holds(self.mean_ic, mean_ic, t_stat):
            failures.append(f"mean IC {mean_ic:+.6f} fails {self.mean_ic.describe()}")
        if not self._holds(self.t_stat, t_stat, t_stat):
            failures.append(f"t-statistic {t_stat:+.6f} fails {self.t_stat.describe()}")
        if not self._holds(self.robustness, robustness_t, t_stat):
            failures.append(
                f"robustness t {robustness_t:+.6f} fails {self.robustness.describe()}"
            )

        applied = tuple(c.describe() for c in (self.mean_ic, self.t_stat, self.robustness))
        return CriteriaVerdict(
            verdict="SUCCESS" if not failures else "FAILURE",
            failures=tuple(failures),
            applied=applied,
        )

    @staticmethod
    def _holds(criterion: Criterion, value: float, primary: float) -> bool:
        if value != value:                      # NaN never passes
            return False
        if criterion.rule == "positive":
            return value > 0.0
        if criterion.rule == "at_least":
            return value >= criterion.threshold
        if criterion.rule == "same_sign":
            return (value > 0 and primary > 0) or (value < 0 and primary < 0)
        raise CriteriaError(f"unknown rule {criterion.rule!r}")

    def as_dict(self) -> dict:
        return {
            "experiment_id": self.experiment_id,
            "period": self.period,
            "source": self.source,
            "mean_ic": self.mean_ic.describe(),
            "t_stat": self.t_stat.describe(),
            "robustness": self.robustness.describe(),
        }
