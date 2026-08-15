#!/usr/bin/env python
"""THE FORWARD CLOCK: prospective market-state records, frozen before
outcomes exist.

    python scripts/hunter_forward_clock.py        # one snapshot (or fast exit)

Runs every 15 minutes via launchd; exits immediately outside REGULAR
session. Each snapshot is a chained EODHD_FORWARD_OBSERVATION in
results/hunter/forward_ledger.jsonl -- state only in v1 (P1B adds decisions
and realizations). Every clean future observation not recorded today can
never be recreated with the same epistemic purity later; that is why this
script exists before the Hunter is finished.

Cost: ~8 EODHD requests per snapshot, ~27 snapshots/session ≈ 220/day of a
100k/day quota. Token from Keychain via wrapper; never logged.
"""
from __future__ import annotations

import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

_S = Path(__file__).resolve().parent
sys.path.insert(0, str(_S.parent)); sys.path.insert(0, str(_S))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from nightly_pull import _chain_append  # noqa: E402

from apex.hunter.evidence import EvidenceClass, stamp  # noqa: E402
from apex.intraday.eodhd import (  # noqa: E402
    QuotaGovernor, fetch_intraday_chunk, normalize_rows,
)
from apex.intraday.sessions import Session, classify  # noqa: E402

LEDGER = Path("results/hunter/forward_ledger.jsonl")
PROTOCOL_HASH_FILE = Path("HUNTER-FORWARD-PROTOCOL.md")
INDEXES = ("SPY.US", "QQQ.US", "IWM.US")
SECTORS = ("XLK.US", "XLF.US", "XLE.US", "XLV.US", "XLI.US")
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
    return hashlib.sha256(PROTOCOL_HASH_FILE.read_bytes()).hexdigest()[:16]


def _day_state(sym: str, gov: QuotaGovernor, today: str) -> dict | None:
    rows, _ = fetch_intraday_chunk(sym, today, today, gov)
    f = normalize_rows(rows, sym)
    if f.empty:
        return None
    reg = f[f["event_time_utc"].map(lambda t: classify(t) is Session.REGULAR)]
    if reg.empty:
        return None
    px = reg["close"].astype(float)
    vol = reg["volume"].astype(float)
    vwap = float((px * vol).sum() / max(vol.sum(), 1))
    r = px.pct_change().dropna()
    last_t = reg["event_time_utc"].iloc[-1]
    return {"symbol": sym,
            "day_return": round(float(px.iloc[-1] / px.iloc[0] - 1), 5),
            "above_vwap": bool(px.iloc[-1] > vwap),
            "realized_vol_ann": round(float(r.std() * np.sqrt(390 * 252)), 4),
            "cum_volume": float(vol.sum()),
            "last_bar_utc": str(last_t),
            "minutes_recorded": int(len(reg))}


def main() -> int:
    now = pd.Timestamp.now(tz="UTC")
    if classify(now) is not Session.REGULAR:
        return 0                                            # fast, silent exit

    # yesterday's fetch cache would poison "today"; the recorder always asks
    # for today's date and the cache key includes it, so intraday snapshots
    # within a day DO reuse the growing cached file only if identical --
    # therefore bypass cache by removing today's chunk before fetching.
    gov = QuotaGovernor()
    today = str(now.date())
    from apex.intraday.eodhd import cache_path
    states, health = [], []
    for sym in (*INDEXES, *SECTORS):
        cp = cache_path(sym, today, today)
        if cp.exists():
            cp.unlink()                                     # intraday: refetch
        try:
            s = _day_state(sym, gov, today)
            if s is None:
                health.append(f"{sym}: no regular-session bars yet")
            else:
                age_min = (now - pd.Timestamp(s["last_bar_utc"])).total_seconds() / 60
                if age_min > STALE_AFTER_MIN:
                    health.append(f"{sym}: last bar {age_min:.0f}m old (STALE)")
                states.append(s)
        except Exception as e:                              # noqa: BLE001
            health.append(f"{sym}: fetch failed ({type(e).__name__})")

    if not states:
        record = stamp({"kind": "forward_state", "timestamp_utc": str(now),
                        "session": "REGULAR",
                        "data_health": ["NO DATA: " + "; ".join(health)],
                        "usable": False},
                       EvidenceClass.EODHD_FORWARD_OBSERVATION)
    else:
        idx = [s for s in states if s["symbol"] in INDEXES]
        sec = [s for s in states if s["symbol"] in SECTORS]
        rets = [s["day_return"] for s in sec]
        record = stamp({
            "kind": "forward_state", "timestamp_utc": str(now),
            "session": "REGULAR",
            "indexes": {s["symbol"]: s for s in idx},
            "sector_dispersion": round(float(np.std(rets)), 5) if rets else None,
            "breadth_proxy_crude": (round(float(np.mean([r > 0 for r in rets])), 2)
                                    if rets else None),
            "market_above_vwap": ([s for s in idx if s["symbol"] == "SPY.US"]
                                  or [{}])[0].get("above_vwap"),
            "data_health": health or ["OK"],
            "usable": len(health) == 0,
            "quota_used_this_snapshot": gov.used,
        }, EvidenceClass.EODHD_FORWARD_OBSERVATION)

    record["code_commit"] = _git_sha()
    record["protocol_hash"] = _protocol_hash()
    entry = _chain_append(LEDGER, record)
    print(f"forward state recorded {entry['entry_hash'][:12]} "
          f"usable={record.get('usable')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
