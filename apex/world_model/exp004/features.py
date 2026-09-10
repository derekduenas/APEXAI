"""EXP-004 features under the frozen registration (R3, R7).

Pure functions over admitted session dicts (exp001b.bars.session_from_doc
shape). Nothing here reads files or decides admission. Every refusal is named;
nothing is repaired, filled, or filtered silently."""
from __future__ import annotations

import math

from apex.world_model.exp001b import bars as B
from apex.world_model.exp001b.run import _usable
from apex.world_model.exp002.registration import RV_FLOOR
from .registration import BASELINE, WINDOW_BARS

BAR_SECONDS = 60
REFUSAL_KEYS = ("WARMUP", "MISSING_FEATURE_BARS", "MISSING_TARGET_BAR", "EMBARGO", "RV_FLOOR",
                "MISSING_PRESSURE_BARS", "INVALID_OHLC", "NO_BASELINE_SUPPORT", "ZERO_BASELINE")
RAW = ("Bbar", "P", "F")
CLIPPED = {"Bbar": "Bbar_c", "P": "P_c", "F": "F_c"}


class FeatureRefused(ValueError):
    """A named refusal at the feature stage."""


def bar_invalid(bar: dict) -> str | None:
    """INVALID_OHLC reason or None. Zero volume in a present bar is VALID."""
    vals = [bar.get(k) for k in ("open", "high", "low", "close", "volume")]
    if any(v is None or isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in vals):
        return "INVALID_OHLC: non-finite or missing field"
    o, h, l, c, v = vals
    if h < l:
        return "INVALID_OHLC: high < low"
    if not (l <= o <= h) or not (l <= c <= h):
        return "INVALID_OHLC: open/close outside [low, high]"
    if v < 0:
        return "INVALID_OHLC: negative volume"
    return None


def body(bar: dict) -> tuple:
    """Signed body-to-range B in [-1, 1]; zero-range bars give 0 and are flagged."""
    rng = bar["high"] - bar["low"]
    if rng > 0:
        return (bar["close"] - bar["open"]) / rng, False
    return 0.0, True


# ---------------------------------------------------------------- session identity and order

def validate_sessions(sessions: list, *, role: str, symbol: str = "SPY") -> dict:
    """The runner never trusts the caller's list. Refuses, by name: an empty
    list, a session without an identity, a symbol other than the registered
    one, a DUPLICATE session_date (the same session offered twice can fabricate
    baseline support), and any non-strictly-increasing date order (the
    session-order bootstrap depends on chronology)."""
    if not sessions:
        raise FeatureRefused("NO_SESSIONS: %s" % role)
    dates = []
    for i, s in enumerate(sessions):
        d, sym = s.get("session_date"), s.get("symbol")
        if not d or not sym:
            raise FeatureRefused("SESSION_WITHOUT_IDENTITY: %s index %d" % (role, i))
        if sym != symbol:
            raise FeatureRefused("SYMBOL_MISMATCH: %s index %d is %r, registered %r" % (role, i, sym, symbol))
        if d in dates:
            raise FeatureRefused("DUPLICATE_SESSION: %s %s offered more than once" % (role, d))
        if dates and d <= dates[-1]:
            raise FeatureRefused("NON_CHRONOLOGICAL_SESSIONS: %s %s after %s" % (role, d, dates[-1]))
        dates.append(d)
    return {"role": role, "n_sessions": len(dates), "first": dates[0], "last": dates[-1],
            "unique": True, "strictly_increasing": True, "symbol": symbol}


def validate_fit_bars(fit_sessions: list) -> dict:
    """Step 1: every fit bar must be valid. A malformed or impossible bar is
    REFUSED by name (session and minute); it is never excluded silently."""
    n = 0
    for s in fit_sessions:
        for bar in s["rows"]:
            why = bar_invalid(bar)
            if why:
                raise FeatureRefused("INVALID_FIT_BAR: %s minute %s: %s" % (s["session_date"], bar.get("minute"), why))
            n += 1
    return {"bars_validated": n, "sessions": len(fit_sessions)}


# ---------------------------------------------------------------- step 2: baselines

