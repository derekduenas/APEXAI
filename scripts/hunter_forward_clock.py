#!/usr/bin/env python
"""THE FORWARD CLOCK: prospective market-state, scan, decision, and
realization records — frozen before outcomes exist.

    python scripts/hunter_forward_clock.py        # one tick (or fast exit)

Every 15 minutes via launchd. REGULAR session: market-state record, then
the Hunter perception pass (ChartState -> RelativeStrength -> abnormality
scan -> playbook matches -> DECISION records with dependency birth stamps
and mechanical forward-eligibility). POSTMARKET: deterministic realization
of today's unresolved decisions. Otherwise: immediate silent exit.

Monday's archive starts as clean prospective DATA; a playbook claims those
observations as forward EVIDENCE only after its own birth timestamp — the
eligibility verdict in each decision record is computed, never judged.

Cost: ~170 requests/tick during REGULAR (8 ETFs + ~150 universe names +
11 sector ETFs), ~27 ticks/session, one-time ~170 context fetches daily
=> ~5k/day of a 100k/day quota. Token from Keychain via wrapper; never
logged.
"""
from __future__ import annotations

import dataclasses
import subprocess
import sys
from pathlib import Path

_S = Path(__file__).resolve().parent
sys.path.insert(0, str(_S.parent)); sys.path.insert(0, str(_S))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from nightly_pull import _chain_append  # noqa: E402

from apex.hunter.context_builder import (  # noqa: E402
    SECTOR_ETF, build_scan_universe, load_or_build_contexts,
)
from apex.hunter.evidence import EvidenceClass, stamp  # noqa: E402
from apex.hunter.forward_pass import (  # noqa: E402
    decision_pass, resolve_decision, unrealized_decisions,
)
from apex.intraday.eodhd import (  # noqa: E402
    QuotaGovernor, cache_path, fetch_intraday_chunk, normalize_rows,
)
from apex.intraday.sessions import Session, classify  # noqa: E402

LEDGER = Path("results/hunter/forward_ledger.jsonl")
PROTOCOL_FILE = Path("HUNTER-FORWARD-PROTOCOL.md")
INDEXES = ("SPY.US", "QQQ.US", "IWM.US")
STALE_AFTER_MIN = 10


def _git_sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True,
                              cwd=_S.parent).stdout.strip()
    except Exception:                                       # noqa: BLE001
        return "unknown"


def _protocol_hash() -> str:
    import hashlib
    return hashlib.sha256(PROTOCOL_FILE.read_bytes()).hexdigest()[:16]


def _fetch_today(sym: str, gov: QuotaGovernor, today: str,
                 bust_cache: bool) -> pd.DataFrame:
    if bust_cache:
        cp = cache_path(sym, today, today)
        if cp.exists():
            cp.unlink()                             # intraday: refetch fresh
    rows, _ = fetch_intraday_chunk(sym, today, today, gov)
    return normalize_rows(rows, sym)


def _etf_state(sym: str, f: pd.DataFrame, now) -> dict | None:
    reg = f[f["event_time_utc"].map(lambda t: classify(t) is Session.REGULAR)]
    if reg.empty:
        return None
    px = reg["close"].astype(float)
    vol = reg["volume"].astype(float)
    vwap = float((px * vol).sum() / max(vol.sum(), 1))
    r = px.pct_change().dropna()
    return {"symbol": sym,
            "day_return": round(float(px.iloc[-1] / px.iloc[0] - 1), 5),
            "above_vwap": bool(px.iloc[-1] > vwap),
            "realized_vol_ann": round(float(r.std() * np.sqrt(390 * 252)), 4),
            "cum_volume": float(vol.sum()),
            "last_bar_utc": str(reg["event_time_utc"].iloc[-1]),
            "minutes_recorded": int(len(reg))}


def _premarket_levels(f: pd.DataFrame) -> tuple:
    pre = f[f["event_time_utc"].map(
        lambda t: classify(t) is Session.PREMARKET)]
    if pre.empty:
        return None, None
    return float(pre["high"].max()), float(pre["low"].min())


