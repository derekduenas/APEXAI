"""Treasury rate source — real provenance, no assumed rate, and an
honest refusal below the curve's published front tenor.
"""
from __future__ import annotations

import pandas as pd
import pytest

from apex.intraday import treasury_rate_source as trs
from apex.option_analytics.rate_curve import RateCurveError, rate_for_tenor

T0 = pd.Timestamp("2026-08-18T20:00:00Z")


def test_source_name_is_never_assumed():
    assert trs.SOURCE_NAME != "ASSUMED"
    with pytest.raises(RateCurveError):
        from apex.option_analytics.rate_curve import RiskFreeCurve
        RiskFreeCurve(points=((0.5, 0.03),), source="ASSUMED", as_of=str(T0))


def test_no_hardcoded_yield_in_module():
    """The directive: do not hardcode today's Treasury yield. The module
    may define TENOR positions, but no rate LEVELS."""
    from pathlib import Path
    src = Path("apex/intraday/treasury_rate_source.py").read_text()
    for hardcoded in ("0.0378", "0.0386", "0.0471", "3.78", "4.71"):
        assert hardcoded not in src


def test_interpolation_method_is_named():
    assert trs.INTERPOLATION_METHOD == "LINEAR_IN_TENOR_YEARS"


def test_provenance_carries_every_required_field():
    p = trs.RateSourceProvenance(
        source_name=trs.SOURCE_NAME, source_url="https://x", record_date=str(T0),
        fetched_at=str(T0), age_days=0.5,
        interpolation_method=trs.INTERPOLATION_METHOD, tenor_count=14,
        is_fresh=True)
    rec = p.as_record()
    for required in ("source_name", "source_url", "record_date", "fetched_at",
                     "age_days", "interpolation_method", "tenor_count", "is_fresh"):
        assert required in rec


def test_unreachable_source_raises_rather_than_substituting(monkeypatch):
    def boom(*a, **k):
        raise OSError("network down")
    monkeypatch.setattr(trs.urllib.request, "urlopen", boom)
    with pytest.raises(trs.TreasuryRateSourceError) as e:
        trs.fetch_latest_curve(now=T0)
    assert "refusing to substitute an assumed rate" in str(e.value)


def test_sub_front_tenor_returns_none_not_extrapolation():
    """A 1-2 DTE option's tenor sits BELOW Treasury's published 1-month
    front point. The curve must return None (honest no-coverage), never
    a flat-extrapolated invention -- this is the documented boundary for
    short-DTE options analytics."""
    from apex.option_analytics.rate_curve import RiskFreeCurve
    curve = RiskFreeCurve(points=((1 / 12, 0.0378), (0.25, 0.0386)),
                          source=trs.SOURCE_NAME, as_of=str(T0))
    assert rate_for_tenor(curve, 2 / 365) is None      # 2 DTE: below front
    assert rate_for_tenor(curve, 0.1) is not None      # ~36 DTE: covered


def test_tenor_fields_cover_the_published_curve():
    assert len(trs.TENOR_FIELDS) == 14
    tenors = [t for _, t in trs.TENOR_FIELDS]
    assert tenors == sorted(tenors)
