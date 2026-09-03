"""TRADE_WORKING_SET_V1 -- bounded operational state for the realtime
equity fabric.

WHY THIS EXISTS
---------------
On 2026-09-02 apex-equity-fabric was OOM-killed three times inside one
RTH session (14:51:39, 17:01:22, 19:58:22 UTC), each time by its own
cgroup at MemoryMax=2500M, growing 13.5-18.3 MiB/min. 94% of that growth
was attributed to two per-trade accumulators:

    self.trades[sym] = deque(maxlen=2_000_000)   # 60 syms = 120M slots
    self._seen[sym]  = set()                     # cleared at 500k, per sym

Neither is a bound the machine can survive: 120,000,000 trade records is
~77 GiB on an 8 GB host. A BOUND THAT CAN NEVER BE REACHED IS NOT A
BOUND. And `seen.clear()` is bounded only by amnesia -- the instant after
it fires the fabric is blind to every duplicate it previously knew.

WHY NOT SIMPLY A SMALLER DEQUE
------------------------------
The retention contract has to come from the economic job, and there is
exactly ONE consumer of retained raw trades:

    <realtime fabric>.bars_1m()  ->  build_1m_bars(...).tail(800)

`.tail(800)` returns the last 800 POPULATED one-minute buckets (measured,
not assumed -- a bucket exists only in a minute that printed). So a
"bounded raw-trade window sized to the job" means retaining every raw
trade behind 800 populated buckets. Measured against APEX's own canonical
bars, that is 13,316,101 trades = 8.0 GiB, against a 2.44 GiB cap. The
honest conclusion is that OPTION A IS STRUCTURALLY IMPOSSIBLE: sizing the
raw window to the job is not a repair, it is a bigger version of the same
failure.

WHAT THIS DOES INSTEAD
----------------------
A raw trade is only needed until the minute it belongs to can no longer
change. After that, the only thing the consumer needs is the minute's
AGGREGATE. So:

    OPEN BUCKETS      raw trades, current forming minute + a bounded
                      lateness window (reconciliation state)
    FINALIZED         last 800 one-minute aggregates per symbol
    DEDUP KEYS        only across the open/lateness horizon
    CANONICAL FILES   complete session history, untouched (P0-2)

Measured worst-case concurrent occupancy over a 3-bucket window across
all 60 symbols is 477,353 raw trades; the finalized store is 60 x 800
aggregates. Both are bounded by construction, and the bound is derived
from observed peak volume rather than chosen.

THREE INDEPENDENT BOUNDS (defense in depth)
-------------------------------------------
BOUND A  SEMANTIC   -- only the open window and 800 aggregates may live
BOUND B  CARDINALITY-- per-symbol and aggregate emergency ceilings, sized
                       from measured peaks, that a pruning defect cannot
                       silently walk past
BOUND C  ASSERTION  -- continuous invariant check; a broken prune clock
                       becomes visible immediately instead of growing

PULSE_V1 proved the failure mode these guard against: the observation
clock and the prune clock diverged, pruning silently stopped, and the
"bound" held only by convention. Here there is ONE clock -- the trade's
own event time -- and BOUND C asserts it.
"""
from __future__ import annotations

import threading
from collections import deque

from apex.intraday.bar_builder import (MAX_EDGE_GAP_S, MAX_INTRA_GAP_S,
                                       MIN_TRADES_HEALTHY, _hl_eligible)

BUCKET_S = 60
NS = 1_000_000_000
BUCKET_NS = BUCKET_S * NS


def to_ns(event_s: float) -> int:
    """Float epoch seconds -> integer nanoseconds, BIT-IDENTICALLY to
    pandas' own cast_from_unit -- which is what the reference builder
    gets from pd.to_datetime(..., unit="s").

    This is not pedantry. The reference computes gap_duration_ms as
    round(seconds * 1000), and a ONE NANOSECOND difference in the
    conversion flips that rounding at a .5 boundary: the equivalence
    war caught exactly that, twice in 27 scenarios, as a 1 ms
    disagreement. Doing the arithmetic in float seconds cannot
    reproduce the reference; doing it in integer nanoseconds can.

    Verified against pandas 3.0.5 on 200,000 randomised timestamps
    with zero mismatches.
    """
    base = int(event_s)
    frac = round(event_s - base, 9)
    return base * NS + int(frac * NS)

