"""TRADE_WORKING_SET_V1 -- the tests that make the bound real.

The equity fabric was OOM-killed three times on 2026-09-02 by state that
was nominally bounded (deque maxlen=2,000,000/symbol) and bounded only by
amnesia (dedup set cleared wholesale at 500,000). These tests exist so
that neither kind of fake bound can come back:

  * the retention contract is the CONSUMER's contract (800 populated
    buckets), proven against the untouched reference builder
  * every bound is asserted, including the ones that are supposed to be
    unreachable
  * canonical session history is proven to survive working-state eviction
"""
import random

import pytest

from apex.intraday.bar_builder import build_1m_bars
from apex.intraday.trade_working_set import (BUCKET_S,
                                             FabricStateBoundViolation,
                                             RETAINED_BUCKETS,
                                             TradeWorkingSet, to_ns)

TRANSPORT = "ALPACA_WEBSOCKET_SIP_V1"
BASE = 1756800000 - (1756800000 % 60)


def _ts(off):
    import pandas as pd
    return pd.Timestamp(BASE + off, unit="s", tz="UTC")


def _ref(trades, outages=(), *, now, minutes=800, sym="X"):
    import json
    df = build_1m_bars(
        [{"event_s": t[0], "price": t[1], "size": t[2],
          "conditions": (t[3] if len(t) > 3 else None)} for t in trades],
        list(outages), now=now, symbol=sym, transport=TRANSPORT,
        minutes=minutes)
    if not len(df):
        return []
    return json.loads(df.to_json(orient="records", date_format="iso"))


def _new(trades, outages=(), *, now, minutes=800, sym="X", **kw):
    import json
    kw.setdefault("lateness_buckets", 10_000)   # equivalence: never refuse
    w = TradeWorkingSet([sym], **kw)
    for t in trades:
        w.admit(sym, event_s=t[0], price=t[1], size=t[2],
                conditions=(t[3] if len(t) > 3 else None))
    df = w.bars(sym, list(outages), now=now, transport=TRANSPORT,
                minutes=minutes)
    if not len(df):
        return [], w
    return json.loads(df.to_json(orient="records", date_format="iso")), w


def _equiv(trades, outages=(), *, now, minutes=800, **kw):
    ref = _ref(trades, outages, now=now, minutes=minutes)
    new, w = _new(trades, outages, now=now, minutes=minutes, **kw)
    assert ref == new, "bar output diverged from the reference builder"
    return ref, w


# ---------------------------------------------------- the 800-bar contract
def test_exactly_800_populated_buckets():
    tr = [(BASE + m * 60 + 5, 100.0 + m, 10) for m in range(800)]
    ref, _ = _equiv(tr, now=_ts(800 * 60))
    assert len(ref) == 800


def test_801_populated_buckets_drops_the_oldest():
    tr = [(BASE + m * 60 + 5, 100.0 + m, 10) for m in range(801)]
    ref, _ = _equiv(tr, now=_ts(801 * 60))
    assert len(ref) == 800
    # the FIRST minute must be the one that fell off
    assert ref[0]["open"] == 101.0


def test_800_buckets_spanning_far_more_than_800_wall_minutes():
    """.tail(800) counts BARS, not MINUTES. A thin symbol's 800
    populated buckets can span days -- a naive 800-MINUTE cutoff would
    silently truncate its history."""
    tr, minute = [], 0
    for m in range(800):
        minute += 5                       # one print every 5 minutes
        tr.append((BASE + minute * 60 + 1, 10.0 + m, 3))
    span_min = minute
    assert span_min > 3000
    ref, _ = _equiv(tr, now=_ts((minute + 1) * 60))
    assert len(ref) == 800


def test_many_trades_in_the_same_minute():
    tr = [(BASE + 10 + i * 1e-5, 100.0 + i * 0.01, 5) for i in range(4000)]
    ref, _ = _equiv(tr, now=_ts(300))
    assert len(ref) == 1 and ref[0]["trades"] == 4000


def test_identical_timestamps_keep_arrival_order():
    tr = [(BASE + 30, 100.0, 1), (BASE + 30, 200.0, 1),
          (BASE + 30, 300.0, 1), (BASE + 45, 150.0, 1)]
    ref, _ = _equiv(tr, now=_ts(300))
    assert ref[0]["open"] == 100.0 and ref[0]["close"] == 150.0


def test_quiet_symbol_is_not_truncated():
    tr = [(BASE + 137 * 60 + 12.5, 42.0, 3),
          (BASE + 400 * 60 + 44.0, 43.0, 1)]
    ref, _ = _equiv(tr, now=_ts(500 * 60))
    assert len(ref) == 2


