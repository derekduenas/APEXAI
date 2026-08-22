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
HEALTH_ARTIFACT = Path("results/hunter/fastwatch_health.json")
FASTWATCH_LAB_BUDGET = 12_000   # units; see allocation note in main()
MAX_SYMBOLS = 8              # bounded: candidates + strongest watchlist
BENCH = "SPY.US"

# PID existence is not health (2026-08-17: Frontier ran for ~3h with a
# live PID and zero completed cycles). These are the measured states a
# consumer must actually check.
HEALTHY, DEGRADED, STALLED, FAILED = "HEALTHY", "DEGRADED", "STALLED", "FAILED"
STALL_AFTER_S = 180          # 3x the default 60s cadence


class _Health:
    """First-class, durable process/cycle state -- written every cycle,
    atomic (os.replace), never dependent on buffered stdout surviving a
    crash to be legible."""

    def __init__(self):
        self.process_status = "STARTING"
        self.last_cycle_start = None
        self.last_cycle_complete = None
        self.last_successful_cycle = None
        self.cycle_duration_s = None
        self.last_input_time = None       # newest official tick consumed
        self.last_output_time = None      # newest fastwatch record written
        self.records_written = 0
        self.error_count = 0
        self.consecutive_failures = 0
        self.watchlist_errors_total = 0

    def cycle_start(self):
        self.last_cycle_start = str(pd.Timestamp.now(tz="UTC"))
        self._t0 = time.monotonic()

    def cycle_ok(self, *, input_time=None, n_written=0, watchlist_errors=0):
        now = str(pd.Timestamp.now(tz="UTC"))
        self.last_cycle_complete = now
        self.last_successful_cycle = now
        self.cycle_duration_s = round(time.monotonic() - self._t0, 3)
        self.last_input_time = input_time
        if n_written:
            self.last_output_time = now
        self.records_written += n_written
        self.consecutive_failures = 0
        self.watchlist_errors_total += watchlist_errors
        self.process_status = "RUNNING"

    def cycle_failed(self, exc: Exception):
        self.last_cycle_complete = str(pd.Timestamp.now(tz="UTC"))
        self.error_count += 1
        self.consecutive_failures += 1
        self.process_status = "RUNNING"   # the LOOP survived; see progress_status

    def progress_status(self) -> str:
        if self.last_successful_cycle is None:
            return STALLED if self.consecutive_failures > 0 else DEGRADED
        age = (pd.Timestamp.now(tz="UTC")
              - pd.Timestamp(self.last_successful_cycle)).total_seconds()
        if self.consecutive_failures >= 5:
            return FAILED
        if age > STALL_AFTER_S:
            return STALLED
        if self.consecutive_failures > 0:
            return DEGRADED
        return HEALTHY

    def as_record(self, *, coverage: dict | None = None) -> dict:
        return {"kind": "fastwatch_health",
               "process_status": self.process_status,
               "progress_status": self.progress_status(),
               "last_cycle_start": self.last_cycle_start,
               "last_cycle_complete": self.last_cycle_complete,
               "last_successful_cycle": self.last_successful_cycle,
               "cycle_duration_s": self.cycle_duration_s,
               "last_input_time": self.last_input_time,
               "last_output_time": self.last_output_time,
               "records_written": self.records_written,
               "error_count": self.error_count,
               "consecutive_failures": self.consecutive_failures,
               "watchlist_errors_total": self.watchlist_errors_total,
               "coverage": coverage,
               "measured_at_utc": str(pd.Timestamp.now(tz="UTC"))}


def write_health(health: "_Health", *, coverage: dict | None = None) -> None:
    import os
    HEALTH_ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    tmp = HEALTH_ARTIFACT.with_suffix(".tmp")
    tmp.write_text(json.dumps(health.as_record(coverage=coverage), indent=1,
                              default=str))
    os.replace(tmp, HEALTH_ARTIFACT)


def coverage_report(observed_symbols: list) -> dict:
    """COVERAGE HONESTY: FastWatch watches a BOUNDED subset (MAX_SYMBOLS)
    of the frozen scan universe, never the whole thing. This must never
    read as universe-wide FastWatch."""
    import json as _json
    eligible: set = set()
    uni = sorted(Path("results/hunter").glob("scan_universe_*.json"))
    if uni:
        try:
            eligible = set(_json.loads(uni[-1].read_text())
                          .get("symbols", {}))
        except _json.JSONDecodeError:
            pass
    observed = {s.replace(".US", "") for s in observed_symbols}
    unobserved = eligible - observed
    return {
        "eligible_symbols": len(eligible),
        "observed_symbols": sorted(observed),
        "observed_symbols_count": len(observed),
        "unobserved_symbols_count": len(unobserved),
        "realtime_coverage_fraction": (round(len(observed) / len(eligible), 4)
                                       if eligible else None),
        "note": "FastWatch watches a BOUNDED subset (candidates + "
               "strongest watchlist), never the full scan universe"}


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
    from apex.hunter.watchlist import record_parse_errors
    targets, errors = select_targets(decisions=decisions, scans=scans[-4:])
    # THE ROOT CAUSE OF THE 2026-08-17 CRASH, fixed: a malformed
    # watchlist entry is now skipped and durably recorded here, never a
    # raised KeyError that kills this whole process on the very first
    # real (non-empty, non-synthetic) watchlist.
    record_parse_errors(errors, component="fastwatch.official_state",
                        input_reference=(scans[-1].get("t_utc")
                                         if scans else None))
    return {"symbols": [t.symbol for t in targets][:MAX_SYMBOLS],
            "last_official_tick": scans[-1].get("t_utc") if scans else None,
            "watchlist_errors": len(errors)}