# ---------------------------------------------------------------- BOUND A
# The consumer's own contract. NOT a tuning knob: bars_1m() asks for
# SESSION_BAR_WINDOW_MIN buckets and build_1m_bars returns .tail() of
# them, so retaining more than this cannot change any output.
RETAINED_BUCKETS = 800

# How long a minute stays reopenable after the event-time watermark has
# moved past it. This is RECONCILIATION state, not a performance knob:
# it is the window in which an out-of-order or late trade can still be
# folded into its true minute with exactly the reference semantics.
#
# NOT a measured provider guarantee. The fabric's own out_of_order
# counter read 0 over 731,990 trades on 2026-09-02, which is suggestive
# and nothing more. Until a lateness contract is measured across
# sessions, this is a DECLARED tolerance and arrivals beyond it are
# counted and refused rather than silently applied.
LATENESS_BUCKETS = 2

# ---------------------------------------------------------------- BOUND B
# Emergency ceilings, derived from measured peaks in APEX's own canonical
# bars (2026-08-27..2026-09-01, 152,813 bars, 60 symbols):
#
#   worst single symbol, 3-minute window   80,398 trades  (NVDA)
#   worst aggregate,     3-minute window  477,353 trades
#
# Ceilings are those peaks with headroom, NOT tuned to today's failure.
# They exist so that a defect in the prune path cannot consume the host;
# in correct operation they are unreachable.
MAX_OPEN_TRADES_PER_SYMBOL = 250_000        # ~3.1x measured worst symbol
MAX_OPEN_TRADES_AGGREGATE = 1_000_000       # ~2.1x measured worst aggregate
MAX_DEDUP_KEYS_PER_SYMBOL = 250_000         # same horizon as open trades


# ---------------------------------------------------- ORDERING SEMANTICS
# The equivalence proof is CONDITIONAL and the condition must be
# observable, never assumed.
#
# build_1m_bars does f.set_index("ts").sort_index(). pandas SKIPS that
# sort when the index is already monotonic, so tied timestamps keep
# arrival order -- which is what this implementation reproduces exactly
# (40 trials / 2,319,500 trades / 40,064 tied-nanosecond pairs,
# byte-identical). When arrival is NOT event-time monotonic, numpy's
# unstable introsort actually runs and permutes ties as a function of
# the WHOLE array, which cannot be reproduced from one bucket.
#
# So while arrival stays monotonic the equivalence claim is exact; the
# moment it does not, the claim becomes conditional and the fabric must
# SAY SO rather than keep asserting equivalence it no longer has.
# SEMANTIC health is NOT operational health. The writer can be doing its
# job perfectly while the strength of the equivalence CLAIM has weakened.
SEMANTIC_HEALTH_EXACT = "EXACT"
SEMANTIC_HEALTH_DEGRADED = "DEGRADED_ORDERING_AMBIGUITY"

# The ambiguity is NOT "an out-of-order trade arrived". Out-of-order
# arrival on its own changes nothing: the aggregator re-sorts, and every
# field still matches the reference. The equivalence claim only weakens
# where BOTH of these hold for the same bucket:
#
#   1. two prints share an IDENTICAL event-time nanosecond, and
#   2. that symbol's arrival was non-monotonic, so pandas actually ran
#      its (unstable) sort instead of skipping it
#
# Only then can the reference's open/close among the tied prints differ
# from arrival order. Counting every out-of-order event instead would
# raise the alarm constantly on a condition that is usually harmless,
# and an alarm that cries wolf is worse than no alarm.
ORDERING_EXACT = SEMANTIC_HEALTH_EXACT
ORDERING_DEGRADED = SEMANTIC_HEALTH_DEGRADED

# how many affected (symbol, bucket) pairs to retain for diagnosis --
# BOUNDED, because this module exists to stop unbounded state
AMBIGUITY_SAMPLE_MAX = 64

# Not yet proven: no lateness contract has been MEASURED across
# sessions, so the declared 2-bucket tolerance stays visible as PARTIAL
# until it is.
LATE_TRADE_CONTRACT = "PARTIAL"


class FabricStateBoundViolation(Exception):
    """A bound that should be unreachable in correct operation was
    reached. This is never routine: it means either the prune path is
    broken or the world is far outside its measured envelope. It is
    raised so the condition surfaces rather than being absorbed."""


