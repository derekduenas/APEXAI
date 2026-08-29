"""ETF CONTINUOUS CORPUS — the shared historical foundation.

Operator GO 2026-08-29: one calendar-continuous, versioned, integrity-
validated 1-minute corpus for the survivorship-free ETF core, serving
H1/H2/H3/H4 first and H5 after -- so no experiment ever silently uses
a different historical reality.

Source: Alpaca historical bars REST (SIP feed, included in the
existing Algo Trader Plus subscription; entitlement PROBED before any
bulk fetch, never assumed). adjustment=raw to match the live fabric's
semantics -- the incumbent's intraday logic is session-local, and the
manifest records the choice so corporate-action handling is explicit,
not silent.

NO ECONOMIC USE UNTIL THE INTEGRITY REPORT PASSES. The manifest hash
versions the artifact; every experiment cites the version it consumed.

decision_power: NONE_DATA_ACQUISITION.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics as st
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apex.governance.chain_ledger import chain_append  # noqa: E402

ETF_CORE = ("SPY", "QQQ", "IWM", "XLB", "XLC", "XLE", "XLF", "XLI",
            "XLK", "XLP", "XLRE", "XLU", "XLV", "XLY")
ROOT = Path("/apex-data/history-b/etf_continuous")
BARS = ROOT / "bars"
START = "2016-01-04"
API = "https://data.alpaca.markets/v2/stocks/{sym}/bars"


def _et_date(t_iso: str) -> str:
    """The EXCHANGE session date, not the UTC calendar date. UTC
    keying stranded Friday's late extended-hours prints (post-19:00
    EST = next-day UTC) in bogus Saturday files and made holidays
    appear in the session calendar."""
    from zoneinfo import ZoneInfo
    dt = datetime.fromisoformat(t_iso.replace("Z", "+00:00"))
    return dt.astimezone(ZoneInfo("America/New_York")) \
        .strftime("%Y-%m-%d")


def _get(url: str) -> dict:
    req = urllib.request.Request(url, headers={
        "APCA-API-KEY-ID": os.environ["APCA_API_KEY_ID"],
        "APCA-API-SECRET-KEY": os.environ["APCA_API_SECRET_KEY"]})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def probe() -> dict:
    """One request proves the entitlement before any bulk fetch."""
    url = API.format(sym="SPY") + "?" + urllib.parse.urlencode({
        "start": "2016-01-05T09:30:00-05:00",
        "end": "2016-01-05T16:00:00-05:00",
        "timeframe": "1Min", "limit": 10, "adjustment": "raw",
        "feed": "sip"})
    try:
        d = _get(url)
        n = len(d.get("bars") or [])
        return {"entitled": n > 0, "bars_returned": n,
                "earliest_probe": "2016-01-05"}
    except Exception as e:                              # noqa: BLE001
        return {"entitled": False,
                "why": f"{type(e).__name__}: {str(e)[:120]}"}


def fetch_symbol(sym: str, *, start: str = START,
                 end: str | None = None) -> dict:
    """Full paged fetch -> fabric-shape day files. Appends nothing to
    existing day files: each day is written whole, idempotently."""
    end = end or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    BARS.mkdir(parents=True, exist_ok=True)
    days: dict[str, list] = {}
    token, pages = None, 0
    while True:
        q = {"start": f"{start}T00:00:00Z", "end": f"{end}T23:59:59Z",
             "timeframe": "1Min", "limit": 10000,
             "adjustment": "raw", "feed": "sip"}
        if token:
            q["page_token"] = token
        d = _get(API.format(sym=sym) + "?" + urllib.parse.urlencode(q))
        for b in d.get("bars") or []:
            t = b["t"]
            days.setdefault(_et_date(t), []).append(
                {"event_time_utc": t.replace("+00:00", "Z"),
                 "open": b["o"], "high": b["h"], "low": b["l"],
                 "close": b["c"], "volume": b["v"]})
        pages += 1
        token = d.get("next_page_token")
        if not token:
            break
        if pages % 40 == 0:
            time.sleep(1)               # polite pacing under the limit
    written = 0
    for day, bars in days.items():
        bars.sort(key=lambda b: b["event_time_utc"])
        (BARS / f"{sym}_{day}.json").write_text(
            json.dumps({"source": "alpaca_sip_raw_1m", "bars": bars}))
        written += 1
    return {"symbol": sym, "pages": pages, "days_written": written,
            "first_day": min(days) if days else None,
            "last_day": max(days) if days else None}


def _is_rth_et(t_iso: str) -> bool:
    from zoneinfo import ZoneInfo
    t = datetime.fromisoformat(t_iso.replace("Z", "+00:00")) \
        .astimezone(ZoneInfo("America/New_York"))
    return (9, 30) <= (t.hour, t.minute) <= (16, 0)


def integrity() -> dict:
    """The full operator checklist. PASS is a prerequisite for any
    economic use; the manifest hash versions the artifact."""
    per_sym: dict[str, dict] = {}
    union_days: set[str] = set()
    files = sorted(BARS.glob("*.json"))
    for f in files:
        sym, day = f.stem.rsplit("_", 1)
        union_days.add(day)
        s = per_sym.setdefault(sym, {"days": 0, "bars": 0,
                                     "dupes": 0, "non_monotonic": 0,
                                     "thin_days": 0,
                                     "by_year": {}})
        bars = json.loads(f.read_text()).get("bars", [])
        s["days"] += 1
        s["bars"] += len(bars)
        s["by_year"][day[:4]] = s["by_year"].get(day[:4], 0) + 1
        seen, prev = set(), ""
        for b in bars:
            t = b["event_time_utc"]
            if t in seen:
                s["dupes"] += 1
            if t <= prev and prev:
                s["non_monotonic"] += 1
            seen.add(t)
            prev = t
        rth = [b for b in bars
               if _is_rth_et(b["event_time_utc"])]
        # DENSITY metric, not a defect: a 1-minute bar exists only
        # where trades printed, so quiet ETFs legitimately skip
        # minutes, and half-days legitimately end early. Reported for
        # the record; never a verdict input.
        if len(rth) < 300:
            s["thin_days"] += 1

    # calendar completeness: the union of days across symbols is the
    # self-consistent session calendar; a symbol missing one of those
    # days AFTER ITS OWN INCEPTION has a hole. Pre-inception absence
    # is history, not a defect -- the first run flagged XLC FAIL for
    # not existing before June 2018.
    have = {sym: {f.stem.rsplit("_", 1)[1] for f in files
                  if f.stem.rsplit("_", 1)[0] == sym}
            for sym in per_sym}
    missing = {sym: sorted(d for d in union_days - have[sym]
                           if d >= min(have[sym]))
               for sym in per_sym}
    post_inception_sessions = {sym: sum(1 for d in union_days
                                        if d >= min(have[sym]))
                               for sym in per_sym}
    worst_missing_pct = max(
        (len(missing[sym]) / max(post_inception_sessions[sym], 1)
         for sym in per_sym), default=0.0)
    worst_missing = max((len(v) for v in missing.values()),
                        default=0)

    # ThetaData overlap comparison on sampled days
    theta = Path("/apex-data/history-a/options_history")
    overlap = {"compared": 0, "close_mismatches": 0}
    import gzip
    for sym in ("SPY", "QQQ", "IWM"):
        tdir = theta / sym
        if not tdir.exists():
            continue
        for tf in sorted(tdir.glob("underlying_*.json.gz"))[:20]:
            day = tf.stem.split("_")[1].split(".")[0]
            day = f"{day[:4]}-{day[4:6]}-{day[6:]}"
            af = BARS / f"{sym}_{day}.json"
            if not af.exists():
                continue
            tb = {b["t"][:16]: b["c"] for b in
                  json.loads(gzip.open(tf).read()).get("bars", [])}
            ab = {b["event_time_utc"][:16]: b["close"] for b in
                  json.loads(af.read_text()).get("bars", [])}
            common = set(tb) & set(ab)
            if not common:
                continue
            overlap["compared"] += 1
            diffs = [abs(tb[k] - ab[k]) / max(ab[k], 1e-9)
                     for k in common]
            if st.median(diffs) > 0.0005:      # 5bps median disagreement
                overlap["close_mismatches"] += 1

    manifest = hashlib.sha256("\n".join(
        f"{f.name}:{f.stat().st_size}" for f in files)
        .encode()).hexdigest()[:16]
    total_dupes = sum(s["dupes"] for s in per_sym.values())
    total_nm = sum(s["non_monotonic"] for s in per_sym.values())
    verdict = "PASS" if (files and total_dupes == 0 and total_nm == 0
                         and overlap["close_mismatches"] == 0
                         and worst_missing_pct < 0.02) \
        else "FAIL"
    rep = {"kind": "etf_corpus_integrity",
           "corpus_version": manifest,
           "verdict": verdict,
           "symbols": len(per_sym),
           "union_sessions": len(union_days),
           "span": (min(union_days), max(union_days))
           if union_days else None,
           "adjustment": "raw (matches live fabric semantics; "
                         "corporate actions explicit, not silent)",
           "duplicates": total_dupes, "non_monotonic": total_nm,
           "worst_symbol_missing_days": worst_missing,
           "worst_missing_pct_post_inception":
           round(worst_missing_pct, 4),
           "inception_by_symbol": {sym: min(have[sym])
                                   for sym in per_sym},
           "missing_by_symbol": {k: len(v) for k, v in
                                 missing.items()},
           "thin_days_by_symbol": {k: s["thin_days"]
                                   for k, s in per_sym.items()},
           "thetadata_overlap": overlap,
           "per_symbol": {k: {kk: s[kk] for kk in
                              ("days", "bars", "by_year")}
                          for k, s in per_sym.items()},
           "law": "no economic use until PASS; every experiment cites "
                  "corpus_version",
           "decision_power": "NONE_DATA_ACQUISITION"}
    chain_append(ROOT / "integrity.jsonl", rep)
    return rep


def rebucket() -> dict:
    """Re-key every existing day file by ET session date (one-time
    repair of the UTC-dating defect; no refetch needed)."""
    from collections import defaultdict
    syms = sorted({f.stem.rsplit("_", 1)[0]
                   for f in BARS.glob("*.json")})
    stats = {"symbols": len(syms), "files_before": 0,
             "files_after": 0, "moved_bars": 0}
    for sym in syms:
        buckets: dict = defaultdict(list)
        old_files = sorted(BARS.glob(f"{sym}_*.json"))
        stats["files_before"] += len(old_files)
        for f in old_files:
            for b in json.loads(f.read_text()).get("bars", []):
                d = _et_date(b["event_time_utc"])
                if d != f.stem.rsplit("_", 1)[1]:
                    stats["moved_bars"] += 1
                buckets[d].append(b)
        for f in old_files:
            f.unlink()
        for day, bars in buckets.items():
            seen, out = set(), []
            for b in sorted(bars,
                            key=lambda x: x["event_time_utc"]):
                if b["event_time_utc"] not in seen:
                    seen.add(b["event_time_utc"])
                    out.append(b)
            (BARS / f"{sym}_{day}.json").write_text(
                json.dumps({"source": "alpaca_sip_raw_1m",
                            "bars": out}))
            stats["files_after"] += 1
    return stats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--rebucket", action="store_true")
    ap.add_argument("--fetch-all", action="store_true")
    ap.add_argument("--integrity", action="store_true")
    a = ap.parse_args()
    if a.probe:
        print(json.dumps(probe(), indent=1))
        return 0
    if a.rebucket:
        print(json.dumps(rebucket(), indent=1))
        return 0
    if a.fetch_all:
        for sym in ETF_CORE:
            r = fetch_symbol(sym)
            print(json.dumps(r), flush=True)
        return 0
    if a.integrity:
        rep = integrity()
        rep.pop("per_symbol", None)
        print(json.dumps(rep, indent=1))
        return 0
    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