def observe_once(gov, symbols: list, last_official) -> dict:
    """One FastWatch sweep: latest 1m bars per symbol, light structure,
    elapsed time since the official clock last looked."""
    from apex.intraday.eodhd import fetch_intraday_chunk, normalize_rows
    from apex.intraday.alpaca_fabric import (
        as_normalize_rows_shape as _alpaca_live_bars)
    from apex.intraday.equity_fabric import (
        as_normalize_rows_shape as _live_bars)
    now = pd.Timestamp.now(tz="UTC")
    day = str(now.date())
    out = {"observed": 0, "paused_quota": 0}
    for sym in symbols:
        # ARM-TUESDAY ROLE ORDER: PRIMARY_BROAD_SENSOR (Alpaca, full
        # 164-symbol universe) tried first, SECONDARY_DEEP_REALTIME_
        # SENSOR (EODHD, ~50-name allocation) second -- neither silently
        # replaces the other. The Intraday Historical endpoint is not a
        # live source and is only consulted as last-resort fallback.
        f = _alpaca_live_bars(sym, day)
        data_source = "ALPACA_WEBSOCKET_SIP_V1" if len(f) else None
        if not len(f):
            f = _live_bars(sym, day)
            data_source = "EODHD_WEBSOCKET_REALTIME" if len(f) else None
        if not len(f):
            try:
                rows, _src = fetch_intraday_chunk(sym, day, day, gov)
            except Exception as e:                          # noqa: BLE001
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
                                 "FastWatch yields before the official "
                                 "clock ever could"})
                continue
            f = normalize_rows(rows, sym)
            data_source = "EODHD_INTRADAY_HISTORICAL"
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
            "observed_at": str(now), "data_source": data_source,
            "last_market_timestamp": str(last["event_time_utc"]),
            "price": float(last["close"]),
            "session_high": float(f["high"].max()),
            "session_low": float(f["low"].min()),
            "above_vwap": bool(float(last["close"]) > vwap),
            "vwap": round(vwap, 4),
            "official_last_seen_at": (str(last_official)
                                      if last_official else None),
            "elapsed_since_official_tick_s": elapsed,
            # LATENCY HONESTY: this measures CANDIDATE_EVOLUTION_LATENCY —
            # what happened to names ALREADY on APEX's radar between
            # official ticks. It is NOT universe discovery latency: a
            # 1-minute 150-symbol shadow scanner does not exist, so a
            # stock never on the watchlist was never seen here.
            "latency_kind": "CANDIDATE_EVOLUTION_LATENCY",
            "universe_discovery_latency": "NOT_MEASURABLE_NO_BROAD_"
                                          "FAST_SCANNER",
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
    # LAB POOL ALLOCATION (operator, 2026-08-16). The shared ceiling is
    # 65k (limit - forward reserve). Declared consumers:
    #     replay    45,000  (LAB_TOTAL_BUDGET in hunter_replay_fast)
    #     fastwatch 12,000  (here)
    #     cushion    8,000  (unallocated, deliberately)
    # LAB-07 protects the FORWARD reserve; these local budgets keep the
    # lab consumers from starving EACH OTHER on the first day cadence is
    # being measured. Enforced twice: locally here, and by the shared
    # ledger for the pool total.
    gov = QuotaGovernor(daily_budget=FASTWATCH_LAB_BUDGET, purpose="LAB")
    print(f"FASTWATCH — observational, LAB-governed, decision_power NONE")
    t_end = time.time() + a.minutes * 60
    health = _Health()
    while time.time() < t_end:
        health.cycle_start()
        try:
            st = official_state()
            symbols = st["symbols"] or [BENCH]  # quiet tape: watch the bench
            r = observe_once(gov, symbols, st["last_official_tick"])
            print(f"{pd.Timestamp.now(tz='UTC'):%H:%M:%S} watched "
                  f"{len(symbols)} observed {r['observed']} "
                  f"quota_paused {r['paused_quota']} used {gov.used}u")
            health.cycle_ok(input_time=st["last_official_tick"],
                            n_written=r["observed"],
                            watchlist_errors=st.get("watchlist_errors", 0))
            write_health(health, coverage=coverage_report(symbols))
        except Exception as e:                              # noqa: BLE001
            # PROCESS SURVIVAL: one bad cycle is recorded, never fatal --
            # but recorded DURABLY (health.as_record + write_health), not
            # only printed into a pipe that may never flush before the
            # loop's next sleep (the exact way the 2026-08-17 Frontier
            # stall hid for ~3 hours).
            health.cycle_failed(e)
            print(f"{pd.Timestamp.now(tz='UTC'):%H:%M:%S} CYCLE FAILED "
                  f"{type(e).__name__}: {e} "
                  f"(consecutive={health.consecutive_failures})")
            write_health(health)
            symbols = [BENCH]
            r = {"paused_quota": 0}
        if r.get("paused_quota") == len(symbols) and symbols:
            print("lab quota exhausted — sleeping 15m (reserve untouched)")
            time.sleep(900)
        else:
            time.sleep(a.cadence)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
