"""Cross-vendor security identity -- the join that must not be a ticker join.

User ruling, 2026-08-09:

    Norgate   = "What actually existed and traded?"   (identity, OHLCV, actions)
    Sharadar  = "What could we have known about it then?"  (PIT shares outstanding)

    Neither source may silently substitute for the other. The universe is valid
    only where BOTH security identity and PIT eligibility can be established for
    a security-date. If a security-date cannot be established PIT from the
    required source, it is EXCLUDED and the exclusion is REPORTED.

That ruling creates one hard problem. Joining two vendors normally means joining
on ticker -- and `apex/contracts.py` bans exactly that, because tickers are
recycled across companies and a ticker join silently reintroduces survivorship
contamination through the back door. "FB" is Meta until 2022 and could belong to
something else afterwards; a naive join would staple one company's fundamentals
onto another company's prices and nothing downstream would notice.

The resolution here is that a ticker match is a CANDIDATE, never a conclusion:

  1. GENERATE  candidates by ticker AND overlapping active date ranges.
  2. VERIFY    each candidate against independent evidence -- the two vendors'
               price series must actually agree over the overlap window.
  3. EXCLUDE   any security that resolves to zero or to more than one verified
               counterpart. Ambiguity is never broken by a heuristic, a
               preference order, or "the most likely one".

The output is a frozen, hashed crosswalk. Everything it could not resolve is
reported, never dropped quietly.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from apex.data.identity import (
    IdentityError,
    SecurityRecord,
    UnresolvedReason,
    resolve_identities,
)

DATES = pd.bdate_range("2020-01-01", periods=60)


def _record(vendor, vid, ticker, start=0, end=59, prices=None, seed=0):
    index = DATES[start : end + 1]
    if prices is None:
        rng = np.random.default_rng(seed)
        prices = 100.0 * np.exp(np.cumsum(rng.standard_normal(len(index)) * 0.01))
    return SecurityRecord(
        vendor=vendor,
        vendor_id=vid,
        ticker=ticker,
        first_date=index[0],
        last_date=index[-1],
        close=pd.Series(np.asarray(prices, dtype="float64"), index=index),
    )


def _pair(ticker, seed, **kw):
    """The same company as seen by both vendors: identical prices."""
    left = _record("norgate", f"N{seed}", ticker, seed=seed, **kw)
    right = _record("sharadar", f"S{seed}", ticker, seed=seed, **kw)
    return left, right


# ---------------------------------------------------------------------------
# the happy path
# ---------------------------------------------------------------------------


def test_a_matching_pair_resolves():
    left, right = _pair("AAA", seed=1)

    crosswalk = resolve_identities([left], [right])

    assert crosswalk.resolved_count == 1
    assert crosswalk.security_id_for("norgate", "N1") == crosswalk.security_id_for("sharadar", "S1")
    assert not crosswalk.unresolved


def test_the_surrogate_key_is_not_a_ticker():
    """contracts.py rejects a panel whose security_id equals its ticker."""
    left, right = _pair("AAA", seed=1)

    crosswalk = resolve_identities([left], [right])
    security_id = crosswalk.security_id_for("norgate", "N1")

    assert security_id != "AAA"
    assert "AAA" not in security_id


def test_several_independent_companies_all_resolve():
    lefts, rights = [], []
    for i, ticker in enumerate(["AAA", "BBB", "CCC"]):
        left, right = _pair(ticker, seed=i + 1)
        lefts.append(left)
        rights.append(right)

    crosswalk = resolve_identities(lefts, rights)

    assert crosswalk.resolved_count == 3
    ids = {crosswalk.security_id_for("norgate", r.vendor_id) for r in lefts}
    assert len(ids) == 3, "each company must get its own surrogate key"


# ---------------------------------------------------------------------------
# TICKER RECYCLING -- the reason this module exists
# ---------------------------------------------------------------------------


def test_a_recycled_ticker_does_not_join_two_different_companies():
    """The core failure a ticker join produces, and the reason for the ban.

    One vendor's 'FB' trades 2020-01..2020-02; another company holds 'FB'
    2020-03..2020-04. Their active windows do not overlap, so they are not the
    same security and must not be joined -- even though the ticker is identical.
    """
    early = _record("norgate", "N-early", "FB", start=0, end=20, seed=1)
    late = _record("sharadar", "S-late", "FB", start=40, end=59, seed=2)

    crosswalk = resolve_identities([early], [late])

    assert crosswalk.resolved_count == 0, (
        "two companies that never traded at the same time were joined on their "
        "shared ticker -- this is precisely the survivorship contamination "
        "contracts.py forbids"
    )
    assert crosswalk.unresolved[0].reason is UnresolvedReason.NO_CANDIDATE


def test_the_right_one_of_two_recycled_tickers_is_chosen():
    """Overlap plus price evidence must pick the genuine counterpart."""
    genuine = _record("norgate", "N-2020", "FB", start=0, end=25, seed=7)
    same = _record("sharadar", "S-2020", "FB", start=0, end=25, seed=7)
    imposter = _record("sharadar", "S-2023", "FB", start=40, end=59, seed=9)

    crosswalk = resolve_identities([genuine], [same, imposter])

    assert crosswalk.security_id_for("sharadar", "S-2020") is not None
    assert crosswalk.security_id_for("sharadar", "S-2023") is None


# ---------------------------------------------------------------------------
# VERIFICATION -- a ticker match is not evidence
# ---------------------------------------------------------------------------


def test_a_ticker_match_with_disagreeing_prices_is_rejected():
    """Same ticker, same window, completely different price series.

    Without the price check this would join. With it, the pair is refused and
    reported -- exactly the 'neither source may silently substitute' rule.
    """
    left = _record("norgate", "N1", "AAA", seed=1)
    right = _record("sharadar", "S1", "AAA", seed=999)

    crosswalk = resolve_identities([left], [right])

    assert crosswalk.resolved_count == 0
    assert crosswalk.unresolved[0].reason is UnresolvedReason.PRICE_DISAGREEMENT


def test_small_vendor_price_differences_are_tolerated():
    """Vendors disagree in the last basis point; that must not break the join."""
    left = _record("norgate", "N1", "AAA", seed=1)
    jittered = left.close * (1.0 + np.random.default_rng(0).normal(0, 1e-5, len(left.close)))
    right = SecurityRecord(
        vendor="sharadar",
        vendor_id="S1",
        ticker="AAA",
        first_date=left.first_date,
        last_date=left.last_date,
        close=jittered,
    )

    assert resolve_identities([left], [right]).resolved_count == 1


def test_too_little_overlap_to_verify_is_refused_not_guessed():
    """Three shared days is not evidence of identity."""
    left = _record("norgate", "N1", "AAA", start=0, end=30, seed=1)
    right = _record("sharadar", "S1", "AAA", start=28, end=59, seed=1)

    crosswalk = resolve_identities([left], [right], min_overlap_days=20)

    assert crosswalk.resolved_count == 0
    assert crosswalk.unresolved[0].reason is UnresolvedReason.INSUFFICIENT_OVERLAP


# ---------------------------------------------------------------------------
# AMBIGUITY -- never broken by a heuristic
# ---------------------------------------------------------------------------


def test_two_equally_good_candidates_are_excluded_not_ranked():
    """A tie must not be resolved by preference, order, or 'most likely'."""
    left = _record("norgate", "N1", "AAA", seed=5)
    twin_a = _record("sharadar", "S-a", "AAA", seed=5)
    twin_b = _record("sharadar", "S-b", "AAA", seed=5)

    crosswalk = resolve_identities([left], [twin_a, twin_b])

    assert crosswalk.resolved_count == 0
    unresolved = crosswalk.unresolved[0]
    assert unresolved.reason is UnresolvedReason.AMBIGUOUS
    assert set(unresolved.candidates) == {"S-a", "S-b"}


def test_a_security_absent_from_the_pit_source_is_excluded_and_reported():
    """Norgate says it traded; Sharadar knows nothing about it.

    The user's hard rule: a security-date whose PIT eligibility cannot be
    established is EXCLUDED and REPORTED -- never filled with today's shares or
    a current ticker mapping.
    """
    orphan = _record("norgate", "N-orphan", "ZZZ", seed=3)

    crosswalk = resolve_identities([orphan], [])

    assert crosswalk.resolved_count == 0
    assert crosswalk.unresolved[0].vendor_id == "N-orphan"
    assert crosswalk.unresolved[0].reason is UnresolvedReason.NO_CANDIDATE


def test_nothing_is_dropped_silently():
    """Every input security appears either resolved or in the exclusion report."""
    resolved_left, resolved_right = _pair("AAA", seed=1)
    orphan = _record("norgate", "N-orphan", "ZZZ", seed=3)
    mismatched = _record("norgate", "N-bad", "BBB", seed=4)
    wrong = _record("sharadar", "S-bad", "BBB", seed=800)

    crosswalk = resolve_identities([resolved_left, orphan, mismatched], [resolved_right, wrong])

    accounted = {m.left_id for m in crosswalk.matches} | {u.vendor_id for u in crosswalk.unresolved}
    assert accounted == {"N1", "N-orphan", "N-bad"}


# ---------------------------------------------------------------------------
# REPRODUCIBILITY
# ---------------------------------------------------------------------------


def test_the_crosswalk_is_deterministic_and_hashed():
    """Section 31: a result that cannot be reproduced does not count."""
    lefts, rights = [], []
    for i, ticker in enumerate(["AAA", "BBB"]):
        left, right = _pair(ticker, seed=i + 1)
        lefts.append(left)
        rights.append(right)

    first = resolve_identities(lefts, rights)
    second = resolve_identities(list(reversed(lefts)), list(reversed(rights)))

    assert first.digest == second.digest, (
        "the crosswalk depends on the order its inputs arrived in, so the same "
        "two vendor extracts could produce two different universes"
    )


def test_the_report_states_every_exclusion_reason():
    orphan = _record("norgate", "N-orphan", "ZZZ", seed=3)
    crosswalk = resolve_identities([orphan], [])

    report = crosswalk.report()

    assert report["resolved"] == 0
    assert report["unresolved"] == 1
    assert report["by_reason"]["no_candidate"] == 1
    assert "digest" in report


def test_duplicate_vendor_ids_are_rejected_outright():
    left = _record("norgate", "N1", "AAA", seed=1)
    duplicate = _record("norgate", "N1", "BBB", seed=2)

    with pytest.raises(IdentityError):
        resolve_identities([left, duplicate], [])
