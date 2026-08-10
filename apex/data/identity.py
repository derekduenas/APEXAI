"""Cross-vendor security identity resolution.

THE RULING THIS IMPLEMENTS (user, 2026-08-09)

    Norgate  = "What actually existed and traded?"      identity, OHLCV, actions
    Sharadar = "What could we have known about it then?"  PIT shares outstanding

    Neither source may silently substitute for the other. The universe is valid
    only where BOTH security identity and PIT eligibility can be established for
    a security-date. Where it cannot, the security-date is EXCLUDED and the
    exclusion is REPORTED. Never fill missing PIT information with today's
    shares, today's market cap, current ticker mappings, or later-revised
    fundamentals.

THE PROBLEM

    Joining two vendors normally means joining on ticker. `apex/contracts.py`
    bans that outright: tickers are recycled across companies, so a ticker join
    reintroduces survivorship contamination through the back door. "FB" belongs
    to Meta until 2022; if another issuer later takes it, a naive join staples
    one company's fundamentals to another company's prices and every downstream
    number is quietly wrong.

THE RESOLUTION

    A ticker match is a CANDIDATE, never a conclusion.

      1. GENERATE   candidates by ticker AND overlapping active date ranges. Two
                    securities that never traded simultaneously are not the same
                    security, whatever they were called.

      2. VERIFY     against independent evidence: the vendors' own price series
                    must agree over the overlap. Prices are the one thing both
                    sources observe directly, which makes them the natural
                    referee. Verification is on RETURNS, not levels, so a
                    difference of adjustment vintage between vendors does not
                    masquerade as a different company.

      3. EXCLUDE    anything resolving to zero or to more than one verified
                    counterpart. Ambiguity is never broken by a heuristic, a
                    vendor preference, or "the most likely one" -- a wrong join
                    is far more damaging than a missing security, because the
                    missing one is reported and the wrong one is not.

    The output is a deterministic, hashed crosswalk. Every input security is
    accounted for as either matched or explicitly unresolved, so nothing is ever
    dropped silently.

WHAT THIS MODULE IS NOT

    It does not fetch data. The concrete vendor readers live in norgate.py and
    sharadar.py; this operates on whatever `SecurityRecord`s they yield, which
    is what lets the whole rule be tested without either vendor's credentials.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum

import numpy as np
import pandas as pd

# A candidate must share at least this many trading days before its prices can
# be said to agree or disagree about anything.
MIN_OVERLAP_DAYS = 20

# Vendors differ in the last basis point through rounding and adjustment
# vintage. This is the median absolute difference in DAILY RETURNS that still
# counts as the same security -- deliberately tight, because two genuinely
# different companies disagree by orders of magnitude more.
RETURN_TOLERANCE = 1e-3

# Fraction of overlapping days whose returns must agree within tolerance.
MIN_AGREEMENT = 0.95


class IdentityError(ValueError):
    """The identity inputs were malformed."""


class UnresolvedReason(Enum):
    NO_CANDIDATE = "no_candidate"
    INSUFFICIENT_OVERLAP = "insufficient_overlap"
    PRICE_DISAGREEMENT = "price_disagreement"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True)
class SecurityRecord:
    """One vendor's view of one security."""

    vendor: str
    vendor_id: str
    ticker: str
    first_date: pd.Timestamp
    last_date: pd.Timestamp
    close: pd.Series

    def returns(self) -> pd.Series:
        return self.close.sort_index().pct_change().dropna()


@dataclass(frozen=True)
class Match:
    security_id: str
    left_id: str
    right_id: str
    ticker: str
    overlap_days: int
    agreement: float


@dataclass(frozen=True)
class Unresolved:
    vendor_id: str
    ticker: str
    reason: UnresolvedReason
    candidates: tuple
    detail: str = ""


@dataclass(frozen=True)
class Crosswalk:
    matches: tuple
    unresolved: tuple
    min_overlap_days: int
    return_tolerance: float
    min_agreement: float

    @property
    def resolved_count(self) -> int:
        return len(self.matches)

    def security_id_for(self, vendor: str, vendor_id: str) -> str | None:
        for match in self.matches:
            if vendor == "norgate" and match.left_id == vendor_id:
                return match.security_id
            if vendor == "sharadar" and match.right_id == vendor_id:
                return match.security_id
        return None

    @property
    def digest(self) -> str:
        """Stable fingerprint of the resolved mapping, for the results header."""
        payload = sorted(
            (m.security_id, m.left_id, m.right_id, m.ticker) for m in self.matches
        )
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def report(self) -> dict:
        by_reason: dict[str, int] = {}
        for item in self.unresolved:
            by_reason[item.reason.value] = by_reason.get(item.reason.value, 0) + 1
        return {
            "resolved": self.resolved_count,
            "unresolved": len(self.unresolved),
            "by_reason": by_reason,
            "min_overlap_days": self.min_overlap_days,
            "return_tolerance": self.return_tolerance,
            "min_agreement": self.min_agreement,
            "digest": self.digest,
            "excluded_ids": sorted(u.vendor_id for u in self.unresolved),
        }


# ---------------------------------------------------------------------------
# verification
# ---------------------------------------------------------------------------


def _agreement(left: SecurityRecord, right: SecurityRecord) -> tuple[int, float]:
    """Fraction of shared days on which the two vendors' RETURNS agree.

    Returns rather than levels: a vendor difference in split or dividend
    adjustment vintage rescales the whole level series by a constant, which
    cancels in a return. Comparing levels would reject genuine matches for a
    reason that has nothing to do with identity.
    """
    a, b = left.returns(), right.returns()
    shared = a.index.intersection(b.index)
    if len(shared) == 0:
        return 0, 0.0

    diff = np.abs(a.loc[shared].to_numpy() - b.loc[shared].to_numpy())
    finite = np.isfinite(diff)
    if not finite.any():
        return len(shared), 0.0
    return len(shared), float((diff[finite] <= RETURN_TOLERANCE).mean())


