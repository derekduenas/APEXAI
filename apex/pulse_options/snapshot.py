"""OPTIONS_TWIN_STATE_V0 — one immutable as-of snapshot (M2).

Built ONLY from inputs whose availability clock is <= as_of. Every field is a
`apex.pulse.twin.Field` (value + quality + source + as_of + known_from) so
missingness and staleness are stated per field, never flattened. The
snapshot is a dict with a content hash; prefix invariance is a tested
property: appending observations after as_of cannot change the snapshot.

Field groups:
    bars        completed-bar returns and realized variance over 1/5/10/15/30/60-minute windows
    session     session phase (REGULAR/PREMARKET/...), minute-of-session, seasonality bucket,
                regular-session boundaries (DST-safe via apex.intraday.sessions)
    location    VWAP (session), position vs VWAP, session range position, prior close and gap
                when supplied (anchors: definitionally older)
    book        top-of-book bid/ask/sizes/spread_bps for the underlying when supplied
    options     chain freshness / count when supplied (surface analytics are M4)
    context     permitted cross-market context (supplied, timestamped) and SCHEDULED events
                (future schedule is a known covariate; released values are NOT taken here)
    provenance  source identities, availability clocks, counters, missingness"""
from __future__ import annotations

import math
from datetime import datetime, timezone

from apex.intraday.sessions import Session, classify
from apex.pulse.twin import Field, NOT_AVAILABLE, NOT_ESTIMABLE, SESSION_INAPPLICABLE, STALE, UNKNOWN, VALID, absent, ok

from .ingest import BAR_SECONDS, rolling_windows

SCHEMA_VERSION = "OPTIONS_TWIN_STATE_V0"
BAR_TOLERANCE_S = 120.0          # a "current" completed bar older than this is STALE for decision use
BOOK_TOLERANCE_S = 15.0
CHAIN_TOLERANCE_S = 60.0
WINDOWS = (1, 5, 10, 15, 30, 60)


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _session_fields(as_of: float) -> dict:
    sess = classify(datetime.fromtimestamp(as_of, tz=timezone.utc))
    f = {"session_phase": ok(sess.value, source="apex.intraday.sessions", as_of=_iso(as_of), known_from=_iso(as_of))}
    if sess == Session.REGULAR:
        # minute-of-session is computed from the exchange-local open, DST-safe (classify already converted)
        local = datetime.fromtimestamp(as_of, tz=timezone.utc).astimezone(__import__("zoneinfo").ZoneInfo("America/New_York"))
        minute = (local.hour - 9) * 60 + (local.minute - 30)
        f["minute_of_session"] = ok(minute, source="apex.intraday.sessions", as_of=_iso(as_of), known_from=_iso(as_of))
        bucket = "OPEN_30" if minute < 30 else "MIDDAY" if minute < 330 else "CLOSE_60"
        f["seasonality_bucket"] = ok(bucket, source="OPTIONS_TWIN_STATE_V0.seasonality", as_of=_iso(as_of), known_from=_iso(as_of),
                                     note="a bucket label; not a fitted seasonality model")
    else:
        f["minute_of_session"] = absent(SESSION_INAPPLICABLE, source="apex.intraday.sessions", note=sess.value)
        f["seasonality_bucket"] = absent(SESSION_INAPPLICABLE, source="apex.intraday.sessions", note=sess.value)
    return f


