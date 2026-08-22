"""option_analytics_live_runtime.py -- pure-logic checks that don't
require live network access or real Alpaca credentials: contract
selection/filtering and the dividend-fact-table lookup law (a real,
provenanced fact table with an honest refusal path, never a guess).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import pandas as pd
import pytest

import option_analytics_live_runtime as rt

T0 = pd.Timestamp("2026-08-18T17:00:00Z")


def test_dividend_schedule_spy_confirmed_none_before_next_ex_div():
    sched, confidence = rt.dividend_schedule_for("SPY", "2026-09-01", known_from=T0)
    assert confidence == "CONFIRMED_NONE"
    assert sched.confirmed_no_dividends is True


def test_dividend_schedule_spy_real_schedule_after_ex_div():
    sched, confidence = rt.dividend_schedule_for("SPY", "2026-09-30", known_from=T0)
    assert confidence == "REAL_SCHEDULE"
    assert sched.events


def test_dividend_schedule_aapl_confirmed_none_within_safe_window():
    sched, confidence = rt.dividend_schedule_for("AAPL", "2026-09-15", known_from=T0)
    assert confidence == "CONFIRMED_NONE"
    assert sched.confirmed_no_dividends is True


def test_dividend_schedule_aapl_refused_beyond_safe_window():
    sched, confidence = rt.dividend_schedule_for("AAPL", "2026-12-01", known_from=T0)
    assert sched is None
    assert confidence == "UNKNOWN"


def test_dividend_schedule_unknown_symbol_refused():
    sched, confidence = rt.dividend_schedule_for("TSLA", "2026-09-01", known_from=T0)
    assert sched is None
    assert confidence == "UNKNOWN"


def test_rate_source_age_grows_with_time():
    age_now = rt.rate_source_age_days(T0)
    age_later = rt.rate_source_age_days(T0 + pd.Timedelta(days=10))
    assert age_later == pytest.approx(age_now + 10, abs=0.01)


def test_rate_curve_is_never_sourced_assumed():
    """rate_curve_now() returns (curve, age_days, source_name). Either it
    reached the live composite source, or it REFUSED with curve=None --
    there is no third outcome, and neither may be sourced "ASSUMED".
    Written to tolerate a network-down test run rather than crashing on
    a None curve."""
    curve, age_days, source_name = rt.rate_curve_now(now=T0)
    assert source_name != "ASSUMED"
    if curve is None:
        assert source_name == rt.RATE_SOURCE_UNAVAILABLE
        assert age_days is None
    else:
        assert curve.source != "ASSUMED"
        assert age_days is not None


def test_select_contracts_filters_missing_quotes():
    snapshots = {
        "AAPL260819C00310000": ({"latestQuote": {"bp": 5.0, "ap": 5.2}}, "1-2"),
        "AAPL260819C00320000": ({"latestQuote": {"bp": None, "ap": None}}, "1-2"),
    }
    selected = rt._select_contracts(snapshots, spot=310.0, now=T0)
    symbols = {s for s, _snap, _b in selected}
    assert "AAPL260819C00310000" in symbols
    assert "AAPL260819C00320000" not in symbols


def test_select_contracts_filters_far_dated():
    snapshots = {
        "AAPL270101C00310000": ({"latestQuote": {"bp": 5.0, "ap": 5.2}}, ">30"),
    }
    selected = rt._select_contracts(snapshots, spot=310.0, now=T0)
    assert selected == []


def test_select_contracts_bounds_strikes_per_expiry():
    snapshots = {}
    for i in range(20):
        strike = 300 + i
        snapshots[f"AAPL260919C{strike*1000:08d}"] = (
            {"latestQuote": {"bp": 5.0, "ap": 5.2}}, "8-30")
    selected = rt._select_contracts(snapshots, spot=310.0, now=T0)
    assert len(selected) <= rt.MAX_STRIKES_PER_EXPIRY


def test_runtime_script_never_imports_production_authority():
    src = Path(rt.__file__).read_text()
    for forbidden in ("apex.hunter", "apex.captain", "apex.execution",
                      "apex.hunter.capital", "apex.frontier2", "apex.frontier"):
        assert f"import {forbidden}" not in src and f"from {forbidden}" not in src, (
            f"{forbidden!r} imported in option_analytics_live_runtime.py")


def test_runtime_script_no_order_placement_keyword():
    src = Path(rt.__file__).read_text().lower()
    for term in ("place_order", "submit_order", "place_option_order"):
        assert term not in src


def test_watchdog_and_certify_scripts_never_import_production_authority():
    scripts_dir = Path(rt.__file__).resolve().parent
    for name in ("option_analytics_live_watchdog.py", "option_analytics_live_certify_v1.py"):
        src = (scripts_dir / name).read_text()
        for forbidden in ("apex.hunter", "apex.captain", "apex.execution",
                          "apex.hunter.capital", "apex.frontier2", "apex.frontier"):
            assert f"import {forbidden}" not in src and f"from {forbidden}" not in src, (
                f"{forbidden!r} imported in {name}")


def test_select_contracts_prefers_near_atm():
    # more strikes than MAX_STRIKES_PER_EXPIRY so the near-ATM
    # truncation actually has something to truncate.
    snapshots = {}
    near_strikes = [300, 302, 304, 306, 308, 310, 312, 314, 316, 318]
    for strike in near_strikes + [200, 400]:
        snapshots[f"AAPL260919C{strike*1000:08d}"] = (
            {"latestQuote": {"bp": 5.0, "ap": 5.2}}, "8-30")
    selected = rt._select_contracts(snapshots, spot=310.0, now=T0)
    selected_symbols = {s for s, _snap, _b in selected}
    assert "AAPL260919C00310000" in selected_symbols
    assert "AAPL260919C00200000" not in selected_symbols
    assert "AAPL260919C00400000" not in selected_symbols


def test_all_four_dte_buckets_are_declared():
    labels = [lbl for lbl, _lo, _hi in rt.DTE_BUCKETS]
    assert labels == ["1-2", "3-7", "8-30", ">30"]
    # windows must be contiguous and non-overlapping
    prev_hi = 0
    for _lbl, lo, hi in rt.DTE_BUCKETS:
        assert lo == prev_hi + 1
        assert hi >= lo
        prev_hi = hi


def test_a_bucket_with_no_liquid_contract_stays_empty():
    """Never force-fill a bucket by stretching a neighbouring expiry
    into it -- a mislabelled contract would corrupt exactly the
    maturity comparison the buckets exist to make."""
    snapshots = {
        "AAPL260919C00310000": ({"latestQuote": {"bp": 5.0, "ap": 5.2}}, "8-30"),
    }
    selected = rt._select_contracts(snapshots, spot=310.0, now=T0)
    buckets_present = {b for _s, _snap, b in selected}
    assert buckets_present <= {"8-30"}
    assert "1-2" not in buckets_present


def test_static_rate_never_reaches_a_live_analytics_state(monkeypatch):
    """A static 4% may never stand in for current rate truth. When every
    live rate leg fails the runtime must REFUSE, not substitute."""
    def boom(**kwargs):
        raise RuntimeError("all rate legs down")
    import apex.intraday.treasury_rate_source as trs
    monkeypatch.setattr(trs, "fetch_composite_curve", boom)
    curve, age, source = rt.rate_curve_now(now=T0)
    assert curve is None, "a live state must not receive a static-rate curve"
    assert source == rt.RATE_SOURCE_UNAVAILABLE
    assert source != rt.STATIC_RATE_SOURCE


def test_no_rate_curve_makes_the_state_refuse_not_guess():
    """curve=None must propagate to a REFUSED analytics state."""
    from apex.option_analytics.canonical_state import build_canonical_state
    from apex.option_analytics.dividends import DividendSchedule
    nodiv = DividendSchedule(events=(), confirmed_no_dividends=True,
                             source="TEST", as_of=str(T0))
    st = build_canonical_state(
        symbol="X", option_type="call", spot=100.0, strike=100.0,
        expiry_date="2026-09-19", bid=8.0, ask=8.2, last_trade=8.1,
        quote_is_current=True, curve=None, dividend_schedule=nodiv,
        known_from=T0, now=T0)
    assert st.state_quality == "REFUSED"
    assert st.refusal_reason == "NO_RATE_CURVE_COVERAGE_FOR_TENOR"


def test_static_rate_constants_are_labeled_non_live():
    assert "TEST" in rt.STATIC_RATE_ALLOWED_USES
    assert "NOT_A_LIVE_FEED" in rt.STATIC_RATE_SOURCE


def test_quote_staleness_is_measured_from_arrival_not_cycle_start():
    """THE 2026-08-19 NEGATIVE-QUOTE-AGE ROOT CAUSE.

    89.4% of that session's option states carried a negative quote_age_s,
    median -6.08s, stable across every hour. Cause: `now` was captured at
    the top of the cycle loop, the bucketed REST fetch then took seconds
    (measured cycle duration 13.5s), and any quote stamped by the
    exchange DURING the fetch was newer than our own baseline.

    The tell was in the same function: underlying_age_s used a fresh
    clock and read a clean -0.077s median while option ages read -6.08s.

    This asserts the fresh arrival clock is captured after the fetch and
    is what reaches the snapshot parser -- while known_from stays the
    cycle clock, because when APEX LEARNED something is a different
    question from how old the quote was.
    """
    import ast
    import inspect
    import textwrap
    src = textwrap.dedent(inspect.getsource(rt.process_symbol))
    tree = ast.parse(src)

    assigns = [n for n in ast.walk(tree)
               if isinstance(n, ast.Assign)
               and any(getattr(t, "id", None) == "quotes_observed_at"
                       for t in n.targets)]
    assert assigns, "quotes_observed_at is gone -- the stale baseline is back"

    for node in ast.walk(tree):
        if (isinstance(node, ast.Call)
                and getattr(node.func, "id", None) == "from_alpaca_snapshot"):
            kw = {k.arg: k.value for k in node.keywords}
            assert getattr(kw.get("now"), "id", None) == "quotes_observed_at", (
                "snapshot staleness is being measured against the cycle-start "
                "clock again")
            assert getattr(kw.get("known_from"), "id", None) == "now", (
                "known_from must stay the cycle clock")
            break
    else:
        raise AssertionError("from_alpaca_snapshot call not found")


def test_fetch_precedes_the_observation_clock():
    """Order matters: capturing the arrival clock BEFORE the fetch would
    reproduce the original bug exactly."""
    import inspect
    src = inspect.getsource(rt.process_symbol)
    assert src.index("fetch_bucketed_snapshots") < src.index("quotes_observed_at")