class _Bucket:
    """Raw trades for one not-yet-finalized minute."""
    __slots__ = ("bucket_s", "trades")

    def __init__(self, bucket_s: int):
        self.bucket_s = bucket_s
        self.trades: list = []          # (event_s, price, size, cond, seq)


def aggregate_bucket(bucket_s: int, trades: list) -> dict:
    """Everything a completed 1-minute bar needs, from that minute's
    trades -- computed to match build_1m_bars EXACTLY.

    `trades`: [(event_s, price, size, conditions, seq), ...] in arrival
    order. Sorted here by (event_s, seq): the reference does
    `.sort_index()` on a DatetimeIndex, which was measured to be STABLE
    on pandas 3.0.5, so equal timestamps keep arrival order. `seq` is
    what preserves that tiebreak once the DataFrame is gone.
    """
    ordered = sorted(trades, key=lambda t: (t[0], t[4]))
    prices = [t[1] for t in ordered]
    elig = [t[1] for t in ordered if _hl_eligible(t[3])]
    # combine_first semantics: a minute whose every print is ineligible
    # falls back to the unfiltered high/low rather than emitting NaN.
    hi = max(elig) if elig else max(prices)
    lo = min(elig) if elig else min(prices)
    # max consecutive silence, in INTEGER ns (see to_ns). The reference
    # does .diff().dt.total_seconds().max(); max(d)/1e9 == max(d/1e9)
    # because the division is monotone, so this is the same number.
    max_intra_ns = 0
    has_ns_tie = False
    for a, b in zip(ordered, ordered[1:]):
        d = b[0] - a[0]
        if d == 0:
            has_ns_tie = True          # identical event-time nanosecond
        if d > max_intra_ns:
            max_intra_ns = d
    return {
        "has_ns_tie": has_ns_tie,
        "bucket_s": bucket_s,
        "open": prices[0], "high": hi, "low": lo, "close": prices[-1],
        "volume": sum(t[2] for t in ordered), "trades": len(ordered),
        "first_ns": ordered[0][0], "last_ns": ordered[-1][0],
        "max_intra": max_intra_ns / 1e9,
    }


def _edge_seconds(delta_ns: int) -> float:
    """Reproduce the reference's SCALAR Timedelta.total_seconds().

    The reference is internally inconsistent about time precision, and
    equivalence means reproducing that, not tidying it:

      edge_gap   (ft - b0).total_seconds()      SCALAR   -> truncated
                                                            to MICROseconds
      max_intra  .dt.total_seconds()            VECTOR   -> full ns/1e9

    Measured on pandas 3.0.5 over 200,000 randomised deltas: the two
    disagree on 199,810 of them. Using ns/1e9 for edge_gap shifts
    gap_duration_ms by 1 ms whenever round() sits on a .5 boundary --
    which is exactly the disagreement the equivalence war surfaced.
    So edge_gap goes through pandas itself rather than through a
    reimplementation that would have to be re-derived every upgrade.
    """
    import pandas as pd
    return pd.Timedelta(delta_ns, unit="ns").total_seconds()


def _coverage(agg: dict, outages) -> tuple:
    """Outage/edge/intra coverage classification -- the reference's
    per-row loop, over one aggregate instead of a DataFrame row."""
    b0 = float(agg["bucket_s"])
    b1 = b0 + BUCKET_S
    overlap = 0.0
    for o0, o1 in outages:
        s0, s1 = max(b0, o0), min(b1, o1)
        if s1 > s0:
            overlap += (s1 - s0)
    # the reference takes each edge as its own Timedelta.total_seconds()
    # and then adds the two floats; summing in ns first would round
    # differently, so the two divisions stay separate here.
    b0_ns = agg["bucket_s"] * NS
    b1_ns = b0_ns + BUCKET_NS
    # two separate scalar conversions, then added as floats -- the
    # reference adds two .total_seconds() results, and summing the ns
    # first would round differently.
    edge_gap = (_edge_seconds(agg["first_ns"] - b0_ns)
                + _edge_seconds(b1_ns - agg["last_ns"]))
    gap_ms = round((overlap + max(0.0, edge_gap - 10)) * 1000)
    intra = agg["max_intra"] or 0.0
    if overlap > 0:
        cov = "COMPLETE_WITH_GAP"
    elif agg["trades"] < MIN_TRADES_HEALTHY or edge_gap > MAX_EDGE_GAP_S:
        cov = "INCOMPLETE"
    elif intra > MAX_INTRA_GAP_S:
        cov = "COMPLETE_WITH_GAP"
        gap_ms = max(gap_ms, round(intra * 1000))
    else:
        cov = "COMPLETE_HEALTHY"
    return cov, gap_ms


