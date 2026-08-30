"""LAYER A — MOVEMENT/TOLL. Model-free economic-terrain validation.

    DOES THIS UNIVERSE CONTAIN ENOUGH MOVEMENT RELATIVE TO REAL
    EXECUTABLE FRICTION TO MAKE INTRADAY ALPHA PLAUSIBLE?

No model, no strategy, no threshold. For a DETERMINISTIC pre-declared
sample of (name, day, time-of-day) points across the PIT high-liquidity
universe and the ETF comparator:

    MOVEMENT  |forward return| at the registered 15m / 60m horizons,
              from 1m bars fetched around the point
    TOLL      the observed SIP NBBO quoted spread at the point
              (median of the quotes in the prior minute) -- friction
              provenance OBSERVED_SIP_NBBO; no quotes => NOT_ESTIMABLE,
              never silently estimated

The decision variable is the FULL RATIO DISTRIBUTION (median/75/90/95)
-- APEX's advantage is selectivity, so the upper tail matters more
than the middle -- plus tail integrity (is the tail just earnings
shocks?) and the spread/volatility coupling (does the toll rise as
fast as the movement?).

SAMPLING (sealed, mechanical, no peeking): per member-month, the 40
alphabetically-hashed names; days = the 2nd Tuesday and 4th Thursday
of the month; time slots 10:15 / 12:45 / 15:15 ET. ETF comparator =
SPY/QQQ/IWM/XLF/XLE, same days and slots, same code path.

decision_power: NONE_TERRAIN_MEASUREMENT.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apex.governance.chain_ledger import chain_append  # noqa: E402

MEMBERSHIP = Path("/apex-data/history-b/pit_singlename/"
                  "membership_v1.jsonl")
OBS = Path("/apex-data/history-b/pit_singlename/"
           "movement_toll_obs.jsonl")
ETF_COMPARATOR = ("SPY", "QQQ", "IWM", "XLF", "XLE")
SLOTS_ET = ((10, 15), (12, 45), (15, 15))
NAMES_PER_MONTH = 40
HORIZONS = (15, 60)
NY = ZoneInfo("America/New_York")


def _get(url: str) -> dict:
    req = urllib.request.Request(url, headers={
        "APCA-API-KEY-ID": os.environ["APCA_API_KEY_ID"],
        "APCA-API-SECRET-KEY": os.environ["APCA_API_SECRET_KEY"]})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read())
        except Exception:                              # noqa: BLE001
            if attempt == 3:
                return {}
            time.sleep(1 + attempt)


def sample_days(month: str) -> list:
    """2nd Tuesday + 4th Thursday -- fixed, boring, unpeeked."""
    y, m = int(month[:4]), int(month[5:7])
    tuesdays, thursdays = [], []
    d = datetime(y, m, 1)
    while d.month == m:
        if d.weekday() == 1:
            tuesdays.append(d)
        if d.weekday() == 3:
            thursdays.append(d)
        d += timedelta(days=1)
    out = []
    if len(tuesdays) >= 2:
        out.append(tuesdays[1].strftime("%Y-%m-%d"))
    if len(thursdays) >= 4:
        out.append(thursdays[3].strftime("%Y-%m-%d"))
    return out


def pick_names(symbols: list, month: str) -> list:
    ranked = sorted(symbols, key=lambda s: hashlib.sha256(
        f"{s}:{month}:layerA".encode()).hexdigest())
    return ranked[:NAMES_PER_MONTH]


def observe(sym: str, day: str, hh: int, mm: int,
            cohort: str) -> dict | None:
    t0 = datetime(int(day[:4]), int(day[5:7]), int(day[8:]),
                  hh, mm, tzinfo=NY)
    t0u = t0.astimezone(ZoneInfo("UTC"))
    start = (t0u - timedelta(minutes=75)).isoformat()
    end = (t0u + timedelta(minutes=65)).isoformat()
    b = _get("https://data.alpaca.markets/v2/stocks/" + sym +
             "/bars?" + urllib.parse.urlencode(
                 {"start": start, "end": end, "timeframe": "1Min",
                  "limit": 200, "adjustment": "raw", "feed": "sip"}))
    bars = b.get("bars") or []
    if len(bars) < 60:
        return None
    ts = [x["t"] for x in bars]
    cut = t0u.isoformat().replace("+00:00", "Z")
    i0 = max(i for i, t in enumerate(ts) if t <= cut) \
        if any(t <= cut for t in ts) else -1
    if i0 < 30:
        return None
    px = bars[i0]["c"]
    rec = {"cohort": cohort, "symbol": sym, "day": day,
           "slot": f"{hh:02d}:{mm:02d}", "price": px}
    # prior-60m realized move (volatility state) -- BEFORE the point
    j = max(0, i0 - 60)
    rec["prior_60m_absmove"] = abs(px - bars[j]["c"]) / px
    for h in HORIZONS:
        tgt = (t0u + timedelta(minutes=h)).isoformat() \
            .replace("+00:00", "Z")
        cand = [x for x, t in zip(bars, ts) if t <= tgt]
        if not cand or (t0u + timedelta(minutes=h)).isoformat() \
                .replace("+00:00", "Z")[:16] > ts[-1][:16]:
            rec[f"fwd{h}"] = None
            continue
        rec[f"fwd{h}"] = (cand[-1]["c"] - px) / px
    q = _get("https://data.alpaca.markets/v2/stocks/" + sym +
             "/quotes?" + urllib.parse.urlencode(
                 {"start": (t0u - timedelta(minutes=1)).isoformat(),
                  "end": t0u.isoformat(), "limit": 60,
                  "feed": "sip"}))
    quotes = q.get("quotes") or []
    spreads = sorted((x["ap"] - x["bp"]) / ((x["ap"] + x["bp"]) / 2)
                     for x in quotes
                     if x.get("ap") and x.get("bp")
                     and x["ap"] > x["bp"] > 0)
    if spreads:
        rec["toll"] = spreads[len(spreads) // 2]
        rec["friction_provenance"] = "OBSERVED_SIP_NBBO"
    else:
        rec["toll"] = None
        rec["friction_provenance"] = "NOT_ESTIMABLE"
    return rec


def run() -> None:
    mem = [json.loads(l) for l in MEMBERSHIP.read_text().splitlines()
           if '"pit_membership"' in l]
    done = set()
    if OBS.exists():
        for l in OBS.read_text().splitlines():
            try:
                r = json.loads(l)
                done.add((r["cohort"], r["symbol"], r["day"],
                          r["slot"]))
            except Exception:                          # noqa: BLE001
                continue
    n = 0
    with OBS.open("a") as fh:
        for m in mem:
            month = m["member_month"]
            days = sample_days(month)
            names = pick_names(m["symbols"], month)
            for day in days:
                for hh, mm in SLOTS_ET:
                    for sym in names:
                        key = ("SINGLE", sym, day, f"{hh:02d}:{mm:02d}")
                        if key in done:
                            continue
                        r = observe(sym, day, hh, mm, "SINGLE")
                        if r:
                            fh.write(json.dumps(r) + "\n")
                        n += 1
                    for sym in ETF_COMPARATOR:
                        key = ("ETF", sym, day, f"{hh:02d}:{mm:02d}")
                        if key in done:
                            continue
                        r = observe(sym, day, hh, mm, "ETF")
                        if r:
                            fh.write(json.dumps(r) + "\n")
                        n += 1
                fh.flush()
            print(json.dumps({"month": month, "cum_requests": n * 2}),
                  flush=True)
    sha = hashlib.sha256(OBS.read_bytes()).hexdigest()[:16]
    chain_append(Path("results/edgeforge/research_board.jsonl"), {
        "kind": "movement_toll_capture_complete",
        "observations_sha": sha, "decision_power":
        "NONE_TERRAIN_MEASUREMENT"})
    print(json.dumps({"complete": True, "sha": sha}))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    if ap.parse_args().run:
        run()
