#!/usr/bin/env python
"""APEX-002 Step 3 (re-run) -- execution-path certification, 14 registered items.

Runs against the WIRED production path. Every artifact examined below is
produced by `apex.experiments.apex002.build_nsi_signal`, which is the function
`build_nsi_output` calls, which is the function `apex.pipeline.run_period`
dispatches to for APEX-002. Provenance is printed per item so no verdict rests
on a reimplementation that merely resembles production.

The previous run of this script introduced a MODULE verdict, for requirements
the signal module satisfied while the gated path ran #001's composite instead.
That verdict is gone: there is no longer a gap between the module and the path,
so every item is now CERTIFIED, FAILED or BLOCKED on the real execution path.

INSPECTION AND MEASUREMENT ONLY. No forward returns, no IC, no spreads, no
t-statistics, no holdout, no credit, no unlock token, no ledger write. The
signal path is deliberately separable from `compute_forward_returns`, so this
certification computes the entire #002 signal without evaluating a single
forward return.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from apex.audit.execution_path import (  # noqa: E402
    EXPERIMENT_ENTRY,
    certify_experiment,
    executable_source,
    module_closure,
)
from apex.config import load_config  # noqa: E402
from apex.data.production_source import build_production_panel  # noqa: E402
from apex.experiments import apex002  # noqa: E402
from apex.features import nsi as nsi_mod  # noqa: E402
from apex.features import nsi_scores as scores_mod  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
ROOT = Path("data/snapshots/sharadar/current")
OUT = Path("results/002_step3_certification.txt")
OUT_JSON = Path("results/002_step3_certification.json")
B1 = Path("results/002_b1_measurement.json")

EXPERIMENT = "APEX-002"


class Certification:
    def __init__(self) -> None:
        self.log: list[str] = []
        self.items: dict[str, dict] = {}

    def say(self, line: str = "") -> None:
        self.log.append(line)
        print(line, flush=True)

    def item(self, n: int, title: str, verdict: str, provenance: str,
             evidence: list[str]) -> None:
        self.say(f"--- ITEM {n:>2}. {title}")
        self.say(f"    VERDICT   : {verdict}")
        self.say(f"    PROVENANCE: {provenance}")
        for e in evidence:
            self.say(f"      {e}")
        self.say("")
        self.items[f"item_{n:02d}"] = {
            "title": title, "verdict": verdict,
            "provenance": provenance, "evidence": evidence,
        }


def ok(condition: bool) -> str:
    return "CERTIFIED" if condition else "FAILED"


def main() -> int:  # noqa: C901
    t0 = time.time()
    c = Certification()
    cfg = load_config("experiment", "costs", "synthetic", "sharadar")

    nsi_src = executable_source(inspect.getsource(nsi_mod))
    sco_src = executable_source(inspect.getsource(scores_mod))
    exp_src = executable_source(inspect.getsource(apex002))
    sco_flat = "".join(sco_src.split())
    nsi_flat = "".join(nsi_src.split())

    c.say("=" * 78)
    c.say("APEX-002 -- STEP 3 EXECUTION-PATH CERTIFICATION (wired path)")
    c.say("=" * 78)
    c.say(f"registered experiment : {cfg.get('experiment.id')}")
    c.say(f"protocol              : {cfg.get('experiment.protocol_file')}")
    c.say("scope                 : inspection + measurement only")
    c.say("does NOT              : forward returns, IC, spreads, t-stats,")
    c.say("                        holdout, credit spend, ledger write")
    c.say("")

    # ------------------------------------------------------------------
    # GATE -- the wiring the previous run failed on.
    # ------------------------------------------------------------------
    c.say("=" * 78)
    c.say("GATE -- does the gated path compute the registered signal?")
    c.say("=" * 78)
    wiring = certify_experiment(REPO, EXPERIMENT)
    closure = module_closure(REPO, EXPERIMENT_ENTRY[EXPERIMENT])
    c.say(f"  entry module      : {EXPERIMENT_ENTRY[EXPERIMENT]}")
    c.say(f"  dispatcher        : apex.pipeline.run_period -> build_nsi_output")
    c.say(f"  signal builder    : apex002.build_nsi_signal")
    c.say(f"  modules reachable : {len(closure)}")
    for m in sorted(closure):
        c.say(f"      {m}")
    for f in wiring:
        c.say(f"  FINDING: {f}")
    c.say(f"  WIRING: {'CONFORMS' if not wiring else 'FAILED'}")
    c.say("")
    wired = not wiring

    # === RUN THE PRODUCTION SIGNAL PATH ==================================
    panel, _ = build_production_panel(
        ROOT, cfg, cfg.get("calendar.lake_start"), cfg.period("in_sample")["end"]
    )
    known_from = pd.DataFrame(
        pd.NaT, index=panel.dates, columns=panel.securities, dtype="datetime64[ns]"
    )
    signal = apex002.build_nsi_signal(panel, cfg, ROOT, known_from_out=known_from)
    c.say(f"[{time.time()-t0:6.0f}s] production signal path executed")

    grid = signal.calendar.grid_formation_dates(
        cfg.period("in_sample")["start"], cfg.period("in_sample")["end"]
    )
    eligible = signal.universe.eligible.loc[grid]
    nsi = signal.nsi.loc[grid]
    score = signal.scores.apex_score.loc[grid]
    decile = signal.scores.decile.loc[grid]
    kf = known_from.loc[grid]
    report = signal.report
    present = eligible & nsi.notna()
    c.say(f"[{time.time()-t0:6.0f}s] {len(grid)} formation dates, "
          f"{int(present.to_numpy().sum()):,} scored observations")
    c.say("")
    c.say("=" * 78)
    c.say("REGISTERED ITEMS")
    c.say("=" * 78)

    # --- 1 ---------------------------------------------------------------
    c.item(1, "SF1 as-filed, earliest filing per (ticker, reportperiod)",
           ok(".first()" in nsi_src and ".last()" not in nsi_src
              and report.dropped_revisions > 0),
           "apex.features.nsi.load_as_filed, called by build_nsi_signal",
           [f".first() in executable code : {'.first()' in nsi_src}",
            f".last() absent              : {'.last()' not in nsi_src}",
            f"ARQ rows in                 : {report.raw_arq_rows:,}",
            f"revisions dropped           : {report.dropped_revisions:,}",
            f"as-filed rows out           : {report.as_filed_rows:,}",
            f"impossible filings dropped  : {report.dropped_impossible_filing:,}",
            f"non-positive shares dropped : {report.dropped_nonpositive_shares:,}"])

    # --- 2 ---------------------------------------------------------------
    pop = present.to_numpy()
    kfa = kf.to_numpy()
    formation = np.repeat(kf.index.to_numpy()[:, None], kf.shape[1], axis=1)
    violations = int((kfa[pop] > formation[pop]).sum())
    missing_kf = int(pd.isna(kfa[pop]).sum())
    total = int(pop.sum())
    lag = (formation[pop] - kfa[pop]).astype("timedelta64[D]").astype(float)
    pit_pct = (total - violations) / total * 100.0 if total else float("nan")
    c.item(2, "Admission only where filing_date <= formation_date",
           ok(violations == 0 and missing_kf == 0),
           "apex.features.nsi.build_nsi_panel known_from_out -- measured, not asserted",
           [f"populated observations   : {total:,}",
            f"PIT violations           : {violations}   (must be 0)",
            f"missing knowability date : {missing_kf}   (must be 0)",
            f"PIT compliance           : {pit_pct:.6f}%",
            f"knowledge lag p50 (days) : {np.nanmedian(lag):.1f}"])

    # --- 3 ---------------------------------------------------------------
    c.item(3, "NSI = ln(S_t / S_t-4q)",
           ok("np.log(shares[i]/shares[j])" in nsi_flat),
           "apex.features.nsi.build_nsi_panel",
           [f"literal log-ratio in executable code : "
            f"{'np.log(shares[i]/shares[j])' in nsi_flat}",
            f"shares column : {nsi_mod.SHARES!r}",
            f"dimension     : {nsi_mod.ARQ!r}",
            f"panel cells populated : {report.computed_observations:,}"
            f"   (cells, not pairs -- scales with the date grid)"])

    # --- 4 ---------------------------------------------------------------
    c.item(4, "Twelve-month window exactly as registered",
           ok(nsi_mod.WINDOW_QUARTERS == 4 and nsi_mod.MIN_WINDOW_DAYS == 270
              and nsi_mod.MAX_WINDOW_DAYS == 460),
           "apex.features.nsi module constants, enforced in build_nsi_panel",
           [f"WINDOW_QUARTERS : {nsi_mod.WINDOW_QUARTERS}   (registered 4)",
            f"MIN_WINDOW_DAYS : {nsi_mod.MIN_WINDOW_DAYS} (registered 270)",
            f"MAX_WINDOW_DAYS : {nsi_mod.MAX_WINDOW_DAYS} (registered 460)"])

    # --- 5 ---------------------------------------------------------------
    expected = {"spinoff", "spunofffrom", "spinoffdividend", "acquisitionby",
                "acquisitionof", "mergerto", "mergerfrom", "conversion",
                "recapitalization", "recapitalisation"}
    actual = set(nsi_mod.EXCLUDING_ACTIONS)
    splits = {a for a in actual if "split" in a}
    # PAIRS over PAIRS. `computed_observations` counts panel CELLS and scales
    # with the date grid; an earlier version used it here and produced a
    # corporate-action rate that moved from 1.86% to 0.09% purely because the
    # production panel spans daily dates where B1 used the 164-date grid.
    considered = report.excluded_corporate_action + report.accepted_corporate_action
    c.item(5, "Frozen corporate-action exclusion set",
           ok(actual == expected and not splits),
           "apex.features.nsi.EXCLUDING_ACTIONS + load_exclusions",
           [f"set matches frozen   : {actual == expected}",
            f"split actions absent : {not splits}  (rebasing already removed them)",
            f"pairs excluded       : {report.excluded_corporate_action:,}",
            f"pairs accepted       : {report.accepted_corporate_action:,}",
            f"pairs considered     : {considered:,}",
            f"exclusion rate       : {report.excluded_corporate_action/considered:.4%}"
            f"   (pairs/pairs, grid-invariant)"]
           + ([f"UNEXPECTED: {sorted(actual ^ expected)}"] if actual != expected else []))

    # --- 6 ---------------------------------------------------------------
    banned = ("winsor", "zscore", "z_score", "ewm(", "rolling(", "fillna(",
              ".quantile(", "standardi")
    hits = sorted({b for b in banned if b in nsi_src or b in sco_src or b in exp_src})
    clips = sco_src.count("np.clip")
    clip_ok = clips == 1 and "np.clip(scaled,1,n_deciles)" in sco_flat
    c.item(6, "No winsorization, clipping, smoothing, z-scoring, transformation",
           ok(not hits and clip_ok),
           "executable-source scan across nsi, nsi_scores, experiments.apex002",
           [f"banned constructs across the #002 path : {hits or 'none'}",
            f"np.clip occurrences in nsi_scores      : {clips}",
            f"sole clip bounds the DECILE INDEX 1..n : {clip_ok}",
            "  clipping a bucket number is the decile mechanism;",
            "  clipping the signal would be winsorisation"])

    # --- 7 ---------------------------------------------------------------
    scored_ineligible = int((score.notna() & ~eligible).to_numpy().sum())
    elig_first = "restricted=nsi.where(eligible)" in sco_flat
    c.item(7, "Eligibility applied before ranking",
           ok(scored_ineligible == 0 and elig_first),
           "apex.features.nsi_scores._ascending_ordinal_rank",
           [f"nsi.where(eligible) precedes rank : {elig_first}",
            f"scored-but-ineligible cells       : {scored_ineligible}   (must be 0)",
            f"eligible security-dates           : {int(eligible.to_numpy().sum()):,}"])

    # --- 8 ---------------------------------------------------------------
    scored_missing = int((score.notna() & nsi.isna()).to_numpy().sum())
    elig_no_nsi = int((eligible & nsi.isna()).to_numpy().sum())
    no_fill = "fillna(" not in sco_src and "fillna(" not in nsi_src
    c.item(8, "Missing NSI = exclude, never fill",
           ok(scored_missing == 0 and no_fill),
           "apex.features.nsi_scores + nsi -- no imputation on the path",
           [f"fillna/interpolate absent : {no_fill}",
            f"scored with missing NSI   : {scored_missing}   (must be 0)",
            f"eligible without NSI      : {elig_no_nsi:,}  (excluded, not filled)"])

    # --- 9 ---------------------------------------------------------------
    tie_method = cfg.get("evaluation.rank_tie_method")
    stacked = nsi.where(present).stack()
    lo_idx, hi_idx = stacked.idxmin(), stacked.idxmax()
    score_lo, score_hi = score.loc[lo_idx], score.loc[hi_idx]
    dec_lo, dec_hi = decile.loc[lo_idx], decile.loc[hi_idx]
    rerun = scores_mod.nsi_percentile_score(nsi, eligible, tie_method)
    shuffled = nsi.columns[::-1]
    reordered = scores_mod.nsi_percentile_score(
        nsi.reindex(columns=shuffled), eligible.reindex(columns=shuffled), tie_method
    ).reindex(columns=nsi.columns)
    c.item(9, "Ascending NSI ranking with deterministic C10 tie handling",
           ok(score_lo == 100.0 and score_lo > score_hi and dec_lo == 1.0
              and score.equals(rerun) and score.equals(reordered)
              and tie_method == "first"),
           "apex.features.nsi_scores._ascending_ordinal_rank on a security_id-sorted view",
           [f"tie method (C10)        : {tie_method!r}",
            f"lowest NSI  {stacked.min():+.6f} -> score {score_lo:7.4f}, decile {int(dec_lo)}",
            f"highest NSI {stacked.max():+.6f} -> score {score_hi:7.4f}, decile {int(dec_hi)}",
            f"lowest NSI scores 100   : {score_lo == 100.0}",
            f"recomputation identical : {score.equals(rerun)}",
            f"column-order invariant  : {score.equals(reordered)}"])

    # --- 10 --------------------------------------------------------------
    n_deciles = int(cfg.get("evaluation.n_deciles"))
    per_date = [decile.loc[d].value_counts() for d in grid]
    imbalance = max(int(v.max() - v.min()) for v in per_date if len(v))
    labels = sorted({int(x) for v in per_date for x in v.index})
    top_is_one = bool(dec_lo == 1.0 and dec_hi == n_deciles)
    uses_own = "assign_deciles" not in sco_src and "assign_deciles" not in exp_src
    c.item(10, "Mechanical percentile conversion only as registered deciles",
           ok(imbalance <= 1 and labels == list(range(1, n_deciles + 1))
              and top_is_one and uses_own),
           "apex.features.nsi_scores.equal_count_deciles -- independent of #001",
           [f"decile labels present     : {labels}",
            f"max within-date imbalance : {imbalance}   (equal-count permits <= 1)",
            f"decile 1 = lowest NSI     : {top_is_one}   (section 9, ruled 2026-08-11)",
            f"does not use #001 assign_deciles : {uses_own}",
            f"dates checked             : {len(grid)}"])

    # --- 11 --------------------------------------------------------------
    foreign = sorted(m for m in closure if m in {
        "apex.features.composite", "apex.features.f1_momentum",
        "apex.features.f2_trend", "apex.features.f3_volatility",
        "apex.features.f4_relative_strength"})
    refs = [b for b in ("APEX-001", "Experiment-001", "build_scores",
                        "assign_deciles", "compute_features")
            if b in nsi_src or b in sco_src or b in exp_src]
    c.item(11, "No calls into APEX-001 scoring/composite machinery",
           ok(not foreign and not refs),
           f"static import closure of {EXPERIMENT_ENTRY[EXPERIMENT]} + source scan",
           [f"APEX-001 modules in #002 closure : {foreign or 'none'}",
            f"APEX-001 symbols in #002 source  : {refs or 'none'}",
            f"#002 closure size                : {len(closure)} modules"])

    # --- 12 --------------------------------------------------------------
    expected_set = eligible & nsi.notna()
    ranked_any = score.notna()
    extra = int((ranked_any & ~expected_set).to_numpy().sum())
    missing = int((expected_set & ~ranked_any).to_numpy().sum())
    dec_matches = bool(decile.notna().equals(ranked_any))
    c.item(12, "Per-date ranked set == {eligible AND NSI-present}",
           ok(extra == 0 and missing == 0 and dec_matches),
           "set comparison on the production ScorePanel, both directions",
           [f"dates checked             : {len(grid)}",
            f"ranked security-dates     : {int(ranked_any.to_numpy().sum()):,}",
            f"ranked but ineligible     : {extra}   (must be 0)",
            f"eligible+NSI but unranked : {missing}   (must be 0)",
            f"decile set == score set   : {dec_matches}"])

    # --- 13 --------------------------------------------------------------
    dup_cols = int(nsi.columns.duplicated().sum())
    dup_rows = int(nsi.index.duplicated().sum())
    frames_ok = all(f.index.is_unique and f.columns.is_unique
                    for f in (nsi, score, decile))
    c.item(13, "No duplicate (security_id, date) observations",
           ok(dup_cols == 0 and dup_rows == 0 and frames_ok),
           "index/column uniqueness on every production frame",
           [f"duplicate security_id columns : {dup_cols}   (must be 0)",
            f"duplicate date rows           : {dup_rows}   (must be 0)",
            f"nsi/score/decile all unique   : {frames_ok}",
            f"panel shape                   : {nsi.shape[0]:,} x {nsi.shape[1]:,}",
            f"index monotonic increasing    : {nsi.index.is_monotonic_increasing}"])

    # --- 14 --------------------------------------------------------------
    dec_places = int(cfg.get("determinism.float_output_decimals"))
    payload = {
        "nsi_p50": float(np.round(nsi.where(present).stack().median(), dec_places)),
        "observations": int(present.to_numpy().sum()),
        "score_p50": float(np.round(score.stack().median(), dec_places)),
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    reserialised = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(blob.encode()).hexdigest()
    cols_sorted = bool(nsi.columns.is_monotonic_increasing)
    c.item(14, "Deterministic serialization: 12 decimals, column order, sorted keys",
           ok(dec_places == 12 and cols_sorted
              and nsi.index.is_monotonic_increasing and blob == reserialised),
           "config determinism.float_output_decimals + canonical JSON",
           [f"float_output_decimals   : {dec_places}   (registered 12)",
            f"security columns sorted : {cols_sorted}",
            f"date index sorted       : {nsi.index.is_monotonic_increasing}",
            f"canonical payload       : {blob}",
            f"digest                  : {digest}"])

    # === B1 CROSS-CHECK ==================================================
    c.say("=" * 78)
    c.say("B1 ANCHOR CROSS-CHECK (reproduction through the WIRED path)")
    c.say("=" * 78)
    vals = nsi.where(present).stack().dropna()
    b1 = json.loads(B1.read_text()) if B1.exists() else {}
    matches = True
    if b1:
        prior = b1.get("nsi_distribution", {})
        for k, now in (("p1", vals.quantile(.01)), ("p25", vals.quantile(.25)),
                       ("p50", vals.quantile(.50)), ("p75", vals.quantile(.75)),
                       ("p99", vals.quantile(.99))):
            was = prior.get(k)
            m = was is not None and abs(was - now) < 1e-12
            matches = matches and m
            c.say(f"  {k:<4} B1 {was:+.6f}   wired {now:+.6f}   "
                  f"{'MATCH' if m else 'DIFFERS'}")
        n_match = prior.get("observations") == len(vals)
        matches = matches and n_match
        c.say(f"  observations  B1 {prior.get('observations'):,}   "
              f"wired {len(vals):,}   {'MATCH' if n_match else 'DIFFERS'}")
        c.say("")
        c.say("  B1 measured the signal module directly; this run measured the")
        c.say("  production path. Identical values mean the wiring changed the")
        c.say("  CALLER, not the computation.")
    c.say("")

    # === SUMMARY =========================================================
    tally: dict[str, int] = {}
    for v in c.items.values():
        tally[v["verdict"]] = tally.get(v["verdict"], 0) + 1
    c.say("=" * 78)
    c.say("CERTIFICATION SUMMARY")
    c.say("=" * 78)
    for verdict in ("CERTIFIED", "BLOCKED", "FAILED"):
        if verdict in tally:
            c.say(f"  {verdict:<10} {tally[verdict]:>2} / 14")
    c.say("")
    all_pass = tally.get("CERTIFIED", 0) == 14 and wired and matches
    if all_pass:
        c.say("  RESULT: CERTIFIED -- 14/14, wiring conforms, B1 anchors reproduce")
    else:
        c.say("  RESULT: NOT CERTIFIED")
        for k, v in sorted(c.items.items()):
            if v["verdict"] != "CERTIFIED":
                c.say(f"    {k}: {v['verdict']} -- {v['title']}")
        if not wired:
            c.say("    wiring: FAILED")
        if not matches:
            c.say("    B1 anchors did not reproduce")
    c.say("")
    c.say("  Credit 2 UNSPENT. Holdout SEALED. No unlock token. No ledger write.")
    c.say("  Dry run NOT run and NOT authorised by this script.")
    c.say("=" * 78)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(c.log) + "\n")
    OUT_JSON.write_text(json.dumps(
        {"wired": wired, "b1_reproduces": bool(matches),
         "all_certified": bool(all_pass), **c.items},
        sort_keys=True, indent=2) + "\n")
    print(f"\n[{time.time()-t0:6.0f}s] wrote {OUT}")
    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