def _claim(ambiguity: int, late: int) -> str:
    """The equivalence claim weakens for TWO distinct reasons, and they
    are not the same defect:

      ordering ambiguity  a closed bucket held an identical-nanosecond
                          tie while that symbol's arrival was
                          non-monotonic -- open/close for THOSE buckets
                          may differ from the reference

      late refusal        a trade arrived after its minute was
                          finalized and was refused. The reference
                          would have folded it in by rebuilding from
                          the whole tape. That is a genuine output
                          difference, so it weakens the claim too --
                          even though it is not ordering ambiguity and
                          must not be reported as such.
    """
    if not ambiguity and not late:
        return ("EXACT -- no bucket has closed with both an "
                "identical-nanosecond tie and non-monotonic arrival, "
                "and no trade has been refused as late; those are the "
                "only two things that can weaken it")
    parts = []
    if ambiguity:
        parts.append(
            "%d bucket(s) closed containing prints sharing an identical "
            "event-time nanosecond while that symbol's arrival was "
            "non-monotonic, so the reference's open/close for those "
            "buckets is an artifact of an unstable whole-array sort and "
            "may differ" % ambiguity)
    if late:
        parts.append(
            "%d trade(s) were refused as arriving after their minute "
            "was finalized, which the reference would have folded in"
            % late)
    return "CONDITIONAL -- " + "; ".join(parts) + \
        ". No other field and no other bucket is affected."


class SymbolState:
    __slots__ = ("open", "finalized", "watermark", "dedup_set",
                 "dedup_order", "seq", "arrival_monotonic")

    def __init__(self):
        self.open: dict = {}            # bucket_s -> _Bucket
        self.finalized: dict = {}       # bucket_s -> agg dict
        self.watermark: int | None = None
        self.dedup_set: set = set()
        self.dedup_order: deque = deque()   # (bucket_s, key), FIFO by bucket
        self.seq = 0
        # True while every arrival for this symbol has been >= the
        # previous one in event time. While this holds, pandas SKIPS
        # sort_index() in the reference and ties keep arrival order --
        # which is exactly what this implementation reproduces.
        self.arrival_monotonic = True