def _state_snapshot(now, gov, today, bars_etf) -> dict:
    sector_syms = tuple(sorted(set(SECTOR_ETF.values())))
    states, health = [], []
    for sym in (*INDEXES, *sector_syms):
        f = bars_etf.get(sym)
        if f is None or f.empty:
            health.append(f"{sym}: no bars")
            continue
        s = _etf_state(sym, f, now)
        if s is None:
            health.append(f"{sym}: no regular-session bars yet")
            continue
        age = (now - pd.Timestamp(s["last_bar_utc"])).total_seconds() / 60
        if age > STALE_AFTER_MIN:
            health.append(f"{sym}: last bar {age:.0f}m old (STALE)")
        states.append(s)
    if not states:
        return stamp({"kind": "forward_state", "timestamp_utc": str(now),
                      "session": "REGULAR",
                      "data_health": ["NO DATA: " + "; ".join(health)],
                      "usable": False},
                     EvidenceClass.EODHD_FORWARD_OBSERVATION)
    idx = [s for s in states if s["symbol"] in INDEXES]
    sec = [s for s in states if s["symbol"] not in INDEXES]
    rets = [s["day_return"] for s in sec]
    return stamp({
        "kind": "forward_state", "timestamp_utc": str(now),
        "session": "REGULAR",
        "indexes": {s["symbol"]: s for s in idx},
        "sectors": {s["symbol"]: s["day_return"] for s in sec},
        "sector_dispersion": round(float(np.std(rets)), 5) if rets else None,
        "breadth_proxy_crude": (round(float(np.mean([r > 0 for r in rets])), 2)
                                if rets else None),
        "market_above_vwap": ([s for s in idx if s["symbol"] == "SPY.US"]
                              or [{}])[0].get("above_vwap"),
        "data_health": health or ["OK"],
        "usable": len(health) == 0,
        "quota_used_this_snapshot": gov.used,
    }, EvidenceClass.EODHD_FORWARD_OBSERVATION)


def _finalize(record: dict) -> dict:
    record["code_commit"] = _git_sha()
    record["protocol_hash"] = _protocol_hash()
    return _chain_append(LEDGER, record)


def _regular_tick(now, gov, today) -> None:
    sector_syms = tuple(sorted(set(SECTOR_ETF.values())))
    bars: dict = {}
    for sym in (*INDEXES, *sector_syms):
        try:
            bars[sym] = _fetch_today(sym, gov, today, bust_cache=True)
        except Exception as e:                              # noqa: BLE001
            print(f"fetch {sym}: {type(e).__name__}")
    entry = _finalize(_state_snapshot(now, gov, today, bars))
    print(f"forward state {entry['entry_hash'][:12]}")

    # Hunter perception pass — isolated so state recording never dies of it
    try:
        universe = build_scan_universe(today)
        contexts = load_or_build_contexts(
            universe["symbols"], today, gov,
            extra_symbols=(*INDEXES, *sector_syms))
        for sym in universe["symbols"]:
            try:
                f = _fetch_today(f"{sym}.US", gov, today, bust_cache=True)
                f["provider_symbol"] = sym
                bars[sym] = f
                pm_hi, pm_lo = _premarket_levels(f)
                if sym in contexts and pm_hi is not None:
                    contexts[sym] = dataclasses.replace(
                        contexts[sym], premarket_high=pm_hi,
                        premarket_low=pm_lo)
            except Exception as e:                          # noqa: BLE001
                print(f"fetch {sym}: {type(e).__name__}")
        scan_record, decisions = decision_pass(now, universe, bars, contexts)
        scan_record["quota_used_cumulative"] = gov.used
        _finalize(scan_record)
        for d in decisions:
            e = _finalize(d)
            print(f"DECISION {d['symbol']} {d['playbook_id']} "
                  f"{d['direction']} {d['forward_eligibility']} "
                  f"{e['entry_hash'][:12]}")
        print(f"scan: {scan_record['states_computed']} states, "
              f"{scan_record['abnormal']} abnormal, "
              f"{len(decisions)} decisions")
    except Exception as e:                                  # noqa: BLE001
        print(f"perception pass failed: {type(e).__name__}: {e}")


def _post_tick(now, gov, today) -> None:
    pending = unrealized_decisions(today)
    if not pending:
        return
    day_bars: dict = {}
    for d in pending:
        sym = d["symbol"]
        if sym not in day_bars:
            try:
                day_bars[sym] = _fetch_today(f"{sym}.US", gov, today,
                                             bust_cache=True)
            except Exception as e:                          # noqa: BLE001
                print(f"resolve fetch {sym}: {type(e).__name__}")
                continue
        rec = resolve_decision(d, day_bars[sym])
        e = _finalize(rec)
        print(f"REALIZATION {d['decision_id']} {sym} "
              f"tbs={rec.get('target_before_stop')} {e['entry_hash'][:12]}")
    # the day self-reports: scoreboard + funnel diagnostics (read-only)
    try:
        from hunter_scoreboard import main as scoreboard_main
        scoreboard_main()
    except Exception as e:                                  # noqa: BLE001
        print(f"scoreboard failed: {type(e).__name__}: {e}")


def main() -> int:
    now = pd.Timestamp.now(tz="UTC")
    sess = classify(now)
    today = str(now.tz_convert("America/New_York").date())
    if sess is Session.REGULAR:
        _regular_tick(now, QuotaGovernor(), today)
    elif sess is Session.POSTMARKET:
        _post_tick(now, QuotaGovernor(), today)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
