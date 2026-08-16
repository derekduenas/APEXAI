#!/usr/bin/env python
"""FASTWATCH — the latency-tax meter. NOT Epoch 1.

    python scripts/fastwatch.py [--minutes 390] [--cadence 60]

The official experiment observes every 15 minutes, frozen. FastWatch
observes the BOUNDED watchlist roughly every minute and records when
relevant geometry first became visible — so after Monday we can answer:

    "The market showed this at 09:48. Official Epoch 1 saw it at 10:00.
     What did those 12 minutes cost?"

STRUCTURAL SAFETY, not promises:

  * QuotaGovernor(purpose="LAB"): FastWatch spends from the lab budget
    and CANNOT touch the 35k forward reserve — the same enforcement
    LAB-07 gave the replay campaign. If the lab budget is gone, FastWatch
    pauses; the official clock is never the one that starves.
  * Reads the official ledger for its symbol list; watches at most
    MAX_SYMBOLS. It never scans the 150-name universe.
  * Writes to its OWN ledger with decision_power NONE_OBSERVATIONAL_EPOCH1
    and kind names no official reader consumes. It cannot mint decisions,
    matches, or eligibility.
  * Conditions it notices are recorded as FASTWATCH_CONDITION_OBSERVED —
    deliberately not a Hunter match, because the frozen playbook
    evaluation is the only thing allowed to call something a match.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

_S = Path(__file__).resolve().parent
sys.path.insert(0, str(_S.parent)); sys.path.insert(0, str(_S))

import pandas as pd  # noqa: E402

OBSERVATIONAL = "NONE_OBSERVATIONAL_EPOCH1"
OFFICIAL_LEDGER = Path("results/hunter/forward_ledger.jsonl")
FW_LEDGER = Path("results/hunter/fastwatch_ledger.jsonl")
MAX_SYMBOLS = 8              # bounded: candidates + strongest watchlist
BENCH = "SPY.US"


def _append(rec: dict) -> None:
    from nightly_pull import _chain_append
    FW_LEDGER.parent.mkdir(parents=True, exist_ok=True)
    _chain_append(FW_LEDGER, {**rec, "decision_power": OBSERVATIONAL})


def official_state() -> dict:
    """Symbols to watch and the last official tick, from the archive."""
    if not OFFICIAL_LEDGER.exists():
        return {"symbols": [], "last_official_tick": None}
    scans, decisions = [], []
    for line in OFFICIAL_LEDGER.read_text().splitlines():
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r.get("kind") == "scan":
            scans.append(r)
        elif r.get("kind") == "decision" and \
                not str(r.get("playbook_id", "")).startswith("BASELINE-"):
            decisions.append(r)
    from apex.hunter.microscope import select_targets
    targets = select_targets(decisions=decisions, scans=scans[-4:])
    return {"symbols": [t.symbol for t in targets][:MAX_SYMBOLS],
            "last_official_tick": scans[-1].get("t_utc") if scans else None}


def observe_once(gov, symbols: list, last_official) -> dict:
    """One FastWatch sweep: latest 1m bars per symbol, light structure,
    elapsed time since the official clock last looked."""
    from apex.intraday.eodhd import fetch_intraday_chunk, normalize_rows
    now = pd.Timestamp.now(tz="UTC")
    day = str(now.date())
    out = {"observed": 0, "paused_quota": 0}
    for sym in symbols:
        try:
            rows, _src = fetch_intraday_chunk(sym, day, day, gov)
        except Exception as e:                              # noqa: BLE001
            _append({"kind": "fastwatch_observation", "symbol": sym,
                     "observed_at": str(now), "status":
                     f"FETCH_{type(e).__name__}"})
            continue
        if rows is None:
            out["paused_quota"] += 1
            _append({"kind": "fastwatch_observation", "symbol": sym,
                     "observed_at": str(now),
                     "status": "PAUSED_LAB_QUOTA",
                     "note": "the forward reserve is untouchable; "
                             "FastWatch yields before the official clock "
                             "ever could"})
            continue
        f = normalize_rows(rows, sym)
        if not len(f):
            _append({"kind": "fastwatch_observation", "symbol": sym,
                     "observed_at": str(now), "status": "NO_BARS"})
            continue
        last = f.iloc[-1]
        px = f["close"].astype(float)
        vwap = float((f["close"] * f["volume"]).sum()
                     / max(float(f["volume"].sum()), 1e-9))
        elapsed = (None if last_official is None else
                   round((now - pd.Timestamp(last_official)).total_seconds(), 1))
        rec = {
            "kind": "fastwatch_observation", "symbol": sym,
            "observed_at": str(now),
            "last_market_timestamp": str(last["event_time_utc"]),
            "price": float(last["close"]),
            "session_high": float(f["high"].max()),
            "session_low": float(f["low"].min()),
            "above_vwap": bool(float(last["close"]) > vwap),
            "vwap": round(vwap, 4),
            "official_last_seen_at": (str(last_official)
                                      if last_official else None),
            "elapsed_since_official_tick_s": elapsed,
            "status": "OK",
        }
        # light geometry flags: OBSERVED conditions, never matches
        conditions = []
        if float(last["close"]) >= float(px.max()):
            conditions.append("SESSION_HIGH_TOUCH")
        if float(last["close"]) > vwap and float(px.iloc[0]) < vwap:
            conditions.append("VWAP_RECLAIM_SHAPE")
        if conditions:
            rec["fastwatch_condition_observed"] = conditions
            rec["condition_note"] = ("FASTWATCH_CONDITION_OBSERVED is not "
                                     "a Hunter match; the frozen playbook "
                                     "is the only judge of matches")
        _append(rec)
        out["observed"] += 1
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=390)
    ap.add_argument("--cadence", type=float, default=60)
    a = ap.parse_args()
    from apex.intraday.eodhd import QuotaGovernor
    gov = QuotaGovernor(daily_budget=20_000, purpose="LAB")
    print(f"FASTWATCH — observational, LAB-governed, decision_power NONE")
    t_end = time.time() + a.minutes * 60
    while time.time() < t_end:
        st = official_state()
        symbols = st["symbols"] or [BENCH]     # quiet tape: watch the bench
        r = observe_once(gov, symbols, st["last_official_tick"])
        print(f"{pd.Timestamp.now(tz='UTC'):%H:%M:%S} watched "
              f"{len(symbols)} observed {r['observed']} "
              f"quota_paused {r['paused_quota']} used {gov.used}u")
        if r["paused_quota"] == len(symbols):
            print("lab quota exhausted — sleeping 15m (reserve untouched)")
            time.sleep(900)
        else:
            time.sleep(a.cadence)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