def compose(*, symbol: str, as_of: float, bars: list, source: str, book: dict | None = None,
            chain_meta: dict | None = None, context: dict | None = None, events: list | None = None,
            prior_close: dict | None = None) -> dict:
    """`bars` must ALREADY be filtered to availability <= as_of (BarStore.bars_available_by does that);
    the function refuses any bar that claims availability after as_of, so a caller cannot leak."""
    for b in bars:
        if b["available"] > as_of:
            raise ValueError("FUTURE_BAR_IN_SNAPSHOT: bar %s available %.3f > as_of %.3f" % (b["event_time"], b["available"], as_of))
    fields: dict = {}
    sess = _session_fields(as_of)
    fields.update(sess)
    # ---- bars
    if bars:
        last = max(bars, key=lambda b: b["event_time"])
        age = as_of - last["bar_complete"]
        q = VALID if age <= BAR_TOLERANCE_S else STALE
        fields["last_bar_close"] = (ok(last["close"], source=source, as_of=_iso(last["bar_complete"]), known_from=_iso(last["available"]))
                                    if q == VALID else absent(STALE, source=source, note="last completed bar %.0fs old > %.0fs" % (age, BAR_TOLERANCE_S)))
        fields["last_bar_age_s"] = ok(round(age, 3), source=source, as_of=_iso(as_of), known_from=_iso(as_of))
        fields["last_bar_revision_count"] = ok(int(last.get("revision_count", 0)), source=source, as_of=_iso(last["available"]), known_from=_iso(last["available"]))
        win = rolling_windows(bars, as_of=as_of, lengths=WINDOWS)
        for L in WINDOWS:
            w = win[L]
            for name, key in (("ret_%d" % L, "ret"), ("rv_%d" % L, "rv")):
                if w is None:
                    fields[name] = absent(NOT_ESTIMABLE, source=source, note="window of %d completed minutes not fully available" % L)
                elif q != VALID:
                    fields[name] = absent(STALE, source=source, note="window ends at a stale bar")
                else:
                    fields[name] = ok(w[key], source=source, as_of=_iso(last["bar_complete"]), known_from=_iso(last["available"]))
        # session VWAP / range from bars of the current session date (bars carry vwap when built from trades)
        vw = [b for b in bars if b.get("vwap") is not None and b.get("volume")]
        if vw and q == VALID:
            num = sum(b["vwap"] * b["volume"] for b in vw); den = sum(b["volume"] for b in vw)
            vwap = num / den
            fields["session_vwap"] = ok(vwap, source=source, as_of=_iso(last["bar_complete"]), known_from=_iso(last["available"]),
                                        note="volume-weighted over completed bars available by as_of")
            fields["vwap_distance_bps"] = ok(1e4 * (last["close"] / vwap - 1.0), source=source, as_of=_iso(last["bar_complete"]), known_from=_iso(last["available"]))
        else:
            fields["session_vwap"] = absent(NOT_ESTIMABLE if q == VALID else STALE, source=source, note="no per-bar vwap/volume")
            fields["vwap_distance_bps"] = absent(NOT_ESTIMABLE if q == VALID else STALE, source=source)
        hi, lo = max(b["high"] for b in bars), min(b["low"] for b in bars)
        if hi > lo and q == VALID:
            fields["session_range_position"] = ok((last["close"] - lo) / (hi - lo), source=source, as_of=_iso(last["bar_complete"]), known_from=_iso(last["available"]))
        else:
            fields["session_range_position"] = absent(NOT_ESTIMABLE if q == VALID else STALE, source=source)
    else:
        for name in ("last_bar_close", "last_bar_age_s", "last_bar_revision_count", "session_vwap", "vwap_distance_bps", "session_range_position"):
            fields[name] = absent(UNKNOWN, source=source, note="no completed bars available by as_of")
        for L in WINDOWS:
            fields["ret_%d" % L] = absent(UNKNOWN, source=source)
            fields["rv_%d" % L] = absent(UNKNOWN, source=source)
    # ---- prior close (anchor; supplied with its own clock)
    if prior_close and _num(prior_close.get("close")) and _num(prior_close.get("available")) and prior_close["available"] <= as_of:
        fields["prior_close"] = ok(prior_close["close"], source=prior_close.get("source", source), as_of=_iso(prior_close["as_of"]),
                                   known_from=_iso(prior_close["available"]), note="anchor: definitionally older")
        if bars and fields["last_bar_close"].usable:
            fields["gap_from_prior_close_bps"] = ok(1e4 * (fields["last_bar_close"].value / prior_close["close"] - 1.0), source=source,
                                                    as_of=fields["last_bar_close"].as_of, known_from=fields["last_bar_close"].known_from)
        else:
            fields["gap_from_prior_close_bps"] = absent(NOT_ESTIMABLE, source=source)
    else:
        fields["prior_close"] = absent(NOT_AVAILABLE if not prior_close else UNKNOWN, source=source)
        fields["gap_from_prior_close_bps"] = absent(NOT_AVAILABLE if not prior_close else UNKNOWN, source=source)
    # ---- top of book (underlying)
    if book and _num(book.get("available")) and book["available"] <= as_of:
        age = as_of - book["available"]
        if not (_num(book.get("bid")) and _num(book.get("ask")) and book["ask"] >= book["bid"] > 0):
            for k in ("underlying_bid", "underlying_ask", "underlying_spread_bps", "underlying_bid_size", "underlying_ask_size"):
                fields[k] = absent(NOT_ESTIMABLE, source=book.get("source", "book"), note="crossed/invalid book")
        elif age > BOOK_TOLERANCE_S:
            for k in ("underlying_bid", "underlying_ask", "underlying_spread_bps", "underlying_bid_size", "underlying_ask_size"):
                fields[k] = absent(STALE, source=book.get("source", "book"), note="book %.1fs old > %.0fs" % (age, BOOK_TOLERANCE_S))
        else:
            src = book.get("source", "book"); t = _iso(book["as_of"]); kf = _iso(book["available"])
            mid = 0.5 * (book["bid"] + book["ask"])
            fields["underlying_bid"] = ok(book["bid"], source=src, as_of=t, known_from=kf)
            fields["underlying_ask"] = ok(book["ask"], source=src, as_of=t, known_from=kf)
            fields["underlying_spread_bps"] = ok(1e4 * (book["ask"] - book["bid"]) / mid, source=src, as_of=t, known_from=kf)
            for k in ("bid_size", "ask_size"):
                fields["underlying_" + k] = (ok(int(book[k]), source=src, as_of=t, known_from=kf) if type(book.get(k)) is int
                                             else absent(NOT_AVAILABLE, source=src))
    else:
        for k in ("underlying_bid", "underlying_ask", "underlying_spread_bps", "underlying_bid_size", "underlying_ask_size"):
            fields[k] = absent(NOT_AVAILABLE if not book else UNKNOWN, source="book")
    # ---- options chain metadata (surface analytics are M4)
    if chain_meta and _num(chain_meta.get("available")) and chain_meta["available"] <= as_of:
        age = as_of - chain_meta["available"]
        src = chain_meta.get("source", "chain")
        if age > CHAIN_TOLERANCE_S:
            fields["chain_quote_count"] = absent(STALE, source=src, note="chain %.0fs old > %.0fs" % (age, CHAIN_TOLERANCE_S))
        else:
            fields["chain_quote_count"] = ok(int(chain_meta.get("quote_count", 0)), source=src, as_of=_iso(chain_meta["as_of"]), known_from=_iso(chain_meta["available"]))
        fields["chain_expirations"] = ok(list(chain_meta.get("expirations", [])), source=src, as_of=_iso(chain_meta["as_of"]), known_from=_iso(chain_meta["available"]))
    else:
        fields["chain_quote_count"] = absent(NOT_AVAILABLE, source="chain")
        fields["chain_expirations"] = absent(NOT_AVAILABLE, source="chain")
    # ---- permitted cross-market context (already-timestamped; refused if not available by as_of)
    for name, ctx in (context or {}).items():
        if _num(ctx.get("value")) and _num(ctx.get("available")) and ctx["available"] <= as_of:
            fields["ctx_" + name] = ok(ctx["value"], source=ctx.get("source", "context"), as_of=_iso(ctx["as_of"]), known_from=_iso(ctx["available"]))
        else:
            fields["ctx_" + name] = absent(UNKNOWN if ctx else NOT_AVAILABLE, source=ctx.get("source", "context"), note="not available by as_of")
    # ---- scheduled events: the SCHEDULE is known; released values are not taken here
    upcoming = [e for e in (events or []) if _num(e.get("scheduled_epoch")) and e["scheduled_epoch"] >= as_of
                and _num(e.get("schedule_known_from")) and e["schedule_known_from"] <= as_of]
    if upcoming:
        nxt = min(upcoming, key=lambda e: e["scheduled_epoch"])
        fields["next_scheduled_event_type"] = ok(str(nxt.get("type")), source=nxt.get("source", "calendar"), as_of=_iso(nxt["schedule_known_from"]), known_from=_iso(nxt["schedule_known_from"]))
        fields["seconds_to_next_scheduled_event"] = ok(nxt["scheduled_epoch"] - as_of, source=nxt.get("source", "calendar"), as_of=_iso(as_of), known_from=_iso(as_of))
    else:
        fields["next_scheduled_event_type"] = absent(NOT_AVAILABLE if not events else UNKNOWN, source="calendar")
        fields["seconds_to_next_scheduled_event"] = absent(NOT_AVAILABLE if not events else UNKNOWN, source="calendar")

    def _record(f: Field) -> dict:
        d = {"value": f.value, "quality": f.quality, "source": f.source, "as_of": f.as_of, "known_from": f.gate_time()}
        a = f.age_ms(_iso(as_of)) if f.gate_time() else None
        if a is not None:
            d["age_ms"] = a
        if f.note:
            d["note"] = f.note
        return d
    rec = {k: _record(f) for k, f in fields.items()}
    census: dict = {}
    for f in fields.values():
        census[f.quality] = census.get(f.quality, 0) + 1
    usable = sum(1 for f in fields.values() if f.usable)
    body = {"kind": "options_twin_state", "schema_version": SCHEMA_VERSION, "symbol": symbol, "as_of_epoch": as_of,
            "as_of_utc": _iso(as_of), "source": source, "fields": rec, "quality_census": dict(sorted(census.items())),
            "missingness": round(1.0 - usable / max(1, len(fields)), 4),
            "n_bars_available": len(bars), "last_bar_event_time": (max(b["event_time"] for b in bars) if bars else None),
            "causality": "every input's availability clock <= as_of; no forward fill; a missing minute refuses its windows",
            "decision_power": "NONE_STATE"}
    from apex.options_pilot.records import canonical_hash
    body["state_hash"] = canonical_hash({k: body[k] for k in ("schema_version", "symbol", "as_of_epoch", "fields", "n_bars_available")})
    return body


def usable_value(snapshot: dict, name: str):
    f = snapshot["fields"].get(name)
    if f and f.get("quality") == VALID:
        return f.get("value")
    return None
