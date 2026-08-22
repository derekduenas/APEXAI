"""SessionCoverage contract tests (Phase 0.1: SESSION INTEGRITY
HARDENING). Test matrix A-N + calendar edge cases, from the operator's
directive following the 2026-08-17 Day-1 defect."""
from __future__ import annotations

import pandas as pd
import pytest

from apex.hunter.session_coverage import (
    DEGRADED, FULL, INVALID, PARTIAL, compute_session_coverage,
)

DAY = "2026-08-17"          # Monday, regular session
T_1030 = pd.Timestamp("2026-08-17 14:30:00", tz="UTC")   # 10:30 ET


def _bars(times, **kw):
    n = len(times)
    return pd.DataFrame({
        "event_time_utc": times,
        "open": kw.get("open", [1.0] * n), "high": [1.0] * n,
        "low": [1.0] * n, "close": [1.0] * n, "volume": [1.0] * n})


def _minutes(start, n):
    return pd.date_range(start, periods=n, freq="1min", tz="UTC")


# A/B — full session beginning exactly 09:30 ET
def test_a_full_session_from_true_open_is_full_and_anchor_valid():
    bars = _bars(_minutes("2026-08-17 13:30:00+00:00", 60))
    sc = compute_session_coverage(bars, DAY, T_1030)
    assert sc.quality == FULL
    assert sc.session_anchor_valid
    assert sc.opening_observed
    assert sc.coverage_fraction == 1.0
    assert sc.missing_intervals == ()


def test_b_first_bar_exactly_09_30_00_is_the_boundary_pass_case():
    bars = _bars(_minutes("2026-08-17 13:30:00+00:00", 1))
    sc = compute_session_coverage(bars, DAY,
                                  pd.Timestamp("2026-08-17 13:31:00", tz="UTC"))
    assert sc.session_anchor_valid
    assert sc.opening_observed


# C — first bar 09:31 (one minute late): must NOT pass
def test_c_first_bar_one_minute_late_invalidates_anchor():
    bars = _bars(_minutes("2026-08-17 13:31:00+00:00", 59))
    sc = compute_session_coverage(bars, DAY, T_1030)
    assert sc.quality == INVALID
    assert not sc.session_anchor_valid
    assert not sc.opening_observed


# D — the actual Day-1 case, first bar 10:17 ET
def test_d_first_bar_1017_et_is_invalid():
    bars = _bars(_minutes("2026-08-17 14:17:00+00:00", 30))
    sc = compute_session_coverage(bars, DAY,
                                  pd.Timestamp("2026-08-17 14:47:00", tz="UTC"))
    assert sc.quality == INVALID
    assert not sc.session_anchor_valid
    assert sc.missing_intervals[0] == (
        "2026-08-17 13:30:00+00:00", "2026-08-17 14:17:00+00:00")


# E — missing middle interval: anchor stays valid, quality degrades
def test_e_missing_middle_interval_is_partial_anchor_still_valid():
    idx = _minutes("2026-08-17 13:30:00+00:00", 60)
    idx = idx[:20].append(idx[25:])            # drop minutes 20-24
    bars = _bars(idx)
    sc = compute_session_coverage(bars, DAY, T_1030)
    assert sc.session_anchor_valid           # the OPEN was observed
    assert sc.quality == PARTIAL
    assert sc.missing_intervals == (
        ("2026-08-17 13:50:00+00:00", "2026-08-17 13:55:00+00:00"),)
    assert sc.continuous_since == "2026-08-17 13:55:00+00:00"


# F — disconnect/reconnect: same mechanism as E, framed as an outage
def test_f_disconnect_then_reconnect_reads_as_partial_with_gap_recorded():
    idx = _minutes("2026-08-17 13:30:00+00:00", 60)
    idx = idx[:40].append(idx[50:])            # 10-minute outage
    bars = _bars(idx)
    sc = compute_session_coverage(bars, DAY, T_1030)
    assert sc.session_anchor_valid
    assert sc.quality in (PARTIAL, DEGRADED)
    assert len(sc.missing_intervals) == 1


# G — prior close known, true open missing: anchor still invalid
def test_g_known_prior_close_does_not_rescue_a_missing_true_open():
    bars = _bars(_minutes("2026-08-17 14:00:00+00:00", 30))  # 10:00 ET start
    sc = compute_session_coverage(bars, DAY,
                                  pd.Timestamp("2026-08-17 14:30:00", tz="UTC"))
    assert not sc.session_anchor_valid
    assert sc.quality == INVALID   # prev_close is a ChartState/ctx concern,
                                    # never rescues session_coverage itself


