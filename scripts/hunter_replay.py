#!/usr/bin/env python
"""THE REPLAY LABORATORY — watch the FROZEN Profit Machine behave on
historical markets, minute-by-minute, without touching Epoch 1.

    python scripts/hunter_replay.py --start 2026-08-13 --end 2026-08-14 \
        [--tag smoke] [--universe-cap 40]

THE LAWS OF THE LAB (each enforced in code, not prose):

1. EVIDENCE: every record is re-stamped EODHD_HISTORICAL_EXPLORATORY
   (survivorship-limited by decree) into a SEPARATE replay ledger.
   The evidence law already forbids graduation/calibration/Credit-5/live
   uses. The lab observes behavior; it can never confirm anything.
2. NO LLM IN REPLAY (Rule 17): swarm auth is force-disabled for the
   process and a tripwire ABORTS if any swarm view reports OK. An
   LLM-mediated component is never backtested.
3. ELIGIBILITY COUNTERFACTUAL, declared: historically-timed decisions
   are NOT forward-eligible (the birth law self-enforces). To observe
   capital behavior the lab evaluates COPIES with
   forward_eligibility=FORWARD_ELIGIBLE and stamps
   replay_counterfactual_eligibility=true on every record. The class
   stamp (law 1) keeps this forever non-confirmatory.
4. PRODUCTION UNTOUCHED: the harness redirects the module ledger paths
   for this process only; the production forward ledger is never read
   or written. The machine executed is the frozen commit's code, as-is.
5. UNIVERSE LIMITATION recorded: the scan universe is the CURRENT
   snapshot's liquidity tier (not PIT for the replay dates) — one more
   reason this is a laboratory, not an exam.

Output: replay ledger + a funnel report (Scout -> Hunter -> Oracle ->
Assassin wounded/clean -> Capital states, with realized 60m EV per
cohort) written to results/hunter/replay_<tag>/.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_S = Path(__file__).resolve().parent
sys.path.insert(0, str(_S.parent)); sys.path.insert(0, str(_S))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from nightly_pull import _chain_append  # noqa: E402

import apex.hunter.forward_pass as fp  # noqa: E402
import apex.hunter.memory as mem  # noqa: E402
import apex.hunter.swarm as swarm  # noqa: E402
from apex.hunter.context_builder import (  # noqa: E402
    build_scan_universe, load_or_build_contexts,
)
from apex.intraday.eodhd import (  # noqa: E402
    QuotaGovernor, fetch_intraday_chunk, normalize_rows,
)
from apex.intraday.sessions import Session, classify  # noqa: E402

ET = "America/New_York"
TICK_TIMES = [f"{h:02d}:{m:02d}" for h in range(9, 16)
              for m in (0, 15, 30, 45) if (h, m) >= (9, 45)]


def restamp(record: dict) -> dict:
    """LAW 1 + LAW 3: historical-exploratory class (limitation flag added
    by the evidence module's semantics) + counterfactual marker."""
    r = dict(record)
    r["evidence_class"] = "EODHD_HISTORICAL_EXPLORATORY"
    r["HISTORICAL_PROVIDER_SURVIVORSHIP_LIMITATION"] = True
    r["replay_counterfactual_eligibility"] = True
    if (r.get("kind") == "forecast_bundle"
            and (r.get("swarm_view") or {}).get("status") == "OK"):
        raise RuntimeError("RULE 17 TRIPWIRE: an LLM view reached the "
                           "replay; aborting the laboratory")
    return r


LAB_DAILY_BUDGET = 90_000        # LAB-02: labs need lab-scale budgets


def replay_day(day: str, gov, ledger: Path, universe_cap: int) -> dict:
    uni = build_scan_universe(day)
    subset = dict(list(uni["symbols"].items())[:universe_cap])
    uni = {**uni, "symbols": subset,
           "universe_limitation": (uni.get("universe_limitation", "")
                                   + " | REPLAY: current-snapshot universe, "
                                     "not PIT for this date")}
    contexts = load_or_build_contexts(subset, day, gov,
                                      extra_symbols=("SPY.US",))
    bars = {}
    for s in ("SPY.US", *subset):
        v = s if s.endswith(".US") else f"{s}.US"
        try:
            rows, _ = fetch_intraday_chunk(v, day, day, gov)
            f = normalize_rows(rows, v)
            f["provider_symbol"] = s
            bars[s] = f
        except Exception as e:                              # noqa: BLE001
            print(f"  fetch {s}: {type(e).__name__}")
    stats = {"ticks": 0, "decisions": 0, "capital": 0}
    # LAB-02: a starving replay must die loudly, never race through
    # hollow days that later masquerade as findings
    healthy = sum(1 for f in bars.values() if len(f) > 100)
    if healthy < 0.5 * (len(subset) + 1):
        raise RuntimeError(
            f"LAB-02 HEALTH ABORT {day}: only {healthy}/{len(subset)+1} "
            f"symbols have bars (quota starvation or vendor outage)")
    for hm in TICK_TIMES:
        t = pd.Timestamp(f"{day} {hm}", tz=ET).tz_convert("UTC")
        if classify(t) is not Session.REGULAR:
            continue
        scan_rec, decisions = fp.decision_pass(t, uni, bars, contexts,
                                               enrich=False)
        _chain_append(ledger, restamp(scan_rec))
        for d in decisions:
            _chain_append(ledger, restamp(d))
        # LAW 3: capital observed under the declared counterfactual
        lab = [{**d, "forward_eligibility": "FORWARD_ELIGIBLE"}
               for d in decisions
               if not d["playbook_id"].startswith("BASELINE-")]
        for r in fp.enrichment_pass(t, day, lab, uni):
            _chain_append(ledger, restamp(r))
            stats["capital"] += r.get("kind") == "capital_decision"
        stats["ticks"] += 1
        stats["decisions"] += len(decisions)
    for d in fp.unrealized_decisions(day, ledger):
        f = bars.get(d["symbol"])
        if f is not None:
            _chain_append(ledger, restamp(fp.resolve_decision(d, f)))
    return stats


def funnel_report(ledger: Path) -> dict:
    rows = [json.loads(x) for x in ledger.read_text().splitlines()
            if x.strip()]
    by = {}
    for r in rows:
        by.setdefault(r.get("kind"), []).append(r)
    realized = {r["decision_id"]: r for r in by.get("realization", [])
                if r.get("resolvable")}

    def ev(ids):
        rets = [realized[i]["ret_60m"] for i in ids
                if i in realized and realized[i].get("ret_60m") is not None]
        return {"n": len(ids), "n_scored": len(rets),
                "ev_60m": round(float(np.mean(rets)), 5) if rets else None,
                "hit_60m": round(float(np.mean([x > 0 for x in rets])), 3)
                if rets else None}

    dec = [d for d in by.get("decision", [])
           if not d["playbook_id"].startswith("BASELINE-")]
    base = [d for d in by.get("decision", [])
            if d["playbook_id"] == "BASELINE-MOMENTUM"]
    reviews = by.get("assassin_review", [])
    clean = {r["decision_id"] for r in reviews
             if r.get("verdict") == "SURVIVED_CLEAN"}
    wounded = {r["decision_id"] for r in reviews
               if r.get("verdict") == "SURVIVED_WOUNDED"}
    caps = by.get("capital_decision", [])
    observe = {c["decision_id"] for c in caps
               if c.get("final_state") == "OBSERVE"}
    return {
        "evidence_class": "EODHD_HISTORICAL_EXPLORATORY (laboratory only; "
                          "can never graduate anything)",
        "scan_ticks": len(by.get("scan", [])),
        "abnormal_total": sum(s.get("abnormal", 0)
                              for s in by.get("scan", [])),
        "funnel": {
            "scout_watchlist_baseline": ev([d["decision_id"] for d in base]),
            "hunter_matched": ev([d["decision_id"] for d in dec]),
            "assassin_survived_clean": ev(list(clean)),
            "assassin_wounded": ev(list(wounded)),
            "capital_observe": ev(list(observe)),
        },
        "capital_states": {k: sum(1 for c in caps
                                  if c.get("final_state") == k)
                           for k in ("OBSERVE", "WATCH", "NO_TRADE",
                                     "REFUSED")},
        "doctrine": "economic quality should RISE down the funnel; a stage "
                    "that does not raise it loses its seat (finding, not "
                    "knob)"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--tag", default="replay")
    ap.add_argument("--universe-cap", type=int, default=40)
    a = ap.parse_args()

    # LAW 2: no LLM in the laboratory, ever
    swarm.auth_available = lambda: False
    # LAW 4: this process reads/writes ONLY the replay ledger
    out = Path(f"results/hunter/replay_{a.tag}")
    out.mkdir(parents=True, exist_ok=True)
    ledger = out / "replay_ledger.jsonl"
    fp.LEDGER = ledger
    mem.LEDGER = ledger

    gov = QuotaGovernor(daily_budget=LAB_DAILY_BUDGET)
    days = [str(d.date()) for d in pd.bdate_range(a.start, a.end)
            if classify(pd.Timestamp(f"{d.date()} 10:00", tz=ET)
                        .tz_convert("UTC")) is Session.REGULAR]
    print(f"REPLAY LAB: {len(days)} sessions, universe cap "
          f"{a.universe_cap}, ledger {ledger}")
    for day in days:
        st = replay_day(day, gov, ledger, a.universe_cap)
        print(f"  {day}: {st['ticks']} ticks, {st['decisions']} decisions, "
              f"{st['capital']} capital records (quota {gov.used})")
    report = funnel_report(ledger)
    (out / "funnel_report.json").write_text(json.dumps(report, indent=1))
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