def test_high_volume_symbol():
    rnd = random.Random(1)
    tr = []
    for m in range(120):
        for _ in range(600):
            tr.append((BASE + m * 60 + rnd.uniform(0, 59.99),
                       100 + rnd.random(), rnd.randint(1, 900)))
    tr.sort(key=lambda t: t[0])
    ref, _ = _equiv(tr, now=_ts(121 * 60))
    assert len(ref) == 120


# ------------------------------------------------------ coverage semantics
def test_outage_reclassifies_finalized_bars():
    """A new outage legitimately reclassifies minutes already finalized;
    a coverage cache that ignored the outage list would freeze the old
    answer."""
    tr = [(BASE + m * 60 + k * 10, 100.0 + m, 5)
          for m in range(10) for k in range(6)]
    now = _ts(700)
    _, w = _equiv(tr, now=now)
    clean = w.bars("X", [], now=now, transport=TRANSPORT)
    dirty = w.bars("X", [(BASE + 180, BASE + 260)], now=now,
                   transport=TRANSPORT)
    assert (clean["coverage_status"] != dirty["coverage_status"]).any()
    assert _ref(tr, [(BASE + 180, BASE + 260)], now=now) == \
        __import__("json").loads(
            dirty.to_json(orient="records", date_format="iso"))


def test_incomplete_and_gap_classifications():
    for tr in ([(BASE + 20, 100.0, 1), (BASE + 30, 101.0, 1)],
               [(BASE + 40, 100.0, 1), (BASE + 41, 100.0, 1),
                (BASE + 42, 100.0, 1)],
               [(BASE + 1, 100.0, 1), (BASE + 2, 100.0, 1),
                (BASE + 3, 100.0, 1), (BASE + 55, 101.0, 1)]):
        _equiv(tr, now=_ts(300))


def test_high_low_ineligible_conditions():
    tr = [(BASE + 5, 100.0, 1, ["@"]), (BASE + 15, 736.49, 1, ["I"]),
          (BASE + 25, 101.0, 1, None), (BASE + 35, 99.0, 1, ["Z"]),
          (BASE + 45, 100.5, 1, ["@"])]
    ref, _ = _equiv(tr, now=_ts(300))
    # BOTH the "I" print (736.49) and the "Z" print (99.0) are in the
    # published CTA/UTP exclusion set, so high/low come only from the
    # regular-way prints -- while volume and trade count keep all five.
    assert ref[0]["high"] == 101.0
    assert ref[0]["low"] == 100.0
    assert ref[0]["trades"] == 5
    assert ref[0]["close"] == 100.5


def test_all_prints_ineligible_falls_back():
    tr = [(BASE + 10 + i, 100.0 + i, 5, ["C"]) for i in range(5)]
    ref, _ = _equiv(tr, now=_ts(300))
    assert ref[0]["high"] == 104.0 and ref[0]["low"] == 100.0


def test_forming_minute_never_emitted():
    tr = [(BASE + m * 60 + 10, 100.0 + m, 4) for m in range(20)]
    ref, _ = _equiv(tr, now=_ts(19 * 60 + 33))
    assert len(ref) == 19


