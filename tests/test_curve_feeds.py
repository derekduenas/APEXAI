"""CURVE DIMENSION FEED tests -- semantics, causality, redundancy.

No outcome data is read anywhere in this file.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from apex.predators.equities import curve_feeds as cf  # noqa: E402

T0 = pd.Timestamp("2026-08-21 14:00:00", tz="UTC")


def _bars(closes, vols=None):
    return [{"event_time_utc": str(T0 + pd.Timedelta(minutes=i)),
             "close": c, "open": c, "high": c * 1.001, "low": c * 0.999,
             "volume": (vols[i] if vols else 10000),
             "coverage_status": "COMPLETE_HEALTHY"}
            for i, c in enumerate(closes)]


# ------------------------------------------------ SEMANTIC HONESTY LAW

def test_liquidity_is_not_estimable_and_has_no_proxy_backdoor():
    """The operator's law: bar activity is NOT executable liquidity."""
    d = cf.DARK_DIMENSIONS["liquidity"]
    assert d["status"] == "NOT_ESTIMABLE"
    assert "persisted bid" in d["requires"]
    # no function in this module produces anything named liquidity
    assert not [n for n in dir(cf)
                if "liquidity" in n.lower() and n.endswith("_points")]


def test_flow_is_starved_and_the_proxy_is_named_proxy():
    assert cf.DARK_DIMENSIONS["flow"]["status"] == "INPUT_STARVED"
    assert hasattr(cf, "volume_pressure_proxy_points")
    assert not hasattr(cf, "flow_points")
    sem = cf.FEED_SEMANTICS["volume_pressure_proxy"]
    assert sem["kind"] == "PROXY"
    assert sem["dimension"] is None          # may not fill a canonical slot
    assert "may NOT populate flow" in sem["law"]


def test_cross_asset_is_not_faked_from_equity_etfs():
    assert cf.DARK_DIMENSIONS["cross_asset"]["status"] == "NOT_JUSTIFIED"
    assert hasattr(cf, "cross_equity_complex_points")
    assert not hasattr(cf, "cross_asset_points")
    sem = cf.FEED_SEMANTICS["cross_equity_complex"]
    assert sem["kind"] == "PROXY" and sem["dimension"] is None


def test_event_reaction_starved_for_a_named_reason():
    d = cf.DARK_DIMENSIONS["event_reaction"]
    assert d["status"] == "INPUT_STARVED"
    assert "CIK" in d["requires"][0]


def test_every_proxy_carries_proxy_in_its_identity():
    for name, sem in cf.FEED_SEMANTICS.items():
        if sem["kind"] == "PROXY":
            assert "proxy" in name.lower() or "complex" in name.lower()
            assert sem["dimension"] is None


# ------------------------------------------------ VOLATILITY

def test_volatility_is_scale_invariant():
    path = [100 + math.sin(i / 3) for i in range(60)]
    a = cf.volatility_points(_bars(path))
    b = cf.volatility_points(_bars([p * 37.0 for p in path]))
    assert a and len(a) == len(b)
    for (t1, v1), (t2, v2) in zip(a, b):
        assert t1 == t2
        assert abs(v1 - v2) < 1e-9          # log returns: identical


def test_volatility_rises_when_volatility_rises():
    calm = [100 + 0.01 * ((-1) ** i) for i in range(60)]
    wild = calm[:30] + [100 + 1.5 * ((-1) ** i) for i in range(30)]
    pts = cf.volatility_points(_bars(wild))
    assert pts
    assert pts[-1][1] > pts[0][1] * 5


def test_volatility_refuses_short_history():
    assert cf.volatility_points(_bars([100, 101, 102])) == []


def test_volatility_is_causal():
    """The value stamped at T uses only bars up to T: truncating the
    future cannot change an earlier value."""
    path = [100 + math.sin(i / 4) for i in range(80)]
    full = cf.volatility_points(_bars(path))
    trunc = cf.volatility_points(_bars(path[:50]))
    common = {t: v for t, v in full}
    for t, v in trunc:
        assert abs(common[t] - v) < 1e-12


# ------------------------------------------------ CORRELATION

