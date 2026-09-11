"""EVENT-TIME INGESTION with availability and receipt clocks (M2).

Clocks, all epoch seconds UTC:
    event_time         when the fact was true (trade print time; bar START for a bar)
    publication_time   when the provider says it published it (None if the provider does not say)
    receipt_time       when THIS process received it (our clock)
    bar_complete       bar start + 60 s: the instant the bar's content is fixed
    available          when APEX could first have used the bar = max(bar_complete, receipt of the
                       last input that formed it). Nothing is presented as known before this.

Rules:
    dedupe             identical (event_time, price, size, provider_seq) -> counted, not double-counted
    out-of-order       accepted; bars are rebuilt; the affected bar's `available` moves to the
                       late receipt time, and the late arrival is counted
    revision           a provider bar for a start already held with DIFFERENT values is a REVISION:
                       both versions are retained, the latest receipt is current, and the bar
                       carries revision_count + revised_at; a snapshot taken before the revision
                       is unaffected (prefix invariance), one taken after sees the revision and
                       says so
    gaps               a missing minute is DATA (no forward fill); windows that need it refuse"""
from __future__ import annotations

import math

BAR_SECONDS = 60


class IngestRefused(ValueError):
    pass


def _finite(x, what):
    if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x):
        raise IngestRefused("%s: not a finite real: %r" % (what, x))
    return float(x)


