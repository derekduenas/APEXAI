"""Economic viability thresholds, DECLARED before any use.

Statistical validity (section 13) says a factor's IC is real. Economic
viability asks a DIFFERENT question: is the real signal worth trading? Both are
pre-registered. These thresholds are declared here, before any projection is
run, so a factor cannot be judged viable by a bar moved to fit it -- the same
discipline as the section-13 success criteria.

A factor is ECONOMICALLY VIABLE only if ALL of these hold on the projection.
None is optimised; they are a fixed, conservative gate.
"""

from __future__ import annotations

from dataclasses import dataclass

# Declared thresholds. Conservative and fixed. Changing one is an amendment
# with a dated rationale, not a convenience.
MIN_NET_SPREAD_ANNUALISED = 0.02        # >= 2% net decile spread to be worth costs
MAX_MONTHLY_TURNOVER = 0.50             # a factor churning >50%/month is fragile
MAX_DEGRADATION_FRACTION = 0.60         # net must retain >=40% of gross
MIN_BREADTH_MEDIAN_NAMES = 400          # narrower is capacity-constrained


@dataclass(frozen=True)
class ViabilityVerdict:
    viable: bool
    failures: tuple

    def as_dict(self) -> dict:
        return {"viable": self.viable, "failures": list(self.failures)}


def assess(projection) -> ViabilityVerdict:
    """Apply the DECLARED thresholds to a ProjectionResult. No tuning.

    Reports every failing gate; does not rank, does not choose, does not soften
    a threshold to admit a borderline factor.
    """
    failures = []
    if projection.net_spread_annualised < MIN_NET_SPREAD_ANNUALISED:
        failures.append(
            f"net spread {projection.net_spread_annualised:.4f} "
            f"< {MIN_NET_SPREAD_ANNUALISED}"
        )
    if projection.monthly_turnover > MAX_MONTHLY_TURNOVER:
        failures.append(
            f"turnover {projection.monthly_turnover:.2f} > {MAX_MONTHLY_TURNOVER}"
        )
    if (projection.degradation_fraction == projection.degradation_fraction
            and projection.degradation_fraction > MAX_DEGRADATION_FRACTION):
        failures.append(
            f"degradation {projection.degradation_fraction:.2f} "
            f"> {MAX_DEGRADATION_FRACTION}"
        )
    if projection.breadth_median_names < MIN_BREADTH_MEDIAN_NAMES:
        failures.append(
            f"breadth {projection.breadth_median_names} "
            f"< {MIN_BREADTH_MEDIAN_NAMES}"
        )
    return ViabilityVerdict(viable=not failures, failures=tuple(failures))
