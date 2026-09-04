"""Quality and missingness -- carried forward from Phase 2, not reinvented.

THE LAW: MISSING IS NOT ZERO.

Each of these says something different, and collapsing them into a
number destroys the distinction permanently:

  VALID                observed and trustworthy
  STALE                genuinely observed, but old -- NOT unhealthy, and
                       NOT the same as absent
  UNKNOWN              the source did not say
  NOT_AVAILABLE        the source cannot provide it here
  NOT_ESTIMABLE        derivable in principle, not derivable from what
                       is actually present
  PROVIDER_ERROR       the source failed -- an error is EVIDENCE, not a
                       gap
  SESSION_INAPPLICABLE the question does not apply in this session
                       (options quotes at 03:00) -- absence is CORRECT
                       here, and reading it as a provider gap would
                       manufacture a defect that does not exist

A model that sees 0.0 for all seven has been told a lie six times.
"""
from __future__ import annotations

VALID = "VALID"
STALE = "STALE"
UNKNOWN = "UNKNOWN"
NOT_AVAILABLE = "NOT_AVAILABLE"
NOT_ESTIMABLE = "NOT_ESTIMABLE"
PROVIDER_ERROR = "PROVIDER_ERROR"
SESSION_INAPPLICABLE = "SESSION_INAPPLICABLE"

QUALITY_STATES = frozenset({VALID, STALE, UNKNOWN, NOT_AVAILABLE,
                            NOT_ESTIMABLE, PROVIDER_ERROR,
                            SESSION_INAPPLICABLE})

# Only these two carry an observed value. Everything else MUST carry
# None -- a non-VALID state with a number attached is the exact
# missing-becomes-zero defect this module exists to prevent.
VALUE_BEARING = frozenset({VALID, STALE})


class QualityContractViolation(ValueError):
    pass


def assert_quality(state: str, *, field: str) -> str:
    if state not in QUALITY_STATES:
        raise QualityContractViolation(
            "%s: unknown quality state %r. Permitted: %s"
            % (field, state, ", ".join(sorted(QUALITY_STATES))))
    return state


def assert_value_matches_quality(state: str, value, *, field: str):
    if state in VALUE_BEARING:
        return
    if value is not None:
        raise QualityContractViolation(
            "%s is %s but carries the value %r. A non-observed component "
            "must carry None; attaching a number to it is how missing "
            "silently becomes zero." % (field, state, value))