def _overlap_days(left: SecurityRecord, right: SecurityRecord) -> int:
    start = max(left.first_date, right.first_date)
    end = min(left.last_date, right.last_date)
    if start > end:
        return 0
    return int(len(left.close.loc[start:end].index.intersection(right.close.loc[start:end].index)))


def _surrogate_key(left: SecurityRecord, right: SecurityRecord) -> str:
    """A stable key derived from BOTH vendor ids -- never the ticker.

    `Panel` rejects a security_id equal to its ticker. Deriving the key from the
    vendor ids and the first trading date keeps it stable across reruns while
    carrying no recycled-symbol semantics.
    """
    seed = f"{left.vendor}:{left.vendor_id}|{right.vendor}:{right.vendor_id}|{left.first_date.date()}"
    return "SEC" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:14].upper()


# ---------------------------------------------------------------------------
# resolution
# ---------------------------------------------------------------------------


def resolve_identities(
    left_records,
    right_records,
    min_overlap_days: int = MIN_OVERLAP_DAYS,
    return_tolerance: float = RETURN_TOLERANCE,
    min_agreement: float = MIN_AGREEMENT,
) -> Crosswalk:
    """Resolve `left_records` (identity vendor) against `right_records` (PIT vendor).

    Deterministic: inputs are sorted by vendor id before anything else happens,
    so the same two extracts always produce the same crosswalk regardless of the
    order they arrived in.
    """
    left_list = sorted(left_records, key=lambda r: r.vendor_id)
    right_list = sorted(right_records, key=lambda r: r.vendor_id)

    for records, label in ((left_list, "left"), (right_list, "right")):
        ids = [r.vendor_id for r in records]
        if len(set(ids)) != len(ids):
            duplicates = sorted({i for i in ids if ids.count(i) > 1})
            raise IdentityError(f"{label} records contain duplicate vendor ids: {duplicates}")

    by_ticker: dict[str, list[SecurityRecord]] = {}
    for record in right_list:
        by_ticker.setdefault(record.ticker, []).append(record)

    matches: list[Match] = []
    unresolved: list[Unresolved] = []
    claimed: set[str] = set()

    for left in left_list:
        candidates = [
            right
            for right in by_ticker.get(left.ticker, [])
            if right.vendor_id not in claimed and _overlap_days(left, right) > 0
        ]

        if not candidates:
            unresolved.append(
                Unresolved(
                    vendor_id=left.vendor_id,
                    ticker=left.ticker,
                    reason=UnresolvedReason.NO_CANDIDATE,
                    candidates=(),
                    detail=(
                        "no security in the PIT source shares this ticker AND an "
                        "overlapping active window; PIT eligibility cannot be "
                        "established, so the security is excluded"
                    ),
                )
            )
            continue

        verified: list[tuple[SecurityRecord, int, float]] = []
        thin: list[str] = []
        disagreed: list[str] = []

        for right in candidates:
            overlap = _overlap_days(left, right)
            if overlap < min_overlap_days:
                thin.append(right.vendor_id)
                continue
            shared, agreement = _agreement(left, right)
            if agreement >= min_agreement:
                verified.append((right, shared, agreement))
            else:
                disagreed.append(right.vendor_id)

        if len(verified) == 1:
            right, overlap, agreement = verified[0]
            claimed.add(right.vendor_id)
            matches.append(
                Match(
                    security_id=_surrogate_key(left, right),
                    left_id=left.vendor_id,
                    right_id=right.vendor_id,
                    ticker=left.ticker,
                    overlap_days=overlap,
                    agreement=agreement,
                )
            )
        elif len(verified) > 1:
            unresolved.append(
                Unresolved(
                    vendor_id=left.vendor_id,
                    ticker=left.ticker,
                    reason=UnresolvedReason.AMBIGUOUS,
                    candidates=tuple(sorted(r.vendor_id for r, _, _ in verified)),
                    detail=(
                        "more than one PIT-source security verifies against this "
                        "one. A wrong join is worse than a missing security, so "
                        "the tie is NOT broken by preference or ordering."
                    ),
                )
            )
        elif disagreed:
            unresolved.append(
                Unresolved(
                    vendor_id=left.vendor_id,
                    ticker=left.ticker,
                    reason=UnresolvedReason.PRICE_DISAGREEMENT,
                    candidates=tuple(sorted(disagreed)),
                    detail=(
                        "a ticker matched but the vendors' price histories do not "
                        "agree, so they are not the same security -- most likely a "
                        "recycled symbol"
                    ),
                )
            )
        else:
            unresolved.append(
                Unresolved(
                    vendor_id=left.vendor_id,
                    ticker=left.ticker,
                    reason=UnresolvedReason.INSUFFICIENT_OVERLAP,
                    candidates=tuple(sorted(thin)),
                    detail=(
                        f"fewer than {min_overlap_days} shared trading days; there "
                        f"is not enough evidence to confirm identity, and identity "
                        f"is not assumed"
                    ),
                )
            )

    return Crosswalk(
        matches=tuple(matches),
        unresolved=tuple(unresolved),
        min_overlap_days=min_overlap_days,
        return_tolerance=return_tolerance,
        min_agreement=min_agreement,
    )