def fit_baselines(fit_sessions: list, *, min_support: int = BASELINE["min_support_sessions"]) -> dict:
    """Per session-minute MEDIAN volume over the fit sessions. Support counts
    UNIQUE sessions (validate_sessions and validate_fit_bars must have run;
    this function re-checks uniqueness and validity and refuses otherwise)."""
    ident = validate_sessions(fit_sessions, role="fit")
    validate_fit_bars(fit_sessions)
    by_minute: dict = {}
    for s in fit_sessions:
        seen = set()
        for bar in s["rows"]:
            m = bar["minute"]
            if m in seen:
                raise FeatureRefused("DUPLICATE_MINUTE: %s minute %s" % (s["session_date"], m))
            seen.add(m)
            by_minute.setdefault(m, []).append(float(bar["volume"]))
    vbar, support = {}, {}
    for m, vols in by_minute.items():
        support[m] = len(vols)
        if len(vols) >= min_support:
            vols = sorted(vols)
            n = len(vols)
            vbar[m] = vols[n // 2] if n % 2 else 0.5 * (vols[n // 2 - 1] + vols[n // 2])
    return {"vbar": vbar, "support": support, "min_support": min_support,
            "sessions": ident["n_sessions"], "unique_session_dates": ident["n_sessions"],
            "minutes_with_baseline": len(vbar)}


# ---------------------------------------------------------------- pressure window

def pressure_from_window(bars: list, vbars: list) -> dict:
    """Pure: raw (Bbar, P, F) from W bars and their W baselines. No checks."""
    W = len(bars)
    bs, zero_range = [], 0
    for b in bars:
        bb, zr = body(b)
        bs.append(bb)
        zero_range += int(zr)
    vs = [float(b["volume"]) for b in bars]
    svbar = float(sum(vbars))
    bbar = sum(bs) / W
    p = sum(vs) / svbar
    f = sum(bb * v for bb, v in zip(bs, vs)) / svbar
    return {"Bbar": bbar, "P": p, "F": f, "zero_range_bars": zero_range, "W": W}


def pressure_for_row(row: dict, by_t: dict, vbar: dict, *, W: int = WINDOW_BARS) -> tuple:
    """(features | None, refusal | None) for the window of W completed bars
    ending at the row's bar. Bars come from the same session's index, so the
    window cannot cross a session; a missing minute refuses, never bridged."""
    t = row["event_time"]
    times = [t - k * BAR_SECONDS for k in range(W - 1, -1, -1)]
    bars = []
    for tt in times:
        b = by_t.get(tt)
        if b is None:
            return None, "MISSING_PRESSURE_BARS"
        why = bar_invalid(b)
        if why:
            return None, "INVALID_OHLC"
        bars.append(b)
    vbars = []
    for b in bars:
        v = vbar.get(b["minute"])
        if v is None:
            return None, "NO_BASELINE_SUPPORT"
        vbars.append(v)
    if not (sum(vbars) > 0):
        return None, "ZERO_BASELINE"
    return pressure_from_window(bars, vbars), None


# ---------------------------------------------------------------- step 3: common eligible rows

def eligible_rows(session: dict, vbar: dict, *, W: int = WINDOW_BARS) -> tuple:
    """Rows satisfying EVERY arm's requirements (legacy warm-up, target,
    embargo, RV_FLOOR, pressure window). Returns ([(row, y, tk)], refusals)."""
    refused = {k: 0 for k in REFUSAL_KEYS}
    rows = B.observable_rows(session)
    tg = B.targets(session, rows)
    for r, (y, tk, why) in zip(rows, tg):
        if r["features"] is None:
            refused[r["why"].split(":")[0]] += 1
        elif y is None:
            refused[why.split(":")[0]] += 1
    by_t = {b["event_time"]: b for b in session["rows"]}
    out, zero_range_total = [], 0
    for r, y, tk in _usable(rows, tg):
        if not (r["features"]["rv_30"] >= RV_FLOOR):
            refused["RV_FLOOR"] += 1
            continue
        pf, why = pressure_for_row(r, by_t, vbar, W=W)
        if why:
            refused[why] += 1
            continue
        r["features"] = {**r["features"], "Bbar": pf["Bbar"], "P": pf["P"], "F": pf["F"]}
        r["pressure"] = {"zero_range_bars": pf["zero_range_bars"]}
        r["session_id"] = session["session_date"]
        zero_range_total += pf["zero_range_bars"]
        out.append((r, y, tk))
    return out, {**refused, "eligible": len(out), "zero_range_bars_in_windows": zero_range_total}


def eligible_rows_many(sessions: list, vbar: dict, *, W: int = WINDOW_BARS, role: str = "development") -> tuple:
    """Rows in strict session order. Returns (rows, aggregate refusals,
    per-session refusals) after validating identity and chronology."""
    validate_sessions(sessions, role=role)
    rows_all, agg, per_session = [], None, {}
    for s in sessions:
        rows, ref = eligible_rows(s, vbar, W=W)
        rows_all.extend(rows)
        per_session[s["session_date"]] = ref
        agg = ref if agg is None else {k: agg[k] + ref[k] for k in ref}
    empty = {k: 0 for k in (*REFUSAL_KEYS, "eligible", "zero_range_bars_in_windows")}
    return rows_all, (agg or empty), per_session


# ---------------------------------------------------------------- step 4: clipping

def order_statistic(values: list, num: int = 99, den: int = 100) -> float:
    """The ceil(num/den * n)-th order statistic, 1-indexed, no interpolation,
    with EXACT integer arithmetic (floating ceil(q*n) can round up)."""
    v = sorted(float(x) for x in values)
    n = len(v)
    if n == 0:
        raise FeatureRefused("NO_ROWS_FOR_QUANTILE")
    k = (num * n + den - 1) // den
    return v[max(1, min(n, k)) - 1]


def clipping_constants(rows_y: list, *, num: int = 99, den: int = 100) -> dict:
    return {"q_B": order_statistic([abs(r["features"]["Bbar"]) for r, _, _ in rows_y], num, den),
            "q_P": order_statistic([r["features"]["P"] for r, _, _ in rows_y], num, den),
            "q_F": order_statistic([abs(r["features"]["F"]) for r, _, _ in rows_y], num, den),
            "quantile": num / den, "convention": "ceil(q*n)-th order statistic, 1-indexed, exact integer arithmetic",
            "n": len(rows_y)}


def apply_clipping(rows_y: list, consts: dict) -> dict:
    """Adds Bbar_c, P_c, F_c in place; returns clipped counts."""
    clipped = {"Bbar": 0, "P": 0, "F": 0}
    qb, qp, qf = consts["q_B"], consts["q_P"], consts["q_F"]
    for r, _, _ in rows_y:
        f = r["features"]
        bc = min(max(f["Bbar"], -qb), qb); clipped["Bbar"] += int(bc != f["Bbar"])
        pc = min(max(f["P"], 0.0), qp);   clipped["P"] += int(pc != f["P"])
        fc = min(max(f["F"], -qf), qf);   clipped["F"] += int(fc != f["F"])
        f["Bbar_c"], f["P_c"], f["F_c"] = bc, pc, fc
    return {"clipped_rows": clipped, "n": len(rows_y)}
