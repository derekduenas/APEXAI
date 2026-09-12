"""WORLD_MODEL_RESEARCH_AUTHORITY_V0 -- what this package may not do.

This module is the CAGE, not the animal. It grants nothing. Every entry
below is a prohibition, and the package's only current capability is
refusing things.

WHY A MACHINE-READABLE CONTRACT AND NOT A DOCSTRING
A comment saying "must not touch real labels" is a wish. APEX has
already learned twice this week what an unenforced intention is worth:
the maintenance block held because it was a systemd condition, and the
2026-09-03 session was lost because "start a successor before the open"
was only a plan. So the contract is data, it is hashed, and code that
wants to read a file must ask it first.

THE DIGEST
AUTHORITY_DIGEST pins the canonical serialisation of the manifest. It is
not anti-tamper against someone editing this file -- they could edit the
digest too. It defends against the realistic failure: a future caller
mutating the manifest dict at runtime to widen its own permissions, or
a merge silently dropping a prohibition. Both change the digest and both
then fail closed.
"""
from __future__ import annotations

import hashlib
import json

AUTHORITY_VERSION = "WORLD_MODEL_RESEARCH_AUTHORITY_V0"

# Every value is a prohibition. There is deliberately no "ALLOWED" key:
# this contract cannot grant, only deny.
WORLD_MODEL_RESEARCH_AUTHORITY_V0 = {
    "contract": AUTHORITY_VERSION,
    "REAL_MARKET_LABEL_ACCESS": "FORBIDDEN",
    "REAL_MARKET_MODEL_FITTING": "FORBIDDEN",
    "PROSPECTIVE_OUTCOME_ACCESS": "FORBIDDEN",
    "P_AND_L_ACCESS": "FORBIDDEN",
    "BOOK_OUTCOME_ACCESS": "FORBIDDEN",
    "ROBINHOOD_ACCESS": "FORBIDDEN",
    "ORDER_AUTHORITY": "NONE",
    "TRADING_AUTHORITY": "NONE",
    "CAPITAL_AUTHORITY": "NONE",
    "PRODUCTION_DEPLOYMENT": "FORBIDDEN",
}

_REQUIRED = frozenset(WORLD_MODEL_RESEARCH_AUTHORITY_V0)
_MUST_BE_FORBIDDEN = frozenset(
    k for k, v in WORLD_MODEL_RESEARCH_AUTHORITY_V0.items()
    if v == "FORBIDDEN")
_MUST_BE_NONE = frozenset(
    k for k, v in WORLD_MODEL_RESEARCH_AUTHORITY_V0.items() if v == "NONE")


class WorldModelAuthorityViolation(Exception):
    """The research authority contract is absent, malformed, or has been
    widened. Nothing proceeds."""


def canonical(manifest: dict | None = None) -> str:
    m = WORLD_MODEL_RESEARCH_AUTHORITY_V0 if manifest is None else manifest
    return json.dumps(m, sort_keys=True, separators=(",", ":"))


def digest(manifest: dict | None = None) -> str:
    return hashlib.sha256(canonical(manifest).encode()).hexdigest()


AUTHORITY_DIGEST = digest()


def assert_authority(manifest: dict | None = None) -> dict:
    """Fail closed on a missing, malformed, or widened contract.

    Returns the manifest so callers read it from here rather than
    keeping their own copy that could drift.
    """
    m = WORLD_MODEL_RESEARCH_AUTHORITY_V0 if manifest is None else manifest
    if m is None:
        raise WorldModelAuthorityViolation(
            "no research authority manifest: research code may not run "
            "without one")
    if not isinstance(m, dict):
        raise WorldModelAuthorityViolation(
            "authority manifest is %s, not a mapping" % type(m).__name__)
    if m.get("contract") != AUTHORITY_VERSION:
        raise WorldModelAuthorityViolation(
            "authority manifest declares contract %r, expected %r"
            % (m.get("contract"), AUTHORITY_VERSION))
    missing = _REQUIRED - set(m)
    if missing:
        raise WorldModelAuthorityViolation(
            "authority manifest is missing prohibitions: %s -- a dropped "
            "prohibition is a widened permission"
            % ", ".join(sorted(missing)))
    for k in _MUST_BE_FORBIDDEN:
        if m.get(k) != "FORBIDDEN":
            raise WorldModelAuthorityViolation(
                "%s is %r, must be FORBIDDEN" % (k, m.get(k)))
    for k in _MUST_BE_NONE:
        if m.get(k) != "NONE":
            raise WorldModelAuthorityViolation(
                "%s is %r, must be NONE" % (k, m.get(k)))
    if manifest is None and digest(m) != AUTHORITY_DIGEST:
        raise WorldModelAuthorityViolation(
            "the in-process authority manifest has been MUTATED at "
            "runtime (digest %s != pinned %s)"
            % (digest(m)[:16], AUTHORITY_DIGEST[:16]))
    return dict(m)
