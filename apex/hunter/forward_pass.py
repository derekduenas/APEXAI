"""The Hunter forward pass: states -> scan -> playbooks -> DECISION records,
and the end-of-day deterministic realization resolver.

Eligibility is mechanical: every DECISION carries the four dependency
birth times (protocol / feature schema / playbook / model) and the computed
FORWARD_ELIGIBLE / NOT_FORWARD_ELIGIBLE verdict. A forecast made before any
dependency's birth can never become forward evidence retroactively — the
ledger refuses it at write time, no human judgment involved.

One DECISION per (symbol, playbook, direction) per session (frozen rule):
the first formation wins; later snapshots of the same setup are not new
evidence, they are the same opportunity observed again.

Realizations are appended, never edited into decisions; each is labeled
MECHANICAL_DETERMINISTIC (protocol §3) — an outcome measurement, computed
identically by anyone from the same bars.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pandas as pd

from apex.hunter import birth as birthlib
from apex.hunter.chartstate import (BAR, ChartState, DailyContext,
                                    compute_chart_state, visible_bars)
from apex.hunter.contracts import HORIZONS_MINUTES
from apex.hunter.evidence import EvidenceClass, stamp
from apex.hunter.playbooks_v1 import match_hunter_001, match_hunter_002
from apex.hunter.relstrength import compute_relative_strength
from apex.hunter.scanner import scan

LEDGER = Path("results/hunter/forward_ledger.jsonl")


def extension_geometry(bars: pd.DataFrame, t_utc) -> dict:
    """Session extremes (LAST touch — the extension was still alive then),
    their ages, and direction-specific leg bases: min/max close in the 60m
    BEFORE the extreme's last touch. From the SAME visible frame ChartState
    uses (as-of inherited)."""
    f = visible_bars(bars, t_utc)
    empty = {"session_high": None, "session_low": None,
             "session_high_age_min": None, "session_low_age_min": None,
             "leg_start_up": None, "leg_start_down": None}
    if f.empty:
        return empty
    t = pd.Timestamp(t_utc)
    hi, lo = f["high"].astype(float), f["low"].astype(float)
    px, times = f["close"].astype(float), f["event_time_utc"]
    sh, sl = float(hi.max()), float(lo.min())
    hi_t = times[hi >= sh * (1 - 1e-9)].iloc[-1]        # last touch
    lo_t = times[lo <= sl * (1 + 1e-9)].iloc[-1]
    pre_hi = px[(times < hi_t) & (times >= hi_t - pd.Timedelta(minutes=60))]
    pre_lo = px[(times < lo_t) & (times >= lo_t - pd.Timedelta(minutes=60))]
    return {
        "session_high": sh, "session_low": sl,
        "session_high_age_min": float((t - (hi_t + BAR)).total_seconds() / 60),
        "session_low_age_min": float((t - (lo_t + BAR)).total_seconds() / 60),
        "leg_start_up": float(pre_hi.min()) if len(pre_hi) else None,
        "leg_start_down": float(pre_lo.max()) if len(pre_lo) else None}


def existing_decision_keys(date: str, ledger: Path = LEDGER) -> set:
    keys = set()
    if not ledger.exists():
        return keys
    for line in ledger.read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line).get("record", {})
        if r.get("kind") == "decision" and r.get("session_date") == date:
            keys.add((r["symbol"], r["playbook_id"], r["direction"]))
    return keys


def realized_decision_ids(ledger: Path = LEDGER) -> set:
    ids = set()
    if not ledger.exists():
        return ids
    for line in ledger.read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line).get("record", {})
        if r.get("kind") == "realization":
            ids.add(r["decision_id"])
    return ids


def unrealized_decisions(date: str, ledger: Path = LEDGER) -> list:
    done = realized_decision_ids(ledger)
    out = []
    if not ledger.exists():
        return out
    for line in ledger.read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line).get("record", {})
        if (r.get("kind") == "decision" and r.get("session_date") == date
                and r["decision_id"] not in done):
            out.append(r)
    return out


def decision_pass(t_utc, universe: dict, bars_by_symbol: dict,
                  contexts: dict, market_symbol: str = "SPY.US") -> tuple:
    """-> (scan_record, decision_records). Pure: caller appends to ledger."""
    t = pd.Timestamp(t_utc)
    date = str(t.tz_convert("America/New_York").date())
    market_bars = bars_by_symbol.get(market_symbol)
    market_cs = (compute_chart_state(
        market_symbol, market_bars, t,
        contexts.get(market_symbol,
                     DailyContext(symbol=market_symbol, as_of_date=date)))
        if market_bars is not None else None)

    etf_cs = {}
    for sym, b in bars_by_symbol.items():
        if sym.endswith(".US") and sym not in universe["symbols"]:
            cs = compute_chart_state(
                sym, b, t, contexts.get(sym, DailyContext(symbol=sym,
                                                          as_of_date=date)))
            if cs is not None:
                etf_cs[sym] = cs

    # target states
    cs_by_symbol, sector_of = {}, {}
    for sym, meta in universe["symbols"].items():
        b = bars_by_symbol.get(sym)
        if b is None:
            continue
        ctx = contexts.get(sym, DailyContext(symbol=sym, as_of_date=date))
        cs = compute_chart_state(sym, b, t, ctx)
        if cs is not None:
            cs_by_symbol[sym] = cs
            sector_of[sym] = meta.get("sector")

    pairs, rs_by_symbol = [], {}
    if market_cs is not None:
        day_excess = tuple(
            (c.day_return - market_cs.day_return)
            if c.day_return is not None and market_cs.day_return is not None
            else None for c in cs_by_symbol.values())
        for sym, cs in cs_by_symbol.items():
            setf = universe["symbols"][sym].get("sector_etf")
            peers = tuple(c for s2, c in cs_by_symbol.items()
                          if s2 != sym and sector_of.get(s2) == sector_of.get(sym))
            rs = compute_relative_strength(
                cs, market_cs, etf_cs.get(setf), peers, day_excess)
            rs_by_symbol[sym] = rs
            pairs.append((cs, rs))

    result = scan(str(t), len(universe["symbols"]), pairs)
    scan_record = stamp(result.as_record(),
                        EvidenceClass.EODHD_FORWARD_OBSERVATION)
    scan_record["kind"] = "scan"
    scan_record["session_date"] = date
    scan_record["universe_limitation"] = universe.get("universe_limitation")

    births = birthlib.load_births()
    seen = existing_decision_keys(date)
    decisions = []
    for sym, _sigs, _rv in result.watchlist:
        cs, rs = cs_by_symbol[sym], rs_by_symbol[sym]
        geo = extension_geometry(bars_by_symbol[sym], t)
        for m in (match_hunter_001(cs, rs, market_cs),
                  match_hunter_002(cs, rs, geo)):
            if m is None:
                continue
            key = (sym, m["playbook_id"], m["direction"])
            if key in seen:
                continue
            seen.add(key)
            # deps of THIS forecast: shared kinds + its OWN playbook only —
            # a later playbook's birth never disqualifies an older one's
            # forecast, and an unborn playbook fails the required-kind check
            deps = {n: b for n, b in births.items()
                    if b["dependency_kind"] != "playbook"
                    or n == m["playbook_id"]}
            eligibility, reasons = birthlib.forward_eligibility(t, deps)
            bstamp = birthlib.birth_stamp(deps)
            rec = stamp({
                "kind": "decision",
                "decision_id": uuid.uuid4().hex[:16],
                "session_date": date, "t_utc": str(t),
                "symbol": sym, **m,
                "horizons_minutes": list(HORIZONS_MINUTES),
                "chart_state": cs.as_record(),
                "relative_strength": rs.as_record(),
                "market_state": (market_cs.as_record()
                                 if market_cs else None),
                "forward_eligibility": eligibility,
                "eligibility_reasons": list(reasons),
                **bstamp,
            }, EvidenceClass.EODHD_FORWARD_OBSERVATION)
            decisions.append(rec)
    return scan_record, decisions


def resolve_decision(decision: dict, day_bars: pd.DataFrame) -> dict:
    """MECHANICAL_DETERMINISTIC outcome measurement from full-session bars.
    Forward window starts strictly AFTER formation time."""
    t0 = pd.Timestamp(decision["t_utc"])
    f = day_bars[day_bars["event_time_utc"] + BAR > t0].reset_index(drop=True)
    entry = float(decision["entry"])
    sign = 1.0 if decision["direction"] == "LONG" else -1.0
    stop, target = float(decision["stop"]), float(decision["target"])
    out = {"kind": "realization", "decision_id": decision["decision_id"],
           "session_date": decision["session_date"],
           "playbook_id": decision["playbook_id"],
           "symbol": decision["symbol"], "direction": decision["direction"],
           "label": "MECHANICAL_DETERMINISTIC",
           "forward_bars": int(len(f))}
    if f.empty:
        out["resolvable"] = False
        return stamp(out, EvidenceClass.EODHD_FORWARD_OBSERVATION)
    px = f["close"].astype(float)
    hi, lo = f["high"].astype(float), f["low"].astype(float)
    times = f["event_time_utc"]
    for h in HORIZONS_MINUTES:
        m = times + BAR <= t0 + pd.Timedelta(minutes=h)
        sub = f[m]
        if sub.empty:
            out[f"ret_{h}m"] = None
            continue
        c = float(sub["close"].iloc[-1])
        out[f"ret_{h}m"] = round(sign * (c / entry - 1), 6)
        fav = (sub["high"].max() if sign > 0 else sub["low"].min())
        adv = (sub["low"].min() if sign > 0 else sub["high"].max())
        out[f"mfe_{h}m"] = round(sign * (float(fav) / entry - 1), 6)
        out[f"mae_{h}m"] = round(sign * (float(adv) / entry - 1), 6)
        out[f"truncated_{h}m"] = bool(
            times.iloc[-1] + BAR < t0 + pd.Timedelta(minutes=h))
    if sign > 0:
        stop_hits = f.index[lo <= stop]
        tgt_hits = f.index[hi >= target]
    else:
        stop_hits = f.index[hi >= stop]
        tgt_hits = f.index[lo <= target]
    s_i = int(stop_hits[0]) if len(stop_hits) else None
    t_i = int(tgt_hits[0]) if len(tgt_hits) else None
    out["stop_hit"] = s_i is not None
    out["target_hit"] = t_i is not None
    out["target_before_stop"] = (t_i is not None
                                 and (s_i is None or t_i < s_i))
    out["stop_before_target"] = (s_i is not None
                                 and (t_i is None or s_i <= t_i))
    out["same_bar_ambiguous"] = (s_i is not None and t_i is not None
                                 and s_i == t_i)
    out["closing_return"] = round(sign * (float(px.iloc[-1]) / entry - 1), 6)
    out["resolvable"] = True
    return stamp(out, EvidenceClass.EODHD_FORWARD_OBSERVATION)