# H — opening print exists, then a gap right after
def test_h_opening_observed_then_immediate_gap_stays_anchor_valid():
    idx = _minutes("2026-08-17 13:30:00+00:00", 60)
    idx = idx[:1].append(idx[11:])             # only :30 print, then gap to :41
    bars = _bars(idx)
    sc = compute_session_coverage(bars, DAY, T_1030)
    assert sc.opening_observed
    assert sc.session_anchor_valid
    assert sc.missing_intervals[0][0] == "2026-08-17 13:31:00+00:00"


# I — DST boundary: EDT (summer) vs EST (winter) session_open in UTC
def test_i_dst_boundary_summer_vs_winter_open_utc_offset():
    from apex.hunter.session_coverage import _true_session_bounds
    summer_open, _ = _true_session_bounds("2026-08-17")   # EDT, UTC-4
    winter_open, _ = _true_session_bounds("2026-01-20")   # EST, UTC-5
    assert summer_open.hour == 13 and summer_open.minute == 30
    assert winter_open.hour == 14 and winter_open.minute == 30


# J — early close (2026-11-27, Thanksgiving, 13:00 ET close)
def test_j_early_close_shrinks_required_session():
    bars = _bars(_minutes("2026-11-27 14:30:00+00:00", 1))   # 09:30 ET
    t = pd.Timestamp("2026-11-27 18:05:00", tz="UTC")        # 13:05 ET, past close
    sc = compute_session_coverage(bars, "2026-11-27", t)
    assert sc.session_close == "2026-11-27 18:00:00+00:00"   # 13:00 ET
    assert sc.required_minutes == 210                        # 09:30-13:00


# K — market holiday: no session exists, never a crash
def test_k_market_holiday_returns_invalid_not_a_crash():
    bars = _bars(_minutes("2026-01-01 14:30:00+00:00", 5))
    sc = compute_session_coverage(bars, "2026-01-01",
                                  pd.Timestamp("2026-01-01 15:00:00", tz="UTC"))
    assert sc.quality == INVALID
    assert sc.session_open is None


# L — premarket bars present before regular open: excluded from coverage
def test_l_premarket_bars_do_not_count_as_regular_session_coverage():
    pre = _minutes("2026-08-17 08:00:00+00:00", 30)           # 04:00 ET+
    reg = _minutes("2026-08-17 13:30:00+00:00", 30)
    bars = _bars(pre.append(reg))
    sc = compute_session_coverage(bars, DAY, T_1030)
    assert sc.session_anchor_valid
    assert sc.observed_minutes == 30                          # premarket excluded


# M — postmarket bars present: excluded from coverage
def test_m_postmarket_bars_do_not_count_as_regular_session_coverage():
    reg = _minutes("2026-08-17 13:30:00+00:00", 60)
    post = _minutes("2026-08-17 20:05:00+00:00", 10)          # after 16:00 ET
    bars = _bars(reg.append(post))
    sc = compute_session_coverage(bars, DAY, T_1030)
    assert sc.observed_minutes == 60


# N — out-of-order data: sorted internally, no corruption
def test_n_out_of_order_bars_do_not_corrupt_observed_start():
    idx = _minutes("2026-08-17 13:30:00+00:00", 30)
    bars = _bars(idx).sample(frac=1, random_state=3).reset_index(drop=True)
    sc = compute_session_coverage(bars, DAY,
                                  pd.Timestamp("2026-08-17 14:00:00", tz="UTC"))
    assert sc.observed_start == str(idx[0])
    assert sc.session_anchor_valid


# O — duplicate bars: never double-counted
def test_o_duplicate_bars_are_not_double_counted():
    idx = _minutes("2026-08-17 13:30:00+00:00", 30)
    bars = pd.concat([_bars(idx), _bars(idx[:10])], ignore_index=True)
    sc = compute_session_coverage(bars, DAY,
                                  pd.Timestamp("2026-08-17 14:00:00", tz="UTC"))
    assert sc.observed_minutes == 30


def test_no_bars_at_all_is_invalid_not_a_crash():
    empty = pd.DataFrame(columns=["event_time_utc", "open", "high", "low",
                                  "close", "volume"])
    sc = compute_session_coverage(empty, DAY, T_1030)
    assert sc.quality == INVALID
    assert sc.session_open is not None       # calendar still resolves


def test_as_of_must_be_tz_aware():
    from apex.hunter.session_coverage import SessionCoverageViolation
    bars = _bars(_minutes("2026-08-17 13:30:00+00:00", 5))
    with pytest.raises(SessionCoverageViolation):
        compute_session_coverage(bars, DAY, pd.Timestamp("2026-08-17 10:30:00"))
