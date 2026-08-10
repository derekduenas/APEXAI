"""The dual-vendor seam enforces the ruling structurally, not by discipline."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from apex.data.dual import IdentitySource, NotWired, PITSource, build_crosswalk, coverage
from apex.data.identity import SecurityRecord

DATES = pd.bdate_range("2020-01-01", periods=40)


def _record(vendor, vid, ticker, seed=0):
    rng = np.random.default_rng(seed)
    prices = 100.0 * np.exp(np.cumsum(rng.standard_normal(len(DATES)) * 0.01))
    return SecurityRecord(vendor, vid, ticker, DATES[0], DATES[-1], pd.Series(prices, index=DATES))


class FakeIdentity:
    name = "norgate-fake"

    def __init__(self, records):
        self._records = records

    def securities(self):
        return self._records

    def prices(self):
        return {r.vendor_id: r.close for r in self._records}

    def corporate_actions(self):
        return pd.DataFrame()


class FakePIT:
    name = "sharadar-fake"

    def __init__(self, records):
        self._records = records

    def securities(self):
        return self._records

    def shares_outstanding(self):
        return {r.vendor_id: pd.Series(1e9, index=DATES) for r in self._records}


def test_the_two_protocols_are_structurally_separate():
    """An identity source has no way to supply shares outstanding, and vice versa.

    This is the ruling's "neither source may silently substitute" made
    unavailable rather than merely discouraged.
    """
    assert not hasattr(IdentitySource, "shares_outstanding")
    assert not hasattr(PITSource, "prices")


def test_both_sources_are_required():
    identity = FakeIdentity([_record("norgate", "N1", "AAA", 1)])

    with pytest.raises(NotWired) as excinfo:
        build_crosswalk(identity, None)

    assert "BOTH" in str(excinfo.value)


def test_a_matched_pair_resolves_through_the_seam():
    identity = FakeIdentity([_record("norgate", "N1", "AAA", 1)])
    pit = FakePIT([_record("sharadar", "S1", "AAA", 1)])

    crosswalk = build_crosswalk(identity, pit)

    assert crosswalk.resolved_count == 1


def test_a_security_missing_from_the_pit_source_is_excluded_and_counted():
    identity = FakeIdentity([_record("norgate", "N1", "AAA", 1), _record("norgate", "N2", "BBB", 2)])
    pit = FakePIT([_record("sharadar", "S1", "AAA", 1)])

    crosswalk = build_crosswalk(identity, pit)
    report = coverage(
        crosswalk,
        shares_out=pd.DataFrame(1e9, index=DATES, columns=["X"]),
        tradable=pd.DataFrame(True, index=DATES, columns=["X"]),
        identity_securities=2,
        pit_securities=1,
    )

    assert report.resolved_securities == 1
    assert report.unresolved_securities == 1
    assert report.unresolved_by_reason["no_candidate"] == 1
    assert report.security_resolution_rate == pytest.approx(0.5)


def test_coverage_counts_security_dates_without_pit_shares():
    """The number that says whether the join is actually working."""
    identity = FakeIdentity([_record("norgate", "N1", "AAA", 1)])
    pit = FakePIT([_record("sharadar", "S1", "AAA", 1)])

    shares = pd.DataFrame(1e9, index=DATES, columns=["X"])
    shares.iloc[:10] = np.nan  # vendor has no PIT figure for the first ten days

    report = coverage(
        crosswalk=build_crosswalk(identity, pit),
        shares_out=shares,
        tradable=pd.DataFrame(True, index=DATES, columns=["X"]),
        identity_securities=1,
        pit_securities=1,
    )

    assert report.security_dates_total == 40
    assert report.security_dates_with_pit == 30
    assert report.pit_coverage_rate == pytest.approx(0.75)


def test_the_coverage_report_states_the_rule_it_enforces():
    identity = FakeIdentity([_record("norgate", "N1", "AAA", 1)])
    pit = FakePIT([_record("sharadar", "S1", "AAA", 1)])

    report = coverage(
        crosswalk=build_crosswalk(identity, pit),
        shares_out=pd.DataFrame(1e9, index=DATES, columns=["X"]),
        tradable=pd.DataFrame(True, index=DATES, columns=["X"]),
        identity_securities=1,
        pit_securities=1,
    ).as_dict()

    assert "never filled" in report["rule"]
    assert "crosswalk_digest" in report
