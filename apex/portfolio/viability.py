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


# --- long-only gate: DECLARED thresholds for the deployable sleeve ----------
#
# Different book, different physics, its own fixed bar -- declared here before
# any long-only projection of real data exists, same discipline as above. A
# concentrated 25-30 name sleeve cannot be judged by the 400-name breadth gate
# built for a two-sided decile spread; sharing that gate would quietly make
# every long-only sleeve fail breadth, and a gate that always fails is as dead
# as one that always passes.

MIN_NET_LONG_EXCESS_ANNUALISED = 0.02   # >= 2% net over benchmark, else index
MAX_QUARTERLY_TURNOVER = 0.60           # slow fundamental signal, slow book
MAX_LONG_ONLY_DEGRADATION = 0.60        # net retains >= 40% of gross
MIN_NAMES_HELD = 20                     # below this, idiosyncratic risk dominates


def assess_long_only(projection) -> ViabilityVerdict:
    """Apply the DECLARED long-only thresholds. No tuning, no ranking."""
    failures = []
    if projection.net_long_excess_annualised < MIN_NET_LONG_EXCESS_ANNUALISED:
        failures.append(
            f"net long excess {projection.net_long_excess_annualised:.4f} "
            f"< {MIN_NET_LONG_EXCESS_ANNUALISED}"
        )
    if projection.quarterly_turnover > MAX_QUARTERLY_TURNOVER:
        failures.append(
            f"quarterly turnover {projection.quarterly_turnover:.2f} "
            f"> {MAX_QUARTERLY_TURNOVER}"
        )
    if (projection.degradation_fraction == projection.degradation_fraction
            and projection.degradation_fraction > MAX_LONG_ONLY_DEGRADATION):
        failures.append(
            f"degradation {projection.degradation_fraction:.2f} "
            f"> {MAX_LONG_ONLY_DEGRADATION}"
        )
    if projection.names_held < MIN_NAMES_HELD:
        failures.append(f"names held {projection.names_held} < {MIN_NAMES_HELD}")
    return ViabilityVerdict(viable=not failures, failures=tuple(failures))
