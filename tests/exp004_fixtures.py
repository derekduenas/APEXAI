"""Deterministic synthetic sessions for EXP-004 implementation checks.

Entirely synthetic: no market data. Sessions are built through the REAL
exp001b.bars.session_from_doc on calendar-verified trading days, so timing,
warm-up, embargo and session bounds are the registered ones. Seeds are
predeclared here and nowhere else."""
from __future__ import annotations

import json
import math
import random
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from apex.world_model.exp001b import bars as B, exchange_calendar as C

SEEDS = {"fit": 20260910, "dev": 20260911, "n": 20260912}
N_FIT_SESSIONS = 110          # >= the registered baseline support of 100
N_DEV_SESSIONS = 8


def trading_days(start: str, n: int) -> list:
    d, out = date.fromisoformat(start), []
    while len(out) < n:
        if d.weekday() < 5:
            try:
                C.session_bounds(d.isoformat(), require_verified=True)
                out.append(d.isoformat())
            except C.NotASession:
                pass
        d += timedelta(days=1)
    return out


def build_bars(day: str, seed: int, *, closes=None, vol_scale: float = 1.0, body_sign: float = 1.0,
               flat_from: int | None = None) -> list:
    """Bars with a U-shaped volume profile and bodies drawn independently of
    the close path, so O/H/L/V can vary while closes stay fixed."""
    b = C.session_bounds(day, require_verified=True)
    t0, minutes = datetime.fromtimestamp(b["open_utc"], timezone.utc), int(b["regular_minutes"])
    rng = random.Random(seed)
    px, bars = 400.0, []
    for i in range(minutes):
        if closes is not None:
            c = closes[i]
        else:
            r = 0.0 if (flat_from is not None and i >= flat_from) else rng.gauss(0, 3e-4)
            px = px * math.exp(r); c = px
        body = body_sign * rng.uniform(-1, 1) * abs(rng.gauss(0, 2e-4)) * c
        o = c - body
        wick = abs(rng.gauss(0, 1.5e-4)) * c
        hi, lo = max(o, c) + wick, min(o, c) - wick
        u = (i - minutes / 2) / (minutes / 2)
        vol = vol_scale * (60_000 * (1 + 2.5 * u * u)) * math.exp(rng.gauss(0, 0.35))
        bars.append({"event_time_utc": (t0 + timedelta(minutes=i)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                     "open": o, "high": hi, "low": lo, "close": c, "volume": float(int(vol))})
    return bars


def session_from_bars(day: str, bars: list) -> dict:
    raw = json.dumps({"source": "alpaca_sip_raw_1m", "bars": bars}).encode()
    return B.session_from_doc({"source": "alpaca_sip_raw_1m", "bars": bars}, Path("SPY_%s.json" % day), raw,
                              {"sha256": "synthetic", "restricted_use": "synthetic fixture"},
                              symbol="SPY", session_date=day)


def make_session(day: str, seed: int, **kw) -> dict:
    return session_from_bars(day, build_bars(day, seed, **kw))


def fit_sessions(n: int = N_FIT_SESSIONS) -> list:
    return [make_session(d, SEEDS["fit"] + i) for i, d in enumerate(trading_days("2017-01-03", n))]


def dev_sessions(n: int = N_DEV_SESSIONS) -> list:
    return [make_session(d, SEEDS["dev"] + i) for i, d in enumerate(trading_days("2019-06-03", n))]


def dev_sessions_years(years=("2019", "2020", "2021"), per_year: int = 4) -> list:
    """Chronological development sessions across the registered report years."""
    out, k = [], 0
    for y in years:
        for d in trading_days("%s-06-01" % y, per_year):
            out.append(make_session(d, SEEDS["dev"] + 100 + k)); k += 1
    return out
