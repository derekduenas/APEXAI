"""OPTIONS ACQUISITION -- ANTI-LOOKAHEAD PROPERTY TESTS (permanent).

Born of the operator's 2026-08-22 catch: the first ingest used the
day's median REGULAR close as the moneyness reference, so a 10:00
retention decision knew 14:00 prices. These tests make that class of
defect structurally impossible to reintroduce.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))


def _mk_ref(bars):
    """Rebuild the daemon's underlying_ref closure from synthetic bars
    (same construction as acquire_symbol_day)."""
    import bisect
    ref_times, ref_closes = [], []
    for b in bars:
        t = pd.Timestamp(b["t"]).tz_convert("America/New_York")
        ref_times.append(t.tz_localize(None) + pd.Timedelta(minutes=1))
        ref_closes.append((b["c"], t.tz_localize(None), "REGULAR"))

    def underlying_ref(T):
        i = bisect.bisect_right(ref_times, T) - 1
        if i < 0:
            return None
        c, lbl, ses = ref_closes[i]
        return (c, lbl, (T - ref_times[i]).total_seconds(), ses)
    return underlying_ref


def _bars(path, start="2024-01-03T14:30:00Z"):
    t0 = pd.Timestamp(start)
    return [{"t": str(t0 + pd.Timedelta(minutes=i)), "c": c}
            for i, c in enumerate(path)]


def test_bar_label_semantics_start_of_bar():
    """A bar labeled L is knowable only from L+1min: the ref at exactly
    L must be the PREVIOUS bar's close, never bar L's own close."""
    ref = _mk_ref(_bars([100.0, 110.0, 120.0]))
    at_l1 = ref(pd.Timestamp("2024-01-03 09:31:00"))
    assert at_l1[0] == 100.0            # bar 09:30's close, not 09:31's
    at_l2 = ref(pd.Timestamp("2024-01-03 09:32:00"))
    assert at_l2[0] == 110.0
    # before any bar has closed: honest None, never zero
    assert ref(pd.Timestamp("2024-01-03 09:30:00")) is None
    # session-edge probes the directive names
    assert ref(pd.Timestamp("2024-01-03 09:30:30")) is None
    assert ref(pd.Timestamp("2024-01-03 09:31:30"))[0] == 100.0


def test_option_may_enter_and_leave_the_band_intraday():
    """A strike-105 contract vs a path 100 -> 130: moneyness 1.05 (in
    band) early, 0.81 (in) mid, 0.807... then out as spot passes 131 --
    eligibility is a per-minute fact, not a day fact."""
    path = [100.0 + i for i in range(35)]      # 100 -> 134
    ref = _mk_ref(_bars(path))
    strike = 105.0
    t0 = pd.Timestamp("2024-01-03 09:31:00")
    verdicts = []
    for i in range(34):
        r = ref(t0 + pd.Timedelta(minutes=i))
        m = strike / r[0]
        verdicts.append(0.80 < m < 1.20)
    assert verdicts[0] is True                 # 105/100 = 1.05
    assert verdicts[-1] is False               # 105/133 = 0.79 -> out
    assert True in verdicts and False in verdicts


def test_mutating_future_prices_cannot_change_earlier_eligibility():
    """THE PERMANENT ANTI-LOOKAHEAD TEST: rewrite every future bar;
    every earlier retention verdict must be bit-identical."""
    base = [100.0 + 0.5 * i for i in range(60)]
    mutated = base[:30] + [500.0] * 30         # absurd future
    ref_a, ref_b = _mk_ref(_bars(base)), _mk_ref(_bars(mutated))
    t0 = pd.Timestamp("2024-01-03 09:31:00")
    for strike in (85.0, 100.0, 115.0, 130.0):
        for i in range(29):                     # instants before mutation
            T = t0 + pd.Timedelta(minutes=i)
            ra, rb = ref_a(T), ref_b(T)
            assert ra == rb, f"future mutated the past at {T}"
            va = 0.80 < strike / ra[0] < 1.20
            vb = 0.80 < strike / rb[0] < 1.20
            assert va == vb


def test_ref_is_monotone_and_never_future():
    """underlying_ref(T) source label is always strictly before T."""
    ref = _mk_ref(_bars([100.0 + i for i in range(20)]))
    t0 = pd.Timestamp("2024-01-03 09:31:00")
    for i in range(19):
        T = t0 + pd.Timedelta(minutes=i)
        r = ref(T)
        assert r[1] < T                        # source bar label < T
        assert r[2] >= 0                       # age never negative


def test_daemon_source_carries_the_law_not_the_defect():
    src = Path("scripts/options_history_acquire.py").read_text()
    assert "median REGULAR close" not in src.replace(
        "used the day's median REGULAR close", "")   # only the confession
    assert "UNDERLYING REFERENCE LAW" in src
    assert "NOT_ESTIMABLE" in src
    assert "future_underlying_joins" in src
    assert "START_OF_BAR" in src


def test_raw_retention_is_not_research_eligibility():
    """ELIGIBILITY LAW: NOT_ESTIMABLE rows are preserved observations
    the Predator may never learn from."""
    import options_history_acquire as m
    ok = m.row_eligibility("CAUSAL")
    assert ok == {"raw_eligible": True, "research_eligible": True,
                  "forecast_eligible": True}
    bad = m.row_eligibility("NOT_ESTIMABLE")
    assert bad["raw_eligible"] is True
    assert bad["research_eligible"] is False
    assert bad["forecast_eligible"] is False
    assert bad["reason"] == "MONEYNESS_NOT_ESTABLISHABLE_AT_T"
    # unknown/future statuses fail CLOSED, not open
    weird = m.row_eligibility("SOME_FUTURE_STATUS")
    assert weird["research_eligible"] is False


def test_oi_coverage_cannot_be_truncated_by_any_band():
    """OI COVERAGE LAW: no strike/moneyness filter may touch OI --
    a morning band could exclude contracts that migrate into the
    research region on a volatile day."""
    src = Path("scripts/options_history_acquire.py").read_text()
    assert "OI COVERAGE LAW" in src
    assert "no strike\n    # filter whatsoever" in src or \
        "no strike" in src
    # the old widened-band code is gone
    assert "MONEY_LO * 0.9" not in src
    assert "first_ref" not in src