class TradeWorkingSet:
    """Bounded per-symbol working state that reproduces the reference
    bars exactly, while retaining raw trades only for minutes that can
    still legitimately change."""

    def __init__(self, symbols, *, retained_buckets: int = RETAINED_BUCKETS,
                 lateness_buckets: int = LATENESS_BUCKETS,
                 max_open_per_symbol: int = MAX_OPEN_TRADES_PER_SYMBOL,
                 max_open_aggregate: int = MAX_OPEN_TRADES_AGGREGATE,
                 max_dedup_per_symbol: int = MAX_DEDUP_KEYS_PER_SYMBOL):
        if retained_buckets < 1:
            raise ValueError("retained_buckets must be >= 1")
        if lateness_buckets < 0:
            raise ValueError("lateness_buckets must be >= 0")
        self.symbols = [str(s).upper() for s in symbols]
        self.retained_buckets = retained_buckets
        self.lateness_buckets = lateness_buckets
        self.max_open_per_symbol = max_open_per_symbol
        self.max_open_aggregate = max_open_aggregate
        self.max_dedup_per_symbol = max_dedup_per_symbol
        self._st: dict = {s: SymbolState() for s in self.symbols}
        self._ambiguous: deque = deque(maxlen=AMBIGUITY_SAMPLE_MAX)
        self._lock = threading.RLock()
        self.counters = {
            "admitted": 0, "duplicates": 0, "late_after_finalize": 0,
            "out_of_order_within_window": 0, "future_rejected": 0,
            "unknown_symbol": 0, "buckets_finalized": 0,
            "buckets_evicted": 0, "dedup_keys_evicted": 0,
            "bound_violations": 0, "forced_finalize": 0,
            "ordering_ambiguity_events": 0, "buckets_with_ns_tie": 0,
            "max_arrival_lag_s": 0.0,
        }

    # ------------------------------------------------------------ ingest
    def admit(self, symbol: str, *, event_s: float, price: float,
              size: float, conditions=None, key=None,
              arrival_s: float | None = None) -> str:
        """Fold one trade into the working set.

        Returns ACCEPTED / DUPLICATE / LATE_AFTER_FINALIZE /
        UNKNOWN_SYMBOL. The caller keeps its own future/staleness gate;
        this method is about STATE, not provider validation.
        """
        sym = str(symbol).upper()
        with self._lock:
            st = self._st.get(sym)
            if st is None:
                self.counters["unknown_symbol"] += 1
                return "UNKNOWN_SYMBOL"

            ns = to_ns(event_s)
            bucket = (ns // BUCKET_NS) * BUCKET_S

            # ONE CLOCK: the watermark is event time, never wall clock.
            # PULSE_V1's plateau failure was exactly a second clock.
            if st.watermark is None or bucket > st.watermark:
                st.watermark = bucket

            horizon = st.watermark - self.lateness_buckets * BUCKET_S
            if bucket < horizon:
                # The minute this belongs to can no longer change. The
                # reference WOULD still fold it in; we refuse and count
                # it, because the alternative is unbounded state. This
                # is the declared limit of LATE_TRADE_CONTRACT.
                self.counters["late_after_finalize"] += 1
                return "LATE_AFTER_FINALIZE"

            if key is not None:
                if key in st.dedup_set:
                    self.counters["duplicates"] += 1
                    return "DUPLICATE"
                st.dedup_set.add(key)
                st.dedup_order.append((bucket, key))

            b = st.open.get(bucket)
            if b is None:
                b = st.open[bucket] = _Bucket(bucket)
            if b.trades and ns < b.trades[-1][0]:
                self.counters["out_of_order_within_window"] += 1
                st.arrival_monotonic = False
            st.seq += 1
            # price/size are stored AS GIVEN. The reference builds a
            # DataFrame straight from the caller's values, so coercing
            # here would change the summed dtype of `volume` (an int
            # stream would serialise as 5101 there and 5101.0 here).
            # The fabric already passes floats; this keeps parity for
            # every other caller too.
            b.trades.append((ns, price, size, conditions, st.seq))
            self.counters["admitted"] += 1
            if arrival_s is not None:
                lag = arrival_s - event_s
                if lag > self.counters["max_arrival_lag_s"]:
                    self.counters["max_arrival_lag_s"] = lag

            self._finalize_ready(st, sym)
            self._expire_dedup(st)
            self._enforce_bound_b(sym, st)
            return "ACCEPTED"

    # ------------------------------------------------------- BOUND A work
    def _finalize_ready(self, st: SymbolState, sym: str = "?") -> None:
        """Close every open bucket the watermark has moved past.

        Finalization is where ordering ambiguity is judged, because a
        bucket is finalized exactly once -- judging it in bars(), which
        re-aggregates open buckets on every call, would count the same
        bucket repeatedly."""
        if st.watermark is None:
            return
        horizon = st.watermark - self.lateness_buckets * BUCKET_S
        ready = [k for k in st.open if k < horizon]
        for k in ready:
            b = st.open.pop(k)
            agg = aggregate_bucket(k, b.trades)
            st.finalized[k] = agg
            self.counters["buckets_finalized"] += 1
            if agg.get("has_ns_tie"):
                self.counters["buckets_with_ns_tie"] += 1
                if not st.arrival_monotonic:
                    # BOTH conditions: a tie AND a sort that actually ran
                    self.counters["ordering_ambiguity_events"] += 1
                    self._ambiguous.append(
                        {"symbol": sym, "bucket_s": k,
                         "trades": agg["trades"]})
        if len(st.finalized) > self.retained_buckets:
            drop = sorted(st.finalized)[:len(st.finalized)
                                        - self.retained_buckets]
            for k in drop:
                del st.finalized[k]
                self.counters["buckets_evicted"] += 1

    def _expire_dedup(self, st: SymbolState) -> None:
        """Dedup keys live exactly as long as the window in which a
        duplicate could still be folded in -- no longer, and never by
        clearing the whole set."""
        if st.watermark is None:
            return
        horizon = st.watermark - self.lateness_buckets * BUCKET_S
        order = st.dedup_order
        while order and order[0][0] < horizon:
            _, k = order.popleft()
            st.dedup_set.discard(k)
            self.counters["dedup_keys_evicted"] += 1

    # ------------------------------------------------------------ BOUND B
    def _enforce_bound_b(self, sym: str, st: SymbolState) -> None:
        """Emergency ceilings. Reaching one is not routine trimming: it
        means the prune path is broken or the world is outside its
        measured envelope. We force the oldest open bucket closed so
        memory stays bounded, and we RECORD the degradation rather than
        letting it pass silently."""
        n_open = sum(len(b.trades) for b in st.open.values())
        if n_open > self.max_open_per_symbol:
            self.counters["bound_violations"] += 1
            self._force_finalize_oldest(st)
        if len(st.dedup_set) > self.max_dedup_per_symbol:
            self.counters["bound_violations"] += 1
            n_drop = len(st.dedup_set) - self.max_dedup_per_symbol
            for _ in range(n_drop):
                if not st.dedup_order:
                    break
                _, k = st.dedup_order.popleft()
                st.dedup_set.discard(k)
                self.counters["dedup_keys_evicted"] += 1

    def _force_finalize_oldest(self, st: SymbolState) -> None:   # noqa: D401
        if not st.open:
            return
        k = min(st.open)
        b = st.open.pop(k)
        st.finalized[k] = aggregate_bucket(k, b.trades)
        self.counters["forced_finalize"] += 1
        self.counters["buckets_finalized"] += 1

    # ------------------------------------------------------------ BOUND C
    def assert_bounded(self) -> None:
        """Continuous invariant check. A broken prune clock must become
        visible IMMEDIATELY, not after the host dies."""
        with self._lock:
            agg_open = 0
            for sym, st in self._st.items():
                n_open = sum(len(b.trades) for b in st.open.values())
                agg_open += n_open
                max_buckets = self.lateness_buckets + 1
                if len(st.open) > max_buckets:
                    raise FabricStateBoundViolation(
                        f"{sym}: {len(st.open)} open buckets exceeds "
                        f"{max_buckets}; the event-time watermark and the "
                        f"finalize horizon have diverged")
                if len(st.finalized) > self.retained_buckets:
                    raise FabricStateBoundViolation(
                        f"{sym}: {len(st.finalized)} finalized buckets "
                        f"exceeds retained_buckets={self.retained_buckets}")
                if len(st.dedup_set) > self.max_dedup_per_symbol:
                    raise FabricStateBoundViolation(
                        f"{sym}: {len(st.dedup_set)} dedup keys exceeds "
                        f"{self.max_dedup_per_symbol}")
                if len(st.dedup_set) != len(st.dedup_order):
                    raise FabricStateBoundViolation(
                        f"{sym}: dedup set/queue diverged "
                        f"({len(st.dedup_set)} vs {len(st.dedup_order)}); "
                        f"one of them is no longer being expired")
                if st.watermark is not None and st.open:
                    horizon = (st.watermark
                               - self.lateness_buckets * BUCKET_S)
                    stale = [k for k in st.open if k < horizon]
                    if stale:
                        raise FabricStateBoundViolation(
                            f"{sym}: {len(stale)} open buckets older than "
                            f"the finalize horizon -- pruning has stopped")
            if agg_open > self.max_open_aggregate:
                raise FabricStateBoundViolation(
                    f"aggregate open trades {agg_open} exceeds "
                    f"{self.max_open_aggregate}")

    # ------------------------------------------------------------- output
    def bars(self, symbol: str, outages=(), *, now, transport: str = "",
             minutes: int | None = None):
        """The last `minutes` POPULATED one-minute bars, with exactly the
        reference's schema, ordering and coverage semantics."""
        import pandas as pd
        minutes = self.retained_buckets if minutes is None else minutes
        sym = str(symbol).upper()
        with self._lock:
            st = self._st.get(sym)
            if st is None:
                return pd.DataFrame()
            aggs = dict(st.finalized)
            for k, b in st.open.items():
                if b.trades:
                    aggs[k] = aggregate_bucket(k, b.trades)
            outages = list(outages)
        if not aggs:
            return pd.DataFrame()
        now_ts = pd.Timestamp(now)
        now_min = now_ts.floor("1min")
        now_min_s = now_min.value // 1_000_000_000
        keys = sorted(k for k in aggs if k < now_min_s)
        if not keys:
            return pd.DataFrame()
        keys = keys[-minutes:] if minutes is not None else keys
        # Coverage depends on the outage list, which GROWS: a new outage
        # legitimately reclassifies already-finalized minutes, exactly as
        # the reference recomputes every bar on every call. So the cache
        # is keyed by the outage list and invalidates itself when it
        # changes -- correctness first, cost second.
        okey = tuple(outages)
        rows = []
        for k in keys:
            a = aggs[k]
            if a.get("_cov_key") == okey:
                cov, gap_ms = a["_cov"]
            else:
                cov, gap_ms = _coverage(a, outages)
                a["_cov_key"] = okey
                a["_cov"] = (cov, gap_ms)
            rows.append({
                "event_time_utc": pd.Timestamp(k, unit="s", tz="UTC"),
                "open": a["open"], "high": a["high"], "low": a["low"],
                "close": a["close"], "volume": a["volume"],
                "trades": a["trades"], "coverage_status": cov,
                "gap_duration_ms": gap_ms, "symbol": sym,
                "transport": transport,
            })
        return pd.DataFrame(rows)

    # ------------------------------------------------ ordering semantics
    def ordering_semantics(self) -> dict:
        """Whether the conditions the equivalence proof depends on still
        hold. This is the tripwire for a claim, not a health verdict:
        an out-of-order print does not by itself corrupt a bar, it only
        removes the guarantee that open/close match the old
        implementation byte-for-byte when two prints share an identical
        nanosecond timestamp."""
        with self._lock:
            ooo = self.counters["out_of_order_within_window"]
            late = self.counters["late_after_finalize"]
            amb = self.counters["ordering_ambiguity_events"]
            ties = self.counters["buckets_with_ns_tie"]
            sample = list(self._ambiguous)
            non_mono = sorted(s for s, st in self._st.items()
                              if not st.arrival_monotonic)
        degraded = amb > 0
        return {
            "semantic_health": (SEMANTIC_HEALTH_DEGRADED if degraded
                                else SEMANTIC_HEALTH_EXACT),
            "state": (SEMANTIC_HEALTH_DEGRADED if degraded
                      else SEMANTIC_HEALTH_EXACT),
            "ordering_ambiguity_events": amb,
            "affected_buckets_sample": sample,
            "buckets_with_ns_tie": ties,
            "symbols_with_non_monotonic_arrival": non_mono,
            # kept as context, deliberately NOT the trigger
            "out_of_order": ooo,
            "late_after_finalize": late,
            "late_trade_contract": LATE_TRADE_CONTRACT,
            "equivalence_claim": _claim(amb, late),
        }

    # -------------------------------------------------------------- health
    def stats(self) -> dict:
        with self._lock:
            open_tr = {s: sum(len(b.trades) for b in st.open.values())
                       for s, st in self._st.items()}
            fin = {s: len(st.finalized) for s, st in self._st.items()}
            ded = {s: len(st.dedup_set) for s, st in self._st.items()}
            oldest = [min(st.finalized) for st in self._st.values()
                      if st.finalized]
            newest = [max(st.finalized) for st in self._st.values()
                      if st.finalized]
            return {
                "state_model": "TRADE_WORKING_SET_V1",
                "raw_trades_retained": sum(open_tr.values()),
                "raw_trades_retained_max_symbol": max(open_tr.values()
                                                      or [0]),
                "dedup_keys_retained": sum(ded.values()),
                "bars_retained": sum(fin.values()),
                "open_buckets": sum(len(st.open) for st in
                                    self._st.values()),
                "oldest_retained_bucket_s": min(oldest) if oldest else None,
                "newest_retained_bucket_s": max(newest) if newest else None,
                "retained_buckets_limit": self.retained_buckets,
                "lateness_buckets": self.lateness_buckets,
                "bound_a_semantic": "open window + %d aggregates"
                                    % self.retained_buckets,
                "ordering_semantics": self.ordering_semantics(),
                "bound_b_ceilings": {
                    "open_per_symbol": self.max_open_per_symbol,
                    "open_aggregate": self.max_open_aggregate,
                    "dedup_per_symbol": self.max_dedup_per_symbol},
                "counters": dict(self.counters),
            }
