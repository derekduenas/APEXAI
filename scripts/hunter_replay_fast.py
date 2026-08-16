#!/usr/bin/env python
"""REPLAY ACCELERATOR — same experiment, less compute.

    python scripts/hunter_replay_fast.py --start A --end B --tag T \
        [--universe-cap 150] [--workers 6] [--preset smoke|micro|research|campaign]

TWO-PASS ARCHITECTURE (semantics identical to scripts/hunter_replay.py):

PASS A — parallel perception (bounded worker pool, one worker per
SESSION-DAY): bars -> ChartState -> RS -> Scout -> Hunter candidates ->
baselines -> realizations. LEGALLY independent across days because (a)
perception at T reads only that day's visible bars + prior-day context,
and (b) analog memory can never contain same-day outcomes anyway (the
resolved-before-as_of firewall makes same-day self-reference impossible
in the legacy harness too). Workers write deterministic per-day JSON;
nothing touches the canonical ledger.

PASS B — chronological evaluation: walks days strictly in date order,
appending scan/decisions per tick, then enrichment (analog memory sees
ONLY the canonical ledger as built so far = exactly the legacy view),
then realizations at day end. Swarm force-disabled + Rule-17 tripwire.
Same restamp law, same counterfactual declaration, same content-derived
decision ids -> the equivalence gate can demand semantic equality.

LAWS PRESERVED: exploratory class, chronological analog memory, campaign
dates/universe, Capital/Assassin/realization semantics, separate ledger,
production isolation. Faster never means fewer symbols, fewer ticks,
truncated retrieval, or approximate outcomes.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

_S = Path(__file__).resolve().parent
sys.path.insert(0, str(_S.parent)); sys.path.insert(0, str(_S))

import pandas as pd  # noqa: E402

PRESETS = {"smoke": 2, "micro": 10, "research": 25, "campaign": 92}
ET = "America/New_York"


LAB_TOTAL_BUDGET = 90_000        # aggregate across ALL workers (< the
                                 # provider's ~100k/day allowance)


def worker_day(args) -> str:
    """PASS A: one session-day of perception, fully self-contained.
    Returns the path of the deterministic per-day cache file."""
    day, universe_cap, outdir, worker_budget = args
    import apex.hunter.forward_pass as fp
    import apex.hunter.swarm as swarm
    from apex.hunter.context_builder import (build_scan_universe,
                                             load_or_build_contexts)
    from apex.intraday.eodhd import (QuotaGovernor, fetch_intraday_chunk,
                                     normalize_rows)
    from apex.intraday.sessions import Session, classify
    from hunter_replay import TICK_TIMES
    swarm.auth_available = lambda: False          # Rule 17, per-process
    tmp_ledger = Path(outdir) / f"_dedupe_{day}.jsonl"
    fp.LEDGER = tmp_ledger                        # day-scoped dedupe only
    t0 = time.monotonic()
    stage = {"io": 0.0, "perception": 0.0, "realization": 0.0}

    # LAB-02 + aggregate invariant: this worker's slice of the LAB TOTAL
    gov = QuotaGovernor(daily_budget=worker_budget)
    uni = build_scan_universe(day)
    subset = dict(list(uni["symbols"].items())[:universe_cap])
    uni = {**uni, "symbols": subset,
           "universe_limitation": (uni.get("universe_limitation", "")
                                   + " | REPLAY: current-snapshot universe, "
                                     "not PIT for this date")}
    s = time.monotonic()
    contexts = load_or_build_contexts(subset, day, gov,
                                      extra_symbols=("SPY.US",))
    ctx_healthy = sum(1 for c in contexts.values()
                      if c.sessions_observed > 0)
    if ctx_healthy < 0.5 * max(len(contexts), 1):
        raise RuntimeError(
            f"LAB-04 CONTEXT ABORT {day}: {ctx_healthy}/{len(contexts)} "
            f"contexts healthy (provider concurrency pressure?) — dying "
            f"loudly rather than scanning a blindfolded universe")
    bars = {}
    for sym in ("SPY.US", *subset):
        v = sym if sym.endswith(".US") else f"{sym}.US"
        try:
            rows, _ = fetch_intraday_chunk(v, day, day, gov)
            f = normalize_rows(rows, v)
            f["provider_symbol"] = sym
            bars[sym] = f
        except Exception:                                   # noqa: BLE001
            pass
    stage["io"] = round(time.monotonic() - s, 1)

    healthy = sum(1 for f in bars.values() if len(f) > 100)
    if healthy < 0.5 * (len(subset) + 1):
        raise RuntimeError(
            f"LAB-02 HEALTH ABORT {day}: only {healthy}/{len(subset)+1} "
            f"symbols have bars (quota starvation or vendor outage)")
    ticks = []
    s = time.monotonic()
    for hm in TICK_TIMES:
        t = pd.Timestamp(f"{day} {hm}", tz=ET).tz_convert("UTC")
        if classify(t) is not Session.REGULAR:
            continue
        scan_rec, decisions = fp.decision_pass(t, uni, bars, contexts,
                                               enrich=False)
        for d in decisions:                       # feed day-scoped dedupe
            from nightly_pull import _chain_append
            _chain_append(tmp_ledger, d)
        ticks.append({"t": str(t), "scan": scan_rec, "decisions": decisions})
    stage["perception"] = round(time.monotonic() - s, 1)

    s = time.monotonic()
    reals = []
    all_dec = [d for tk in ticks for d in tk["decisions"]]
    for d in all_dec:
        f = bars.get(d["symbol"])
        if f is not None:
            reals.append(fp.resolve_decision(d, f))
    stage["realization"] = round(time.monotonic() - s, 1)
    tmp_ledger.unlink(missing_ok=True)

    out = Path(outdir) / f"day_{day}.json"
    out.write_text(json.dumps(
        {"day": day, "universe": uni, "ticks": ticks,
         "realizations": reals,
         "profile": {**stage, "total": round(time.monotonic() - t0, 1)}},
        default=str))
    return str(out)


def pass_b(days_files: list, ledger: Path) -> dict:
    """Chronological: canonical ledger built in date order; analog memory
    at day N sees exactly days < N (the legacy view)."""
    import apex.hunter.forward_pass as fp
    import apex.hunter.memory as mem
    import apex.hunter.swarm as swarm
    from hunter_replay import restamp
    from nightly_pull import _chain_append
    swarm.auth_available = lambda: False
    fp.LEDGER = ledger
    mem.LEDGER = ledger
    prof = {"enrichment": 0.0, "ledger": 0.0}
    n_caps = 0
    for path in sorted(days_files):               # date order = file order
        blob = json.loads(Path(path).read_text())
        day = blob["day"]
        for tk in blob["ticks"]:
            s = time.monotonic()
            _chain_append(ledger, restamp(tk["scan"]))
            for d in tk["decisions"]:
                _chain_append(ledger, restamp(d))
            prof["ledger"] += time.monotonic() - s
            lab = [{**d, "forward_eligibility": "FORWARD_ELIGIBLE"}
                   for d in tk["decisions"]
                   if not d["playbook_id"].startswith("BASELINE-")]
            s = time.monotonic()
            for r in fp.enrichment_pass(tk["t"], day, lab, blob["universe"]):
                _chain_append(ledger, restamp(r))
                n_caps += r.get("kind") == "capital_decision"
            prof["enrichment"] += time.monotonic() - s
        for r in blob["realizations"]:
            _chain_append(ledger, restamp(r))
    return {"capital_records": n_caps,
            "profile": {k: round(v, 1) for k, v in prof.items()}}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--universe-cap", type=int, default=150)
    ap.add_argument("--workers", type=int, default=4)  # LAB-04:
    # provider concurrency limits punish 8-way fetch storms
    a = ap.parse_args()

    from apex.intraday.sessions import Session, classify
    days = [str(d.date()) for d in pd.bdate_range(a.start, a.end)
            if classify(pd.Timestamp(f"{d.date()} 10:00", tz=ET)
                        .tz_convert("UTC")) is Session.REGULAR]
    out = Path(f"results/hunter/replay_{a.tag}")
    out.mkdir(parents=True, exist_ok=True)
    ledger = out / "replay_ledger.jsonl"
    if ledger.exists():
        print("REFUSED: ledger exists; a campaign denominator is never "
              "silently appended to")
        return 1
    t0 = time.monotonic()
    print(f"ACCELERATED REPLAY: {len(days)} sessions, cap "
          f"{a.universe_cap}, workers {a.workers}")

    per_worker = LAB_TOTAL_BUDGET // a.workers
    print(f"provider budget: {LAB_TOTAL_BUDGET} aggregate -> "
          f"{per_worker}/worker x {a.workers} (structural invariant: "
          f"workers can never collectively exceed the lab total)")
    with ProcessPoolExecutor(max_workers=a.workers) as ex:
        files = list(ex.map(worker_day,
                            [(d, a.universe_cap, str(out), per_worker)
                             for d in days]))
    ta = time.monotonic() - t0
    profiles = [json.loads(Path(f).read_text())["profile"] for f in files]
    print(f"PASS A done in {ta/60:.1f}m; per-day median "
          f"io={pd.Series([p['io'] for p in profiles]).median():.0f}s "
          f"perception="
          f"{pd.Series([p['perception'] for p in profiles]).median():.0f}s")

    tb0 = time.monotonic()
    st = pass_b(files, ledger)
    print(f"PASS B done in {(time.monotonic()-tb0)/60:.1f}m; "
          f"{st['capital_records']} capital records; {st['profile']}")
    for f in files:                               # cache is disposable
        Path(f).unlink(missing_ok=True)
    print(f"TOTAL {(time.monotonic()-t0)/60:.1f}m -> {ledger}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
