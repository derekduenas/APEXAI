"""Phase 0.4 (FULL-UNIVERSE SENSORY ARCHITECTURE) contract tests:
UniverseCoverageState, BroadMarketDataProvider abstraction (EODHD
implementation), DataDisagreementState. Research/architecture phase —
these prove the CONTRACTS are correct; they do not purchase or switch
any provider.
"""
from __future__ import annotations

import pandas as pd
import pytest

from apex.intraday.disagreement import SourceQuote, compare
from apex.intraday.universe_coverage import (
    BROAD_DISCOVERY_MIN_FRACTION, DEGRADED, FAILED, HEALTHY, PARTIAL,
    compute_universe_coverage,
)


def _idx(start, n):
    return pd.date_range(start, periods=n, freq="1min", tz="UTC")


# --------------------------------------------------- UniverseCoverageState
def test_measured_5017_bottleneck_reads_degraded_not_healthy():
    """The exact 2026-08-17 shape: 50/164 continuous."""
    intended = tuple(f"S{i:03d}" for i in range(164))
    streamed = intended[:50]
    bars = {s: _idx("2026-08-17 14:17:00+00:00", 200) for s in streamed}
    cov = compute_universe_coverage(
        intended_universe=intended, authorized_universe=streamed,
        streamed_universe=streamed, bar_index_by_symbol=bars,
        as_of=pd.Timestamp("2026-08-17 17:45:00", tz="UTC"),
        source="EODHD_WEBSOCKET_REALTIME_V1")
    assert cov.coverage_count == 50
    assert cov.coverage_fraction == pytest.approx(50 / 164, abs=1e-3)
    assert cov.broad_discovery_valid is False
    assert cov.status in (DEGRADED, PARTIAL)
    assert cov.discovery_latency_scope == "CANDIDATE_EVOLUTION_LATENCY_ONLY"
    assert len(cov.never_observed) == 114


def test_full_164_coverage_is_healthy_and_discovery_valid():
    intended = tuple(f"S{i:03d}" for i in range(164))
    bars = {s: _idx("2026-08-17 13:30:00+00:00", 200) for s in intended}
    cov = compute_universe_coverage(
        intended_universe=intended, authorized_universe=intended,
        streamed_universe=intended, bar_index_by_symbol=bars,
        as_of=pd.Timestamp("2026-08-17 17:00:00", tz="UTC"))
    assert cov.coverage_fraction == 1.0
    assert cov.continuous_coverage_fraction == 1.0
    assert cov.broad_discovery_valid is True
    assert cov.status == HEALTHY
    assert cov.discovery_latency_scope == "UNIVERSE_DISCOVERY_LATENCY"
    assert cov.never_observed == ()


def test_zero_streamed_is_failed_not_a_crash():
    cov = compute_universe_coverage(
        intended_universe=("A", "B"), authorized_universe=(),
        streamed_universe=(), bar_index_by_symbol={},
        as_of=pd.Timestamp.now(tz="UTC"))
    assert cov.status == FAILED
    assert cov.coverage_fraction == 0.0
    assert cov.broad_discovery_valid is False


def test_gap_detection_excludes_symbol_from_continuous():
    """A streamed symbol with a >60s gap is rotated/partial, never
    silently counted as continuous."""
    idx = _idx("2026-08-17 14:17:00+00:00", 60)
    idx_gapped = idx[:20].append(idx[25:])   # 5-minute gap
    bars = {"GOOD": idx, "GAPPY": idx_gapped}
    cov = compute_universe_coverage(
        intended_universe=("GOOD", "GAPPY"), authorized_universe=("GOOD", "GAPPY"),
        streamed_universe=("GOOD", "GAPPY"), bar_index_by_symbol=bars,
        as_of=pd.Timestamp("2026-08-17 15:30:00", tz="UTC"))
    assert "GOOD" in cov.continuous_universe
    assert "GAPPY" not in cov.continuous_universe
    assert "GAPPY" in cov.rotated_universe


# ---------------------------------------------------- DataDisagreementState
def test_agreeing_sources_are_not_material():
    q1 = SourceQuote("EODHD", 100.00, 99.99, 100.01,
                     "2026-08-17T15:00:00Z", "2026-08-17T15:00:01Z")
    q2 = SourceQuote("ROBINHOOD", 100.01, 100.00, 100.02,
                     "2026-08-17T15:00:00Z", "2026-08-17T15:00:02Z")
    d = compare("X", "2026-08-17T15:00:05Z", (q1, q2))
    assert d.material is False
    assert d.price_diff_frac < 0.001


def test_material_price_disagreement_is_flagged_never_silently_resolved():
    q1 = SourceQuote("EODHD", 100.00, None, None,
                     "2026-08-17T15:00:00Z", "2026-08-17T15:00:01Z")
    q2 = SourceQuote("ROBINHOOD", 101.50, None, None,   # 1.5% off
                     "2026-08-17T15:00:00Z", "2026-08-17T15:00:02Z")
    d = compare("X", "2026-08-17T15:00:05Z", (q1, q2))
    assert d.material is True
    assert "price_diff" in d.reason
    assert d.sources == (q1, q2)          # BOTH preserved, neither dropped


def test_stale_source_is_flagged_material():
    q1 = SourceQuote("EODHD", 100.0, None, None,
                     "2026-08-17T15:00:00Z", "2026-08-17T14:00:00Z")  # 1h stale
    d = compare("X", "2026-08-17T15:00:05Z", (q1,))
    assert d.material is True
    assert "stale" in d.reason


def test_no_priced_source_is_material_not_a_crash():
    q1 = SourceQuote("EODHD", None, None, None, None, None)
    d = compare("X", "2026-08-17T15:00:00Z", (q1,))
    assert d.material is True
    assert "no source" in d.reason


# --------------------------------------------------- provider abstraction
def test_eodhd_provider_conforms_to_the_broad_provider_protocol():
    from apex.intraday.provider_interface import (
        BroadMarketDataProvider, EODHDBroadProvider,
    )
    from apex.intraday.equity_fabric import EquityRealtimeFabric
    fab = EquityRealtimeFabric(symbols=["SPY", "QQQ"])
    provider = EODHDBroadProvider(fab)
    assert isinstance(provider, BroadMarketDataProvider)
    ent = provider.get_entitlement()
    assert ent.measured is True
    assert ent.trade_symbol_cap == 50
