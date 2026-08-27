"""GEO-2026-08-26-A — degenerate geometry is never a location.

Found by the 2026-08-26 end-to-end causal audit. reward/risk was
guarded against adverse == 0; entry_quality was not, so a ZERO
invalidation distance satisfied `inval_atr <= INVALIDATION_GOOD_ATR`
and scored as the BEST possible location. AAPL 12:01:57 recorded
exactly that and was blocked only by chase == EXTREME -- by luck, not
by law.

SEMANTIC repair, not a tuned threshold: the epsilon identifies
floating-point zero and says nothing about how much risk room is
economically sensible.
"""
from __future__ import annotations

import inspect
import math

from apex.predators.equities.attack_geometry import (
    DEGENERATE_ATR_EPSILON, INVALIDATION_GOOD_ATR, EquityAttackGeometry)


def _bars(closes, *, lows=None, highs=None):
    import pandas as pd
    n = len(closes)
    lows = lows if lows is not None else [c - 0.5 for c in closes]
    highs = highs if highs is not None else [c + 0.5 for c in closes]
    t0 = pd.Timestamp("2026-08-26 13:30:00", tz="UTC")
    return [{"event_time_utc": str(t0 + pd.Timedelta(minutes=i)),
             "open": closes[i], "high": highs[i], "low": lows[i],
             "close": closes[i], "volume": 1000,
             "coverage_status": "COMPLETE_HEALTHY"} for i in range(n)]


def _geo(bars, direction):
    import pandas as pd
    now = pd.Timestamp(bars[-1]["event_time_utc"]) + pd.Timedelta(minutes=1)
    return EquityAttackGeometry().compute(
        subject="TEST", direction=direction, bars=bars, now=now,
        known_from=str(now))


def _close_on_swing_low(n=40):
    """Close sits EXACTLY on the 20-bar swing low -> adverse == 0."""
    closes = [100.0 + i * 0.01 for i in range(n - 1)] + [99.0]
    lows = [c - 0.4 for c in closes[:-1]] + [99.0]
    return _bars(closes, lows=lows)


def _close_on_swing_high(n=40):
    closes = [100.0 - i * 0.01 for i in range(n - 1)] + [101.0]
    highs = [c + 0.4 for c in closes[:-1]] + [101.0]
    return _bars(closes, highs=highs)


def test_zero_invalidation_distance_is_degenerate_long():
    g = _geo(_close_on_swing_low(), "LONG")
    assert g.invalidation_distance_atr <= DEGENERATE_ATR_EPSILON
    assert g.entry_quality == "DEGENERATE_GEOMETRY"
    assert "no room to be wrong" in " ".join(g.reasoning)


def test_zero_invalidation_distance_is_degenerate_short():
    """The SHORT side is protected identically -- a mirrored defect
    would be exactly as dangerous."""
    g = _geo(_close_on_swing_high(), "SHORT")
    assert g.invalidation_distance_atr <= DEGENERATE_ATR_EPSILON
    assert g.entry_quality == "DEGENERATE_GEOMETRY"


def test_degenerate_is_never_good_even_though_zero_passes_the_old_test():
    """THE ACTUAL DEFECT: 0.0 <= INVALIDATION_GOOD_ATR was TRUE, so the
    old branch scored zero risk room as the best possible location."""
    assert 0.0 <= INVALIDATION_GOOD_ATR, "the old branch would match"
    g = _geo(_close_on_swing_low(), "LONG")
    assert g.entry_quality not in ("GOOD", "ACCEPTABLE")


def test_degenerate_geometry_is_not_attackable_by_construction():
    """entry_quality feeds a WHITELIST, so a new state is
    non-attackable without anyone remembering to block it."""
    from apex.predators.options.attack_geometry import assess
    src = inspect.getsource(assess)
    assert 'ug in ("STRONG", "GOOD")' in src
    assert "DEGENERATE_GEOMETRY" not in src, \
        "the whitelist must never be widened to admit it"


def test_normal_positive_invalidation_is_unchanged():
    """The incumbent path must behave exactly as before."""
    closes = [100.0 + math.sin(i / 3) * 0.6 for i in range(40)]
    g = _geo(_bars(closes), "LONG")
    assert g.invalidation_distance_atr > DEGENERATE_ATR_EPSILON
    assert g.entry_quality in ("GOOD", "ACCEPTABLE", "POOR")


def test_the_epsilon_is_numerical_not_economic():
    """1e-9 identifies floating-point zero. A value chosen because
    '0.15 ATR performs badly' would be strategy tuning."""
    assert 0 < DEGENERATE_ATR_EPSILON <= 1e-6
    assert DEGENERATE_ATR_EPSILON < INVALIDATION_GOOD_ATR / 1000


def test_declared_risk_must_be_positive_on_both_expressions():
    """Clause 4: R = pnl / declared_1R, so a zero denominator makes R
    undefined, and a costless debit spread is a quote artifact."""
    from apex.predators.options import expression as ex
    assert ex.MIN_DECLARED_RISK > 0
    src = inspect.getsource(ex)
    assert src.count("MIN_DECLARED_RISK") >= 3, \
        "the single leg AND the vertical must both be guarded"


def test_a_flat_tape_does_not_crash_and_is_not_good():
    """Every high == low == close: adverse is 0 and ATR may be 0."""
    closes = [100.0] * 40
    g = _geo(_bars(closes, lows=[100.0] * 40, highs=[100.0] * 40),
             "LONG")
    assert g.entry_quality in ("DEGENERATE_GEOMETRY", "UNKNOWN")


# ============ FRESHNESS PROPAGATION -- READ-ONLY AUDIT RESULT
# The 2026-08-26 audit flagged FRESHNESS_PROPAGATION as a GAP because
# quote age is not carried into the Expression Arena. The read-only
# follow-up found CASE A: stale data is structurally prevented from
# reaching the arena at all, so carrying the field there is
# unnecessary. These tests PROVE the contract instead of building one.

def test_stale_quotes_are_gated_upstream_of_the_expression_arena():
    """live_world judges freshness against a PREDECLARED limit and
    downgrades feed_quality; the session then returns FEED_DEGRADED
    BEFORE geometry, expression or execution are ever reached."""
    from apex.predators.options import live_world
    src = inspect.getsource(live_world)
    assert "MAX_QUOTE_AGE_S" in src
    assert live_world.MAX_QUOTE_AGE_S > 0
    assert 'quality = "STALE_QUOTES"' in src

    from pathlib import Path
    sess = Path("scripts/options_paper_session.py").read_text()
    i_gate = sess.index('if obs.feed_quality != "GOOD"')
    i_geom = sess.index("underlying_bridge.build")
    i_expr = sess.index("build_candidates")
    assert i_gate < i_geom < i_expr, \
        "the freshness gate must precede geometry AND the arena"
    assert 'status": "FEED_DEGRADED"' in sess[i_gate:i_geom]


def test_the_live_path_declares_its_timezone_convention():
    """The ET-naive quote vs UTC-aware bar mismatch is the same defect
    class that produced three analytical errors; the live path states
    the convention explicitly rather than inferring it."""
    from apex.predators.options import live_world
    src = inspect.getsource(live_world)
    assert "TIMEZONE CONVENTION" in src
    assert "ET-NAIVE" in src and "UTC-AWARE" in src
    assert "tz_convert" in src and "tz_localize(None)" in src
