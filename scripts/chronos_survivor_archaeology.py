"""SURVIVOR ARCHAEOLOGY — was C2EDGE_002 information, or beta in an
EdgeForge costume?

The Campaign #002 survivor: gap_pct LONG, family attempt 3, born
2020-09, ~112 sealed acts, +11.35R, decay-retired 2022-10 — a run
that coincides with a major bull regime. This does not reject it; it
demands the question be asked properly.

PREDECLARED VERDICT RULES (written before the analysis ran):

  The core instrument is a SELECTION PERMUTATION TEST: 2,000 uniform
  random subsets of the same size drawn from the candidate's active
  period; where does the candidate's total R rank?
  p_hat = (1 + #random >= real) / 2001.

  - BASELINE_REPACKAGING     p_hat > 0.05 — the selection is
                             indistinguishable from random day-picking
                             inside the same regime window; the R was
                             the period's, not the signal's
  - NO_EDGE                  net R <= 0
  - INSUFFICIENT_EVIDENCE    < 30 acts, or every regime cell < 10 acts
  - CONDITIONAL_EDGE_CANDIDATE  selection significant overall but
                             >= 70% of R concentrated in one regime
                             cell, or significant in only one cell
  - GENERAL_EDGE_CANDIDATE   selection significant and positive in a
                             majority of occupied regime cells

Regimes are defined WITHOUT the candidate's outcomes: trailing 50-day
trend (close vs SMA50) x trailing 20-day vol vs expanding median —
all computed causally from prior data only.

Leave-regime-out transport: re-derive the threshold from discovery
data EXCLUDING one regime, evaluate frozen on that regime's active-
period days. No retuning after observing results.

Everything here is HISTORICAL_REPLAY. Full-family economics stand
beside the survivor and are never replaced by it.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apex.chronos import EVIDENCE_LABEL                       # noqa: E402
from apex.edgeforge.world_foundry import _Rng                 # noqa: E402
from apex.governance.verification import stamp                # noqa: E402

ALPACA = "https://data.alpaca.markets/v2"
CODE_PATHS = ["scripts/chronos_survivor_archaeology.py"]

BIRTH_EPOCH_START = "2020-09-01"      # C2EDGE_002 born epoch 2020-09
ACTIVE_START = "2020-10-01"           # trades from the NEXT epoch
ACTIVE_END = "2022-10-31"             # decay-retired
VALIDATION_SESSIONS = 126
N_PERMUTATIONS = 2000


def _get(url, k, s):
    r = urllib.request.Request(url, headers={
        "APCA-API-KEY-ID": k, "APCA-API-SECRET-KEY": s})
    with urllib.request.urlopen(r, timeout=30) as f:
        return json.loads(f.read().decode())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", required=True)
    ap.add_argument("--secret", required=True)
    ap.add_argument("--out", default="results/chronos")
    a = ap.parse_args()
    out = Path(a.out)

    days = _get(f"{ALPACA}/stocks/SPY/bars?timeframe=1Day"
                f"&start=2018-01-01&end=2024-12-31&limit=10000"
                f"&feed=sip&adjustment=raw", a.key, a.secret)["bars"]
    gap, o2c, sessions = {}, {}, []
    closes, ocr = [], []
    sma50, vol20, volmed = {}, {}, {}
    prev = None
    for b in days:
        d = b["t"][:10]
        if prev is not None:
            gap[d] = (b["o"] / prev["c"] - 1) * 100
            o2c[d] = (b["c"] / b["o"] - 1) * 100
            sessions.append(d)
            # regime inputs, strictly from PRIOR data
            if len(closes) >= 50:
                sma50[d] = sum(closes[-50:]) / 50
            if len(ocr) >= 20:
                v = statistics.pstdev(ocr[-20:])
                vol20[d] = v
                hist = [vol20[s2] for s2 in sessions[:-1]
                        if s2 in vol20]
                volmed[d] = (statistics.median(hist) if hist else v)
        closes.append(b["c"])
        if prev is not None:
            ocr.append((b["c"] / b["o"] - 1) * 100)
        prev = b

    def regime_of(d, prior_close):
        t = ("UP" if d in sma50 and prior_close > sma50[d] else
             "DOWN" if d in sma50 else "UNKNOWN")
        v = ("HIVOL" if d in vol20 and vol20[d] > volmed[d]
             else "LOVOL" if d in vol20 else "UNKNOWN")
        return f"{t}_{v}"

    prior_close_of = {}
    pc = None
    for b in days:
        d = b["t"][:10]
        if pc is not None:
            prior_close_of[d] = pc
        pc = b["c"]

    # ---------------- reconstruct the frozen threshold (train-only)
    birth_idx = next(i for i, d in enumerate(sessions)
                     if d >= BIRTH_EPOCH_START)
    knowledge = sessions[:birth_idx]
    disc = knowledge[:-VALIDATION_SESSIONS]
    vals = sorted(gap[d] for d in disc)
    thresh = vals[len(vals) * 4 // 5]

    active = [d for d in sessions if ACTIVE_START <= d <= ACTIVE_END]
    acts = [d for d in active if gap[d] >= thresh]
    act_R = [o2c[d] for d in acts]
    total_real = sum(act_R)

    # ---------------- baselines on IDENTICAL history
    def summarize(rs):
        rs = list(rs)
        eq, peak, mdd = 0.0, 0.0, 0.0
        for r in rs:
            eq += r
            peak = max(peak, eq)
            mdd = min(mdd, eq - peak)
        return {"n": len(rs), "total_R": round(sum(rs), 4),
                "median_R": (round(statistics.median(rs), 4)
                             if rs else "NOT_ESTIMABLE"),
                "favorable_fraction": (round(
                    sum(1 for r in rs if r > 0) / len(rs), 4)
                    if rs else "NOT_ESTIMABLE"),
                "max_drawdown_R": round(mdd, 4)}

    rng = _Rng(77)
    baselines = {
        "CANDIDATE_C2EDGE_002": summarize(act_R),
        "SPY_BUY_HOLD_O2C": summarize(o2c[d] for d in active),
        "SIMPLE_MOMENTUM": summarize(
            (o2c[d] if o2c.get(sessions[sessions.index(d) - 1], 0) > 0
             else -o2c[d]) for d in active),
        "SIMPLE_TREND": summarize(
            (o2c[d] if d in sma50
             and prior_close_of[d] > sma50[d] else 0.0)
            for d in active),
        "RANDOM_ELIGIBLE": summarize(
            (o2c[d] if rng.random() > 0.5 else -o2c[d])
            for d in active),
        "NO_TRADE": summarize([0.0] * len(active))}

    # beta and capture: candidate holds market on act days, flat else
    mkt = [o2c[d] for d in active]
    cand = [o2c[d] if d in set(acts) else 0.0 for d in active]
    mbar, cbar = (sum(mkt) / len(mkt)), (sum(cand) / len(cand))
    cov = sum((m - mbar) * (c - cbar) for m, c in zip(mkt, cand)) \
        / len(mkt)
    var = sum((m - mbar) ** 2 for m in mkt) / len(mkt)
    beta = cov / var if var else None
    up = [d for d in active if o2c[d] > 0]
    dn = [d for d in active if o2c[d] < 0]
    up_cap = (sum(o2c[d] for d in up if d in set(acts))
              / sum(o2c[d] for d in up)) if up else None
    dn_cap = (sum(o2c[d] for d in dn if d in set(acts))
              / sum(o2c[d] for d in dn)) if dn else None

    # ---------------- THE CORE TEST: selection vs random same-period
    n_acts = len(acts)
    rng2 = _Rng(101)
    perm_totals = []
    pool = [o2c[d] for d in active]
    for _ in range(N_PERMUTATIONS):
        chosen, seen = 0.0, set()
        while len(seen) < n_acts:
            j = rng2.randint(0, len(pool) - 1)
            if j not in seen:
                seen.add(j)
                chosen += pool[j]
        perm_totals.append(chosen)
    exceed = sum(1 for t in perm_totals if t >= total_real)
    p_hat = (1 + exceed) / (N_PERMUTATIONS + 1)
    srt = sorted(perm_totals)
    selection = {
        "n_acts": n_acts, "real_total_R": round(total_real, 4),
        "random_subset_median": round(statistics.median(srt), 4),
        "random_subset_p90": round(srt[int(0.9 * len(srt))], 4),
        "random_subset_max": round(srt[-1], 4),
        "exceedance": exceed, "p_hat": round(p_hat, 6),
        "question": "did PICKING these days add anything beyond "
                    "being long in this period?"}

    # ---------------- regime decomposition (regimes defined causally)
    by_regime = {}
    for d in acts:
        rg = regime_of(d, prior_close_of[d])
        by_regime.setdefault(rg, []).append(o2c[d])
    regime_rows = {rg: summarize(v) for rg, v in by_regime.items()}
    occupied = {rg: r for rg, r in regime_rows.items() if r["n"] >= 10}
    conc = (max((abs(r["total_R"]) for r in regime_rows.values()),
                default=0.0) / abs(total_real)
            if total_real else None)

    # within-regime selection test for the dominant cell
    dom = max(regime_rows, key=lambda rg: regime_rows[rg]["total_R"],
              default=None)
    within = None
    if dom:
        cell_days = [d for d in active
                     if regime_of(d, prior_close_of[d]) == dom]
        cell_acts = [d for d in acts
                     if regime_of(d, prior_close_of[d]) == dom]
        if len(cell_days) > len(cell_acts) >= 10:
            cpool = [o2c[d] for d in cell_days]
            creal = sum(o2c[d] for d in cell_acts)
            rng3 = _Rng(131)
            ctot = []
            for _ in range(N_PERMUTATIONS):
                chosen, seen = 0.0, set()
                while len(seen) < len(cell_acts):
                    j = rng3.randint(0, len(cpool) - 1)
                    if j not in seen:
                        seen.add(j)
                        chosen += cpool[j]
                ctot.append(chosen)
            cex = sum(1 for t in ctot if t >= creal)
            within = {"regime": dom, "n_cell_days": len(cell_days),
                      "n_cell_acts": len(cell_acts),
                      "real_cell_R": round(creal, 4),
                      "p_hat": round((1 + cex) /
                                     (N_PERMUTATIONS + 1), 6),
                      "question": "INSIDE the dominant regime, does "
                                  "day-picking still beat random?"}

    # ---------------- leave-regime-out transport
    lro = {}
    for omit in sorted({regime_of(d, prior_close_of[d])
                        for d in disc if d in prior_close_of}):
        kept = [d for d in disc if d in prior_close_of
                and regime_of(d, prior_close_of[d]) != omit]
        if len(kept) < 100:
            lro[omit] = {"verdict": "INSUFFICIENT_EVIDENCE",
                         "n_disc_kept": len(kept)}
            continue
        v2 = sorted(gap[d] for d in kept)
        th2 = v2[len(v2) * 4 // 5]
        omit_days = [d for d in active
                     if regime_of(d, prior_close_of[d]) == omit]
        omit_acts = [o2c[d] for d in omit_days if gap[d] >= th2]
        lro[omit] = ({"verdict": "INSUFFICIENT_EVIDENCE",
                      "n_acts": len(omit_acts)}
                     if len(omit_acts) < 10 else
                     {"verdict": "EVALUATED",
                      "n_acts": len(omit_acts),
                      "total_R": round(sum(omit_acts), 4),
                      "median_R": round(
                          statistics.median(omit_acts), 4)})

    # ---------------- PREDECLARED VERDICT
    if total_real <= 0:
        verdict = "NO_EDGE"
    elif n_acts < 30 or not occupied:
        verdict = "INSUFFICIENT_EVIDENCE"
    elif p_hat > 0.05:
        verdict = "BASELINE_REPACKAGING"
    else:
        pos_cells = sum(1 for r in occupied.values()
                        if r["total_R"] > 0)
        if (conc is not None and conc >= 0.7) or pos_cells <= 1:
            verdict = "CONDITIONAL_EDGE_CANDIDATE"
        elif pos_cells > len(occupied) / 2:
            verdict = "GENERAL_EDGE_CANDIDATE"
        else:
            verdict = "CONDITIONAL_EDGE_CANDIDATE"

    report = stamp({
        "kind": "chronos_survivor_archaeology",
        "candidate": "C2EDGE_002 (gap_pct LONG, family attempt 3)",
        "evidence_label": EVIDENCE_LABEL,
        "active_period": f"{ACTIVE_START}..{ACTIVE_END}",
        "frozen_threshold": round(thresh, 4),
        "baselines_identical_history": baselines,
        "market_beta": (round(beta, 4) if beta is not None
                        else "NOT_ESTIMABLE"),
        "up_capture": (round(up_cap, 4) if up_cap is not None
                       else "NOT_ESTIMABLE"),
        "down_capture": (round(dn_cap, 4) if dn_cap is not None
                         else "NOT_ESTIMABLE"),
        "selection_permutation_test": selection,
        "regime_decomposition": regime_rows,
        "regime_concentration": (round(conc, 4)
                                 if conc is not None else None),
        "within_dominant_regime_test": within,
        "leave_regime_out": lro,
        "full_family_reference": {
            "all_attempts_R": 9.1009, "attempt_1_R": -1.8737,
            "attempt_3_R": 11.352, "attempt_4_R": -0.3774,
            "law": "survivor economics never replace full-family "
                   "economics"},
        "verdict": verdict}, CODE_PATHS)
    (out / "survivor_archaeology.json").write_text(
        json.dumps(report, indent=1, default=str))
    print(json.dumps({
        "candidate_total_R": round(total_real, 4),
        "n_acts": n_acts,
        "market_beta": report["market_beta"],
        "selection_p_hat": selection["p_hat"],
        "random_subset_median": selection["random_subset_median"],
        "regimes": {rg: {"n": r["n"], "R": r["total_R"]}
                    for rg, r in regime_rows.items()},
        "within_dominant": (within or {}).get("p_hat"),
        "leave_regime_out": {k: v.get("verdict") if "total_R" not in v
                             else v["total_R"] for k, v in lro.items()},
        "VERDICT": verdict}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
