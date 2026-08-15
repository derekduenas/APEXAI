#!/usr/bin/env python
"""Hunter calibration scoreboard + funnel diagnostics — read-only over the
one forward ledger.

    python scripts/hunter_scoreboard.py            # all sessions to date

Reports, per playbook x horizon, ONLY forward-eligible scored decisions:
n, hit rate, mean/median return, MAE/MFE, target-before-stop — against
every frozen baseline twice: on IDENTICAL SUBJECTS (the sessions/symbols
that playbook decided on) and on the full watchlist (the
ALWAYS-TAKE-SCANNER-CANDIDATE aggregate). NO-TRADE is the implicit zero
row. N_raw and N_effective are never reported apart; anything below 10
effective observations is stamped PRELIMINARY — a direction of a rumor,
not a result. Ineligible decisions are counted, never scored. Mixed
evidence classes refuse (law). Diagnostics describe; they never retune.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

_S = Path(__file__).resolve().parent
sys.path.insert(0, str(_S.parent)); sys.path.insert(0, str(_S))

import numpy as np  # noqa: E402

from apex.hunter.contracts import HORIZONS_MINUTES  # noqa: E402
from apex.hunter.evidence import require_unmixed  # noqa: E402
from apex.hunter.neff import effective_sample  # noqa: E402

LEDGER = Path("results/hunter/forward_ledger.jsonl")
OUT = Path("results/hunter")
PRELIMINARY_BELOW = 10


def load_ledger(ledger: Path = LEDGER) -> dict:
    kinds: dict = {"forward_state": [], "scan": [], "decision": [],
                   "realization": [], "capital_decision": []}
    if ledger.exists():
        for line in ledger.read_text().splitlines():
            if not line.strip():
                continue
            r = json.loads(line)                 # chain entries are FLAT
            if r.get("kind") in kinds:
                kinds[r["kind"]].append(r)
    return kinds


def horizon_stats(rows: list, h: int) -> dict | None:
    rets = [r[f"ret_{h}m"] for r in rows
            if r.get(f"ret_{h}m") is not None]
    if not rets:
        return None
    out = {"n": len(rets),
           "hit_rate": round(float(np.mean([x > 0 for x in rets])), 3),
           "mean_ret": round(float(np.mean(rets)), 5),
           "median_ret": round(float(np.median(rets)), 5)}
    maes = [r[f"mae_{h}m"] for r in rows if r.get(f"mae_{h}m") is not None]
    mfes = [r[f"mfe_{h}m"] for r in rows if r.get(f"mfe_{h}m") is not None]
    if maes:
        out["mean_mae"] = round(float(np.mean(maes)), 5)
    if mfes:
        out["mean_mfe"] = round(float(np.mean(mfes)), 5)
    return out


def build_scoreboard(kinds: dict) -> dict:
    require_unmixed({r.get("evidence_class")
                     for k in ("decision", "realization", "scan",
                               "capital_decision")
                     for r in kinds.get(k, [])} or
                    {"EODHD_FORWARD_OBSERVATION"})
    realized = {r["decision_id"]: r for r in kinds["realization"]
                if r.get("resolvable")}
    decisions = kinds["decision"]
    eligible = [d for d in decisions
                if d.get("forward_eligibility") == "FORWARD_ELIGIBLE"]
    ineligible = [d for d in decisions
                  if d.get("forward_eligibility") != "FORWARD_ELIGIBLE"]
    scored = [d for d in eligible if d["decision_id"] in realized]

    def merged(rows):
        return [{**d, **realized[d["decision_id"]]} for d in rows]

    by_pid: dict = {}
    for d in scored:
        by_pid.setdefault(d["playbook_id"], []).append(d)

    playbook_ids = sorted(p for p in by_pid if not p.startswith("BASELINE-"))
    baseline_ids = sorted(p for p in by_pid if p.startswith("BASELINE-"))

    board: dict = {}
    for pid in (*playbook_ids, *baseline_ids):
        rows = merged(by_pid[pid])
        acct = effective_sample(by_pid[pid])["per_playbook"][pid]
        entry = {"n_raw": acct["n_raw"], "n_effective": acct["n_effective"],
                 "n_sessions": acct["n_sessions"],
                 "n_symbols": acct["n_symbols"],
                 "status": ("PRELIMINARY"
                            if acct["n_effective"] < PRELIMINARY_BELOW
                            else "REPORTABLE"),
                 "horizons": {}}
        for h in HORIZONS_MINUTES:
            s = horizon_stats(rows, h)
            if s:
                entry["horizons"][f"{h}m"] = s
        tbs = [r for r in rows if r.get("target_before_stop") is not None]
        if tbs:
            entry["target_before_stop_rate"] = round(float(np.mean(
                [r["target_before_stop"] for r in tbs])), 3)
            entry["same_bar_ambiguous_n"] = int(sum(
                r.get("same_bar_ambiguous", False) for r in tbs))
        board[pid] = entry

    # identical-subject baseline comparison per real playbook
    comparisons: dict = {}
    for pid in playbook_ids:
        subjects = {(d["session_date"], d["symbol"]) for d in by_pid[pid]}
        comp: dict = {}
        for bid in baseline_ids:
            match = [d for d in by_pid[bid]
                     if (d["session_date"], d["symbol"]) in subjects]
            rows = merged(match)
            comp[bid] = {f"{h}m": horizon_stats(rows, h)
                         for h in HORIZONS_MINUTES}
        comparisons[pid] = {"n_subjects": len(subjects),
                            "baselines_on_identical_subjects": comp}

    # the three frozen relationships (docs/HUNTER-GRADUATION-CRITERIA.md):
    # R1 hunter-vs-scanner and R3 selected-vs-rejected isolate SELECTION by
    # scoring both cohorts under the SAME naive instrument
    # (BASELINE-MOMENTUM), so direction skill and subject-selection skill
    # are never conflated. R2 is the identical-subject table above.
    selected_subjects = {(d["session_date"], d["symbol"])
                         for pid in playbook_ids for d in by_pid[pid]}
    mom = by_pid.get("BASELINE-MOMENTUM", [])
    sel_rows = merged([d for d in mom
                       if (d["session_date"], d["symbol"])
                       in selected_subjects])
    rej_rows = merged([d for d in mom
                       if (d["session_date"], d["symbol"])
                       not in selected_subjects])
    relationships = {
        "instrument": "BASELINE-MOMENTUM on both cohorts",
        "selected_subjects": len(selected_subjects),
        "rejected_watchlist_subjects": len(
            {(d["session_date"], d["symbol"]) for d in mom}
            - selected_subjects),
        "selected_cohort": {f"{h}m": horizon_stats(sel_rows, h)
                            for h in HORIZONS_MINUTES},
        "rejected_cohort": {f"{h}m": horizon_stats(rej_rows, h)
                            for h in HORIZONS_MINUTES},
        "note": ("DESCRIPTIVE until protocol §10 checkpoint; PRELIMINARY "
                 "below 10 effective; separation is a finding to record, "
                 "never a threshold to retune toward"),
    }

    # capital layer view: final states + reason codes, and the seed of the
    # rejected-for-economics vs taken comparison (rejections are PRESERVED)
    cap_recs = kinds.get("capital_decision", [])
    capital = {
        "n": len(cap_recs),
        "final_states": dict(Counter(r["final_state"] for r in cap_recs)),
        "reason_codes": dict(Counter(c for r in cap_recs
                                     for c in r.get("reason_codes", []))),
        "paper_eligible_n": sum(r["final_state"] == "PAPER_ELIGIBLE"
                                for r in cap_recs),
        "note": ("PAPER_ELIGIBLE requires the commissioned Phase 3 forecast "
                 "path; LIVE_ELIGIBLE does not exist"),
    }

    scans = kinds["scan"]
    sig_counts: Counter = Counter()
    for s in scans:
        for w in s.get("watchlist", []):
            sig_counts.update(w.get("signals", []))
    funnel = {
        "n_scan_ticks": len(scans),
        "sessions": sorted({s["session_date"] for s in scans}),
        "mean_states_computed": (round(float(np.mean(
            [s["states_computed"] for s in scans])), 1) if scans else None),
        "abnormal_per_tick": ({"mean": round(float(np.mean(
            [s["abnormal"] for s in scans])), 1),
            "max": int(max(s["abnormal"] for s in scans))} if scans else None),
        "signal_counts": dict(sig_counts.most_common()),
        "watchlist_symbols_seen": len({w["symbol"] for s in scans
                                       for w in s.get("watchlist", [])}),
    }

    acct_playbooks = effective_sample(
        [d for d in scored if not d["playbook_id"].startswith("BASELINE-")])
    return {
        "generated_from": "forward_ledger.jsonl (read-only)",
        "no_trade_row": {"mean_ret": 0.0, "note": "implicit zero benchmark"},
        "decisions_total": len(decisions),
        "decisions_forward_eligible": len(eligible),
        "decisions_ineligible": len(ineligible),
        "decisions_scored": len(scored),
        "effective_sample_playbooks": {
            k: acct_playbooks[k] for k in
            ("n_raw", "n_effective", "n_sessions")},
        "checkpoint_frozen": ">=40 sessions AND >=100 effective across "
                             ">=2 regimes (protocol §10)",
        "scoreboard": board,
        "identical_subject_comparisons": comparisons,
        "selected_vs_rejected": relationships,
        "capital": capital,
        "funnel": funnel,
    }


def main() -> int:
    kinds = load_ledger()
    sb = build_scoreboard(kinds)
    OUT.mkdir(parents=True, exist_ok=True)
    dates = sb["funnel"]["sessions"]
    tag = dates[-1] if dates else "empty"
    path = OUT / f"scoreboard_{tag}.json"
    path.write_text(json.dumps(sb, indent=1))
    print(f"sessions={len(dates)} decisions={sb['decisions_total']} "
          f"eligible={sb['decisions_forward_eligible']} "
          f"scored={sb['decisions_scored']}")
    for pid, e in sb["scoreboard"].items():
        h60 = e["horizons"].get("60m") or {}
        print(f"  {pid:24s} {e['status']:11s} n={e['n_raw']:3d} "
              f"neff={e['n_effective']:3d} "
              f"60m: hit={h60.get('hit_rate')} mean={h60.get('mean_ret')}")
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