def test_correlation_is_not_redundant_with_relative_strength():
    """THE REDUNDANCY TEST the directive demands: construct a case
    where relative strength is CONSTANT while correlation collapses.
    If correlation were a repackaging of RS this would be impossible."""
    n = 90
    mkt = [100 * (1 + 0.0005 * i) for i in range(n)]
    # subject holds a constant ratio to the market for the first half
    # (RS flat, correlation ~1), then oscillates around that same ratio
    # (RS still ~flat on average, correlation destroyed)
    sub = [m * 1.05 for m in mkt[:45]]
    sub += [mkt[i] * 1.05 * (1 + 0.004 * ((-1) ** i))
            for i in range(45, n)]
    corr = cf.correlation_points(_bars(sub), _bars(mkt))
    assert corr, "correlation series not produced"
    early = [v for t, v in corr[:5]]
    late = [v for t, v in corr[-5:]]
    assert sum(early) / len(early) > 0.8, "should start coupled"
    assert sum(late) / len(late) < 0.5, "should decouple"
    # and RS (the ratio) is essentially unchanged end to end
    rs_start, rs_end = sub[0] / mkt[0], sub[-1] / mkt[-1]
    assert abs(rs_end - rs_start) < 0.02


def test_correlation_bounded_and_aligned_on_time():
    n = 60
    mkt = [100 + math.sin(i / 5) for i in range(n)]
    sub = [50 + math.sin(i / 5) * 0.5 for i in range(n)]
    pts = cf.correlation_points(_bars(sub), _bars(mkt))
    assert pts
    for _t, v in pts:
        assert -1.0001 <= v <= 1.0001


def test_correlation_refuses_unaligned_or_short_series():
    assert cf.correlation_points(_bars([100] * 5), _bars([100] * 5)) == []


# ------------------------------------------------ PROXIES

def test_cross_equity_complex_needs_at_least_two_members():
    one = {"SPY": _bars([100 + i * 0.1 for i in range(60)])}
    assert cf.cross_equity_complex_points(one) == []


def test_cross_equity_complex_rises_on_disagreement():
    n = 70
    agree = {s: _bars([100 + i * 0.1 for i in range(n)])
             for s in ("SPY", "QQQ", "IWM")}
    pts_agree = cf.cross_equity_complex_points(agree)
    disagree = {"SPY": _bars([100 + i * 0.1 for i in range(n)]),
                "QQQ": _bars([100 + i * 0.4 for i in range(n)]),
                "IWM": _bars([100 - i * 0.3 for i in range(n)])}
    pts_dis = cf.cross_equity_complex_points(disagree)
    assert pts_agree and pts_dis
    assert pts_dis[-1][1] > pts_agree[-1][1]


def test_volume_pressure_proxy_responds_to_volume_and_sign():
    n = 60
    closes = [100 + 0.05 * i for i in range(n)]
    normal = cf.volume_pressure_proxy_points(_bars(closes))
    vols = [10000] * (n - 1) + [500000]
    spike = cf.volume_pressure_proxy_points(_bars(closes, vols))
    assert normal and spike
    assert abs(spike[-1][1]) > abs(normal[-1][1]) * 5
    down = cf.volume_pressure_proxy_points(
        _bars([100 - 0.05 * i for i in range(n)]))
    assert down[-1][1] < 0 < normal[-1][1]


# ------------------------------------------------ shadow discipline

def test_feeds_are_shadow_power_until_promoted():
    assert cf.SHADOW_POWER == "NONE_CURVE_DIMENSION_SHADOW"


def test_dependency_groups_are_declared_with_reasons():
    for name in ("volatility", "correlation"):
        sem = cf.FEED_SEMANTICS[name]
        assert sem["kind"] == "CANONICAL"
        assert sem["dependency_group"]
        assert sem["reason_for_group"]


def test_correlation_group_is_cross_sectional_not_gamed():
    """Correlation needs another subject, so it shares the
    cross-sectional dependency -- assigning it a private group to
    manufacture independence would be gaming."""
    assert cf.FEED_SEMANTICS["correlation"]["dependency_group"] == \
        "CROSS_SECTIONAL"
    from apex.frontier2.curve import DEPENDENCY_GROUPS
    assert DEPENDENCY_GROUPS["correlation"] == "CROSS_SECTIONAL"
    assert DEPENDENCY_GROUPS["volatility"] == "VOLATILITY"
