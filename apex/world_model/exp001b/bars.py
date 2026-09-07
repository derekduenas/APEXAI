"""Session bars -> rows with six explicit clocks, on the exchange calendar.

Admission is NOT decided here. Callers pass an admission record from the
route that admitted the file (laboratory or real-data); this module parses
an already-admitted document and grants nothing.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

from apex.world_model import exchange_calendar as C, sources
from .registration import (BAR_SECONDS, EMBARGO_MINUTES, HORIZON_MINUTES,
                           NOT_AVAILABLE_IN_CORPUS, WARMUP_MINUTES)


class BarsRefused(Exception):
    """Input was present but unusable. Named reason, no default."""


def _t(s: str) -> float:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def load_session(path, *, declared_class: str, fixture_root=None, symbol: str,
                 session_date: str) -> dict:
    """LABORATORY route: sources.admit first, fixtures only."""
    adm = sources.admit(path, declared_class=declared_class, fixture_root=fixture_root)
    p = Path(path)
    raw = p.read_bytes()
    return session_from_doc(json.loads(raw), p, raw, adm, symbol=symbol, session_date=session_date)


def session_from_doc(doc: dict, p: Path, raw: bytes, adm: dict, *, symbol: str,
                     session_date: str) -> dict:
    try:
        bounds = C.session_bounds(session_date)
    except C.NotASession as e:
        raise BarsRefused("NOT_A_SESSION: %s" % e)
    bars = doc.get("bars")
    if not isinstance(bars, list) or not bars:
        raise BarsRefused("MISSING_BARS: %s has no bars" % p.name)
    o, c = bounds["open_utc"], bounds["close_utc"]
    rows, last_t, dropped = [], -math.inf, {"before_open": 0, "after_close": 0}
    for b in bars:
        try:
            t = _t(b["event_time_utc"])
        except (KeyError, ValueError, TypeError) as e:
            raise BarsRefused("MALFORMED_BAR_TIME: %s" % e)
        if t % BAR_SECONDS != 0:
            raise BarsRefused("UNALIGNED_BAR: %s at %s is not on a whole minute" % (p.name, b["event_time_utc"]))
        if C.local_date(t) != session_date:
            raise BarsRefused("SESSION_DATE_MISMATCH: %s carries a bar dated %s (exchange-local) "
                              "but declares session %s" % (p.name, C.local_date(t), session_date))
        if t < o:
            dropped["before_open"] += 1; continue
        if t >= c:
            dropped["after_close"] += 1; continue
        if t <= last_t:
            raise BarsRefused("NON_MONOTONIC: %s at %s" % (p.name, b["event_time_utc"]))
        last_t = t
        for k in ("open", "high", "low", "close", "volume"):
            v = b.get(k)
            if v is None or isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
                raise BarsRefused("INVALID_FIELD: %s.%s=%r" % (p.name, k, v))
        if b["close"] <= 0 or b["open"] <= 0:
            raise BarsRefused("NONPOSITIVE_PRICE: %s" % p.name)
        rows.append({"event_time": t, "bar_complete": t + BAR_SECONDS,
                     "assumed_available": t + BAR_SECONDS, "publication_time": None,
                     "minute": int((t - o) // 60),
                     "open": float(b["open"]), "high": float(b["high"]), "low": float(b["low"]),
                     "close": float(b["close"]), "volume": float(b["volume"])})
    if len(rows) < WARMUP_MINUTES + HORIZON_MINUTES + 1:
        raise BarsRefused("INSUFFICIENT_SESSION: %s has %d regular-session bars" % (p.name, len(rows)))
    return {"path": str(p), "sha256": hashlib.sha256(raw).hexdigest(),
            "source": doc.get("source", "UNDECLARED"), "admission": adm,
            "symbol": symbol, "session_date": session_date, "bounds": bounds,
            "n_raw_bars": len(bars), "n_regular": len(rows), "dropped_outside_session": dropped,
            "availability_basis": "ASSUMED_BAR_CLOSE", "publication_time": "NOT_AVAILABLE",
            "rows": rows, "not_available": list(NOT_AVAILABLE_IN_CORPUS)}


def _index(rows: list) -> dict:
    return {r["event_time"]: r for r in rows}


def observable_rows(session: dict) -> list:
    """Features from the bars at EXACTLY t-k*60s, k = 0..30. Any missing
    minute refuses the row; nothing is filled."""
    rows = session["rows"]
    by_t = _index(rows)
    o = session["bounds"]["open_utc"]
    out = []
    for i, r in enumerate(rows):
        t = r["event_time"]
        if t - WARMUP_MINUTES * 60 < o:
            out.append({**r, "i": i, "features": None,
                        "why": "WARMUP: %d minutes since open, %d required" % (r["minute"], WARMUP_MINUTES)})
            continue
        need = [t - k * 60 for k in range(WARMUP_MINUTES, -1, -1)]
        missing = [k for k, tt in zip(range(WARMUP_MINUTES, -1, -1), need) if tt not in by_t]
        if missing:
            out.append({**r, "i": i, "features": None,
                        "why": "MISSING_FEATURE_BARS: %d of 31 minute bars absent in [t-30m, t] (k=%s)"
                               % (len(missing), missing[:5])})
            continue
        c = [by_t[tt]["close"] for tt in need]
        lr = [math.log(c[k] / c[k - 1]) for k in range(1, len(c))]
        rv = math.sqrt(sum(x * x for x in lr) / len(lr))
        f = {"ret_1": math.log(c[-1] / c[-2]), "ret_5": math.log(c[-1] / c[-6]), "rv_30": rv}
        for k, v in f.items():
            if not math.isfinite(v):
                raise BarsRefused("NONFINITE_FEATURE: %s at bar %d" % (k, i))
        out.append({**r, "i": i, "features": f, "why": None})
    return out


def targets(session: dict, rows: list) -> list:
    """(y, outcome_available, reason) per row. The target is the bar at
    EXACTLY t + 15 min; its completion is when the outcome is known."""
    by_t = _index(session["rows"])
    close = session["bounds"]["close_utc"]
    out = []
    for r in rows:
        t = r["event_time"]
        tt = t + HORIZON_MINUTES * 60
        if tt + EMBARGO_MINUTES * 60 >= close:
            out.append((None, None, "EMBARGO: target within %d min of the close" % EMBARGO_MINUTES)); continue
        tb = by_t.get(tt)
        if tb is None:
            out.append((None, None, "MISSING_TARGET_BAR: no bar at t+%dmin" % HORIZON_MINUTES)); continue
        out.append((math.log(tb["close"] / r["close"]), tb["bar_complete"], None))
    return out


def execution_legs(session: dict, row: dict) -> dict:
    """Registered convention: entry at the OPEN of the bar at t+1min, exit
    at the OPEN of the bar at t+16min. Missing leg -> NOT_EXECUTABLE."""
    by_t = _index(session["rows"])
    t = row["event_time"]
    e, x = by_t.get(t + 60), by_t.get(t + (HORIZON_MINUTES + 1) * 60)
    if e is None or x is None:
        return {"executable": False, "why": "NOT_EXECUTABLE: %s leg bar missing"
                % ("entry" if e is None else "exit")}
    return {"executable": True, "entry_open": e["open"], "entry_time": e["event_time"],
            "exit_open": x["open"], "exit_time": x["event_time"],
            "decision_time": row["assumed_available"]}
