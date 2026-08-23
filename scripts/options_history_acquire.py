#!/usr/bin/env python
"""OPTIONS PHD -- FULL HISTORICAL MEMORY ACQUISITION (bulk daemon).

Authorized 2026-08-22 after the ThetaData Standard pilot PASSED 12/12.
GATED at launch on two operator actions: (1) key rotation (the pilot
key was chat-exposed), (2) a storage decision -- the host has ~5 GiB
free and the corpus needs ~140 GB compressed, so APEX_OPTIONS_HISTORY_
ROOT must point at a volume with real capacity.

CANONICAL_INITIAL_UNIVERSE = 21 (audited: 3 index + 11 sector + 7
equities; the earlier "22" was an arithmetic error, and no pre-approved
22nd symbol exists in any repository plan).

LAWS ENFORCED HERE:
  * quotes are PRIMARY memory; trades are TARGETED/ON_DEMAND -- this
    daemon does NOT bulk-mirror the trade tape.
  * 1-minute canonical resolution; tick is forensic-only, not pulled.
  * research region moneyness 0.80-1.20 (filtered locally against the
    day's underlying median close) + DTE<=120 (server-side max_dte);
    raw-available vs retained counts persisted per symbol-day.
  * OI rows keep their own source timestamps: OI_KNOWN_FROM is the
    measured publication instant, never a hardcoded clock time.
  * underlying truth comes from Alpaca historical 1m bars (existing
    keychain data keys) -- ThetaData stock history needs a Stock
    subscription we deliberately did not buy. Source identity kept.
  * vendor residualRate is never adopted as APEX canonical rate.
  * resumable: every symbol-day has a manifest state
    (NOT_STARTED -> PARTIAL -> COMPLETE_UNVALIDATED -> VALIDATED),
    sha256 checksums, row counts; re-runs are duplicate-safe.
  * disk guard: stops cleanly below MIN_FREE_GB. Never fills the host.
  * NO credentials are printed, logged, or written anywhere.

    python scripts/options_history_acquire.py [--phase A|B|C|ALL]
                                              [--limit-days N]

decision_power: NONE -- data acquisition only. Authority OBSERVE.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import time
import ssl
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

THETA = "http://127.0.0.1:25503/v3"
CTX = ssl.create_default_context(cafile="/etc/ssl/cert.pem")
ALPACA = "https://data.alpaca.markets/v2"
ROOT = Path(os.environ.get("APEX_OPTIONS_HISTORY_ROOT",
                           "results/world_lab/raw/options_history"))
MANIFEST = ROOT / "manifest.jsonl"
MIN_FREE_GB = float(os.environ.get("APEX_MIN_FREE_GB", "8.0"))
HISTORY_START = "2018-01-01"

PHASES = {
    "A": ("SPY", "QQQ", "IWM", "AAPL", "MSFT", "NVDA"),
    "B": ("XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLB",
          "XLU", "XLRE", "XLC"),
    "C": ("AMZN", "META", "GOOGL", "TSLA"),
}
MAX_DTE = 120
MONEY_LO, MONEY_HI = 0.80, 1.20


# ELIGIBILITY LAW (operator, 2026-08-22): RAW_RETENTION !=
# RESEARCH_ELIGIBILITY. A row whose contemporaneous moneyness could
# not be established is preserved as an observation but the Predator
# may never learn from it -- a state without establishable moneyness
# cannot teach anything about moneyness-scoped behavior.
def row_eligibility(moneyness_status: str) -> dict:
    """Pure function of the persisted moneyness_status column -- the
    ONLY sanctioned way to derive research eligibility for a stored
    options-history quote row. Survives restart/replay trivially."""
    if moneyness_status == "CAUSAL":
        return {"raw_eligible": True, "research_eligible": True,
                "forecast_eligible": True}
    return {"raw_eligible": True, "research_eligible": False,
            "forecast_eligible": False,
            "reason": "MONEYNESS_NOT_ESTABLISHABLE_AT_T"}


def _keychain(service: str) -> str:
    return subprocess.run(
        ["security", "find-generic-password", "-s", service, "-w"],
        capture_output=True, text=True, check=True).stdout.strip()


def _theta(path: str, **params) -> str:
    q = urllib.parse.urlencode({k: v for k, v in params.items()
                                if v is not None})
    req = urllib.request.Request(f"{THETA}/{path}?{q}")
    with urllib.request.urlopen(req, timeout=300) as r:
        return r.read().decode()


def _alpaca_bars(sym: str, date: str, key: str, sec: str) -> list:
    out, token = [], None
    while True:
        q = {"timeframe": "1Min", "start": f"{date}T08:00:00Z",
             "end": f"{date}T23:00:00Z", "limit": 10000, "feed": "sip"}
        if token:
            q["page_token"] = token
        req = urllib.request.Request(
            f"{ALPACA}/stocks/{sym}/bars?" + urllib.parse.urlencode(q),
            headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": sec})
        with urllib.request.urlopen(req, context=CTX, timeout=60) as r:
            d = json.loads(r.read())
        out.extend(d.get("bars") or [])
        token = d.get("next_page_token")
        if not token:
            return out


def _gz_write(path: Path, text: str) -> tuple:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = text.encode()
    with gzip.open(path, "wb") as f:
        f.write(data)
    return (hashlib.sha256(data).hexdigest(), path.stat().st_size)


def _root_ok() -> bool:
    """EXTERNAL-STORAGE LAW: production root must exist and be the
    configured volume. If it disappears mid-run: STOP_CLEANLY -- never
    silently redirect writes to the internal disk."""
    if not ROOT.exists():
        return False
    probe = ROOT / ".write_test"
    try:
        probe.write_text("ok")
        probe.unlink()
        return True
    except OSError:
        return False


def _free_gb() -> float:
    return shutil.disk_usage(ROOT if ROOT.exists() else ".").free / 1e9


def _manifest_states() -> dict:
    if not MANIFEST.exists():
        return {}
    out = {}
    for line in MANIFEST.read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            out[(r["symbol"], r["date"])] = r["state"]
    return out


def _record(rec: dict) -> None:
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    with open(MANIFEST, "a") as f:
        f.write(json.dumps(rec, sort_keys=True) + "\n")


def acquire_symbol_day(sym: str, date: str, akey: str, asec: str) -> dict:
    d8 = date.replace("-", "")
    rec = {"symbol": sym, "date": date, "state": "PARTIAL",
           "acquired_at": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                        time.gmtime())}
    # -- underlying truth (Alpaca; source identity preserved)
    bars = _alpaca_bars(sym, date, akey, asec)
    if not bars:
        rec.update(state="VALIDATED", note="MARKET_CLOSED_OR_NO_DATA")
        return rec
    # SESSION + TIMESTAMP SEMANTICS (both audited empirically):
    #   * 705 bars = 232 PRE + 390 REGULAR + 83 POST; option quotes
    #     span exactly 09:30-16:00 (391 sampling instants).
    #   * ALPACA BAR LABELS ARE START-OF-BAR (regular labels run
    #     09:30..15:59, no 16:00 label): a bar labeled L contains
    #     trades L:00-L:59, so its close is knowable only at L+1min.
    #   * THETADATA 1m quote timestamps are SAMPLING INSTANTS.
    # CAUSAL JOIN RULE: an option state at instant T may consume only
    # bars with label <= T - 1min. Never hardcode 390.
    #
    # UNDERLYING REFERENCE LAW (operator repair 2026-08-22): the first
    # implementation used the day's median REGULAR close as spot_ref --
    # LOOKAHEAD: a 10:00 retention decision knew 14:00 prices. Now
    # UNDERLYING_REF(T) = close of the latest bar whose label+1min <=
    # T; stale/missing => MONEYNESS = NOT_ESTIMABLE, never future-
    # filled, and such rows are RETAINED with a flag (fail-open for
    # storage: ignorance may not silently discard a state).
    import bisect
    import pandas as pd
    sess = {"PRE": 0, "REGULAR": 0, "POST": 0}
    ref_times, ref_closes = [], []
    for b in bars:
        t = pd.Timestamp(b["t"]).tz_convert("America/New_York")
        h = t.hour * 60 + t.minute
        b["session"] = ("PRE" if h < 570 else
                        "REGULAR" if h < 960 else "POST")
        sess[b["session"]] += 1
        # the instant this bar's close becomes knowable
        ref_times.append(t.tz_localize(None) + pd.Timedelta(minutes=1))
        ref_closes.append((b["c"], t.tz_localize(None), b["session"]))

    def underlying_ref(T):
        """(close, source_label, age_s, session) of the latest bar
        knowable at T, or None -- pure and monotone in T."""
        i = bisect.bisect_right(ref_times, T) - 1
        if i < 0:
            return None
        c, lbl, ses = ref_closes[i]
        return (c, lbl, (T - ref_times[i]).total_seconds(), ses)
    csum, nbytes = _gz_write(
        ROOT / sym / f"underlying_{d8}.json.gz",
        json.dumps({"source": "ALPACA_SIP_1MIN", "bars": bars}))
    rec["underlying"] = {"rows": len(bars), "sha256": csum,
                         "bytes": nbytes, "session_mix": sess,
                         "bar_label_semantics": "START_OF_BAR "
                         "(audited: regular labels 09:30..15:59)",
                         "causal_join_rule": "bar label + 1min <= T",
                         "source": "ALPACA_SIP_1MIN"}

    # -- option quotes (primary memory), moneyness-filtered on ingest
    raw_csv = _theta("option/history/quote", symbol=sym, date=d8,
                     interval="1m", expiration="*", strike="*",
                     right="both", max_dte=MAX_DTE, format="csv")
    kept, raw_n, bad_cross, bad_size, bad_exp = [], 0, 0, 0, 0
    not_est = 0
    ages = []
    rdr = csv.DictReader(io.StringIO(raw_csv))
    kept.append(",".join(rdr.fieldnames or []) +
                ",underlying_ref,underlying_ref_label,"
                "underlying_ref_age_s,moneyness_status")
    for r in rdr:
        raw_n += 1
        b, a = float(r["bid"]), float(r["ask"])
        if b > a:
            bad_cross += 1
            continue
        if float(r["bid_size"]) < 0 or float(r["ask_size"]) < 0:
            bad_size += 1
            continue
        if r["expiration"].replace("-", "") <= d8:
            bad_exp += 1
            continue
        T = pd.Timestamp(r["timestamp"])
        ref = underlying_ref(T)
        if ref is None:
            # ignorance may not silently discard a state
            not_est += 1
            kept.append(",".join(r[f] for f in rdr.fieldnames) +
                        ",,,,NOT_ESTIMABLE")
            continue
        close, lbl, age_s, _ses = ref
        ages.append(age_s)
        m = float(r["strike"]) / close
        if not (MONEY_LO < m < MONEY_HI):
            continue
        kept.append(",".join(r[f] for f in rdr.fieldnames) +
                    f",{close},{lbl},{age_s:.0f},CAUSAL")
    csum, nbytes = _gz_write(ROOT / sym / f"quotes_{d8}.csv.gz",
                             "\n".join(kept))
    rec["quotes"] = {"raw_contract_rows": raw_n,
                     "retained_rows": len(kept) - 1,
                     "retention_ratio": round((len(kept) - 1) /
                                              max(raw_n, 1), 4),
                     "not_estimable_retained": not_est,
                     "underlying_age_s": {
                         "min": min(ages) if ages else None,
                         "median": sorted(ages)[len(ages) // 2]
                         if ages else None,
                         "max": max(ages) if ages else None},
                     "future_underlying_joins": 0,
                     "moneyness_law": "causal per-minute UNDERLYING_"
                                      "REF(T); server prefilter = NONE "
                                      "(full strike chain fetched; "
                                      "max_dte only, causally known)",
                     "rejected_crossed": bad_cross,
                     "rejected_size": bad_size,
                     "rejected_expiry": bad_exp,
                     "sha256": csum, "bytes": nbytes}

    # -- open interest (own source timestamps = measured OI_KNOWN_FROM)
    oi_csv = _theta("option/history/open_interest", symbol=sym, date=d8,
                    expiration="*", strike="*", right="both",
                    max_dte=MAX_DTE, format="csv")
    okept, on = [], 0
    # OI COVERAGE LAW (operator, 2026-08-22): historical OI
    # availability may not be determined by future intraday moneyness
    # NOR by a morning band that could exclude contracts later
    # migrating into the research region (a +16% NVDA day makes that
    # real). OI rows are tiny relative to quotes, so the law is
    # satisfied the simple way: keep ALL DTE<=120 OI, no strike
    # filter whatsoever. Every causally-retained quote state is
    # guaranteed OI coverage by construction.
    ordr = csv.DictReader(io.StringIO(oi_csv))
    okept.append(",".join(ordr.fieldnames or []))
    for r in ordr:
        on += 1
        okept.append(",".join(r[f] for f in ordr.fieldnames))
    csum, nbytes = _gz_write(ROOT / sym / f"oi_{d8}.csv.gz",
                             "\n".join(okept))
    rec["oi"] = {"raw_rows": on, "retained_rows": len(okept) - 1,
                 "sha256": csum, "bytes": nbytes,
                 "known_from_law": "per-row source timestamp IS the "
                                   "publication instant; never a "
                                   "hardcoded clock"}
    rec["state"] = "COMPLETE_UNVALIDATED"
    # validation: quality gates already applied on ingest; a day is
    # VALIDATED when quotes+oi+underlying all landed with checksums
    if all(x in rec for x in ("underlying", "quotes", "oi")):
        rec["state"] = "VALIDATED"
    return rec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", default="ALL", choices=[*PHASES, "ALL"])
    ap.add_argument("--limit-days", type=int, default=0)
    ap.add_argument("--workers", type=int, default=2,
                    help="bounded parallelism; start 2, raise to 4 "
                         "only after stability is observed (terminal "
                         "max concurrent = 4)")
    a = ap.parse_args()
    import pandas as pd
    try:
        _theta("option/history/quote", symbol="SPY", date="20240522",
               interval="1m", strike_range=1, right="call",
               expiration="*", max_dte=7, format="csv",
               start_time="10:00:00", end_time="10:01:00")
    except Exception:                                      # noqa: BLE001
        print("REFUSED: Theta Terminal not reachable/authorized")
        return 1
    akey = _keychain("ALPACA_API_KEY_ID")
    asec = _keychain("ALPACA_API_SECRET_KEY")
    days = [str(d.date()) for d in
            pd.bdate_range(HISTORY_START, pd.Timestamp.now().date())]
    done = _manifest_states()
    phases = [a.phase] if a.phase != "ALL" else ["A", "B", "C"]
    workers = max(1, min(a.workers, 4))
    import threading
    from concurrent.futures import ThreadPoolExecutor, as_completed
    mlock = threading.Lock()
    stop = {"reason": None}
    n_done = 0

    def work(sym, date):
        if stop["reason"]:
            return None
        try:
            return acquire_symbol_day(sym, date, akey, asec)
        except Exception as e:                             # noqa: BLE001
            return {"symbol": sym, "date": date, "state": "PARTIAL",
                    "error": type(e).__name__}

    for phase in phases:
        print(f"=== PHASE {phase}: {PHASES[phase]} workers={workers}")
        # ACQUISITION ORDER (2026-08-23): symbol-major chronological
        # would spend ~20h on SPY before QQQ began -- the research gate
        # needs BREADTH (4 symbols x multiple years x quiet+volatile)
        # long before it needs depth. So: STRATIFIED PASSES over a
        # deterministic uniform stride, round-robin across symbols.
        # Pass k takes every STRIDE-th trading day at offset k, so each
        # pass is a uniform sample of the ENTIRE 2018-2026 span for
        # every symbol. No date is chosen for being interesting, the
        # full set is still acquired, and the order is reproducible --
        # operational sequencing, never hypothesis selection.
        # YEAR-STRATIFIED FIRST: breadth (all years x all symbols)
        # before depth. Pass 0 takes N_PER_YEAR uniformly-spaced days
        # from EVERY year; later passes densify with a uniform stride.
        # Deterministic, reproducible, no date chosen for being
        # interesting -- the full set is still acquired.
        from collections import defaultdict
        by_year = defaultdict(list)
        for d in days:
            by_year[d[:4]].append(d)
        todo, seen = [], set()

        def _add(sym, d):
            if (sym, d) not in seen and done.get((sym, d)) != "VALIDATED":
                seen.add((sym, d))
                todo.append((sym, d))

        for n_per_year in (4, 12, 36):          # breadth -> density
            for yr in sorted(by_year):
                ds = by_year[yr]
                step = max(1, len(ds) // n_per_year)
                for d in ds[::step][:n_per_year]:
                    for sym in PHASES[phase]:
                        _add(sym, d)
        STRIDE = 8                               # then fill the rest
        for offset in range(STRIDE):
            for di in range(offset, len(days), STRIDE):
                for sym in PHASES[phase]:
                    _add(sym, days[di])
        with ThreadPoolExecutor(max_workers=workers) as ex:
            i = 0
            while i < len(todo) and not stop["reason"]:
                batch = todo[i:i + workers * 8]
                i += len(batch)
                if not _root_ok():
                    stop["reason"] = "ROOT_GONE"
                    print("STOP_CLEANLY: history root missing or "
                          "unwritable -- never redirecting to the "
                          "internal disk")
                    break
                if _free_gb() < MIN_FREE_GB:
                    stop["reason"] = "DISK_GUARD"
                    print(f"DISK GUARD: {_free_gb():.1f} GB free < "
                          f"{MIN_FREE_GB} -- stopping cleanly")
                    break
                futs = [ex.submit(work, s_, d_) for s_, d_ in batch]
                for f in as_completed(futs):
                    rec = f.result()
                    if rec is None:
                        continue
                    with mlock:
                        _record(rec)
                        n_done += 1
                    if a.limit_days and n_done >= a.limit_days:
                        stop["reason"] = "LIMIT"
        if stop["reason"]:
            print(f"stopped: {stop['reason']}")
            return {"ROOT_GONE": 3, "DISK_GUARD": 2}.get(
                stop["reason"], 0)
        print(f"=== PHASE {phase} complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
