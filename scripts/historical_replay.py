"""HISTORICAL CAUSAL REPLAY — Phase 0 of the walk-forward program.

    STRATIFIED_HISTORICAL_DIAGNOSTIC only. The calendar was sampled,
    so every output row supports CONDITIONAL claims ("given a day of
    type X...") and no time-integrated claim (frequency, CAGR,
    drawdown) -- those wait for the CONTINUOUS corpus.

The replay engine is the Equity Field pattern with a simulated clock:
at each 15-minute tick T the FROZEN incumbent decide() sees only bars
with event_time <= T. Expectations are never recomputed with future
knowledge; refusal counterfactuals reuse the field's frozen-sizer
sealing; resolution reuses the incumbent stop-first policy.

H0 — REPLAY VALIDITY gates everything: a planted future bar must not
change earlier decisions; a poison field embedded in bar records must
be invisible; two runs must be byte-deterministic. NO ECONOMIC
CONCLUSION COUNTS UNTIL H0 PASSES.

Historical ledgers live under results/historical/ and never touch the
prospective field, the outbox, or any book.

decision_power: PREDATOR_EVIDENCE_ONLY (historical tier).
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import statistics as st
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from apex.governance.chain_ledger import chain_append  # noqa: E402
from apex.predators.equities import day_trader  # noqa: E402
from apex.predators.equities import shadow_resolution  # noqa: E402

import equity_field_session as FIELD  # noqa: E402  (frozen reuse)

EVIDENCE_CLASS = "STRATIFIED_HISTORICAL_DIAGNOSTIC"
CORPUS = Path("/apex-data/history-a/options_history")
HIST_BARS = Path("data/historical/bars")
DECISIONS = Path("results/historical/decisions.jsonl")
OUTCOMES = Path("results/historical/outcomes.jsonl")

# CONTINUOUS ECONOMIC WALK-FORWARD (certified corpus, calendar-
# continuous): time-integrated claims become legitimate here.
CONT_BARS = Path("/apex-data/history-b/etf_continuous/bars")
CONT_DECISIONS = Path("results/historical/continuous/decisions.jsonl")
CONT_OUTCOMES = Path("results/historical/continuous/outcomes.jsonl")
CONT_EVIDENCE_CLASS = "CONTINUOUS_ECONOMIC_WALK_FORWARD"
CONT_CORPUS_VERSION = "5c0d768b7ee2ea14"
RTH_SEMANTICS = "ET_CALENDAR_V2 (EQUITY-RTH-DST repaired)"
TICK_S = 900                    # the incumbent cadence, not a new one

ERAS = (("DISCOVERY", "2016-01-01", "2021-12-31"),
        ("VALIDATION", "2022-01-01", "2024-12-31"),
        ("DESIGN_CONTEMPORANEOUS", "2025-01-01", "2026-12-31"))


def era_of(session: str) -> str:
    for name, a, b in ERAS:
        if a <= session <= b:
            return name
    return "OUT_OF_SCOPE"


# ------------------------------------------------------------- adapt

def adapt(symbol: str, date: str, *, corpus: Path | None = None,
          out_root: Path | None = None) -> dict:
    """ThetaData underlying day-file -> fabric bar-file shape, with a
    full-denominator integrity report (DIAGNOSTIC_VALIDITY)."""
    src = (corpus or CORPUS) / symbol / \
        f"underlying_{date.replace('-', '')}.json.gz"
    root = out_root or HIST_BARS
    if not src.exists():
        return {"adapted": False, "why": f"no corpus file {src.name}"}
    rows = json.loads(gzip.open(src).read()).get("bars", [])
    bars, bad = [], 0
    prev = ""
    for r in rows:
        t = str(r.get("t", ""))
        if not t or not all(isinstance(r.get(k), (int, float))
                            for k in ("o", "h", "l", "c", "v")):
            bad += 1
            continue
        if t <= prev:                    # monotonicity is a law
            bad += 1
            continue
        prev = t
        bars.append({"event_time_utc": t.replace("+00:00", "Z"),
                     "open": r["o"], "high": r["h"], "low": r["l"],
                     "close": r["c"], "volume": r["v"]})
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{symbol}_{date}.json").write_text(
        json.dumps({"source": "thetadata_historical_adapter",
                    "bars": bars}))
    return {"adapted": True, "symbol": symbol, "session": date,
            "attempted": len(rows), "succeeded": len(bars),
            "failed": bad,
            "coverage_pct": round(100 * len(bars) / len(rows), 1)
            if rows else 0.0}


def _load_hist(symbol: str, session: str, root: Path) -> list:
    f = root / f"{symbol}_{session}.json"
    if not f.exists():
        return []
    return json.loads(f.read_text()).get("bars", [])


# ------------------------------------------------------------ replay

def replay_session(symbol: str, session: str, *,
                   bars_root: Path | None = None,
                   decisions_ledger: Path | None = None,
                   outcomes_ledger: Path | None = None) -> dict:
    """One symbol-session under the simulated clock. Frozen logic
    only; each tick sees bars <= tick."""
    root = bars_root or HIST_BARS
    dled = decisions_ledger or DECISIONS
    oled = outcomes_ledger or OUTCOMES
    # THE SESSION-DATE FENCE: a session file may only contribute bars
    # of its own date. H0's planted 2030 bar proved why -- without
    # this, one foreign-dated bar stretched the tick loop across
    # eleven years. Foreign dates are excluded, never consumed.
    bars = [b for b in _load_hist(symbol, session, root)
            if str(b.get("event_time_utc", ""))[:10] == session]
    rth = [b for b in bars
           if FIELD.rth_only([b])]      # DST-correct classification
    if len(rth) < day_trader.MIN_BARS:
        return {"symbol": symbol, "session": session,
                "replayed": False, "why": "insufficient RTH bars"}
    vols = [b.get("volume", 0) for b in rth]
    if st.median(vols) < day_trader.MIN_MEDIAN_VOLUME_PER_MIN:
        return {"symbol": symbol, "session": session,
                "replayed": False, "why": "below incumbent floor",
                "median_vol": st.median(vols)}

    open_t = datetime.fromisoformat(
        rth[0]["event_time_utc"].replace("Z", "+00:00"))
    close_t = datetime.fromisoformat(
        rth[-1]["event_time_utc"].replace("Z", "+00:00"))
    decisions, n_att, n_cf = [], 0, 0
    tick = open_t + timedelta(seconds=TICK_S)
    while tick <= close_t:
        cut = tick.isoformat().replace("+00:00", "Z")
        visible = [b for b in bars if b["event_time_utc"] <= cut]
        if visible:
            d = day_trader.decide(
                symbol=symbol, session=session, bars=visible,
                now=visible[-1]["event_time_utc"],
                known_from=visible[-1]["event_time_utc"],
                release_sha="HISTORICAL_REPLAY",
                median_volume=st.median(
                    [b.get("volume", 0)
                     for b in FIELD.rth_only(visible)] or [0]))
            rec = d.as_record()
            rec["kind"] = "historical_decision"
            rec["evidence_class"] = (CONT_EVIDENCE_CLASS
                                     if root == CONT_BARS
                                     else EVIDENCE_CLASS)
            if root == CONT_BARS:
                rec["corpus_version"] = CONT_CORPUS_VERSION
            rec["rth_semantics"] = RTH_SEMANTICS
            rec["era"] = era_of(session)
            rec["decision_power"] = "PREDATOR_EVIDENCE_ONLY"
            if rec.get("decision") in FIELD.COUNTERFACTUAL_CLASSES:
                cf = FIELD.counterfactual_expression(rec)
                rec["counterfactual_expression"] = cf or \
                    "NOT_ESTIMABLE"
                if cf:
                    n_cf += 1
            if rec.get("decision") == "ATTACK_READY_SHADOW":
                n_att += 1
            chain_append(dled, rec)
            decisions.append(rec)
        tick += timedelta(seconds=TICK_S)

    resolved = 0
    for rec in decisions:
        shaped = FIELD._resolvable(rec)
        if shaped is None:
            continue
        out = shadow_resolution.resolve(decision=shaped, bars=bars,
                                        close_utc=close_t)
        out["kind"] = "historical_outcome"
        out["evidence_class"] = (CONT_EVIDENCE_CLASS
                                 if root == CONT_BARS
                                 else EVIDENCE_CLASS)
        if root == CONT_BARS:
            out["corpus_version"] = CONT_CORPUS_VERSION
        out["era"] = era_of(session)
        out["original_decision"] = rec["decision"]
        out["counterfactual"] = \
            rec["decision"] != "ATTACK_READY_SHADOW"
        out["setup_type"] = rec.get("setup_type")
        out["direction"] = rec.get("direction")
        out["known_from"] = rec.get("known_from")
        out["decision_power"] = "PREDATOR_EVIDENCE_ONLY"
        chain_append(oled, out)
        resolved += 1
    return {"symbol": symbol, "session": session, "replayed": True,
            "era": era_of(session), "ticks": len(decisions),
            "attackable": n_att, "counterfactuals": n_cf,
            "resolved": resolved}


# ---------------------------------------------------------------- H0

def h0(symbol: str, session: str, *, corpus: Path | None = None,
       scratch: Path | None = None, preadapted: bool = False) -> dict:
    """REPLAY VALIDITY. Three proofs on a real corpus day:
    TRUNCATION  a planted far-future bar changes nothing earlier
    POISON      an injected non-OHLCV field is invisible to decisions
    DETERMINISM two runs produce identical decision content
    """
    from tempfile import mkdtemp
    work = scratch or Path(mkdtemp(prefix="h0_"))
    if not preadapted:
        a = adapt(symbol, session, corpus=corpus,
                  out_root=work / "clean")
        if not a.get("adapted"):
            return {"h0": "NOT_RUNNABLE", "why": a.get("why")}

    def run(root, tag):
        led = work / f"d_{tag}.jsonl"
        out = work / f"o_{tag}.jsonl"
        r = replay_session(symbol, session, bars_root=root,
                           decisions_ledger=led, outcomes_ledger=out)
        rows = []
        if led.exists():
            for line in led.read_text().splitlines():
                d = json.loads(line)
                d.pop("prev_hash", None)
                d.pop("entry_hash", None)
                d.pop("sealed_utc", None)
                rows.append(d)
        return r, hashlib.sha256(
            json.dumps(rows, sort_keys=True).encode()).hexdigest()

    r1, h1_ = run(work / "clean", "base")
    _, h2_ = run(work / "clean", "again")
    deterministic = h1_ == h2_

    # planted future bar (a year ahead) appended to the file
    f = work / "clean" / f"{symbol}_{session}.json"
    d = json.loads(f.read_text())
    future = dict(d["bars"][-1])
    future["event_time_utc"] = "2030-01-01T15:00:00Z"
    future["close"] = future["close"] * 2
    (work / "future").mkdir(parents=True, exist_ok=True)
    (work / "future" / f.name).write_text(
        json.dumps({"bars": d["bars"] + [future]}))
    _, h3_ = run(work / "future", "future")
    truncation_ok = h3_ == h1_

    # poison field injected into every bar
    poisoned = [dict(b, settle_close_future=999999.0)
                for b in d["bars"]]
    (work / "poison").mkdir(parents=True, exist_ok=True)
    (work / "poison" / f.name).write_text(
        json.dumps({"bars": poisoned}))
    _, h4_ = run(work / "poison", "poison")
    poison_ok = h4_ == h1_

    verdict = "PASS" if (deterministic and truncation_ok
                         and poison_ok) else "FAIL"
    rep = {"kind": "h0_replay_validity", "symbol": symbol,
           "session": session, "verdict": verdict,
           "deterministic": deterministic,
           "future_bar_ignored": truncation_ok,
           "poison_field_invisible": poison_ok,
           "ticks": r1.get("ticks"),
           "law": "no economic conclusion counts until H0 passes",
           "decision_power": "PREDATOR_EVIDENCE_ONLY"}
    chain_append(Path("results/historical/h0.jsonl"), rep)
    return rep


# -------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--adapt-era", metavar="ERA")
    ap.add_argument("--replay-era", metavar="ERA")
    ap.add_argument("--h0", nargs=2, metavar=("SYM", "DATE"))
    ap.add_argument("--h0-continuous", nargs=2,
                    metavar=("SYM", "DATE"))
    ap.add_argument("--replay-continuous", action="store_true")
    ap.add_argument("--start", default="2016-01-01")
    ap.add_argument("--end", default="2026-08-28")
    ap.add_argument("--symbols", default="SPY,QQQ,IWM,AAPL,MSFT,NVDA")
    a = ap.parse_args()
    syms = a.symbols.split(",")

    if a.h0:
        print(json.dumps(h0(a.h0[0], a.h0[1]), indent=1))
        return 0
    if a.h0_continuous:
        sym, date = a.h0_continuous
        from tempfile import mkdtemp
        import shutil
        work = Path(mkdtemp(prefix="h0c_"))
        (work / "clean").mkdir(parents=True)
        src = CONT_BARS / f"{sym}_{date}.json"
        if not src.exists():
            print(json.dumps({"h0": "NOT_RUNNABLE",
                              "why": f"no corpus file {src.name}"}))
            return 1
        shutil.copy(src, work / "clean" / src.name)
        print(json.dumps(h0(sym, date, corpus=None, scratch=work,
                            preadapted=True), indent=1))
        return 0
    if a.replay_continuous:
        sessions = sorted({f.stem.rsplit("_", 1)[1]
                           for f in CONT_BARS.glob("*.json")
                           if a.start <= f.stem.rsplit("_", 1)[1]
                           <= a.end})
        syms = sorted({f.stem.rsplit("_", 1)[0]
                       for f in CONT_BARS.glob("*.json")})
        tot = {"sessions": 0, "replayed": 0, "attackable": 0,
               "counterfactuals": 0, "resolved": 0, "below_floor": 0}
        for i, d in enumerate(sessions):
            for sym in syms:
                r = replay_session(sym, d, bars_root=CONT_BARS,
                                   decisions_ledger=CONT_DECISIONS,
                                   outcomes_ledger=CONT_OUTCOMES)
                tot["sessions"] += 1
                if r.get("replayed"):
                    tot["replayed"] += 1
                    for k in ("attackable", "counterfactuals",
                              "resolved"):
                        tot[k] += r[k]
                elif r.get("why") == "below incumbent floor":
                    tot["below_floor"] += 1
            if (i + 1) % 50 == 0:
                print(json.dumps({"progress_sessions": i + 1,
                                  "of": len(sessions), **tot}),
                      flush=True)
        print(json.dumps({"era": "CONTINUOUS", **tot}, indent=1))
        return 0

    def era_dates(era):
        lo, hi = next((x, y) for n, x, y in ERAS if n == era)
        out = set()
        for s in syms:
            for f in sorted((CORPUS / s).glob("underlying_*.json.gz")):
                d = f.stem.split("_")[1].split(".")[0]
                d = f"{d[:4]}-{d[4:6]}-{d[6:]}"
                if lo <= d <= hi:
                    out.add(d)
        return sorted(out)

    if a.adapt_era:
        n = ok = 0
        for d in era_dates(a.adapt_era):
            for s in syms:
                r = adapt(s, d)
                n += 1
                ok += 1 if r.get("adapted") else 0
        print(json.dumps({"era": a.adapt_era, "attempted": n,
                          "adapted": ok}))
        return 0
    if a.replay_era:
        tot = {"sessions": 0, "replayed": 0, "attackable": 0,
               "counterfactuals": 0, "resolved": 0, "below_floor": 0}
        for d in era_dates(a.replay_era):
            for s in syms:
                r = replay_session(s, d)
                tot["sessions"] += 1
                if r.get("replayed"):
                    tot["replayed"] += 1
                    for k in ("attackable", "counterfactuals",
                              "resolved"):
                        tot[k] += r[k]
                elif r.get("why") == "below incumbent floor":
                    tot["below_floor"] += 1
        print(json.dumps({"era": a.replay_era, **tot}, indent=1))
        return 0
    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
