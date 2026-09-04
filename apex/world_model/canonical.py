"""Canonical serialisation, hashing and STRICT numeric admission.

WHY NUMERIC STRICTNESS LIVES HERE AND NOT IN EACH CONTRACT
APEX has already paid for a permissive number once. On the money path a
single NaN reached `session_realized_pnl`, and because `NaN <= -1000` is
False the session drawdown halt silently stopped existing. Nothing threw.
The system just quietly lost a safety property.

A World Model is the same shape of risk with a different surface: a NaN
that becomes 0.0, a probability of 1.7, or the string "0.03" silently
coerced to a float are all ways of manufacturing information that was
never observed. So:

    no clamping. no abs(). no float("nan") passthrough.
    no string coercion. no None -> 0. bool is NOT a number.

`bool` deserves its own sentence: isinstance(True, int) is True in
Python, so a bool sails through a naive numeric check and lands in a
distribution as 1.0. It is rejected explicitly.
"""
from __future__ import annotations

import hashlib
import json
import math

CANONICAL_VERSION = "WORLD_MODEL_CANONICAL_V0"


class NumericContractViolation(ValueError):
    """A value was not a real, finite number where one was required.
    Raised rather than repaired: repairing it invents data."""


def strict_float(value, *, field: str, allow_none: bool = False):
    """The ONLY way a number enters a World Model contract."""
    if value is None:
        if allow_none:
            return None
        raise NumericContractViolation(
            "%s is None; an absent quantity must be declared absent, not "
            "defaulted to a number" % field)
    if isinstance(value, bool):
        raise NumericContractViolation(
            "%s is a bool (%r). isinstance(True, int) is True in Python, "
            "so a bool would silently become 1.0 -- rejected explicitly"
            % (field, value))
    if isinstance(value, str):
        raise NumericContractViolation(
            "%s is the string %r. Coercing strings to numbers is how a "
            "malformed feed becomes a confident number" % (field, value))
    if not isinstance(value, (int, float)):
        raise NumericContractViolation(
            "%s is %s, not a real number" % (field, type(value).__name__))
    f = float(value)
    if math.isnan(f):
        raise NumericContractViolation(
            "%s is NaN. A NaN comparison is False in both directions, "
            "which is how a threshold silently stops existing" % field)
    if math.isinf(f):
        raise NumericContractViolation("%s is %s" % (field, f))
    return f


def strict_probability(value, *, field: str, allow_none: bool = False):
    p = strict_float(value, field=field, allow_none=allow_none)
    if p is None:
        return None
    if not (0.0 <= p <= 1.0):
        raise NumericContractViolation(
            "%s = %r is not a probability. It is NOT clamped: a "
            "probability outside [0,1] means the producer is broken, and "
            "clamping hides that" % (field, p))
    return p


def canonical_json(obj) -> str:
    """Deterministic serialisation. sort_keys makes identity independent
    of incidental dict ordering, so scientific identity never depends on
    the order a producer happened to build its payload."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      default=_default, allow_nan=False)


def _default(o):
    raise NumericContractViolation(
        "%s is not canonically serialisable; a contract may not embed "
        "an opaque object" % type(o).__name__)


def content_hash(obj) -> str:
    return hashlib.sha256(canonical_json(obj).encode()).hexdigest()
