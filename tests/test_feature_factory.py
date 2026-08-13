"""Feature factory, registry, redundancy, PIT. Infrastructure, not alpha.

No forward returns, no IC, no performance ranking anywhere. Every load-bearing
invariant carries a positive control and a counterexample, because a guard that
cannot fail is not a guard -- established repeatedly in this project.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from apex.contracts import Panel
from apex.features import factory, pit_validation, redundancy
from apex.features.registry import (
    BUILT,
    DATA_AVAILABLE,
    DATA_GAP,
    FEATURE_REGISTRY,
    FeatureSpec,
    built_specs,
)


# ---------------------------------------------------------------------------
# fixtures: a tiny as-filed table + a matching panel, no market data needed
# for ratio/growth features
# ---------------------------------------------------------------------------


def _as_filed(rows) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    df["reportperiod"] = pd.to_datetime(df["reportperiod"])
    return df


def _panel(dates, tickers=("AAA",)) -> Panel:
    idx = pd.DatetimeIndex(pd.to_datetime(dates))
    secs = pd.Index([f"SEC_{t}" for t in tickers], name="security_id")
    wide = lambda v: pd.DataFrame(v, index=idx, columns=secs, dtype="float64")
    meta = pd.DataFrame(
        {"security_id": secs, "ticker": list(tickers),
         "exchange": "NYSE", "security_type": "common", "sector": "Tech",
         "first_date": idx[0], "last_date": idx[-1],
         "delist_date": pd.NaT, "delist_reason": None},
        index=secs,
    )
    return Panel(
        dates=idx, securities=secs,
        close_adj=wide(10.0), high_adj=wide(11.0), low_adj=wide(9.0),
        close_unadj=wide(10.0), volume=wide(1e6), shares_out=wide(1e8),
        meta=meta, benchmark_tr=pd.Series(100.0, index=idx),
        vol_index=pd.Series(20.0, index=idx),
    )


def _spec_by_id(fid: str) -> FeatureSpec:
    return FEATURE_REGISTRY[fid]


# ---------------------------------------------------------------------------
# REGISTRY -- one authoritative definition, no duplicates
# ---------------------------------------------------------------------------


def test_the_registry_has_no_duplicate_ids():
    ids = [s.feature_id for s in FEATURE_REGISTRY.values()]
    assert len(ids) == len(set(ids))


def test_counterexample_two_features_with_the_same_formula_are_detected():
    """DUPLICATE-DEFINITION guard. The f1_mom_63 / f4_vs_market lesson, at the
    descriptor level: identical formulas must be caught before compute."""
    a = _spec_by_id("prof_return_on_assets")            # netinc / assets
    clone = FeatureSpec(**{**a.__dict__, "feature_id": "prof_roa_DUPLICATE"})

    findings = redundancy.structural_findings([a, clone])

    assert any(f.kind == "identical_formula" for f in findings), (
        "an identical formula under a second name was not detected"
    )


def test_the_real_registry_contains_no_identical_formulas():
    findings = redundancy.structural_findings(list(FEATURE_REGISTRY.values()))

    identical = [f for f in findings if f.kind == "identical_formula"]
    assert not identical, f"registry has duplicate definitions: {identical}"


def test_counterexample_reciprocal_ratios_are_flagged_algebraic():
    """book/market and a hypothetical market/book carry the same information."""
    btm = _spec_by_id("val_book_to_market")
    # a reciprocal, expressed as a plain ratio for the structural test
    inverse = FeatureSpec(**{
        **btm.__dict__, "feature_id": "val_market_to_book",
        "formula": {"kind": "ratio", "num": "marketcap", "den": "equity"},
    })
    as_ratio = FeatureSpec(**{
        **btm.__dict__, "feature_id": "val_book_to_market_ratio",
        "formula": {"kind": "ratio", "num": "equity", "den": "marketcap"},
    })

    findings = redundancy.structural_findings([as_ratio, inverse])

    assert any(f.kind == "algebraic_equivalent" for f in findings)


def test_every_built_spec_has_complete_metadata():
    """LINEAGE test: no feature enters the registry without full provenance."""
    for s in built_specs():
        assert s.economic_mechanism.strip()
        assert s.source_fields
        assert s.pit_rule.strip()
        assert s.lineage.strip()
        assert s.version.strip()
        assert s.limitations.strip()


# ---------------------------------------------------------------------------
# FACTORY -- positive controls on known arithmetic
# ---------------------------------------------------------------------------


def test_positive_control_ratio_is_computed_exactly():
    """gross profitability = gp / assets, on a hand-checkable fixture."""
    af = _as_filed([
        {"ticker": "AAA", "reportperiod": "2020-03-31", "date": "2020-05-01",
         "gp": 30.0, "assets": 300.0},
        {"ticker": "AAA", "reportperiod": "2020-06-30", "date": "2020-08-01",
         "gp": 40.0, "assets": 200.0},
    ])
    panel = _panel(["2020-09-01"])
    spec = _spec_by_id("prof_gross_profitability")

    stream = factory._per_security_stream(af, spec)
    known, val = stream

    # latest as-filed by 2020-09-01 is the 2020-06-30 record: 40/200 = 0.20
    assert val[-1] == pytest.approx(0.20)


def test_positive_control_growth_pairs_across_four_quarters():
    af = _as_filed([
        {"ticker": "AAA", "reportperiod": f"20{y}-{m}", "date": d, "assets": a}
        for (y, m, d, a) in [
            ("20", "03-31", "2020-05-01", 100.0),
            ("20", "06-30", "2020-08-01", 110.0),
            ("20", "09-30", "2020-11-01", 120.0),
            ("20", "12-31", "2021-02-01", 130.0),
            ("21", "03-31", "2021-05-01", 150.0),
        ]
    ])
    spec = _spec_by_id("grow_asset_growth")

    known, val = factory._per_security_stream(af, spec)

    # q1-2021 vs q1-2020: 150/100 - 1 = 0.50, knowable at the later filing
    assert val[-1] == pytest.approx(0.50)
    assert known[-1] == np.datetime64("2021-05-01")


def test_counterexample_a_zero_denominator_is_excluded_not_infinite():
    af = _as_filed([
        {"ticker": "AAA", "reportperiod": "2020-06-30", "date": "2020-08-01",
         "gp": 40.0, "revenue": 0.0},
    ])
    spec = _spec_by_id("prof_gross_margin")

    _, val = factory._per_security_stream(af, spec)

    assert np.isnan(val[-1]), "division by zero revenue produced a value"


def test_accruals_subtracts_in_the_right_order():
    """(netinc - ncfo)/assets, not (ncfo - netinc). Order matters: a-b != b-a."""
    af = _as_filed([
        {"ticker": "AAA", "reportperiod": "2020-06-30", "date": "2020-08-01",
         "netinc": 50.0, "ncfo": 30.0, "assets": 100.0},
    ])
    spec = _spec_by_id("accr_total_accruals")

    _, val = factory._per_security_stream(af, spec)

    assert val[-1] == pytest.approx(0.20)          # (50-30)/100, not (30-50)/100


# ---------------------------------------------------------------------------
# DETERMINISM
# ---------------------------------------------------------------------------


def test_the_factory_is_deterministic():
    af = _as_filed([
        {"ticker": "AAA", "reportperiod": "2020-06-30", "date": "2020-08-01",
         "netinc": 5.0, "equity": 50.0},
    ])
    spec = _spec_by_id("prof_return_on_equity")

    a = factory._per_security_stream(af, spec)
    b = factory._per_security_stream(af.copy(), spec)

    assert np.array_equal(a[1], b[1], equal_nan=True)


# ---------------------------------------------------------------------------
# PIT -- measured, with a deliberate violation
# ---------------------------------------------------------------------------


def test_pit_a_future_filing_is_not_used_before_it_exists():
    """A record filed 2020-08-01 must be invisible on 2020-07-01."""
    af = _as_filed([
        {"ticker": "AAA", "reportperiod": "2020-06-30", "date": "2020-08-01",
         "gp": 40.0, "assets": 200.0},
    ])
    spec = _spec_by_id("prof_gross_profitability")
    known, val = factory._per_security_stream(af, spec)

    idx = factory._broadcast_latest(
        known, val, pd.to_datetime(["2020-07-01"]).to_numpy()
    )
    assert np.isnan(idx[0][0]), "a filing dated 2020-08-01 was used on 2020-07-01"


def test_counterexample_the_pit_validator_flags_a_late_knowability_date():
    """PROVE the PIT measure can report < 100%, not only 100%."""
    dates = pd.DatetimeIndex(pd.to_datetime(["2020-09-01"]))
    secs = pd.Index(["SEC_AAA"], name="security_id")
    values = pd.DataFrame([[0.2]], index=dates, columns=secs)
    eligible = pd.DataFrame([[True]], index=dates, columns=secs)

    clean = pd.DataFrame([[pd.Timestamp("2020-08-01")]], index=dates, columns=secs)
    assert pit_validation.validate_feature("x", values, clean, eligible).compliant

    late = pd.DataFrame([[pd.Timestamp("2020-09-02")]], index=dates, columns=secs)
    result = pit_validation.validate_feature("x", values, late, eligible)
    assert not result.compliant and result.violations == 1


# ---------------------------------------------------------------------------
# EMPIRICAL REDUNDANCY -- identical vs correlated
# ---------------------------------------------------------------------------


def test_a_per_date_scalar_difference_is_identical_information():
    """The f1_mom_63 / f4_vs_market signature, reproduced and detected."""
    dates = pd.bdate_range("2021-01-01", periods=10)
    secs = pd.Index([f"S{i}" for i in range(20)], name="security_id")
    base = pd.DataFrame(np.random.default_rng(0).normal(size=(10, 20)),
                        index=dates, columns=secs)
    shifted = base.sub(base.mean(axis=1), axis=0)      # minus a per-date scalar
    eligible = pd.DataFrame(True, index=dates, columns=secs)

    findings = redundancy.empirical_findings(
        {"base": base, "demeaned": shifted}, eligible
    )

    assert findings and findings[0].kind == "per_date_scalar"
    assert findings[0].is_identical_information()


def test_counterexample_correlated_features_are_not_called_identical():
    """A related-but-distinct pair must be CORRELATED, never removed."""
    dates = pd.bdate_range("2021-01-01", periods=40)
    secs = pd.Index([f"S{i}" for i in range(30)], name="security_id")
    rng = np.random.default_rng(1)
    a = pd.DataFrame(rng.normal(size=(40, 30)), index=dates, columns=secs)
    # clearly related (~0.9 rank) but NOT identical and NOT a per-date scalar
    b = a + 0.4 * pd.DataFrame(rng.normal(size=(40, 30)), index=dates, columns=secs)
    eligible = pd.DataFrame(True, index=dates, columns=secs)

    findings = redundancy.empirical_findings({"a": a, "b": b}, eligible)

    assert findings and findings[0].kind == "correlated", (
        f"expected a correlated finding, got {[f.kind for f in findings]}"
    )
    assert not findings[0].is_identical_information(), (
        "a merely-correlated pair was classed as identical information"
    )


def test_summary_separates_identical_from_correlated():
    dates = pd.bdate_range("2021-01-01", periods=10)
    secs = pd.Index([f"S{i}" for i in range(15)], name="security_id")
    base = pd.DataFrame(np.random.default_rng(2).normal(size=(10, 15)),
                        index=dates, columns=secs)
    eligible = pd.DataFrame(True, index=dates, columns=secs)

    findings = redundancy.empirical_findings(
        {"a": base, "b": base.sub(base.mean(axis=1), axis=0),
         "c": base * 0.7 + 1}, eligible
    )
    summary = redundancy.summarise(findings)

    assert summary["n_identical"] >= 1


# ---------------------------------------------------------------------------
# STATUS honesty -- no pretending unavailable data exists
# ---------------------------------------------------------------------------


def test_data_gaps_are_marked_not_faked():
    gaps = [s for s in FEATURE_REGISTRY.values() if s.status == DATA_GAP]
    ids = {s.feature_id for s in gaps}

    assert "evt_pead" in ids, "PEAD must be a DATA GAP: no announcement date"
    assert "pos_short_interest" in ids, "positioning must be a DATA GAP"
    for s in gaps:
        assert "none" in s.lineage.lower() or "absent" in s.lineage.lower()


def test_roe_roa_are_built_from_raw_not_the_empty_vendor_field():
    """The vendor roe/roa fields are 0% in ARQ; specs must not source them."""
    for fid in ("prof_return_on_equity", "prof_return_on_assets"):
        spec = FEATURE_REGISTRY[fid]
        assert "roe" not in spec.source_fields and "roa" not in spec.source_fields
        assert "NOT vendor" in spec.lineage
