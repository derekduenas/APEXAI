"""Causal claims that cannot say "confirmed" from significance alone.

The one prohibition this module enforces: no object may emit "causal effect
confirmed" merely because a coefficient is significant. A `CausalClaim` carries
a RUNG on the evidence ladder, the ASSUMPTIONS the rung depends on, and a
PLACEBO result -- and construction fails without them. Significance is an input
to a claim, never a claim by itself.

Our data (observational SF1 panel, no instrument, no shock, filing dates only)
supports placebo and neutralised-re-test reasoning ONLY. This module does not
implement IV/RDD/DiD, because the data cannot carry them; a claim naming an
unsupported identification strategy is refused. See APEX-CAUSAL-GOVERNANCE.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# The evidence ladder. A claim may occupy a rung only with the rungs below.
DESCRIPTIVE = "descriptive_association"
CONDITIONAL = "conditional_association"
HYPOTHESIS = "causal_hypothesis"
IDENTIFIED = "identified_causal_claim"
RUNGS = (DESCRIPTIVE, CONDITIONAL, HYPOTHESIS, IDENTIFIED)

# Identification strategies the current data actually supports. Anything else
# (iv, rdd, diff_in_diff, structural) is refused rather than faked.
SUPPORTED_STRATEGIES = ("placebo", "neutralised_re_test", "sensitivity")


class CausalError(ValueError):
    """A causal claim violated the evidence discipline."""


@dataclass(frozen=True)
class CausalClaim:
    treatment: str
    outcome: str
    confounders: tuple[str, ...]          # PRE-REGISTERED, never searched
    rung: str
    identification_strategy: str
    assumptions: tuple[str, ...]
    placebo_passed: bool                  # a placebo test was run and its result
    sensitivity_note: str = ""

    def __post_init__(self) -> None:
        if self.rung not in RUNGS:
            raise CausalError(f"rung must be one of {RUNGS}; got {self.rung!r}")
        if self.identification_strategy not in SUPPORTED_STRATEGIES:
            raise CausalError(
                f"identification strategy {self.identification_strategy!r} is not "
                f"supported by the available data. Supported: {SUPPORTED_STRATEGIES}. "
                f"IV/RDD/DiD are not implemented because this vendor's data cannot "
                f"identify them; naming one would be pretending."
            )
        # A claim above descriptive needs assumptions AND a placebo.
        if self.rung in (HYPOTHESIS, IDENTIFIED):
            if not self.assumptions:
                raise CausalError(
                    f"a {self.rung} requires explicit identification assumptions; "
                    f"a coefficient's significance is not a causal claim"
                )
            if not self.placebo_passed:
                raise CausalError(
                    f"a {self.rung} requires a passed placebo/falsification test; "
                    f"without it the relationship is an association, not causal"
                )

    def as_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}