# ------------------------------------------------------------ ONE CLOCK
def test_bucket_assignment_matches_pandas_exactly():
    import pandas as pd
    rnd = random.Random(9)
    for _ in range(20000):
        ev = BASE + rnd.uniform(0, 86400)
        mine = (to_ns(ev) // (BUCKET_S * 1_000_000_000)) * BUCKET_S
        theirs = int(pd.Timestamp(ev, unit="s", tz="UTC")
                     .floor("1min").timestamp())
        assert mine == theirs


def test_future_event_time_is_the_callers_gate_not_a_crash():
    w = TradeWorkingSet(["X"])
    assert w.admit("X", event_s=BASE + 10**9, price=1.0, size=1) == "ACCEPTED"
    w.assert_bounded()


def test_clock_regression_does_not_move_the_watermark_backwards():
    w = TradeWorkingSet(["X"], lateness_buckets=1)
    w.admit("X", event_s=BASE + 600, price=1.0, size=1)
    st = w._st["X"]
    assert st.watermark == BASE + 600
    w.admit("X", event_s=BASE + 60, price=1.0, size=1)     # far in the past
    assert st.watermark == BASE + 600, "watermark must never regress"
    assert w.counters["late_after_finalize"] == 1
    w.assert_bounded()


def test_unknown_symbol_is_refused_not_created():
    w = TradeWorkingSet(["X"])
    assert w.admit("ZZZZ", event_s=BASE, price=1.0, size=1) == "UNKNOWN_SYMBOL"
    assert "ZZZZ" not in w._st


# --------------------------------------------------------- late arrivals
def test_late_trade_inside_tolerance_is_folded_in():
    w = TradeWorkingSet(["X"], lateness_buckets=2)
    for m in range(3):
        w.admit("X", event_s=BASE + m * 60 + 10, price=100.0, size=1)
    # a trade for minute 0 arriving while the watermark is at minute 2
    assert w.admit("X", event_s=BASE + 5, price=1.0, size=1) == "ACCEPTED"
    df = w.bars("X", [], now=_ts(600), transport=TRANSPORT)
    assert float(df.iloc[0]["open"]) == 1.0       # it became the open


def test_late_trade_beyond_tolerance_is_refused_and_counted():
    w = TradeWorkingSet(["X"], lateness_buckets=1)
    for m in range(6):
        w.admit("X", event_s=BASE + m * 60 + 10, price=100.0, size=1)
    assert w.admit("X", event_s=BASE + 5, price=1.0, size=1) == \
        "LATE_AFTER_FINALIZE"
    assert w.counters["late_after_finalize"] == 1
    df = w.bars("X", [], now=_ts(600), transport=TRANSPORT)
    assert float(df.iloc[0]["open"]) == 100.0     # bar NOT retroactively hit


# ---------------------------------------------------------------- dedup
def test_duplicate_inside_horizon_is_suppressed():
    w = TradeWorkingSet(["X"], lateness_buckets=2)
    k = ("t1", 100.0, 5, "id1")
    assert w.admit("X", event_s=BASE + 10, price=100.0, size=5, key=k) == \
        "ACCEPTED"
    assert w.admit("X", event_s=BASE + 10, price=100.0, size=5, key=k) == \
        "DUPLICATE"
    assert w.counters["duplicates"] == 1


def test_dedup_keys_expire_with_their_window_not_by_clearing():
    """The old fabric did `if len(seen) > 500_000: seen.clear()` -- a
    single event that made it blind to every duplicate it knew. Keys
    must expire with the window instead."""
    w = TradeWorkingSet(["X"], lateness_buckets=1)
    for m in range(50):
        w.admit("X", event_s=BASE + m * 60 + 1, price=1.0, size=1,
                key=("k", m))
    st = w._st["X"]
    assert len(st.dedup_set) <= 3, "dedup state is not expiring"
    assert len(st.dedup_set) == len(st.dedup_order)
    assert w.counters["dedup_keys_evicted"] > 0
    w.assert_bounded()


def test_duplicate_after_expiry_cannot_corrupt_a_finalized_bar():
    """§9: a duplicate arriving after its key has legitimately expired
    is NOT silently applied. Its bucket is already finalized, so it is
    refused by the lateness contract and counted."""
    w = TradeWorkingSet(["X"], lateness_buckets=1)
    k = ("dup", 1)
    w.admit("X", event_s=BASE + 10, price=100.0, size=5, key=k)
    for m in range(1, 8):
        w.admit("X", event_s=BASE + m * 60 + 1, price=50.0, size=1,
                key=("k", m))
    assert k not in w._st["X"].dedup_set          # expired
    assert w.admit("X", event_s=BASE + 10, price=100.0, size=5, key=k) == \
        "LATE_AFTER_FINALIZE"
    df = w.bars("X", [], now=_ts(900), transport=TRANSPORT)
    assert int(df.iloc[0]["trades"]) == 1, "the expired duplicate was applied"


# ------------------------------------------------------ BOUND A / B / C
def test_bound_a_working_state_plateaus_while_buckets_advance():
    w = TradeWorkingSet(["X"], retained_buckets=100, lateness_buckets=2)
    seen = []
    for m in range(600):
        for k in range(50):
            w.admit("X", event_s=BASE + m * 60 + k, price=1.0, size=1,
                    key=(m, k))
        if m % 50 == 49:
            s = w.stats()
            seen.append((s["raw_trades_retained"], s["bars_retained"],
                         s["dedup_keys_retained"]))
            w.assert_bounded()
    raw = [x[0] for x in seen]
    bars = [x[1] for x in seen]
    assert max(raw) <= 3 * 50, "raw trades did not plateau: %s" % raw
    assert max(bars) <= 100, "finalized bars exceeded the cap: %s" % bars
    assert raw[-1] == raw[-2] == raw[-3], "raw state still growing"


def test_bound_b_per_symbol_ceiling_forces_closure_and_records_it():
    w = TradeWorkingSet(["X"], max_open_per_symbol=500,
                        lateness_buckets=10_000)
    for i in range(2000):
        w.admit("X", event_s=BASE + 1 + i * 1e-4, price=1.0, size=1)
    assert w.counters["bound_violations"] > 0
    assert w.counters["forced_finalize"] > 0
    s = w.stats()
    assert s["raw_trades_retained"] <= 500 + 1


def test_bound_b_dedup_ceiling_evicts_oldest_not_everything():
    w = TradeWorkingSet(["X"], max_dedup_per_symbol=100,
                        lateness_buckets=10_000)
    for i in range(500):
        w.admit("X", event_s=BASE + 1 + i * 1e-4, price=1.0, size=1,
                key=("k", i))
    st = w._st["X"]
    assert len(st.dedup_set) <= 101
    assert len(st.dedup_set) == len(st.dedup_order)
    assert ("k", 499) in st.dedup_set, "newest key was evicted, not oldest"


def test_bound_c_detects_a_stopped_prune_clock():
    """The PULSE_V1 failure, transplanted: if the finalize horizon stops
    advancing while observations keep arriving, the assertion must fire
    rather than let state grow."""
    w = TradeWorkingSet(["X"], lateness_buckets=1)
    for m in range(5):
        w.admit("X", event_s=BASE + m * 60 + 1, price=1.0, size=1)
    w.assert_bounded()
    st = w._st["X"]
    st.watermark = BASE + 100 * 60          # horizon jumps; prune did not run
    with pytest.raises(FabricStateBoundViolation, match="pruning has stopped"):
        w.assert_bounded()


def test_bound_c_detects_dedup_set_queue_divergence():
    w = TradeWorkingSet(["X"])
    w.admit("X", event_s=BASE + 1, price=1.0, size=1, key=("a",))
    w._st["X"].dedup_set.add(("ghost",))
    with pytest.raises(FabricStateBoundViolation, match="diverged"):
        w.assert_bounded()


def test_bound_c_detects_too_many_open_buckets():
    from apex.intraday.trade_working_set import _Bucket
    w = TradeWorkingSet(["X"], lateness_buckets=1)
    w.admit("X", event_s=BASE + 1, price=1.0, size=1)
    st = w._st["X"]
    for m in range(5):
        st.open[BASE + (m + 1) * 60] = _Bucket(BASE + (m + 1) * 60)
    with pytest.raises(FabricStateBoundViolation):
        w.assert_bounded()


def test_construction_rejects_nonsense_bounds():
    with pytest.raises(ValueError):
        TradeWorkingSet(["X"], retained_buckets=0)
    with pytest.raises(ValueError):
        TradeWorkingSet(["X"], lateness_buckets=-1)


def test_default_retention_is_the_consumers_contract():
    """RETAINED_BUCKETS is not a tuning knob -- it is bars_1m()'s own
    SESSION_BAR_WINDOW_MIN. If one moves, the other must."""
    from apex.intraday.alpaca_fabric import AlpacaRealtimeFabric
    assert RETAINED_BUCKETS == AlpacaRealtimeFabric.SESSION_BAR_WINDOW_MIN


# -------------------------------------------------------- P0-2 protection
def test_evicting_working_state_never_touches_canonical_history(tmp_path):
    """P0-2: the in-memory ring is WORKING STORAGE; the session file is
    the durable record. Eviction must not be able to shorten it."""
    import json
    from scripts.alpaca_fabric_daemon import persist_bars

    class _Fab:
        symbols = ["X"]

        def __init__(self, w):
            self._w = w

        def bars_1m(self, sym, minutes=800):
            return self._w.bars(sym, [], now=self._now,
                                transport=TRANSPORT, minutes=minutes)

    import scripts.alpaca_fabric_daemon as dmn
    orig = dmn.BARS_DIR
    dmn.BARS_DIR = tmp_path
    try:
        w = TradeWorkingSet(["X"], retained_buckets=5, lateness_buckets=1)
        fab = _Fab(w)
        for m in range(40):
            w.admit("X", event_s=BASE + m * 60 + 5, price=100.0 + m, size=1)
            w.admit("X", event_s=BASE + m * 60 + 25, price=101.0 + m, size=1)
            w.admit("X", event_s=BASE + m * 60 + 45, price=102.0 + m, size=1)
            fab._now = _ts((m + 1) * 60 + 1)
            persist_bars(fab, "2026-09-02")
        disk = json.loads((tmp_path / "X_2026-09-02.json").read_text())
        assert w.stats()["bars_retained"] <= 5, "working state not bounded"
        assert len(disk["bars"]) >= 38, (
            "canonical history was truncated by working-state eviction: "
            "only %d bars survived" % len(disk["bars"]))
        opens = [b["open"] for b in disk["bars"]]
        assert opens == sorted(opens), "session file lost ordering"
        assert opens[0] == 100.0, "the FIRST minute of the session is gone"
    finally:
        dmn.BARS_DIR = orig


# ------------------------------------------------------ reference parity
def test_randomised_equivalence_against_the_reference_builder():
    rnd = random.Random(20260903)
    for _ in range(25):
        n_min = rnd.randint(10, 90)
        tr = []
        for m in range(n_min):
            if rnd.random() < 0.2:
                continue
            for _ in range(rnd.randint(1, 25)):
                tr.append((BASE + m * 60 + rnd.uniform(0, 59.9999),
                           round(50 + rnd.random() * 100, 4),
                           rnd.randint(1, 5000),
                           rnd.choice([None, ["@"], ["C"], ["I"], ["Z"]])))
        if not tr:
            continue
        tr.sort(key=lambda t: t[0])
        outs = ([(BASE + rnd.uniform(0, n_min * 60), BASE +
                  rnd.uniform(0, n_min * 60))] if rnd.random() < 0.3 else [])
        outs = [(min(a, b), max(a, b)) for a, b in outs]
        _equiv(tr, outs, now=_ts((n_min + 1) * 60),
               minutes=rnd.choice([50, 200, 800]))


def test_stats_shape_is_operational_not_a_ledger():
    w = TradeWorkingSet(["X", "Y"])
    w.admit("X", event_s=BASE + 1, price=1.0, size=1)
    s = w.stats()
    for k in ("raw_trades_retained", "dedup_keys_retained", "bars_retained",
              "oldest_retained_bucket_s", "newest_retained_bucket_s",
              "bound_b_ceilings", "counters"):
        assert k in s
    assert s["state_model"] == "TRADE_WORKING_SET_V1"


# ================================================================== the
# EXACT SCOPE OF THE EQUIVALENCE GUARANTEE
#
# build_1m_bars does f.set_index("ts").sort_index(). pandas SKIPS that
# sort when the index is already monotonic, so tied timestamps keep
# arrival order -- which is what this implementation reproduces. When
# arrival is NOT event-time monotonic, numpy's introsort actually runs
# and permutes ties arbitrarily, and that permutation is a function of
# the WHOLE array, so it cannot be reproduced from one bucket's trades.
#
# The condition is therefore exactly the one the fabric already measures:
# counters["out_of_order"], which read 0 over 731,990 trades on
# 2026-09-02.
# =====================================================================

def test_equivalence_holds_under_dense_tied_timestamps_when_monotonic():
    """40 trials / 2,319,500 trades / 40,064 tied-nanosecond pairs were
    byte-identical offline. This is the in-suite version."""
    import pandas as pd
    rnd = random.Random(31337)
    for _ in range(3):
        tr = []
        for m in range(25):
            for _ in range(400):
                # ms-rounded offsets in a dense minute => many exact ties
                tr.append((BASE + m * 60 + round(rnd.uniform(0, 59), 3),
                           round(50 + rnd.random() * 900, 4),
                           float(rnd.choice([1, 100, 5000])),
                           rnd.choice([None, ["@"], ["C"], ["Z"]])))
        tr.sort(key=lambda t: t[0])                 # MONOTONIC arrival
        ns = [pd.Timestamp(t[0], unit="s").value for t in tr]
        assert len(ns) != len(set(ns)), "this test needs tied timestamps"
        _equiv(tr, now=_ts(26 * 60))


def test_tied_timestamps_resolve_to_arrival_order_deterministically():
    """The DECLARED difference. Under non-monotonic arrival the
    reference's answer here is an artifact of an unstable sort and
    varies with unrelated trades in the same array; this implementation
    always answers in arrival order. Pinned so it stays deliberate."""
    w = TradeWorkingSet(["X"], lateness_buckets=10)
    # identical event time, arriving out of event order overall
    w.admit("X", event_s=BASE + 120 + 0.5, price=10.0, size=1.0)
    w.admit("X", event_s=BASE + 0.25, price=111.0, size=1.0)
    w.admit("X", event_s=BASE + 0.25, price=222.0, size=1.0)
    df = w.bars("X", [], now=_ts(600), transport=TRANSPORT)
    row = df.iloc[0]
    assert float(row["open"]) == 111.0, "tie must resolve to arrival order"
    assert float(row["close"]) == 222.0
    assert int(row["trades"]) == 2


def test_out_of_order_counter_is_the_guarantees_own_tripwire():
    """The equivalence guarantee is conditional on monotonic arrival, so
    the condition must be OBSERVABLE at runtime, not assumed."""
    w = TradeWorkingSet(["X"], lateness_buckets=10)
    w.admit("X", event_s=BASE + 30, price=1.0, size=1.0)
    assert w.counters["out_of_order_within_window"] == 0
    w.admit("X", event_s=BASE + 10, price=1.0, size=1.0)
    assert w.counters["out_of_order_within_window"] == 1


def test_volume_dtype_matches_the_reference_for_integer_sizes():
    """A caller passing int sizes must still serialise volume the way
    the reference does -- coercing to float here changed 5101 to
    5101.0 in the canonical file."""
    tr = [(BASE + 10, 100.0, 1), (BASE + 20, 101.0, 100),
          (BASE + 30, 102.0, 5000)]
    _equiv(tr, now=_ts(300))


def test_fabric_ingest_path_is_bounded_end_to_end():
    """Through the REAL _apply_trade, including its provider-string
    timestamp parsing and future gate -- the offline scale run ingested
    5.1M trades this way with a flat retained set."""
    import pandas as pd
    import apex.intraday.alpaca_fabric as af
    fab = af.AlpacaRealtimeFabric(["SPY", "QQQ"])
    base = BASE
    rnd = random.Random(5)
    for m in range(300):
        minute_iso = pd.Timestamp(base + m * 60, unit="s",
                                  tz="UTC").strftime("%Y-%m-%dT%H:%M:")
        for sym in ("SPY", "QQQ"):
            for off in sorted(rnd.uniform(0, 59.99) for _ in range(40)):
                fab._apply_trade(
                    {"S": sym, "p": 100.0 + rnd.random(), "s": 100.0,
                     "t": minute_iso + "%09.6fZ" % off,
                     "i": "%d-%s-%f" % (m, sym, off), "c": ["@"]},
                    base + m * 60 + off + 0.05)
    assert fab.counters["future_rejected"] == 0, "the workload was rejected"
    assert fab.counters["trades"] == 300 * 2 * 40
    st = fab.state_stats()
    # 3 open buckets max per symbol, 40 trades each
    assert st["raw_trades_retained"] <= 2 * 3 * 40
    assert st["bars_retained"] <= 2 * 800
    assert st["dedup_keys_retained"] <= 2 * 3 * 40
    fab.working.assert_bounded()
    h = fab.health()
    assert h["health_axes"]["state_bound_ok"] is True
    assert h["working_state"]["state_model"] == "TRADE_WORKING_SET_V1"


def test_health_degrades_and_reports_when_a_bound_is_violated():
    """BOUND C must be visible in the artifact an operator reads."""
    import apex.intraday.alpaca_fabric as af
    fab = af.AlpacaRealtimeFabric(["SPY"])
    fab.working.admit("SPY", event_s=BASE + 1, price=1.0, size=1.0,
                      key=("a",))
    fab.working._st["SPY"].dedup_set.add(("ghost",))
    h = fab.health()
    assert h["health_axes"]["state_bound_ok"] is False
    assert "diverged" in (h["state_bound_error"] or "")


def test_provider_interface_still_reports_known_from_and_latency():
    """provider_interface used to read trades[sym][-1]; that tape is
    gone, so the fabric must still answer for the LAST trade."""
    import apex.intraday.alpaca_fabric as af
    from apex.intraday.provider_interface import AlpacaBroadProvider
    fab = af.AlpacaRealtimeFabric(["SPY"])
    prov = AlpacaBroadProvider(fab)
    assert prov.get_known_from("SPY") is None
    assert prov.get_latency("SPY") is None
    fab._apply_trade({"S": "SPY", "p": 100.0, "s": 1.0,
                      "t": "2026-09-02T13:30:00.000000000Z", "i": "1",
                      "c": ["@"]},
                     __import__("pandas").Timestamp(
                         "2026-09-02T13:30:00.250Z").timestamp())
    assert prov.get_known_from("SPY") is not None
    assert prov.get_latency("SPY") == 0.25
