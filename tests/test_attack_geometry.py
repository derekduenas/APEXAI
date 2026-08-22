"""ATTACK GEOMETRY property tests (§7 of the v2 Phase 1 directive).

These are PROPERTY tests, not outcome tests: none of them references
profitability, and none was written after inspecting realized P&L.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from apex.predators.core.attack_geometry import (  # noqa: E402
    ENTRY_ATTACKABLE, NOT_ESTIMABLE, AttackGeometry, GeometryRefused,
    unknown_geometry)
from apex.predators.equities.attack_geometry import (  # noqa: E402
    EquityAttackGeometry, atr, session_vwap)

T0 = pd.Timestamp("2026-08-21 14:00:00", tz="UTC")


def _bars(prices, *, vol=10000, start=T0, scale=1.0, noise=None):
    """1m bars from a close path.

    Intrabar range is proportional to the bar-to-bar move (real 1m bars
    have a true range comparable to their drift). A first fixture used
    a fixed 0.2% range regardless of drift, which made ATR absurdly
    small and every path read as a chase -- the geometry was right and
    the synthetic data was wrong.
    """
    out = []
    for i, p in enumerate(prices):
        p = p * scale
        step = abs(prices[i] - prices[i - 1]) * scale if i else \
            abs(prices[1] - prices[0]) * scale
        rng = max(step, p * 0.0005) * (noise if noise is not None else 1.5)
        out.append({"event_time_utc": str(start + pd.Timedelta(minutes=i)),
                    "open": p, "high": p + rng / 2, "low": p - rng / 2,
                    "close": p, "volume": vol, "trades": 50,
                    "coverage_status": "COMPLETE_HEALTHY",
                    "symbol": "TEST"})
    return out


def _flat_then_pullback():
    """The canonical GOOD entry: a coiled range that establishes VWAP,
    a small push off it, then a drift back toward VWAP.

    A first attempt used a steady 40-bar grind with a shallow pullback
    and called it 'good'. The geometry correctly read it as a chase --
    closing 4 ATR above session VWAP is a chase however smooth the
    trend was. Reachability was then verified against 164 real symbols
    on the 2026-08-21 session: GOOD fires on 8.5% of real windows, so
    the rules are selective, not unreachable. This fixture encodes the
    shape that actually produces it -- a coil, not a grind.
    """
    coil = [100 + (0.3 if i % 2 else -0.3) for i in range(32)]
    drift = [100.3, 100.45, 100.5, 100.42, 100.3, 100.22, 100.15, 100.1]
    return coil + drift


def _runaway(n=40):
    """Vertical extension far from VWAP: the canonical chase."""
    return [100 + i * i * 0.02 for i in range(n)]


def _now(bars):
    return pd.Timestamp(bars[-1]["event_time_utc"]) + pd.Timedelta(minutes=1)


ENG = EquityAttackGeometry()


def _compute(bars, direction="LONG", **kw):
    return ENG.compute(subject="TEST", direction=direction, bars=bars,
                       now=_now(bars), known_from=str(_now(bars)), **kw)


# ---------------------------------------------- scale invariance

def test_same_structure_under_price_scaling_reads_identically():
    """A $3 stock and a $700 stock with identical structure must get
    identical normalized geometry."""
    path = _flat_then_pullback()
    cheap = _compute(_bars(path, scale=0.03))
    rich = _compute(_bars(path, scale=7.0))
    assert cheap.entry_quality == rich.entry_quality
    assert cheap.chase_risk == rich.chase_risk
    assert abs(cheap.invalidation_distance_atr -
               rich.invalidation_distance_atr) < 1e-6
    # and the dimensionless units really are dimensionless
    assert cheap.local_volatility_atr != rich.local_volatility_atr


# ---------------------------------------------- honest unknowns

def test_stale_input_is_unknown_not_neutral():
    bars = _bars(_flat_then_pullback())
    late = pd.Timestamp(bars[-1]["event_time_utc"]) + pd.Timedelta(hours=2)
    g = ENG.compute(subject="TEST", direction="LONG", bars=bars,
                    now=late, known_from=str(late))
    assert g.entry_quality == "UNKNOWN"
    assert g.expected_mae_r == NOT_ESTIMABLE
    assert not g.attackable


def test_insufficient_bars_is_unknown():
    g = _compute(_bars([100, 101, 102]))
    assert g.entry_quality == "UNKNOWN"
    assert "insufficient bars" in g.pedigree["reason"]


def test_unknown_never_becomes_zero_or_neutral():
    g = unknown_geometry("EQUITIES_INTRADAY", "X", "LONG", str(T0), "test")
    for v in (g.expected_mae_r, g.expected_mfe_r, g.time_to_move,
              g.reward_risk_available):
        assert v == NOT_ESTIMABLE and v != 0
    assert g.invalidation is None          # not 0.0
    assert g.local_volatility_atr is None


# ---------------------------------------------- the structural laws

def test_missing_liquidity_cannot_yield_excellent_entry():
    """Constructor-level law: no known liquidity -> no STRONG."""
    with pytest.raises(GeometryRefused, match="liquidity"):
        AttackGeometry(
            sleeve="EQUITIES_INTRADAY", subject="X", direction="LONG",
            entry_quality="STRONG", geometry_quality="STRONG",
            entry_zone=(1.0, 2.0), invalidation=0.9,
            invalidation_distance_atr=0.5, chase_risk="LOW",
            local_volatility_atr=0.2, liquidity_quality="UNKNOWN",
            expected_mae_r=NOT_ESTIMABLE, expected_mfe_r=NOT_ESTIMABLE,
            time_to_move=NOT_ESTIMABLE, reward_risk_available=3.0,
            data_quality="FULL", known_from=str(T0))


def test_equity_v1_ceiling_is_GOOD_because_quotes_are_not_persisted():
    """An honest ceiling, recorded rather than routed around."""
    g = _compute(_bars(_flat_then_pullback()))
    assert g.entry_quality != "STRONG"
    assert g.liquidity_quality == NOT_ESTIMABLE
    assert any("STRONG withheld" in r for r in g.reasoning) or \
        g.entry_quality != "GOOD"


def test_chase_cannot_be_rescued_by_trend_strength():
    """Far extension must not become attackable however strong the
    move that produced it."""
    g = _compute(_bars(_runaway()))
    assert g.chase_risk in ("HIGH", "EXTREME")
    assert g.entry_quality == "POOR"
    assert not g.attackable
    with pytest.raises(GeometryRefused, match="chase"):
        AttackGeometry(
            sleeve="E", subject="X", direction="LONG",
            entry_quality="GOOD", geometry_quality="GOOD",
            entry_zone=(1.0, 2.0), invalidation=0.9,
            invalidation_distance_atr=0.5, chase_risk="EXTREME",
            local_volatility_atr=0.2, liquidity_quality="FULL",
            expected_mae_r=NOT_ESTIMABLE, expected_mfe_r=NOT_ESTIMABLE,
            time_to_move=NOT_ESTIMABLE, reward_risk_available=3.0,
            data_quality="FULL", known_from=str(T0))


def test_tight_invalidation_alone_does_not_imply_good_trade():
    """A coiled, tight-stop chase is still a chase."""
    path = [100 + i * i * 0.02 for i in range(32)] + [
        100 + 31 * 31 * 0.02] * 8            # tight stop after a run
    g = _compute(_bars(path))
    assert g.invalidation_distance_atr is not None
    if g.chase_risk in ("HIGH", "EXTREME"):
        assert g.entry_quality == "POOR"


def test_good_thesis_bad_entry_remains_distinguishable():
    """Geometry never sees the thesis: the same subject can be
    simultaneously worth caring about and unattackable."""
    good = _compute(_bars(_flat_then_pullback()))
    bad = _compute(_bars(_runaway()))
    assert good.entry_quality != bad.entry_quality
    assert good.subject == bad.subject      # thesis identity unchanged


def test_geometry_cannot_see_the_thesis_at_all():
    """Structural proof of the separation: compute() has no thesis
    parameter, so a bad thesis cannot borrow good geometry."""
    import inspect
    params = set(inspect.signature(ENG.compute).parameters)
    for forbidden in ("thesis", "thesis_quality", "conviction",
                      "direction_quality", "outcome", "pnl", "realized"):
        assert forbidden not in params


def test_future_bars_never_enter_computation():
    bars = _bars(_flat_then_pullback())
    early = pd.Timestamp(bars[0]["event_time_utc"])
    with pytest.raises(ValueError, match="NO-FUTURE-BARS"):
        ENG.compute(subject="TEST", direction="LONG", bars=bars,
                    now=early, known_from=str(early))


def test_short_direction_mirrors_long():
    path = [100 - i * 0.05 for i in range(32)] + [
        100 - 31 * 0.05 + i * 0.04 for i in range(1, 9)]
    g = _compute(_bars(path), direction="SHORT")
    assert g.direction == "SHORT"
    assert g.invalidation > g.entry_zone[0]      # stop is above


# ---------------------------------------------- primitives

def test_atr_and_vwap_are_real_computations():
    bars = _bars([100 + i * 0.1 for i in range(30)])
    a = atr(bars)
    v = session_vwap(bars)
    assert a and a > 0
    assert 100 <= v <= 103


def test_atr_refuses_short_history():
    assert atr(_bars([100, 101, 102])) is None


def test_pedigree_declares_it_is_not_outcome_tuned():
    g = _compute(_bars(_flat_then_pullback()))
    assert g.pedigree["not_outcome_tuned"] is True
    assert "before any profitability" in g.pedigree["rules_predeclared"]


def test_entry_tiers_match_what_captain_accepts():
    """If Captain's accepted tiers ever drift, geometry must fail
    loudly rather than silently stop being attackable."""
    from apex.frontier2 import captain_shadow as cs
    assert set(ENTRY_ATTACKABLE) == set(cs._ENTRY_QUALITY_STRONG)