class BarStore:
    """Completed 1-minute bars for one symbol, from trades and/or provider bars."""

    def __init__(self, symbol: str, *, source: str):
        self.symbol = symbol
        self.source = source
        self._trades: dict = {}          # key -> trade
        self._bars: dict = {}            # start -> current bar (from provider or built)
        self._history: dict = {}         # start -> [versions]
        self.counters = {"trades": 0, "duplicates": 0, "out_of_order": 0, "late": 0, "revisions": 0,
                         "provider_bars": 0, "rejected": 0}
        self._last_event = -math.inf

    # ------------------------------------------------------------ trades
    def add_trade(self, *, event_time: float, price: float, size: float, receipt_time: float,
                  provider_seq=None, conditions=None) -> dict:
        et = _finite(event_time, "event_time"); rt = _finite(receipt_time, "receipt_time")
        px = _finite(price, "price"); sz = _finite(size, "size")
        if px <= 0 or sz < 0:
            self.counters["rejected"] += 1
            raise IngestRefused("TRADE_INVALID: price %r size %r" % (price, size))
        if rt < et:
            self.counters["rejected"] += 1
            raise IngestRefused("RECEIPT_BEFORE_EVENT: receipt %.3f < event %.3f" % (rt, et))
        key = (et, px, sz, provider_seq)
        if key in self._trades:
            self.counters["duplicates"] += 1
            return {"accepted": False, "why": "DUPLICATE"}
        if et < self._last_event:
            self.counters["out_of_order"] += 1
        self._last_event = max(self._last_event, et)
        start = math.floor(et / BAR_SECONDS) * BAR_SECONDS
        late = rt > start + BAR_SECONDS + 5.0          # arrived after the bar completed (+5 s grace)
        if late:
            self.counters["late"] += 1
        self._trades[key] = {"event_time": et, "price": px, "size": sz, "receipt_time": rt, "seq": provider_seq,
                             "conditions": conditions, "late": late}
        self.counters["trades"] += 1
        self._rebuild(start)
        return {"accepted": True, "bar_start": start, "late": late}

    def _rebuild(self, start: float):
        ts = sorted((t for t in self._trades.values() if start <= t["event_time"] < start + BAR_SECONDS),
                    key=lambda t: (t["event_time"], t["seq"] if t["seq"] is not None else -1))
        if not ts:
            return
        bar = {"symbol": self.symbol, "event_time": start, "bar_complete": start + BAR_SECONDS,
               "open": ts[0]["price"], "high": max(t["price"] for t in ts), "low": min(t["price"] for t in ts),
               "close": ts[-1]["price"], "volume": sum(t["size"] for t in ts), "trades": len(ts),
               "vwap": (sum(t["price"] * t["size"] for t in ts) / sum(t["size"] for t in ts)) if sum(t["size"] for t in ts) > 0 else None,
               "last_receipt": max(t["receipt_time"] for t in ts),
               "available": max(start + BAR_SECONDS, max(t["receipt_time"] for t in ts)),
               "publication_time": None, "built_from": "TRADES", "source": self.source,
               "late_prints": sum(1 for t in ts if t["late"]), "revision_count": 0, "revised_at": None}
        prev = self._bars.get(start)
        if prev is not None and prev.get("built_from") == "TRADES" and _same_values(prev, bar):
            return
        if prev is not None:
            bar["revision_count"] = prev["revision_count"] + 1
            bar["revised_at"] = bar["last_receipt"]
            self.counters["revisions"] += 1 if prev.get("built_from") == "PROVIDER" or prev["trades"] == bar["trades"] else 0
        self._bars[start] = bar
        self._history.setdefault(start, []).append(bar)

    # ------------------------------------------------------------ provider bars
    def add_provider_bar(self, *, event_time: float, open: float, high: float, low: float, close: float,
                         volume: float, receipt_time: float, publication_time: float | None = None,
                         vwap: float | None = None, trades: int | None = None) -> dict:
        et = _finite(event_time, "event_time"); rt = _finite(receipt_time, "receipt_time")
        if et % BAR_SECONDS != 0:
            self.counters["rejected"] += 1
            raise IngestRefused("BAR_NOT_ON_MINUTE: %r" % event_time)
        o, h, l, c = (_finite(open, "open"), _finite(high, "high"), _finite(low, "low"), _finite(close, "close"))
        v = _finite(volume, "volume")
        if not (l <= min(o, c) and max(o, c) <= h) or l <= 0 or v < 0:
            self.counters["rejected"] += 1
            raise IngestRefused("BAR_INCONSISTENT: o=%r h=%r l=%r c=%r v=%r" % (open, high, low, close, volume))
        if publication_time is not None:
            pt = _finite(publication_time, "publication_time")
            if pt < et + BAR_SECONDS - 1e-9:
                self.counters["rejected"] += 1
                raise IngestRefused("PUBLISHED_BEFORE_COMPLETE: publication %.3f < bar_complete %.3f" % (pt, et + BAR_SECONDS))
            if rt < pt:
                self.counters["rejected"] += 1
                raise IngestRefused("RECEIPT_BEFORE_PUBLICATION")
        else:
            pt = None
        if rt < et + BAR_SECONDS:
            self.counters["rejected"] += 1
            raise IngestRefused("RECEIVED_BEFORE_COMPLETE: receipt %.3f < bar_complete %.3f" % (rt, et + BAR_SECONDS))
        bar = {"symbol": self.symbol, "event_time": et, "bar_complete": et + BAR_SECONDS, "open": o, "high": h, "low": l,
               "close": c, "volume": v, "trades": trades, "vwap": vwap, "last_receipt": rt,
               "available": max(et + BAR_SECONDS, rt), "publication_time": pt, "built_from": "PROVIDER",
               "source": self.source, "late_prints": 0, "revision_count": 0, "revised_at": None}
        self.counters["provider_bars"] += 1
        prev = self._bars.get(et)
        if prev is not None:
            if _same_values(prev, bar):
                self.counters["duplicates"] += 1
                return {"accepted": False, "why": "DUPLICATE_BAR"}
            bar["revision_count"] = prev["revision_count"] + 1
            bar["revised_at"] = rt
            self.counters["revisions"] += 1
        if et < self._last_event:
            self.counters["out_of_order"] += 1
        self._last_event = max(self._last_event, et)
        self._bars[et] = bar
        self._history.setdefault(et, []).append(bar)
        return {"accepted": True, "bar_start": et, "revision": bar["revision_count"]}

    # ------------------------------------------------------------ reads (as-of)
    def bars_available_by(self, as_of: float, *, include_revisions: bool = True) -> list:
        """Completed bars whose CURRENT version (as of `as_of`) was available by `as_of`.
        A revision received after `as_of` is invisible; the earlier version is returned."""
        out = []
        for start in sorted(self._bars):
            versions = [v for v in self._history[start] if v["available"] <= as_of]
            if not versions:
                continue
            out.append(dict(versions[-1]))
        return out

    def versions(self, start: float) -> list:
        return list(self._history.get(start, []))


def _same_values(a: dict, b: dict) -> bool:
    return all(a.get(k) == b.get(k) for k in ("open", "high", "low", "close", "volume"))


def rolling_windows(bars: list, *, as_of: float, lengths=(1, 5, 10, 15, 30, 60)) -> dict:
    """Exact-minute windows ending at the last COMPLETED bar available by as_of. A missing
    minute inside a window refuses that window (no fill). Returns {L: {...}|None}."""
    by_t = {b["event_time"]: b for b in bars}
    if not by_t:
        return {L: None for L in lengths}
    last = max(by_t)
    out = {}
    for L in lengths:
        need = [last - k * BAR_SECONDS for k in range(L, -1, -1)]
        missing = [t for t in need if t not in by_t]
        if missing:
            out[L] = None
            continue
        c = [by_t[t]["close"] for t in need]
        lr = [math.log(c[k] / c[k - 1]) for k in range(1, len(c))]
        out[L] = {"ret": math.log(c[-1] / c[0]), "rv": math.sqrt(sum(x * x for x in lr) / len(lr)),
                  "n": L, "first": need[0], "last": last}
    return out
