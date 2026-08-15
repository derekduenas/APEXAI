"""P1A mandated counterexamples: every load-bearing rule attacked directly.

The directive's list, mapped: future-bar-early / bar-before-completion /
ticker recycle / split-as-crash / future listing / DST session shift /
missing-minute-not-filled / duplicate rows / determinism / provider leak /
broker unreachable from replay / not-wired refusal.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from apex.intraday.contract import (
    DataQuality, IntradayDataError, PartitionManifest, require_quality,
)
from apex.intraday.corporate import (
    SplitAction, analytical_normalized, tradable_price_at,
)
from apex.intraday.identity import IdentityBridge, SecurityIdentityMap
from apex.intraday.massive import MassiveIntradayProvider, NotWired
from apex.intraday.replay import (
    EventType, ReplayClock, replay_events, stream_hash,
)
from apex.intraday.sessions import Session, classify


# --- no lookahead through bar construction -----------------------------------

def test_a_completed_bar_is_invisible_before_completion():
    clock = ReplayClock(pd.Timestamp("2026-03-06 14:30:59", tz="UTC"))
    bar_t = pd.Timestamp("2026-03-06 14:30:00", tz="UTC")   # covers :30:00-:59
    assert not clock.bar_visible(bar_t), "the 09:30 bar is mid-construction"
    with pytest.raises(IntradayDataError, match="NO LOOKAHEAD"):
        clock.require_visible(bar_t)
    clock.advance_to(pd.Timestamp("2026-03-06 14:31:00", tz="UTC"))
    assert clock.bar_visible(bar_t)


def test_the_clock_never_runs_backwards():
    clock = ReplayClock(pd.Timestamp("2026-03-06 14:31:00", tz="UTC"))
    with pytest.raises(IntradayDataError, match="backwards"):
        clock.advance_to(pd.Timestamp("2026-03-06 14:30:00", tz="UTC"))


# --- identity: recycle + ambiguity fail closed -------------------------------

def _bridge():
    return IdentityBridge([
        SecurityIdentityMap("APX-001", "massive", "ABC", "2005-01-01",
                            "2012-06-30", {"permaticker": 111}, "vendor+figi",
                            0.99, "figi match"),
        SecurityIdentityMap("APX-777", "massive", "ABC", "2014-01-01",
                            "9999-12-31", {"permaticker": 777}, "vendor+figi",
                            0.99, "figi match"),
    ])


def test_a_recycled_ticker_resolves_differently_across_time():
    b = _bridge()
    assert b.resolve("ABC", "2010-05-01") == "APX-001"
    assert b.resolve("ABC", "2020-05-01") == "APX-777"


def test_counterexample_unmapped_and_gap_periods_fail_closed():
    b = _bridge()
    with pytest.raises(IntradayDataError, match="NOTHING"):
        b.resolve("ABC", "2013-06-01")          # the dead zone between issuers
    with pytest.raises(IntradayDataError, match="NOTHING"):
        b.resolve("ZZZ", "2020-01-01")


def test_counterexample_overlapping_windows_are_ambiguous_and_refuse():
    b = IdentityBridge([
        SecurityIdentityMap("A", "m", "DUP", "2020-01-01", "9999-12-31",
                            {}, "x", 0.9, ""),
        SecurityIdentityMap("B", "m", "DUP", "2021-01-01", "9999-12-31",
                            {}, "x", 0.9, ""),
    ])
    with pytest.raises(IntradayDataError, match="AMBIGUOUS"):
        b.resolve("DUP", "2022-01-01")


def test_permaticker_disagreement_is_a_finding_not_an_autofix():
    b = _bridge()
    findings = b.reconcile_against_permatickers({"APX-001": 999})
    assert len(findings) == 1 and "999" in findings[0]


# --- corporate actions: three price meanings ---------------------------------

def _raw_split_series():
    idx = pd.date_range("2026-03-02", periods=6, freq="D", tz="UTC")
    # 2:1 split executes 2026-03-05: raw prints halve
    return pd.Series([100.0, 102.0, 104.0, 52.0, 53.0, 54.0], index=idx)


def test_a_split_is_not_an_economic_crash_in_the_analytical_series():
    raw = _raw_split_series()
    actions = [SplitAction("APX-1", "2026-03-05", 2.0)]
    norm = analytical_normalized(raw, actions, "APX-1",
                                 retrospective_use_declared=True)
    rets = norm.pct_change().dropna()
    assert rets.abs().max() < 0.05, "the split boundary must not be a -50% day"


def test_counterexample_the_tradable_price_at_t_is_the_raw_print():
    raw = _raw_split_series()
    actions = [SplitAction("APX-1", "2026-03-05", 2.0)]
    # the day BEFORE the split executes, the agent saw 104, not 52
    assert tradable_price_at(raw, actions, "APX-1", "2026-03-04") == 104.0
    assert tradable_price_at(raw, actions, "APX-1", "2026-03-05") == 52.0


def test_the_analytical_series_refuses_undeclared_retrospective_use():
    with pytest.raises(ValueError, match="must use tradable_price_at"):
        analytical_normalized(_raw_split_series(), [], "APX-1",
                              retrospective_use_declared=False)


# --- sessions: DST + early close ---------------------------------------------

def test_dst_shift_moves_the_session_boundary_for_the_same_utc_hour():
    # 14:00 UTC is 09:00 ET in winter (PREMARKET) but 10:00 ET in summer (REGULAR)
    winter = pd.Timestamp("2026-01-15 14:00", tz="UTC")
    summer = pd.Timestamp("2026-07-15 14:00", tz="UTC")
    assert classify(winter) is Session.PREMARKET
    assert classify(summer) is Session.REGULAR


def test_an_early_close_ends_the_regular_session():
    t = pd.Timestamp("2026-11-27 19:00", tz="UTC")     # 14:00 ET, close 13:00
    assert classify(t) is Session.POSTMARKET


# --- replay: missing minutes, duplicates, determinism ------------------------

def _partition(date, rows):
    return pd.DataFrame(rows, columns=["provider_symbol", "event_time_utc",
                                       "open", "high", "low", "close",
                                       "volume"])


def _day():
    rows = [("XYZ", f"2026-03-06 14:{m:02d}:00+00:00", 10, 11, 9, 10.5, 1000)
            for m in (31, 32, 34)]                     # minute :33 MISSING
    return [("2026-03-06", _partition("2026-03-06", rows))]


def test_a_missing_minute_stays_missing_in_the_event_stream():
    events = list(replay_events(iter(_day()), "2026-03-06 14:30:00+00:00",
                                "2026-03-06 15:00:00+00:00",
                                dataset_fingerprint="f", adapter_version="a",
                                config_hash="c"))
    bar_minutes = [pd.Timestamp(e.payload["bar_time"]).strftime("%H:%M")
                   for e in events if e.event_type is EventType.BAR_AVAILABLE]
    assert "14:33" not in bar_minutes, "absence is data, not a fill"
    assert bar_minutes == ["14:31", "14:32", "14:34"]


def test_counterexample_duplicate_rows_are_refused_not_averaged():
    rows = [("XYZ", "2026-03-06 14:31:00+00:00", 10, 11, 9, 10.5, 1000)] * 2
    with pytest.raises(IntradayDataError, match="duplicate"):
        list(replay_events(iter([("2026-03-06",
                                  _partition("2026-03-06", rows))]),
                           "2026-03-06 14:30:00+00:00",
                           "2026-03-06 15:00:00+00:00",
                           dataset_fingerprint="f", adapter_version="a",
                           config_hash="c"))


def test_replay_is_deterministic_and_provenance_sensitive():
    def run(fp="f"):
        return stream_hash(
            replay_events(iter(_day()), "2026-03-06 14:30:00+00:00",
                          "2026-03-06 15:00:00+00:00",
                          dataset_fingerprint=fp, adapter_version="a",
                          config_hash="c"),
            dataset_fingerprint=fp, adapter_version="a", config_hash="c")
    assert run() == run(), "same inputs must produce the same stream hash"
    assert run() != run(fp="OTHER"), "provenance must be part of the identity"


def test_bar_visibility_in_the_stream_is_completion_time():
    events = list(replay_events(iter(_day()), "2026-03-06 14:30:00+00:00",
                                "2026-03-06 15:00:00+00:00",
                                dataset_fingerprint="f", adapter_version="a",
                                config_hash="c"))
    for e in events:
        if e.event_type is EventType.BAR_AVAILABLE:
            assert (pd.Timestamp(e.visible_at_utc)
                    - pd.Timestamp(e.payload["bar_time"])) == pd.Timedelta(minutes=1)


# --- quality + provider + broker isolation -----------------------------------

def test_critical_quality_fails_closed_and_unknown_is_valid():
    with pytest.raises(IntradayDataError, match="fails closed"):
        require_quality(DataQuality.AMBIGUOUS_IDENTITY, "test")
    require_quality(DataQuality.UNKNOWN, "test")       # valid state, not fatal
    require_quality(DataQuality.MISSING_BAR, "test")   # non-critical


def test_an_unvalidated_partition_is_not_replay_eligible():
    m = PartitionManifest("massive", "bars1m", "2026-03-06", "v1", 100,
                          "a", "b", 10, 1234, "h" * 64, "now", {})
    assert not m.replay_eligible()


def test_the_unwired_massive_adapter_refuses_with_remediation():
    p = MassiveIntradayProvider()
    assert p.availability()["status"] == "BLOCKED_EXTERNAL"
    with pytest.raises(NotWired, match="OPERATOR act"):
        p.get_bars(["APX-1"], "2026-01-01", "2026-01-02", "1m", None)


def test_the_broker_is_unreachable_from_replay():
    import inspect

    import apex.intraday.contract as C
    import apex.intraday.corporate as K
    import apex.intraday.identity as I
    import apex.intraday.massive as M
    import apex.intraday.replay as R
    import apex.intraday.sessions as S
    for mod in (C, I, S, K, R, M):
        src = inspect.getsource(mod)
        for banned in ("apex.hunter.broker", "place_order", "BrokerAdapter"):
            assert banned not in src, (
                f"{mod.__name__} references {banned}: replay must not be "
                f"able to reach execution")
