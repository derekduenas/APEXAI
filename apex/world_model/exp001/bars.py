"""Session bars -> observable rows, through the source boundary FIRST.

Admission is requested from apex.world_model.sources.admit for every file.
A refusal propagates unchanged: it is the result, not an error to catch.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

from apex.world_model import sources
from .registration import (HORIZON_STEPS, NOT_AVAILABLE_IN_CORPUS,
                           SESSION_UTC, WARMUP_BARS)


class BarsRefused(Exception):
    """Input was present but unusable. Named reason, no default."""


def _t(s: str) -> float:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def load_session(path, *, declared_class: str, fixture_root=None) -> dict:
    """One session file. sources.admit decides; nothing here overrides it."""
    adm = sources.admit(path, declared_class=declared_class,
                        fixture_root=fixture_root)
    p = Path(path)
    raw = p.read_bytes()
    return session_from_doc(json.loads(raw), p, raw, adm)


def session_from_doc(doc: dict, p: Path, raw: bytes, adm: dict) -> dict:
    """Parse an ALREADY-ADMITTED session document. Admission is the caller's
    problem and is recorded in `adm`; this function grants nothing."""
    bars = doc.get("bars")
    if not isinstance(bars, list) or not bars:
        raise BarsRefused("MISSING_BARS: %s has no bars" % p.name)
    lo, hi = SESSION_UTC
    rows, last_t = [], -math.inf
    for b in bars:
        try:
            t = _t(b["event_time_utc"])
        except (KeyError, ValueError) as e:
            raise BarsRefused("MALFORMED_BAR_TIME: %s" % e)
        hhmm = datetime.fromtimestamp(t, timezone.utc).strftime("%H:%M")
        if not (lo <= hhmm < hi):
            continue
        if t <= last_t:
            raise BarsRefused("NON_MONOTONIC: %s at %s" % (p.name, b["event_time_utc"]))
        last_t = t
        for k in ("open", "high", "low", "close", "volume"):
            v = b.get(k)
            if v is None or not isinstance(v, (int, float)) or not math.isfinite(v):
                raise BarsRefused("INVALID_FIELD: %s.%s=%r" % (p.name, k, v))
        if b["close"] <= 0 or b["open"] <= 0:
            raise BarsRefused("NONPOSITIVE_PRICE: %s" % p.name)
        rows.append({"t": t, "open": float(b["open"]), "close": float(b["close"]),
                     "high": float(b["high"]), "low": float(b["low"]),
                     "volume": float(b["volume"])})
    if len(rows) < WARMUP_BARS + HORIZON_STEPS + 1:
        raise BarsRefused("INSUFFICIENT_SESSION: %s has %d regular-session bars"
                          % (p.name, len(rows)))
    return {"path": str(p), "sha256": hashlib.sha256(raw).hexdigest(),
            "source": doc.get("source", "UNDECLARED"), "admission": adm,
            "rows": rows, "not_available": list(NOT_AVAILABLE_IN_CORPUS)}


def observable_rows(session: dict) -> list:
    """Per-bar observable state with features, or an explicit refusal for
    the warm-up. Features use bars with t <= this bar's t and nothing else."""
    rows = session["rows"]
    out = []
    for i, r in enumerate(rows):
        if i < WARMUP_BARS:
            out.append({**r, "i": i, "features": None,
                        "why": "WARMUP: %d bars precede, %d required" % (i, WARMUP_BARS)})
            continue
        c = [x["close"] for x in rows[i - WARMUP_BARS:i + 1]]
        lr = [math.log(c[k] / c[k - 1]) for k in range(1, len(c))]
        rv = math.sqrt(sum(x * x for x in lr[-30:]) / 30.0)
        f = {"ret_1": math.log(c[-1] / c[-2]), "ret_5": math.log(c[-1] / c[-6]),
             "rv_30": rv}
        for k, v in f.items():
            if not math.isfinite(v):
                raise BarsRefused("NONFINITE_FEATURE: %s at bar %d" % (k, i))
        out.append({**r, "i": i, "features": f, "why": None})
    return out
